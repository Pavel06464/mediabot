"""Юнит-тесты настроек Telegram-бота. Telegram и Mongo замоканы, сеть не нужна."""
import asyncio
import httpx
import pytest
from fastapi.testclient import TestClient

import bot_config
import telegram_bot
import server
import auth

GOOD = "123456789:AAFakeTokenForUnitTestsOnly_abcdefgh1234"
BAD = "987654321:BBFakeTokenForUnitTestsOnly_zzzzzzzz9999"


class FakeColl:
    def __init__(self):
        self.docs = {}

    async def find_one(self, q, proj=None):
        d = self.docs.get(q["_id"])
        return dict(d) if d else None

    async def update_one(self, q, op, upsert=False):
        d = self.docs.setdefault(q["_id"], {"_id": q["_id"]})
        d.update(op.get("$set", {}))
        for k in op.get("$unset", {}):
            d.pop(k, None)


class FakeDB:
    def __init__(self):
        self.app_config = FakeColl()


def tg_handler(request: httpx.Request):
    if f"/bot{GOOD}/getMe" in str(request.url):
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "first_name": "Медиа", "username": "media_bot"}})
    return httpx.Response(401, json={"ok": False, "error_code": 401, "description": "Unauthorized"})


@pytest.fixture
def env(monkeypatch):
    fdb = FakeDB()
    monkeypatch.setattr(server, "db", fdb)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("ENABLE_BOT_POLLING", raising=False)
    monkeypatch.delenv("TELEGRAM_LOCAL_API_URL", raising=False)
    real = httpx.AsyncClient
    monkeypatch.setattr(bot_config.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(tg_handler)))
    polls = {"active": 0, "max": 0, "started": 0}

    async def fake_start_polling(self, *bots, **kw):
        polls["active"] += 1; polls["started"] += 1
        polls["max"] = max(polls["max"], polls["active"])
        self._stop_ev = asyncio.Event()
        try:
            await self._stop_ev.wait()
        finally:
            polls["active"] -= 1

    async def fake_stop_polling(self):
        self._stop_ev.set()

    async def fake_delete_webhook(self, **kw):
        return True

    monkeypatch.setattr(telegram_bot.Dispatcher, "start_polling", fake_start_polling)
    monkeypatch.setattr(telegram_bot.Dispatcher, "stop_polling", fake_stop_polling)
    monkeypatch.setattr(telegram_bot.Bot, "delete_webhook", fake_delete_webhook)
    server.app.dependency_overrides[auth.get_current_user] = lambda: {"id": "1", "email": "a@b"}
    client = TestClient(server.app)
    yield client, fdb, polls
    server.app.dependency_overrides.clear()
    telegram_bot.bot = telegram_bot._dp = telegram_bot._task = None
    telegram_bot.router._parent_router = None


def test_resolve_precedence(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "env:tok")
    monkeypatch.setenv("ENABLE_BOT_POLLING", "1")
    assert bot_config.resolve(None)["source"] == "env"
    assert bot_config.resolve(None)["polling"] is True
    r = bot_config.resolve({"token": "db:tok", "polling_enabled": False})
    assert (r["token"], r["source"], r["polling"], r["polling_source"]) == ("db:tok", "db", False, "db")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert bot_config.resolve({})["source"] == "none"


def test_mask_never_full():
    assert bot_config.mask(GOOD) == "••••" + GOOD[-4:]
    assert bot_config.mask(None) is None


def test_auth_required():
    c = TestClient(server.app)
    assert c.get("/api/settings/bot").status_code == 401
    assert c.put("/api/settings/bot", json={"token": GOOD}).status_code == 401
    assert c.post("/api/settings/bot/restart").status_code == 401


def test_not_configured(env):
    c, _, _ = env
    r = c.get("/api/settings/bot?check=true").json()
    assert r["source"] == "none" and r["token_masked"] is None
    assert r["check"]["status"] == "not_configured"


