# Computer: pre-approved actions for scheduled work

> Written before `docs/computer.md` (the user guide, PR 8) exists on this branch. Fold this in as a "Pre-approved actions" section there once it does.

Normally every consequential action the helper reaches on the computer — send, post, delete, submit, buy — stops for your approval. A routine that runs on a schedule ("submit the timesheet every Friday") would ping you every time for the same button. Pre-approvals let a **scheduled action** name the one gate its tasks may cross without asking.

**Where.** Agent → **Heartbeat** tab → **Scheduled actions** → the action's **Allowed without asking** list. Each row is a site and a button text, e.g. `time.example` · "Submit timesheet". Add and remove rows there; nothing else can write the list — not the agent, not its scheduled-action tools, not the action's other settings.

**What it does.** When a computer task started by that scheduled action is about to press a control the gate classifier would stop, Chatty checks the list on the server: the page's host must equal the row's host (case-insensitive, `www.` ignored) and the control's accessible name must equal the button text (case and whitespace ignored). On a match the gate is recorded as already approved (`decision: preapproved`) and the click is sent through the same path an owner's approval takes: one activation, bound to the page facts read at that moment (host, path, frame, form, fields, control), re-checked by the computer inside the click request. If the page changed under the click, or the control is gone, a normal approval card opens instead. The task's step log shows `preapproved:<kind>`.

**What never pre-approves.**

- **Purchases.** A `buy` gate always asks, whatever the list says.
- **Anything but a single plain click or Enter/Space.** Double clicks, held keys, typed newlines and selects still ask.
- **Heartbeats and reminders.** Only cron scheduled actions can carry a list; a heartbeat's or a reminder's tasks never match.
- **Near misses.** `Submit timesheets`, `Submit`, `sub.time.example` and `time.example.com` are not `Submit timesheet` on `time.example`.
- **A changed prompt.** The list is bound to the action's prompt (its sha256) when you save it. Editing the prompt — from the dashboard or by the agent — voids the list until you save it again; the UI shows it empty.

**Scope.** The pre-approval covers the task the scheduled action started and its follow-ups (approvals, report-back turns) — the whole routine — but not tasks the agent starts from chat. Use it for routines whose button does one well-understood thing; the computer still refuses a click whose page facts differ from what was read, but it cannot know what a submission means to the site.
