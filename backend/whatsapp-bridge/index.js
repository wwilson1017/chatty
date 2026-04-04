/**
 * WhatsApp Bridge — Baileys sidecar for CAKE OS / Chatty.
 *
 * Thin Express server that manages WhatsApp Web sessions via Baileys.
 * Each session gets its own multi-file auth state on disk.  Incoming
 * messages are forwarded to the CAKE/Chatty webhook; outbound messages
 * are sent via REST.
 *
 * Environment:
 *   WEBHOOK_URL   – where to POST inbound messages  (default: http://localhost:8000/api/messaging/whatsapp/webhook)
 *   API_KEY       – shared secret for X-Api-Key header auth (optional)
 *   PORT          – listen port (default: 3001)
 *   SESSIONS_DIR  – directory for per-session auth state (default: ./sessions)
 */

import makeWASocket, {
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} from '@whiskeysockets/baileys';
import express from 'express';
import QRCode from 'qrcode';
import pino from 'pino';
import fs from 'fs';
import path from 'path';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

const WEBHOOK_URL =
  process.env.WEBHOOK_URL ||
  'http://localhost:8000/api/messaging/whatsapp/webhook';
const API_KEY = process.env.API_KEY || '';
const PORT = parseInt(process.env.PORT || '3001', 10);
const SESSIONS_DIR = process.env.SESSIONS_DIR || './sessions';

// In-memory session map: sessionId → { sock, status, qr, jid }
const sessions = new Map();

// LID → full JID mapping (WhatsApp multi-device uses LIDs instead of phone JIDs)
const lidToJid = new Map();

// -----------------------------------------------------------------------
// Validation & helpers
// -----------------------------------------------------------------------

const SAFE_SESSION_ID = /^[a-zA-Z0-9_-]+$/;

function validateSessionId(sessionId) {
  if (!sessionId || !SAFE_SESSION_ID.test(sessionId)) {
    throw new Error(`Invalid session ID: ${sessionId}`);
  }
}

// Reconnect backoff state per session
const reconnectAttempts = new Map();
const MAX_RECONNECT_DELAY_MS = 60_000;

function getReconnectDelay(sessionId) {
  const attempts = reconnectAttempts.get(sessionId) || 0;
  reconnectAttempts.set(sessionId, attempts + 1);
  return Math.min(1000 * 2 ** attempts, MAX_RECONNECT_DELAY_MS);
}

function resetReconnectAttempts(sessionId) {
  reconnectAttempts.delete(sessionId);
}

// -----------------------------------------------------------------------
// Baileys session helpers
// -----------------------------------------------------------------------

