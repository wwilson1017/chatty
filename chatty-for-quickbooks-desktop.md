# Connecting an AI Assistant to QuickBooks Desktop and Fishbowl

A practical look at the options for plugging an AI assistant into a manufacturing business that runs QuickBooks Desktop and Fishbowl Inventory.

---

## What we're trying to do

Imagine an AI assistant that actually knows your business — it can answer questions like:

- "What did we invoice last month, and who hasn't paid yet?"
- "Are we below reorder point on any raw materials?"
- "Draft polite follow-ups to customers 30+ days overdue, and let me approve before sending."
- "When a sales order comes in, check inventory and tell me if we can ship by Friday."
- "What was our gross margin on Product X last quarter?"

…all in plain English, by looking at your live QuickBooks and Fishbowl data — not by guessing, and not by asking you to copy-paste data into ChatGPT.

The platform we're considering is **Chatty** — a free, open-source AI assistant you run for yourself in the cloud. The question is whether and how it can plug into a setup like yours.

---

## Why your setup is harder than the average case

Most cloud AI tools that connect to QuickBooks assume **QuickBooks Online** — that's a website, so any cloud app can talk to it directly over the internet.

You're running **QuickBooks Desktop** on a computer in your office, and **Fishbowl** on a server on your network. To anything outside your office, those programs are invisible. There's no public web address to call.

This isn't a Chatty quirk — it's a fundamental difference between Desktop and Online software. Every solution has the same shape: **something has to live on your network and act as a translator** between your local QuickBooks/Fishbowl and the outside world.

---

## The realistic options

### Option 1 — Manual exports (works today, no setup)

You export reports from QuickBooks (CSV files) and upload them to Chatty when you want it to take a look. Chatty already supports this.

- **Pros:** Zero setup. Nothing new to install. Works this week.
- **Cons:** Not live data — you're working from a snapshot. Fine for a monthly review, not for "what's our cash position right now?"
- **Good for:** Trying it out before investing in anything bigger. The cheapest way to find out if the AI part is even useful for your style of questions.

### Option 2 — A paid bridge service (easiest "live" option)

Companies like **Conductor** sell exactly this: you install their small program on your QuickBooks machine, it makes QB Desktop look like a normal cloud service, and Chatty talks to it.

- **Pros:** Cleanest experience. Set up once and it just works. They maintain it.
- **Cons:** Roughly $50–$200/month per company file. Adds a third party in the middle of your data. Conductor handles QuickBooks but not Fishbowl — you'd still need another path for inventory.
- **Good for:** If you'd rather pay for reliability than wait for anything custom to be built.

### Option 3 — A custom local connector (the path we'd actually recommend)

Build a small program — call it the **App Bridge** — that runs on your QuickBooks machine. It speaks QuickBooks's language and Fishbowl's language locally, and quietly phones home to your Chatty in the cloud.

Here's what this would look like for you in practice.

**One-time setup (about 15 minutes, with someone helping):**

1. Spin up Chatty in the cloud. (One-click deploy on a service called Railway — gives you a private web address only you can log into.)
2. Download a small installer onto the QuickBooks Desktop machine. Double-click, next-next-finish.
3. Chatty shows you a 6-digit pairing code, the same way you'd set up a Roku. Type it into the installer's setup screen.
4. Done. The bridge handles everything from there.

**Day-to-day, what you'd see:**

- You use Chatty from any phone or laptop at your private web address.
- When you ask a question that needs QB or Fishbowl data, Chatty asks the bridge, the bridge looks it up locally, and the answer comes back in a few seconds.
- The bridge runs in the background like an antivirus or a printer driver. You don't think about it.

**Things a business owner would reasonably ask about:**

- **Firewall and IT.** No router changes, no port forwarding, no IT call. The bridge dials *out* to Chatty the same way your browser dials out to a website.
- **Where your data lives.** It's just your QB machine talking to your own Chatty instance in the cloud. No third party in the middle.
- **Fishbowl.** Same bridge, second adapter. The AI can see inventory, work orders, and manufacturing data, not just the financials.
- **Future-proofing.** The same bridge could later add ShipStation, UPS WorldShip, your warehouse database, etc. — anything else local on your network.

---

## Honest tradeoffs about Option 3

Worth being upfront about what this involves:

- **It has to be built.** This is a real piece of software, not a weekend project. Realistically, plan a few weeks of development for a solid v1 covering QuickBooks Desktop, plus more time to add Fishbowl.
- **It has to be maintained.** When QuickBooks releases an update, or Windows pushes a security patch, things can occasionally break and someone has to fix them. (This is partly why services like Conductor charge what they charge — running this stuff reliably is genuinely tedious.)
- **It has to be trustworthy.** It holds the keys to your books. Building it well means a signed installer, encrypted credentials, proper logging, and ongoing patches.

For one shop, with someone who can step in if it acts up, that's a reasonable amount of work. The upside is you'd own the result — no monthly fee, no third party, and the same bridge would help any other small manufacturer in the same boat.

---

## A suggested order of operations

1. **This week — try Option 1.** Export a few QuickBooks reports as CSV, load them into Chatty, ask it the kinds of business questions you'd actually want answered. It costs nothing, and it tells you whether the AI part is even worth pursuing for your style of work.
2. **If yes, and live data matters — go to Option 3.** Build the local bridge. It's the only path that's both free of ongoing fees and keeps your data on your own hardware.
3. **Keep Option 2 (Conductor) as a paid shortcut.** If you want live QuickBooks data right now and are willing to pay $50–200/month, it's a faster on-ramp. Just remember it doesn't cover Fishbowl on its own.

---

## What we'd need from you to move forward

If you want to seriously look at this, a few quick facts would help shape the work:

- Which edition and year of QuickBooks Desktop (Pro, Premier, or Enterprise — and the year, e.g. 2023, 2024).
- Which version of Fishbowl, and roughly how many SKUs / users / warehouses it manages.
- The Windows version of the machine that runs QuickBooks, and whether QB lives on that same PC or on a server.
- Roughly how many people would use Chatty (just you, you + a bookkeeper, the whole front office).

None of this is a commitment — it just lets us scope the bridge work realistically.

---

## Bottom line

- **There's no off-the-shelf "click here to connect" for QB Desktop + Fishbowl + cloud AI.** Anyone who tells you otherwise is selling you Option 2 with a markup.
- **There is a clean, doable path** — a small local bridge program on your QuickBooks machine, paired once with your private Chatty in the cloud. After that, you ask your business questions in plain English from your phone, and the AI actually knows the answers because it can see your real numbers.
- **Start cheap** with manual CSV exports to find out whether the AI part earns its keep before building anything custom.
