# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Chatty, **please do not open a public issue.**

Instead, email **willwilson101@gmail.com** with:

- A description of the vulnerability
- Steps to reproduce it
- The potential impact

I'll respond within 72 hours and work with you on a fix before any public disclosure.

## Scope

Chatty handles sensitive data including AI provider API keys and OAuth tokens. Security issues in these areas are especially important:

- Authentication and session handling
- Credential storage and encryption
- API key exposure
- Cross-site scripting (XSS) or injection vulnerabilities
- Integration authentication (OAuth flows, webhook secrets)

## Supported Versions

Security fixes are applied to the latest version on the `master` branch.
