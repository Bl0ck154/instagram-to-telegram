from __future__ import annotations

import random
from pathlib import Path

import instaloader

from .config import AppConfig


def create_loader(config: AppConfig, proxy_url: str | None) -> instaloader.Instaloader:
    loader = instaloader.Instaloader(
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        max_connection_attempts=config.max_connection_attempts,
        request_timeout=config.request_timeout,
        user_agent=random.choice(config.user_agents),
    )
    loader.context._session.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
    return loader


def media_files(directory: Path) -> list[Path]:
    suffixes = {".jpg", ".jpeg", ".png", ".mp4"}
    return sorted(path for path in directory.glob("*") if path.suffix.lower() in suffixes)


def is_connection_error(error: Exception) -> bool:
    return isinstance(error, (instaloader.ConnectionException, instaloader.LoginRequiredException))
