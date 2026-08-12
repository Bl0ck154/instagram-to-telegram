from __future__ import annotations

import shutil
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
from .telegram import create_telegram_sender


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
        for account in self.config.accounts:
            self._sync_account(account)
        self.state.save()

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

        self.state.add_external_results(
            "apify",
            charged_results,
            self.config.apify.billing_cycle_start_day,
        )
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
        new_posts = [
            post
            for post in posts[: account.check_limit]
            if post.shortcode not in processed
        ]
        if not new_posts:
            print(f"No new Apify posts for @{account.username}.")
            return

        print(f"Found {len(new_posts)} new Apify posts for @{account.username}.")
        for post in reversed(new_posts):
            self._process_post(account, post)

    def _process_post(self, account: AccountConfig, post: ApifyPost) -> None:
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
            print(
                f"Dry run: would send {len(files)} Apify files "
                f"for @{account.username} post {post.shortcode}."
            )
        else:
            self.telegram.send_media(account.telegram_chat_id, caption, files)
            print(f"Sent Apify post @{account.username} {post.shortcode} to Telegram.")
            self.state.mark_processed(account.username, post.shortcode)
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
