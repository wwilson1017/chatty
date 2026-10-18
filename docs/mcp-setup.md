# MCP servers

Connect remote [MCP](https://modelcontextprotocol.io) servers to Chatty. Every agent gets the server's tools; nothing is per agent.

## Adding a server

Settings → Integrations → **MCP servers** → **Add server**.

- **URL** — the server's streamable-HTTP endpoint (for example `https://api.githubcopilot.com/mcp/`). It must be `https` on a public host; private, loopback and link-local addresses are refused, and Chatty connects only to the address it validated.
- **Header** and **API key** — the key is sent in that header on every call. `Authorization` gets `Bearer ` added unless your key already names a scheme. The key is stored encrypted and never shown again. Leave the key empty for a server that uses OAuth.

Connecting fetches the server's tool list. It is cached, refreshed from the card's **Test & refresh tools** button and every 6 hours; agents never fetch it themselves.

## OAuth sign-in

A server added without a key that answers 401 is saved with no tools and a **Sign in with OAuth** button. Signing in follows the MCP authorization spec: Chatty reads the server's protected-resource metadata, the authorization server's metadata and registers itself as a client, then opens the provider's consent page in a popup — the same flow as the Google card. If the authorization server has no dynamic client registration, create an OAuth client there with the redirect URI shown under the Google card's "bring your own credentials" (by default `https://auth.mechatty.com/callback`) and paste its id and secret with **Use my own OAuth client** before signing in.

- Tokens are stored encrypted per server and sent only to that server. They are refreshed a minute before they expire; a rotated refresh token replaces the old one. When the server gives no refresh token, or refuses the refresh, the card says **Sign in again**.
- A call refused with 401 before the tool ran gets one refreshed token and one retry. A tool that failed while running is never retried.
- Every metadata, registration and token URL is held to the same https-and-public-host rule as the server URL.

## Permissions

- **Every tool is a write tool** until you mark it read-only on the card. In chat that means a confirmation card before it runs (normal mode). A server's own `readOnlyHint` is shown as "server says read-only" — a suggestion, nothing more.
- **Background turns** (scheduled actions, heartbeats, reminders) run without anyone to confirm, so a server's write tools are refused there unless you tick **Allow writes in background turns** for that server. Read-only tools run anywhere.
- Changes on the card apply at the next call, even to tools an agent already loaded. A tool that became stricter since it was loaded (switched to a write, turned off) is refused with "this tool's permissions changed; ask again" and reloaded on the next turn.
- Tool results are wrapped as untrusted content, like email and web pages.

Tool names look like `mcp_<server>__<tool>`. Command servers that run on the Chatty computer come in a later release.
