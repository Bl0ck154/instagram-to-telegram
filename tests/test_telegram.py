from pathlib import Path

from insta_tg_sync.config import TelegramConfig
from insta_tg_sync.telegram import TelegramBot, TelegramFallbackSender, _describe_bot_token, create_telegram_sender


def test_telethon_backend_uses_bot_fallback_when_token_is_available():
    sender = create_telegram_sender(
        TelegramConfig(
            backend="telethon",
            bot_token="bot-token",
            api_id=123,
            api_hash="hash",
            session_file=Path("data/telegram.session"),
        )
    )

    assert isinstance(sender, TelegramFallbackSender)


def test_bot_token_diagnostics_do_not_expose_secret():
    token = "123456789:abcdefghijklmnopqrstuvwxyzABCDE"

    description = _describe_bot_token(token)

    assert "present" in description
    assert "numeric-prefix" in description
    assert "valid-shape" in description
    assert token not in description
    assert "abcdefghijklmnopqrstuvwxyz" not in description


def test_bot_sender_rejects_empty_token():
    try:
        TelegramBot("  ")
    except ValueError as error:
        assert "Telegram bot token is empty" in str(error)
    else:
        raise AssertionError("Expected empty bot token to be rejected")
