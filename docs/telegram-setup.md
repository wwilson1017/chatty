# Telegram Setup

Connect a Telegram bot to your Chatty agent so you can chat with it from the Telegram app on your phone or desktop.

## Prerequisites

- A Telegram account
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Step 1: Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a display name for your bot (e.g., "My Chatty Agent")
4. Choose a username for your bot (must end in `bot`, e.g., `my_chatty_agent_bot`)
5. BotFather gives you a **bot token** — copy it

## Step 2: Connect in Chatty

### Local

1. Start Chatty with `python run.py`
2. Open the agent you want to connect
3. Go to the agent's settings and find the **Telegram** tab
4. Paste your bot token and save
5. Chatty validates the token and starts **polling** for messages

In local development, Chatty uses long-polling since there's no public URL for webhooks. This works fine — messages just may take a moment longer to arrive.

### Railway

1. Open your Chatty instance on Railway
2. Open the agent you want to connect
3. Go to the agent's settings and find the **Telegram** tab
4. Paste your bot token and save
5. Chatty validates the token and registers a **webhook** automatically

On Railway, Chatty uses webhooks so responses are instant — Telegram pushes messages directly to your Chatty URL.

## Step 3: Start Chatting

1. In Telegram, search for your bot by its username
2. Send it a message — your Chatty agent responds

## Group Chats

Your agent can also participate in Telegram group conversations. See [Telegram Group Chat Setup](telegram-group-chat.md) for details on group chat configuration, including bot-to-bot conversations with multiple agents.

## What Your Agents Can Do

Once connected, your agent has access to all its normal capabilities through Telegram — memory, integrations, tools, and personality all carry over. You're chatting with the same agent, just from a different interface.

## Notes

- Each Chatty agent needs its own Telegram bot (one token per agent)
- Bot tokens are long-lived — no refresh or re-auth needed
- Local: uses polling (no public URL required)
- Railway: uses webhooks (automatic, no configuration needed)
