from insta_tg_sync.apify_provider import ApifyInstagramClient, _download_url_candidates, _image_dimensions, normalize_apify_posts
from insta_tg_sync.config import AccountConfig, ApifyConfig, AppConfig, TelegramConfig


def test_normalize_apify_posts_supports_child_posts():
    posts = normalize_apify_posts(
        [
            {
                "url": "https://www.instagram.com/p/ABC123/",
                "shortCode": "ABC123",
                "caption": "caption",
                "displayUrl": "https://example.com/main.jpg",
                "childPosts": [{"displayUrl": "https://example.com/child.jpg"}],
            }
        ],
        limit=10,
    )

    assert len(posts) == 1
    assert posts[0].shortcode == "ABC123"
    assert posts[0].caption == "caption"
    assert posts[0].media_urls == ["https://example.com/child.jpg"]


def test_normalize_apify_posts_prefers_high_resolution_image_candidates():
    posts = normalize_apify_posts(
        [
            {
                "shortCode": "HIGHRES",
                "displayUrl": "https://example.com/small_320x400.jpg",
                "images": [
                    {"url": "https://example.com/mid.jpg", "width": 720, "height": 900},
                    {"url": "https://example.com/large.jpg", "width": 1440, "height": 1800},
                ],
                "thumbnailUrl": "https://example.com/thumb_150x150.jpg",
            }
        ],
        limit=10,
    )

    assert posts[0].media_urls == ["https://example.com/large.jpg"]


def test_normalize_apify_posts_uses_best_image_for_each_carousel_child():
    posts = normalize_apify_posts(
        [
            {
                "shortCode": "CAROUSEL",
                "displayUrl": "https://example.com/cover_320x400.jpg",
                "childPosts": [
                    {
                        "displayResources": [
                            {"src": "https://example.com/first-small.jpg", "config_width": 320, "config_height": 400},
                            {"src": "https://example.com/first-large.jpg", "config_width": 1440, "config_height": 1800},
                        ]
                    },
                    {
                        "image_versions2": {
                            "candidates": [
                                {"url": "https://example.com/second-small.jpg", "width": 480, "height": 600},
                                {"url": "https://example.com/second-large.jpg", "width": 1080, "height": 1350},
                            ]
                        }
                    },
                ],
            }
        ],
        limit=10,
    )

    assert posts[0].media_urls == ["https://example.com/first-large.jpg", "https://example.com/second-large.jpg"]


def test_normalize_apify_posts_prefers_parent_images_for_carousel():
    posts = normalize_apify_posts(
        [
            {
                "shortCode": "CAROUSELIMAGES",
                "images": ["https://example.com/high-1.jpg", "https://example.com/high-2.jpg"],
                "childPosts": [
                    {"displayUrl": "https://example.com/small-1.jpg"},
                    {"displayUrl": "https://example.com/small-2.jpg"},
                ],
            }
        ],
        limit=10,
    )

    assert posts[0].media_urls == ["https://example.com/high-1.jpg", "https://example.com/high-2.jpg"]


def test_normalize_apify_posts_supports_carousel_image_collections():
    posts = normalize_apify_posts(
        [
            {
                "shortCode": "COLLECTION",
                "carouselImages": [
                    {"url": "https://example.com/one.jpg", "width": 1080, "height": 1350},
                    "https://example.com/two.jpg",
                ],
            }
        ],
        limit=10,
    )

    assert posts[0].media_urls == ["https://example.com/one.jpg", "https://example.com/two.jpg"]


def test_image_dimensions_reads_png_header():
    content = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1080).to_bytes(4, "big") + (1365).to_bytes(4, "big")

    assert _image_dimensions(content) == (1080, 1365)


def test_download_url_candidates_try_high_resolution_instagram_variant_first():
    original = "https://scontent.cdninstagram.com/v/t51.82787-15/photo.jpg?stp=dst-jpg_e35_s640x640_tt6&_nc_ht=scontent.cdninstagram.com"

    candidates = _download_url_candidates(original)

    assert candidates == [
        "https://scontent.cdninstagram.com/v/t51.82787-15/photo.jpg?stp=dst-jpg_e35_p1080x1080_sh2.08_tt6&_nc_ht=scontent.cdninstagram.com",
        original,
    ]


def test_normalize_apify_posts_extracts_shortcode_from_url():
    posts = normalize_apify_posts(
        [{"url": "https://www.instagram.com/reel/XYZ789/", "videoUrl": "https://example.com/video.mp4"}],
        limit=10,
    )

    assert posts[0].shortcode == "XYZ789"
    assert posts[0].media_urls == ["https://example.com/video.mp4"]


