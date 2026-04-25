# Telegram Setup

Connect a Telegram bot to your Chatty agent so you can chat with it from the Telegram app on your phone or desktop.

## What You Need

- A Telegram account (free — install the Telegram app and sign up if you haven't already)
- A bot token (you'll create one in the next section — it's free and takes about a minute)

## How to Make a Bot Token

A bot token is the password Chatty uses to control your Telegram bot. You get one from **BotFather**, Telegram's official bot for creating bots.

1. Open Telegram.
2. In the search bar at the top, type **BotFather** and tap the result with the blue checkmark (the verified one — that's the official BotFather).
3. Tap **Start** to open a chat with BotFather.
4. Send the message: `/newbot`
5. BotFather will ask for a **display name** for your bot — this is what people see in chats. Type something like `My Chatty Agent` and send.
6. BotFather will then ask for a **username** — this must be unique across all of Telegram and must end in `bot` (for example, `my_chatty_agent_bot`). Type one and send.
7. BotFather replies with a message containing your **bot token**. It looks something like:
   ```
   123456789:ABCdefGhIJKlmNoPQRstuVwxyZ
   ```
   Copy this whole string. Treat it like a password — anyone with this token can control your bot.

That's it — your bot exists. Now you need to give the token to Chatty.

## How to Connect the Bot to Chatty

You have two options. Both work — pick whichever is easier for you.

### Option 1: Paste the Token Into the Agent Chat

This is the quickest way.

1. Open your Chatty agent.
2. Paste your bot token into the chat and send it. You can just paste it on its own, or say something like "here's my Telegram bot token: `123456789:ABCdef...`"
3. The agent recognizes the token, validates it with Telegram, and connects automatically. It'll confirm when it's done.

### Option 2: Use the Settings Menu

1. Open your Chatty agent.
2. Go to the agent's **Settings** and find the **Telegram** tab.
3. Paste your bot token into the field and click **Save**.
4. Chatty validates the token and connects.

## How to Start Chatting With Your Bot

1. In Telegram, search for your bot by the username you chose in step 6 above (e.g. `my_chatty_agent_bot`).
2. Tap **Start**.
3. Send a message — your Chatty agent will reply.

## Local vs. Railway

Chatty handles message delivery slightly differently depending on where it's running. You don't need to configure anything — it picks the right method automatically.

- **Local** (`python run.py` on your computer): Chatty uses **long-polling**, which means it asks Telegram for new messages periodically. Replies may take a moment longer.
- **Railway** (cloud-hosted): Chatty uses **webhooks**, so Telegram pushes messages directly to your Chatty URL. Replies are instant.

## Group Chats

Your agent can join Telegram groups too. See [Telegram Group Chat Setup](telegram-group-chat.md) for how to set that up, including running multiple agents that talk to each other.

## What Your Agent Can Do on Telegram

Once connected, your agent has all its normal capabilities through Telegram — memory, integrations, tools, and personality all carry over. You're chatting with the same agent, just from a different app.

## Notes

- Each Chatty agent needs its own Telegram bot — one bot token per agent.
- Bot tokens don't expire. Set it up once and it stays connected.
- If you ever lose your token, send `/mybots` to BotFather, pick your bot, and choose **API Token** to see it again. You can also revoke and regenerate it from there.
