from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
import time
from pathlib import Path

from .apify_provider import (
    ApifyInstagramClient,
    ApifyPost,
    describe_apify_media_fields,
    download_apify_media,
    normalize_apify_posts,
)
from .config import AccountConfig, AppConfig
from .state import StateStore
from .telegram import TelegramDeliveryUncertain, create_telegram_sender


class ApifySyncRunner:
    """Lightweight default runner for Apify -> Telegram Bot deployments.

    This module intentionally imports only the dependencies required by the
    public GitHub Actions setup. Experimental/advanced backends remain in
    ``sync.py`` and are loaded only when explicitly selected.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = StateStore(config.state_file)
        self.telegram = create_telegram_sender(config.telegram)

    def run(self) -> None:
        self.state.load()
        errors: list[Exception] = []
        for account in self.config.accounts:
            try:
                self._sync_account(account)
            except Exception as error:
                self.state.record_stat("errors")
                errors.append(error)
                print(f"Account sync failed for @{account.username}: {type(error).__name__}")
            finally:
                self.state.save()
        if errors and not (self.config.dry_run or self.config.initialize_only):
            failures = self.state.increment_failure()
            self.state.save()
            if failures >= 2 and self.config.alert_chat_id:
                self._send_failure_alert(failures, len(errors))
        elif not errors and not (self.config.dry_run or self.config.initialize_only):
            self.state.reset_failures()
            self.state.save()
        if errors:
            raise RuntimeError(f"Sync failed for {len(errors)} account(s); see job logs.") from errors[0]

    def _send_failure_alert(self, failures: int, accounts_failed: int) -> None:
        try:
            from .telegram import TelegramBot
            bot = TelegramBot(self.config.telegram.bot_token)
            bot._post(f"{bot.base_url}/sendMessage", data={
                "chat_id": self.config.alert_chat_id,
                "text": f"Instagram to Telegram: {accounts_failed} account sync(s) failed. "
                        f"Consecutive failed runs: {failures}. Check GitHub Actions."
            })
            print("Failure alert sent.")
        except Exception:
            print("Could not send failure alert; check Actions logs.")

    def diagnose_apify_shortcode(self, shortcode: str) -> None:
        for account in self.config.accounts:
            requested = min(
                max(account.check_limit, account.initial_skip),
                self.config.apify.max_results_per_run,
            )
            print(f"Diagnosing Apify media for @{account.username} shortcode {shortcode}")
            client = ApifyInstagramClient(self.config)
            raw_matches: list[tuple[str, dict]] = []
            post_matches: list[tuple[str, ApifyPost]] = []

            request_plan = [
                ("posts", requested),
                ("reels", requested),
                ("details", ApifyInstagramClient.DETAILS_RESULTS_LIMIT),
            ]
            for results_type, result_limit in request_plan:
                items = client.fetch_raw_items(account, result_limit, results_type)
                normalized = normalize_apify_posts(items, requested)
                print(
                    f"Apify {results_type} returned {len(items)} raw item(s), "
                    f"normalized {len(normalized)} post(s)."
                )
                post_matches.extend(
                    (results_type, item)
                    for item in normalized
                    if item.shortcode == shortcode
                )
                raw_matches.extend(
                    (results_type, item)
                    for item in _iter_diagnostic_raw_posts(items)
                    if (item.get("shortCode") or item.get("shortcode")) == shortcode
                )

            post = post_matches[-1][1] if post_matches else None
            if post is None:
                print(f"Shortcode {shortcode} was not found in Apify post(s) for @{account.username}.")
                continue

            for results_type, raw_item in raw_matches:
                print(f"Apify {results_type} raw fields for shortcode {shortcode}:")
                for line in describe_apify_media_fields(raw_item):
                    print(line)

            if post_matches:
                print(
                    f"Using Apify {post_matches[-1][0]} media for diagnostic download; "
                    f"matched sources: {', '.join(source for source, _ in post_matches)}."
                )

            post_dir = self.config.temp_dir / account.username / post.shortcode
            if post_dir.exists():
                shutil.rmtree(post_dir)
            post_dir.mkdir(parents=True, exist_ok=True)
            try:
                files = download_apify_media(
                    post,
                    post_dir,
                    self.config.request_timeout,
                    self.config.user_agents[-1],
                )
                print(
                    f"Diagnosed {len(files)} Apify media file(s) for @{account.username} "
                    f"post {post.shortcode}; nothing was sent."
                )
            finally:
                self._archive_or_cleanup(post_dir, account.username, post.shortcode)
            return

        raise RuntimeError(f"Shortcode {shortcode} was not found for any configured account.")

    def _sync_account(self, account: AccountConfig) -> None:
        print(f"Checking @{account.username}")
        self.state.record_stat("checks")
        used = self.state.external_results_used(
            "apify",
            self.config.apify.billing_cycle_start_day,
        )
        remaining = self.config.apify.monthly_result_cap - used
        if remaining <= 0:
            print(
                f"Apify monthly result cap reached "
                f"({used}/{self.config.apify.monthly_result_cap}); skipping @{account.username}."
            )
            return

        request_multiplier = len(ApifyInstagramClient.RESULTS_TYPES)
        details_request = ApifyInstagramClient.DETAILS_RESULTS_LIMIT
        minimum_request = request_multiplier + details_request
        if remaining < minimum_request:
            print(
                f"Apify monthly result cap almost reached "
                f"({used}/{self.config.apify.monthly_result_cap}); "
                f"not enough remaining results for @{account.username}."
            )
            return

        max_requested = max(1, (remaining - details_request) // request_multiplier)
        requested = min(
            max(account.check_limit, account.initial_skip),
            self.config.apify.max_results_per_run,
            max_requested,
        )
        charged_results = requested * request_multiplier + details_request

        client = ApifyInstagramClient(self.config)
        posts = client.fetch_posts(account, requested)
        print(f"Apify backend extracted {len(posts)} post(s) for @{account.username}.")

        charged_results = getattr(client, "requested_results", charged_results)
        self.state.add_external_results("apify", charged_results, self.config.apify.billing_cycle_start_day)
        self.state.record_stat("estimated_apify_results", charged_results)
        self.state.record_stat("fetched", len(posts))
        self.state.save()

        if not posts:
            raise RuntimeError(f"Apify backend found no posts for @{account.username}.")
        self._sync_posts(account, posts)

    def _sync_posts(self, account: AccountConfig, posts: list[ApifyPost]) -> None:
        if self.config.initialize_only:
            print(
                f"Initialize-only: marking {len(posts)} Apify post(s) processed "
                f"for @{account.username}; nothing will be sent."
            )
            for post in posts:
                self.state.mark_processed(account.username, post.shortcode)
            self.state.save()
            return

        if not self.state.has_account(account.username):
            print(f"Initializing state for @{account.username}; current Apify posts will not be sent.")
            for post in posts[: account.initial_skip]:
                self.state.mark_processed(account.username, post.shortcode)
            self.state.save()
            return

        processed = self.state.processed(account.username)
        now = datetime.now(timezone.utc)
        max_age = timedelta(hours=self.config.apify.max_post_age_hours)
        max_clock_skew = timedelta(minutes=10)
        new_posts: list[ApifyPost] = []
        skipped_posts: list[ApifyPost] = []
        for post in posts[: account.check_limit]:
            if post.shortcode in processed:
                continue
            if post.published_at is None:
                print("Skipping Apify post without a trustworthy publication timestamp.")
                skipped_posts.append(post)
            elif not -max_clock_skew <= now - post.published_at <= max_age:
                print("Skipping Apify post outside the publication freshness window.")
                skipped_posts.append(post)
            else:
                new_posts.append(post)

        # Permanently suppress stale/undated items so changed profile order or
        # pinned Reels cannot resurrect them on subsequent scheduled runs.
        # Dry runs must not modify the duplicate index.
        if skipped_posts and not self.config.dry_run:
            for post in skipped_posts:
                self.state.mark_processed(account.username, post.shortcode)
            self.state.save()

        self.state.record_stat("skipped", len(skipped_posts))
        if not new_posts:
            print(f"No eligible new Apify posts for @{account.username}.")
            return

        print(f"Found {len(new_posts)} recent Apify posts for @{account.username}.")
        for post in sorted(new_posts, key=lambda item: (item.published_at, item.shortcode)):
            self._process_post(account, post)

    def _process_post(self, account: AccountConfig, post: ApifyPost) -> None:
        if self.state.is_uncertain(account.username, post.shortcode):
            print("Telegram delivery requires manual review; automatic resend suppressed.")
            return
        post_dir = self.config.temp_dir / account.username / post.shortcode
        if post_dir.exists():
            shutil.rmtree(post_dir)
        post_dir.mkdir(parents=True, exist_ok=True)

        print(f"Downloading Apify media for @{account.username} post {post.shortcode}")
        files = download_apify_media(
            post,
            post_dir,
            self.config.request_timeout,
            self.config.user_agents[-1],
        )
        if not files:
            raise RuntimeError(
                f"No Apify media downloaded for @{account.username} post {post.shortcode}"
            )

        caption = account.caption_template.format(
            caption=post.caption,
            shortcode=post.shortcode,
            url=post.url,
            username=account.username,
        ).strip()

        if self.config.dry_run:
            self.state.record_stat("dry_runs")
            print(
                f"Dry run: would send {len(files)} Apify files "
                f"for @{account.username} post {post.shortcode}."
            )
        else:
            try:
                self.telegram.send_media(account.telegram_chat_id, caption, files)
            except TelegramDeliveryUncertain:
                self.state.mark_uncertain(account.username, post.shortcode)
                self.state.record_stat("uncertain")
                self.state.save()
                raise
            print(f"Sent Apify post @{account.username} {post.shortcode} to Telegram.")
            self.state.mark_processed(account.username, post.shortcode)
            self.state.record_stat("published")
            self.state.save()

        self._archive_or_cleanup(post_dir, account.username, post.shortcode)
        time.sleep(self.config.post_delay_seconds)

    def _archive_or_cleanup(self, post_dir: Path, username: str, shortcode: str) -> None:
        if self.config.archive_dir:
            destination = self.config.archive_dir / username / shortcode
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(post_dir), str(destination))
        else:
            shutil.rmtree(post_dir, ignore_errors=True)


def _iter_diagnostic_raw_posts(items: list[dict]):
    for item in items:
        latest_posts = item.get("latestPosts")
        if isinstance(latest_posts, list):
            yield from (post for post in latest_posts if isinstance(post, dict))
            continue
        yield item
