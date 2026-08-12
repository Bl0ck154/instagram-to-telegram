from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TelegramConfig:
    backend: str = "bot"
    bot_token: str = ""
    api_id: int | None = None
    api_hash: str = ""
    session_file: Path | None = None


@dataclass(frozen=True)
class AccountConfig:
    username: str
    telegram_chat_id: str
    enabled: bool = True
    check_limit: int = 10
    initial_skip: int = 12
    caption_template: str = "{caption}\n\nLink: {url}"


@dataclass(frozen=True)
class ProxyConfig:
    urls: list[str] = field(default_factory=list)
    try_direct: bool = True
    shuffle: bool = True


@dataclass(frozen=True)
class ApifyConfig:
    token: str = ""
    actor_id: str = "apify/instagram-scraper"
    timeout_seconds: int = 180
    max_results_per_run: int = 3
    monthly_result_cap: int = 300
    billing_cycle_start_day: int = 1


@dataclass(frozen=True)
class AppConfig:
    telegram: TelegramConfig
    accounts: list[AccountConfig]
    backend: str = "instaloader"
    apify: ApifyConfig = field(default_factory=ApifyConfig)
    proxy: ProxyConfig = field(default_factory=ProxyConfig)
    state_file: Path = Path("data/state.json")
    temp_dir: Path = Path("data/tmp")
    debug_dir: Path = Path("data/debug")
    browser_storage_state: Path | None = None
    browser_timezone: str = "UTC"
    curl_impersonate: str = "chrome120"
    archive_dir: Path | None = None
    request_timeout: int = 25
    max_connection_attempts: int = 1
    post_delay_seconds: float = 4.0
    connection_retry_min_seconds: float = 3.0
    connection_retry_max_seconds: float = 8.0
    user_agents: list[str] = field(default_factory=list)
    dry_run: bool = False
    initialize_only: bool = False


