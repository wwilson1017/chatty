# CRM Lite Setup

CRM Lite is Chatty's built-in contact and deal management system. No external accounts or API keys needed — it runs entirely inside your Chatty instance.

## Local Setup

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations**
3. Find **CRM Lite** and click **Setup**
4. Done — the CRM database is created and your agents can start using it

## Railway Setup

1. Open your Chatty instance on Railway
2. Go to **Settings** > **Integrations**
3. Find **CRM Lite** and click **Setup**
4. Done — your CRM data is stored on the Railway persistent volume

No environment variables or external credentials needed for either setup. You can also access the CRM directly from the **CRM** tab in the Chatty dashboard.

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
