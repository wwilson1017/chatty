# Privacy Policy

**Chatty** is a free, open-source personal AI agent platform. This policy describes how Chatty handles your data.

**Last updated:** April 5, 2026

## What Chatty Is

Chatty is self-hosted software that runs on your own infrastructure. You control where it runs, what data it accesses, and how that data is stored.

## Data Collection

Chatty itself does not collect, transmit, or share any user data with the Chatty project or its maintainers. All data remains on the infrastructure where you deploy Chatty.

## Third-Party Integrations

When you connect third-party services (QuickBooks Online, Google, OpenAI, Odoo, BambooHR), Chatty stores OAuth tokens and API credentials locally on your server. These credentials are encrypted at rest and are used solely to communicate with the services you have authorized.

Each third-party service has its own privacy policy:

- **QuickBooks Online / Intuit**: https://www.intuit.com/privacy/
- **Google**: https://policies.google.com/privacy
- **OpenAI**: https://openai.com/privacy

## Data Storage

- All data (chat history, agent configurations, credentials) is stored locally in SQLite databases and JSON files on your server.
- Credentials are encrypted at rest using Fernet symmetric encryption.
- No data is sent to any server operated by the Chatty project.

## AI Provider Usage

Chat messages are sent to the AI provider you configure (Anthropic, OpenAI, or Google) for processing. These interactions are governed by the respective provider's privacy policy and terms of service.

## Your Rights

Since all data is stored on your own infrastructure, you have full control over it. You can delete all data at any time by removing the `data/` directory.

## Contact

Chatty is maintained as an open-source project at https://github.com/wwilson1017/chatty. For questions, open an issue on GitHub.
