# Security Policy

## Supported version

Security fixes are applied to the current `main` branch.

## Reporting a vulnerability

If you find a security issue, please avoid publishing credentials, session data, private Instagram content, Telegram tokens, Apify tokens, proxy credentials, or other sensitive runtime values in a public issue.

If GitHub private vulnerability reporting is available for this repository, use it for security-sensitive reports. For ordinary non-sensitive bugs, open a regular GitHub issue with a minimal reproducible example.

## Secrets and private data

The default deployment expects credentials to be stored in GitHub Actions Secrets. Do not commit:

- Telegram bot tokens
- Apify API tokens
- Telegram/Telethon sessions
- browser cookies or storage-state files
- proxy credentials
- `.env` files
- downloaded private media or debug snapshots

If a credential is accidentally committed, revoke/rotate it immediately. Removing it from the latest commit alone does not remove it from Git history.
