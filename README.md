# Instagram to Telegram Sync

A small GitHub Actions project that checks an Instagram profile every 6 hours and reposts new posts to Telegram.

The default setup intentionally uses only **4 repository values**:

| Type | Name | What it is |
| --- | --- | --- |
| Variable | `INSTAGRAM_USERNAME` | Instagram username to monitor |
| Variable | `TELEGRAM_CHAT_ID` | Telegram channel/chat destination |
| Secret | `TELEGRAM_BOT_TOKEN` | Telegram bot token from BotFather |
| Secret | `APIFY_TOKEN` | Apify API token used to read Instagram |

That is all that is required for the normal GitHub Actions deployment.

## Variables vs Secrets

Use a **Variable** for ordinary configuration that is not a credential. In this project the Instagram username and Telegram destination are configuration, so they are Variables.

Use a **Secret** only for credentials that would let somebody access an account/API or spend quota. The Telegram bot token and Apify token are therefore Secrets.

## Setup

Open:

**Settings → Secrets and variables → Actions**

### Variables

Create:

- `INSTAGRAM_USERNAME` — for example `some_public_profile`
- `TELEGRAM_CHAT_ID` — for example `@my_channel` or a numeric Telegram chat ID

### Secrets

Create:

- `TELEGRAM_BOT_TOKEN` — token from BotFather
- `APIFY_TOKEN` — your Apify API token

No Telegram API ID, API hash, Telethon session, proxy, browser cookie, HMAC key, or extra enable switch is required for the default deployment.

The Telegram bot must have permission to post in the destination channel/chat.

## First run

After adding the 4 values above:

1. Open **Actions → Instagram to Telegram → Run workflow**.
2. Enable `initialize_only`.
3. Run it once.

This records the currently visible Instagram posts without sending them to Telegram, so old posts are not reposted after deployment.

After that, the scheduled workflow runs automatically every 6 hours. There is no separate `SYNC_ENABLED` variable.

You can also use `dry_run` for a manual test that downloads/checks posts without sending them.

## Default behaviour

The public deployment uses:

- Instagram source: Apify Instagram Scraper
- Telegram sender: Telegram Bot API
- check window: 6 posts
- initial baseline: 6 posts
- Apify local safety cap: 1800 results per billing cycle
- Apify billing cycle start day: 26
- schedule: every 6 hours

These operational defaults live in `config.example.yml`; they are not credentials.

## State

`data/state.json` prevents duplicate reposts. Instagram post identifiers are stored as deterministic keyed hashes rather than raw shortcodes. The default deployment derives the internal state key from an existing credential, so there is **no extra state secret to configure**.

The state file may also contain non-sensitive numeric Apify usage counters.

## Local run

```bash
python -m pip install -r requirements.txt
```

Set the same four environment variables locally and run:

```bash
python -m insta_tg_sync.cli --config config.example.yml
```

Useful options:

```bash
python -m insta_tg_sync.cli --config config.example.yml --dry-run
python -m insta_tg_sync.cli --config config.example.yml --initialize-only
python -m insta_tg_sync.cli --config config.example.yml --validate
```

## Advanced backends

The Python package still contains optional Telethon, browser, `curl_cffi`, Instaloader, proxy, and fallback support for developers who want to build a more complex deployment. Those options are intentionally **not part of the default GitHub Actions setup**.

For the normal Instagram → Telegram use case, you do not need a Telethon session or any of those extra credentials.

## Public repository safety

Real API tokens are never committed to the repository. Runtime files such as Telegram sessions, browser storage, proxy files, downloaded media, `.env` files, and debug output are ignored by Git.

Pushes run the test suite. The production sync runs only for manual workflow executions or the 6-hour schedule once `INSTAGRAM_USERNAME` and `TELEGRAM_CHAT_ID` Variables exist.
