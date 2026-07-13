"""Backend tests for the NEW watermark feature.

Endpoints covered:
- GET /api/settings/watermark              (auth-gated; returns defaults if not set)
- PUT /api/settings/watermark              (persists config)
- POST /api/settings/watermark/preview     (returns data:image/jpeg;base64,...)
- POST /api/upload                          (photo uploads get watermark burned in when enabled)

Uses one class -> loadscope pins to a single worker so state (login token, config) is shared.
Resets watermark to disabled at teardown to avoid affecting later manual use.
"""
import os
import io
import base64
import pytest
import requests
from PIL import Image

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL", "https://auto-channel-poster.preview.emergentagent.com"
).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@mediabot.local"
ADMIN_PASSWORD = "admin123"


def _make_png_bytes(w=200, h=150, color=(30, 90, 200)) -> bytes:
    """Create a real solid-color PNG so watermark rendering has canvas room."""
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"login failed: {r.text}"
    tok = r.json()["token"]
    s.headers.update({"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def anon():
    return requests.Session()


class TestWatermark:
    """Full watermark flow: auth → CRUD → preview → apply-on-upload → reset."""

    # ---------- auth gating ----------
    def test_01_get_watermark_requires_auth(self, anon):
        assert anon.get(f"{API}/settings/watermark").status_code == 401

    def test_02_put_watermark_requires_auth(self, anon):
        r = anon.put(f"{API}/settings/watermark", json={"enabled": True})
        assert r.status_code == 401

    def test_03_preview_requires_auth(self, anon):
        r = anon.post(f"{API}/settings/watermark/preview", json={"enabled": True})
        assert r.status_code == 401

    # ---------- GET returns object ----------
    def test_04_get_watermark_returns_object(self, client):
        r = client.get(f"{API}/settings/watermark")
        assert r.status_code == 200
        d = r.json()
        # Must have the expected keys
        for k in ("enabled", "type", "text", "color", "position", "size", "opacity"):
            assert k in d, f"missing key {k} in {d}"
        assert "_id" not in d

    # ---------- PUT persists and GET reflects ----------
    def test_05_put_and_get_reflects(self, client):
        cfg = {
            "enabled": True,
            "type": "text",
            "text": "@test_wm",
            "color": "white",
            "logo_b64": "",
            "position": "bottom-right",
            "size": 20,
            "opacity": 70,
        }
        r = client.put(f"{API}/settings/watermark", json=cfg)
        assert r.status_code == 200, r.text
        saved = r.json()
        for k, v in cfg.items():
            assert saved[k] == v, f"{k}: expected {v}, got {saved.get(k)}"

        # GET should reflect
        r2 = client.get(f"{API}/settings/watermark")
        assert r2.status_code == 200
        got = r2.json()
        for k, v in cfg.items():
            assert got[k] == v, f"persist mismatch: {k}={got.get(k)} != {v}"

    # ---------- preview returns data URI JPEG ----------
    def test_06_preview_returns_data_uri_jpeg(self, client):
        payload = {
            "enabled": True, "type": "text", "text": "@preview",
            "color": "white", "position": "center", "size": 20, "opacity": 60,
        }
        r = client.post(f"{API}/settings/watermark/preview", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "image" in data
        img = data["image"]
        assert isinstance(img, str)
        assert img.startswith("data:image/jpeg;base64,")
        raw = base64.b64decode(img.split(",", 1)[1])
        # Should decode as a valid JPEG image (opens with Pillow, mode!=None)
        pim = Image.open(io.BytesIO(raw))
        pim.verify()  # raises on bad image
        assert pim.format == "JPEG"

    def test_07_preview_changes_when_settings_change(self, client):
        base = {"enabled": True, "type": "text", "text": "AAA", "color": "white",
                "position": "top-left", "size": 15, "opacity": 50}
        img1 = client.post(f"{API}/settings/watermark/preview", json=base).json()["image"]
        # Change position -> pixels differ
        p2 = {**base, "position": "bottom-right", "text": "ZZZ", "size": 40, "opacity": 90}
        img2 = client.post(f"{API}/settings/watermark/preview", json=p2).json()["image"]
        assert img1 != img2, "preview image did not change after settings change"

    # ---------- Upload applies watermark when enabled ----------
    def test_08_upload_photo_applies_watermark_when_enabled(self, client):
        # ensure enabled
        client.put(f"{API}/settings/watermark", json={
            "enabled": True, "type": "text", "text": "@test_wm",
            "color": "white", "logo_b64": "", "position": "bottom-right",
            "size": 25, "opacity": 90,
        })
        original = _make_png_bytes(300, 200, color=(50, 200, 100))
        r = client.post(
            f"{API}/upload",
            files={"file": ("in.png", io.BytesIO(original), "image/png")},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["type"] == "photo"
        assert "media_id" in d
        media_id = d["media_id"]

        # Fetch stored file
        g = requests.get(f"{API}/media/{media_id}", timeout=15)
        assert g.status_code == 200
        stored = g.content
        # content-type should now be jpeg
        assert g.headers.get("content-type", "").startswith("image/jpeg"), g.headers
        # differs from original
        assert stored != original, "stored image identical to input; watermark not applied"
        # is a valid JPEG
        pim = Image.open(io.BytesIO(stored))
        assert pim.format == "JPEG"
        assert pim.size == (300, 200)  # dimensions preserved

    def test_09_upload_photo_no_watermark_when_disabled(self, client):
        # disable
        client.put(f"{API}/settings/watermark", json={
            "enabled": False, "type": "text", "text": "@off",
            "color": "white", "logo_b64": "", "position": "bottom-right",
            "size": 15, "opacity": 50,
        })
        original = _make_png_bytes(120, 80, color=(200, 30, 30))
        r = client.post(
            f"{API}/upload",
            files={"file": ("off.png", io.BytesIO(original), "image/png")},
        )
        assert r.status_code == 200, r.text
        media_id = r.json()["media_id"]

        g = requests.get(f"{API}/media/{media_id}", timeout=15)
        assert g.status_code == 200
        # When disabled the original PNG bytes should be stored as-is (content-type image/png)
        assert g.headers.get("content-type", "").startswith("image/png"), g.headers
        assert g.content == original, "photo bytes were altered while watermark disabled"

    # ---------- teardown ----------
    def test_10_reset_watermark_to_disabled(self, client):
        r = client.put(f"{API}/settings/watermark", json={
            "enabled": False, "type": "text", "text": "@mychannel",
            "color": "white", "logo_b64": "", "position": "bottom-right",
            "size": 15, "opacity": 50,
        })
        assert r.status_code == 200
        assert r.json()["enabled"] is False
