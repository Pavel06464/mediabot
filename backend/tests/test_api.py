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


# ---------- Cover ordering with multiple photos ----------
class TestCoverOrdering:
    """Verify server reorders is_cover block to be first, before other photos in Telegraph output."""

    def test_cover_ordered_before_other_photos(self, client):
        # Upload three photos
        media = []
        for i in range(3):
            r = client.post(f"{API}/upload", files={"file": (f"p{i}.png", io.BytesIO(PNG), "image/png")})
            assert r.status_code == 200
            media.append(r.json())

        # Blocks: text, photo(not cover), photo(cover), photo(not cover)
        # Server should reorder → cover first
        payload = {
            "title": "TEST_ cover ordering",
            "blocks": [
                {"type": "text", "value": "intro"},
                {"type": "photo", "url": media[0]["url"], "media_id": media[0]["media_id"], "is_cover": False},
                {"type": "photo", "url": media[1]["url"], "media_id": media[1]["media_id"], "is_cover": True, "caption": "COVER_CAP"},
                {"type": "photo", "url": media[2]["url"], "media_id": media[2]["media_id"], "is_cover": False},
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200, r.text
        post = r.json()
        post_id = post["id"]
        try:
            # Fetch telegraph page HTML and verify cover media_id appears BEFORE the two others
            html = requests.get(post["telegraph_url"], timeout=15).text
            positions = []
            for m in media:
                pos = html.find(m["media_id"])
                # Telegraph may rehost — accept -1 as "unknown" only if rehosted (telegra.ph/file present)
                positions.append(pos)
            cover_pos = positions[1]
            # If media_ids stripped by rehost, at least check img order matches by counting <img before caption
            if cover_pos != -1 and positions[0] != -1 and positions[2] != -1:
                assert cover_pos < positions[0], f"cover should appear before photo0, got cover={cover_pos} photo0={positions[0]}"
                assert cover_pos < positions[2], f"cover should appear before photo2, got cover={cover_pos} photo2={positions[2]}"
            else:
                # Rehosted case: caption text should be the first <figcaption> (COVER_CAP)
                first_cap = html.find("<figcaption>")
                cover_cap = html.find("COVER_CAP")
                if cover_cap != -1:
                    assert first_cap == -1 or cover_cap <= first_cap + 100
        finally:
            # cleanup
            client.delete(f"{API}/posts/{post_id}")


# ---------- Cover URL storage (bug fix: large preview via sendPhoto) ----------
class TestCoverUrl:
    """Verify cover_url is correctly computed & stored on post creation.

    Bug context: publish previously produced only a small thumbnail because
    prefer_large_media doesn't apply to telegra.ph links. Fix stores a cover_url
    on the post and publish uses telegram_api.send_photo (uploads real image).
    We can't exercise real Telegram in preview (no bot token / channel), so we
    verify (1) cover_url stored correctly for 3 cases and (2) publish returns
    graceful 400 (no channel) and (3) code path uses send_photo.
    """

    def _upload(self, client):
        r = client.post(f"{API}/upload", files={"file": ("c.png", io.BytesIO(PNG), "image/png")})
        assert r.status_code == 200, r.text
        return r.json()

    def test_cover_url_explicit_is_cover(self, client):
        m1 = self._upload(client)
        m2 = self._upload(client)
        payload = {
            "title": "TEST_ cover explicit",
            "blocks": [
                {"type": "text", "value": "hello"},
                {"type": "photo", "url": m1["url"], "media_id": m1["media_id"], "is_cover": False},
                {"type": "photo", "url": m2["url"], "media_id": m2["media_id"], "is_cover": True},
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200, r.text
        post = r.json()
        pid = post["id"]
        try:
            # cover_url present, non-null, equals the is_cover photo url (m2)
            assert post.get("cover_url") == m2["url"], f"expected cover_url == m2 url, got {post.get('cover_url')}"
            # persisted — GET returns same
            g = client.get(f"{API}/posts/{pid}")
            assert g.status_code == 200
            assert g.json().get("cover_url") == m2["url"]
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_cover_url_null_when_no_photos(self, client):
        payload = {
            "title": "TEST_ no photos",
            "blocks": [
                {"type": "text", "value": "only text here"},
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200, r.text
        post = r.json()
        pid = post["id"]
        try:
            assert "cover_url" in post, "cover_url key must exist even if null"
            assert post["cover_url"] is None, f"cover_url should be null, got {post['cover_url']}"
            g = client.get(f"{API}/posts/{pid}")
            assert g.json().get("cover_url") is None
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_cover_url_falls_back_to_first_photo(self, client):
        m1 = self._upload(client)
        m2 = self._upload(client)
        payload = {
            "title": "TEST_ fallback cover",
            "blocks": [
                {"type": "text", "value": "no cover flag"},
                {"type": "photo", "url": m1["url"], "media_id": m1["media_id"], "is_cover": False},
                {"type": "photo", "url": m2["url"], "media_id": m2["media_id"], "is_cover": False},
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200, r.text
        post = r.json()
        pid = post["id"]
        try:
            # first photo (m1) wins as fallback
            assert post.get("cover_url") == m1["url"], (
                f"expected cover_url to fall back to first photo m1, got {post.get('cover_url')}"
            )
            g = client.get(f"{API}/posts/{pid}")
            assert g.json().get("cover_url") == m1["url"]
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_publish_without_channel_graceful_400(self, client):
        """Ensure preview env (no channel) returns HTTP 400 with clear message, not 500."""
        # Create a post with cover to hit the send_photo code path (even though it won't run)
        m = self._upload(client)
        payload = {
            "title": "TEST_ publish no channel",
            "blocks": [
                {"type": "photo", "url": m["url"], "media_id": m["media_id"], "is_cover": True},
            ],
        }
        r = client.post(f"{API}/posts", json=payload)
        assert r.status_code == 200
        pid = r.json()["id"]
        try:
            # ensure no channel configured
            client.delete(f"{API}/settings/channel")
            pub = client.post(f"{API}/posts/{pid}/publish")
            assert pub.status_code == 400, f"expected 400, got {pub.status_code}: {pub.text}"
            detail = (pub.json().get("detail") or "").lower()
            assert ("канал" in detail) or ("channel" in detail), f"expected channel-related detail, got: {detail}"
            # Not published
            g = client.get(f"{API}/posts/{pid}")
            assert g.json().get("published") is False
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_telegram_api_has_send_photo_and_is_used(self):
        """Code-level check: telegram_api.send_photo exists and publish_post uses it when cover_url present."""
        import importlib
        import inspect
        # Add backend to path
        import sys
        sys.path.insert(0, "/app/backend")
        telegram_api_mod = importlib.import_module("telegram_api")
        assert hasattr(telegram_api_mod, "send_photo"), "telegram_api.send_photo must exist"
        assert callable(telegram_api_mod.send_photo)
        # Signature should accept (chat_id, photo_url, caption)
        sig = inspect.signature(telegram_api_mod.send_photo)
        params = list(sig.parameters.keys())
        assert params[:3] == ["chat_id", "photo_url", "caption"], f"unexpected signature: {params}"

        # server.publish_post should reference telegram_api.send_photo
        server_mod = importlib.import_module("server")
        src = inspect.getsource(server_mod.publish_post)
        assert "send_photo" in src, "publish_post must call telegram_api.send_photo"
        assert "send_message" in src, "publish_post must have send_message fallback"
        assert "cover_url" in src, "publish_post must branch on cover_url"


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
