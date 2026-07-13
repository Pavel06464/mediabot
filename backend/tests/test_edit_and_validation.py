"""Backend tests for iteration_7:
- Upload slot validation: mismatched content-type -> 400 (Russian message)
- Photo slot size cap 25MB -> 400
- md_to_html conversion helper
- GET /posts/{id}/edit for finalized posts + 400 for still-processing drafts
- PUT /posts/{id} edits in place (same telegraph URL/path), updates title/preview/cover
- Delete post: no crash when r2_keys is empty (GridFS mode), GridFS media_ids cleaned up
"""
import io
import os
import time
import pytest
import requests

from telegraph_service import md_to_html

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://auto-channel-poster.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "admin@mediabot.local"
ADMIN_PASSWORD = "admin123"

# Minimal valid 1x1 PNG
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


def _wait_status(client, pid, want, timeout=30):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = client.get(f"{API}/posts/{pid}")
        if r.status_code == 200:
            last = r.json()
            if last.get("status") == want:
                return last
        time.sleep(0.5)
    raise AssertionError(f"post {pid} did not reach status={want}, last={last}")


# ---------- md_to_html helper ----------
class TestMdToHtml:
    def test_heading_h3(self):
        out = md_to_html("# Hello")
        assert out == "<h3>Hello</h3>"

    def test_heading_h4(self):
        out = md_to_html("## Sub")
        assert out == "<h4>Sub</h4>"

    def test_bold(self):
        out = md_to_html("**loud**")
        assert "<b>loud</b>" in out
        assert out.startswith("<p>")

    def test_italic(self):
        out = md_to_html("*soft*")
        assert "<i>soft</i>" in out

    def test_link(self):
        out = md_to_html("[here](https://example.com)")
        assert '<a href="https://example.com">here</a>' in out

    def test_quote(self):
        out = md_to_html("> wise")
        assert out == "<blockquote>wise</blockquote>"

    def test_combined(self):
        text = "# Title\n\nParagraph with **bold** and *italic* and [link](https://t.me).\n\n> quoted"
        out = md_to_html(text)
        assert "<h3>Title</h3>" in out
        assert "<b>bold</b>" in out
        assert "<i>italic</i>" in out
        assert '<a href="https://t.me">link</a>' in out
        assert "<blockquote>quoted</blockquote>" in out

    def test_html_escaped(self):
        out = md_to_html("plain <script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


# ---------- Upload validation ----------
class TestUploadValidation:
    def test_wrong_type_returns_400_russian(self, client):
        # Draft with 1 photo slot
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ validation wrong type",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        pid = r.json()["id"]
        slot = r.json()["slots"][0]
        try:
            # Attempt to upload a video into a photo slot
            bad = client.post(
                f"{API}/posts/{pid}/media/{slot}",
                files={"file": ("clip.mp4", io.BytesIO(b"\x00\x00\x00 ftypmp42"), "video/mp4")},
            )
            assert bad.status_code == 400, bad.text
            detail = bad.json().get("detail", "")
            assert "Ожидается" in detail or "изображение" in detail
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_wrong_type_video_slot_returns_400(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ validation video slot",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "video", "is_cover": False, "caption": ""}],
        })
        pid = r.json()["id"]
        slot = r.json()["slots"][0]
        try:
            bad = client.post(
                f"{API}/posts/{pid}/media/{slot}",
                files={"file": ("pic.png", io.BytesIO(PNG), "image/png")},
            )
            assert bad.status_code == 400
            detail = bad.json().get("detail", "")
            assert "видео" in detail.lower() or "Ожидается" in detail
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_photo_too_large_returns_400(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ big photo",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        pid = r.json()["id"]
        slot = r.json()["slots"][0]
        try:
            # 26 MB fake image payload (content_type=image/jpeg to pass type check)
            big = b"\xff\xd8\xff\xe0" + b"\x00" * (26 * 1024 * 1024)
            bad = client.post(
                f"{API}/posts/{pid}/media/{slot}",
                files={"file": ("big.jpg", io.BytesIO(big), "image/jpeg")},
            )
            assert bad.status_code == 400, bad.text
            detail = bad.json().get("detail", "")
            assert "25" in detail or "МБ" in detail or "больше" in detail.lower()
        finally:
            client.delete(f"{API}/posts/{pid}")


# ---------- Edit endpoints ----------
class TestEditEndpoints:
    def test_get_edit_400_for_processing_draft(self, client):
        # Draft with media but not uploaded -> no telegraph_path yet
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ edit processing",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        pid = r.json()["id"]
        try:
            g = client.get(f"{API}/posts/{pid}/edit")
            assert g.status_code == 400, g.text
            detail = (g.json().get("detail") or "").lower()
            assert "создаётся" in detail or "недоступн" in detail
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_get_edit_404_for_unknown(self, client):
        g = client.get(f"{API}/posts/does-not-exist/edit")
        assert g.status_code == 404

    def test_get_edit_returns_shape_for_ready_post(self, client):
        # Create a text-only post that auto-finalizes
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ edit ready",
            "description": "Hello **world** and [link](https://t.me)",
            "publish_after": False,
            "media": [],
        })
        pid = r.json()["id"]
        try:
            ready = _wait_status(client, pid, "ready", timeout=20)
            assert ready["telegraph_url"].startswith("https://telegra.ph/")
            g = client.get(f"{API}/posts/{pid}/edit")
            assert g.status_code == 200, g.text
            data = g.json()
            assert data["id"] == pid
            assert data["title"] == "TEST_ edit ready"
            assert "**world**" in data["description"] or "world" in data["description"]
            assert data["telegraph_url"] == ready["telegraph_url"]
            assert data["media"] == []
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_put_edit_in_place_same_url(self, client):
        # Text-only post
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ edit put",
            "description": "original body",
            "publish_after": False,
            "media": [],
        })
        pid = r.json()["id"]
        try:
            ready = _wait_status(client, pid, "ready", timeout=20)
            orig_url = ready["telegraph_url"]
            orig_path = ready.get("telegraph_path")

            # PUT with new title/description
            put = client.put(f"{API}/posts/{pid}", json={
                "title": "TEST_ edit put UPDATED",
                "description": "# New heading\n\nUpdated body",
                "media": [],
            })
            assert put.status_code == 200, put.text
            pj = put.json()
            assert pj["status"] == "updated"
            # Should be the SAME telegraph URL (edit in place)
            assert pj["telegraph_url"] == orig_url

            # GET reflects new title & path unchanged
            g = client.get(f"{API}/posts/{pid}")
            assert g.status_code == 200
            gj = g.json()
            assert gj["title"] == "TEST_ edit put UPDATED"
            assert gj["telegraph_url"] == orig_url
            if orig_path:
                assert gj.get("telegraph_path") == orig_path
            assert "New heading" in gj["preview"] or "Updated" in gj["preview"]

            # GET /edit reflects new description
            g2 = client.get(f"{API}/posts/{pid}/edit")
            assert g2.status_code == 200
            assert g2.json()["title"] == "TEST_ edit put UPDATED"
            assert "New heading" in g2.json()["description"]
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_put_requires_title(self, client):
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ put no title",
            "description": "x",
            "publish_after": False,
            "media": [],
        })
        pid = r.json()["id"]
        try:
            _wait_status(client, pid, "ready", timeout=20)
            put = client.put(f"{API}/posts/{pid}", json={
                "title": "   ", "description": "y", "media": []
            })
            assert put.status_code == 400
        finally:
            client.delete(f"{API}/posts/{pid}")

    def test_put_404_for_unknown(self, client):
        put = client.put(f"{API}/posts/does-not-exist", json={
            "title": "x", "description": "y", "media": []
        })
        assert put.status_code == 404


