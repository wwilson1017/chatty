# chatty-connector

Lets your [Chatty](https://github.com/WWilson1017/chatty) agents hand tasks to **your own** Claude Code (or Codex) on an always-on machine you control.

It polls Chatty over HTTPS for queued jobs, so nothing on your network is exposed. For each job it runs `claude -p` (or `codex exec`) headless in its own directory, then posts the result, the session id and the usage back to Chatty.

**Your environment, your risk.** Whatever your Claude Code can do on this machine (MCP servers, logins, CLAUDE.md, tools), a job can do. The connector only decides *which level* a job runs at, and never above the ceiling you set here. Read "Access levels" before you install it.

## Install

Requires Python 3.11+, and `claude` (and/or `codex`) installed and logged in for the user that will run the connector.

In Chatty: **Settings → Integrations → Claude Code → Connect**. Paste the one command the card shows:

```bash
uv tool install --reinstall "git+https://github.com/WWilson1017/chatty#subdirectory=connector" && chatty-connector pair https://your-chatty.example.com 123456
# or from a checkout:  uv tool install ./connector
```

`pair` then runs `setup` (below), asks whether to run the health check (`doctor`), and whether to install and start the background service (`install-service`). Press Enter to take the defaults, or pass `--yes`. Without a terminal it pairs and keeps the current setup (a first pair gets the defaults).

## Setup: what this machine allows

```bash
chatty-connector setup
```

A short wizard you can re-run any time. It shows what it found (claude, codex, gh, playwright-cli, and whether the OS sandbox works), then asks:

1. **The ceiling:** the most Chatty may ask of this machine: Look only, Sandbox (the default) or Full. In Chatty you pick a level per connection *within* that ceiling; higher options are greyed out there.
2. **Browser in Sandbox jobs?** [y/N] Allows `playwright-cli`. A browser can submit forms, so this is a real widening.
3. **Codex?** [Y/n] Only asked if Codex is installed.
4. **Jobs at once** [1]
5. **Refuse jobs when the sandbox can't start?** [y/N] Off means Sandbox jobs fall back to deny rules only (see below).

It prints a summary, asks to save, writes the files below, and restarts the background service if it is installed. Enter keeps the value shown in brackets, which is your current setting.

For scripts: `chatty-connector setup --yes` keeps every current value; `--ceiling look|sandbox|full` and `--browser` / `--no-browser` change just those. With no terminal it behaves like `--yes`.

It writes `~/.config/chatty-connector/`:
- `config.toml` (from `pair`): the Chatty URL and the connector token (mode 0600; Chatty only stores its hash)
- `profiles.toml`: the ceiling and how each level runs
- `sandbox-settings.json` and `look-settings.json`: the Claude Code settings for those levels, with your absolute paths filled in

`setup` regenerates these three files each time, so hand edits are overwritten (it keeps each runner's `command` and `resume`). To change something, re-run `setup`.

## Upgrading from 0.1.0

0.1.0 had two modes, `safe` and `full`. A 0.1.0 connector gets no jobs from an updated Chatty, and after upgrading, `run` refuses the old `profiles.toml` (the service stays stopped) until you run setup:

```bash
uv tool install --reinstall "git+https://github.com/WWilson1017/chatty#subdirectory=connector"
chatty-connector setup
```

`setup` starts from your old values (ceiling Sandbox, which is what `safe` was), writes the new files, renames `safe-settings.json` to `safe-settings.json.bak`, and restarts the service. Chatty shows "Update your connector" until a 0.2.0 connector checks in.

## Check it

```bash
chatty-connector doctor
```

It checks that Chatty answers (it never claims a job), that the CLIs run, that a one-turn `claude` ping works at the Sandbox level, that the profiles parse, the ceiling and extras, whether the OS sandbox can start, and that job containment works. It prints `sandbox: available` or `sandbox: unavailable (…; sandbox level = deny rules only)`.

## Run it as a service

```bash
chatty-connector install-service
```

- **Linux:** writes `~/.config/systemd/user/chatty-connector.service`, reloads systemd, enables and (re)starts it, and turns on linger so it keeps running when you're logged out (if `loginctl enable-linger` needs root, it prints the `sudo` command). Logs: `journalctl --user -u chatty-connector -f`.
- **macOS:** writes `~/Library/LaunchAgents/com.chatty.connector.plist` and (re)loads it with `launchctl`. Logs: `~/Library/Logs/chatty-connector.log`.

The unit captures your current `PATH` so it can find `claude` and `codex`. Re-run `install-service` if they move.

`chatty-connector run` runs it in the foreground.

## Access levels

| Level | Claude Code | Codex |
|---|---|---|
| **Look only** | `--permission-mode default` + `look-settings.json`: no file edits anywhere, only the read-only `gh`/`git` commands below | `--sandbox read-only` |
| **Sandbox** | `--permission-mode acceptEdits` + `sandbox-settings.json`: edits in the job's own folder, shell commands in the OS sandbox | `--sandbox workspace-write` |
| **Full** | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |

**The ceiling is enforced here.** The connector reports its ceiling on every check-in, and a job above it fails immediately with `above this machine's ceiling`, whatever Chatty sent. Only `setup` on this machine raises it.

Chatty guarantees the **gate** below the ceiling:
- a Full job runs only after you approve its exact text (Telegram buttons or the integration card); chat and Telegram requests default to Sandbox
- scheduled actions, background turns and job-completion turns never go above Sandbox, within a budget of 10 jobs per agent per day

Chatty does **not** guarantee what a level can do on this machine. That's whatever the settings files enforce. Both settings files:
- turn on Claude Code's OS sandbox for shell commands, with `allowUnsandboxedCommands: false`
- deny reading `~/.ssh`, `~/.aws`, `~/.config/gh`, `.env` files and this connector's own config
- also deny reading `~/.codex`, `~/.netrc`, `~/.npmrc`, gcloud/kube/docker/gnupg config and `~/.claude/.credentials.json`
- deny `git push`, `gh pr`, `gh release`, `gh repo` and package publishing

`sandbox-settings.json` also denies editing the connector config, `~/.claude` and `.claude/` in the job dir (no planting hooks or settings). `look-settings.json` denies `Edit`, `Write` and `NotebookEdit` outright, and sets `autoAllowBashIfSandboxed: false`, so the sandbox never waves a shell command through.

Their limits, plainly:
- **The sandbox covers shell commands only.** MCP servers and hooks run outside it, with your full permissions, at every level.
- **Without a working sandbox, Sandbox is "deny rules only".** On Linux the sandbox needs `bubblewrap` and `socat`, and unprivileged user namespaces. Ubuntu 24.04 blocks those by default through AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`), so `doctor` reports the sandbox as unavailable there. Claude Code then runs shell commands *unsandboxed* and prints a warning. The deny rules still apply, and in headless mode any command that would need approval (for example `bash -c …` or `python -c …`) is refused. To make Sandbox jobs fail instead, answer yes to "Refuse jobs when the sandbox can't start" in `setup`.
- Deny rules match command prefixes. They are a speed bump, not a proof.
- **Read-only allow list.** Headless jobs can't answer approval prompts, so any shell command not explicitly allowed is refused. Both files allow read-only `gh` (`issue/pr list|view`, `pr diff|checks`, `repo view`, `run list|view`, `search`) and `git` (`log`, `status`, `diff`, `show`, `clone`). The write forms (`gh pr create`, `gh issue create`, `gh api`, `git push` and the like) are denied. The browser extra adds `Bash(playwright-cli:*)` to Sandbox. If your sandbox works, `gh` can't read `~/.config/gh` from inside it; give jobs a read-only `GH_TOKEN` if they need it.

Chatty also prepends a fixed preamble to every job that matches its level: Look only reads and reports; no level spends money, sends email or messages as you, deploys to production, or merges PRs.

## Profiles

`profiles.toml` (generated by `setup`):

```toml
ceiling = "sandbox"   # look, sandbox or full
max_concurrent = 1    # jobs at once
max_codex = 1         # of which Codex

[claude]
command = "claude"
look = ["--permission-mode", "default", "--settings", "{config_dir}/look-settings.json"]
sandbox = ["--permission-mode", "acceptEdits", "--settings", "{config_dir}/sandbox-settings.json"]
full = ["--dangerously-skip-permissions"]
timeout = { look = 1800, sandbox = 1800, full = 7200 }   # seconds
resume = true

[codex]   # only if you said yes to Codex
command = "codex"
look = ["--sandbox", "read-only"]
sandbox = ["--sandbox", "workspace-write"]
full = ["--dangerously-bypass-approvals-and-sandbox"]
timeout = { look = 1800, sandbox = 1800, full = 7200 }
resume = false
```

The connector adds the fixed flags itself: `-p --output-format stream-json --verbose [--resume <id>]` for Claude, and `exec [resume <id>] --json --skip-git-repo-check … -` for Codex. The prompt always goes on stdin.

`resume` tells Chatty whether follow-ups can continue a session. Leave it `false` for Codex if your `command` is a wrapper that throws its session state away (for example a per-run `CODEX_HOME`). Chatty then asks for a fresh job instead.

`setup` carries over each runner's `command` and `resume`, so a wrapper like `codex-isolated` (or a Codex `resume = true` you made work) survives a re-run. Anything else you edit by hand is overwritten by the next `setup`; restart the service after a hand edit.

## Where jobs run

Each job chain gets its own directory, `~/.local/share/chatty-connector/jobs/<key>/`. Follow-ups resume the same session in the same directory, and run one at a time. To open a job's session yourself: `cd` there and run `claude --resume <session id>` (the card shows the command).

**Containment (Linux).** Each job runs in its own transient systemd user scope (`chatty-job-<id>.scope`). Cancelling, a timeout, or the connector restarting stops the whole scope, including anything the job started in the background. `run` refuses to start without `systemd-run --user` unless you pass `--no-containment`.

**macOS.** Best effort: each job gets its own process group. A process that starts its own session can escape cancellation.

**Restarts.** Job state lives in `~/.local/state/chatty-connector/`. After a restart the connector stops anything left over, reports those jobs to Chatty as `failed: connector restarted`, and only then takes new work. Results that hadn't reached Chatty yet are re-sent.

**Disconnecting.** When you disconnect or re-pair in Chatty, the connector stops every job the next time it checks in, then exits. To reconnect, run `pair` again and answer yes to the service prompt (or run `install-service`), which restarts it. The unit deliberately doesn't restart itself after a rejected token.

## Cleaning up

Job directories are never deleted automatically.

```bash
chatty-connector clean --older-than 30d --dry-run
chatty-connector clean --older-than 30d
```

`clean` skips directories that a job still owns, that were used recently, or that contain a git repo with uncommitted or unpushed work.
