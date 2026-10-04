# Step 0 spike — findings (skydiver, Ubuntu 24.04, 2026-10-02)

Claude Code 2.1.287, codex-cli 0.157.1. Fixtures in `tests/fixtures/` (paths rewritten to `/home/user`, hook events and thinking text removed, init event trimmed).

**claude -p stream-json** (`claude -p --output-format stream-json --verbose`, prompt on stdin)
- `session_id` is on *every* event, including the hook events that come before `system/init`, so it is captured from the first line.
- The final `{"type":"result"}` carries `result`, `is_error`, `total_cost_usd`, `usage`, `num_turns`, `duration_ms`, `permission_denials` (`[{tool_name, tool_use_id, tool_input}]`).
- `--resume <sid>` worked from the same cwd and, in this version, also from a different cwd (it found the session across project dirs). The connector still runs follow-ups in the same job dir, because the files live there.
- A safe-profile `--resume` of a session that started with `--dangerously-skip-permissions` applied the safe permissions (the token read was denied).

**Starter safe-settings.json** (`--permission-mode acceptEdits --settings safe-settings.json`, haiku)
- Read tool on `~/.ssh/known_hosts` and on the connector `config.toml`: denied by the `Read(//abs/path/**)` rules.
- `cat`/`ls` of those paths through Bash: denied too (Read deny rules apply to Bash read commands).
- `git push` and `gh pr create`: denied by `Bash(git push:*)` / `Bash(gh pr:*)`. `bash -c 'git push …'` and `python3 -c "subprocess.run(['git','push',…])"`: "This command requires approval", which `-p` turns into a denial. The local bare remote received nothing.
- Plain commands (`echo`) run without a prompt.
- `dangerouslyDisableSandbox: true` ran `echo` — irrelevant here because the sandbox never started (below). Not provable on this host.

**Sandbox on this box: unavailable.**
- `bwrap --ro-bind / / true` → `bwrap: setting up uid map: Permission denied` (exit 1); `kernel.apparmor_restrict_unprivileged_userns = 1`.
- Claude Code also needs `socat`, which is not installed. Its stderr says: `Sandbox disabled: sandbox is enabled but dependencies are missing: socat not installed … Commands will run WITHOUT sandboxing.`
- So on skydiver the safe profile is "deny rules only". `doctor` checks bwrap, socat and the AppArmor sysctl and names the cause. `sandbox.failIfUnavailable: true` exists in the settings schema; the starter leaves it off (default) so safe jobs still run, and the README says how to turn it on.

**Codex** (`codex-isolated exec --json --skip-git-repo-check --sandbox workspace-write -`)
- Events: `thread.started{thread_id}`, `turn.started`, `item.completed{item:{type:agent_message,text}}`, `turn.completed{usage}`. A non-fatal `item.completed{item:{type:"error"}}` deprecation warning appears too, so `error` items are not treated as failure.
- `codex-isolated exec resume <id> …` → `thread/resume failed: no rollout found for thread id` (exit 1): the throwaway `CODEX_HOME` discards sessions. Codex profile defaults to `resume = false`.

**systemd-run**
- `systemd-run --user --scope --unit=chatty-job-test.scope --collect -- sleep 30` works; `systemctl --user stop chatty-job-test.scope` kills it (launcher exits -15) and the unit is gone (`LoadState=not-found`).
- The bare name `chatty-job-test` resolves to `.service` (`inactive`), confirming the full `.scope` name is required.
- `systemd-run --scope` execs the command in place (the launcher pid becomes `sleep`), so `PR_SET_PDEATHSIG` set in `preexec_fn` survives into the job.
- `systemd-run` prints "Running as unit: …" on stderr unless `--quiet`; the connector passes `--quiet`.