DEFAULT_USER_AGENTS = [
    "Instagram 264.0.0.22.106 Android (28/9.0; 480dpi; 1080x2260; samsung; SM-G960F)",
    "Instagram 215.0.0.27.359 iPhone (iPhone13,3; iOS 15_2; en_US; en-US; scale=3.00)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        if config_path.suffix.lower() == ".json":
            raw = json.load(handle)
        else:
            raw = yaml.safe_load(handle) or {}

    return parse_config(raw)


def parse_config(raw: dict[str, Any]) -> AppConfig:
    telegram = raw.get("telegram") or {}
    telegram_config = _parse_telegram(telegram)

    accounts = [_parse_account(item) for item in raw.get("accounts", [])]
    accounts = [account for account in accounts if account.enabled]
    if not accounts:
        raise ValueError("At least one enabled account is required.")

    proxy = raw.get("proxy") or {}
    proxy_urls = list(proxy.get("urls") or [])
    proxy_urls.extend(_load_proxy_urls_from_env(proxy.get("urls_env")))
    proxy_urls.extend(_load_proxy_urls_from_file(proxy.get("file")))

    settings = raw.get("settings") or {}
    user_agents = list(settings.get("user_agents") or DEFAULT_USER_AGENTS)
    backend = str(os.environ.get("SYNC_BACKEND") or settings.get("backend", "instaloader")).lower()
    if backend not in {"instaloader", "browser", "curl_cffi", "apify", "auto"}:
        raise ValueError("settings.backend must be one of: instaloader, browser, curl_cffi, apify, auto.")

    return AppConfig(
        telegram=telegram_config,
        accounts=accounts,
        backend=backend,
        apify=_parse_apify(raw.get("apify") or {}),
        proxy=ProxyConfig(
            urls=[url for url in proxy_urls if url],
            try_direct=bool(proxy.get("try_direct", True)),
            shuffle=bool(proxy.get("shuffle", True)),
        ),
        state_file=Path(settings.get("state_file", "data/state.json")),
        temp_dir=Path(settings.get("temp_dir", "data/tmp")),
        debug_dir=Path(settings.get("debug_dir", "data/debug")),
        browser_storage_state=Path(settings["browser_storage_state"]) if settings.get("browser_storage_state") else None,
        browser_timezone=str(os.environ.get("BROWSER_TIMEZONE") or settings.get("browser_timezone", "UTC")),
        curl_impersonate=str(settings.get("curl_impersonate", "chrome120")),
        archive_dir=Path(settings["archive_dir"]) if settings.get("archive_dir") else None,
        request_timeout=int(settings.get("request_timeout", 25)),
        max_connection_attempts=int(settings.get("max_connection_attempts", 1)),
        post_delay_seconds=float(settings.get("post_delay_seconds", 4.0)),
        connection_retry_min_seconds=float(settings.get("connection_retry_min_seconds", 3.0)),
        connection_retry_max_seconds=float(settings.get("connection_retry_max_seconds", 8.0)),
        user_agents=user_agents,
        dry_run=bool(settings.get("dry_run", False)),
        initialize_only=bool(settings.get("initialize_only", False)),
    )


def _parse_apify(raw: dict[str, Any]) -> ApifyConfig:
    token = _env_or_value(raw.get("token_env"), raw.get("token"))
    max_results_per_run = int(os.environ.get("APIFY_MAX_RESULTS_PER_RUN") or raw.get("max_results_per_run", 3))
    monthly_result_cap = int(os.environ.get("APIFY_MONTHLY_RESULT_CAP") or raw.get("monthly_result_cap", 300))
    billing_cycle_start_day = int(os.environ.get("APIFY_BILLING_CYCLE_START_DAY") or raw.get("billing_cycle_start_day", 1))
    if not 1 <= billing_cycle_start_day <= 28:
        raise ValueError("apify.billing_cycle_start_day must be between 1 and 28.")
    return ApifyConfig(
        token=token,
        actor_id=str(raw.get("actor_id", "apify/instagram-scraper")),
        timeout_seconds=int(raw.get("timeout_seconds", 180)),
        max_results_per_run=max_results_per_run,
        monthly_result_cap=monthly_result_cap,
        billing_cycle_start_day=billing_cycle_start_day,
    )


def _parse_telegram(raw: dict[str, Any]) -> TelegramConfig:
    backend = str(os.environ.get("TELEGRAM_BACKEND") or raw.get("backend", "bot")).lower()
    if backend not in {"bot", "telethon"}:
        raise ValueError("telegram.backend must be one of: bot, telethon.")

    bot_token = _env_or_value(raw.get("bot_token_env"), raw.get("bot_token"))
    api_id_raw = _env_or_value(raw.get("api_id_env"), raw.get("api_id"))
    api_hash = _env_or_value(raw.get("api_hash_env"), raw.get("api_hash"))
    session_file_raw = _env_or_value(raw.get("session_file_env"), raw.get("session_file"))

    if backend == "bot" and not bot_token:
        raise ValueError("Telegram bot token is required for bot backend.")
    if backend == "telethon" and (not api_id_raw or not api_hash or not session_file_raw):
        raise ValueError("Telegram api_id, api_hash, and session_file are required for telethon backend.")

    return TelegramConfig(
        backend=backend,
        bot_token=bot_token,
        api_id=int(api_id_raw) if api_id_raw else None,
        api_hash=api_hash,
        session_file=Path(session_file_raw) if session_file_raw else None,
    )


def _parse_account(raw: dict[str, Any]) -> AccountConfig:
    username = _normalize_instagram_username(_env_or_value(raw.get("username_env"), raw.get("username")))
    if not username:
        env_name = raw.get("username_env")
        hint = f" Set environment variable {env_name}." if env_name else ""
        raise ValueError(f"Instagram account username is required.{hint}")

    chat_id = _env_or_value(raw.get("telegram_chat_id_env"), raw.get("telegram_chat_id"))
    if not chat_id:
        env_name = raw.get("telegram_chat_id_env")
        hint = f" Set environment variable {env_name}." if env_name else ""
        raise ValueError(f"Telegram chat id is required for the configured account.{hint}")

    return AccountConfig(
        username=username,
        telegram_chat_id=chat_id,
        enabled=bool(raw.get("enabled", True)),
        check_limit=int(raw.get("check_limit", 10)),
        initial_skip=int(raw.get("initial_skip", 12)),
        caption_template=str(raw.get("caption_template", "{caption}\n\nLink: {url}")),
    )


def _normalize_instagram_username(value: str) -> str:
    return value.strip().lstrip("@").strip()


def _env_or_value(env_name: str | None, value: Any) -> str:
    if env_name:
        return os.environ.get(str(env_name), "")
    return str(value or "")


def _load_proxy_urls_from_env(env_name: str | None) -> list[str]:
    if not env_name:
        return []
    raw = os.environ.get(str(env_name), "")
    return [item.strip() for item in raw.replace("\n", ",").split(",") if item.strip()]


def _load_proxy_urls_from_file(path: str | None) -> list[str]:
    if not path:
        return []

    proxy_path = Path(path)
    if not proxy_path.exists():
        return []

    urls: list[str] = []
    with proxy_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            urls.append(_normalize_proxy(value))
    return urls


def _normalize_proxy(value: str) -> str:
    if "://" in value:
        return value

    parts = value.split(":")
    if len(parts) == 4:
        host, port, username, password = parts
        return f"http://{username}:{password}@{host}:{port}"
    return value
