"""Backend tests for async post creation (draft + slot uploads + finalize).

Covers:
- POST /api/posts/draft with no media -> auto finalize -> status 'ready', telegraph_url set
- POST /api/posts/draft with media -> status 'uploading', slots returned
- POST /api/posts/{id}/media/{idx} -> fills slot, increments media_done,
  when media_done == media_total -> status flips to 'processing' then 'ready',
  telegraph_url + cover_url populated
- Cover selection: is_cover=true photo becomes cover
- GET /api/posts includes 'status' field and telegraph_url can be null
- Publish endpoint graceful 400 when no channel configured
- Draft with title only whitespace -> 400
- Bad slot index -> 400
"""
import io
import os
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://auto-channel-poster.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@mediabot.local"
ADMIN_PASSWORD = "admin123"

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\xf3\xff\xa8\xc7\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    return s


def _wait_status(client, pid, want, timeout=25):
    """Poll GET /posts/{id} until status matches (or fail)."""
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = client.get(f"{API}/posts/{pid}")
        if r.status_code == 200:
            last = r.json()
            if last.get("status") == want:
                return last
        time.sleep(0.5)
    raise AssertionError(f"post {pid} did not reach status={want} within {timeout}s, last={last}")


class TestDraftTextOnly:
    """Draft with no media should auto-finalize to 'ready' with telegraph_url."""

    def test_text_only_draft_auto_ready(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ async text only",
            "description": "Some description body",
            "publish_after": False,
            "media": [],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        assert "id" in d and d["slots"] == []
        pid = d["id"]
        try:
            # Finalize is inline for no-media, but tolerate small async delay.
            got = _wait_status(client, pid, "ready", timeout=15)
            assert got["telegraph_url"] and got["telegraph_url"].startswith("https://telegra.ph/")
            assert got["media_total"] == 0
            assert got["media_done"] == 0
            assert got["published"] is False
            assert got["cover_url"] is None
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_draft_requires_title(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "   ", "description": "x", "publish_after": False, "media": [],
        })
        assert r.status_code == 400


class TestDraftWithMedia:
    """Draft with media slots must return 'uploading' then finalize after uploads."""

    def test_draft_with_cover_upload_flow(self, client):
        # Create draft with 2 photo slots (first is cover)
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ async media",
            "description": "hello async",
            "publish_after": False,
            "media": [
                {"kind": "photo", "is_cover": True, "caption": "cover"},
                {"kind": "photo", "is_cover": False, "caption": "second"},
            ],
        })
        assert r.status_code == 200, r.text
        d = r.json()
        pid = d["id"]
        slots = d["slots"]
        assert len(slots) == 2

        try:
            # Immediately after draft: status uploading, telegraph_url null
            g = client.get(f"{API}/posts/{pid}")
            assert g.status_code == 200
            gj = g.json()
            assert gj["status"] == "uploading"
            assert gj["telegraph_url"] is None
            assert gj["media_total"] == 2
            assert gj["media_done"] == 0

            # Also present in /api/posts list with status field, null telegraph_url
            lst = client.get(f"{API}/posts").json()
            match = next((p for p in lst if p["id"] == pid), None)
            assert match is not None
            assert "status" in match
            assert match["status"] == "uploading"
            assert match["telegraph_url"] is None

            # Upload first slot (cover)
            r1 = client.post(
                f"{API}/posts/{pid}/media/{slots[0]}",
                files={"file": ("cover.png", io.BytesIO(PNG), "image/png")},
            )
            assert r1.status_code == 200, r1.text
            j1 = r1.json()
            assert j1["media_done"] == 1
            assert j1["status"] == "uploading"

            # Upload second slot -> should trigger finalize
            r2 = client.post(
                f"{API}/posts/{pid}/media/{slots[1]}",
                files={"file": ("p2.png", io.BytesIO(PNG), "image/png")},
            )
            assert r2.status_code == 200, r2.text

            # Wait for status ready (finalize is awaited but be safe)
            final = _wait_status(client, pid, "ready", timeout=25)
            assert final["telegraph_url"] and final["telegraph_url"].startswith("https://telegra.ph/")
            assert final["cover_url"] is not None
            assert final["media_done"] == 2
            assert final["published"] is False
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_upload_bad_slot_index(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ bad slot",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        assert r.status_code == 200
        pid = r.json()["id"]
        try:
            # index 99 doesn't exist
            bad = client.post(
                f"{API}/posts/{pid}/media/99",
                files={"file": ("x.png", io.BytesIO(PNG), "image/png")},
            )
            assert bad.status_code == 400
            # index 0 is the description text block (only if description non-empty) -
            # here description is empty so slot 0 IS the photo. Try slot pointing at text
            # via a new draft with description
            r2 = client.post(f"{API}/posts/draft", json={
                "title": "TEST_ text plus photo",
                "description": "hello",
                "publish_after": False,
                "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
            })
            pid2 = r2.json()["id"]
            try:
                # index 0 is text block -> should be 400
                bad2 = client.post(
                    f"{API}/posts/{pid2}/media/0",
                    files={"file": ("x.png", io.BytesIO(PNG), "image/png")},
                )
                assert bad2.status_code == 400
            finally:
                client.delete(f"{API}/posts/{pid2}")
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_upload_post_not_found(self, client):
        r = client.post(
            f"{API}/posts/does-not-exist/media/0",
            files={"file": ("x.png", io.BytesIO(PNG), "image/png")},
        )
        assert r.status_code == 404


class TestPublishAsyncGuards:
    def test_publish_draft_without_telegraph_url_400(self, client):
        # Create draft with media but do NOT upload -> telegraph_url null
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ unfinished",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        pid = r.json()["id"]
        try:
            # ensure no channel
            client.delete(f"{API}/settings/channel")
            pub = client.post(f"{API}/posts/{pid}/publish")
            # Should be 400 with a Russian detail mentioning that article is still being created
            assert pub.status_code == 400, pub.text
            detail = (pub.json().get("detail") or "").lower()
            assert ("создаётся" in detail) or ("канал" in detail) or ("channel" in detail)
        finally:
            client.delete(f"{API}/posts/{pid}")
