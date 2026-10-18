# chatty

Chat with your [Chatty](https://github.com/WWilson1017/chatty) agents from a terminal on macOS or Linux. It's a thin client of your running Chatty (Railway or local): your agents, conversations and tools all stay on the server.

```bash
uv tool install "git+https://github.com/WWilson1017/chatty#subdirectory=cli"
chatty login https://your-chatty.example.com   # scan the QR with your phone, approve
chatty                                         # pick an agent and chat
# or from a checkout:  uv tool install ./cli
```

`chatty login --password` logs in with the password (and 2FA code) instead. `chatty -c` continues your latest conversation, `-a <slug>` picks the agent, `--power` turns on power mode. Inside, `/help` lists the commands.

The full guide is [docs/cli.md](../docs/cli.md).

## Development

```bash
uv run --project cli --extra dev pytest cli/tests
```
