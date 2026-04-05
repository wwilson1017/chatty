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
  makeCacheableSignalKeyStore,
} from '@whiskeysockets/baileys';
import express from 'express';
import QRCode from 'qrcode';
import pino from 'pino';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

const logger = pino({ level: process.env.LOG_LEVEL || 'info' });

const WEBHOOK_URL =
  process.env.WEBHOOK_URL ||
  'http://localhost:8000/api/messaging/whatsapp/webhook';
const API_KEY = process.env.API_KEY || '';
const PORT = parseInt(process.env.PORT || '3001', 10);
const SESSIONS_DIR = process.env.SESSIONS_DIR || './sessions';

// Message dedup: TTL in ms and max entries
const DEDUP_TTL_MS = 20 * 60 * 1000; // 20 minutes
const DEDUP_MAX_ENTRIES = 5000;

// Upsert append-window: only forward "append" messages arriving within
// this many milliseconds of connection time.
const APPEND_WINDOW_MS = 60_000;

// Max reconnect attempts before giving up
const MAX_RECONNECT_ATTEMPTS = 12;

// In-memory session map: sessionId → { sock, status, qr, jid, lidToJid, connectedAtMs }
const sessions = new Map();

// Global message dedup cache: messageId → receive timestamp
const seenMessages = new Map();

function isDuplicate(messageId) {
  if (!messageId) return false;
  const now = Date.now();
  // Lazy eviction when cache exceeds max entries
  if (seenMessages.size > DEDUP_MAX_ENTRIES) {
    for (const [id, ts] of seenMessages) {
      if (now - ts > DEDUP_TTL_MS) seenMessages.delete(id);
    }
  }
  if (seenMessages.has(messageId)) return true;
  seenMessages.set(messageId, now);
  return false;
}

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
  if (attempts >= MAX_RECONNECT_ATTEMPTS) return -1; // signal: stop retrying
  reconnectAttempts.set(sessionId, attempts + 1);
  const base = Math.min(1000 * 2 ** attempts, MAX_RECONNECT_DELAY_MS);
  // Add +/-25% jitter to prevent synchronized reconnects
  const jitter = base * (0.75 + Math.random() * 0.5);
  return Math.round(jitter);
}

function resetReconnectAttempts(sessionId) {
  reconnectAttempts.delete(sessionId);
}

/**
 * Strip device suffix (:N) from JIDs for identity comparison.
 * e.g. "1234567890:3@s.whatsapp.net" -> "1234567890@s.whatsapp.net"
 */
function normalizeJid(jid) {
  return jid ? jid.replace(/:\d+(?=@)/, '') : jid;
}

/** Regex to identify LID-format JIDs (both @lid and @hosted.lid). */
const LID_REGEX = /@(lid|hosted\.lid)$/i;

/** JID suffixes we never forward to the webhook. */
const SKIP_JID_SUFFIXES = ['@g.us', '@broadcast', '@status'];

/**
 * Extract text content from a Baileys message object.
 * Covers: conversation, extendedText, image/video/document captions,
 * ephemeral messages, and view-once messages.
 */
function extractTextContent(message) {
  if (!message) return '';

  // Direct conversation text
  if (message.conversation) return message.conversation;

  // Extended text
  if (message.extendedTextMessage?.text) return message.extendedTextMessage.text;

  // Image / video / document captions
  if (message.imageMessage?.caption) return message.imageMessage.caption;
  if (message.videoMessage?.caption) return message.videoMessage.caption;
  if (message.documentMessage?.caption) return message.documentMessage.caption;
  if (message.documentWithCaptionMessage?.message)
    return extractTextContent(message.documentWithCaptionMessage.message);

  // Ephemeral wrapper (disappearing messages)
  const ephemeral = message.ephemeralMessage?.message;
  if (ephemeral) return extractTextContent(ephemeral);

  // View-once wrappers
  const viewOnce =
    message.viewOnceMessage?.message ||
    message.viewOnceMessageV2?.message ||
    message.viewOnceMessageV2Extension?.message;
  if (viewOnce) return extractTextContent(viewOnce);

  return '';
}

// -----------------------------------------------------------------------
// Baileys session helpers
// -----------------------------------------------------------------------

