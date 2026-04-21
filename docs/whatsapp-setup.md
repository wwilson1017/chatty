# WhatsApp Setup

Connect WhatsApp to your Chatty agent so you can chat with it from your phone — just like texting a contact.

## Prerequisites

- A WhatsApp account (personal or business)
- The WhatsApp Bridge sidecar running alongside Chatty

## Local Setup

1. Start the WhatsApp Bridge sidecar (a Node.js service in the `whatsapp-bridge/` directory):
   ```bash
   cd whatsapp-bridge
   npm install
   npm start
   ```
2. Add the bridge connection details to your `.env` file:
   ```env
   WHATSAPP_BRIDGE_URL=http://localhost:3001
   WHATSAPP_BRIDGE_API_KEY=your-shared-secret
   ```
3. Start Chatty with `python run.py`
4. Go to **Settings** > **Integrations**
5. In the **WhatsApp** section, select the agent you want to connect
6. Click **Connect WhatsApp** — a QR code appears
7. On your phone, open WhatsApp > **Linked Devices** > **Link a Device**
8. Scan the QR code — the status changes to "Connected"

## Railway Setup

1. In your Railway dashboard, add a new service for the WhatsApp Bridge (or use the one included in the template)
2. Set these environment variables on your Chatty service:
   ```
   WHATSAPP_BRIDGE_URL=http://whatsapp-bridge.railway.internal:3001
   WHATSAPP_BRIDGE_API_KEY=your-shared-secret
   ```
3. Open your Chatty instance and go to **Settings** > **Integrations**
4. In the **WhatsApp** section, select the agent you want to connect
5. Click **Connect WhatsApp** — a QR code appears
6. On your phone, open WhatsApp > **Linked Devices** > **Link a Device**
7. Scan the QR code — the status changes to "Connected"

## What Your Agents Can Do

Once connected, your agent works through WhatsApp the same way it does in the Chatty web interface. All capabilities carry over — memory, tools, integrations, and personality.

Send a message to the linked WhatsApp number and your Chatty agent responds in the conversation.

## Notes

- Each agent gets its own WhatsApp session (linked to a different number)
- The QR code refreshes frequently — scan it promptly when it appears
- If the session disconnects, go back to Integrations and scan a new QR code to reconnect
- The bridge uses [Baileys](https://github.com/WhiskeySockets/Baileys) to emulate WhatsApp Web — works with both personal and business accounts
- The bridge must be running for WhatsApp to work — if it goes down, messages won't be received until it's back up
