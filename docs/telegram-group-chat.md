# Telegram Group Chat Setup

Chatty agents can participate in Telegram group conversations. In groups, bots respond when @mentioned or when someone replies to one of their messages.

## Basic Group Setup

1. In Chatty, go to the agent's **Telegram** tab
2. Toggle **Enable Group Chats** on
3. Create a Telegram group and add your bot
4. @mention the bot in the group to start chatting

## Bot-to-Bot Group Chat

Two or more Chatty agents can talk to each other in the same Telegram group. A human message kicks off the conversation, and the bots exchange messages up to a configurable turn limit.

### BotFather Setup (repeat for each bot)

1. Open `@BotFather` in Telegram
2. Send `/setbottobot`
3. Select your bot and **Enable** — this allows bots to see messages from other bots
4. Send `/setprivacy`
5. Select your bot and choose **Disable** — this lets the bot receive all group messages, not just commands and @mentions
6. _(Optional)_ Send `/setjoingroups`, select your bot, and choose **Disable** — this prevents other people from adding your bot to groups you don't control

### Chatty Dashboard Setup (repeat for each agent)

1. Go to the agent's **Telegram** tab
2. Toggle **Enable Group Chats** on
3. Toggle **Respond to Other Bots** on
4. Set **Max Bot Turns** (default 3) — the maximum number of consecutive bot-to-bot messages before the bots pause and wait for a human message

### Create the Group

1. Create a Telegram group
2. Add both bots to the group
3. Make both bots **admins** in the group
4. Send a message @mentioning both bots to kick off the conversation

### How It Works

- Human messages reset the bot turn counter — send a new message anytime to restart the conversation
- Each bot has its own conversation context scoped to the group
- The **Max Bot Turns** slider controls how many back-and-forth messages the bots exchange before pausing (1-10)
- A 2-second cooldown between responses prevents rapid-fire exchanges
