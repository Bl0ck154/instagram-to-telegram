import os

from insta_tg_sync.config import parse_config


def test_parse_config_supports_multiple_accounts_and_proxy_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT_ONE", "@one")
    monkeypatch.setenv("CHAT_TWO", "@two")
    monkeypatch.setenv("INSTAGRAM_PROXIES", "http://user:pass@host:9000\nhttp://user:pass@host2:9000")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [
                {"username": "first", "telegram_chat_id_env": "CHAT_ONE"},
                {"username": "second", "telegram_chat_id_env": "CHAT_TWO", "check_limit": 5},
            ],
            "proxy": {"try_direct": False, "urls_env": "INSTAGRAM_PROXIES"},
        }
    )

    assert config.telegram.bot_token == "token"
    assert config.backend == "instaloader"
    assert config.telegram.backend == "bot"
    assert [account.username for account in config.accounts] == ["first", "second"]
    assert config.accounts[1].check_limit == 5
    assert config.proxy.try_direct is False
    assert config.proxy.urls == ["http://user:pass@host:9000", "http://user:pass@host2:9000"]


def test_parse_config_reads_username_from_environment(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("INSTAGRAM_USERNAME", "private_account")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@private_chat")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [
                {
                    "username_env": "INSTAGRAM_USERNAME",
                    "telegram_chat_id_env": "TELEGRAM_CHAT_ID",
                }
            ],
        }
    )

    assert config.accounts[0].username == "private_account"
    assert config.accounts[0].telegram_chat_id == "@private_chat"


def test_parse_config_ignores_disabled_accounts(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT", "@chat")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [
                {"username": "disabled", "enabled": False, "telegram_chat_id_env": "CHAT"},
                {"username": "enabled", "telegram_chat_id_env": "CHAT"},
            ],
        }
    )

    assert [account.username for account in config.accounts] == ["enabled"]


def test_parse_config_supports_backend_override(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT", "@chat")
    monkeypatch.setenv("SYNC_BACKEND", "browser")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [{"username": "account", "telegram_chat_id_env": "CHAT"}],
            "settings": {"backend": "instaloader"},
        }
    )

    assert config.backend == "browser"


def test_parse_config_supports_telethon(monkeypatch):
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash")
    monkeypatch.setenv("CHAT", "@chat")

    config = parse_config(
        {
            "telegram": {
                "backend": "telethon",
                "api_id_env": "TELEGRAM_API_ID",
                "api_hash_env": "TELEGRAM_API_HASH",
                "session_file": "data/telegram.session",
            },
            "accounts": [{"username": "account", "telegram_chat_id_env": "CHAT"}],
            "settings": {"backend": "apify"},
        }
    )

    assert config.telegram.backend == "telethon"
    assert config.telegram.api_id == 123
    assert config.backend == "apify"


def test_parse_config_supports_apify_billing_cycle_start_day(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT", "@chat")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [{"username": "account", "telegram_chat_id_env": "CHAT"}],
            "apify": {"billing_cycle_start_day": 26},
        }
    )

    assert config.apify.billing_cycle_start_day == 26


def test_parse_config_supports_public_runtime_variables(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("CHAT", "@chat")
    monkeypatch.setenv("APIFY_MAX_RESULTS_PER_RUN", "5")
    monkeypatch.setenv("APIFY_MONTHLY_RESULT_CAP", "1234")
    monkeypatch.setenv("APIFY_BILLING_CYCLE_START_DAY", "17")
    monkeypatch.setenv("BROWSER_TIMEZONE", "Europe/Berlin")

    config = parse_config(
        {
            "telegram": {"bot_token_env": "TELEGRAM_BOT_TOKEN"},
            "accounts": [{"username": "account", "telegram_chat_id_env": "CHAT"}],
            "apify": {
                "max_results_per_run": 3,
                "monthly_result_cap": 300,
                "billing_cycle_start_day": 1,
            },
            "settings": {"browser_timezone": "UTC"},
        }
    )

    assert config.apify.max_results_per_run == 5
    assert config.apify.monthly_result_cap == 1234
    assert config.apify.billing_cycle_start_day == 17
    assert config.browser_timezone == "Europe/Berlin"
