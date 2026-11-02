# Setup and troubleshooting

This guide supports one or more **public** Instagram profiles, each mapped to a Telegram channel. Use the [setup wizard](https://bl0ck154.github.io/instagram-to-telegram/) for a guided configuration.

## Create a copy

Use **Use this template** on the repository page, or fork the repository. In your copy, visit **Actions** and enable workflows if GitHub presents a disabled-workflow banner. Do not alter the scheduled job until the standard setup is working.

## Create the bot and channel

1. Start [@BotFather](https://t.me/BotFather) in Telegram and create a bot. Copy its token.
2. Create a channel or use an existing channel you administer.
3. Add the new bot as a channel administrator and grant posting permission.
4. For public channels, use the `@channelname` value as `TELEGRAM_CHAT_ID`. For private channels, use the actual numeric chat ID.

## Configure GitHub Actions

Go to **Settings → Secrets and variables → Actions** in your *own* repository.

Under **Variables**, add `INSTAGRAM_USERNAME` and `TELEGRAM_CHAT_ID`.

Under **Secrets**, add `APIFY_TOKEN` from the Apify Console and `TELEGRAM_BOT_TOKEN` from BotFather. Never put either token in a variable or commit it to a file.

Your GitHub repository needs GitHub Actions permission to write repository contents so the tool can save duplicate-protection state on a dedicated branch. The workflow declares `contents: write` for the sync job. If your organization restricts GitHub Actions permissions, ask its administrator to allow that job.

## Run the setup once

Open **Actions → Instagram to Telegram → Run workflow**.

First run: enable `initialize_only`. This records existing posts in a `sync-state` branch without posting them.

For a subsequent safe test, use `dry_run`. It fetches images/videos and checks processing logic without publishing anything.

After the test, the normal scheduled run checks every six hours. With more than four profiles, it checks a rotating batch each run. Scheduled Actions workflows run on the repository's default branch and may be delayed by GitHub. You can always use **Run workflow** to start one manually.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| No workflow runs | Enable Actions in your fork/copy; confirm the YAML is on `main` |
| Workflow is skipped | Check `INSTAGRAM_USERNAME` and `TELEGRAM_CHAT_ID` variables |
| Telegram HTTP 400 | Chat ID and bot posting permission |
| Telegram HTTP 403 | Bot membership and channel administrator rights |
| Telegram HTTP 404 | Re-copy the BotFather token into Actions Secrets |
| Apify 401 / 403 | Apify token, account status and actor access |
| Apify quota reached | Check Apify billing usage and the configured local result cap |
| No new content | First-run baseline, duplicate state and 48-hour freshness filter |
| State API error | Ensure Actions can write repository contents; do not disable the `sync-state` branch |
| Missing newer Reels | Check the Apify run output and timestamp fields; the system deliberately skips undated items |
| Uncertain Telegram delivery | Inspect the destination and the `sync-state` journal; the post stays quarantined to prevent an automatic duplicate |
| Alerts not received | Set `ALERT_CHAT_ID` and bot posting rights; alerts start after two consecutive failed real runs, never dry-runs |

### Important recovery warning

**Do not delete `sync-state` or reset its history** to troubleshoot missing posts. It records which Instagram posts were already processed and the local Apify usage counters. Removing it may make old content eligible again or reset a safety counter.

If Telegram times out, loses the connection or returns HTTP 5xx, the post is quarantined in `sync-state` instead of blindly retried. Check the channel before manually resolving that entry. If GitHub state persistence fails after a confirmed post, a later retry could still duplicate it.

The **Usage and delivery summary** step reports aggregate checks, posted items, failures, estimated Apify requested results and uncertain deliveries. It does **not** measure actual Apify-billed results. Media captions longer than 1024 characters are sent in extra text messages. Files above Telegram's upload limits are rejected before sending.

### Operator recovery: uncertain delivery and prolonged downtime

When Telegram may have accepted a request but its response was lost, find the Instagram shortcode in GitHub Actions logs and check the destination channel:

1. Open **Actions → Instagram to Telegram → Run workflow**.
2. Set **resolve_action** to `delivered` if the post arrived, or `retry` if you confirmed it did not.
3. Enter **resolve_username** and **resolve_shortcode**. The resolution job does **not** publish to Telegram. It persists only the corrected duplicate-protection state.
4. For `retry`, first run `dry_run=true`. If the post is older than the normal 48-hour freshness window, set manual **catch_up_hours** between 48 and 168 with dry-run enabled to preview the candidates; then run a reviewed live sync if appropriate.

Manual catch-up cannot restore posts already marked processed as stale. Scheduled runs always keep the default 48-hour freshness limit.

For larger configurations, four profiles per scheduled run is the default. Twenty accounts are checked roughly once per 30 hours if scheduled runs continue normally. A batch may end earlier when it approaches its execution-time safety budget. The next run resumes from the saved cursor, with no concurrent writers to the shared state branch.

**Scheduled workflow inactivity:** GitHub documents automatic disabling of schedules in public repositories after 60 days without repository activity. It does not guarantee that separate `sync-state` branch commits prevent this. Check the copied repository's Actions tab and re-enable the workflow if needed.

**Apify estimates:** Requested-results allowances are now recorded before each actor attempt (including retries and failures). They are deliberately conservative and are **not** the vendor's actual invoice. Check the Apify dashboard for billed usage.

## Advanced backends and local testing

For local-only backends:

```bash
python -m pip install -r requirements-advanced.txt
python -m insta_tg_sync.cli --config config.example.yml --backend instaloader --dry-run
```

The default hosted workflow intentionally does not install Playwright, Instaloader, Telethon or `curl_cffi`. Advanced backends may need credentials, browser setup or proxy settings that are outside the standard four-value deployment.

## Security

Keep tokens in GitHub Actions Secrets. Redact usernames, chat IDs, access tokens, cookies and session files before attaching logs to issues. See [SECURITY.md](../SECURITY.md).
