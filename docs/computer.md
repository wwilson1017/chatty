# The virtual computer

Give your agents a computer of their own: a Linux desktop (Chromium, a terminal, a file manager, LibreOffice Writer and Calc) that runs as a container next to Chatty. An agent drives it itself, in the conversation: it reads pages, clicks, types, runs commands and handles files. For long chores it hands a task to a **helper**, a loop in Chatty's backend that runs a cheaper model (Claude Sonnet 5.5 by default) in the background and reports back with a summary and any files. You can watch the screen live, take it over to sign in to a site, and nothing that spends money or leaves the computer for good happens without your approval.

It is optional and off until you add one and turn it on.

## Add a computer

### On Railway

If your project already has a `computer` service (newer template deployments do), **Settings → Integrations → Computer** shows it as online; skip to [Turn it on](#turn-it-on).

Otherwise the card adds one for you:

1. Create a token at [railway.com/account/tokens](https://railway.com/account/tokens). An **account** or **workspace** token works; a project token can't create services.
2. Paste it into the card and press **Add computer to this Railway project**.
3. Chatty creates a service named `computer` in the same project and environment from `ghcr.io/wwilson1017/chatty-computer:latest`, gives it a fresh 48-character `COMPUTER_SECRET` and `PORT=8080`, attaches a volume at `/data` and deploys it. Chatty saves the private address (`http://computer.railway.internal:8080`) and the secret in its encrypted credentials, so Chatty itself isn't redeployed.
4. The card says **Starting up** while Railway downloads the image (a minute or two), then **Online**.

The token is used for those three API calls and nowhere else: not stored, not logged, not shown in errors. You can delete it in Railway as soon as the card shows Online.

The service has no public domain. Only Chatty reaches it, over the project's private network, with the secret. It costs about a dollar a month while idle (the container keeps about 100 MB of memory), more while it works, plus volume storage at Railway's usual rate.

If Railway refuses a step after the service exists (for example a volume limit on your plan), the card says so and Chatty keeps the address and secret. Finish in the Railway dashboard: give the `computer` service a volume at `/data` and deploy it.

**Doing it by hand instead.** In the Railway dashboard add a service from the image above with variables `COMPUTER_SECRET` (32 characters or more) and `PORT=8080`, a volume at `/data` and no public domain. Then on the `chatty` service set `COMPUTER_URL=http://${{computer.RAILWAY_PRIVATE_DOMAIN}}:8080` and `COMPUTER_SECRET=${{computer.COMPUTER_SECRET}}` (Chatty redeploys). Environment variables win over anything saved from the card.

### Locally with `python run.py`

With Docker installed and running, `run.py` asks once:

```
Give your agents a virtual computer (a Docker container, ~1.4 GB download)? [y/N]
```

- **Yes** writes `COMPUTER_URL=http://127.0.0.1:8765` and a fresh `COMPUTER_SECRET` to `.env`, then starts a container named `chatty-computer` with a Docker volume (also `chatty-computer`) at `/data`. The port is bound to `127.0.0.1`, so nothing else on your network can reach it. Every later `python run.py` starts the same container again.
- **No** writes an empty `COMPUTER_URL=` to `.env` so you aren't asked again. Delete those lines to get the question back.
- **Without Docker** you get a one-line pointer to this guide and Chatty runs as before.

`docker logs chatty-computer` shows the computer's own log. `docker rm -f chatty-computer` and a new `python run.py` recreate it with the latest image; the volume keeps your data.

### Anywhere else

Run the container where Chatty can reach it, with your own secret of at least 32 characters:

```bash
docker run -d --name chatty-computer --restart unless-stopped \
  -p 127.0.0.1:8765:8080 -v chatty-computer:/data \
  -e COMPUTER_SECRET=<your secret> --shm-size=1g \
  ghcr.io/wwilson1017/chatty-computer:latest
```

Then set `COMPUTER_URL` (for example `http://127.0.0.1:8765`) and `COMPUTER_SECRET` (the same value) in Chatty's environment or `.env` and restart Chatty.

The control API is plain HTTP protected by the secret. Keep it on the same host, a private network or a VPN; never publish the port to the internet. `--shm-size=1g` is for Chromium, which crashes on Docker's default 64 MB. To update, `docker pull` the image and recreate the container; `/data` survives.

## Turn it on

- **The switch on the card.** Chatty enables the computer only when it can reach it and both speak the same control-API version; otherwise it tells you what's wrong.
- **Keep the computer running.** *Close when idle (after 30 min)*, the default, stops the desktop and Chromium after 30 minutes without activity; the container stays up and the next task brings everything back in a few seconds. *Always on* keeps the desktop up for instant starts.
- **Agents that can use it.** Untick an agent to keep it off the computer. Each listed agent has **Open the screen** and **Signed-in sites**.

## How agents use the computer

**Directly, first.** An agent drives the computer itself with `computer_browser` (read a page as text, click, type, navigate, switch tabs), `computer_shell` (run a command), `computer_files` (list, read or write files in its folder) and `computer_screen` (look at the screen; click, type, scroll or drag). Its own model does the work, in the conversation you're having with it. The first call in a turn takes the screen and the end of the turn gives it back. Each such session shows on the card as a **Direct** row with its step log.

- **The screen.** `computer_screen` is for what the text browser can't do: canvas apps, dragging, checking how a page looks, other windows. Each screenshot numbers the browser page's clickable controls; the agent clicks by number (or by pixel), and every action comes back with a fresh screenshot. A number is good for one click from the latest screenshot only, and at the moment of the click Chatty and the computer check that the same control (role, name and position within 4 pixels) is still under it; otherwise nothing is clicked. A click Chatty can't identify in the browser page, in a desktop app say, stops for your approval like a purchase.
  - Only agents on models that take images get it: model ids starting `claude-`, `gemini-`, `gpt-4o`, `gpt-4.1`, `gpt-5` or `gpt-6`. Ollama and Together models, and OpenAI's text-only reasoning models, work from the text browser, the shell and files.
  - Screenshots are shown to the model but not saved in the chat history, and only the last three stay in the conversation during a turn. Each one is kept in the session's step log on the card for 14 days.
- **The ceiling.** Once an agent has used the computer, its turn may take up to 100 model steps (instead of 20 in chat, or 5 to 10 in the background), and it can make up to 100 computer calls in that turn. Direct work has no money cap of its own: it's part of the agent's turn.
- **Approvals.** The same checks as for the helper stop every consequential click (see [Approvals and purchases](#approvals-and-purchases)). Nothing is clicked; the agent tells you it's waiting for your approval and can't use the computer again in that turn. When you approve, Chatty makes that one click and the agent gets a new turn to check the outcome, carry on, and tell you how it went.
- **A busy screen.** If the helper or another agent has the screen, the agent waits up to 30 seconds, then hands the work to the helper, which queues.
- **Handing off.** For chores of more than about 20 steps, or anything that needn't finish while you wait, the agent calls `computer_task("…")`. That frees the screen, and the helper carries on in the same browser, with the agent's own profile and logins.
- **Signing in.** The agent never types passwords. It asks you to sign in on the screen yourself (**Open the screen**, then **Take control**).

**Through the helper.** `computer_task("…")` queues a task. The helper takes the screen, works through it with a browser, a shell and files, and the agent gets at most one turn to tell you the result in the same conversation (and on Telegram or WhatsApp if that's where you asked). An agent can check or cancel its own tasks (`computer_task_get`, `computer_task_list`, `computer_task_cancel`), fetch a file from its folder (`computer_file_get`, which lets Gmail and Drive tools send it on) and ask about the computer (`computer_info`). A follow-up is always a new task that continues the chain.

- **One screen.** Tasks run one at a time; the rest queue. Your own requests go before background work. An agent driving directly holds the screen only during its turn.
- **Per agent.** Each agent has its own Chrome profile (its logins) and its own folder, `/workspace/<agent>`, with `downloads/` and an `inbox/` for files you attached in chat. `/workspace/shared` is common to all.
- **Caps per helper task chain:** 500 steps, 2 hours of running time and a $10 budget. At a cap the task stops and the agent reports what it has, with no extra model call. The dollar figure is a budget enforced on conservative estimates, not a hard guarantee (see [Known limits](#known-limits)).
- **Models.** The helper's model needs a known price in Chatty's pricing table or it is refused. Screenshot-and-click needs a Claude model; with other providers the helper gets a text browser, the shell and files.
- **Background work.** Scheduled actions and heartbeats can use the computer too. A scheduled action can carry a short **Allowed without asking** list of site + button pairs so routine submissions go through unattended; editing the action's prompt clears that list, and purchases always ask.

**In groups, only you.** In a Telegram group, the computer works only for messages from your own Telegram account, the one paired with the agent in the dashboard. Anyone else's request is refused, whether it would drive the computer or hand it a task. Approval cards and takeover links never go to a group: they come to your private chat with the agent (and the Computer card). The group sees only the agent's replies.

## Approvals and purchases

Before every click, key press or submission that could leave the computer, its target is checked, whether the agent or the helper is driving. These stop and ask you:

- **Buy:** place order, buy, pay, purchase, subscribe, donate, transfer; any button on a cart, checkout, payment or billing page.
- **Delete:** delete, remove or close an account, erase, empty trash, cancel a subscription or order.
- **Post:** post, publish, tweet, share, comment, reply, submit a review.
- **Send:** send, reply all, forward, and Ctrl/Cmd+Enter anywhere.
- **Any other form submission** not positively identified as a login, a search, or cart legwork (add to cart, quantities, coupons, a shipping step), and generic confirmations such as Confirm, Yes, OK, Agree, Save, Update, Create or Register.

When something is stopped, the task (or the agent's direct session) ends as *waiting for your approval* and you get a message with a screenshot on Telegram (if the agent has a bot) and an approval box on the card. It shows the **checked facts** (site, button text, the order total the page shows) separately from the helper's own reason, if it gave one, which is not verified. **Approve** runs a follow-up that re-opens the page and performs exactly that one action, bound to the site, page, form, recipients and, for a purchase, the total; if any of them changed in the meantime, you get a new request instead of the click. **Deny** ends it. Approvals expire after 24 hours.

- **Each purchase is approved on its own**, and the total is checked again at the moment of the click.
- **"Take over to do this yourself"** appears when the details can't be pinned down, for instance no single order total on the page or a message composer with no readable recipients. Approving it brings the agent's page up for you to finish by hand.
- **Outcome unknown.** If the connection drops right as an approved click goes out, the task ends with "I clicked X and couldn't confirm what happened" and a screenshot. Nothing consequential is ever retried on its own; check the site.

These checks catch mistakes and hostile pages, not a determined attacker: whoever drives (the agent or the helper) has a shell with sudo and could in principle drive Chrome around them. Their instructions forbid that, and every step is logged. A click by pixel that Chatty can't identify in the browser page (a desktop app, a system dialog) stops for approval too, or becomes a take-over card. A page's own scripts can still change it between Chatty's last check and the click; the checks narrow that window rather than close it.

## Watching and logins

**Open the screen** (from the card, or the link an agent sends you) shows the live desktop. Watching is view-only: nothing you do reaches the screen.

**Take control** pauses whoever is driving: while you hold the screen, every request from the agent or the helper is refused, including screenshots and page reads. Type, click, sign in; on a phone there is a Type box with Enter, Backspace, Tab and Esc. **I'm done** hands the screen back and the helper continues from a fresh look at the page. Control also ends 60 seconds after your connection drops without coming back, or after 15 minutes.

**Signing in.** When the helper reaches a login page it stops and sends you a link to take over. You type the password; the helper never sees it. Password fields are never read, and screenshots stop during your turn. The cookies stay in that agent's Chrome profile on the computer, so the next task is already signed in. If nobody takes over within 15 minutes the task ends with "sign-in needed".

**Signed-in sites** on the card lists, per agent, the sites with stored data. **Sign out** clears that site's cookies and stored data on the computer, whether or not that agent's browser is running; **Reset browser** clears the whole profile. Neither tells the site's servers, so a session may stay valid there until it expires.

## What persists

Everything under `/data` survives restarts, image updates and Railway redeploys: each agent's `/workspace/<agent>` and `/workspace/shared`, the Chrome profiles (logins), the home directory (`/data/home`, so `pip install --user` and tool configs stay), the computer's own settings and its action journal. Anything else in the container, including packages installed with `apt`, is gone when the container is replaced; running programs don't survive a restart. Deleting the volume is a factory reset. Chatty's backup ZIP does not include the computer's volume; use Railway's volume backups or back up the Docker volume yourself.

## Trust model

- **The secret.** Every call carries it as a bearer token; Chatty stores it encrypted like every other credential, and the computer refuses to start with a secret under 32 characters. The API has no TLS of its own, which is why it lives on a private network.
- **No wall between agents.** All agents share one Linux user with sudo on the computer. Separate Chrome profiles stop them signing each other out, but a program one agent runs can read another agent's files and logins. Treat every agent allowed on the computer as one trust level, or exclude the ones you don't want there.
- **What the agent and the helper see:** the task text, page contents with password values removed, screenshots (a masked password field shows as dots), and the files in the agent's folder. Chatty never knowingly passes a password or an API key to either.
- **Pages are untrusted.** Everything read from a website is wrapped as untrusted data, but instructions hidden in a page are a real risk. The approval gates exist for exactly that case.
- **Command MCP servers** that run on the computer receive their key as an environment variable, only when the process starts, held in memory. Any process on the computer could still read it, and the server itself can print it. Prefer hosted servers; give command servers narrow, read-only, revocable keys.
- **Every step is logged** on the card (tool, result excerpt, screenshot), kept 14 days.
- **Turning the integration off** stops a running task (or a direct session) at its next step, closes open viewers and makes pending approvals impossible to approve.

## Known limits

- **Datacenter IP.** Expect more CAPTCHAs and blocks than from your own connection. Take over and solve them yourself; routing the browser through your own connection comes later.
- **One screen.** Tasks queue, and a takeover can hold the queue for up to 15 minutes.
- **The $10 limit is a budget, not a guarantee.** It is enforced on conservative estimates before each model call and holds as long as your provider bills at or below the rates in Chatty's pricing table. Steps and time are hard limits.
- **Screenshots need a model that takes images.** The helper's screenshot-and-click needs a Claude model, and an agent's own `computer_screen` one of the models listed above; the rest get the text browser, the shell and files. Two identical controls in the same place on screen can't be told apart.
- **No wall between agents** (above), and gates that stop mistakes rather than a determined attacker.
- **Out of scope:** native apps, payment infrastructure, Windows or macOS, a computer per agent.

## Troubleshooting

- **Card says Offline.** On Railway open the `computer` service's logs; a `COMPUTER_SECRET` under 32 characters stops it from starting. Locally, `docker ps` and `docker logs chatty-computer`.
- **"The computer speaks control API vX; this Chatty needs v1.x."** One side is out of date. Redeploy the computer service (it pulls `latest`) or update Chatty, whichever is older.
- **"Railway rejected the token."** Use an account or workspace token, not a project token, and make sure it hasn't been deleted.
- **"The computer service was created, but …"** Finish in the Railway dashboard: a volume at `/data`, then deploy.
- **Starting up never ends.** The image is about 1.4 GB; a slow pull can take several minutes. If the service's deploy failed, redeploy it from the dashboard.
- **Chromium crashes or shows a blank page** on your own Docker host: start the container with `--shm-size=1g`.
- **Lots of CAPTCHAs.** See Known limits; take over and solve them, then hand back.
