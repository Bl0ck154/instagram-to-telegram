"""Regression checks for safe recovery, scheduled batches and quota reservations."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests
import yaml

from insta_tg_sync.apify_provider import ApifyInstagramClient, ApifyPost
from insta_tg_sync.apify_sync import ApifySyncRunner
from insta_tg_sync.config import AccountConfig, AppConfig, ApifyConfig, TelegramConfig
from insta_tg_sync.reconcile import resolve
from insta_tg_sync.state import StateStore


def config(tmp_path, **kwargs):
    return AppConfig(
        telegram=TelegramConfig(bot_token="fake"),
        accounts=[AccountConfig("demo", "@channel")],
        backend="apify",
        apify=ApifyConfig(token="fake", max_results_per_run=6, monthly_result_cap=30),
        state_file=tmp_path / "state.json",
        temp_dir=tmp_path / "tmp",
        post_delay_seconds=0,
        **kwargs,
    )


def test_reconcile_requires_exact_uncertain_item(tmp_path):
    state=StateStore(tmp_path/"state.json")
    state.load()
    state.mark_uncertain("my-profile","ABC")
    state.save()
    with pytest.raises(ValueError,match="No uncertain"):
        resolve(state.path,"my-profile","WRONG","delivered")
    resolve(state.path,"my-profile","ABC","delivered")
    restored=StateStore(state.path)
    restored.load()
    assert not restored.is_uncertain("my-profile","ABC")
    assert "ABC" in restored.processed("my-profile")
    with pytest.raises(ValueError,match="No uncertain"):
        resolve(state.path,"my-profile","ABC","delivered")


def test_reconcile_retry_unquarantines_without_marking_processed(tmp_path):
    state=StateStore(tmp_path/"state.json")
    state.load()
    state.mark_uncertain("my-profile","ABC")
    state.save()
    resolve(state.path,"my-profile","ABC","retry")
    restored=StateStore(state.path)
    restored.load()
    assert not restored.is_uncertain("my-profile","ABC")
    assert "ABC" not in restored.processed("my-profile")


def test_account_rotation_does_not_starve_later_profiles(tmp_path,monkeypatch):
    names=[f"account{i}" for i in range(11)]
    accounts=[AccountConfig(name,"@channel") for name in names]
    cfg=replace(config(tmp_path),accounts=accounts,max_accounts_per_run=4)
    runner=ApifySyncRunner(cfg)
    seen=[]
    monkeypatch.setattr(runner,"_sync_account",lambda account: seen.append(account.username))
    runner.run()
    runner.run()
    runner.run()
    assert seen[:11]==names
    assert len(seen)==12
    assert seen[-1]=="account0"
    restored=StateStore(cfg.state_file)
    restored.load()
    assert restored.data["health"]["next_account_index"]==1


def test_dry_run_does_not_advance_rotation(tmp_path,monkeypatch):
    accounts=[AccountConfig(f"account{i}","@channel") for i in range(10)]
    cfg=replace(config(tmp_path),accounts=accounts,max_accounts_per_run=3,dry_run=True)
    runner=ApifySyncRunner(cfg)
    selected=[]
    monkeypatch.setattr(runner,"_sync_account",lambda account:selected.append(account.username))
    runner.run()
    runner.run()
    assert selected==["account0","account1","account2"]*2


def test_failure_alert_cooldown_and_recovery(tmp_path,monkeypatch):
    runner=ApifySyncRunner(replace(config(tmp_path),alert_chat_id="@alerts"))
    posted=[]
    monkeypatch.setattr(runner,"_send_alert",lambda message:posted.append(message) or True)
    def fail(account):
        raise RuntimeError("temporary provider error")
    monkeypatch.setattr(runner,"_sync_account",fail)
    for run in range(3):
        with pytest.raises(RuntimeError):
            runner.run()
    assert len(posted)==1
    assert "Consecutive failed runs: 2" in posted[0]
    monkeypatch.setattr(runner,"_sync_account",lambda account:None)
    runner.run()
    assert len(posted)==2
    assert "recovered" in posted[1]
    assert runner.state.data["health"]["consecutive_failures"]==0
    assert not runner.state.had_failure_alert()


def test_failed_apify_request_still_reserves_quota(tmp_path,monkeypatch):
    runner=ApifySyncRunner(config(tmp_path))
    runner.state.load()
    client=ApifyInstagramClient(runner.config)
    client.usage_recorder=runner._reserve_apify_attempt
    calls=[]
    def break_network(*args,**kwargs):
        calls.append(1)
        assert runner.state.external_results_used("apify")==6
        raise requests.Timeout("test")
    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post",break_network)
    with pytest.raises(requests.Timeout):
        client._post_with_retry("https://api.apify.com/example",{"resultsLimit":6},"posts")
    assert calls==[1]
    state=StateStore(runner.config.state_file)
    state.load()
    assert state.external_results_used("apify")==6


def test_retries_count_each_attempt_and_enforce_limit(tmp_path,monkeypatch):
    cfg=replace(config(tmp_path),apify=ApifyConfig(token="fake",monthly_result_cap=10))
    runner=ApifySyncRunner(cfg)
    runner.state.load()
    client=ApifyInstagramClient(cfg)
    client.usage_recorder=runner._reserve_apify_attempt
    sent=[]
    class Response:
        status_code=503
        headers={}
    def fake_post(*args,**kwargs):
        sent.append(1)
        return Response()
    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post",fake_post)
    monkeypatch.setattr("insta_tg_sync.apify_provider.sleep",lambda seconds:None)
    with pytest.raises(RuntimeError,match="allowance exhausted"):
        client._post_with_retry("https://api.apify.com/example",{"resultsLimit":5},"posts")
    assert len(sent)==2
    assert runner.state.external_results_used("apify")==10


def test_remote_checkpoint_happens_before_apify_request(tmp_path,monkeypatch):
    cfg=config(tmp_path)
    runner=ApifySyncRunner(cfg)
    runner.state.load()
    events=[]
    monkeypatch.setenv("APIFY_CHECKPOINT_REMOTE","true")
    monkeypatch.setenv("GITHUB_REPOSITORY","owner/repo")
    monkeypatch.setenv("GITHUB_TOKEN","dummy")
    monkeypatch.setattr("insta_tg_sync.github_state.GitHubState.persist",
                        lambda self: events.append(("checkpoint",self.path.read_bytes())) or True)
    client=ApifyInstagramClient(cfg)
    client.usage_recorder=runner._reserve_apify_attempt
    def fake_post(*args,**kwargs):
        events.append(("actor",None))
        raise requests.Timeout("network")
    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post",fake_post)
    with pytest.raises(requests.Timeout):
        client._post_with_retry("https://api.apify.com/example",{"resultsLimit":6},"posts")
    assert [item[0] for item in events]==["checkpoint","actor"]


def test_extended_freshness_only_when_explicitly_configured(tmp_path,monkeypatch):
    cfg=config(tmp_path)
    runner=ApifySyncRunner(cfg)
    runner.state.load()
    runner.state.mark_processed("demo","SEED")
    posted=[]
    monkeypatch.setattr(runner,"_process_post",lambda account,post:posted.append(post.shortcode))
    item=ApifyPost("PAST", "https://instagram.com/p/PAST", "", ["https://example.com/m.jpg"],
                  datetime.now(timezone.utc)-timedelta(hours=75))
    runner._sync_posts(cfg.accounts[0],[item])
    assert posted==[]
    extended=ApifySyncRunner(replace(cfg,apify=replace(cfg.apify,max_post_age_hours=120)))
    extended.state.load()
    posted2=[]
    monkeypatch.setattr(extended,"_process_post",lambda account,post:posted2.append(post.shortcode))
    extended._sync_posts(cfg.accounts[0],[item])
    # Note: standard run marked the item stale, so the documented catch-up
    # cannot resurrect it. A separate unprocessed account can catch it up.
    assert posted2==[]


def test_workflow_and_social_preview_are_wired():
    root=Path(__file__).parents[1]
    workflow=yaml.safe_load((root/".github/workflows/instagram-to-telegram.yml").read_text())
    triggers=workflow.get("on",workflow.get(True))
    inputs=triggers["workflow_dispatch"]["inputs"]
    assert {"catch_up_hours","resolve_action","resolve_username","resolve_shortcode"}<=set(inputs)
    assert any("MAX_ACCOUNTS_PER_RUN" in step.get("env", {})
               for step in workflow["jobs"]["sync"]["steps"])
    assert "APIFY_CHECKPOINT_REMOTE" in str(workflow["jobs"]["sync"])
    assert "reconcile" in str(workflow["jobs"]["resolve"])
    html=(root/"docs/index.html").read_text()
    assert 'rel="canonical"' in html
    assert 'property="og:image"' in html
    assert 'name="twitter:card"' in html
    assert (root/"docs/social-preview.png").stat().st_size>10000
    assert (root/"docs/favicon.svg").exists()


def test_explicit_extended_freshness_can_pick_up_old_unprocessed_post(tmp_path,monkeypatch):
    cfg=config(tmp_path)
    extended=ApifySyncRunner(replace(cfg,apify=replace(cfg.apify,max_post_age_hours=120)))
    extended.state.load()
    extended.state.mark_processed("demo","SEED")
    posted=[]
    monkeypatch.setattr(extended,"_process_post",lambda account,post:posted.append(post.shortcode))
    item=ApifyPost("PAST", "https://instagram.com/p/PAST", "", ["https://example.com/m.jpg"],
                  datetime.now(timezone.utc)-timedelta(hours=75))
    extended._sync_posts(cfg.accounts[0],[item])
    assert posted==["PAST"]
