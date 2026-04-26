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

## Setup

### Option A: Both on Railway (Recommended)

The simplest path for production use. Both services run on Railway with public URLs.

#### Step 1: Deploy Paperclip on Railway

Deploy Paperclip using the Railway template:

1. Go to [Railway](https://railway.app) → **New Project** → **Deploy from GitHub Repo**
2. Select the `paperclip-railway` repo (or use the deploy button if public)
3. Wait for the build to complete (~10-15 minutes for first build)
4. **Generate a domain**: Click the service → **Settings** → **Networking** → **Generate Domain**
5. Check the **deploy logs** for your admin invite URL:
   ```
   ════════════════════════════════════════════
     ADMIN INVITE CREATED
   ════════════════════════════════════════════
     https://your-paperclip.up.railway.app/invite/pcp_bootstrap_...
   ════════════════════════════════════════════
   ```
6. Open the invite URL in your browser and create your admin account

#### Step 2: Set Up Your Company in Paperclip

1. After signing in, Paperclip walks you through creating your first company and CEO agent
2. The onboarding wizard creates a company and one agent (CEO) automatically
3. **Important**: After onboarding, go to your CEO agent → **Configuration** tab → change the adapter from "Claude Code" to **HTTP**
4. Set the webhook URL to your Chatty Railway instance: `https://your-chatty.up.railway.app/api/integrations/paperclip/heartbeat`
5. Create additional agents as needed (PM, Engineer, etc.) — set all to HTTP adapter with the same Chatty webhook URL

#### Step 3: Connect Chatty to Paperclip

1. Open Chatty → **Settings** → **Integrations** → scroll to **Paperclip**
2. Click **Setup**
3. Enter:
   - **Paperclip URL**: `https://your-paperclip.up.railway.app`
   - **Email**: Your Paperclip account email
   - **Password**: Your Paperclip account password
4. Click **Connect** — Chatty logs into Paperclip and auto-detects your company
5. Expand **Agent Mapping** and map each Paperclip agent to a Chatty agent
6. Click **Save Mapping**

### Option B: Both Local (For Development)

Best for tinkering, testing, and development.

#### Prerequisites

- Python 3.10+ and Node.js 18+ (for Chatty)
- Node.js 20+ and pnpm 9.15+ (for Paperclip)

#### Step 1: Run Chatty

```bash
git clone https://github.com/WWilson1017/chatty.git
cd chatty
python run.py
# Chatty runs at http://localhost:8000 (API) and http://localhost:5173 (UI in dev mode)
```

#### Step 2: Run Paperclip

```bash
git clone https://github.com/paperclipai/paperclip.git
cd paperclip
pnpm install
pnpm dev
# Paperclip runs at http://localhost:3100
```

Paperclip runs in **local trusted mode** — no authentication required. Open `http://localhost:3100` in your browser to access the UI directly.

#### Step 3: Create Your Company

1. Open Paperclip at `http://localhost:3100`
2. Complete the onboarding wizard — it creates a company and CEO agent
3. Go to your CEO agent → **Configuration** → change adapter to **HTTP**
4. Set webhook URL: `http://localhost:8000/api/integrations/paperclip/heartbeat`

#### Step 4: Connect Chatty

For local mode, Paperclip doesn't require authentication. In Chatty:

1. Go to **Settings** → **Integrations** → **Paperclip** → **Setup**
2. Enter the Paperclip URL: `http://localhost:3100`
3. For local trusted mode, you can use any email/password (the API doesn't require auth)
4. Map your agents and save

> **Note:** In local trusted mode, the email/password login step will fail since there's no auth. You may need to configure the integration manually or run Paperclip in authenticated mode locally. See the Paperclip docs for details.

### Option C: Chatty on Railway + Paperclip on Railway

This is the same as Option A. Both services get Railway public URLs and communicate over HTTPS. The Chatty webhook URL uses your Chatty Railway domain.

---

## Usage Guide

### Creating Your First AI Company

Here's a recommended approach for setting up your first Paperclip company with Chatty agents:

#### 1. Plan Your Org Structure

Start small. A good first setup:

| Role | Paperclip Agent | Chatty Agent | Responsibilities |
|------|----------------|--------------|------------------|
| CEO | Strategic lead | Agent with leadership personality | Strategy, decisions, reviews |
| PM | Project manager | Agent with organizational personality | Task breakdown, coordination, client comms |
| Analyst | Engineer/Researcher | Agent with analytical personality | Research, reports, data analysis |

#### 2. Create Chatty Agents First

In Chatty, create your agents through the onboarding wizard:
- Give each a distinct name and personality
- Add knowledge files with company info, client details, and SOPs
- Each agent should have a context file explaining how to use Paperclip tools

#### 3. Create Matching Paperclip Agents

In Paperclip's UI:
- Create agents with matching roles
- Set the reporting hierarchy (PM reports to CEO, Analyst reports to PM)
- **Set all agents to HTTP adapter** with the Chatty webhook URL
- Keep agents **paused** until everything is configured

#### 4. Map Agents

In Chatty's Paperclip integration settings:
- Expand Agent Mapping
- Map each Paperclip agent to its Chatty counterpart
- Save the mapping

#### 5. Create Issues

In Paperclip's UI, create issues (tasks) for your agents:
- Set a title and description with clear deliverables
- Assign to the appropriate agent
- Set priority (critical, high, medium, low)
- Issues start in **todo** status

#### 6. Test Interactively

Before enabling automated heartbeats, test in chat mode:
1. Open a Chatty agent's chat
2. Ask: *"Check Paperclip for tasks assigned to you"*
3. The agent should list its assigned issues
4. Ask: *"Claim issue [ID] and start working on it"*
5. Verify the agent uses `paperclip_checkout_issue` and `paperclip_update_issue` tools

#### 7. Enable Heartbeats (Optional)

Once interactive mode works:
1. In Paperclip, **resume** your agents
2. Paperclip will send periodic heartbeats to Chatty's webhook
3. Chatty runs the mapped agent headlessly
4. The agent checks its tasks, does work, and posts results as comments
5. Check Paperclip's issue threads to see agent activity

### Paperclip Tools Available to Agents

When the Paperclip integration is enabled, all Chatty agents get these tools:

| Tool | What It Does | Write? |
|------|-------------|--------|
| `paperclip_list_issues` | List issues with optional status/assignee filters | No |
| `paperclip_get_issue` | Get full issue details including comments | No |
| `paperclip_checkout_issue` | Atomically claim an issue | Yes |
| `paperclip_update_issue` | Change status, title, description, or add inline comment | Yes |
| `paperclip_add_comment` | Post a comment on an issue thread | Yes |

Write tools require approval in **normal** permission mode (the default). Set Paperclip to **full control** mode in the integration settings if you want agents to act without approval.

### Issue Statuses

Issues flow through these statuses:

```
backlog → todo → in_progress → in_review → done
                                    ↓
                                 blocked
```

- **backlog** — Not yet prioritized
- **todo** — Ready to start
- **in_progress** — Agent is actively working
- **in_review** — Work done, awaiting review
- **done** — Completed
- **blocked** — Cannot proceed, needs intervention
- **cancelled** — Abandoned

### Tips

- **Start with interactive mode** — Chat with agents about their Paperclip tasks before enabling automated heartbeats. This lets you verify the tools work and the agents understand their assignments.
- **Keep agents paused in Paperclip** until you've mapped them in Chatty. Otherwise, Paperclip will try to trigger heartbeats to a URL that isn't configured yet, creating cascading recovery issues.
- **One company at a time** — Start with a single Paperclip company. The integration auto-detects your company during setup.
- **Agent knowledge files** — Give each Chatty agent a context file explaining Paperclip and their role. Include their Paperclip agent ID so they know which issues are theirs.
- **Permission modes** — Use "Approval" mode (default) when testing so you can see and approve each tool call. Switch to "Full Control" once you trust the agent's behavior.

---

## Troubleshooting

### "Cannot reach Paperclip" during setup
- Check that the Paperclip URL is correct and the server is running
- For Railway: make sure you've generated a domain in Railway's networking settings
- For local: make sure Paperclip is running on the expected port (default: 3100)

### "Login failed: Invalid email or password"
- Verify your Paperclip account credentials
- For local trusted mode: Paperclip doesn't have auth, so the login step won't work. Use authenticated mode locally or configure manually.

### Recovery issue cascade in Paperclip
- This happens when an agent's adapter fails repeatedly. Paperclip creates recovery issues for each failure.
- **Fix**: Pause the agent in Paperclip, cancel the recovery issues, then fix the adapter config before resuming.
- **Prevention**: Always configure agents with the HTTP adapter pointing at your Chatty webhook URL, and keep agents paused until Chatty is connected and mapped.

### Agent tools return errors
- Check that the Paperclip integration is enabled in Chatty (Settings → Integrations)
- Verify the session hasn't expired — disconnect and reconnect if needed
- Check the Chatty backend logs for detailed error messages

### Heartbeats not triggering agents
- Verify the agent mapping is saved (Chatty Settings → Integrations → Paperclip → Agent Mapping)
- Check that the Paperclip agent's HTTP adapter URL points to the correct Chatty webhook endpoint
- For Railway-to-Railway: both services need public domains configured
- The webhook endpoint doesn't require Chatty login — it authenticates via a shared secret header (optional)
