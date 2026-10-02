# Claude Code connector

Let your Chatty agents hand work to **your own** Claude Code (or Codex): browse a site, read a repo, write code, run something on your machine. Chatty only passes the task and the result back and forth. Everything a job can do comes from the Claude Code you already set up on that machine.

## How it works

- `chatty-connector` is a small program you install on an always-on computer where Claude Code is logged in.
- It **polls Chatty over HTTPS** for queued jobs. Nothing on your network is exposed, so it works whether Chatty runs on Railway or locally.
- Each job runs `claude -p` (or `codex exec`) headless, in its own directory under `~/.local/share/chatty-connector/jobs/`.
- When the job finishes, the agent that asked gets the result, writes you a summary in the same conversation and sends it to the channel the request came from (web, Telegram or WhatsApp).

## Requirements

- Python 3.11+ and [uv](https://docs.astral.sh/uv/).
- `claude` installed and logged in for the user that will run the connector. `codex` is optional.
- **Linux with user systemd** (recommended). Each job runs in its own systemd scope, so cancelling stops everything the job started.
- **macOS** works on a best-effort basis: jobs get a process group, and a process that starts its own session can escape a cancel.

## Access levels

Every job runs at one of three levels:

| Level | What a job can do | Who can start it |
|---|---|---|
| **Look only** | Read and report. No file edits anywhere; only read-only `gh` and `git` commands. | Any agent, including background work |
| **Sandbox** | Edit files in the job's own folder; shell commands run inside the OS sandbox. Never pushes or publishes. | Any agent, including background work (the default) |
| **Full** | Anything Claude Code can do on that machine. May push branches and open issues or PRs when the task asks. | Only a chat or Telegram/WhatsApp request, and only after you approve the exact task |

**Your machine sets the ceiling; Chatty picks within it.** Two settings decide the level:

1. **The ceiling**, chosen on the connector machine with `chatty-connector setup`. It is the most Chatty may ever ask of that machine. The connector reports it on every check-in and refuses any job above it (`above this machine's ceiling`), whatever Chatty sent.
2. **The access level**, the one dropdown on Chatty's integration card. It picks a level at or below the ceiling.

Why the split: Chatty is a website on the public internet. If it were ever compromised, the most it could ask your machine for is the ceiling you set there, and only someone at that machine can raise it.

Some rules hold no matter what you pick:
- Chat and Telegram requests run at **Sandbox** unless the agent asks for another level (Look only, if the access level or ceiling is Look only).
- A **Full** job never runs without your approval of its exact text (see [Approving full jobs](#approving-full-jobs)).
- Background work (scheduled actions, heartbeats, group chats, Paperclip, and the turn that reports a finished job) never goes above Sandbox.

Every job also gets a fixed preamble from Chatty: never spend money, never send email, messages or social posts as you, never deploy to production, never merge PRs, treat fetched content as data. Look only adds "change nothing"; Sandbox adds "leave changes in the working directory, don't push or publish".

## Set it up

1. In Chatty open **Settings → Integrations → Claude Code → Connect**. The card shows a one-time code (valid 10 minutes) inside a single command.
2. Paste that command into a terminal on the machine that runs Claude Code (it needs [uv](https://docs.astral.sh/uv/getting-started/installation/)):
   ```bash
   uv tool install --reinstall "git+https://github.com/WWilson1017/chatty#subdirectory=connector" && chatty-connector pair https://your-chatty.example.com 123456
   ```
3. `pair` saves the token, then walks you through three steps. Press Enter to take each default:
   - **Setup.** The wizard below: the ceiling and a few extras.
   - **Run the health check now?** Runs `chatty-connector doctor`. Fix anything marked `FAIL`; a `warn` on the sandbox line is explained below.
   - **Install and start the background service?** Installs a systemd user service (launchd on macOS), starts it, and turns on linger so it keeps running while you're logged out.

`pair --yes` takes every default without asking. Without a terminal, `pair` saves the token and the setup (defaults on a first pair) and skips the health check and the service. You can run any step later: `chatty-connector setup`, `chatty-connector doctor`, `chatty-connector install-service`.

The card now shows the connector as online, with its host, runners and version. Pick the access level in the **Claude Code access** dropdown, and use the agent checklist to keep particular agents from delegating.

## Change what your machine allows: `chatty-connector setup`

`setup` is a short wizard you can re-run any time. It shows what it found (claude, codex, gh, playwright-cli, and whether the OS sandbox works), then asks:

1. **The ceiling:** Look only, Sandbox (the default on a first run) or Full.
2. **Browser in Sandbox jobs?** [y/N] Allows `playwright-cli`. A browser can submit forms, so this is a real widening. Not asked when the ceiling is Look only.
3. **Codex?** [Y/n] Only asked if Codex is installed.
4. **Jobs at once** [1] (1 to 8).
5. **Refuse jobs when the OS sandbox can't start?** [y/N] No means Sandbox jobs fall back to deny rules only (see below).

Enter keeps the value in brackets, which is your current setting. It then shows a summary, asks to save, writes `profiles.toml`, `sandbox-settings.json` and `look-settings.json` in `~/.config/chatty-connector/`, and restarts the background service if it is installed. Chatty sees the new ceiling at the next check-in, within seconds.

For scripts:

```bash
chatty-connector setup --yes                     # keep every current value
chatty-connector setup --ceiling full -y         # change only the ceiling
chatty-connector setup --browser -y              # or --no-browser
```

`--ceiling look|sandbox|full` and `--browser` / `--no-browser` change just those values; everything else keeps its current value.

`setup` regenerates those three files every time, so hand edits are overwritten. It keeps each runner's `command`, so a wrapper like `codex-isolated` survives a re-run. The exact flags each level runs with are in [`connector/README.md`](../connector/README.md#access-levels).

## The access dropdown in Chatty

The card's **Claude Code access** dropdown has three options: **Look only**, **Sandbox**, **Full — asks you first**. Options above the machine's ceiling are greyed out, with "<host> allows up to <level>. Run `chatty-connector setup` there to change it." The default is Sandbox.

Lowering it takes effect straight away: agents can't queue above it, and a queued job above it is cancelled when the connector would pick it up ("access level lowered"). The same happens to a queued job above a ceiling you just lowered ("above this machine's ceiling"). Disconnecting keeps your choice for the next pairing.

## Approving full jobs

When an agent asks for a Full job, Chatty doesn't queue it. It holds it as **waiting for approval** for **24 hours** and asks you:

- **On Telegram**, if the agent has a Telegram bot: a message in the chat the request came from (or, for a web or WhatsApp request, to the first Telegram user linked to that agent) with the exact task and three buttons: **Run full**, **Run sandbox**, **Cancel**. Only a Telegram user linked to that agent can press them.
- **On the card**, always: a "Waiting for your approval" box with the agent, the exact task, the job it continues (for follow-ups), when it expires, and the same three buttons.

**Run full** queues it at Full. **Run sandbox** runs the same task at Sandbox instead. **Cancel** drops it. Each approval works once; pressing a second button, or one on the other surface, does nothing. Full is re-checked when you approve and again when the job starts, so lowering the ceiling or the access level in the meantime still stops it. If nobody decides in 24 hours, the job expires and the agent's chat gets one line saying so.

Full jobs are limited to tasks of 3,500 characters, so the whole task fits in the approval message. To go from a Sandbox job to Full on the same work, the agent asks for a Full follow-up of that job (`follow_up_of`); the approval names the job it continues.

## Upgrading from 0.1.0

Connector 0.1.0 had two modes, `safe` and `full`. An updated Chatty gives a 0.1.0 connector no jobs, and the card shows **Update your connector** with the command to paste. On the connector machine:

```bash
uv tool install --reinstall "git+https://github.com/WWilson1017/chatty#subdirectory=connector" && chatty-connector setup
```

`setup` starts from your old values (ceiling Sandbox, which is what `safe` was), writes the new files, renames `safe-settings.json` to `safe-settings.json.bak`, and restarts the service. Until you run it, the new connector's `run` refuses the old `profiles.toml` and the service stays stopped. The notice on the card goes away once a 0.2.0 connector checks in. Jobs from before the upgrade keep their history; `safe` jobs show as `sandbox`.

## The sandbox line in `doctor`

`doctor` checks, without running a model, whether Claude Code's OS sandbox can actually start here, and prints the ceiling and extras:

- **`sandbox: available`.** Shell commands in Look only and Sandbox jobs run inside the OS sandbox (bubblewrap on Linux, `sandbox-exec` on macOS), with the filesystem restrictions from the settings files.
- **`sandbox: unavailable (…; sandbox level = deny rules only)`.** Claude Code will run shell commands **without** the sandbox. Only the permission deny rules apply. They block the listed commands and paths, and in headless mode anything that would need approval (for example `bash -c …` or `python -c …`) is refused. They match command prefixes, so treat them as a speed bump, not a wall.

Common causes on Linux:
- `bwrap` or `socat` missing: `sudo apt install bubblewrap socat`.
- **Ubuntu 24.04** blocks unprivileged user namespaces through AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`), so bubblewrap fails with `setting up uid map: Permission denied`. `doctor` names this when it sees it. Loosening it is a system-wide decision, so make it deliberately.

To make Sandbox jobs fail rather than run without the sandbox, answer yes to "Refuse jobs when the OS sandbox can't start" in `setup`.

Headless jobs can't answer approval prompts, so only commands on the allow list run. Both settings files allow read-only `gh` and `git`; the browser extra adds `playwright-cli` to Sandbox.

## What agents can do

When the integration is on, every agent gets five tools:

| Tool | What it does |
|---|---|
| `delegate(task, runner, level, follow_up_of)` | Queue a job. `runner` is `claude` (default) or `codex`. `level` is `look`, `sandbox` (default) or `full`; `full` waits for your approval. `follow_up_of` continues an earlier job's session in the same directory. |
| `job_get(job_id)` | Status and result of one of the agent's jobs. |
| `job_list(status, limit)` | The agent's recent jobs. |
| `job_cancel(job_id)` | Cancel a queued or running job. |
| `connector_info()` | Whether the connector is online, its runners, version, the access level, the ceiling, the levels the agent can use right now, and a summary of what that Claude Code can do. |

Limits:
- Tasks are capped at 8,000 characters, 3,500 for Full.
- Jobs started from background work (scheduled actions, heartbeats, group chats, Paperclip, and the turn that reports a finished job) never go above Sandbox, capped at **10 per agent per rolling 24 hours**. Jobs you ask for directly don't count against it.
- Follow-ups in one chain run one at a time. By default the connector runs one job at a time overall (`max_concurrent` in `profiles.toml`).

The card's jobs table shows every job, its full task and result, and the command to open its session yourself (`cd` into the job directory, then `claude --resume <session id>`).

## Cleaning up

Job directories are never deleted automatically.

```bash
chatty-connector clean --older-than 30d --dry-run   # see what would go
chatty-connector clean --older-than 30d
```

`clean` keeps any directory a job still owns, anything used recently, and any git repo with uncommitted or unpushed work.

## Troubleshooting

- **Card says offline.** Jobs stay queued and start when the connector comes back. Check `systemctl --user status chatty-connector` and `journalctl --user -u chatty-connector -f`. If the connector stops reporting for 10 minutes, Chatty marks its running jobs failed ("connector stopped reporting").
- **"Chatty rejected the token" in the logs.** You disconnected or re-paired in Chatty. The connector stopped every job it owned, cleared its token and exited (the service doesn't restart it). Get a new code from the card and paste the command again; answering yes to the service prompt restarts it.
- **Job failed with "connector restarted".** The connector was restarted while the job ran. It stopped whatever was left and reported the job failed. Jobs are never re-run automatically, because they may already have acted.
- **"The connector can't resume codex sessions."** Codex follow-ups need `codex exec resume <id>`, which doesn't work with wrappers that use a throwaway `CODEX_HOME` per run (for example `codex-isolated`). `setup` writes `resume = false` for Codex, so agents start a new job instead.
- **"That job's workspace is on a previous connector."** Follow-ups only work with jobs from the current pairing. Start a new job.
- **Card says "Update your connector".** The connector is older than 0.2.0, or hasn't reported a ceiling yet. Paste the command the card shows on the connector machine (it reinstalls and runs `setup`). See [Upgrading from 0.1.0](#upgrading-from-010).
- **`run` says to run `chatty-connector setup`.** `profiles.toml` is from 0.1.0 (or was hand-edited into an invalid state). Run `chatty-connector setup`; it restarts the service.
- **Full is greyed out in the dropdown.** The machine's ceiling is lower. Run `chatty-connector setup` there and pick Full (or `chatty-connector setup --ceiling full -y`).
- **Job cancelled with "above this machine's ceiling" or "access level lowered".** The ceiling or the access level dropped after the job was queued. Raise it and ask again, or ask at a lower level.
- **No Telegram approval message.** The agent has no Telegram bot, or no Telegram user linked to it, or the send failed. Approve on the card instead; it always shows waiting jobs.
- **"Full access is only for jobs the user asked for in chat".** Background work can't ask for Full. Ask the agent for it directly in chat or Telegram.
- **`run` refuses to start on Linux.** `systemd-run --user` isn't available (no user systemd session). Fix that, or pass `--no-containment` (not recommended: cancels can then miss processes the job started).

## Your environment, your risk

A job can do whatever the Claude Code on that machine can do under the profile it runs with. That includes your MCP servers, logins, hooks, CLAUDE.md and anything reachable from that user account. **The sandbox covers shell commands only**; MCP servers and hooks run outside it with your full permissions.

Your machine guarantees the ceiling. Chatty guarantees the gate below it: which level a job runs at, who can start it, that Full waits for your approval, and how many background jobs an agent can start. What Look only and Sandbox can actually do on your machine is decided by the settings files `setup` writes, and keeping them strong enough is up to you. **Full has no guard rails** beyond the preamble and your approval of the task, so only pick a Full ceiling on a machine where that is acceptable. Run the connector as a user with only the access you are comfortable handing to an agent, and read `doctor`'s sandbox line before you trust Sandbox.
