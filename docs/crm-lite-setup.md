# CRM Lite Setup

CRM Lite is Chatty's optional built-in contact and deal management system. No external accounts or API keys needed — it runs entirely inside your Chatty instance. It ships **disabled by default**; enable it if you want lightweight contact/deal tracking. (For everyday task management, use the built-in [Todos (GTD) system](../README.md) instead — it's always on.)

## Enabling It

1. Open Chatty (locally via `python run.py`, or your Railway instance)
2. Go to **Settings** > **Integrations**
3. Find **CRM** and toggle it on for an empty CRM — or ask any agent to run `enable_crm`, which also seeds clearable example data so you can see how a populated CRM looks
4. Done — the CRM database is created, the CRM tab appears in the nav, and your agents get the CRM tools

Your data lives in Chatty's local SQLite storage (on Railway: the persistent volume). No environment variables or external credentials needed.

## Disabling It

Toggle CRM off in **Settings** > **Integrations** at any time. Your data stays on disk untouched — re-enabling brings everything back. (Real deletion lives in **Settings** > **Danger** > "Clear CRM data".)

> **Tip:** Want your CRM tasks in the Todos system? Before disabling, ask any agent: *"Move my open CRM tasks into my todo inbox."* The agent reads them with `crm_list_tasks` and recreates them with `todo_create`.

## Demo Data

When you first enable CRM Lite, Chatty seeds it with realistic example data — 8 contacts, 7 deals, 8 tasks, and 11 activity log entries — so you can see what a populated CRM looks like before entering your own data. The demo data uses a fictional bakery business with sample customers, suppliers, and deals at various pipeline stages.

While demo data is active, a banner appears in the CRM view. Click **Clear demo data** to wipe it and start fresh with an empty CRM. Once cleared, the demo data is gone permanently — your real data is never mixed with it.

## What Your Agents Can Do

Your agents can manage your full sales pipeline through conversation:

**Contacts**
- Create, update, and look up contacts
- Track contact details: name, email, phone, company, notes, tags
- Filter and search across your contact list

**Deals**
- Create and track deals through pipeline stages
- Assign deals to contacts
- Track deal value and status

**Tasks**
- Create tasks linked to contacts or deals
- Track task status and due dates
- Assign and update tasks through conversation

**Activities**
- Log calls, meetings, and notes
- View activity timeline for any contact or deal

Example questions you can ask:

- "Add a new contact: Jane Smith, jane@example.com, Acme Corp"
- "Create a deal for the Acme project, $15,000"
- "What tasks are due this week?"
- "Log a call with Jane — discussed the proposal, she's reviewing it"
- "Show me all deals in the negotiation stage"

## Notes

- All CRM data is stored locally in your Chatty instance — nothing leaves your server
- CRM Lite is single-user (like the rest of Chatty)
- For teams that have outgrown a local CRM, consider connecting to [Odoo](odoo-setup.md) for a full ERP
