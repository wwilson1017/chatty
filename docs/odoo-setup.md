# Odoo Setup

Connect your Odoo ERP so your Chatty agents can look up and manage sales, inventory, accounting, HR, projects, and more.

## Prerequisites

- An Odoo instance (cloud or self-hosted)
- An Odoo user account with API key access

## Step 1: Generate an API Key in Odoo

1. Log in to your Odoo instance
2. Go to **Settings** > **Users & Companies** > **Users**
3. Select your user
4. Go to the **Account Security** tab
5. Under **API Keys**, click **New API Key**
6. Name it (e.g., "Chatty") and copy the key

## Step 2: Connect in Chatty

### Local

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations**
3. Find **Odoo** and click **Setup**
4. Fill in the connection form:
   - **Odoo URL** — your instance URL (e.g., `https://erp.yourcompany.com`)
   - **Database** — your Odoo database name
   - **Username** — the email or username you log in with
   - **API Key** — the key you generated in Step 1
5. Click **Connect** — Chatty tests the connection and shows your Odoo version on success

### Railway

1. Open your Chatty instance on Railway
2. Go to **Settings** > **Integrations**
3. Find **Odoo** and click **Setup**
4. Fill in the same connection form (Odoo URL, Database, Username, API Key)
5. Click **Connect** — Chatty tests the connection and shows your Odoo version on success

Odoo credentials are entered in the Chatty UI, not as environment variables — so the setup is the same on both local and Railway. Your Odoo instance just needs to be reachable from wherever Chatty is running.

## What Your Agents Can Do

Once connected, your agents can work with data across your entire Odoo installation:

- **Sales** — search, create, update, and confirm sales orders
- **Purchase** — create and manage purchase orders, approvals, and confirmations
- **Inventory** — track stock levels, warehouse locations, product lots
- **Products** — search, create, and update products and categories
- **CRM** — create and manage leads, move through pipeline stages, mark won/lost, log notes and activities
- **Accounting** — create invoices, register payments, view aged receivables/payables
- **HR** — look up employee records and departments
- **Projects** — create and update tasks, log timesheets
- **Helpdesk** — search tickets, update stages, assign agents, post messages and replies
- **Manufacturing** — create, update, and confirm production orders
- **Quality** — run quality checks (pass/fail), create quality alerts
- **Maintenance** — create and update maintenance requests, track equipment
- **Documents** — download PDFs and read attachments from any record

Example questions you can ask:

- "Create a sales order for 50 units of Widget A for Acme Corp"
- "What invoices are overdue?"
- "Assign ticket #412 to Sarah and post a reply to the customer"
- "Log 2 hours on the website redesign project"
- "Move the Acme lead to the 'Proposal' stage"
- "Create a purchase order for 100 units from Supplier X"
- "How much stock do we have of product X?"

## Notes

- Chatty uses Odoo's XML-RPC API — make sure XML-RPC is enabled on your instance
- For safety, delete operations are disabled — your agent can create and update records but cannot delete them
- 43 standard Odoo models are accessible across all major modules
- Credentials are encrypted at rest in your Chatty instance
