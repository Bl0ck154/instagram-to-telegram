from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi import requests

from .config import AccountConfig, AppConfig


@dataclass(frozen=True)
class CurlPost:
    shortcode: str
    url: str
    caption: str
    media_urls: list[str]


class CurlCffiInstagramClient:
    def __init__(self, config: AppConfig, proxy_url: str | None = None) -> None:
        self.config = config
        self.proxy_url = proxy_url

    def fetch_posts(self, account: AccountConfig, limit: int) -> list[CurlPost]:
        url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={account.username}"
        response = requests.get(
            url,
            headers=_headers(self.config.user_agents[-1]),
            proxies={"http": self.proxy_url, "https": self.proxy_url} if self.proxy_url else None,
            impersonate=self.config.curl_impersonate,
            timeout=self.config.request_timeout,
        )
        if response.status_code != 200:
            raise RuntimeError(f"curl_cffi Instagram request failed: HTTP {response.status_code}: {response.text[:200]}")

        user = response.json().get("data", {}).get("user") or {}
        edges = user.get("edge_owner_to_timeline_media", {}).get("edges") or []
        posts: list[CurlPost] = []
        for edge in edges[:limit]:
            node = edge.get("node") or {}
            shortcode = node.get("shortcode") or ""
            if not shortcode:
                continue
            media_urls = _media_urls(node)
            if not media_urls:
                continue
            posts.append(
                CurlPost(
                    shortcode=shortcode,
                    url=f"https://www.instagram.com/p/{shortcode}/",
                    caption=_caption(node),
                    media_urls=media_urls,
                )
            )
        return posts


def download_curl_media(
    post: CurlPost,
    target_dir: Path,
    timeout: int,
    user_agent: str,
    impersonate: str,
    proxy_url: str | None = None,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, url in enumerate(post.media_urls, start=1):
        suffix = _media_suffix(url)
        destination = target_dir / f"{post.shortcode}_{index}{suffix}"
        response = requests.get(
            url,
            headers={"User-Agent": user_agent, "Referer": post.url},
            proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None,
            impersonate=impersonate,
            timeout=timeout,
        )
        response.raise_for_status()
        destination.write_bytes(response.content)
        files.append(destination)
    return files


def _headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "129477",
        "X-IG-WWW-Claim": "0",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "*/*",
        "Referer": "https://www.instagram.com/",
    }


def _caption(node: dict) -> str:
    edges = node.get("edge_media_to_caption", {}).get("edges") or []
    if not edges:
        return ""
    return ((edges[0].get("node") or {}).get("text") or "").strip()


def _media_urls(node: dict) -> list[str]:
    children = node.get("edge_sidecar_to_children", {}).get("edges") or []
    if children:
        urls = []
        for child in children:
            child_node = child.get("node") or {}
            value = child_node.get("video_url") or child_node.get("display_url")
            if value:
                urls.append(value)
        return urls[:10]

    value = node.get("video_url") or node.get("display_url")
    return [value] if value else []


def _media_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    if ".mp4" in path:
        return ".mp4"
    if ".png" in path:
        return ".png"
    return ".jpg"
