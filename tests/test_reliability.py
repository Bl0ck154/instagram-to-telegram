from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import requests

from insta_tg_sync.telegram import TelegramBot, TelegramDeliveryUncertain
from insta_tg_sync.apify_provider import ApifyPost, download_apify_media
from insta_tg_sync.apify_sync import ApifySyncRunner
from insta_tg_sync.config import AccountConfig, ApifyConfig, AppConfig, TelegramConfig
from insta_tg_sync.state import StateStore


def photo(tmp_path):
    path = tmp_path / "image.jpg"
    path.write_bytes(b"\xff\xd8\xff" + b"x" * 24)
    return path


def test_long_caption_is_preserved_after_media(tmp_path):
    bot = TelegramBot("test:token")
    calls = []
    bot._post = lambda url, **params: calls.append((url, params))
    caption = "A" * 1030 + "\nLink: https://instagram.com/p/ABC/"
    bot.send_media("@channel", caption, [photo(tmp_path)])
    assert calls[0][0].endswith("/sendPhoto")
    assert calls[0][1]["data"]["caption"] == ""
    text = "".join(call[1]["data"]["text"] for call in calls[1:])
    assert text == caption


def test_large_caption_is_split_without_loss(tmp_path):
    bot = TelegramBot("test:token")
    calls = []
    bot._post = lambda url, **params: calls.append((url, params))
    caption = "B" * 9000
    bot.send_media("@channel", caption, [photo(tmp_path)])
    assert all(len(x[1]["data"]["text"]) <= 4096 for x in calls[1:])
    assert "".join(x[1]["data"]["text"] for x in calls[1:]) == caption


def test_network_timeout_is_uncertain_and_not_retried(monkeypatch):
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        raise requests.Timeout("timeout")
    monkeypatch.setattr("insta_tg_sync.telegram.requests.post", fail)
    with pytest.raises(TelegramDeliveryUncertain):
        TelegramBot("test:token")._post("https://api.telegram.org/bottest/sendPhoto")
    assert len(attempts) == 1


def test_http_5xx_delivery_is_uncertain_not_retried(monkeypatch):
    class Response:
        status_code = 502
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        return Response()
    monkeypatch.setattr("insta_tg_sync.telegram.requests.post", fail)
    with pytest.raises(TelegramDeliveryUncertain):
        TelegramBot("test:token")._post("https://api.telegram.org/bottest/sendPhoto")
    assert attempts == [1]


def test_html_media_is_rejected_before_upload(tmp_path):
    bot = TelegramBot("test:token")
    path = tmp_path / "image.jpg"
    path.write_bytes(b"<html>error</html>")
    with pytest.raises(ValueError, match="Media content"):
        bot.send_media("@channel", "caption", [path])


def test_uncertain_deliveries_are_quarantined(tmp_path, monkeypatch):
    conf = AppConfig(telegram=TelegramConfig(backend="bot", bot_token="test"),
        accounts=[], backend="apify", apify=ApifyConfig(token="test"),
        state_file=tmp_path/"state.json", temp_dir=tmp_path/"tmp",
        user_agents=["test"], post_delay_seconds=0)
    account = AccountConfig(username="account", telegram_chat_id="@channel")
    media = photo(tmp_path)
    monkeypatch.setattr("insta_tg_sync.apify_sync.download_apify_media", lambda *a: [media])
    runner = ApifySyncRunner(conf)
    class Sender:
        calls = 0
        def send_media(self, *a):
            self.calls += 1
            raise TelegramDeliveryUncertain("unknown")
    sender = Sender()
    runner.telegram = sender
    runner.state.load()
    post = ApifyPost(shortcode="NEW", url="https://www.instagram.com/p/NEW/",
                     caption="x", media_urls=["https://example.com/test.jpg"])
    with pytest.raises(TelegramDeliveryUncertain):
        runner._process_post(account, post)
    assert runner.state.is_uncertain("account", "NEW")
    runner._process_post(account, post)
    assert sender.calls == 1
    restored = StateStore(conf.state_file)
    restored.load()
    assert restored.is_uncertain("account", "NEW")


def test_posts_are_sent_oldest_first(tmp_path, monkeypatch):
    conf = AppConfig(telegram=TelegramConfig(backend="bot", bot_token="test"),
        accounts=[], backend="apify", apify=ApifyConfig(token="test"),
        state_file=tmp_path/"state.json", temp_dir=tmp_path/"tmp")
    runner = ApifySyncRunner(conf)
    runner.state.load()
    runner.state.mark_processed("account", "SEED")
    now = datetime.now(timezone.utc)
    posts = [ApifyPost("LATER", "https://x/LATER", "", ["https://example.com/a.jpg"], now-timedelta(hours=1)),
             ApifyPost("EARLIER", "https://x/EARLIER", "", ["https://example.com/a.jpg"], now-timedelta(hours=3))]
    sent = []
    monkeypatch.setattr(runner, "_process_post", lambda account, post: sent.append(post.shortcode))
    runner._sync_posts(AccountConfig(username="account", telegram_chat_id="@c"), posts)
    assert sent == ["EARLIER", "LATER"]


def test_streaming_download_detects_mp4_despite_jpg_url(tmp_path, monkeypatch):
    class Response:
        ok = True
        headers = {"Content-Type": "application/octet-stream"}
        def iter_content(self, chunk_size):
            yield b"\x00\x00\x00\x18ftypisom"
            yield b"\x00" * 128
        def close(self):
            pass
    monkeypatch.setattr("insta_tg_sync.apify_provider._download_response",
                        lambda *args: (Response(), "https://example.com/file.jpg"))
    post = ApifyPost("A", "https://instagram.com/p/A", "", ["https://example.com/file.jpg"])
    paths = download_apify_media(post, tmp_path, 10, "agent")
    assert paths[0].suffix == ".mp4"
    assert paths[0].stat().st_size == 140


