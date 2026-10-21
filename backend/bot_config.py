"""Настройки Telegram-бота: токен и polling из БД (app_config._id='telegram_bot') с fallback на env.

Токен НИКОГДА не логируется и не отдаётся во фронт целиком — только маска (последние 4 символа).
Текущие значения кэшируются в памяти, чтобы синхронный telegram_api._api() мог их брать без БД.
"""
import os
import logging

import httpx

logger = logging.getLogger("bot_config")

CONFIG_ID = "telegram_bot"

_state = {"token": None, "source": "none", "polling": False, "polling_source": "env"}


def _env_token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _env_polling() -> bool:
    return os.environ.get("ENABLE_BOT_POLLING") == "1"


def api_base() -> str:
    """Базовый URL Bot API: Local Bot API Server (TELEGRAM_LOCAL_API_URL) или облако."""
    local = (os.environ.get("TELEGRAM_LOCAL_API_URL") or "").strip().rstrip("/")
    return local or "https://api.telegram.org"


def resolve(doc: dict | None) -> dict:
    """Чистая функция: приоритет БД > env."""
    doc = doc or {}
    db_token = (doc.get("token") or "").strip()
    if db_token:
        token, source = db_token, "db"
    elif _env_token():
        token, source = _env_token(), "env"
    else:
        token, source = None, "none"
    if "polling_enabled" in doc and doc["polling_enabled"] is not None:
        polling, psrc = bool(doc["polling_enabled"]), "db"
    else:
        polling, psrc = _env_polling(), "env"
    return {"token": token, "source": source, "polling": polling, "polling_source": psrc}


async def load(db) -> dict:
    doc = await db.app_config.find_one({"_id": CONFIG_ID})
    _state.update(resolve(doc))
    return dict(_state)


def current_token() -> str:
    """Актуальный токен (из кэша; до первого load() — из env)."""
    return _state["token"] or _env_token()


def current() -> dict:
    return dict(_state)


def mask(token: str | None) -> str | None:
    if not token:
        return None
    return "••••" + token[-4:] if len(token) > 4 else "••••"


async def check_token(token: str | None) -> dict:
    """getMe. status: valid | invalid | network_error | not_configured."""
    if not token:
        return {"status": "not_configured", "message": "Токен не задан"}
    url = f"{api_base()}/bot{token}/getMe"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        # Не логируем URL — в нём токен.
        return {"status": "network_error", "message": f"Нет связи с Telegram ({type(e).__name__})"}
    try:
        data = r.json()
    except Exception:
        data = {}
    if r.status_code in (401, 404) or (data.get("ok") is False and data.get("error_code") in (401, 404)):
        return {"status": "invalid",
                "message": "Токен невалиден или бот удалён (Telegram: %s)" % (data.get("description") or r.status_code)}
    if not data.get("ok"):
        return {"status": "network_error",
                "message": f"Ошибка Telegram: {data.get('description') or r.status_code}"}
    res = data["result"]
    return {"status": "valid", "message": "Бот найден",
            "bot": {"id": res.get("id"), "first_name": res.get("first_name"), "username": res.get("username")}}
