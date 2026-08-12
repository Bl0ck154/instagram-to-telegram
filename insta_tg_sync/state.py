from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_HASH_PREFIX = "hmac-sha256:"


class ProcessedIndex:
    def __init__(self, values: list[str], key: bytes) -> None:
        self._values = set(values)
        self._key = key

    def __contains__(self, shortcode: object) -> bool:
        if not isinstance(shortcode, str):
            return False
        return _private_id("post", shortcode, self._key) in self._values

    def __len__(self) -> int:
        return len(self._values)


@dataclass
class StateStore:
    path: Path
    max_items: int = 300
    data: dict[str, Any] = field(default_factory=dict)
    _key: bytes = field(default_factory=lambda: _state_key(), init=False, repr=False)

    def load(self) -> None:
        if not self.path.exists():
            self.data = {"accounts": {}}
            return

        with self.path.open("r", encoding="utf-8") as handle:
            self.data = json.load(handle)

        if "accounts" not in self.data:
            legacy_processed = self.data.get("processed", [])
            self.data = {"accounts": {"default": {"processed": legacy_processed}}}

        self._migrate_plaintext_identifiers()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2, sort_keys=True)

    def has_account(self, username: str) -> bool:
        return self._account_key(username) in self.data.setdefault("accounts", {})

    def processed(self, username: str) -> ProcessedIndex:
        account = self._account(username)
        return ProcessedIndex(list(account.get("processed", [])), self._key)

    def mark_processed(self, username: str, shortcode: str) -> None:
        account = self._account(username)
        value = _private_id("post", shortcode, self._key)
        values = list(dict.fromkeys([*account.get("processed", []), value]))
        account["processed"] = values[-self.max_items :]

    def external_results_used(self, provider: str, billing_cycle_start_day: int = 1) -> int:
        providers = self._usage_providers(billing_cycle_start_day)
        return int(providers.get(provider, 0))

    def add_external_results(self, provider: str, count: int, billing_cycle_start_day: int = 1) -> None:
        providers = self._usage_providers(billing_cycle_start_day)
        providers[provider] = int(providers.get(provider, 0)) + count

    def _account_key(self, username: str) -> str:
        return _private_id("account", username, self._key)

    def _account(self, username: str) -> dict[str, Any]:
        key = self._account_key(username)
        return self.data.setdefault("accounts", {}).setdefault(key, {"processed": []})

    def _migrate_plaintext_identifiers(self) -> None:
        accounts = self.data.setdefault("accounts", {})
        migrated: dict[str, Any] = {}
        for account_key, account_data in accounts.items():
            safe_account_key = account_key if _is_private_id(account_key) else _private_id("account", account_key, self._key)
            if not isinstance(account_data, dict):
                account_data = {"processed": []}
            processed = []
            for value in account_data.get("processed", []):
                if not isinstance(value, str):
                    continue
                processed.append(value if _is_private_id(value) else _private_id("post", value, self._key))
            migrated[safe_account_key] = {**account_data, "processed": list(dict.fromkeys(processed))[-self.max_items :]}
        self.data["accounts"] = migrated

    def _usage_providers(self, billing_cycle_start_day: int) -> dict[str, Any]:
        if not 1 <= billing_cycle_start_day <= 28:
            raise ValueError("billing_cycle_start_day must be between 1 and 28.")

        now = _now_utc()
        usage = self.data.setdefault("usage", {})
        period = _billing_period(now, billing_cycle_start_day)
        providers = usage.setdefault(period, {})

        legacy_month = now.strftime("%Y-%m")
        if billing_cycle_start_day != 1 and now.day < billing_cycle_start_day and not providers:
            legacy_providers = usage.get(legacy_month)
            if isinstance(legacy_providers, dict):
                providers.update(legacy_providers)

        return providers


def _state_key() -> bytes:
    value = (
        os.environ.get("STATE_HMAC_KEY")
        or os.environ.get("TELEGRAM_API_HASH")
        or os.environ.get("TELEGRAM_BOT_TOKEN")
        or "local-development-state-key"
    )
    return value.encode("utf-8")


def _private_id(namespace: str, value: str, key: bytes) -> str:
    digest = hmac.new(key, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


def _is_private_id(value: str) -> bool:
    return value.startswith(_HASH_PREFIX) and len(value) == len(_HASH_PREFIX) + 64


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _billing_period(now: datetime, start_day: int) -> str:
    if now.day >= start_day:
        return now.strftime("%Y-%m-") + f"{start_day:02d}"

    previous_month = now.month - 1 or 12
    previous_year = now.year if now.month > 1 else now.year - 1
    return f"{previous_year:04d}-{previous_month:02d}-{start_day:02d}"
