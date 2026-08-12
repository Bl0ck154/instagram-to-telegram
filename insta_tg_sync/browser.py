from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from .config import AccountConfig, AppConfig


@dataclass(frozen=True)
class BrowserPost:
    shortcode: str
    url: str
    caption: str
    media_urls: list[str]


class BrowserInstagramClient:
    def __init__(self, config: AppConfig, proxy_url: str | None = None) -> None:
        self.config = config
        self.proxy_url = proxy_url

    def fetch_posts(self, account: AccountConfig, limit: int) -> list[BrowserPost]:
        return asyncio.run(self._fetch_posts(account, limit))

    async def _fetch_posts(self, account: AccountConfig, limit: int) -> list[BrowserPost]:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=True,
                proxy=_playwright_proxy(self.proxy_url),
                args=["--disable-blink-features=AutomationControlled"],
            )
            context_options = {
                "viewport": {"width": 1365, "height": 900},
                "user_agent": self.config.user_agents[-1],
                "locale": "en-US",
                "timezone_id": self.config.browser_timezone,
            }
            if self.config.browser_storage_state and self.config.browser_storage_state.exists():
                context_options["storage_state"] = str(self.config.browser_storage_state)
                print(f"Using browser storage state: {self.config.browser_storage_state}")
            context = await browser.new_context(**context_options)
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = await context.new_page()
            try:
                shortcodes = await self._profile_shortcodes(page, account.username, limit)
                posts = []
                for shortcode in shortcodes:
                    post = await self._post_details(page, shortcode)
                    if post.media_urls:
                        posts.append(post)
                return posts
            finally:
                await browser.close()

    async def _profile_shortcodes(self, page, username: str, limit: int) -> list[str]:
        await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=self.config.request_timeout * 1000)
        await page.wait_for_timeout(1500)
        await self._continue_saved_login_if_needed(page, username)

        if await _looks_blocked(page):
            raise RuntimeError("Instagram blocked or challenged the browser profile request.")

        shortcodes: list[str] = []
        for _ in range(3):
            hrefs = await page.locator('a[href*="/p/"], a[href*="/reel/"]').evaluate_all(
                "nodes => nodes.map(node => node.href)"
            )
            for href in hrefs:
                shortcode = _shortcode_from_url(str(href))
                if shortcode and shortcode not in shortcodes:
                    shortcodes.append(shortcode)
                if len(shortcodes) >= limit:
                    return shortcodes
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(900)

        if not shortcodes:
            html = await page.content()
            for shortcode in _shortcodes_from_html(html):
                if shortcode not in shortcodes:
                    shortcodes.append(shortcode)
                if len(shortcodes) >= limit:
                    break

        if not shortcodes:
            await self._save_debug_snapshot(page, username)

        return shortcodes[:limit]

    async def _save_debug_snapshot(self, page, username: str) -> None:
        debug_dir = self.config.debug_dir / username
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "profile.html").write_text(await page.content(), encoding="utf-8")
        await page.screenshot(path=str(debug_dir / "profile.png"), full_page=True)
        body_text = await page.locator("body").inner_text(timeout=3000)
        (debug_dir / "profile.txt").write_text(body_text[:10000], encoding="utf-8")

    async def _continue_saved_login_if_needed(self, page, username: str) -> None:
        continue_button = page.get_by_text("Continue", exact=True).first
        if await continue_button.count() == 0:
            return
        await continue_button.click()
        await page.wait_for_timeout(2500)
        await page.goto(f"https://www.instagram.com/{username}/", wait_until="domcontentloaded", timeout=self.config.request_timeout * 1000)
        await page.wait_for_timeout(2500)

    async def _post_details(self, page, shortcode: str) -> BrowserPost:
        url = f"https://www.instagram.com/p/{shortcode}/"
        await page.goto(url, wait_until="domcontentloaded", timeout=self.config.request_timeout * 1000)
        await page.wait_for_timeout(1500)

        if await _looks_blocked(page):
            raise RuntimeError(f"Instagram blocked or challenged post request: {shortcode}")

        caption = await _meta_content(page, "meta[property='og:description']")
        media_urls = await self._media_urls(page)
        return BrowserPost(shortcode=shortcode, url=url, caption=_clean_caption(caption), media_urls=media_urls)

    async def _media_urls(self, page) -> list[str]:
        urls: list[str] = []
        for selector in ["meta[property='og:video']", "meta[property='og:image']"]:
            value = await _meta_content(page, selector)
            if value:
                urls.append(value)

        try:
            article_urls = await page.locator("article img, article video").evaluate_all(
                "nodes => nodes.map(node => node.currentSrc || node.src).filter(Boolean)"
            )
            for value in article_urls:
                if value and value not in urls:
                    urls.append(value)
        except PlaywrightTimeoutError:
            pass

        return urls[:10]


def download_browser_media(
    post: BrowserPost,
    target_dir: Path,
    timeout: int,
    user_agent: str,
    proxy_url: str | None = None,
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    headers = {"User-Agent": user_agent, "Referer": post.url}
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    for index, url in enumerate(post.media_urls, start=1):
        suffix = _media_suffix(url)
        destination = target_dir / f"{post.shortcode}_{index}{suffix}"
        response = requests.get(url, headers=headers, proxies=proxies, timeout=timeout)
        response.raise_for_status()
        destination.write_bytes(response.content)
        files.append(destination)
    return files


async def _meta_content(page, selector: str) -> str:
    locator = page.locator(selector).first
    if await locator.count() == 0:
        return ""
    return await locator.get_attribute("content") or ""


async def _looks_blocked(page) -> bool:
    text = (await page.locator("body").inner_text(timeout=3000)).lower()
    blocked_markers = [
        "please wait a few minutes",
        "suspicious",
        "challenge_required",
        "checkpoint_required",
        "429",
        "temporarily blocked",
    ]
    return any(marker in text for marker in blocked_markers)


def _shortcode_from_url(url: str) -> str:
    match = re.search(r"/(?:p|reel)/([^/?#]+)/?", url)
    return match.group(1) if match else ""


def _shortcodes_from_html(html: str) -> list[str]:
    values = re.findall(r'"shortcode"\s*:\s*"([A-Za-z0-9_-]+)"', html)
    values.extend(re.findall(r'/(?:p|reel)/([A-Za-z0-9_-]+)/', html))
    return list(dict.fromkeys(values))


def _clean_caption(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"^.*? on Instagram: ", "", value).strip(' "')


def _media_suffix(url: str) -> str:
    path = urlparse(url).path.lower()
    if ".mp4" in path:
        return ".mp4"
    if ".png" in path:
        return ".png"
    return ".jpg"


def _playwright_proxy(proxy_url: str | None) -> dict[str, str] | None:
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        return {"server": proxy_url}
    result = {"server": f"{parsed.scheme or 'http'}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result
