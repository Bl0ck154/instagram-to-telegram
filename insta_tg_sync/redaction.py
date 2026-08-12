from __future__ import annotations

import re
import sys
from typing import TextIO

from .config import AppConfig


_SHORTCODE_PATTERNS = [
    re.compile(r"(\bshortcode\s+)([A-Za-z0-9_-]{5,})", re.IGNORECASE),
    re.compile(r"(\bpost\s+)([A-Za-z0-9_-]{5,})", re.IGNORECASE),
    re.compile(r"(/(?:p|reel)/)([A-Za-z0-9_-]{5,})(/?)", re.IGNORECASE),
]


class RedactingTextIO:
    def __init__(self, wrapped: TextIO, literals: list[str]) -> None:
        self._wrapped = wrapped
        self._literals = sorted({value for value in literals if value}, key=len, reverse=True)

    def write(self, text: str) -> int:
        redacted = text
        for value in self._literals:
            redacted = redacted.replace(value, "<redacted>")
        for pattern in _SHORTCODE_PATTERNS:
            redacted = pattern.sub(
                lambda match: f"{match.group(1)}<redacted>{match.group(3) if match.lastindex and match.lastindex >= 3 else ''}",
                redacted,
            )
        return self._wrapped.write(redacted)

    def flush(self) -> None:
        self._wrapped.flush()

    def isatty(self) -> bool:
        return self._wrapped.isatty()

    @property
    def encoding(self) -> str | None:
        return getattr(self._wrapped, "encoding", None)

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


def install_output_redaction(config: AppConfig) -> None:
    sensitive = [
        config.telegram.bot_token,
        str(config.telegram.api_id or ""),
        config.telegram.api_hash,
        str(config.telegram.session_file or ""),
        *(account.username for account in config.accounts),
        *(account.telegram_chat_id for account in config.accounts),
        *config.proxy.urls,
        config.apify.token,
    ]
    sys.stdout = RedactingTextIO(sys.stdout, sensitive)
    sys.stderr = RedactingTextIO(sys.stderr, sensitive)
