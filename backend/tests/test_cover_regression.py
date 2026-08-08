"""Regression tests after cover-parameter fix: auth + dashboard endpoints."""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://auto-channel-poster.preview.emergentagent.com").rstrip("/")


def _login():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "admin@mediabot.local", "password": "admin123"},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok, f"no token in login response: {r.json()}"
    return tok


def test_login_ok():
    tok = _login()
    assert isinstance(tok, str) and len(tok) > 10


def test_stats():
    tok = _login()
    r = requests.get(f"{BASE_URL}/api/stats", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, dict)


def test_posts():
    tok = _login()
    r = requests.get(f"{BASE_URL}/api/posts", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, (list, dict))


def test_channels():
    tok = _login()
    r = requests.get(f"{BASE_URL}/api/channels", headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data, (list, dict))
