import os
import json
import shutil
import asyncio
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


async def probe_video(path: str):
    """Через ffprobe возвращает (duration_sec, width, height) или (None, None, None)."""
    if not shutil.which("ffprobe"):
        return None, None, None
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height:format=duration",
            "-of", "json", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        info = json.loads(out or b"{}")
        st = (info.get("streams") or [{}])[0]
        w, h = st.get("width"), st.get("height")
        dur = info.get("format", {}).get("duration")
        dur = int(float(dur)) if dur else None
        return dur, w, h
    except Exception:
        return None, None, None


async def extract_thumb(path: str):
    """Через ffmpeg извлекает JPEG-обложку (<=320px), возвращает путь или None."""
    if not shutil.which("ffmpeg"):
        return None
    fd, thumb = tempfile.mkstemp(prefix="thumb_", suffix=".jpg")
    os.close(fd)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-ss", "0", "-i", path, "-vframes", "1",
            "-vf", "scale=320:320:force_original_aspect_ratio=decrease",
            "-q:v", "4", thumb,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if os.path.exists(thumb) and os.path.getsize(thumb) > 0:
            return thumb
    except Exception:
        pass
    if os.path.exists(thumb):
        os.unlink(thumb)
    return None


async def extract_cover(path: str):
    """Полноразмерный JPEG-кадр для параметра `cover` (НЕ ограничен 320px, в отличие от thumbnail).

    Берёт кадр на ~1-й секунде (пропуская возможный чёрный интро-кадр), высокое качество q:v 2,
    без уменьшения разрешения. Даёт чёткую обложку видео в канале.
    """
    if not shutil.which("ffmpeg"):
        return None
    fd, out = tempfile.mkstemp(prefix="cover_", suffix=".jpg")
    os.close(fd)
    for ss in ("1", "0"):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-ss", ss, "-i", path, "-vframes", "1", "-q:v", "2", out,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            if os.path.exists(out) and os.path.getsize(out) > 0:
                return out
        except Exception:
            pass
    if os.path.exists(out):
        os.unlink(out)
    return None


async def remux_faststart(path: str):
    """Перепаковывает mp4 c moov-атомом в начало (стрим + серверное превью).

    Быстро (-c copy, без перекодирования). Возвращает путь к новому файлу
    или None, если ffmpeg нет / перепаковка не удалась (тогда шлём оригинал).
    """
    if not shutil.which("ffmpeg"):
        return None
    fd, out = tempfile.mkstemp(prefix="fast_", suffix=".mp4")
    os.close(fd)
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", path, "-c", "copy", "-movflags", "+faststart", out,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate()
        if proc.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return out
    except Exception:
        pass
    if os.path.exists(out):
        os.unlink(out)
    return None



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


async def edit_message_caption(chat_id, message_id, caption: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_api()}/editMessageCaption",
                         json={"chat_id": chat_id, "message_id": message_id, "caption": caption, "parse_mode": "HTML"})
        data = r.json()
        if not data.get("ok"):
            raise ValueError(data.get("description", "Ошибка Telegram"))
        return True


async def edit_message_text(chat_id, message_id, text: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{_api()}/editMessageText",
                         json={"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML",
                               "disable_web_page_preview": False})
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


async def send_video_file(chat_id, path: str, filename: str, caption: str,
                          thumb: str = None, width=None, height=None, duration=None, cover: str = None):
    async def _post(include_cover: bool):
        handles = []
        try:
            fh = open(path, "rb")
            handles.append(fh)
            files = {"video": (filename, fh, "video/mp4")}
            form = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML", "supports_streaming": "true"}
            if width:
                form["width"] = str(width)
            if height:
                form["height"] = str(height)
            if duration:
                form["duration"] = str(duration)
            if thumb:
                tfh = open(thumb, "rb")
                handles.append(tfh)
                files["thumb"] = ("thumb.jpg", tfh, "image/jpeg")
                form["thumbnail"] = "attach://thumb"
            if include_cover and cover:
                cfh = open(cover, "rb")
                handles.append(cfh)
                files["cover"] = ("cover.jpg", cfh, "image/jpeg")
                form["cover"] = "attach://cover"
            async with httpx.AsyncClient(timeout=_LONG) as c:
                r = await c.post(f"{_api()}/sendVideo", data=form, files=files)
            return r.json()
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass

    data = await _post(include_cover=True)
    if not data.get("ok") and cover:
        # Старый Local Bot API может не знать поле cover — повторяем без него
        data = await _post(include_cover=False)
    if not data.get("ok"):
        raise ValueError(data.get("description", "Ошибка Telegram"))
    return data["result"]


async def send_media_group_files(chat_id, items: list):
    """Альбом (2-10) multipart-ом. items: [{type, path, filename, mime, caption?,
    (для видео) thumb?, cover?, width?, height?, duration?}]."""
    async def _post(include_cover: bool):
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
                if it["type"] == "video":
                    m["supports_streaming"] = True
                    if it.get("width"):
                        m["width"] = it["width"]
                    if it.get("height"):
                        m["height"] = it["height"]
                    if it.get("duration"):
                        m["duration"] = it["duration"]
                    if it.get("thumb"):
                        tkey = f"thumb{i}"
                        tfh = open(it["thumb"], "rb")
                        handles.append(tfh)
                        files[tkey] = ("thumb.jpg", tfh, "image/jpeg")
                        m["thumbnail"] = f"attach://{tkey}"
                    if include_cover and it.get("cover"):
                        ckey = f"cover{i}"
                        cfh = open(it["cover"], "rb")
                        handles.append(cfh)
                        files[ckey] = ("cover.jpg", cfh, "image/jpeg")
                        m["cover"] = f"attach://{ckey}"
                if it.get("caption"):
                    m["caption"] = it["caption"]
                    m["parse_mode"] = "HTML"
                media.append(m)
            form = {"chat_id": str(chat_id), "media": json.dumps(media)}
            async with httpx.AsyncClient(timeout=_LONG) as c:
                r = await c.post(f"{_api()}/sendMediaGroup", data=form, files=files)
            return r.json()
        finally:
            for fh in handles:
                try:
                    fh.close()
                except Exception:
                    pass

    has_cover = any(it.get("cover") for it in items)
    data = await _post(include_cover=True)
    if not data.get("ok") and has_cover:
        # Старый Local Bot API может не знать поле cover — повторяем без него
        data = await _post(include_cover=False)
    if not data.get("ok"):
        raise ValueError(data.get("description", "Ошибка Telegram"))
    return data["result"]



async def send_photo_album(chat_id, urls: list, caption: str):
    """Скачивает 2-3 фото-обложки и отправляет альбомом (media group) с подписью на первом.

    Используется как «обложка до 3 фото» для Telegraph-постов вместо одного большого превью.
    Возвращает список сообщений Telegram.
    """
    paths = []
    try:
        items = []
        for i, u in enumerate(urls):
            p = await _download_to_temp(u)
            paths.append(p)
            fn, mime = _guess("photo", u)
            it = {"type": "photo", "path": p, "filename": fn, "mime": mime}
            if i == 0 and caption:
                it["caption"] = caption
            items.append(it)
        return await send_media_group_files(chat_id, items)
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except Exception:
                pass