async function startSession(sessionId) {
  validateSessionId(sessionId);
  const sessionDir = path.join(SESSIONS_DIR, sessionId);
  fs.mkdirSync(sessionDir, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(sessionDir);
  const { version } = await fetchLatestBaileysVersion();

  const entry = { sock: null, status: 'connecting', qr: null, jid: null };
  sessions.set(sessionId, entry);

  // Message cache for retry decryption (required by Baileys multi-device)
  const msgCache = new Map();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: 'warn' }),
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: true,
    getMessage: async (key) => {
      const cached = msgCache.get(key.id);
      return cached?.message || undefined;
    },
  });

  entry.sock = sock;

  // Persist credentials whenever they change
  sock.ev.on('creds.update', saveCreds);

  // Connection lifecycle
  sock.ev.on('connection.update', (update) => {
    const { connection, lastDisconnect, qr: qrString } = update;

    if (qrString) {
      entry.qr = qrString;
      entry.status = 'scan_qr';
      logger.info({ sessionId }, 'QR code available — waiting for scan');
    }

    if (connection === 'open') {
      entry.status = 'connected';
      entry.qr = null;
      entry.jid = sock.user?.id || null;
      resetReconnectAttempts(sessionId);
      logger.info({ sessionId, jid: entry.jid }, 'Session connected');
    }

    if (connection === 'close') {
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect =
        statusCode !== DisconnectReason.loggedOut;

      logger.info(
        { sessionId, statusCode, shouldReconnect },
        'Session disconnected',
      );

      if (shouldReconnect) {
        const delay = getReconnectDelay(sessionId);
        logger.info({ sessionId, delay }, 'Reconnecting after delay');
        setTimeout(() => {
          startSession(sessionId).catch((err) =>
            logger.error({ err, sessionId }, 'Reconnect failed'),
          );
        }, delay);
      } else {
        entry.status = 'disconnected';
        entry.sock = null;
      }
    }
  });

  // Forward incoming messages to webhook
  sock.ev.on('messages.upsert', async ({ messages: msgs, type }) => {
    logger.info({ sessionId, count: msgs.length, type }, 'messages.upsert event');
    for (const msg of msgs) {
      // Cache for getMessage retries
      if (msg.key.id && msg.message) {
        msgCache.set(msg.key.id, msg);
        // Evict old entries to prevent unbounded growth
        if (msgCache.size > 500) {
          const firstKey = msgCache.keys().next().value;
          msgCache.delete(firstKey);
        }
      }
      logger.info({ sessionId, fromMe: msg.key.fromMe, remoteJid: msg.key.remoteJid, hasMessage: !!msg.message }, 'Processing message');
      if (msg.key.fromMe) continue;

      const remoteJid = msg.key.remoteJid || '';
      // Handle personal chats — both traditional (@s.whatsapp.net) and
      // linked identity (@lid) formats. Skip groups (@g.us).
      if (remoteJid.endsWith('@g.us')) continue;

      // Extract phone number or LID as the sender identifier
      const phone = remoteJid.includes('@')
        ? remoteJid.split('@')[0]
        : remoteJid;

      // Cache the LID→JID mapping so we can reply using the correct JID
      if (remoteJid.endsWith('@lid')) {
        lidToJid.set(phone, remoteJid);
        logger.info({ phone, jid: remoteJid }, 'Cached LID→JID mapping');
      }

      // Also try to get the real phone from the participant field (for LID messages)
      const senderPhone = msg.key.participant
        ? msg.key.participant.split('@')[0]
        : phone;
      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        '';
      if (!text) continue;

      logger.info({ sessionId, phone, senderPhone, remoteJid, text: text.substring(0, 50) }, 'Forwarding message to webhook');

      const payload = {
        session: sessionId,
        phone: senderPhone,
        text,
        sender_name: msg.pushName || '',
        message_id: msg.key.id,
      };

      try {
        const headers = { 'Content-Type': 'application/json' };
        if (API_KEY) headers['X-Api-Key'] = API_KEY;

        await fetch(WEBHOOK_URL, {
          method: 'POST',
          headers,
          body: JSON.stringify(payload),
        });
      } catch (err) {
        logger.error({ err, sessionId, phone }, 'Webhook delivery failed');
      }
    }
  });

  return entry;
}

// -----------------------------------------------------------------------
// Express app
// -----------------------------------------------------------------------

const app = express();
app.use(express.json());

// API key middleware (skip if no API_KEY configured)
app.use((req, res, next) => {
  if (!API_KEY) return next();
  const provided = req.headers['x-api-key'] || '';
  if (provided !== API_KEY) {
    return res.status(401).json({ error: 'Invalid API key' });
  }
  next();
});

// POST /sessions — Create and start a new session
app.post('/sessions', async (req, res) => {
  const sessionId = req.body.session;
  if (!sessionId) {
    return res.status(400).json({ error: 'Missing "session" in body' });
  }
  if (!SAFE_SESSION_ID.test(sessionId)) {
    return res.status(400).json({ error: 'Invalid session ID format' });
  }
  if (sessions.has(sessionId)) {
    const existing = sessions.get(sessionId);
    return res.json({ status: existing.status, jid: existing.jid });
  }

  try {
    await startSession(sessionId);
    res.json({ status: 'starting' });
  } catch (err) {
    logger.error({ err, sessionId }, 'Failed to start session');
    res.status(500).json({ error: 'Failed to start session' });
  }
});

// GET /sessions — List all sessions
app.get('/sessions', (_req, res) => {
  const list = [];
  for (const [id, entry] of sessions) {
    list.push({
      session: id,
      status: entry.status,
      jid: entry.jid,
    });
  }
  res.json(list);
});

