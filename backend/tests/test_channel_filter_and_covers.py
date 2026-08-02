"""Backend tests for NEW FEATURES: channel-scoped stats/posts + cover_urls (up to 3)."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fallback: read from frontend/.env
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL"):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")

ADMIN_EMAIL = "admin@mediabot.local"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    s.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return s


# ---------- Channel-scoped stats ----------
class TestStatsScoped:
    def test_stats_alpha(self, client):
        r = client.get(f"{BASE_URL}/api/stats?channel_ref=chan-alpha")
        assert r.status_code == 200
        d = r.json()
        assert d["total_posts"] == 3
        assert d["total_published"] == 1
        assert d["total_drafts"] == 2
        assert d["in_queue"] == 1
        assert "channels_configured" in d

    def test_stats_beta(self, client):
        r = client.get(f"{BASE_URL}/api/stats?channel_ref=chan-beta")
        assert r.status_code == 200
        d = r.json()
        assert d["total_posts"] == 1
        assert d["total_published"] == 0
        assert d["total_drafts"] == 1
        assert d["in_queue"] == 0

    def test_stats_no_channel(self, client):
        # global — should be >= 4
        r = client.get(f"{BASE_URL}/api/stats")
        assert r.status_code == 200
        assert r.json()["total_posts"] >= 4


# ---------- Channel-scoped posts ----------
class TestPostsScoped:
    def test_posts_alpha(self, client):
        r = client.get(f"{BASE_URL}/api/posts?channel_ref=chan-alpha&page_size=50")
        assert r.status_code == 200
        d = r.json()
        ids = {p["id"] for p in d["items"]}
        assert {"seed-a1", "seed-a2", "seed-a3"} <= ids
        assert "seed-b1" not in ids
        # all items must have channel_ref == chan-alpha
        for p in d["items"]:
            assert p.get("channel_ref") == "chan-alpha"

    def test_posts_beta(self, client):
        r = client.get(f"{BASE_URL}/api/posts?channel_ref=chan-beta&page_size=50")
        assert r.status_code == 200
        d = r.json()
        ids = {p["id"] for p in d["items"]}
        assert ids == {"seed-b1"}
        assert d["total"] == 1


# ---------- Cover URLs storage (up to 3) via edit_post ----------
class TestCoverUrls:
    @pytest.fixture
    def native_post_id(self, client):
        # Create native draft with 3 photos (no upload — set url manually via edit_post new_media)
        r = client.post(f"{BASE_URL}/api/posts/draft", json={
            "title": "TEST_cover_urls", "description": "d", "publish_after": False,
            "post_type": "native", "hashtags": [], "media": [], "channel_ref": "chan-alpha",
        })
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        yield pid
        client.delete(f"{BASE_URL}/api/posts/{pid}?delete_media=false")

    def test_edit_stores_up_to_3_covers(self, client, native_post_id):
        # Send edit with 3 new photos, all is_cover=True
        payload = {
            "title": "TEST_cover_urls",
            "description": "d",
            "hashtags": [],
            "media": [],
            "new_media": [
                {"kind": "photo", "url": "https://example.com/a.jpg", "is_cover": True, "caption": ""},
                {"kind": "photo", "url": "https://example.com/b.jpg", "is_cover": True, "caption": ""},
                {"kind": "photo", "url": "https://example.com/c.jpg", "is_cover": True, "caption": ""},
                {"kind": "photo", "url": "https://example.com/d.jpg", "is_cover": True, "caption": ""},
            ],
            "channel_ref": "chan-alpha",
        }
        r = client.put(f"{BASE_URL}/api/posts/{native_post_id}", json=payload)
        assert r.status_code == 200, r.text

        # Verify persistence: cover_urls capped at 3
        r = client.get(f"{BASE_URL}/api/posts/{native_post_id}")
        assert r.status_code == 200
        d = r.json()
        assert "cover_urls" in d
        assert isinstance(d["cover_urls"], list)
        assert len(d["cover_urls"]) == 3
        assert d["cover_urls"] == [
            "https://example.com/a.jpg",
            "https://example.com/b.jpg",
            "https://example.com/c.jpg",
        ]


# ---------- Cover album publish path (send_photo_album called for 2-3 covers) ----------
class TestPublishAlbumPath:
    def test_do_publish_uses_album_for_multiple_covers(self, monkeypatch=None):
        """Unit-ish: call _do_publish directly with mocked telegram_api."""
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        import telegram_api
        import server

        called = {"album": None, "photo": None, "message": None}

        async def fake_album(chat_id, urls, caption):
            called["album"] = (chat_id, list(urls), caption)
            return [{"message_id": 101}, {"message_id": 102}]

        async def fake_photo(*a, **k):
            called["photo"] = (a, k)
            return {"message_id": 999}

        async def fake_msg(*a, **k):
            called["message"] = (a, k)
            return {"message_id": 998}

        telegram_api.send_photo_album = fake_album
        telegram_api.send_photo = fake_photo
        telegram_api.send_message = fake_msg

        post = {
            "title": "T", "hashtags": [], "blocks": [],
            "cover_urls": ["u1", "u2", "u3"], "cover_url": "u1",
            "telegraph_url": "https://telegra.ph/x",
        }
        channel = {"channel_id": -100, "channel_title": "C", "channel_username": None}
        result = asyncio.get_event_loop().run_until_complete(server._do_publish(post, channel))
        assert called["album"] is not None, "send_photo_album must be called for 2+ covers"
        assert called["album"][1] == ["u1", "u2", "u3"]
        assert called["photo"] is None
        assert result == [101, 102]

    def test_do_publish_single_cover_uses_send_photo(self):
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        import telegram_api
        import server

        called = {"album": None, "photo": None}

        async def fake_album(*a, **k):
            called["album"] = (a, k); return []

        async def fake_photo(chat_id, url, caption):
            called["photo"] = (chat_id, url, caption)
            return {"message_id": 55}

        telegram_api.send_photo_album = fake_album
        telegram_api.send_photo = fake_photo

        post = {"title": "T", "hashtags": [], "blocks": [],
                "cover_urls": ["only"], "cover_url": "only", "telegraph_url": "https://x"}
        channel = {"channel_id": -1, "channel_title": "C", "channel_username": None}
        result = asyncio.get_event_loop().run_until_complete(server._do_publish(post, channel))
        assert called["album"] is None
        assert called["photo"] == (-1, "only", called["photo"][2])
        assert result == [55]
