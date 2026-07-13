"""Backend API tests for Media Post Bot dashboard (JWT auth).

Covers: /api/auth/login+me, auth gating, stats, posts list, upload+media (public),
create-with-cover, telegraph page, publish (400 no channel), settings (400 no bot token), delete.

NOTE: pytest.ini pins xdist to `-n 2 --dist loadscope` → tests inside ONE class run on the
same worker with shared class state. State-dependent chain (upload → create → publish → delete)
lives inside `TestFullFlow`.
"""
import os
import io
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://auto-channel-poster.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@mediabot.local"
ADMIN_PASSWORD = "admin123"

# 1x1 PNG
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\xf3\xff\xa8\xc7\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(scope="module")
def anon():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(anon):
    r = anon.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def client(token):
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "Authorization": f"Bearer {token}"})
    return s


# ---------- Auth ----------
class TestAuth:
    def test_login_success(self, anon):
        r = anon.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("token"), str) and len(data["token"]) > 20
        assert data["user"]["email"] == ADMIN_EMAIL
        assert "id" in data["user"]

    def test_login_wrong_password(self, anon):
        r = anon.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "wrongpass"})
        assert r.status_code == 401
        assert "detail" in r.json()

    def test_login_unknown_email(self, anon):
        r = anon.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401

    def test_me_requires_token(self, anon):
        assert anon.get(f"{API}/auth/me").status_code == 401

    def test_me_with_token(self, client):
        r = client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL

    def test_me_bad_token(self, anon):
        r = anon.get(f"{API}/auth/me", headers={"Authorization": "Bearer bad.token.here"})
        assert r.status_code == 401


# ---------- Auth gating ----------
class TestProtected:
    def test_stats_401(self, anon):
        assert anon.get(f"{API}/stats").status_code == 401

    def test_posts_401(self, anon):
        assert anon.get(f"{API}/posts").status_code == 401

    def test_settings_401(self, anon):
        assert anon.get(f"{API}/settings").status_code == 401

    def test_upload_401(self, anon):
        r = anon.post(f"{API}/upload", files={"file": ("t.txt", b"hi", "text/plain")})
        assert r.status_code == 401


# ---------- Stats ----------
class TestStats:
    def test_stats_schema(self, client):
        r = client.get(f"{API}/stats")
        assert r.status_code == 200
        d = r.json()
        for k in ("total_posts", "total_published", "total_drafts", "total_media", "channels_configured"):
            assert k in d and isinstance(d[k], int)
        assert d["total_drafts"] == d["total_posts"] - d["total_published"]


# ---------- Posts list ----------
class TestPostsList:
    def test_posts_list(self, client):
        r = client.get(f"{API}/posts")
        assert r.status_code == 200
        posts = r.json()
        assert isinstance(posts, list)
        for p in posts:
            assert "_id" not in p
            assert "id" in p and "title" in p and "telegraph_url" in p
        if len(posts) > 1:
            dates = [p["created_at"] for p in posts]
            assert dates == sorted(dates, reverse=True)

    def test_get_post_not_found(self, client):
        r = client.get(f"{API}/posts/nonexistent-uuid-xxx")
        assert r.status_code == 404


# ---------- Media errors (no shared state) ----------
class TestMediaErrors:
    def test_media_invalid(self, anon):
        assert anon.get(f"{API}/media/not-a-valid-oid").status_code == 404

    def test_media_not_found(self, anon):
        assert anon.get(f"{API}/media/000000000000000000000000").status_code == 404


# ---------- Full flow (single class, loadscope keeps them on one worker) ----------
class TestFullFlow:
    state = {}

    def test_01_upload_photo(self, client):
        r = client.post(f"{API}/upload", files={"file": ("test.png", io.BytesIO(PNG), "image/png")})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["type"] == "photo"
        assert "url" in d and "media_id" in d
        assert "/api/media/" in d["url"]
        TestFullFlow.state["media_id"] = d["media_id"]
        TestFullFlow.state["media_url"] = d["url"]

    def test_02_media_public(self, anon):
        mid = TestFullFlow.state["media_id"]
        r = anon.get(f"{API}/media/{mid}")
        assert r.status_code == 200
        assert len(r.content) > 0
        assert r.headers.get("content-type", "").startswith("image/")

    def test_03_create_requires_title(self, client):
        r = client.post(f"{API}/posts", json={"title": "  ", "blocks": [{"type": "text", "value": "x"}]})
        assert r.status_code == 400

    def test_04_create_requires_blocks(self, client):
        r = client.post(f"{API}/posts", json={"title": "T", "blocks": []})
        assert r.status_code == 400

    def test_05_create_with_cover(self, client):
        media_id = TestFullFlow.state["media_id"]
        media_url = TestFullFlow.state["media_url"]
        payload = {
            "title": "TEST_ pytest article",
            "blocks": [
                {"type": "text", "value": "Hello world from pytest"},
                {
                    "type": "photo",
                    "url": media_url,
                    "media_id": media_id,
                    "caption": "cover photo",
                    "is_cover": True,
                },
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["title"] == "TEST_ pytest article"
        assert p["media_count"] == 1
        assert p["block_count"] == 2
        assert p["published"] is False
        assert p["telegraph_url"].startswith("https://telegra.ph/")
        assert media_id in p["media_ids"]
        assert "_id" not in p
        assert p["preview"].startswith("Hello world")
        TestFullFlow.state["post_id"] = p["id"]
        TestFullFlow.state["telegraph_url"] = p["telegraph_url"]

    def test_06_get_created_post(self, client):
        pid = TestFullFlow.state["post_id"]
        r = client.get(f"{API}/posts/{pid}")
        assert r.status_code == 200
        assert r.json()["id"] == pid

    def test_07_telegraph_page_has_image(self, anon):
        url = TestFullFlow.state["telegraph_url"]
        r = anon.get(url, timeout=15)
        assert r.status_code == 200
        assert "TEST_ pytest article" in r.text
        # Telegraph either rehosts to telegra.ph/file OR keeps the original media URL.
        assert ("telegra.ph/file/" in r.text) or (TestFullFlow.state["media_id"] in r.text) or ("<img" in r.text)

    def test_08_publish_no_channel_returns_400(self, client):
        client.delete(f"{API}/settings/channel")
        pid = TestFullFlow.state["post_id"]
        r = client.post(f"{API}/posts/{pid}/publish")
        assert r.status_code == 400
        detail = r.json().get("detail", "").lower()
        assert "канал" in detail or "channel" in detail

    def test_09_publish_post_not_found(self, client):
        r = client.post(f"{API}/posts/does-not-exist/publish")
        assert r.status_code == 404

    def test_10_delete_not_found(self, client):
        r = client.delete(f"{API}/posts/nonexistent-uuid-yyy")
        assert r.status_code == 404

    def test_11_delete_created_post(self, client):
        pid = TestFullFlow.state["post_id"]
        r = client.delete(f"{API}/posts/{pid}")
        assert r.status_code == 200
        assert client.get(f"{API}/posts/{pid}").status_code == 404


# ---------- Channel settings (no bot token in preview → 400) ----------
class TestChannelSettings:
    def test_get_settings_empty(self, client):
        client.delete(f"{API}/settings/channel")
        r = client.get(f"{API}/settings")
        assert r.status_code == 200
        assert r.json().get("channel_id") is None

    def test_set_channel_without_bot_token_returns_400(self, client):
        r = client.post(f"{API}/settings/channel", json={"identifier": "@somechannel"})
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "TELEGRAM_BOT_TOKEN" in detail or "токен" in detail.lower()
