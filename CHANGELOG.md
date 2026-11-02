# Changelog

## Unreleased

- Preserve long captions in Telegram text messages instead of truncating.
- Stream and validate downloaded media by actual file signature and MIME type.
- Quarantine uncertain Telegram deliveries rather than risking duplicate retries.
- Skip unnecessary Apify details calls; keep fallback for incomplete feeds.
- Process new posts in chronological order.
- Add optional multi-account configuration (`ACCOUNTS_JSON`).
- Add failure alerts (`ALERT_CHAT_ID`), privacy-safe usage summaries and interactive setup wizard.

## 1.0.0 (2026-11-02)

First documented public release.

- Automatically repost new public Instagram photos, Reels and carousels to Telegram using GitHub Actions, Apify and the Telegram Bot API.
- Keep the standard hosted setup lightweight with two runtime Python dependencies and four repository values.
- Reject old, undated and future-dated posts to avoid unwanted Reels replays after partial Apify failures.
- Store deduplication and Apify result counters in a dedicated `sync-state` branch. The initial production state was preserved before the migration.
- Add clearer setup guidance, cost disclosures, public example artwork, contribution instructions and issue templates.
- Run tests for relevant PR and main-branch code changes, avoiding state-only CI builds.

The default no-login mode is for public Instagram profiles; Apify has separate usage charges and the six-hour schedule is best-effort.