def test_apify_client_fetches_posts_and_reels(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self.headers = {}
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_post(url, params, json, timeout):
        calls.append((json["resultsType"], json["directUrls"][0]))
        if json["resultsType"] == "posts":
            return FakeResponse([{"shortCode": "POST", "displayUrl": "https://example.com/post.jpg"}])
        if json["resultsType"] == "reels":
            return FakeResponse([
                {"shortCode": "REEL", "url": "https://www.instagram.com/reel/REEL/", "videoUrl": "https://example.com/reel.mp4"}
            ])
        return FakeResponse([])

    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post", fake_post)

    config = AppConfig(
        telegram=TelegramConfig(backend="bot", bot_token="token"),
        accounts=[],
        apify=ApifyConfig(token="token", max_results_per_run=6),
    )
    account = AccountConfig(username="account", telegram_chat_id="@chat")

    posts = ApifyInstagramClient(config).fetch_posts(account, 6)

    assert calls == [
        ("posts", "https://www.instagram.com/account/"),
        ("reels", "https://www.instagram.com/account/reels/"),
        ("details", "https://www.instagram.com/account/"),
    ]
    assert [post.shortcode for post in posts] == ["POST", "REEL"]


def test_apify_client_uses_details_latest_posts_fallback(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self.headers = {}
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_post(url, params, json, timeout):
        calls.append(json["resultsType"])
        if json["resultsType"] in {"posts", "reels"}:
            return FakeResponse([])
        return FakeResponse([
            {
                "latestPosts": [
                    {"shortCode": "LATEST", "url": "https://www.instagram.com/reel/LATEST/", "videoUrl": "https://example.com/latest.mp4"}
                ]
            }
        ])

    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post", fake_post)

    config = AppConfig(
        telegram=TelegramConfig(backend="bot", bot_token="token"),
        accounts=[],
        apify=ApifyConfig(token="token", max_results_per_run=6),
    )
    account = AccountConfig(username="account", telegram_chat_id="@chat")

    posts = ApifyInstagramClient(config).fetch_posts(account, 6)

    assert calls == ["posts", "reels", "details"]
    assert [post.shortcode for post in posts] == ["LATEST"]
    assert posts[0].media_urls == ["https://example.com/latest.mp4"]


def test_apify_client_prefers_details_media_for_duplicate_posts(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.status_code = 200
            self.headers = {}
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_post(url, params, json, timeout):
        if json["resultsType"] == "posts":
            return FakeResponse([{"shortCode": "DUP", "displayUrl": "https://example.com/low_s640x640.jpg"}])
        if json["resultsType"] == "reels":
            return FakeResponse([])
        return FakeResponse([{"latestPosts": [{"shortCode": "DUP", "displayUrl": "https://example.com/high_p1080x1080.jpg"}]}])

    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post", fake_post)

    config = AppConfig(
        telegram=TelegramConfig(backend="bot", bot_token="token"),
        accounts=[],
        apify=ApifyConfig(token="token", max_results_per_run=6),
    )
    account = AccountConfig(username="account", telegram_chat_id="@chat")

    posts = ApifyInstagramClient(config).fetch_posts(account, 6)

    assert [post.shortcode for post in posts] == ["DUP"]
    assert posts[0].media_urls == ["https://example.com/high_p1080x1080.jpg"]


def test_apify_client_retries_transient_server_error(monkeypatch):
    calls = []
    sleeps = []

    class FakeResponse:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.payload = payload or []
            self.headers = {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"Unexpected final HTTP status {self.status_code}")

        def json(self):
            return self.payload

    def fake_post(url, params, json, timeout):
        calls.append(json["resultsType"])
        if len(calls) == 1:
            return FakeResponse(502)
        return FakeResponse(200, [{"shortCode": "POST", "displayUrl": "https://example.com/post.jpg"}])

    monkeypatch.setattr("insta_tg_sync.apify_provider.requests.post", fake_post)
    monkeypatch.setattr("insta_tg_sync.apify_provider.sleep", lambda delay: sleeps.append(delay))

    config = AppConfig(
        telegram=TelegramConfig(backend="bot", bot_token="token"),
        accounts=[],
        apify=ApifyConfig(token="token", max_results_per_run=6),
    )
    account = AccountConfig(username="account", telegram_chat_id="@chat")

    posts = ApifyInstagramClient(config).fetch_posts(account, 6)

    assert calls[:2] == ["posts", "posts"]
    assert sleeps == [2.0]
    assert posts[0].shortcode == "POST"
