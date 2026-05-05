# Todoist Setup

Connect your Todoist account so your Chatty agents can create, manage, and complete tasks and projects on your behalf.

## Prerequisites

- A Todoist account (free or Pro)

## Step 1: Get Your API Token

1. Open [Todoist](https://todoist.com) and log in
2. Click your avatar (top-left) > **Settings**
3. Go to **Integrations** > **Developer**
4. Click **Copy API token**

> **Note:** Your API token gives full access to your Todoist account. Keep it private. You can regenerate it at any time from the same page (this invalidates the old one).

## Step 2: Connect in Chatty

### Local

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations**
3. Find **Todoist** and click **Setup**
4. Paste your API token and click **Connect**

### Railway

1. Open your Chatty instance on Railway
2. Go to **Settings** > **Integrations**
3. Find **Todoist** and click **Setup**
4. Paste your API token and click **Connect**

Todoist credentials are entered in the Chatty UI, not as environment variables -- so the setup is the same on both local and Railway.

## What Your Agents Can Do

Once connected, your agents can:

- **View tasks** -- list all tasks, filter by project, label, or due date using Todoist's filter syntax
- **Create tasks** -- with titles, descriptions, due dates, priorities, projects, and labels
- **Quick-add tasks** -- using natural language like "Buy milk tomorrow #Shopping @errands p1"
- **Update tasks** -- change title, description, priority, due date, or labels
- **Complete and reopen tasks** -- mark tasks done or undo a completion
- **Move tasks** -- between projects and sections
- **Delete tasks** -- permanently remove tasks
- **View completed tasks** -- see what's been done recently
- **Manage projects** -- list, create, and update projects
- **View sections** -- see how projects are organized
- **Work with comments** -- read and add comments on tasks
- **List labels** -- see available labels for organizing tasks

Example questions you can ask:

- "What are my tasks for today?"
- "Add a task to call the dentist tomorrow"
- "Show me all overdue tasks"
- "Create a task 'Review proposal' in the Work project with priority 1"
- "Complete the groceries task"
- "What tasks are in my Shopping project?"
- "Move the dentist task to the Personal project"
- "What did I complete this week?"

## Notes

- **Write tools require confirmation** -- creating, updating, completing, moving, and deleting tasks will ask for your approval before executing (in normal tool mode)
- **Priority numbering** -- Chatty uses p1 (urgent) through p4 (normal), matching what you see in the Todoist app
- **Filter syntax** -- your agent can use Todoist's powerful filter language (e.g. "today | overdue", "#Work & p1", "due before: next Friday")
- **Quick Add** -- the quick-add tool parses natural language just like Todoist's quick-add bar, including `#Project`, `@label`, and `p1`-`p4` syntax
- Credentials are encrypted at rest in your Chatty instance
