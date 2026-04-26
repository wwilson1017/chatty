# What is Chatty?

A plain-English guide for non-technical readers.

## The One-Sentence Version

Chatty is free software that lets you create your own AI assistants that know your business, connect to your tools, and work for you 24/7.

## Why It Exists

Right now, if a small business owner wants an AI chatbot that knows their business, they have two choices: pay $50-200/month for a SaaS product, or hire a developer. Chatty is a third option — it's free, you own it, and you only pay for the AI usage (like paying for electricity instead of renting a generator).

## How It Works

Think of Chatty like hiring a team of virtual assistants:

1. **You set it up once** — Either click a button to put it in the cloud (takes 5 minutes), or run it on your own computer
2. **You create agents** — Each agent is like a different employee. You give them a name, a personality, and tell them what they're good at. "Tom handles customer questions. Sarah does bookkeeping."
3. **You teach them** — Drag and drop documents (PDFs, Word docs) into the chat and the agent reads and remembers them. Upload your employee handbook, your price list, your FAQ — whatever they need to know.
4. **You connect your tools** — QuickBooks, Gmail, Google Calendar, Google Drive, Odoo, Telegram, WhatsApp. The agents can read your email, check your calendar, look up invoices, and more.
5. **You talk to them** — Open a browser on your phone or laptop, type a question, get an answer. Just like texting.

## What Can the Agents Actually Do?

- **Answer questions** about your business using the documents you uploaded
- **Read and send emails** through your Gmail
- **Check and create calendar events**
- **Look up customers, invoices, and bills** in QuickBooks
- **Manage a simple CRM** — track contacts, deals, tasks, and follow-ups
- **Chat with customers** on Telegram or WhatsApp on your behalf
- **Remember things** — they build memory over time and get better at helping you
- **Think overnight** — they review their conversations while you sleep and prepare for tomorrow

## What Does It Cost?

- **The software**: Free. Forever. No catch.
- **The cloud hosting** (Railway): ~$5/month — like a phone bill
- **The AI brain** (Anthropic, OpenAI, or Google): Pay per use. Light usage is a few dollars a month. You can also use **Ollama** to run AI models on your own computer for completely free.

Nobody takes a cut. No middleman. You pay the AI company directly for what you use.

## How Is This Different from ChatGPT?

ChatGPT is a general-purpose AI that doesn't know your business. Chatty agents:

- **Know your business** — they've read your documents
- **Connect to your tools** — they can actually do things, not just talk
- **Remember everything** — conversations carry over, they learn your preferences
- **Are always available** — they run 24/7, answer customers on Telegram/WhatsApp even when you're asleep
- **Are brandable** — your logo, your company name, your colors

## How Is This Different from Other AI Agent Platforms?

- **Free** — Most competitors charge $30-200/month
- **You own your data** — It lives on your server, not someone else's
- **Open source** — Anyone can see the code, improve it, or verify it's safe
- **No vendor lock-in** — Switch AI providers anytime. Use Anthropic today, OpenAI tomorrow, or run a free local model

## The Lean Thinking Angle

- **Eliminate waste**: No paying for features you don't use. No per-seat pricing. No annual contracts.
- **Pull system**: Agents only use AI when you ask them something — no wasted compute.
- **Continuous improvement**: The agents learn from every conversation (memory + dreaming). They get better over time without you doing anything.
- **Standard work**: Once an agent is trained, it handles routine questions the same way every time — consistent quality.
- **Reduce batch size**: Instead of one expensive enterprise system, deploy lightweight agents that each do one thing well.

## To Try It Right Now

**Cloud (easiest, 5 minutes):**

1. Go to [mechatty.com](https://mechatty.com)
2. Click "Get Started" or "Deploy on Railway"
3. Set a password
4. Wait 3 minutes for it to build
5. Open the URL, log in, paste an AI provider API key
6. Create your first agent and start chatting

**Local (free, no cloud):**

1. Install Python and Node.js on your computer
2. Download Chatty from GitHub
3. Run `python run.py`
4. Open your browser to localhost:8000
