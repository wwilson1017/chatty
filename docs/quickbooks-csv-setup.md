# QuickBooks CSV Analysis Setup

Analyze your QuickBooks data by importing exported CSV files — no OAuth or developer account required.

This is a good option if you want quick financial insights without connecting directly to QuickBooks Online, or if you use QuickBooks Desktop.

## Prerequisites

- A QuickBooks account (Online or Desktop)
- CSV files exported from QuickBooks

## Local Setup

1. Start Chatty with `python run.py`
2. Go to **Settings** > **Integrations**
3. Find **QuickBooks CSV** and click **Setup**
4. That's it — the integration initializes a local database for your imported data

## Railway Setup

1. Open your Chatty instance on Railway
2. Go to **Settings** > **Integrations**
3. Find **QuickBooks CSV** and click **Setup**
4. Done — your data is stored on the Railway persistent volume

No environment variables or external credentials needed for either setup.

## Importing Data

Export CSV files from QuickBooks, then share them with your agent:

1. In QuickBooks, export the reports or transaction lists you want to analyze
2. In a Chatty conversation, tell your agent about the CSV file or paste the data
3. The agent imports and parses the data automatically

The importer handles common QuickBooks export formats from both Desktop and Online versions. Duplicate transactions are detected and flagged.

## What Your Agents Can Do

Once you've imported data, your agents can:

- **Query transactions** — search and filter your imported financial data
- **Analyze trends** — track expenses over time
- **Break down categories** — see where your money is going
- **Cash flow analysis** — understand income vs. expenses
- **Vendor and customer summaries** — see totals by vendor or customer

Example questions you can ask:

- "What were my total expenses last quarter?"
- "Show me a breakdown of spending by category"
- "Which vendor did I spend the most with this year?"
- "How does this month's revenue compare to last month?"

## Notes

- This is a **snapshot analysis tool** — it works with exported data, not a live connection to QuickBooks
- You can import multiple CSV files over time (incremental append)
- For real-time access to your QuickBooks data, use the [QuickBooks Online integration](quickbooks-setup.md) instead
- All data stays local in your Chatty instance
