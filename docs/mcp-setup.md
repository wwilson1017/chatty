# MCP servers

Connect [MCP](https://modelcontextprotocol.io) servers to Chatty. Every agent gets the server's tools; nothing is per agent. Two kinds: **hosted servers** you reach over https, and **command servers** (`npx …`, `uvx …`) that run on the [Chatty computer](#command-servers-on-the-computer).

## Adding a hosted server

Settings → Integrations → **MCP servers** → **Add server** → kind **Hosted server (https)**.

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

Tool names look like `mcp_<server>__<tool>`.

## Command servers (on the computer)

Most MCP servers are published as programs to run locally (`npx -y @modelcontextprotocol/server-everything`, `uvx mcp-server-fetch`). Chatty never runs them on its own server. With the **Computer** integration set up and turned on, pick **Run on the computer** when adding a server and give it the command plus any environment variables it needs (an API key, typically). The computer starts the program behind its MCP bridge, and to Chatty it is one more remote server at `<computer>/mcp/<id>/mcp` — the only address on a private network Chatty will talk MCP to, and only that exact origin.

- **Keys.** Each value is typed into a masked field, stored encrypted in Chatty, and sent to the computer as an environment variable each time the server starts; the computer keeps it in memory and never writes it to disk. It is never shown again, and never appears in a route response or a log (a start failure's log tail is shown with the values blanked).
- **What Chatty cannot promise.** A command server can print or save its own environment, and any process on the computer — another command server, an agent's shell, the helper — can read it. **Prefer a hosted server**, whose key never leaves Chatty. For a command server use a key that is **narrow, read-only and revocable**.
- **Lifecycle.** Processes live only as long as the computer. After the computer restarts, the next call starts the server again and retries only if it failed before the tool call itself; a tool call whose outcome is unknown is reported as such, never replayed. Disabling the server, the MCP integration or the computer stops the process; removing the server stops it and deletes its values. The card's **Restart** starts it fresh, and its status line says whether it is running on the computer right now.
- **Permissions** are the same as for hosted servers: every tool is a write until you mark it read-only, background turns need **Allow writes in background turns**, and calls are refused with a plain message while the computer is off, not set up or unreachable.
- The command is split like a shell would (`shlex`), runs as the computer's user from `/workspace/shared`, with `PATH`, `HOME` and `LANG` set.
