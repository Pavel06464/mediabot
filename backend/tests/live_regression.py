"""Live regression: photo post + multi-page video post + hashtag not in Telegraph article."""
import time
import struct
import zlib
import requests

BASE = "https://auto-channel-poster.preview.emergentagent.com"


def _png_bytes():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _mp4_bytes():
    ftyp = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41"
    mdat = b"\x00\x00\x00\x08mdat"
    return ftyp + mdat + b"\x00" * 128


def login():
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@mediabot.local", "password": "admin123"}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def wait_ready(headers, pid, timeout=120):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = requests.get(f"{BASE}/api/posts/{pid}", headers=headers, timeout=30)
        r.raise_for_status()
        last = r.json()
        if last.get("status") in ("ready", "error"):
            return last
        time.sleep(1.5)
    return last


created = []
token = login()
H = {"Authorization": f"Bearer {token}"}
print("LOGIN OK")

# --- Test 1: Single photo post
draft = {
    "title": "TEST_photo_post",
    "description": "regression photo body",
    "hashtags": ["#TESTtag1", "#TESTtag2"],
    "media": [{"kind": "photo", "is_cover": True}],
}
r = requests.post(f"{BASE}/api/posts/draft", headers=H, json=draft, timeout=30)
print("draft photo:", r.status_code, r.text[:200])
assert r.status_code in (200, 201), r.text
d = r.json()
pid = d["id"]
slots = d["slots"]
created.append(pid)

files = {"file": ("t.png", _png_bytes(), "image/png")}
r = requests.post(f"{BASE}/api/posts/{pid}/media/{slots[0]}", headers=H, files=files, timeout=60)
print("upload photo:", r.status_code, r.text[:200])
assert r.status_code in (200, 201), r.text

final = wait_ready(H, pid, timeout=120)
print("final photo status:", final.get("status"), "photos_url:", final.get("photos_url") or final.get("telegraph_url"))
assert final.get("status") == "ready", final
tg_url = final.get("photos_url") or final.get("telegraph_url")
assert tg_url and tg_url.startswith("https://telegra.ph/"), final

# Hashtag NOT in Telegraph article
page_html = requests.get(tg_url, timeout=30).text
assert "TESTtag1" not in page_html and "TESTtag2" not in page_html, "Hashtag leaked into Telegraph article!"
print("HASHTAGS ABSENT FROM TELEGRAPH OK")

# --- Test 2: Multi-page video post (12 slots -> pagination)
draft2 = {
    "title": "TEST_video_paginated",
    "description": "regression video pagination",
    "hashtags": [],
    "media": [{"kind": "video"} for _ in range(12)],
}
r = requests.post(f"{BASE}/api/posts/draft", headers=H, json=draft2, timeout=30)
print("draft video:", r.status_code)
assert r.status_code in (200, 201), r.text
d2 = r.json()
pid2 = d2["id"]
slots2 = d2["slots"]
created.append(pid2)

for idx in slots2:
    files = {"file": ("t.mp4", _mp4_bytes(), "video/mp4")}
    rr = requests.post(f"{BASE}/api/posts/{pid2}/media/{idx}", headers=H, files=files, timeout=60)
    if rr.status_code not in (200, 201):
        print(f"upload video slot {idx}: {rr.status_code} {rr.text[:200]}")
    assert rr.status_code in (200, 201), rr.text

final2 = wait_ready(H, pid2, timeout=240)
print("final video status:", final2.get("status"), "videos_url:", final2.get("videos_url"))
assert final2.get("status") == "ready", final2
assert final2.get("videos_url", "").startswith("https://telegra.ph/"), final2

# Cleanup
for cid in created:
    try:
        rr = requests.delete(f"{BASE}/api/posts/{cid}?delete_media=true", headers=H, timeout=30)
        print(f"cleanup {cid}: {rr.status_code}")
    except Exception as e:
        print("cleanup err:", e)

print("ALL LIVE REGRESSION OK")
