from dataclasses import replace

from insta_tg_sync.apify_provider import ApifyPost
from insta_tg_sync.config import AccountConfig, ApifyConfig, AppConfig, TelegramConfig
from insta_tg_sync.sync import SyncRunner


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def send_media(self, chat_id, caption, files):
        self.sent.append((chat_id, caption, files))


def _config(tmp_path, dry_run=False, initialize_only=False):
    return AppConfig(
        telegram=TelegramConfig(backend="bot", bot_token="token"),
        accounts=[],
        backend="apify",
        apify=ApifyConfig(token="token", max_results_per_run=6, monthly_result_cap=1000),
        state_file=tmp_path / "state.json",
        temp_dir=tmp_path / "tmp",
        user_agents=["test-agent"],
        post_delay_seconds=0,
        dry_run=dry_run,
        initialize_only=initialize_only,
    )


def _account():
    return AccountConfig(username="account", telegram_chat_id="@chat", check_limit=6, initial_skip=6)


def _post(shortcode="NEW"):
    return ApifyPost(shortcode=shortcode, url=f"https://www.instagram.com/p/{shortcode}/", caption="caption", media_urls=["https://example.com/image.jpg"])


def test_dry_run_does_not_mark_new_apify_post_processed(tmp_path, monkeypatch):
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    monkeypatch.setattr("insta_tg_sync.sync.download_apify_media", lambda *args: [media])

    runner = SyncRunner(_config(tmp_path, dry_run=True))
    runner.telegram = FakeTelegram()
    runner.state.load()
    runner.state.mark_processed("account", "OLD")

    runner._process_apify_post(_account(), _post())

    assert "OLD" in runner.state.processed("account")
    assert "NEW" not in runner.state.processed("account")
    assert runner.telegram.sent == []


def test_real_run_marks_apify_post_after_successful_send(tmp_path, monkeypatch):
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    monkeypatch.setattr("insta_tg_sync.sync.download_apify_media", lambda *args: [media])

    runner = SyncRunner(_config(tmp_path))
    runner.telegram = FakeTelegram()
    runner.state.load()
    runner.state.mark_processed("account", "OLD")

    runner._process_apify_post(_account(), _post())

    assert "OLD" in runner.state.processed("account")
    assert "NEW" in runner.state.processed("account")
    assert len(runner.telegram.sent) == 1


def test_apify_usage_counts_requested_results_not_normalized_posts(tmp_path, monkeypatch):
    class FakeApifyClient:
        RESULTS_TYPES = ("posts", "reels")
        DETAILS_RESULTS_LIMIT = 1

        def __init__(self, config):
            pass

        def fetch_posts(self, account, requested):
            assert requested == 6
            return [_post("OLD")]

    monkeypatch.setattr("insta_tg_sync.sync.ApifyInstagramClient", FakeApifyClient)

    config = replace(_config(tmp_path), accounts=[_account()])
    runner = SyncRunner(config)
    runner.state.load()
    runner.state.mark_processed("account", "OLD")

    runner._sync_account_apify(_account())

    assert runner.state.external_results_used("apify") == 13


def test_initialize_only_marks_all_fetched_apify_posts_without_sending(tmp_path):
    runner = SyncRunner(_config(tmp_path, initialize_only=True))
    runner.telegram = FakeTelegram()
    runner.state.load()
    runner.state.mark_processed("account", "PINNED")

    runner._sync_apify_posts(_account(), [_post("PINNED"), _post("CURRENT"), _post("OLDER")])

    processed = runner.state.processed("account")
    assert "PINNED" in processed
    assert "CURRENT" in processed
    assert "OLDER" in processed
    assert runner.telegram.sent == []
