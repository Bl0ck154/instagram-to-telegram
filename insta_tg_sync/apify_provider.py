from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from time import sleep
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests

from .config import AccountConfig, AppConfig


@dataclass(frozen=True)
class ApifyPost:
    shortcode: str
    url: str
    caption: str
    media_urls: list[str]


@dataclass(frozen=True)
class _ImageCandidate:
    url: str
    width: int
    height: int
    priority: int


class ApifyInstagramClient:
    RESULTS_TYPES = ("posts", "reels")
    DETAILS_RESULTS_LIMIT = 1
    MAX_ATTEMPTS = 3

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def fetch_posts(self, account: AccountConfig, limit: int) -> list[ApifyPost]:
        posts: list[ApifyPost] = []
        for results_type in self.RESULTS_TYPES:
            posts.extend(self._fetch_posts(account, limit, results_type))
        posts.extend(self._fetch_posts(account, self.DETAILS_RESULTS_LIMIT, "details", normalize_limit=limit))
        return _dedupe_posts(posts, prefer_later=True)[:limit]

    def fetch_raw_items(self, account: AccountConfig, limit: int, results_type: str) -> list[dict]:
        if not self.config.apify.token:
            raise ValueError("APIFY_TOKEN is required for apify backend.")

        actor = quote(self.config.apify.actor_id.replace("/", "~"), safe="~")
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        response = self._post_with_retry(
            url,
            {
                "directUrls": [_direct_url(account.username, results_type)],
                "resultsType": results_type,
                "resultsLimit": limit,
                "searchType": "user",
                "searchLimit": 1,
            },
            results_type,
        )
        return response.json()

    def _fetch_posts(self, account: AccountConfig, limit: int, results_type: str, normalize_limit: int | None = None) -> list[ApifyPost]:
        items = self.fetch_raw_items(account, limit, results_type)
        posts = normalize_apify_posts(items, normalize_limit or limit)
        print(f"Apify {results_type} returned {len(items)} raw item(s), normalized {len(posts)} post(s).", flush=True)
        return posts

    def _post_with_retry(self, url: str, payload: dict, results_type: str) -> requests.Response:
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            response = requests.post(
                url,
                params={"token": self.config.apify.token, "timeout": self.config.apify.timeout_seconds},
                json=payload,
                timeout=self.config.apify.timeout_seconds + 30,
            )
            if response.status_code in {429} or response.status_code >= 500:
                if attempt < self.MAX_ATTEMPTS:
                    delay = _retry_delay(response, attempt)
                    print(
                        f"Apify {results_type} returned HTTP {response.status_code}; retrying in {delay:.1f}s "
                        f"({attempt}/{self.MAX_ATTEMPTS}).",
                        flush=True,
                    )
                    sleep(delay)
                    continue
            response.raise_for_status()
            return response

        response.raise_for_status()
        return response


def normalize_apify_posts(items: list[dict], limit: int) -> list[ApifyPost]:
    posts: list[ApifyPost] = []
    for item in _iter_post_items(items):
        shortcode = item.get("shortCode") or _shortcode_from_url(item.get("url", ""))
        if not shortcode:
            continue
        media_urls = _media_urls(item)
        if not media_urls:
            continue
        posts.append(
            ApifyPost(
                shortcode=shortcode,
                url=item.get("url") or f"https://www.instagram.com/p/{shortcode}/",
                caption=item.get("caption") or "",
                media_urls=media_urls,
            )
        )
        if len(posts) >= limit:
            break
    return posts


def _iter_post_items(items: list[dict]):
    for item in items:
        latest_posts = item.get("latestPosts")
        if isinstance(latest_posts, list):
            yield from (post for post in latest_posts if isinstance(post, dict))
            continue
        yield item


def _dedupe_posts(posts: list[ApifyPost], prefer_later: bool = False) -> list[ApifyPost]:
    seen = set()
    unique = []
    index_by_shortcode: dict[str, int] = {}
    for post in posts:
        if post.shortcode in seen:
            if prefer_later:
                unique[index_by_shortcode[post.shortcode]] = post
            continue
        seen.add(post.shortcode)
        index_by_shortcode[post.shortcode] = len(unique)
        unique.append(post)
    return unique


def _direct_url(username: str, results_type: str) -> str:
    suffix = "reels/" if results_type == "reels" else ""
    return f"https://www.instagram.com/{username}/{suffix}"


def _retry_delay(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 30.0)
        except ValueError:
            pass
    return float(2 ** attempt)


def download_apify_media(post: ApifyPost, target_dir: Path, timeout: int, user_agent: str) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index, url in enumerate(post.media_urls, start=1):
        response, downloaded_url = _download_response(url, post.url, timeout, user_agent)
        destination = target_dir / f"{post.shortcode}_{index}{_media_suffix(downloaded_url)}"
        destination.write_bytes(response.content)
        print(_download_diagnostic(index, len(post.media_urls), downloaded_url, response.content), flush=True)
        files.append(destination)
    return files