// GET /sessions/:id — Get session status
app.get('/sessions/:id', (req, res) => {
  if (!SAFE_SESSION_ID.test(req.params.id)) {
    return res.status(400).json({ error: 'Invalid session ID format' });
  }
  const entry = sessions.get(req.params.id);
  if (!entry) {
    return res.status(404).json({ error: 'Session not found' });
  }
  res.json({
    status: entry.status,
    jid: entry.jid,
    qr_available: !!entry.qr,
  });
});

// GET /sessions/:id/qr — Get QR code as PNG
app.get('/sessions/:id/qr', async (req, res) => {
  if (!SAFE_SESSION_ID.test(req.params.id)) {
    return res.status(400).json({ error: 'Invalid session ID format' });
  }
  const entry = sessions.get(req.params.id);
  if (!entry || !entry.qr) {
    return res.status(404).json({ error: 'QR not available' });
  }
  try {
    const png = await QRCode.toBuffer(entry.qr, { type: 'png', width: 300 });
    res.set('Content-Type', 'image/png');
    res.send(png);
  } catch (err) {
    logger.error({ err }, 'QR render failed');
    res.status(500).json({ error: 'QR render failed' });
  }
});

// POST /sessions/:id/send — Send a text message
app.post('/sessions/:id/send', async (req, res) => {
  if (!SAFE_SESSION_ID.test(req.params.id)) {
    return res.status(400).json({ error: 'Invalid session ID format' });
  }
  const entry = sessions.get(req.params.id);
  if (!entry || !entry.sock) {
    return res.status(404).json({ error: 'Session not found or not connected' });
  }
  if (entry.status !== 'connected') {
    return res.status(400).json({ error: `Session not connected (status: ${entry.status})` });
  }

  const { phone, text } = req.body;
  if (!phone || !text) {
    return res.status(400).json({ error: 'Missing "phone" or "text"' });
  }

  // Try LID format first (if the phone looks like a LID), then fall back to standard JID
  const cleanPhone = phone.replace(/^\+/, '');
  const jid = lidToJid.has(cleanPhone)
    ? lidToJid.get(cleanPhone)
    : `${cleanPhone}@s.whatsapp.net`;
  logger.info({ phone: cleanPhone, jid }, 'Sending message');
  try {
    const result = await entry.sock.sendMessage(jid, { text });
    res.json({ ok: true, id: result?.key?.id });
  } catch (err) {
    logger.error({ err, phone }, 'Send failed');
    res.status(500).json({ error: 'Send failed' });
  }
});

// DELETE /sessions/:id — Logout and delete session
app.delete('/sessions/:id', async (req, res) => {
  const sessionId = req.params.id;
  if (!SAFE_SESSION_ID.test(sessionId)) {
    return res.status(400).json({ error: 'Invalid session ID format' });
  }
  const entry = sessions.get(sessionId);

  if (entry?.sock) {
    try {
      await entry.sock.logout();
    } catch {
      // Already disconnected — ignore
    }
    entry.sock = null;
  }
  sessions.delete(sessionId);

  // Remove auth state from disk
  const sessionDir = path.join(SESSIONS_DIR, sessionId);
  try {
    fs.rmSync(sessionDir, { recursive: true, force: true });
  } catch {
    // Directory may not exist — ignore
  }

  res.json({ ok: true });
});

// -----------------------------------------------------------------------
// Startup: reconnect saved sessions
// -----------------------------------------------------------------------

async function reconnectSavedSessions() {
  if (!fs.existsSync(SESSIONS_DIR)) return;

  const dirs = fs
    .readdirSync(SESSIONS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory())
    .map((d) => d.name);

  for (const sessionId of dirs) {
    const credsPath = path.join(SESSIONS_DIR, sessionId, 'creds.json');
    if (!fs.existsSync(credsPath)) continue;

    logger.info({ sessionId }, 'Reconnecting saved session');
    try {
      await startSession(sessionId);
    } catch (err) {
      logger.error({ err, sessionId }, 'Failed to reconnect session');
    }
  }
}

// -----------------------------------------------------------------------
// Boot
// -----------------------------------------------------------------------

await reconnectSavedSessions();

if (!API_KEY) {
  logger.warn(
    'No API_KEY set — sidecar is running without authentication. ' +
    'Set the API_KEY environment variable in production.',
  );
}

app.listen(PORT, () => {
  logger.info({ port: PORT, webhook: WEBHOOK_URL }, 'WhatsApp bridge started');
});
