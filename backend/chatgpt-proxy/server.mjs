/**
 * ChatGPT Proxy Sidecar
 *
 * A minimal HTTP server that accepts OpenAI-format chat completion requests
 * and forwards them through pi-ai to ChatGPT's backend API using a ChatGPT
 * OAuth token (from the Codex CLI).
 *
 * Endpoints:
 *   POST /v1/chat/completions  — proxied chat completion (streaming SSE)
 *   POST /v1/validate          — validate a ChatGPT token
 *   GET  /health               — health check
 *
 * The Python backend calls this instead of chatgpt.com directly.
 */

import { createServer } from "node:http";
import { streamSimple, getModel } from "@mariozechner/pi-ai";

const PORT = parseInt(process.env.CHATGPT_PROXY_PORT || "9877", 10);

function parseBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString()));
      } catch (e) {
        reject(e);
      }
    });
    req.on("error", reject);
  });
}

// Codex-compatible model IDs (standard GPT models aren't supported with ChatGPT tokens)
const CODEX_MODELS = ["gpt-5.4", "gpt-5.3-codex", "gpt-5.3-codex-spark", "gpt-5.2-codex"];
const DEFAULT_CODEX_MODEL = "gpt-5.4";

/**
 * Map standard model names to Codex equivalents.
 */
function resolveModelId(requestedModel) {
  if (CODEX_MODELS.includes(requestedModel)) return requestedModel;
  // Map common model names to the default codex model
  return DEFAULT_CODEX_MODEL;
}

/**
 * Build a pi-ai model object for the ChatGPT backend.
 */
function buildCodexModel(modelId) {
  const base = getModel("openai", "gpt-4o");
  return {
    ...base,
    id: modelId,
    provider: "openai-codex",
    api: "openai-codex-responses",
    baseUrl: "https://chatgpt.com/backend-api",
  };
}

/**
 * Convert OpenAI messages format to pi-ai messages format.
 */
function convertMessages(openaiMessages) {
  return openaiMessages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => ({
      role: m.role,
      content:
        typeof m.content === "string"
          ? [{ type: "text", text: m.content }]
          : m.content,
    }));
}

/**
 * Handle POST /v1/chat/completions
 * Accepts standard OpenAI chat completion request, streams back SSE.
 */
async function handleChatCompletions(req, res, body) {
  const token = (req.headers.authorization || "").replace("Bearer ", "");
  if (!token) {
    res.writeHead(401, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Missing Authorization header" }));
    return;
  }

  const modelId = resolveModelId(body.model || "gpt-4o");
  const model = buildCodexModel(modelId);

  const systemPrompt =
    body.messages?.find((m) => m.role === "system")?.content ||
    "You are a helpful assistant.";
  const messages = convertMessages(
    body.messages?.filter((m) => m.role !== "system") || [],
  );

  // Stream SSE response
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });

  try {
    const stream = streamSimple(
      model,
      {
        systemPrompt,
        messages,
      },
      {
        apiKey: token,
        maxTokens: body.max_tokens || 16384,
        temperature: body.temperature,
      },
    );

    for await (const event of stream) {
      if (event.type === "text_delta") {
        const chunk = {
          choices: [
            {
              index: 0,
              delta: { content: event.delta },
              finish_reason: null,
            },
          ],
        };
        res.write(`data: ${JSON.stringify(chunk)}\n\n`);
      } else if (event.type === "done") {
        const chunk = {
          choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
        };
        res.write(`data: ${JSON.stringify(chunk)}\n\n`);
        res.write("data: [DONE]\n\n");
      }
    }
  } catch (err) {
    const errorChunk = {
      error: { message: err.message || "Stream error" },
    };
    res.write(`data: ${JSON.stringify(errorChunk)}\n\n`);
    res.write("data: [DONE]\n\n");
  }

  res.end();
}

/**
 * Handle POST /v1/validate
 * Quick validation that the token works by making a minimal request.
 */
async function handleValidate(req, res, body) {
  const token = body.token;
  if (!token) {
    res.writeHead(400, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ valid: false, error: "No token provided" }));
    return;
  }

  const model = buildCodexModel(DEFAULT_CODEX_MODEL);

  try {
    const stream = streamSimple(
      model,
      {
        systemPrompt: "You are a helpful assistant.",
        messages: [
          { role: "user", content: [{ type: "text", text: "hi" }] },
        ],
      },
      { apiKey: token, maxTokens: 1, transport: "sse" },
    );

    // Consume just enough to confirm it works
    for await (const event of stream) {
      if (event.type === "text_delta" || event.type === "done") {
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ valid: true }));
        return;
      }
    }

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ valid: true }));
  } catch (err) {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({ valid: false, error: err.message || "Validation failed" }),
    );
  }
}

const server = createServer(async (req, res) => {
  // CORS for local dev
  res.setHeader("Access-Control-Allow-Origin", "*");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  if (req.method === "GET" && req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", service: "chatgpt-proxy" }));
    return;
  }

  if (req.method !== "POST") {
    res.writeHead(405, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "Method not allowed" }));
    return;
  }

  try {
    const body = await parseBody(req);

    if (req.url === "/v1/chat/completions") {
      await handleChatCompletions(req, res, body);
    } else if (req.url === "/v1/validate") {
      await handleValidate(req, res, body);
    } else {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Not found" }));
    }
  } catch (err) {
    console.error("Request error:", err);
    if (!res.headersSent) {
      res.writeHead(500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: err.message || "Internal error" }));
    }
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`ChatGPT proxy sidecar listening on http://127.0.0.1:${PORT}`);
});
