# Instagram to Telegram Sync

A configurable Python project that monitors one or more public Instagram accounts and forwards new posts to Telegram.

The repository is designed to be safe for public hosting: account names, Telegram destinations, API credentials, proxy credentials, browser sessions, and other private runtime values are supplied through environment variables or GitHub Actions secrets instead of being committed to source control.

## Features

- Multiple Instagram backends: `apify`, `curl_cffi`, `instaloader`, `browser`, and `auto` fallback mode.
- Telegram Bot API and optional Telethon support.
- GitHub Actions scheduling and manual runs.
- Per-account duplicate prevention.
- Privacy-safe persisted state: account names and Instagram post shortcodes are stored only as keyed HMAC-SHA256 identifiers.
- Runtime log redaction for configured usernames, chat IDs, tokens, API hashes, proxy URLs, Apify tokens, and detected Instagram shortcodes.
- Optional proxy support and Playwright browser storage state.

## Installation

```bash
python -m venv .venv
python -m pip install -r requirements.txt
```

For browser mode, also install Chromium:

```bash
python -m playwright install chromium
```

## Configuration

`config.example.yml` contains only generic configuration. Private values are referenced by environment-variable name.

Example account configuration:

```yaml
accounts:
  - username_env: INSTAGRAM_USERNAME
    enabled: true
    telegram_chat_id_env: TELEGRAM_CHAT_ID
    check_limit: 6
    initial_skip: 6
```

For multiple accounts, use different environment variables:

```yaml
accounts:
  - username_env: INSTAGRAM_USERNAME_1
    telegram_chat_id_env: TELEGRAM_CHAT_ID_1
  - username_env: INSTAGRAM_USERNAME_2
    telegram_chat_id_env: TELEGRAM_CHAT_ID_2
```

The parser still accepts literal `username` and `telegram_chat_id` fields for local/private configurations, but public repositories should use the `*_env` form.

## GitHub Actions secrets

The included workflow expects these secrets as needed:

- `INSTAGRAM_USERNAME` — Instagram account to monitor.
- `TELEGRAM_CHAT_ID` — Telegram channel/group/user destination.
- `TELEGRAM_BOT_TOKEN` — Telegram Bot API token when using the bot backend.
- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` — required for Telethon.
- `TELETHON_SESSION_B64` — optional base64 Telethon session.
- `APIFY_TOKEN` — required for the Apify backend.
- `INSTAGRAM_PROXIES` — optional comma- or newline-separated proxy URLs.
- `IG_BROWSER_STORAGE_STATE` or `IG_BROWSER_STORAGE_STATE_B64` — optional Playwright login state.
- `STATE_HMAC_KEY` — recommended dedicated random key for hashing persisted identifiers.

If `STATE_HMAC_KEY` is not set, the state layer falls back to an available Telegram credential as the HMAC key. For a public deployment, a dedicated random `STATE_HMAC_KEY` is preferable.

## Local run

Set environment variables using your shell or an ignored `.env` loader of your choice, then run:

```bash
python -m insta_tg_sync.cli --config config.example.yml
```

Validate configuration without contacting Instagram:

```bash
python -m insta_tg_sync.cli --config config.example.yml --validate
```

Download/check without sending to Telegram:

```bash
python -m insta_tg_sync.cli --config config.example.yml --dry-run
```

Initialize/re-baseline the current fetch window without sending old posts:

```bash
python -m insta_tg_sync.cli --config config.example.yml --initialize-only
```

## Backends

- `apify`: hosted scraper path suitable for environments where Instagram blocks datacenter IPs.
- `curl_cffi`: no-login web request path with browser TLS impersonation.
- `instaloader`: simple direct Instagram access; may be rate-limited on shared/datacenter IPs.
- `browser`: Playwright Chromium extraction.
- `auto`: tries Apify, then curl_cffi, Instaloader, and browser.

Override the configured backend with:

```bash
python -m insta_tg_sync.cli --config config.example.yml --backend auto
```

## Privacy-safe state

The workflow persists `data/state.json` so scheduled runs do not repost the same Instagram content. The state file does **not** store configured Instagram usernames or raw post shortcodes. They are converted to keyed HMAC-SHA256 identifiers before being written.

Provider usage counters can remain as ordinary numeric metadata because they do not contain account credentials or destination identifiers.

Changing `STATE_HMAC_KEY` invalidates existing hashed identifiers. The next run will behave like a new state baseline for the configured account.

## Logging and debug data

The CLI installs an output redaction layer before synchronization begins. Configured usernames, Telegram destinations, credentials, proxy URLs, provider tokens, and detected Instagram shortcodes are replaced in stdout/stderr.

Browser storage state, Telethon sessions, local proxy files, debug snapshots, downloaded media, `.env` files, and logs are excluded by `.gitignore` and must never be committed.

The public GitHub Actions workflow intentionally does not upload browser debug snapshots on failure because those artifacts can contain profile-specific content.

## GitHub Actions

The included workflow runs every six hours by default and also supports manual execution. It can persist the privacy-safe hashed state back to the repository using the built-in `github-actions[bot]` identity.

Repository variables can be used for non-sensitive settings such as `SYNC_BACKEND`. Use GitHub Secrets for private values.

## Security checklist before publishing a fork

- Keep all real account names and destination IDs in GitHub Secrets or local environment variables.
- Never commit `.session`, browser storage state, proxy credential files, `.env`, downloaded media, or debug artifacts.
- Start a new public repository from a sanitized snapshot rather than publishing an older private repository whose Git history may contain personal metadata.
- Review commit author email settings before creating the first public commit.
