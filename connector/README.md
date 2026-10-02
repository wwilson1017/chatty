# chatty-connector

Lets your [Chatty](https://github.com/WWilson1017/chatty) agents hand tasks to **your own** Claude Code (or Codex) on an always-on machine you control.

It polls Chatty over HTTPS for queued jobs, so nothing on your network is exposed. For each job it runs `claude -p` (or `codex exec`) headless in its own directory, then posts the result, the session id and the usage back to Chatty.

**Your environment, your risk.** Whatever your Claude Code can do on this machine (MCP servers, logins, CLAUDE.md, tools), a job can do. The connector only decides *which profile* a job runs under. Read "Safe vs full" before you install it.

## Install

Requires Python 3.11+, and `claude` (and/or `codex`) installed and logged in for the user that will run the connector.

```bash
uv tool install "git+https://github.com/WWilson1017/chatty#subdirectory=connector"
# or from a checkout:  uv tool install ./connector
```

## Pair

In Chatty: **Settings → Integrations → Claude Code → Connect**. Copy the pair command it shows:

```bash
chatty-connector pair https://your-chatty.example.com 123456
```

This writes `~/.config/chatty-connector/`:
- `config.toml`: the Chatty URL and the connector token (mode 0600; Chatty only stores its hash)
- `profiles.toml`: how each job mode runs (edit freely)
- `safe-settings.json`: the starter Claude Code settings for `safe` jobs, with your absolute paths filled in

Existing `profiles.toml` and `safe-settings.json` are never overwritten.

## Check it

```bash
chatty-connector doctor
```

It checks that Chatty answers (it never claims a job), that the CLIs run, that a one-turn `claude` ping works with the safe profile, that the profiles parse, whether the OS sandbox can start, and that job containment works. It prints `sandbox: available` or `sandbox: unavailable (…; safe profile = deny rules only)`.

## Run it as a service

```bash
chatty-connector install-service
```

- **Linux:** writes `~/.config/systemd/user/chatty-connector.service`. Then run `systemctl --user daemon-reload && systemctl --user enable --now chatty-connector`, and `loginctl enable-linger $USER` so it keeps running when you're logged out. Logs: `journalctl --user -u chatty-connector -f`.
- **macOS:** writes `~/Library/LaunchAgents/com.chatty.connector.plist`. Start it with `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.chatty.connector.plist`. Logs: `~/Library/Logs/chatty-connector.log`.

The unit captures your current `PATH` so it can find `claude` and `codex`. Re-run `install-service` if they move.

`chatty-connector run` runs it in the foreground.

## Safe vs full

Chatty guarantees the **gate**:
- a job runs under your `full` profile only after you approved its exact text
- everything else (scheduled actions, background turns, group chats, job-completion turns) can only use `safe`, within a budget of 10 jobs per agent per day

Chatty does **not** guarantee what `safe` can do on this machine. That's whatever your `safe` profile enforces. The starter profile:
- runs Claude Code with `--permission-mode acceptEdits` and `safe-settings.json`
- turns on Claude Code's OS sandbox for shell commands, with `allowUnsandboxedCommands: false`
- denies reading `~/.ssh`, `~/.aws`, `~/.config/gh`, `.env` files and this connector's own config, and denies editing the connector config and `~/.claude`
- also denies reading `~/.codex`, `~/.netrc`, `~/.npmrc`, gcloud/kube/docker/gnupg config and `~/.claude/.credentials.json`, and writing `.claude/` in the job dir (no planting hooks or settings)
- denies `git push`, `gh pr`, `gh release`, `gh repo` and package publishing

Its limits, plainly:
- **The sandbox covers shell commands only.** MCP servers and hooks run outside it, with your full permissions.
- **Without a working sandbox, `safe` is "deny rules only".** On Linux the sandbox needs `bubblewrap` and `socat`, and unprivileged user namespaces. Ubuntu 24.04 blocks those by default through AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`), so `doctor` reports the sandbox as unavailable there. Claude Code then runs shell commands *unsandboxed* and prints a warning. The deny rules still apply, and in headless mode any command that would need approval (for example `bash -c …` or `python -c …`) is refused. To make safe jobs fail instead of running without the sandbox, add `"failIfUnavailable": true` under `"sandbox"` in `safe-settings.json`.
- Deny rules match command prefixes. They are a speed bump, not a proof.
- **Read-only allow list.** Headless `safe` jobs can't answer approval prompts, so any shell command not explicitly allowed is refused. The starter file allows read-only `gh` (`issue/pr list|view`, `pr diff|checks`, `repo view`, `run list|view`, `search`) and `git` (`log`, `status`, `diff`, `show`, `clone`). The write forms (`gh pr create`, `gh issue create`, `gh api`, `git push` and the like) are denied. Add to `permissions.allow` for anything else you want `safe` jobs to run, for example `"Bash(playwright-cli:*)"` for browsing. Note that a browser can submit forms, so that is a real widening. If your sandbox works, `gh` can't read `~/.config/gh` from inside it; remove that path from `sandbox.filesystem.denyRead` or give jobs a read-only `GH_TOKEN`.

Chatty also prepends a fixed preamble to every job: never spend money, never send email or messages as you, never deploy to production, never merge PRs.

## Profiles

`profiles.toml`:

```toml
max_concurrent = 1   # jobs at once
max_codex = 1        # of which Codex

[claude]
command = "claude"
safe = ["--permission-mode", "acceptEdits", "--settings", "{config_dir}/safe-settings.json"]
full = ["--dangerously-skip-permissions"]
timeout = { safe = 1800, full = 7200 }   # seconds
resume = true

[codex]   # optional
command = "codex"
safe = ["--sandbox", "workspace-write"]
full = ["--dangerously-bypass-approvals-and-sandbox"]
timeout = { safe = 1800, full = 7200 }
resume = false
```

The connector adds the fixed flags itself: `-p --output-format stream-json --verbose [--resume <id>]` for Claude, and `exec [resume <id>] --json --skip-git-repo-check … -` for Codex. The prompt always goes on stdin.

`resume` tells Chatty whether follow-ups can continue a session. Leave it `false` for Codex if your `command` is a wrapper that throws its session state away (for example a per-run `CODEX_HOME`). Chatty then asks for a fresh job instead.

Restart the service after editing.

## Where jobs run

Each job chain gets its own directory, `~/.local/share/chatty-connector/jobs/<key>/`. Follow-ups resume the same session in the same directory, and run one at a time. To open a job's session yourself: `cd` there and run `claude --resume <session id>` (the card shows the command).

**Containment (Linux).** Each job runs in its own transient systemd user scope (`chatty-job-<id>.scope`). Cancelling, a timeout, or the connector restarting stops the whole scope, including anything the job started in the background. `run` refuses to start without `systemd-run --user` unless you pass `--no-containment`.

**macOS.** Best effort: each job gets its own process group. A process that starts its own session can escape cancellation.

**Restarts.** Job state lives in `~/.local/state/chatty-connector/`. After a restart the connector stops anything left over, reports those jobs to Chatty as `failed: connector restarted`, and only then takes new work. Results that hadn't reached Chatty yet are re-sent.

**Disconnecting.** When you disconnect or re-pair in Chatty, the connector stops every job the next time it checks in, then exits. To reconnect, run `pair` again and restart the service: `systemctl --user restart chatty-connector` on Linux (the unit deliberately doesn't restart itself after a rejected token), or `launchctl kickstart -k gui/$(id -u)/com.chatty.connector` on macOS.

## Cleaning up

Job directories are never deleted automatically.

```bash
chatty-connector clean --older-than 30d --dry-run
chatty-connector clean --older-than 30d
```

`clean` skips directories that a job still owns, that were used recently, or that contain a git repo with uncommitted or unpushed work.
