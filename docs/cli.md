# Terminal: the `chatty` command

Chat with your agents from a terminal on macOS or Linux. `chatty` talks to the Chatty you already run (Railway or local) over HTTPS, the same way the web app does. Your agents, conversations, memory and integrations stay on the server, and nothing runs on your computer. A conversation you start in the terminal shows up in the web app too, and the other way round.

## Install

You need [uv](https://docs.astral.sh/uv/), which brings its own Python. In Chatty, **Settings → Terminal** shows this command with your URL filled in:

```bash
uv tool install "git+https://github.com/WWilson1017/chatty#subdirectory=cli" && chatty login https://your-chatty.example.com
```

To update, run the same `uv tool install` with `--reinstall`.

## Log in

`chatty login <url>` prints a QR code and a short code like `K7PX-2MQR`.

1. Scan the QR with the phone where you're logged in to Chatty, or open the link printed under it. It opens **Settings → Terminal** with the code filled in. If you're logged out, you go through the login page first.
2. Check that the code Chatty shows matches the one in your terminal, then press **Approve**. Approve only a code you can see in your own terminal: anyone can ask to pair, and approving gives that terminal full access to your Chatty.
3. The terminal says it's logged in. The code expires after 10 minutes.

No browser handy? `chatty login <url> --password` asks for your password (and your 2FA code, if you have 2FA turned on).

Both ways give this computer its own device token, saved in `~/.config/chatty/config.json` (readable only by you). The password is never stored. Each paired terminal is listed in **Settings → Terminal**, where **Revoke** logs it out within 15 minutes. `chatty logout` revokes it and forgets the token here.

`chatty` remembers one server. `chatty login <another-url>` replaces it. To use a second server side by side, give it its own file: `CHATTY_CONFIG=~/.config/chatty/work.json chatty login https://work.example.com`, then run `chatty` with the same `CHATTY_CONFIG`.

## Chat

```bash
chatty              # the agent you used last (or a numbered list), in a new conversation
chatty -a tom       # this agent (by slug)
chatty -c           # continue this agent's most recent conversation, on any device
chatty --power      # power mode, remembered
```

- **Enter** sends; **Alt+Enter** starts a new line. Up and down arrows recall what you typed before.
- **Ctrl+C** while a reply is streaming stops *showing* it and gives you the prompt back. The reply still finishes and saves on the server (you'll see it in the web app). Your next message, or any command, waits for it first and says `finishing the previous reply…`. Press Ctrl+C again to give up on it; the server then stops that reply.
- **Ctrl+D** or `/quit` exits, after the same wait.

Tool calls show as one dim line each: `▸ web_search ✓ 1.2s`. `/verbose` adds their arguments and results.

| Command | What it does |
|---|---|
| `/new` | Start a new conversation |
| `/agent [slug]` | Switch agent (numbered list without a slug), in a new conversation |
| `/resume` | Pick one of the 10 most recently updated conversations and show its last messages |
| `/model` | Show this agent's model and pick another from your configured providers. It changes the agent for the web too. `/model auto` goes back to automatic. |
| `/mode normal \| power \| read-only` | Change the tool mode (remembered) |
| `/attach <file>…` | Attach up to 5 files (csv, xlsx, md, txt, pdf, docx; 10 MB each) to your next message. `/attach` alone clears them. The prompt shows `📎N`. |
| `/verbose` | Show tool arguments and results (remembered) |
| `/help`, `/quit` | |

## Modes and approvals

The modes are the web app's:

- **normal**: before a tool that changes something (sends an email, creates an event, writes a file), the reply shows the tool and its arguments and asks `Allow? [y/N]`. **y** runs it and the agent carries on; anything else doesn't run it.
- **power** (`⚡` in the prompt): those tools run without asking.
- **read-only**: the agent gets no tools that change things.

Power mode only skips the question. The server's own limits still apply: per-integration read-only settings, the write budget per turn, the hourly limit, and Claude Code's approval for full-access jobs.

If you pressed Ctrl+C on a reply that then asked to run a tool, it is not run. The terminal tells you when it catches up.

## Not in this version

Replies show as plain text, without markdown formatting. There are no notifications in the terminal and no todo capture. The terminal can't run tools on your own computer (that's what the [Claude Code connector](claude-code-connector.md) is for). Windows isn't supported. These are tracked in issue #170.
