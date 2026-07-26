"""Verifies Telegraph flood-control auto-retry for short wait windows."""
import asyncio
import pytest

import telegraph_service as ts


class _FloodThenOk:
    """Fake tg: raises 'Flood control' N times, then returns a page dict."""
    def __init__(self, fails, wait_seconds):
        self.calls = 0
        self.fails = fails
        self.wait = wait_seconds

    async def create_page(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fails:
            raise Exception(f"Flood control exceeded. Retry in {self.wait} seconds")
        return {"url": "https://telegra.ph/ok", "path": "ok"}


def test_flood_retry_short_wait(monkeypatch):
    """Short flood window (<= FLOOD_MAX_WAIT) is auto-retried until success."""
    fake = _FloodThenOk(fails=2, wait_seconds=1)
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(ts.asyncio, "sleep", fake_sleep)

    async def factory():
        return await fake.create_page(title="t", html_content="c", author_name="a")

    resp = asyncio.run(ts._call_with_flood_retry(factory))
    assert resp["path"] == "ok"
    assert fake.calls == 3  # 2 floods + 1 success
    assert len(slept) == 2  # waited before each retry


def test_flood_long_wait_not_retried(monkeypatch):
    """Long flood window (> FLOOD_MAX_WAIT) is NOT auto-retried; error bubbles up."""
    fake = _FloodThenOk(fails=1, wait_seconds=ts.FLOOD_MAX_WAIT + 100)

    async def fake_sleep(s):
        pass

    monkeypatch.setattr(ts.asyncio, "sleep", fake_sleep)

    async def factory():
        return await fake.create_page()

    with pytest.raises(Exception) as ei:
        asyncio.run(ts._call_with_flood_retry(factory))
    assert "flood" in str(ei.value).lower()
    assert fake.calls == 1  # not retried


def test_non_flood_error_reraised(monkeypatch):
    async def factory():
        raise ValueError("CONTENT_TOO_BIG")

    with pytest.raises(ValueError):
        asyncio.run(ts._call_with_flood_retry(factory))
