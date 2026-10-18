# MCP servers

Connect remote [MCP](https://modelcontextprotocol.io) servers to Chatty. Every agent gets the server's tools; nothing is per agent.

## Adding a server

Settings → Integrations → **MCP servers** → **Add server**.

- **URL** — the server's streamable-HTTP endpoint (for example `https://api.githubcopilot.com/mcp/`). It must be `https` on a public host; private, loopback and link-local addresses are refused, and Chatty connects only to the address it validated.
- **Header** and **API key** — the key is sent in that header on every call. `Authorization` gets `Bearer ` added unless your key already names a scheme. The key is stored encrypted and never shown again.

Connecting fetches the server's tool list. It is cached, refreshed from the card's **Test & refresh tools** button and every 6 hours; agents never fetch it themselves.

## Permissions

- **Every tool is a write tool** until you mark it read-only on the card. In chat that means a confirmation card before it runs (normal mode). A server's own `readOnlyHint` is shown as "server says read-only" — a suggestion, nothing more.
- **Background turns** (scheduled actions, heartbeats, reminders) run without anyone to confirm, so a server's write tools are refused there unless you tick **Allow writes in background turns** for that server. Read-only tools run anywhere.
- Changes on the card apply at the next call, even to tools an agent already loaded. A tool that became stricter since it was loaded (switched to a write, turned off) is refused with "this tool's permissions changed; ask again" and reloaded on the next turn.
- Tool results are wrapped as untrusted content, like email and web pages.

Tool names look like `mcp_<server>__<tool>`. Servers with OAuth sign-in and command servers that run on the Chatty computer come in later releases.
