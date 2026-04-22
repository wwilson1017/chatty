# Sales Workflow — Cross-Tool Playbook

This guide defines how your tools work together to build and manage the sales pipeline. Use it as your default framework when handling sales-related tasks.

## The Sales Loop

### 1. Capture — CRM + Gmail
When a new inquiry arrives (email, Telegram, WhatsApp):
- Check CRM for an existing contact (`crm_find_contact`)
- If new: create the contact (`crm_create_contact`) with source, company, and notes
- Create a deal (`crm_create_deal`) with estimated value and stage "Lead"
- Log the initial interaction (`crm_log_activity` type: "email" or "note")

### 2. Qualify — CRM + Gmail
As you learn more about the prospect:
- Update deal stage to "Qualified" (`crm_update_deal_stage`)
- Update contact details as you learn them (`crm_update_contact`)
- Log every call, email, or meeting as a CRM activity
- Create tasks for follow-ups with due dates (`crm_create_task`)

### 3. Propose — CRM + Gmail + QuickBooks/Odoo
When it's time to send a proposal:
- Move deal to "Proposal" stage
- If QuickBooks is connected: create an estimate for the deal value
- If Odoo is connected: create a quotation via the sales module
- Email the proposal via Gmail (`send_email`)
- Create a follow-up task (3 days out)

### 4. Negotiate — CRM + Gmail
During negotiation:
- Move deal to "Negotiation"
- Update deal value and probability as terms change
- Log every touchpoint as a CRM activity
- Watch for stalled deals — if no activity in 5+ days, flag and follow up

### 5. Close — CRM + QuickBooks/Odoo
When the deal closes:
- Move deal to "Won" (or "Lost" with notes on why)
- If QuickBooks: convert estimate to invoice
- If Odoo: confirm the sales order and create an invoice
- Log the close activity
- Create onboarding or delivery tasks if needed

## Cross-Tool Quick Reference

| When this happens...              | Do this...                                        |
|-----------------------------------|---------------------------------------------------|
| New email from unknown sender     | Check CRM → create contact + deal if new          |
| Email from existing contact       | Log as CRM activity, check for open deals         |
| Meeting scheduled                 | Log as CRM activity, link to deal if relevant     |
| Task comes due                    | Follow up via Gmail, update CRM                   |
| Deal closes (won)                 | Create QuickBooks/Odoo invoice                    |
| Deal closes (lost)               | Log reason in deal notes, update contact status   |

## Stale Deal Rules
- **5 days** no activity on a Lead or Qualified deal → send a follow-up email
- **3 days** no response after Proposal sent → nudge with a follow-up
- **7 days** stalled in Negotiation → flag to the user as at-risk

## BambooHR
When staffing or capacity questions come up during sales:
- Check team availability before committing to delivery dates
- Look up employee skills when scoping project work
- Use org structure to identify who would handle the account

## Key Principles
- **Always log**: every email, call, and meeting gets a CRM activity entry
- **Always task**: if something needs to happen later, create a CRM task with a due date
- **Always update**: deal values, stages, and contact details stay current in real time
- **Proactive, not reactive**: don't wait to be asked — flag stale deals, suggest follow-ups, keep the pipeline moving
