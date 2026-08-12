import json
from datetime import datetime, timezone

from insta_tg_sync.state import StateStore


def test_state_tracks_posts_per_account_without_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_HMAC_KEY", "test-key")
    state = StateStore(tmp_path / "state.json", max_items=2)
    state.load()

    state.mark_processed("first", "a")
    state.mark_processed("first", "b")
    state.mark_processed("first", "c")
    state.mark_processed("second", "x")
    state.save()

    raw = (tmp_path / "state.json").read_text(encoding="utf-8")
    assert '"first"' not in raw
    assert '"second"' not in raw
    assert '"a"' not in raw
    assert '"b"' not in raw
    assert '"c"' not in raw
    assert '"x"' not in raw
    assert "hmac-sha256:" in raw

    loaded = StateStore(tmp_path / "state.json", max_items=2)
    loaded.load()

    assert "a" not in loaded.processed("first")
    assert "b" in loaded.processed("first")
    assert "c" in loaded.processed("first")
    assert "x" in loaded.processed("second")


def test_state_migrates_plaintext_account_and_post_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_HMAC_KEY", "test-key")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"accounts": {"legacy_account": {"processed": ["old_post"]}}}), encoding="utf-8")

    state = StateStore(state_file)
    state.load()
    state.save()

    raw = state_file.read_text(encoding="utf-8")
    assert "legacy_account" not in raw
    assert "old_post" not in raw
    assert "old_post" in state.processed("legacy_account")


def test_state_tracks_external_provider_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_HMAC_KEY", "test-key")
    state = StateStore(tmp_path / "state.json")
    state.load()

    state.add_external_results("apify", 2)
    state.add_external_results("apify", 3)

    assert state.external_results_used("apify") == 5


def test_state_uses_apify_billing_cycle_and_migrates_current_legacy_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_HMAC_KEY", "test-key")
    monkeypatch.setattr("insta_tg_sync.state._now_utc", lambda: datetime(2026, 7, 25, tzinfo=timezone.utc))
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"accounts": {}, "usage": {"2026-07": {"apify": 999}}}), encoding="utf-8")
    state = StateStore(state_file)
    state.load()
    state.add_external_results("apify", 13, billing_cycle_start_day=26)

    assert state.external_results_used("apify", billing_cycle_start_day=26) == 1012
    assert state.data["usage"]["2026-06-26"]["apify"] == 1012


def test_state_starts_new_apify_billing_cycle_on_renewal_day(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_HMAC_KEY", "test-key")
    monkeypatch.setattr("insta_tg_sync.state._now_utc", lambda: datetime(2026, 7, 26, tzinfo=timezone.utc))
    state = StateStore(tmp_path / "state.json")
    state.load()
    state.data = {"accounts": {}, "usage": {"2026-07": {"apify": 999}}}

    assert state.external_results_used("apify", billing_cycle_start_day=26) == 0
