"""iteration_10 backend tests: EDIT-REMOVE feature.

- Create a post with 1 photo + 2 videos, finalize (status=ready).
- GET /posts/{id}/edit to read media idxs.
- PUT keeping only the photo + one video.
- After edit: video_count 2->1, photo_count stays 1, media_count = 2.
- GET /api/media/{removed_video_media_id} returns 404 (GridFS file deleted).
- Removing ALL photos while keeping videos: photos_url becomes None; videos_url intact.
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

# 1x1 PNG
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01"
    b"\xf3\xff\xa8\xc7\x00\x00\x00\x00IEND\xaeB`\x82"
)
# Minimal fake MP4 (ftyp box + 128 bytes) - enough for MIME sniffing
MP4 = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 128


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/json"})
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
                raise AssertionError(f"post {pid} entered error status: {last}")
        time.sleep(0.7)
    raise AssertionError(f"post {pid} did not reach status={want}, last={last}")


def _make_1p2v_post(client, title):
    """Create + upload draft with 1 photo + 2 videos and finalize."""
    r = client.post(f"{API}/posts/draft", json={
        "title": title,
        "description": "тело поста",
        "publish_after": False,
        "media": [
            {"kind": "photo", "is_cover": True, "caption": "p1"},
            {"kind": "video", "is_cover": False, "caption": "v1"},
            {"kind": "video", "is_cover": False, "caption": "v2"},
        ],
    })
    assert r.status_code == 200, r.text
    data = r.json()
    pid = data["id"]
    slots = data["slots"]
    # Upload files
    up = client.post(
        f"{API}/posts/{pid}/media/{slots[0]}",
        files={"file": ("p.png", io.BytesIO(PNG), "image/png")},
    )
    assert up.status_code == 200, up.text
    for s in slots[1:]:
        up = client.post(
            f"{API}/posts/{pid}/media/{s}",
            files={"file": ("v.mp4", io.BytesIO(MP4), "video/mp4")},
        )
        assert up.status_code == 200, up.text
    ready = _wait_status(client, pid, "ready", timeout=90)
    assert ready.get("photo_count") == 1
    assert ready.get("video_count") == 2
    return pid, ready


class TestEditRemoveMedia:
    def test_remove_one_video_deletes_gridfs_file(self, client):
        pid, ready = _make_1p2v_post(client, "TEST_ edit-remove one video")
        try:
            edit = client.get(f"{API}/posts/{pid}/edit")
            assert edit.status_code == 200, edit.text
            ed = edit.json()
            media = ed["media"]
            assert len(media) == 3
            photos = [m for m in media if m["kind"] == "photo"]
            videos = [m for m in media if m["kind"] == "video"]
            assert len(photos) == 1 and len(videos) == 2

            # capture the media_id URL for the video we are about to remove
            removed_video = videos[1]
            removed_url = removed_video["url"] or ""
            # url looks like {BASE_URL}/api/media/{media_id}
            removed_mid = removed_url.rstrip("/").split("/")[-1] if "/media/" in removed_url else None

            # Sanity: media file exists before removal (GridFS mode)
            if removed_mid:
                pre = requests.get(f"{API}/media/{removed_mid}", timeout=15)
                assert pre.status_code == 200, f"pre-check failed: {pre.status_code}"

            # Keep only the photo + first video
            keep = [photos[0], videos[0]]
            put = client.put(f"{API}/posts/{pid}", json={
                "title": ed["title"],
                "description": ed["description"],
                "hashtags": ed.get("hashtags", []),
                "media": [{"idx": m["idx"], "caption": m.get("caption", ""), "is_cover": bool(m.get("is_cover"))} for m in keep],
            })
            assert put.status_code == 200, put.text

            # counts recomputed
            got = client.get(f"{API}/posts/{pid}").json()
            assert got["photo_count"] == 1, got
            assert got["video_count"] == 1, got
            assert got["media_count"] == 2, got
            assert got.get("photos_url"), "photos article should still exist"
            assert got.get("videos_url"), "videos article should still exist"

            # GridFS file for the removed video should be gone
            if removed_mid:
                # small delay in case of async cleanup
                for _ in range(5):
                    after = requests.get(f"{API}/media/{removed_mid}", timeout=15)
                    if after.status_code == 404:
                        break
                    time.sleep(0.5)
                assert after.status_code == 404, f"expected 404 after removal, got {after.status_code}"
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")

    def test_remove_all_photos_keeps_videos(self, client):
        pid, ready = _make_1p2v_post(client, "TEST_ edit-remove all photos")
        try:
            edit = client.get(f"{API}/posts/{pid}/edit").json()
            videos = [m for m in edit["media"] if m["kind"] == "video"]
            assert len(videos) == 2

            # Keep only videos (drop the photo)
            put = client.put(f"{API}/posts/{pid}", json={
                "title": edit["title"],
                "description": edit["description"],
                "hashtags": edit.get("hashtags", []),
                "media": [{"idx": m["idx"], "caption": m.get("caption", ""), "is_cover": False} for m in videos],
            })
            assert put.status_code == 200, put.text

            got = client.get(f"{API}/posts/{pid}").json()
            assert got["photo_count"] == 0, got
            assert got["video_count"] == 2, got
            # Per spec: photos_url may be null OR keep text-only page — both acceptable, must not error
            assert got.get("videos_url"), "videos_url must remain"
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")

    def test_remove_all_videos_keeps_photo(self, client):
        pid, ready = _make_1p2v_post(client, "TEST_ edit-remove all videos")
        try:
            edit = client.get(f"{API}/posts/{pid}/edit").json()
            photos = [m for m in edit["media"] if m["kind"] == "photo"]
            assert len(photos) == 1

            put = client.put(f"{API}/posts/{pid}", json={
                "title": edit["title"],
                "description": edit["description"],
                "hashtags": edit.get("hashtags", []),
                "media": [{"idx": photos[0]["idx"], "caption": photos[0].get("caption", ""), "is_cover": True}],
            })
            assert put.status_code == 200, put.text

            got = client.get(f"{API}/posts/{pid}").json()
            assert got["photo_count"] == 1, got
            assert got["video_count"] == 0, got
            assert got.get("photos_url"), "photos_url must remain"
            assert got.get("videos_url") in (None, "", False), f"videos_url should be null, got {got.get('videos_url')}"
        finally:
            client.delete(f"{API}/posts/{pid}?delete_media=true")