# ---------- Delete safety (no R2 in preview) ----------
class TestDeleteCleanup:
    def test_delete_gridfs_post_no_crash(self, client):
        # Create a real post with media via draft+upload
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ delete gridfs",
            "description": "",
            "publish_after": False,
            "media": [{"kind": "photo", "is_cover": True, "caption": ""}],
        })
        pid = r.json()["id"]
        slot = r.json()["slots"][0]
        up = client.post(
            f"{API}/posts/{pid}/media/{slot}",
            files={"file": ("c.png", io.BytesIO(PNG), "image/png")},
        )
        assert up.status_code == 200
        _wait_status(client, pid, "ready", timeout=25)
        # Delete should return 200 and no server crash even though r2_keys is []
        d = client.delete(f"{API}/posts/{pid}")
        assert d.status_code == 200
        assert d.json().get("status") == "deleted"
        # Confirm gone
        g = client.get(f"{API}/posts/{pid}")
        assert g.status_code == 404


# ---------- Markdown finalization end-to-end ----------
class TestMarkdownFinalization:
    def test_draft_with_markdown_finalizes(self, client):
        text = "# Heading\n\n**bold** and *italic* and [link](https://t.me/x)\n\n> quote"
        r = client.post(f"{API}/posts/draft", json={
            "title": "TEST_ markdown finalize",
            "description": text,
            "publish_after": False,
            "media": [],
        })
        pid = r.json()["id"]
        try:
            ready = _wait_status(client, pid, "ready", timeout=20)
            assert ready["telegraph_url"].startswith("https://telegra.ph/")
        finally:
            client.delete(f"{API}/posts/{pid}")