def _download_response(url: str, referer: str, timeout: int, user_agent: str) -> tuple[requests.Response, str]:
    last_response: requests.Response | None = None
    for candidate_url in _download_url_candidates(url):
        response = requests.get(candidate_url, headers={"User-Agent": user_agent, "Referer": referer}, timeout=timeout)
        if response.ok:
            return response, candidate_url
        last_response = response

    if last_response is None:
        raise RuntimeError("No media download URL candidates were generated.")
    last_response.raise_for_status()
    return last_response, url


def _download_url_candidates(url: str) -> list[str]:
    upgraded = _high_resolution_instagram_url(url)
    return list(dict.fromkeys([upgraded, url] if upgraded else [url]))


def _high_resolution_instagram_url(url: str) -> str:
    parsed = urlparse(url)
    if "cdninstagram.com" not in parsed.netloc:
        return ""

    query = parse_qsl(parsed.query, keep_blank_values=True)
    updated_query = []
    changed = False
    for key, value in query:
        if key == "stp":
            updated_value = re.sub(r"(?<=_)s\d+x\d+(?=(_|$))", "p1080x1080_sh2.08", value, count=1)
            if updated_value != value:
                changed = True
                value = updated_value
        updated_query.append((key, value))

    if not changed:
        return ""
    return urlunparse(parsed._replace(query=urlencode(updated_query)))


def _media_urls(item: dict) -> list[str]:
    urls: list[str] = []

    urls.extend(_carousel_media_urls(item))

    if not urls:
        urls.extend(_best_media_urls(item))

    return list(dict.fromkeys(urls))[:10]


def _carousel_media_urls(item: dict) -> list[str]:
    urls: list[str] = []
    if _has_carousel_children(item):
        urls.extend(_media_urls_from_collection(item.get("images")))
        if urls:
            return urls

    for key in ("childPosts", "carouselMedia", "carousel_media", "children"):
        value = item.get(key)
        if isinstance(value, list):
            for child in value:
                if isinstance(child, dict):
                    urls.extend(_best_media_urls(child))
                elif isinstance(child, str) and _is_media_url(child):
                    urls.append(child)

    for key in ("carouselImages", "carousel_images"):
        urls.extend(_media_urls_from_collection(item.get(key)))
    for key in ("carouselVideos", "carousel_videos"):
        urls.extend(_media_urls_from_collection(item.get(key)))

    return urls


def _has_carousel_children(item: dict) -> bool:
    for key in ("childPosts", "carouselMedia", "carousel_media", "children"):
        value = item.get(key)
        if isinstance(value, list) and len(value) > 1:
            return True
    return False


