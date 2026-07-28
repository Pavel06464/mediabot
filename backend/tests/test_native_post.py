"""iteration_11 backend tests: NATIVE POST TYPE feature.

Covers:
- create draft with post_type='native' + media, upload slots -> finalize to status ready,
  telegraph_url=None, cover_url set (first photo), photo_count/video_count correct.
- publish endpoint on native post without a channel configured returns 400 (Russian message),
  NOT 500.
- GET /posts/{id}/edit works for native post (no "статья создаётся" error), returns
  post_type='native', media list, description, hashtags.
- PUT /posts/{id} on native updates title/description/hashtags/captions, can REMOVE media
  (keep-list), recomputes photo_count/video_count, deletes removed GridFS file, does NOT
  create/touch Telegraph.
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
MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 128


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}", "Accept": "application/json"})
    return s


def _wait_status(client, pid, want, timeout=60):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = client.get(f"{API}/posts/{pid}")
        if r.status_code == 200:
            last = r.json()
            if last.get("status") == want:
                return last
            if last.get("status") == "error":
                raise AssertionError(f"post {pid} error: {last}")
        time.sleep(0.6)
    raise AssertionError(f"post {pid} did not reach {want}, last={last}")


def _create_native(client, title, photos=2, videos=1):
    media = [{"kind": "photo", "is_cover": True, "caption": "cov"}]
    for i in range(photos - 1):
        media.append({"kind": "photo", "is_cover": False, "caption": f"p{i}"})
    for i in range(videos):
        media.append({"kind": "video", "is_cover": False, "caption": f"v{i}"})
    r = client.post(f"{API}/posts/draft", json={
        "title": title,
        "description": "тело нативного поста",
        "publish_after": False,
        "hashtags": ["#test", "#native"],
        "post_type": "native",
        "media": media,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    pid, slots = data["id"], data["slots"]
    # slots order matches media order
    for i, s in enumerate(slots):
        kind = media[i]["kind"]
        payload = PNG if kind == "photo" else MP4
        ctype = "image/png" if kind == "photo" else "video/mp4"
        fname = "p.png" if kind == "photo" else "v.mp4"
        up = client.post(
            f"{API}/posts/{pid}/media/{s}",
            files={"file": (fname, io.BytesIO(payload), ctype)},
        )
        assert up.status_code == 200, up.text
    ready = _wait_status(client, pid, "ready", timeout=90)
    return pid, ready


class TestNativeFinalize:
    def test_native_finalize_no_telegraph(self, client):
        pid, ready = _create_native(client, "TEST_ native finalize", photos=2, videos=1)
        try:
            assert ready["post_type"] == "native"
            assert ready["status"] == "ready"
            assert ready.get("telegraph_url") in (None, "", False), f"telegraph_url must be null, got {ready.get('telegraph_url')}"
            assert ready.get("photos_url") in (None, "", False)
            assert ready.get("videos_url") in (None, "", False)
            assert ready.get("cover_url"), "cover_url must be set (first photo)"
            assert ready["photo_count"] == 2, ready
            assert ready["video_count"] == 1, ready
            assert ready["media_count"] == 3, ready
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")


class TestNativePublishGraceful:
    def test_publish_native_no_channel_returns_400(self, client):
        # ensure no channel configured
        channel = client.get(f"{API}/channel")
        if channel.status_code == 200 and channel.json():
            # delete channel to guarantee graceful path
            client.delete(f"{API}/channel")
        pid, _ = _create_native(client, "TEST_ native publish no-channel", photos=1, videos=0)
        try:
            r = client.post(f"{API}/posts/{pid}/publish")
            assert r.status_code == 400, f"expected 400, got {r.status_code} body={r.text}"
            body = r.json()
            msg = (body.get("detail") or "").lower()
            assert "канал" in msg, f"Russian channel message expected, got: {body}"
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")


class TestNativeEdit:
    def test_get_edit_returns_native_no_error(self, client):
        pid, _ = _create_native(client, "TEST_ native edit get", photos=2, videos=1)
        try:
            r = client.get(f"{API}/posts/{pid}/edit")
            assert r.status_code == 200, r.text
            ed = r.json()
            assert ed["post_type"] == "native"
            assert ed["title"].startswith("TEST_ native edit")
            assert ed["description"] == "тело нативного поста"
            assert "#test" in ed["hashtags"] and "#native" in ed["hashtags"]
            assert len(ed["media"]) == 3
            # No telegraph url on native
            assert ed.get("telegraph_url") in (None, "", False)
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")

    def test_put_native_removes_media_and_updates_counts(self, client):
        pid, _ = _create_native(client, "TEST_ native edit put", photos=2, videos=1)
        try:
            ed = client.get(f"{API}/posts/{pid}/edit").json()
            media = ed["media"]
            photos = [m for m in media if m["kind"] == "photo"]
            videos = [m for m in media if m["kind"] == "video"]
            assert len(photos) == 2 and len(videos) == 1

            # Remove the video; capture URL to verify GridFS deletion
            removed_url = videos[0]["url"] or ""
            removed_mid = removed_url.rstrip("/").split("/")[-1] if "/media/" in removed_url else None
            if removed_mid:
                pre = requests.get(f"{API}/media/{removed_mid}", timeout=15)
                assert pre.status_code == 200

            keep = photos  # drop the video
            put = client.put(f"{API}/posts/{pid}", json={
                "title": "TEST_ native edit put UPDATED",
                "description": "обновлённое описание",
                "hashtags": ["#updated"],
                "media": [{"idx": m["idx"], "caption": "new-cap", "is_cover": bool(m.get("is_cover"))} for m in keep],
            })
            assert put.status_code == 200, put.text

            got = client.get(f"{API}/posts/{pid}").json()
            assert got["title"] == "TEST_ native edit put UPDATED"
            assert got["photo_count"] == 2
            assert got["video_count"] == 0
            assert got["media_count"] == 2
            assert got.get("telegraph_url") in (None, "", False), "native edit must NOT create telegraph"
            assert got.get("post_type") == "native"

            # description/hashtags via edit endpoint
            ed2 = client.get(f"{API}/posts/{pid}/edit").json()
            assert ed2["description"] == "обновлённое описание"
            assert ed2["hashtags"] == ["#updated"]
            # captions updated
            for m in ed2["media"]:
                assert m["caption"] == "new-cap"

            # GridFS file gone
            if removed_mid:
                for _ in range(5):
                    after = requests.get(f"{API}/media/{removed_mid}", timeout=15)
                    if after.status_code == 404:
                        break
                    time.sleep(0.5)
                assert after.status_code == 404
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")