def test_streaming_rejects_html(tmp_path, monkeypatch):
    class Response:
        headers = {"Content-Type": "text/html"}
        def iter_content(self, chunk_size):
            yield b"<html>not a picture</html>"
        def close(self):
            pass
    monkeypatch.setattr("insta_tg_sync.apify_provider._download_response",
                        lambda *args: (Response(), "https://example.com/file.jpg"))
    post = ApifyPost("A", "https://instagram.com/p/A", "", ["https://example.com/file.jpg"])
    with pytest.raises(ValueError, match="text"):
        download_apify_media(post, tmp_path, 10, "agent")


def test_long_caption_linebreaks_preserved(tmp_path):
    bot = TelegramBot("test:token")
    calls = []
    bot._post = lambda url, **params: calls.append((url, params))
    caption = ("Words and a newline\\n" * 260) + "Original post link: https://instagram.com/p/x"
    bot.send_media("@channel", caption, [photo(tmp_path)])
    assert "".join(call[1]["data"]["text"] for call in calls[1:]) == caption


def test_multiple_accounts_json_variable(monkeypatch):
    import json
    from insta_tg_sync.config import parse_config
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ACCOUNTS_JSON", json.dumps([
        {"username": "one", "telegram_chat_id": "@first_channel"},
        {"username": "two", "telegram_chat_id": "@second_channel"},
    ]))
    config = parse_config({
        "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
        "accounts": [{"username_env": "INSTAGRAM_USERNAME", "telegram_chat_id_env": "TELEGRAM_CHAT_ID"}],
        "settings": {"backend": "apify"},
    })
    assert [a.username for a in config.accounts] == ["one", "two"]
    assert [a.telegram_chat_id for a in config.accounts] == ["@first_channel", "@second_channel"]


def test_duplicate_instagram_usernames_are_rejected(monkeypatch):
    import json
    from insta_tg_sync.config import parse_config
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ACCOUNTS_JSON", json.dumps([
        {"username": "ONE", "telegram_chat_id": "@first_channel"},
        {"username": "one", "telegram_chat_id": "@second_channel"},
    ]))
    with pytest.raises(ValueError, match="only once"):
        parse_config({"telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"}})


def test_usage_report_contains_counts_without_private_ids(tmp_path):
    from insta_tg_sync.report import build_report
    state = StateStore(tmp_path / "state.json")
    state.load()
    state.mark_processed("private_profile", "PRIVATE_POST")
    state.record_stat("fetched", 6)
    state.record_stat("published", 2)
    state.record_stat("estimated_apify_results", 12)
    state.save()
    report = build_report(state.path)
    assert "Fetched | 6" in report
    assert "Published | 2" in report
    assert "Estimated Apify Results | 12" in report
    assert "private_profile" not in report
    assert "PRIVATE_POST" not in report


def test_failure_alerts_after_second_real_failure(tmp_path, monkeypatch):
    conf = AppConfig(telegram=TelegramConfig(backend="bot", bot_token="test"),
        accounts=[AccountConfig(username="account", telegram_chat_id="@channel")],
        backend="apify", apify=ApifyConfig(token="test"),
        state_file=tmp_path / "state.json", temp_dir=tmp_path / "tmp",
        alert_chat_id="@monitor")
    runner = ApifySyncRunner(conf)
    calls = []
    def fail(account):
        raise RuntimeError("simulated fetch failure")
    monkeypatch.setattr(runner, "_sync_account", fail)
    monkeypatch.setattr(runner, "_send_alert", lambda message: calls.append(message) or True)
    with pytest.raises(RuntimeError):
        runner.run()
    assert calls == []
    with pytest.raises(RuntimeError):
        runner.run()
    assert len(calls) == 1
    assert "Consecutive failed runs: 2" in calls[0]
    assert runner.state.data["health"]["consecutive_failures"] == 2


def test_carousel_of_twelve_media_is_sent_in_two_albums(tmp_path):
    bot = TelegramBot("test:token")
    calls = []
    bot._post = lambda url, **params: calls.append((url, params))
    media = photo(tmp_path)
    bot.send_media("@channel", "caption", [media] * 12)
    assert len(calls) == 2
    assert calls[0][0].endswith("/sendMediaGroup")
    assert calls[1][0].endswith("/sendMediaGroup")
    import json
    first = json.loads(calls[0][1]["data"]["media"])
    second = json.loads(calls[1][1]["data"]["media"])
    assert len(first) == 10 and len(second) == 2
    assert first[0]["caption"] == "caption"
    assert all("caption" not in item for item in second)


def test_partial_carousel_delivery_is_quarantined(tmp_path):
    bot = TelegramBot("test:token")
    requests = []
    def send(url, **params):
        requests.append(url)
        if len(requests) == 2:
            raise RuntimeError("Second album rejected")
    bot._post = send
    with pytest.raises(TelegramDeliveryUncertain, match="Some media batches"):
        bot.send_media("@channel", "caption", [photo(tmp_path)] * 12)


def test_apify_does_not_truncate_twenty_item_carousel():
    from insta_tg_sync.apify_provider import normalize_apify_posts
    children = [{"displayUrl": f"https://example.com/media-{n}.jpg"} for n in range(20)]
    posts = normalize_apify_posts([{"shortCode": "ALLTWENTY", "childPosts": children}], limit=1)
    assert len(posts) == 1
    assert len(posts[0].media_urls) == 20
