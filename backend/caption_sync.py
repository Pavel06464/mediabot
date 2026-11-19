"""Синхронизация подписи поста в Telegram из текущего текста в БД.

Для медиа (альбом, фото, видео) — только editMessageCaption, перебор channel_message_ids.
Для чисто текстовых сообщений — только editMessageText.
«message is not modified» считаем успехом «уже так». 429 — ждём retry_after + запас.
Первая ошибка caption логируется. Токен в логи не пишем.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import telegram_api

logger = logging.getLogger("caption_sync")

SLEEP_BETWEEN_POSTS = 1.5
RETRY_MARGIN = 2.0
MAX_429_RETRIES = 5


def message_ids(post: dict) -> list:
    """Сначала channel_message_id, затем остальные из альбома, без повторов."""
    ids = []
    mid = post.get("channel_message_id")
    if mid is not None:
        ids.append(mid)
    for x in post.get("channel_message_ids") or []:
        if x is not None and x not in ids:
            ids.append(x)
    return ids


def is_media_post(post: dict) -> bool:
    """Нативный альбом или Telegraph с обложкой/медиа — подпись, не текст сообщения."""
    if post.get("post_type") == "native":
        return any(b.get("type") in ("photo", "video") for b in (post.get("blocks") or []))
    if post.get("cover_url") or post.get("cover_urls"):
        return True
    if (post.get("photo_count") or 0) > 0 or (post.get("video_count") or 0) > 0:
        return True
    blocks = post.get("blocks") or []
    return any(b.get("type") in ("photo", "video") for b in blocks)


def is_not_modified(err: Exception) -> bool:
    if getattr(err, "is_not_modified", None):
        try:
            if err.is_not_modified():
                return True
        except TypeError:
            if err.is_not_modified:
                return True
    return "not modified" in str(err).lower()


def retry_after_seconds(err: Exception) -> float | None:
    val = getattr(err, "retry_after", None)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            return None
    return None


def build_caption(post: dict, publish_caption, native_caption) -> str:
    if post.get("post_type") == "native":
        return native_caption(post)
    return publish_caption(post)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def last_sync_fields(result: dict) -> dict:
    now = now_iso()
    return {
        "updated_at": now,
        "last_sync": {
            "at": now,
            "status": result.get("status"),
            "message": (result.get("message") or result.get("first_error") or "")[:400],
            "method": result.get("method"),
            "message_id": result.get("message_id"),
        },
    }


async def _call_with_retry(fn, chat_id, mid, caption, *, sleep, kind: str):
    attempts = 0
    while True:
        try:
            await fn(chat_id, mid, caption)
            return "ok", None
        except Exception as e:
            wait = retry_after_seconds(e)
            if wait is not None and attempts < MAX_429_RETRIES:
                attempts += 1
                await sleep(wait + RETRY_MARGIN)
                continue
            if is_not_modified(e):
                return "already_same", str(e)
            return "error", str(e)


async def push_caption(
    post: dict,
    caption: str,
    channel_id,
    *,
    edit_caption=None,
    edit_text=None,
    sleep=None,
) -> dict:
    """Отправляет готовую HTML-подпись в канал. Не меняет БД."""
    import asyncio
    sleep = sleep or asyncio.sleep
    edit_caption = edit_caption or telegram_api.edit_message_caption
    edit_text = edit_text or telegram_api.edit_message_text

    ids = message_ids(post)
    pid = post.get("id")
    if not ids:
        return {"status": "skip", "message": "Нет идентификатора сообщения в канале"}
    if not caption:
        return {"status": "skip", "message": "Пустая подпись"}

    media = is_media_post(post)
    method = "caption" if media else "text"
    fn = edit_caption if media else edit_text
    first_error = None

    for mid in ids:
        status, err = await _call_with_retry(fn, channel_id, mid, caption, sleep=sleep, kind=method)
        if status in ("ok", "already_same"):
            return {
                "status": status,
                "message": "Подпись уже такая" if status == "already_same" else "Подпись обновлена",
                "method": method,
                "message_id": mid,
                "first_error": first_error,
            }
        if first_error is None:
            first_error = f"{method} id={mid}: {err}"
            logger.warning("caption sync %s failed for post %s mid %s: %s", method, pid, mid, err)

    return {
        "status": "error",
        "message": first_error or "Не удалось обновить подпись в канале",
        "method": method,
        "first_error": first_error,
    }
