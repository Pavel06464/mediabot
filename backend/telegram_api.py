import os
import httpx

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


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
                "link_preview_options": {"is_disabled": False, "prefer_large_media": True, "show_above_text": True},
            },
        )
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]


async def send_photo(chat_id, photo_url: str, caption: str):
    """Скачивает изображение и отправляет как фото (гарантирует большой предпросмотр)."""
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as c:
        img = await c.get(photo_url, headers={"User-Agent": _UA})
        img.raise_for_status()
        ctype = img.headers.get("content-type", "")
        if not ctype.startswith("image/"):
            raise ValueError(f"Обложка не изображение (content-type: {ctype or 'unknown'})")
        if len(img.content) > 10 * 1024 * 1024:
            raise ValueError("Обложка больше 10 МБ — Telegram не примет её как фото")
        files = {"photo": ("cover.jpg", img.content, "image/jpeg")}
        form = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
        r = await c.post(f"{_api()}/sendPhoto", data=form, files=files)
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]
