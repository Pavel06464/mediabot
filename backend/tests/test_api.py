"""Backend API tests for Media Post Bot dashboard.

Covers:
- GET /api/stats
- GET /api/posts, GET /api/posts/{id}
- GET /api/channels
- GET /api/media/{media_id}
- DELETE /api/posts/{id}  (only 404 branch — do NOT delete seeded post)
"""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


# ---------- /api/ root ----------
def test_root(client):
    r = client.get(f"{API}/")
    assert r.status_code == 200
    assert r.json().get("message") == "Media Post Bot API"


# ---------- /api/stats ----------
def test_stats_schema(client):
    r = client.get(f"{API}/stats")
    assert r.status_code == 200
    data = r.json()
    for k in ("total_posts", "total_published", "total_drafts", "total_media", "channels_configured"):
        assert k in data, f"missing key {k}"
        assert isinstance(data[k], int)
    # drafts = total - published
    assert data["total_drafts"] == data["total_posts"] - data["total_published"]


# ---------- /api/posts ----------
def test_posts_list_no_objectid_and_sorted(client):
    r = client.get(f"{API}/posts")
    assert r.status_code == 200
    posts = r.json()
    assert isinstance(posts, list)
    assert len(posts) >= 1, "expected seeded post"
    for p in posts:
        assert "_id" not in p, "mongo _id must be excluded"
        assert "id" in p
        assert "title" in p
        assert "telegraph_url" in p
        assert "created_at" in p
    # sorted desc by created_at
    if len(posts) > 1:
        dates = [p["created_at"] for p in posts]
        assert dates == sorted(dates, reverse=True), "posts must be sorted by created_at desc"


def test_seeded_post_present(client):
    r = client.get(f"{API}/posts")
    posts = r.json()
    titles = [p["title"] for p in posts]
    assert "Тестовая статья" in titles


# ---------- /api/posts/{id} ----------
def test_get_post_by_id(client):
    posts = client.get(f"{API}/posts").json()
    assert posts, "need at least one post"
    pid = posts[0]["id"]
    r = client.get(f"{API}/posts/{pid}")
    assert r.status_code == 200
    p = r.json()
    assert p["id"] == pid
    assert "_id" not in p


def test_get_post_not_found(client):
    r = client.get(f"{API}/posts/nonexistent-uuid-xxx")
    assert r.status_code == 404


# ---------- /api/channels ----------
def test_channels_list(client):
    r = client.get(f"{API}/channels")
    assert r.status_code == 200
    channels = r.json()
    assert isinstance(channels, list)
    for c in channels:
        assert "user_id" in c
        assert "channel_id" in c
        assert "channel_title" in c


# ---------- /api/media/{media_id} ----------
def test_media_valid(client):
    posts = client.get(f"{API}/posts").json()
    media_id = None
    for p in posts:
        if p.get("media_ids"):
            media_id = p["media_ids"][0]
            break
    if not media_id:
        pytest.skip("no media in seeded data")
    r = client.get(f"{API}/media/{media_id}")
    assert r.status_code == 200
    assert len(r.content) > 0
    assert "content-type" in {k.lower() for k in r.headers.keys()}


def test_media_invalid_objectid(client):
    # A bad ObjectId string that fails ObjectId parsing
    r = client.get(f"{API}/media/not-a-valid-objectid")
    assert r.status_code == 404


def test_media_valid_objectid_not_found(client):
    # A valid ObjectId format but not stored
    r = client.get(f"{API}/media/000000000000000000000000")
    assert r.status_code == 404


# ---------- DELETE /api/posts/{id} (only 404 branch, don't touch seeded) ----------
def test_delete_post_not_found(client):
    r = client.delete(f"{API}/posts/nonexistent-uuid-yyy")
    assert r.status_code == 404
