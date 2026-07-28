import os
import json
import tempfile
import httpx

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# Без таймаута на upload/download — большие файлы (до 2 ГБ) могут идти долго.
_LONG = httpx.Timeout(None)


def _base() -> str:
    """Базовый URL Telegram Bot API: Local Bot API Server, если задан, иначе облако."""
    local = (os.environ.get("TELEGRAM_LOCAL_API_URL") or "").strip().rstrip("/")
    return local or "https://api.telegram.org"


def _api() -> str:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    return f"{_base()}/bot{token}"


def _guess(kind: str, url_or_name: str) -> tuple[str, str]:
    """Возвращает (filename, mime) по типу медиа и имени/URL."""
    ext = os.path.splitext((url_or_name or "").split("?")[0])[1].lower()
    if kind == "video":
        return (f"video{ext or '.mp4'}", "video/mp4")
    return (f"photo{ext or '.jpg'}", "image/jpeg")


async def _download_to_temp(url: str) -> str:
    """Скачивает файл по URL (R2/GridFS) во временный файл потоком, возвращает путь."""
    fd, path = tempfile.mkstemp(prefix="tgsend_")
    os.close(fd)
    try:
        async with httpx.AsyncClient(timeout=_LONG, follow_redirects=True) as c:
            async with c.stream("GET", url, headers={"User-Agent": _UA}) as resp:
                resp.raise_for_status()
                with open(path, "wb") as f:
                    async for chunk in resp.aiter_bytes(1024 * 1024):
                        f.write(chunk)
        return path
    except Exception:
        if os.path.exists(path):
            os.unlink(path)
        raise


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


async def delete_message(chat_id, message_id):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{_api()}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id})
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return True


async def send_media_group(chat_id, media: list):
    """Отправляет альбом (2-10 медиа) по URL. media: [{type, media, caption?, parse_mode?}]."""
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{_api()}/sendMediaGroup", json={"chat_id": str(chat_id), "media": media})
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]  # список сообщений


async def send_video(chat_id, video_url: str, caption: str):
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{_api()}/sendVideo",
            json={"chat_id": str(chat_id), "video": video_url, "caption": caption, "parse_mode": "HTML"},
        )
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]


# ── Multipart-отправка файлов (обход лимита 20 МБ при скачивании по URL) ──
# Каждый файл скачивается с R2 во временный файл и отправляется как InputFile.
# Для файлов > 50 МБ обязателен Local Bot API Server (TELEGRAM_LOCAL_API_URL).

async def send_photo_file(chat_id, path: str, filename: str, caption: str):
    with open(path, "rb") as fh:
        files = {"photo": (filename, fh, "image/jpeg")}
        form = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML"}
        async with httpx.AsyncClient(timeout=_LONG) as c:
            r = await c.post(f"{_api()}/sendPhoto", data=form, files=files)
    data = r.json()
    if not data.get("ok"):
        raise ValueError(data.get("description", "Ошибка Telegram"))
    return data["result"]


async def send_video_file(chat_id, path: str, filename: str, caption: str):
    with open(path, "rb") as fh:
        files = {"video": (filename, fh, "video/mp4")}
        form = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML", "supports_streaming": "true"}
        async with httpx.AsyncClient(timeout=_LONG) as c:
            r = await c.post(f"{_api()}/sendVideo", data=form, files=files)
    data = r.json()
    if not data.get("ok"):
        raise ValueError(data.get("description", "Ошибка Telegram"))
    return data["result"]


async def send_media_group_files(chat_id, items: list):
    """Альбом (2-10) multipart-ом. items: [{type, path, filename, mime, caption?}]."""
    handles = []
    try:
        media = []
        files = {}
        for i, it in enumerate(items):
            key = f"file{i}"
            fh = open(it["path"], "rb")
            handles.append(fh)
            files[key] = (it["filename"], fh, it.get("mime") or ("video/mp4" if it["type"] == "video" else "image/jpeg"))
            m = {"type": it["type"], "media": f"attach://{key}"}
            if it.get("caption"):
                m["caption"] = it["caption"]
                m["parse_mode"] = "HTML"
            media.append(m)
        form = {"chat_id": str(chat_id), "media": json.dumps(media)}
        async with httpx.AsyncClient(timeout=_LONG) as c:
            r = await c.post(f"{_api()}/sendMediaGroup", data=form, files=files)
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return data["result"]
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:
                pass