def test_env_fallback(env, monkeypatch):
    c, _, _ = env
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", GOOD)
    r = c.get("/api/settings/bot?check=true").json()
    assert r["source"] == "env"
    assert r["check"]["status"] == "valid" and r["check"]["bot"]["username"] == "media_bot"


def test_save_token_masked_and_polling(env):
    c, fdb, polls = env
    r = c.put("/api/settings/bot", json={"token": GOOD, "polling_enabled": True})
    assert r.status_code == 200
    assert GOOD not in r.text
    body = r.json()
    assert body["source"] == "db" and body["token_masked"].endswith(GOOD[-4:])
    assert body["check"]["status"] == "valid"
    assert fdb.app_config.docs["telegram_bot"]["token"] == GOOD
    assert bot_config.current_token() == GOOD
    assert GOOD not in c.get("/api/settings/bot").text


def test_invalid_token(env):
    c, _, _ = env
    r = c.post("/api/settings/bot/check", json={"token": BAD}).json()
    assert r["status"] == "invalid"


def test_bad_format_rejected(env):
    c, _, _ = env
    assert c.put("/api/settings/bot", json={"token": "nope"}).status_code == 400


def test_network_error(env, monkeypatch):
    c, _, _ = env
    def boom(request):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(bot_config.httpx, "AsyncClient", lambda **kw: _ac(boom))
    r = c.post("/api/settings/bot/check", json={"token": GOOD}).json()
    assert r["status"] == "network_error"
    assert GOOD not in r["message"]


_RealAC = httpx.AsyncClient
def _ac(handler):
    return _RealAC(transport=httpx.MockTransport(handler))


def test_clear_token_falls_back_to_env(env, monkeypatch):
    c, fdb, _ = env
    c.put("/api/settings/bot", json={"token": GOOD})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BAD)
    r = c.put("/api/settings/bot", json={"clear_token": True}).json()
    assert r["source"] == "env" and "token" not in fdb.app_config.docs["telegram_bot"]


def test_restart_never_two_pollers():
    """Многократный restart: одновременно работает не более одного поллера, сессии закрываются."""
    closed = []

    class FakeSession:
        async def close(self):
            closed.append(1)

    class FakeBot:
        def __init__(self):
            self.session = FakeSession()
        async def delete_webhook(self, **kw):
            return True

    polls = {"active": 0, "max": 0}

    async def fake_start(self, *b, **kw):
        polls["active"] += 1; polls["max"] = max(polls["max"], polls["active"])
        self._ev = asyncio.Event()
        try:
            await self._ev.wait()
        finally:
            polls["active"] -= 1

    async def fake_stop(self):
        self._ev.set()

    async def run():
        mp = pytest.MonkeyPatch()
        mp.setattr(telegram_bot, "_build_bot", lambda token: FakeBot())
        mp.setattr(telegram_bot.Dispatcher, "start_polling", fake_start)
        mp.setattr(telegram_bot.Dispatcher, "stop_polling", fake_stop)
        try:
            for _ in range(3):
                assert await telegram_bot.restart_bot(GOOD, True) is True
                await asyncio.sleep(0.01)
                assert telegram_bot.is_running()
            await asyncio.gather(*(telegram_bot.restart_bot(GOOD, True) for _ in range(3)))
            await asyncio.sleep(0.01)
            assert polls["max"] == 1
            assert await telegram_bot.restart_bot(GOOD, False) is False
            assert not telegram_bot.is_running() and polls["active"] == 0
            assert len(closed) == 6
        finally:
            await telegram_bot.stop_bot()
            mp.undo()

    asyncio.run(run())


def test_local_api_base(monkeypatch):
    monkeypatch.setenv("TELEGRAM_LOCAL_API_URL", "http://localhost:8081/")
    assert bot_config.api_base() == "http://localhost:8081"
    import telegram_api
    bot_config._state["token"] = GOOD
    assert telegram_api._api() == f"http://localhost:8081/bot{GOOD}"
