from __future__ import annotations

from pathlib import Path
from time import sleep
import re

import requests
from telethon import TelegramClient

from .config import TelegramConfig


class TelegramSender:
    def send_media(self, chat_id: str, caption: str, files: list[Path]) -> None:
        raise NotImplementedError


def create_telegram_sender(config: TelegramConfig) -> TelegramSender:
    print(_describe_telegram_config(config))
    if config.backend == "telethon":
        if config.api_id is None or not config.session_file:
            raise ValueError("Telethon config is incomplete.")
        primary = TelegramTelethon(config.session_file, config.api_id, config.api_hash)
        fallback = TelegramBot(config.bot_token) if config.bot_token else None
        return TelegramFallbackSender(primary, fallback)
    return TelegramBot(config.bot_token)


class TelegramFallbackSender(TelegramSender):
    def __init__(self, primary: TelegramSender, fallback: TelegramSender | None) -> None:
        self.primary = primary
        self.fallback = fallback

    def send_media(self, chat_id: str, caption: str, files: list[Path]) -> None:
        try:
            self.primary.send_media(chat_id, caption, files)
        except Exception as error:
            if self.fallback is None:
                raise
            print(f"Primary Telegram sender failed; falling back to Bot API: {error}")
            self.fallback.send_media(chat_id, caption, files)


class TelegramBot(TelegramSender):
    def __init__(self, token: str, timeout: int = 60) -> None:
        token = token.strip()
        if not token:
            raise ValueError("Telegram bot token is empty. Set TELEGRAM_BOT_TOKEN to a token from @BotFather.")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def send_media(self, chat_id: str, caption: str, files: list[Path]) -> None:
        media_files = [path for path in files if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".mp4"}]
        if not media_files:
            return

        if len(media_files) == 1:
            self._send_single(chat_id, caption, media_files[0])
            return

        self._send_group(chat_id, caption, media_files[:10])

    def _send_single(self, chat_id: str, caption: str, file_path: Path) -> None:
        is_video = file_path.suffix.lower() == ".mp4"
        endpoint = "sendVideo" if is_video else "sendPhoto"
        field_name = "video" if is_video else "photo"
        with file_path.open("rb") as handle:
            self._post(
                f"{self.base_url}/{endpoint}",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={field_name: handle},
            )

    def _send_group(self, chat_id: str, caption: str, files: list[Path]) -> None:
        upload_files = {}
        media = []
        handles = []
        try:
            for index, file_path in enumerate(files):
                field = f"file{index}"
                handle = file_path.open("rb")
                handles.append(handle)
                upload_files[field] = handle
                item = {"type": "video" if file_path.suffix.lower() == ".mp4" else "photo", "media": f"attach://{field}"}
                if index == 0 and caption:
                    item["caption"] = caption[:1024]
                media.append(item)

            self._post(
                f"{self.base_url}/sendMediaGroup",
                data={"chat_id": chat_id, "media": __import__("json").dumps(media)},
                files=upload_files,
            )
        finally:
            for handle in handles:
                handle.close()

    def _post(self, url: str, **kwargs) -> requests.Response:
        response = requests.Response()
        for attempt in range(3):
            _rewind_files(kwargs.get("files"))
            response = requests.post(url, timeout=self.timeout, **kwargs)
            if response.status_code == 429:
                retry_after = 5
                try:
                    retry_after = int(response.json().get("parameters", {}).get("retry_after", retry_after))
                except ValueError:
                    pass
                sleep(retry_after)
                continue
            if response.status_code >= 500 and attempt < 2:
                sleep(2 ** attempt)
                continue
            self._raise_for_status(response, url)
            return response
        self._raise_for_status(response, url)
        return response

    def _raise_for_status(self, response: requests.Response, url: str) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            if response.status_code == 404 and "/bot" in url:
                raise RuntimeError(
                    "Telegram Bot API returned 404. Check that TELEGRAM_BOT_TOKEN is a valid "
                    "bot token from @BotFather and was copied without extra spaces."
                ) from error
            if response.status_code == 400:
                raise RuntimeError(
                    "Telegram Bot API returned 400. Check the configured Telegram chat ID and confirm "
                    "the bot can post to the target chat/channel."
                ) from error
            if response.status_code == 403:
                raise RuntimeError(
                    "Telegram Bot API returned 403. Add the bot to the target chat/channel and grant posting rights."
                ) from error
            raise


def _rewind_files(files: object) -> None:
    if isinstance(files, dict):
        values = files.values()
    elif isinstance(files, (list, tuple)):
        values = files
    else:
        return

    for value in values:
        handle = value[-1] if isinstance(value, tuple) else value
        if hasattr(handle, "seek"):
            handle.seek(0)


_BOT_TOKEN_PATTERN = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def _describe_telegram_config(config: TelegramConfig) -> str:
    parts = [f"Telegram backend={config.backend}"]
    if config.bot_token:
        parts.append(f"bot_token={_describe_bot_token(config.bot_token)}")
    else:
        parts.append("bot_token=missing")

    if config.backend == "telethon":
        parts.append(f"api_id={'set' if config.api_id else 'missing'}")
        parts.append(f"api_hash={'set' if config.api_hash else 'missing'}")
        parts.append(f"session_file={_describe_session_file(config.session_file)}")

    return "; ".join(parts)


def _describe_bot_token(token: str) -> str:
    value = token.strip()
    if not value:
        return "empty"
    prefix = value.split(":", 1)[0]
    prefix_status = "numeric-prefix" if prefix.isdigit() else "non-numeric-prefix"
    shape = "valid-shape" if _BOT_TOKEN_PATTERN.match(value) else "unexpected-shape"
    return f"present({prefix_status}, {shape}, length={len(value)})"


def _describe_session_file(session_file: Path | None) -> str:
    if session_file is None:
        return "missing"
    if not session_file.exists():
        return f"missing at {session_file}"
    size = session_file.stat().st_size
    return f"present at {session_file} ({size} bytes)"


class TelegramTelethon(TelegramSender):
    def __init__(self, session_file: Path, api_id: int, api_hash: str) -> None:
        self.session_file = session_file
        self.api_id = api_id
        self.api_hash = api_hash

    def send_media(self, chat_id: str, caption: str, files: list[Path]) -> None:
        import asyncio

        asyncio.run(self._send_media(chat_id, caption, files))

    async def _send_media(self, chat_id: str, caption: str, files: list[Path]) -> None:
        client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise RuntimeError("Telethon session is not authorized. Refresh the session secret.")
            await client.send_message(chat_id, message=caption, file=[str(path) for path in files])
        finally:
            await client.disconnect()
