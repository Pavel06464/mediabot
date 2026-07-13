import os
import httpx


def _api() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return f"https://api.telegram.org/bot{token}"


async def get_chat(identifier):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{_api()}/getChat", params={"chat_id": identifier})
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]


async def send_message(chat_id, text: str):
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(
            f"{_api()}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": False, "prefer_large_media": True},
            },
        )
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]