def _media_urls_from_collection(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    urls: list[str] = []
    for item in value:
        if isinstance(item, str) and _is_media_url(item):
            urls.append(item)
        elif isinstance(item, dict):
            direct_candidates = _candidate_from_value(item, 65)
            if direct_candidates:
                urls.append(max(direct_candidates, key=_image_candidate_score).url)
            else:
                urls.extend(_best_media_urls(item))
    return urls


def _best_media_urls(item: dict) -> list[str]:
    video_url = item.get("videoUrl")
    if isinstance(video_url, str) and video_url:
        return [video_url]

    image_url = _best_image_url(item)
    if image_url:
        return [image_url]
    return []


def _best_image_url(item: dict) -> str:
    candidates = _image_candidates(item)
    if not candidates:
        return ""
    return max(candidates, key=_image_candidate_score).url


def _image_candidates(item: dict) -> list[_ImageCandidate]:
    candidates: list[_ImageCandidate] = []
    for priority, key in (
        (80, "fullImageUrl"),
        (70, "imageUrl"),
        (60, "displayUrl"),
        (20, "thumbnailUrl"),
    ):
        candidates.extend(_candidate_from_value(item.get(key), priority))

    for priority, key in (
        (75, "displayResources"),
        (75, "display_resources"),
        (65, "images"),
        (15, "thumbnailResources"),
        (15, "thumbnail_resources"),
    ):
        candidates.extend(_candidate_from_value(item.get(key), priority))

    for key in ("image_versions2", "imageVersions2", "imageVersions"):
        value = item.get(key)
        if isinstance(value, dict):
            candidates.extend(_candidate_from_value(value.get("candidates") or value.get("items"), 75))
        else:
            candidates.extend(_candidate_from_value(value, 75))

    return _dedupe_candidates(candidates)


def _candidate_from_value(value: object, priority: int) -> list[_ImageCandidate]:
    if isinstance(value, str):
        return [_make_candidate(value, {}, priority)] if _is_media_url(value) else []
    if isinstance(value, dict):
        url = value.get("url") or value.get("src") or value.get("uri")
        return [_make_candidate(url, value, priority)] if isinstance(url, str) and _is_media_url(url) else []
    if isinstance(value, list):
        candidates: list[_ImageCandidate] = []
        for item in value:
            candidates.extend(_candidate_from_value(item, priority))
        return candidates
    return []


def _make_candidate(url: str, metadata: dict, priority: int) -> _ImageCandidate:
    width = _int_value(metadata, "width", "config_width")
    height = _int_value(metadata, "height", "config_height")
    if not width or not height:
        width, height = _dimensions_from_url(url)
    return _ImageCandidate(url=url, width=width, height=height, priority=priority)


def _dedupe_candidates(candidates: list[_ImageCandidate]) -> list[_ImageCandidate]:
    best_by_url: dict[str, _ImageCandidate] = {}
    for candidate in candidates:
        current = best_by_url.get(candidate.url)
        if current is None or _image_candidate_score(candidate) > _image_candidate_score(current):
            best_by_url[candidate.url] = candidate
    return list(best_by_url.values())


def _image_candidate_score(candidate: _ImageCandidate) -> tuple[int, int]:
    return (candidate.priority, candidate.width * candidate.height)


def _int_value(mapping: dict, *keys: str) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


_DIMENSIONS_RE = re.compile(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)")


def _dimensions_from_url(url: str) -> tuple[int, int]:
    matches = _DIMENSIONS_RE.findall(url)
    if not matches:
        return (0, 0)
    return max(((int(width), int(height)) for width, height in matches), key=lambda size: size[0] * size[1])


def _is_media_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def describe_apify_media_fields(item: dict) -> list[str]:
    lines = [f"Apify raw media keys: {', '.join(sorted(item.keys()))}"]
    for label, target in [("post", item), *_child_targets(item)]:
        lines.extend(_describe_media_target(label, target))
    return lines


def _child_targets(item: dict) -> list[tuple[str, dict]]:
    children: list[tuple[str, dict]] = []
    for key in ("childPosts", "carouselMedia", "carousel_media", "children"):
        value = item.get(key)
        if isinstance(value, list):
            for index, child in enumerate(value, start=1):
                if isinstance(child, dict):
                    children.append((f"{key}[{index}]", child))
    return children


def _describe_media_target(label: str, item: dict) -> list[str]:
    lines: list[str] = []
    for key in ("displayUrl", "imageUrl", "fullImageUrl", "thumbnailUrl", "videoUrl"):
        value = item.get(key)
        if isinstance(value, str) and value:
            lines.append(f"{label}.{key}: {_safe_media_source(value)}")
    for key in ("images", "displayResources", "display_resources", "thumbnailResources", "image_versions2", "imageVersions2"):
        value = item.get(key)
        count = len(value.get("candidates") or value.get("items") or []) if isinstance(value, dict) else len(value) if isinstance(value, list) else 0
        if count:
            lines.append(f"{label}.{key}: {count} candidate(s)")
    return lines


def _shortcode_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] in {"p", "reel"}:
        return parts[1]
    return ""


def _media_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    if ".mp4" in path:
        return ".mp4"
    if ".png" in path:
        return ".png"
    return ".jpg"


def _download_diagnostic(index: int, total: int, url: str, content: bytes) -> str:
    dimensions = _image_dimensions(content)
    dimension_text = f"{dimensions[0]}x{dimensions[1]}" if dimensions else "unknown"
    return (
        f"Downloaded Apify media {index}/{total}: "
        f"bytes={len(content)}, dimensions={dimension_text}, source={_safe_media_source(url)}"
    )


def _image_dimensions(content: bytes) -> tuple[int, int] | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n") and len(content) >= 24:
        return (int.from_bytes(content[16:20], "big"), int.from_bytes(content[20:24], "big"))
    if content.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(content)
    return None


def _jpeg_dimensions(content: bytes) -> tuple[int, int] | None:
    index = 2
    while index < len(content) - 9:
        if content[index] != 0xFF:
            index += 1
            continue
        marker = content[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if marker == 0xDA or index + 2 > len(content):
            break
        segment_length = int.from_bytes(content[index : index + 2], "big")
        if segment_length < 2 or index + segment_length > len(content):
            break
        if 0xC0 <= marker <= 0xCF and marker not in {0xC4, 0xC8, 0xCC}:
            height = int.from_bytes(content[index + 3 : index + 5], "big")
            width = int.from_bytes(content[index + 5 : index + 7], "big")
            return (width, height)
        index += segment_length
    return None


def _safe_media_source(url: str) -> str:
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "media"
    stp = ""
    for item in parsed.query.split("&"):
        if item.startswith("stp="):
            stp = item[:80]
            break
    return f"{parsed.netloc}/{filename}" + (f"?{stp}" if stp else "")
