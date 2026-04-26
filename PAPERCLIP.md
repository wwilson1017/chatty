# Paperclip Integration Guide

Connect Chatty to [Paperclip](https://github.com/paperclipai/paperclip) to give your AI agents organizational structure, task management, and multi-agent coordination.

## What is Paperclip?

Paperclip is an open-source orchestration control plane for AI agent companies. While Chatty gives each agent a brain (LLM, tools, personality), Paperclip gives the *team* structure:

- **Org charts** — Agents have roles (CEO, PM, engineer), titles, and reporting lines
- **Issues** — Tasks with status, priority, assignments, and comments — like Linear or Jira, but for AI agents
- **Heartbeats** — Paperclip periodically triggers agents to check their tasks and do work
- **Governance** — Budget caps, audit trails, and approval flows

Together, Chatty + Paperclip lets you run a coordinated team of AI agents that assign work, track progress, and communicate through structured task management.

## How It Works

```
Paperclip (Control Plane)               Chatty (Agent Runtime)
┌─────────────────────┐                 ┌──────────────────────────┐
│ Issues / Tasks      │                 │ AI Agents with LLM       │
│ Org Chart           │◄── tool calls ──│ + Paperclip tools        │
│ Agent Management    │                 │                          │
│ Budget Tracking     │── heartbeats ──►│ Webhook endpoint         │
└─────────────────────┘                 └──────────────────────────┘
```

**Two modes of operation:**

1. **Interactive (chat)** — Talk to a Chatty agent: *"Check Paperclip for my tasks"*. The agent uses Paperclip tools to list issues, claim work, update status, and post comments.

2. **Automated (heartbeat)** — Paperclip sends HTTP webhooks to Chatty on a schedule. Chatty runs the mapped agent headlessly — the agent checks its assignments, does work, and posts results back to Paperclip.

---

## Setup: Railway (Recommended)

This walks you through deploying both Chatty and Paperclip on Railway and connecting them. Total time: about 20 minutes.

### Part 1: Deploy Paperclip on Railway

#### 1.1 Click the deploy button

[![Deploy Paperclip on Railway](https://railway.com/button.svg)](https://railway.com/deploy/ZLeQVd?referralCode=HMgK-M)

This deploys Paperclip from a pre-configured Railway template. Click the button above, then click **Deploy** in Railway.

#### 1.2 Wait for the build

The first build takes **10-15 minutes** — it compiles the full Paperclip application from source. You'll see build progress in Railway's dashboard. Subsequent deploys are much faster due to caching.

#### 1.3 Generate a public domain

Once the build finishes and the service shows **Online**:

1. Click on the **paperclip-railway** service in your Railway project
2. Click the **Settings** tab
3. Scroll to **Networking**
4. Click **Generate Domain**
5. Railway assigns a URL like `paperclip-production-xxxx.up.railway.app`

Copy this URL — you'll need it throughout the setup.

#### 1.4 Find your admin invite URL

After the first deploy, Paperclip automatically generates an admin invite link. To find it:

1. Click on the **paperclip-railway** service
2. Click **Deployments** tab
3. Click **View logs** on the active deployment
4. Look in the **deploy logs** (not build logs) for a block like this:

```
════════════════════════════════════════════════════════
  ADMIN INVITE CREATED
════════════════════════════════════════════════════════
  https://your-paperclip-url.up.railway.app/invite/pcp_bootstrap_abc123...

  Expires: 2026-04-29T...
  Open this URL in your browser to create your account.
════════════════════════════════════════════════════════
```

5. Copy the full invite URL (the line starting with `https://...`)

> **Can't find the invite?** The invite is only generated on the very first deploy. If you missed it, you'll need to redeploy with a fresh database (delete the service and deploy again from the template).

#### 1.5 Create your Paperclip account

1. Paste the invite URL into your browser
2. You'll see a signup form — enter your **name**, **email**, and **password**
3. Click **Create Account**
4. You're now signed into Paperclip as the instance admin

### Part 2: Set Up Your Company in Paperclip

#### 2.1 Complete the onboarding wizard

After signing in, Paperclip walks you through creating your first company:

1. **Company name** — Enter your company or project name (e.g., "My Agency", "TNC")
2. **First agent** — The wizard creates a CEO agent automatically. Give them a name and role.
3. Click through to finish onboarding

You'll land on the company dashboard with your first agent visible in the left sidebar.

#### 2.2 Switch your agent's adapter to HTTP

This is the most important step. By default, Paperclip creates agents with the "Claude Code" adapter, which tries to run a CLI tool inside the container. **You need to switch it to HTTP** so Paperclip sends work to Chatty instead.

1. Click on your agent in the left sidebar (e.g., "Tim Sparks")
2. Click the **Configuration** tab
3. Find the **Adapter** section
4. Change the adapter type from **Claude Code** to **HTTP**
5. Set the **URL** to your Chatty Railway instance's webhook endpoint:
   ```
   https://your-chatty-url.up.railway.app/api/integrations/paperclip/heartbeat
   ```
6. Save the configuration

> **Why this matters:** If you skip this step, Paperclip will try to run the Claude CLI (which doesn't exist in the Railway container), fail repeatedly, and create hundreds of "Recover stalled issue" tasks. If this happens, pause the agent immediately and cancel the recovery issues.

#### 2.3 Pause your agent (recommended)

Keep your agent **paused** until Chatty is fully connected and mapped:

1. On your agent's page, click the **Pause** button (top right)
2. This prevents Paperclip from sending heartbeats before Chatty is ready

You'll resume the agent later after everything is connected.

#### 2.4 Create additional agents (optional)

To add more agents (PM, Engineer, Analyst, etc.):

1. Click the **+** next to **AGENTS** in the left sidebar
2. Set the agent's name, role, and title
3. Set the reporting hierarchy (e.g., PM reports to CEO)
4. **Switch each new agent to HTTP adapter** with the same Chatty webhook URL
5. Keep them **paused**

### Part 3: Connect Chatty to Paperclip

#### 3.1 Open Chatty's integration settings

1. Open your Chatty instance in a browser
2. Log in with your Chatty password
3. Click the **gear icon** (Settings) in the left sidebar
4. Click the **Integrations** tab
5. Scroll down to find **Paperclip**

#### 3.2 Sign in to Paperclip from Chatty

1. Click **Setup** on the Paperclip integration card
2. Fill in the three fields:
   - **Paperclip URL**: Your Paperclip Railway URL (e.g., `https://paperclip-production-xxxx.up.railway.app`)
   - **Email**: The email you used to create your Paperclip account
   - **Password**: Your Paperclip account password
3. Click **Connect**

Chatty logs into Paperclip, gets a session, and auto-detects your company. You'll see the Paperclip card update to show it's connected.

> **"Cannot reach Paperclip" error?** Make sure you included `https://` in the URL and that the Paperclip service is online in Railway.
>
> **"Login failed" error?** Double-check your email and password. These are your Paperclip credentials, not your Chatty password.

#### 3.3 Map your agents

Now tell Chatty which Chatty agent corresponds to which Paperclip agent:

1. On the Paperclip integration card, click **Agent Mapping** to expand it
2. You'll see a list of your Paperclip agents (e.g., "Tim Sparks (ceo)")
3. For each Paperclip agent, select the matching Chatty agent from the dropdown
4. Click **Save Mapping**

If you don't see any Paperclip agents, make sure you completed the Paperclip onboarding wizard and created at least one agent.

### Part 4: Test the connection

#### 4.1 Chat with your agent about Paperclip

1. Go back to Chatty's main screen
2. Click on the Chatty agent you mapped (e.g., the one mapped to the CEO)
3. Type: **"Check Paperclip for any tasks"**
4. The agent should use the `paperclip_list_issues` tool and report what it finds

If the agent successfully lists issues (or says there are none), the integration is working.

#### 4.2 Create a test task in Paperclip

1. Go to your Paperclip instance in the browser
2. Click **Issues** in the left sidebar
3. Click **+ New Issue** (or use the button at the top)
4. Enter a title and description, assign it to your agent, set priority
5. Go back to Chatty and ask your agent: **"Check Paperclip for new tasks"**
6. The agent should see the issue you just created

#### 4.3 Have your agent work on the task

Ask your agent to claim and work on the task:

- *"Claim that issue and start working on it"*
- *"Update the issue status to in_progress"*
- *"Post a comment on the issue with your findings"*

Each of these uses a Paperclip tool (checkout, update, add_comment). In **Approval** mode (the default), Chatty will ask you to approve each write action before executing it.

#### 4.4 Enable automated heartbeats (optional)

Once you've verified interactive mode works:

1. Go to Paperclip and **resume** your agent (click the Resume button)
2. Paperclip will send periodic heartbeats (every 30 seconds by default) to Chatty's webhook
3. Chatty runs the mapped agent headlessly — the agent checks its tasks, does work, and posts results
4. Check the issue threads in Paperclip to see the agent's activity

> **Important:** Only resume agents after the Chatty integration is connected and agent mapping is saved. Otherwise, the heartbeats will fail and create recovery issue cascades.

---

## Setup: Local Development

For tinkering and development. Both services run on your machine.

### Prerequisites

- Python 3.10+ and Node.js 18+ (for Chatty)
- Node.js 20+ and pnpm 9.15+ (for Paperclip)

If you don't have pnpm: `npm install -g pnpm`

### Step 1: Start Chatty

```bash
git clone https://github.com/WWilson1017/chatty.git
cd chatty
python run.py
```

Chatty runs at `http://localhost:8000`. Open it in your browser and complete the initial setup (set password, add an AI provider API key, create at least one agent).

### Step 2: Start Paperclip

In a separate terminal:

```bash
git clone https://github.com/paperclipai/paperclip.git
cd paperclip
pnpm install
pnpm dev
```

Paperclip runs at `http://localhost:3100`. Open it in your browser — in local mode, no login is required.

### Step 3: Create your company in Paperclip

1. Open `http://localhost:3100`
2. Complete the onboarding wizard (company name, first agent)
3. Go to your agent → **Configuration** → change adapter to **HTTP**
4. Set webhook URL: `http://localhost:8000/api/integrations/paperclip/heartbeat`
5. **Pause** the agent

### Step 4: Connect Chatty to Paperclip

1. In Chatty, go to **Settings** → **Integrations** → **Paperclip** → **Setup**
2. Enter URL: `http://localhost:3100`
3. Enter any email/password (local trusted mode doesn't validate credentials)
4. Expand **Agent Mapping**, map agents, and save

### Step 5: Test

Chat with your agent: *"Check Paperclip for any tasks assigned to you"*

---

## Usage Guide

### Planning Your Org Structure

Start small. A good first setup:

| Role | Paperclip Agent | Chatty Agent | Responsibilities |
|------|----------------|--------------|------------------|
| CEO | Strategic lead | Agent with leadership personality | Strategy, decisions, reviews |
| PM | Project manager | Agent with organizational personality | Task breakdown, coordination |
| Analyst | Engineer/Researcher | Agent with analytical personality | Research, reports, analysis |

### Creating Issues

In Paperclip's UI, create issues (tasks) for your agents:

- **Title**: Clear, actionable (e.g., "Q3 Revenue Strategy Review")
- **Description**: Include context, scope, and expected deliverables
- **Priority**: critical, high, medium, or low
- **Assignee**: The agent responsible for the work
- **Status**: Issues start as **todo**

### Issue Workflow

Issues flow through these statuses:

```
backlog → todo → in_progress → in_review → done
                       ↓
                    blocked
```

Your agents move issues through this workflow using Paperclip tools:
1. Agent sees a **todo** issue assigned to them
2. Agent claims it with `paperclip_checkout_issue` → moves to **in_progress**
3. Agent works on it and posts updates via `paperclip_add_comment`
4. Agent marks it done with `paperclip_update_issue` → moves to **done** or **in_review**

### Paperclip Tools Available to Agents

When connected, all Chatty agents automatically get these tools:

| Tool | What It Does | Needs Approval? |
|------|-------------|-----------------|
| `paperclip_list_issues` | List issues with optional status/assignee filters | No |
| `paperclip_get_issue` | Get full issue details including recent comments | No |
| `paperclip_checkout_issue` | Atomically claim an issue for an agent | Yes |
| `paperclip_update_issue` | Change status, title, description, or add inline comment | Yes |
| `paperclip_add_comment` | Post a comment on an issue thread | Yes |

In **Approval** mode (the default), Chatty shows you each write action and asks for confirmation before executing. Set the Paperclip permission level to **Full Control** in the integration settings if you want agents to act without asking.

### Giving Agents Paperclip Context

For best results, add a knowledge file to each Chatty agent explaining their Paperclip role. Create a file in the agent's context (Settings → Knowledge, or upload in chat) with content like:

```markdown
# Task Management

We use Paperclip for task coordination. You have tools to interact with it:

- Use paperclip_list_issues to check your assignments
- Use paperclip_checkout_issue to claim a task before working on it
- Use paperclip_update_issue to change status as you make progress
- Use paperclip_add_comment to post updates and findings

Your Paperclip agent ID is: [paste from Paperclip agent page]

Always check for new tasks when asked, and update issue status as you work.
```

---

## Reconnecting / Changing Instances

If you need to switch to a different Paperclip instance or your session expires:

1. Go to **Settings** → **Integrations** → **Paperclip**
2. Click **Disconnect**
3. Click **Setup** to connect to a new instance
4. Re-enter the URL, email, and password
5. Re-map your agents

---

## Troubleshooting

### "Cannot reach Paperclip" during setup

- Check that the URL is correct and includes `https://`
- Make sure the Paperclip service is **Online** in Railway
- For Railway: verify you've generated a public domain in **Settings** → **Networking**
- For local: confirm Paperclip is running on the expected port (default: 3100)

### "Login failed: Invalid email or password"

- Verify your Paperclip account credentials (not your Chatty password)
- Make sure you completed the Paperclip invite signup (check the deploy logs for the invite URL)

### Recovery issue cascade in Paperclip

This happens when an agent's adapter is misconfigured. Paperclip tries to trigger the agent, fails, creates a "Recover stalled issue" task, which also fails, creating another recovery issue, and so on.

**To fix it:**
1. **Pause** the agent immediately in Paperclip
2. Cancel the recovery issues (select all → cancel)
3. Go to the agent's **Configuration** tab
4. Make sure the adapter is set to **HTTP** (not Claude Code or Codex)
5. Make sure the webhook URL is correct and Chatty is running
6. **Resume** the agent only after Chatty is connected and mapped

**To prevent it:**
- Always set agents to HTTP adapter before resuming
- Always keep agents paused until Chatty is connected

### Agent can't find any issues

- Make sure issues are assigned to the correct Paperclip agent
- Check that the agent mapping is saved in Chatty
- Try asking the agent to list *all* issues, not just assigned ones: *"List all issues in Paperclip"*

### Session expired

Paperclip sessions can expire. If tools start returning auth errors:
1. Go to Chatty **Settings** → **Integrations** → **Paperclip**
2. Click **Disconnect**, then **Setup** to reconnect with your credentials

### Heartbeats not working

- The Paperclip agent's HTTP adapter URL must point to Chatty's webhook: `https://your-chatty.up.railway.app/api/integrations/paperclip/heartbeat`
- Both services need public domains on Railway
- Agent mapping must be saved in Chatty
- The agent must be **resumed** (not paused) in Paperclip
- Check Chatty's backend logs for webhook errors