async function startSession(sessionId) {
  validateSessionId(sessionId);
  const sessionDir = path.join(SESSIONS_DIR, sessionId);
  fs.mkdirSync(sessionDir, { recursive: true });

  // --- Credential backup/restore ---
  const credsPath = path.join(sessionDir, 'creds.json');
  const credsBakPath = path.join(sessionDir, 'creds.json.bak');

  // On startup: if creds.json is missing or corrupt, try restoring from backup
  if (fs.existsSync(credsPath)) {
    try {
      JSON.parse(fs.readFileSync(credsPath, 'utf8'));
    } catch {
      logger.warn({ sessionId }, 'creds.json is corrupt — attempting restore from backup');
      if (fs.existsSync(credsBakPath)) {
        fs.copyFileSync(credsBakPath, credsPath);
        logger.info({ sessionId }, 'Restored creds.json from backup');
      }
    }
  } else if (fs.existsSync(credsBakPath)) {
    logger.warn({ sessionId }, 'creds.json missing — restoring from backup');
    fs.copyFileSync(credsBakPath, credsPath);
  }

  const { state, saveCreds: _rawSaveCreds } = await useMultiFileAuthState(sessionDir);
  const { version } = await fetchLatestBaileysVersion();

  // Serialized credential save queue to avoid race conditions
  let saveCredsChain = Promise.resolve();
  const saveCreds = () => {
    saveCredsChain = saveCredsChain.then(async () => {
      try {
        // Back up current creds.json before saving (only if it's valid JSON)
        if (fs.existsSync(credsPath)) {
          try {
            JSON.parse(fs.readFileSync(credsPath, 'utf8'));
            fs.copyFileSync(credsPath, credsBakPath);
          } catch {
            // Current creds.json is not valid JSON — skip backup
          }
        }
        await _rawSaveCreds();
      } catch (err) {
        logger.error({ err, sessionId }, 'Failed to save credentials');
      }
    });
    return saveCredsChain;
  };

  const entry = {
    sock: null,
    status: 'connecting',
    qr: null,
    jid: null,
    lidToJid: new Map(),   // per-session LID->JID mapping
    connectedAtMs: 0,      // track connection time for append window
  };
  sessions.set(sessionId, entry);

  // Message cache for retry decryption (required by Baileys multi-device)
  const msgCache = new Map();

  const sockLogger = pino({ level: 'warn' });
  const sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, sockLogger),
    },
    logger: sockLogger,
    browser: ['Chatty', 'Desktop', '1.0'],
    printQRInTerminal: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
    getMessage: async (key) => {
      const cached = msgCache.get(key.id);
      return cached?.message || undefined;
    },
  });

  entry.sock = sock;

  // Attach WebSocket error handler to prevent unhandled crashes
  if (sock.ws) {
    sock.ws.on('error', (err) => {
      logger.error({ err, sessionId }, 'WebSocket error');
    });
  }

  // Persist credentials whenever they change (serialized)
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
      entry.connectedAtMs = Date.now();
      entry.jid = sock.user?.id || null;
      resetReconnectAttempts(sessionId);
      logger.info({ sessionId, jid: entry.jid }, 'Session connected');
    }

    if (connection === 'close') {
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;

      // Non-retryable conditions
      const isLoggedOut = statusCode === DisconnectReason.loggedOut;
      const isConflict = statusCode === DisconnectReason.connectionReplaced;
      const shouldReconnect = !isLoggedOut && !isConflict;

      logger.info(
        { sessionId, statusCode, shouldReconnect },
        'Session disconnected',
      );

      if (shouldReconnect) {
        // For restart-required (515), reconnect immediately
        if (statusCode === DisconnectReason.restartRequired) {
          logger.info({ sessionId }, 'Restart required — reconnecting immediately');
          startSession(sessionId).catch((err) =>
            logger.error({ err, sessionId }, 'Restart reconnect failed'),
          );
          return;
        }

        const delay = getReconnectDelay(sessionId);
        if (delay < 0) {
          logger.error({ sessionId }, 'Max reconnect attempts reached — giving up');
          entry.status = 'disconnected';
          entry.sock = null;
        } else {
          logger.info({ sessionId, delay }, 'Reconnecting after delay');
          setTimeout(() => {
            startSession(sessionId).catch((err) =>
              logger.error({ err, sessionId }, 'Reconnect failed'),
            );
          }, delay);
        }
      } else {
        entry.status = 'disconnected';
        entry.sock = null;
        if (isConflict) {
          logger.warn({ sessionId }, 'Session replaced by another device — not retrying');
        }
      }
    }
  });

  // Forward incoming messages to webhook
  sock.ev.on('messages.upsert', async ({ messages: msgs, type }) => {
    // Only process "notify" events. Allow "append" only within the first
    // 60 seconds after connection (catches messages missed while offline).
    if (type !== 'notify') {
      if (type === 'append' && entry.connectedAtMs &&
          (Date.now() - entry.connectedAtMs) <= APPEND_WINDOW_MS) {
        // Allow — these are recent messages that arrived while reconnecting
      } else {
        return;
      }
    }

    logger.info({ sessionId, count: msgs.length, type }, 'messages.upsert event');

    for (const msg of msgs) {
      // Cache for getMessage retries
      if (msg.key.id && msg.message) {
        msgCache.set(msg.key.id, msg);
        if (msgCache.size > 500) {
          const firstKey = msgCache.keys().next().value;
          msgCache.delete(firstKey);
        }
      }

      if (msg.key.fromMe) continue;

      const remoteJid = msg.key.remoteJid || '';

      // Skip groups, broadcast, and status JIDs
      if (SKIP_JID_SUFFIXES.some((s) => remoteJid.endsWith(s))) continue;

      // Dedup check
      if (msg.key.id && isDuplicate(msg.key.id)) {
        logger.debug({ sessionId, messageId: msg.key.id }, 'Duplicate message — skipping');
        continue;
      }

      // Normalize JID (strip device suffix)
      const normalizedJid = normalizeJid(remoteJid);

      // Extract phone number or LID as the sender identifier
      const phone = normalizedJid.includes('@')
        ? normalizedJid.split('@')[0]
        : normalizedJid;

      // Cache LID->JID mapping (handles both @lid and @hosted.lid)
      if (LID_REGEX.test(remoteJid)) {
        entry.lidToJid.set(phone, remoteJid);
        logger.info({ phone, jid: remoteJid }, 'Cached LID->JID mapping');
      }

      // Also try to get the real phone from the participant field (for LID messages)
      const senderPhone = msg.key.participant
        ? normalizeJid(msg.key.participant).split('@')[0]
        : phone;

      // Extended text extraction (conversation, captions, ephemeral, view-once)
      const text = extractTextContent(msg.message);
      if (!text) continue;

      logger.info(
        { sessionId, phone, senderPhone, remoteJid, text: text.substring(0, 50) },
        'Forwarding message to webhook',
      );

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
  // Timing-safe comparison to prevent side-channel attacks
  const a = Buffer.from(provided);
  const b = Buffer.from(API_KEY);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
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

  // Try LID format first (if the phone is cached), then fall back to standard JID
  const cleanPhone = phone.replace(/^\+/, '');
  const jid = entry.lidToJid.has(cleanPhone)
    ? entry.lidToJid.get(cleanPhone)
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
  reconnectAttempts.delete(sessionId);

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
    const credsBakPath = path.join(SESSIONS_DIR, sessionId, 'creds.json.bak');
    if (!fs.existsSync(credsPath) && !fs.existsSync(credsBakPath)) continue;

    logger.info({ sessionId }, 'Reconnecting saved session');
    try {
      await startSession(sessionId);
    } catch (err) {
      logger.error({ err, sessionId }, 'Failed to reconnect session');
    }
  }
}

// -----------------------------------------------------------------------
// Global error handling — crypto rejection recovery
// -----------------------------------------------------------------------

process.on('unhandledRejection', (err) => {
  const message = String(err?.message || err || '');
  const stack = String(err?.stack || '');

  const isCryptoError =
    message.includes('unsupported state or unable to authenticate data') ||
    (message.includes('bad mac') &&
      (stack.includes('baileys') ||
       stack.includes('noise-handler') ||
       stack.includes('aesdecryptgcm')));

  if (isCryptoError) {
    logger.error({ err }, 'Baileys crypto error — forcing reconnect for all sessions');
    for (const [sessionId, entry] of sessions) {
      if (entry.sock) {
        try { entry.sock.end(undefined); } catch { /* ignore */ }
        entry.sock = null;
        entry.status = 'reconnecting';
        startSession(sessionId).catch((reconnectErr) =>
          logger.error({ err: reconnectErr, sessionId }, 'Crypto recovery reconnect failed'),
        );
      }
    }
  } else {
    logger.error({ err }, 'Unhandled rejection');
  }
});

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
