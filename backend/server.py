import os
import re
import uuid
import html as _html
import asyncio
import tempfile
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

from fastapi import FastAPI, APIRouter, HTTPException, Depends, UploadFile, File, Response
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from bson import ObjectId

from database import db, get_gridfs
import storage
import auth
import telegram_api
import watermark
from telegraph_service import create_paginated_page, edit_paginated_page

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

app = FastAPI(title="Media Post Bot API")
api_router = APIRouter(prefix="/api")


# ---------- Models ----------
class LoginIn(BaseModel):
    email: str
    password: str


class BlockIn(BaseModel):
    type: str  # text | photo | video
    url: Optional[str] = None
    media_id: Optional[str] = None
    r2_key: Optional[str] = None
    caption: Optional[str] = ""
    value: Optional[str] = None
    is_cover: bool = False


class PostIn(BaseModel):
    title: str
    blocks: List[BlockIn]


class ChannelIn(BaseModel):
    identifier: str


class MediaDesc(BaseModel):
    kind: str  # photo | video
    is_cover: bool = False
    caption: Optional[str] = ""


class DraftIn(BaseModel):
    title: str
    description: Optional[str] = ""
    publish_after: bool = False
    post_type: str = "telegraph"  # telegraph | native
    hashtags: List[str] = []
    media: List[MediaDesc] = []
    channel_ref: Optional[str] = None  # id канала (channels.id)


class MediaEdit(BaseModel):
    idx: int
    caption: Optional[str] = ""
    is_cover: bool = False


class NewMediaIn(BaseModel):
    kind: str  # photo | video
    url: str
    media_id: Optional[str] = None
    r2_key: Optional[str] = None
    caption: Optional[str] = ""
    is_cover: bool = False


class PostEditIn(BaseModel):
    title: str
    description: Optional[str] = ""
    hashtags: List[str] = []
    media: List[MediaEdit] = []
    new_media: List[NewMediaIn] = []
    channel_ref: Optional[str] = None


class ScheduleIn(BaseModel):
    scheduled_at: Optional[str] = None  # ISO datetime (интерпретируется как UTC)
    channel_ref: Optional[str] = None


class QueueIn(BaseModel):
    in_queue: bool = True
    channel_ref: Optional[str] = None


class QueueOrderIn(BaseModel):
    order: List[str] = []  # ids постов в нужном порядке


class SchedulerIn(BaseModel):
    enabled: bool = False
    interval_minutes: int = 60
    auto_enqueue: bool = False


class ChannelSchedulerIn(BaseModel):
    enabled: bool = False
    interval_minutes: int = 60
    auto_enqueue: bool = False


class SignatureIn(BaseModel):
    name: str
    content: str = ""


def _normalize_tags(raw):
    tags = []
    for item in raw or []:
        for piece in re.split(r"[\s,]+", str(item)):
            t = piece.strip().lstrip("#")
            t = re.sub(r"[^\wа-яёА-ЯЁ]", "", t, flags=re.UNICODE)
            if t:
                tags.append("#" + t)
    seen, out = set(), []
    for t in tags:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


async def _migrate_channels():
    """Однократная миграция: старый одиночный канал + scheduler → коллекция channels."""
    if await db.channels.count_documents({}) > 0:
        return
    old = await db.app_config.find_one({"_id": "channel"})
    if not old or not old.get("channel_id"):
        return
    sched = await db.app_config.find_one({"_id": "scheduler"}) or {}
    ch = {
        "id": str(uuid.uuid4()),
        "channel_id": old.get("channel_id"),
        "channel_title": old.get("channel_title"),
        "channel_username": old.get("channel_username"),
        "enabled": bool(sched.get("enabled")),
        "interval_minutes": int(sched.get("interval_minutes") or 60),
        "auto_enqueue": bool(sched.get("auto_enqueue")),
        "next_run_at": sched.get("next_run_at"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.channels.insert_one(ch)
    # все посты без channel_ref привязываем к этому каналу
    await db.posts.update_many({"channel_ref": {"$exists": False}}, {"$set": {"channel_ref": ch["id"]}})
    await db.posts.update_many({"channel_ref": None}, {"$set": {"channel_ref": ch["id"]}})


async def _resolve_channel(post: dict):
    """Канал поста: по channel_ref, иначе первый канал (fallback)."""
    ref = post.get("channel_ref")
    ch = await db.channels.find_one({"id": ref}) if ref else None
    if not ch:
        ch = await db.channels.find_one({}, sort=[("created_at", 1)])
    return ch


async def _next_queue_order(channel_ref: str) -> int:
    last = await db.posts.find_one(
        {"in_queue": True, "channel_ref": channel_ref},
        sort=[("queue_order", -1)], projection={"queue_order": 1},
    )
    return (last.get("queue_order") or 0) + 1 if last else 1



def _compose_description(description, tags):
    desc = (description or "").strip()
    tagline = " ".join(tags)
    if desc and tagline:
        return desc + "\n\n" + tagline
    return desc or tagline


# ---------- Auth ----------
@api_router.post("/auth/login")
async def login(payload: LoginIn):
    email = payload.email.strip().lower()
    user = await db.users.find_one({"email": email})
    if not user or not auth.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = auth.create_token(str(user["_id"]), email)
    return {"token": token, "user": {"id": str(user["_id"]), "email": email}}


@api_router.get("/auth/me")
async def me(user=Depends(auth.get_current_user)):
    return user


# ---------- Public health ----------
@api_router.get("/")
async def root():
    return {"message": "Media Post Bot API"}


# ---------- Stats ----------
@api_router.get("/stats")
async def get_stats(channel_ref: str = "", user=Depends(auth.get_current_user)):
    base = {}
    if channel_ref and channel_ref.strip():
        base = {"channel_ref": channel_ref.strip()}
    total_posts = await db.posts.count_documents(base)
    total_published = await db.posts.count_documents({**base, "published": True})
    pipeline = [{"$match": base}] if base else []
    pipeline.append({"$group": {"_id": None, "media": {"$sum": "$media_count"}}})
    agg = await db.posts.aggregate(pipeline).to_list(1)
    total_media = agg[0]["media"] if agg else 0
    in_queue = await db.posts.count_documents({**base, "in_queue": True, "published": {"$ne": True}})
    channels_count = await db.channels.count_documents({})
    return {
        "total_posts": total_posts,
        "total_published": total_published,
        "total_drafts": total_posts - total_published,
        "total_media": total_media,
        "in_queue": in_queue,
        "channels_configured": channels_count,
    }


# ---------- Posts ----------
@api_router.get("/posts")
async def get_posts(page: int = 1, page_size: int = 20, q: str = "",
                    sort_by: str = "date", sort_dir: str = "desc",
                    channel_ref: str = "",
                    user=Depends(auth.get_current_user)):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    query = {}
    if q and q.strip():
        query["title"] = {"$regex": re.escape(q.strip()), "$options": "i"}
    if channel_ref and channel_ref.strip():
        query["channel_ref"] = channel_ref.strip()
    total = await db.posts.count_documents(query)
    skip = (page - 1) * page_size
    direction = 1 if sort_dir == "asc" else -1

    pipeline = [{"$match": query}]
    collation = None
    if sort_by == "status":
        pipeline.append({"$addFields": {"_rank": {"$switch": {"branches": [
            {"case": {"$in": ["$status", ["uploading", "processing"]]}, "then": 0},
            {"case": {"$eq": ["$status", "ready"]}, "then": 1},
            {"case": {"$eq": ["$status", "published"]}, "then": 2},
            {"case": {"$eq": ["$status", "failed"]}, "then": 3},
        ], "default": 4}}}})
        sort_stage = {"_rank": direction, "created_at": -1}
    else:
        field = {"title": "title", "photos": "photo_count", "videos": "video_count",
                 "date": "created_at", "channel": "channel_title"}.get(sort_by, "created_at")
        sort_stage = {field: direction}
        if field != "created_at":
            sort_stage["created_at"] = -1
        if sort_by == "title":
            collation = {"locale": "ru", "strength": 2}
    pipeline += [{"$sort": sort_stage}, {"$skip": skip}, {"$limit": page_size},
                 {"$project": {"_id": 0, "blocks": 0, "_rank": 0}}]

    cursor = db.posts.aggregate(pipeline, collation=collation) if collation else db.posts.aggregate(pipeline)
    items = await cursor.to_list(page_size)
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@api_router.get("/posts/check-title")
async def check_title(title: str = "", user=Depends(auth.get_current_user)):
    t = (title or "").strip()
    if not t:
        return {"exists": False, "count": 0}
    count = await db.posts.count_documents({"title": {"$regex": f"^{re.escape(t)}$", "$options": "i"}})
    return {"exists": count > 0, "count": count}


@api_router.get("/hashtags/popular")
async def popular_hashtags(limit: int = 5, user=Depends(auth.get_current_user)):
    limit = min(50, max(1, limit))
    pipeline = [
        {"$unwind": "$hashtags"},
        {"$group": {"_id": "$hashtags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    rows = await db.posts.aggregate(pipeline).to_list(limit)
    return {"tags": [{"tag": r["_id"], "count": r["count"]} for r in rows if r["_id"]]}


@api_router.get("/signatures")
async def list_signatures(user=Depends(auth.get_current_user)):
    rows = await db.signatures.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    return {"signatures": rows}


@api_router.post("/signatures")
async def create_signature(payload: SignatureIn, user=Depends(auth.get_current_user)):
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Укажите название подписи")
    doc = {"id": str(uuid.uuid4()), "name": payload.name.strip(), "content": payload.content or "",
           "created_at": datetime.now(timezone.utc).isoformat()}
    await db.signatures.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api_router.put("/signatures/{sig_id}")
async def update_signature(sig_id: str, payload: SignatureIn, user=Depends(auth.get_current_user)):
    r = await db.signatures.update_one({"id": sig_id}, {"$set": {"name": payload.name.strip(), "content": payload.content or ""}})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Подпись не найдена")
    return {"status": "ok"}


@api_router.delete("/signatures/{sig_id}")
async def delete_signature(sig_id: str, user=Depends(auth.get_current_user)):
    await db.signatures.delete_one({"id": sig_id})
    return {"status": "ok"}



@api_router.get("/posts/{post_id}")
async def get_post(post_id: str, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id}, {"_id": 0, "blocks": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    return post


@api_router.post("/posts")
async def create_post(payload: PostIn, user=Depends(auth.get_current_user)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Укажите заголовок")
    blocks = [b.model_dump() for b in payload.blocks]
    if not blocks:
        raise HTTPException(status_code=400, detail="Добавьте хотя бы один блок")

    # Обложка (cover) идёт первой — Telegram берёт её как предпросмотр
    cover_idx = next(
        (i for i, b in enumerate(blocks) if b.get("is_cover") and b["type"] in ("photo", "video")),
        None,
    )
    if cover_idx is not None:
        ordered = [blocks[cover_idx]] + [b for i, b in enumerate(blocks) if i != cover_idx]
    else:
        ordered = blocks

    try:
        url, paths = await create_paginated_page(payload.title, ordered, BASE_URL)
        path = paths[0]
    except Exception as e:
        logger.exception("Telegraph create failed")
        raise HTTPException(status_code=500, detail=f"Ошибка Telegraph: {e}")

    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    r2_keys = [b["r2_key"] for b in blocks if b.get("r2_key")]
    preview = next((b.get("value") for b in blocks if b.get("type") == "text" and b.get("value")), "")
    cover_block = next((b for b in blocks if b.get("is_cover") and b["type"] == "photo" and b.get("url")), None)
    if not cover_block:
        cover_block = next((b for b in blocks if b["type"] == "photo" and b.get("url")), None)
    cover_url = cover_block["url"] if cover_block else None
    post_id = str(uuid.uuid4())
    doc = {
        "id": post_id,
        "user_id": user["id"],
        "title": payload.title.strip(),
        "telegraph_url": url,
        "telegraph_path": path,
        "cover_url": cover_url,
        "cover_urls": _cover_urls(blocks),
        "media_count": sum(1 for b in blocks if b["type"] in ("photo", "video")),
        "media_ids": media_ids,
        "r2_keys": r2_keys,
        "block_count": len(blocks),
        "preview": (preview or "")[:200],
        "published": False,
        "channel_title": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.posts.insert_one(doc)
    doc.pop("_id", None)
    return doc


def _split_media(blocks):
    """Разбивает блоки на текст / фото / видео и определяет обложки (до 3 is_cover фото)."""
    text_blocks = [b for b in blocks if b.get("type") == "text" and (b.get("value") or "").strip()]
    photos = [b for b in blocks if b.get("type") == "photo" and b.get("url")]
    videos = [b for b in blocks if b.get("type") == "video" and b.get("url")]
    covers = [b for b in photos if b.get("is_cover")][:3]
    if covers:
        photos = covers + [b for b in photos if not any(b is c for c in covers)]
        cover = covers[0]
    else:
        cover = photos[0] if photos else None
    return text_blocks, photos, videos, cover


def _cover_urls(blocks):
    """Список URL обложек (до 3 отмеченных is_cover фото). Если ни одна не отмечена — первое фото."""
    covers = [b for b in blocks if b.get("type") == "photo" and b.get("is_cover") and b.get("url")][:3]
    if not covers:
        first = next((b for b in blocks if b.get("type") == "photo" and b.get("url")), None)
        return [first["url"]] if first else []
    return [c["url"] for c in covers]



_LINK_RE = re.compile(r'\[([^\]]+)\]\((https?://[^)\s]+)\)')
_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')
_ITALIC_RE = re.compile(r'__([^_]+)__')


def _caption_html(text: str) -> str:
    """Конвертирует лёгкий markdown подписи в Telegram-HTML: скрытые ссылки, жирный, курсив.

    [Надпись](https://ссылка) → <a href="...">Надпись</a> (ссылка спрятана за текстом).
    """
    if not text:
        return ""
    t = _html.escape(text, quote=False)
    t = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', t)
    t = _BOLD_RE.sub(lambda m: f'<b>{m.group(1)}</b>', t)
    t = _ITALIC_RE.sub(lambda m: f'<i>{m.group(1)}</i>', t)
    return t


def _publish_caption(post: dict) -> str:
    photos_url = post.get("photos_url")
    videos_url = post.get("videos_url")
    pc = post.get("photo_count") or 0
    vc = post.get("video_count") or 0
    blocks = post.get("blocks", [])
    desc = next((b.get("value", "") for b in blocks if b.get("type") == "text"), "")

    links = []
    if photos_url and pc > 1:
        links.append(f"📷 Фото ({pc}): {photos_url}")
    if videos_url and vc > 0:
        links.append(f"🎬 Видео ({vc}): {videos_url}")
    if not links and not photos_url and not videos_url and post.get("telegraph_url"):
        links.append(post["telegraph_url"])

    def plain(d):
        parts = [post["title"]]
        if d:
            parts += ["", d]
        if links:
            parts += [""] + links
        if post.get("hashtags"):
            parts += ["", " ".join(post["hashtags"])]
        return "\n".join(parts)

    # обрезаем описание по «сырой» длине, чтобы не сломать HTML-теги
    if len(plain(desc)) > 1024 and desc:
        overflow = len(plain(desc)) - 1024 + 1
        desc = desc[:max(0, len(desc) - overflow)].rstrip() + "…"

    parts = [f"<b>{_html.escape(post['title'], quote=False)}</b>"]
    if desc:
        parts += ["", _caption_html(desc)]
    if links:
        parts += [""] + [_caption_html(l) for l in links]
    if post.get("hashtags"):
        parts += ["", " ".join(post["hashtags"])]
    return "\n".join(parts)


def _channel_post_url(channel: dict, message_id) -> Optional[str]:
    """Ссылка на сообщение в канале: t.me/username/id или t.me/c/internal/id."""
    if not message_id or not channel:
        return None
    uname = channel.get("channel_username")
    if uname:
        return f"https://t.me/{uname}/{message_id}"
    cid = str(channel.get("channel_id") or "")
    if cid.startswith("-100"):
        return f"https://t.me/c/{cid[4:]}/{message_id}"
    return None


async def _do_publish(post: dict, channel: dict):
    caption = _publish_caption(post)
    cover_urls = (post.get("cover_urls") or ([post["cover_url"]] if post.get("cover_url") else []))[:3]
    # 2-3 обложки → альбом (media group) с подписью на первом
    if len(cover_urls) >= 2:
        try:
            msgs = await telegram_api.send_photo_album(channel["channel_id"], cover_urls, caption)
            return [(m or {}).get("message_id") for m in (msgs or [])]
        except Exception as e:
            logger.warning("cover album failed, fallback to single/message: %s", e)
    if cover_urls:
        try:
            res = await telegram_api.send_photo(channel["channel_id"], cover_urls[0], caption)
        except Exception as e:
            logger.warning("sendPhoto failed, fallback to sendMessage: %s", e)
            res = await telegram_api.send_message(channel["channel_id"], caption)
    else:
        res = await telegram_api.send_message(channel["channel_id"], caption)
    mid = (res or {}).get("message_id")
    return [mid] if mid else []


def _native_caption(post: dict) -> str:
    blocks = post.get("blocks", [])
    desc = next((b.get("value", "") for b in blocks if b.get("type") == "text"), "")
    hashtags = post.get("hashtags") or []
    title = (post.get("title") or "").strip()

    def plain(d):
        parts = [title] if title else []
        if d:
            parts += (["", d] if parts else [d])
        if hashtags:
            parts += ["", " ".join(hashtags)] if parts else [" ".join(hashtags)]
        return "\n".join(parts)

    if len(plain(desc)) > 1024 and desc:
        overflow = len(plain(desc)) - 1024 + 1
        desc = desc[:max(0, len(desc) - overflow)].rstrip() + "…"

    parts = [f"<b>{_html.escape(title, quote=False)}</b>"] if title else []
    if desc:
        parts += (["", _caption_html(desc)] if parts else [_caption_html(desc)])
    if hashtags:
        parts += (["", " ".join(hashtags)] if parts else [" ".join(hashtags)])
    return "\n".join(parts)


async def _do_publish_native(post: dict, channel: dict):
    """Публикует нативный пост — альбом(ы) прямо в канал (медиа по 10 в группе).

    Медиа скачивается с R2 во временный файл и отправляется multipart-ом (InputFile),
    что обходит лимит Telegram в 20 МБ при загрузке по URL. Для файлов > 50 МБ
    нужен Local Bot API Server (TELEGRAM_LOCAL_API_URL) — до 2 ГБ.
    """
    blocks = post.get("blocks", [])
    _t, photos, videos, cover = _split_media(blocks)
    items = photos + videos  # cover уже первым среди photos (см. _split_media)
    if not items:
        raise ValueError("Нет медиа для публикации")
    caption = _native_caption(post)
    chat_id = channel["channel_id"]
    msg_ids = []
    tmp_paths = []
    thumb_paths = []
    try:
        # скачиваем все медиа во временные файлы (+ обложка/метаданные для видео)
        prepared = []  # [{type, path, filename, mime, (video) thumb/width/height/duration}]
        for b in items:
            url = b.get("url")
            if not url:
                raise ValueError("У медиа нет ссылки на файл")
            path = await telegram_api._download_to_temp(url)
            tmp_paths.append(path)
            filename, mime = telegram_api._guess(b["type"], url)
            item = {"type": b["type"], "path": path, "filename": filename, "mime": mime}
            if b["type"] == "video":
                fast = await telegram_api.remux_faststart(path)
                if fast:
                    tmp_paths.append(fast)
                    item["path"] = fast
                src = item["path"]
                dur, w, h = await telegram_api.probe_video(src)
                thumb = await telegram_api.extract_thumb(src)
                if thumb:
                    thumb_paths.append(thumb)
                item.update({"duration": dur, "width": w, "height": h, "thumb": thumb})
                logger.info(
                    "native video prep: faststart=%s thumb=%s dur=%s size=%sx%s file=%s",
                    bool(fast), bool(thumb), dur, w, h, filename,
                )
            prepared.append(item)

        # разбиваем на альбомы по 10
        chunks = [prepared[i:i + 10] for i in range(0, len(prepared), 10)]
        for ci, chunk in enumerate(chunks):
            cap = caption if ci == 0 else ""
            if len(chunk) == 1:
                b = chunk[0]
                if b["type"] == "photo":
                    res = await telegram_api.send_photo_file(chat_id, b["path"], b["filename"], cap)
                else:
                    res = await telegram_api.send_video_file(
                        chat_id, b["path"], b["filename"], cap,
                        thumb=b.get("thumb"), width=b.get("width"),
                        height=b.get("height"), duration=b.get("duration"),
                    )
                msg_ids.append(res.get("message_id"))
            else:
                if cap:
                    chunk[0]["caption"] = cap
                res = await telegram_api.send_media_group_files(chat_id, chunk)
                msg_ids += [m.get("message_id") for m in res]
        return msg_ids
    finally:
        for p in tmp_paths + thumb_paths:
            try:
                os.unlink(p)
            except Exception:
                pass


async def _finalize_native(post_id: str):
    post = await db.posts.find_one({"id": post_id})
    if not post or post.get("status") not in ("uploading", "processing"):
        return
    blocks = post.get("blocks", [])
    _t, photos, videos, cover = _split_media(blocks)
    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    upd = {
        "telegraph_url": None,
        "telegraph_path": None,
        "photos_url": None,
        "videos_url": None,
        "cover_url": cover["url"] if cover else None,
        "cover_urls": _cover_urls(blocks),
        "media_ids": media_ids,
        "status": "ready",
    }
    published = False
    channel_title = None
    if post.get("publish_after"):
        channel = await _resolve_channel({**post, **upd})
        if channel:
            try:
                msg_ids = await _do_publish_native({**post, **upd}, channel)
                published = True
                channel_title = channel.get("channel_title")
                upd["channel_message_ids"] = msg_ids
                upd["channel_message_id"] = msg_ids[0] if msg_ids else None
                upd["channel_post_url"] = _channel_post_url(channel, msg_ids[0] if msg_ids else None)
                upd["status"] = "published"
            except Exception as e:
                logger.warning("native auto-publish failed: %s", e)
                upd["error"] = f"Публикация не удалась: {e}"
    upd["published"] = published
    upd["channel_title"] = channel_title
    await db.posts.update_one({"id": post_id}, {"$set": upd})
    await _maybe_auto_enqueue(post_id)


async def _maybe_auto_enqueue(post_id: str):
    """Авто-постановка в очередь, если у целевого канала поста включён auto_enqueue."""
    post = await db.posts.find_one({"id": post_id}, {"status": 1, "published": 1, "in_queue": 1, "scheduled_at": 1, "channel_ref": 1})
    if not post or post.get("status") != "ready" or post.get("published") or post.get("in_queue") or post.get("scheduled_at"):
        return
    channel = await _resolve_channel(post)
    if not (channel and channel.get("auto_enqueue")):
        return
    ref = channel["id"]
    order = await _next_queue_order(ref)
    await db.posts.update_one({"id": post_id}, {"$set": {"in_queue": True, "queue_order": order, "channel_ref": ref}})


async def _store_bytes(content: bytes, ctype: str, kind: str, filename: str):
    ext = os.path.splitext(filename or "")[1] or (".mp4" if kind == "video" else ".jpg")
    if kind == "photo" and ctype == "image/jpeg":
        ext = ".jpg"
    if storage.r2_enabled():
        key = f"{kind}/{uuid.uuid4()}{ext}"
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(content)
        tmp.close()
        try:
            url = await asyncio.to_thread(storage.upload_file, tmp.name, key, ctype)
        finally:
            os.unlink(tmp.name)
        return url, None, key
    bucket = get_gridfs()
    oid = await bucket.upload_from_stream(filename or kind, content, metadata={"content_type": ctype})
    return f"{BASE_URL}/api/media/{oid}", str(oid), None


async def _stream_to_temp(file: UploadFile) -> tuple[str, int]:
    """Stream an upload to a temp file in chunks (avoids holding big files in RAM)."""
    tmp = tempfile.NamedTemporaryFile(delete=False)
    size = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)
            size += len(chunk)
    finally:
        tmp.close()
    return tmp.name, size


async def _store_temp(path: str, ctype: str, kind: str, filename: str):
    ext = os.path.splitext(filename or "")[1] or (".mp4" if kind == "video" else ".jpg")
    if storage.r2_enabled():
        key = f"{kind}/{uuid.uuid4()}{ext}"
        url = await asyncio.to_thread(storage.upload_file, path, key, ctype)
        return url, None, key
    bucket = get_gridfs()
    with open(path, "rb") as f:
        oid = await bucket.upload_from_stream(filename or kind, f, metadata={"content_type": ctype})
    return f"{BASE_URL}/api/media/{oid}", str(oid), None


async def _finalize_post(post_id: str):
    post = await db.posts.find_one({"id": post_id})
    if not post or post.get("status") not in ("uploading", "processing"):
        return
    if post.get("post_type") == "native":
        await _finalize_native(post_id)
        return
    blocks = post.get("blocks", [])
    text_blocks, photos, videos, cover = _split_media(blocks)
    photos_url = photos_path = videos_url = videos_path = None
    photos_paths = videos_paths = []
    try:
        # Статья с фото (или текстовая, если медиа нет вовсе). Текст идёт в фото-статью.
        if photos or not videos:
            photos_url, photos_paths = await create_paginated_page(post["title"], text_blocks + photos, BASE_URL)
        # Отдельная статья с видео (по 10 медиа на страницу — видео тяжело грузятся).
        if videos:
            vcontent = videos if photos else (text_blocks + videos)
            videos_url, videos_paths = await create_paginated_page(post["title"], vcontent, BASE_URL, max_items=10)
    except Exception as e:
        logger.exception("finalize telegraph failed")
        err = str(e)
        if "flood" in err.lower():
            m = re.search(r"retry in (\d+)", err, re.I)
            secs = m.group(1) if m else "несколько"
            err = f"Telegraph ограничил создание статей (flood). Подождите ~{secs} сек и нажмите «Повторить»."
        await db.posts.update_one({"id": post_id}, {"$set": {"status": "failed", "error": err}})
        return
    photos_path = photos_paths[0] if photos_paths else None
    videos_path = videos_paths[0] if videos_paths else None
    primary_url = photos_url or videos_url
    primary_path = photos_path or videos_path
    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    upd = {
        "telegraph_url": primary_url,
        "telegraph_path": primary_path,
        "photos_url": photos_url,
        "photos_path": photos_path,
        "photos_paths": photos_paths,
        "videos_url": videos_url,
        "videos_path": videos_path,
        "videos_paths": videos_paths,
        "cover_url": cover["url"] if cover else None,
        "cover_urls": _cover_urls(blocks),
        "media_ids": media_ids,
        "status": "ready",
    }
    published = False
    channel_title = None
    if post.get("publish_after"):
        merged = {**post, **upd}
        channel = await _resolve_channel(merged)
        if channel:
            try:
                msg_ids = await _do_publish(merged, channel)
                published = True
                channel_title = channel.get("channel_title")
                upd["channel_message_ids"] = msg_ids
                upd["channel_message_id"] = msg_ids[0] if msg_ids else None
                upd["channel_post_url"] = _channel_post_url(channel, msg_ids[0] if msg_ids else None)
                upd["status"] = "published"
            except Exception as e:
                logger.warning("auto-publish failed: %s", e)
                upd["error"] = f"Публикация не удалась: {e}"
    upd["published"] = published
    upd["channel_title"] = channel_title
    await db.posts.update_one({"id": post_id}, {"$set": upd})
    await _maybe_auto_enqueue(post_id)


@api_router.post("/posts/draft")
async def create_draft(payload: DraftIn, user=Depends(auth.get_current_user)):
    post_type = payload.post_type if payload.post_type in ("telegraph", "native") else "telegraph"
    if post_type == "telegraph" and not payload.title.strip():
        raise HTTPException(status_code=400, detail="Укажите заголовок для Telegraph-статьи")
    tags = _normalize_tags(payload.hashtags)
    desc_text = (payload.description or "").strip()
    blocks = []
    if desc_text:
        blocks.append({"type": "text", "value": desc_text})
    slots = []
    photo_count = video_count = 0
    for m in payload.media:
        idx = len(blocks)
        blocks.append({
            "type": m.kind, "is_cover": m.is_cover, "caption": m.caption or "",
            "url": None, "media_id": None, "pending": True,
        })
        slots.append(idx)
        if m.kind == "photo":
            photo_count += 1
        elif m.kind == "video":
            video_count += 1
    post_id = str(uuid.uuid4())
    doc = {
        "id": post_id,
        "user_id": user["id"],
        "title": payload.title.strip(),
        "telegraph_url": None,
        "telegraph_path": None,
        "cover_url": None,
        "blocks": blocks,
        "hashtags": tags,
        "media_ids": [],
        "r2_keys": [],
        "media_count": len(slots),
        "photo_count": photo_count,
        "video_count": video_count,
        "media_total": len(slots),
        "media_done": 0,
        "block_count": len(blocks),
        "preview": (desc_text or "")[:200],
        "publish_after": payload.publish_after,
        "published": False,
        "channel_title": None,
        "channel_message_id": None,
        "post_type": post_type,
        "status": "uploading" if slots else "processing",
        "scheduled_at": None,
        "in_queue": False,
        "queue_order": None,
        "channel_ref": payload.channel_ref,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.posts.insert_one(doc)
    if not slots:
        await _finalize_post(post_id)
    return {"id": post_id, "slots": slots}


async def _process_upload(file: UploadFile, expected_kind: str = None):
    """Валидирует и сохраняет загруженный файл. Возвращает (kind, url, media_id, r2_key)."""
    ctype = file.content_type or "application/octet-stream"
    name = (file.filename or "").lower()
    file_kind = "video" if ctype.startswith("video") else ("photo" if ctype.startswith("image") else None)
    if file_kind is None:
        if name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp", ".tiff")):
            file_kind = "photo"
        elif name.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg")):
            file_kind = "video"
    if file_kind is None:
        raise HTTPException(status_code=400, detail=f"Неизвестный тип файла «{file.filename or ctype}»")
    if expected_kind and file_kind != expected_kind:
        expected = "видео" if expected_kind == "video" else "изображение"
        raise HTTPException(status_code=400, detail=f"Ожидается {expected}, а получен файл «{file.filename or ctype}»")

    if file_kind == "photo":
        content = await file.read()
        if len(content) > 25 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Изображение больше 25 МБ")
        content, ctype = await asyncio.to_thread(watermark.ensure_web_format, content, ctype, file.filename or "")
        wm = await db.app_config.find_one({"_id": "watermark"})
        if wm and wm.get("enabled"):
            content = await asyncio.to_thread(watermark.apply_watermark, content, wm)
            ctype = "image/jpeg"
        url, media_id, r2_key = await _store_bytes(content, ctype, "photo", file.filename or "")
    else:
        path, size = await _stream_to_temp(file)
        if size > 5 * 1024 * 1024 * 1024:
            os.unlink(path)
            raise HTTPException(status_code=400, detail="Видео больше 5 ГБ")
        try:
            url, media_id, r2_key = await _store_temp(path, ctype, "video", file.filename or "")
        finally:
            os.unlink(path)
    return file_kind, url, media_id, r2_key


@api_router.post("/posts/{post_id}/media/{idx}")
async def upload_media_slot(post_id: str, idx: int, file: UploadFile = File(...), user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    blocks = post.get("blocks", [])
    if idx < 0 or idx >= len(blocks) or blocks[idx]["type"] not in ("photo", "video"):
        raise HTTPException(status_code=400, detail="Неверный слот")

    slot_kind = blocks[idx]["type"]
    _kind, url, media_id, r2_key = await _process_upload(file, expected_kind=slot_kind)

    set_fields = {f"blocks.{idx}.url": url, f"blocks.{idx}.pending": False}
    if media_id:
        set_fields[f"blocks.{idx}.media_id"] = media_id
    if r2_key:
        set_fields[f"blocks.{idx}.r2_key"] = r2_key
    update = {"$set": set_fields, "$inc": {"media_done": 1}}
    if r2_key:
        update["$push"] = {"r2_keys": r2_key}
    await db.posts.update_one({"id": post_id}, update)

    updated = await db.posts.find_one({"id": post_id})
    if updated["media_done"] >= updated["media_total"]:
        # Атомарно захватываем финализацию, чтобы её запустил ровно один загрузчик
        gate = await db.posts.find_one_and_update(
            {"id": post_id, "status": "uploading"},
            {"$set": {"status": "processing"}},
        )
        if gate:
            await _finalize_post(post_id)
    out = await db.posts.find_one({"id": post_id}, {"_id": 0, "blocks": 0})
    return out


@api_router.post("/posts/{post_id}/media")
async def upload_edit_media(post_id: str, file: UploadFile = File(...), user=Depends(auth.get_current_user)):
    """Загружает новый файл при редактировании поста. Не привязывает к посту —
    возвращает метаданные, которые фронтенд шлёт в PUT /posts/{id} (new_media)."""
    post = await db.posts.find_one({"id": post_id}, {"_id": 1})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    kind, url, media_id, r2_key = await _process_upload(file)
    return {"kind": kind, "url": url, "media_id": media_id, "r2_key": r2_key}


async def _publish_and_store(post: dict) -> dict:
    """Публикует готовый пост (native/telegraph) и сохраняет результат в БД.

    Бросает ValueError при проблемах. Возвращает channel_title.
    """
    if post.get("status") in ("uploading", "processing", "failed"):
        raise ValueError("Пост ещё создаётся")
    channel = await _resolve_channel(post)
    if not channel:
        raise ValueError("Канал не настроен")
    if post.get("post_type") == "native":
        msg_ids = await _do_publish_native(post, channel)
        set_fields = {"channel_message_ids": msg_ids, "channel_message_id": msg_ids[0] if msg_ids else None,
                      "channel_post_url": _channel_post_url(channel, msg_ids[0] if msg_ids else None)}
    else:
        if not post.get("telegraph_url"):
            raise ValueError("Статья ещё создаётся")
        msg_ids = await _do_publish(post, channel)
        set_fields = {"channel_message_ids": msg_ids, "channel_message_id": msg_ids[0] if msg_ids else None,
                      "channel_post_url": _channel_post_url(channel, msg_ids[0] if msg_ids else None)}
    set_fields.update({
        "published": True,
        "status": "published",
        "channel_title": channel.get("channel_title"),
        "channel_ref": channel["id"],
        "scheduled_at": None,
        "in_queue": False,
        "error": None,
    })
    await db.posts.update_one({"id": post["id"]}, {"$set": set_fields})
    return channel.get("channel_title")


@api_router.post("/posts/{post_id}/publish")
async def publish_post(post_id: str, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.get("status") in ("uploading", "processing", "failed"):
        raise HTTPException(status_code=400, detail="Пост ещё создаётся, подождите")
    channel = await _resolve_channel(post)
    if not channel:
        raise HTTPException(status_code=400, detail="Сначала настройте канал в настройках")
    try:
        channel_title = await _publish_and_store(post)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка публикации: {e}")
    return {"status": "published", "channel_title": channel_title}


PUBLISH_ALL_PAUSE = 5  # пауза между постами при массовой публикации (анти-флуд)


async def _publish_all_task(ids: list):
    for pid in ids:
        post = await db.posts.find_one({"id": pid})
        if not post or post.get("published") or post.get("status") != "ready":
            continue
        try:
            await _publish_and_store(post)
            logger.info("publish-all: published %s", pid)
        except Exception as e:
            logger.warning("publish-all failed %s: %s", pid, e)
            await db.posts.update_one({"id": pid}, {"$set": {"error": f"Массовая публикация: {e}"}})
        await asyncio.sleep(PUBLISH_ALL_PAUSE)


@api_router.post("/posts/publish-all")
async def publish_all(user=Depends(auth.get_current_user)):
    channel = await db.app_config.find_one({"_id": "channel"})
    if not channel:
        raise HTTPException(status_code=400, detail="Сначала настройте канал в настройках")
    rows = await db.posts.find(
        {"status": "ready", "published": {"$ne": True}, "scheduled_at": None},
        {"id": 1},
    ).sort("created_at", 1).to_list(2000)
    ids = [r["id"] for r in rows]
    if not ids:
        raise HTTPException(status_code=400, detail="Нет готовых постов для публикации")
    asyncio.create_task(_publish_all_task(ids))
    return {"started": len(ids)}


def _parse_scheduled(s: str) -> str:
    """Парсит входящую дату-время (ISO, UTC) → нормализованный UTC isoformat. Бросает ValueError."""
    from datetime import datetime as _dt
    raw = (s or "").strip()
    if not raw:
        raise ValueError("Не указано время")
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = _dt.fromisoformat(raw)
    except Exception:
        raise ValueError("Неверный формат даты-времени")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


@api_router.post("/posts/{post_id}/schedule")
async def schedule_post(post_id: str, payload: ScheduleIn, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id}, {"status": 1, "published": 1})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.get("status") not in ("ready", "published"):
        raise HTTPException(status_code=400, detail="Пост ещё создаётся")
    if not payload.scheduled_at:
        # снять расписание
        await db.posts.update_one({"id": post_id}, {"$set": {"scheduled_at": None}})
        return {"status": "unscheduled"}
    try:
        iso = _parse_scheduled(payload.scheduled_at)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    fields = {"scheduled_at": iso, "in_queue": False, "published": False, "status": "ready"}
    if payload.channel_ref:
        fields["channel_ref"] = payload.channel_ref
    await db.posts.update_one({"id": post_id}, {"$set": fields})
    return {"status": "scheduled", "scheduled_at": iso}


@api_router.post("/posts/{post_id}/queue")
async def queue_post(post_id: str, payload: QueueIn, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id}, {"status": 1, "channel_ref": 1})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.get("status") not in ("ready", "published"):
        raise HTTPException(status_code=400, detail="Пост ещё создаётся")
    if payload.in_queue:
        ref = payload.channel_ref or post.get("channel_ref")
        if not ref:
            ch = await db.channels.find_one({}, sort=[("created_at", 1)])
            if not ch:
                raise HTTPException(status_code=400, detail="Сначала добавьте канал")
            ref = ch["id"]
        order = await _next_queue_order(ref)
        await db.posts.update_one(
            {"id": post_id},
            {"$set": {"in_queue": True, "queue_order": order, "channel_ref": ref,
                      "scheduled_at": None, "published": False, "status": "ready"}},
        )
    else:
        await db.posts.update_one({"id": post_id}, {"$set": {"in_queue": False, "queue_order": None}})
    return {"status": "ok", "in_queue": payload.in_queue}


# ── Мультиканальность: управление каналами и их планами ──

async def _channel_out(ch: dict) -> dict:
    qcount = await db.posts.count_documents({"in_queue": True, "channel_ref": ch["id"], "published": {"$ne": True}})
    return {
        "id": ch["id"], "channel_id": ch.get("channel_id"), "channel_title": ch.get("channel_title"),
        "channel_username": ch.get("channel_username"), "enabled": bool(ch.get("enabled")),
        "interval_minutes": int(ch.get("interval_minutes") or 60), "auto_enqueue": bool(ch.get("auto_enqueue")),
        "next_run_at": ch.get("next_run_at"), "queue_count": qcount,
    }


@api_router.get("/channels")
async def list_channels(user=Depends(auth.get_current_user)):
    await _migrate_channels()
    chans = await db.channels.find({}).sort("created_at", 1).to_list(100)
    return {"channels": [await _channel_out(c) for c in chans]}


@api_router.post("/channels")
async def add_channel(payload: ChannelIn, user=Depends(auth.get_current_user)):
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise HTTPException(status_code=400, detail="Не задан TELEGRAM_BOT_TOKEN на сервере")
    try:
        chat = await telegram_api.get_chat(payload.identifier.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось получить канал: {e}. Бот должен быть админом.")
    existing = await db.channels.find_one({"channel_id": chat["id"]})
    if existing:
        raise HTTPException(status_code=400, detail="Этот канал уже добавлен")
    title = chat.get("title") or chat.get("username") or str(chat.get("id"))
    ch = {
        "id": str(uuid.uuid4()), "channel_id": chat["id"], "channel_title": title,
        "channel_username": chat.get("username"), "enabled": False, "interval_minutes": 60,
        "auto_enqueue": False, "next_run_at": None, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.channels.insert_one(ch)
    return await _channel_out(ch)


@api_router.put("/channels/{ch_id}")
async def update_channel(ch_id: str, payload: ChannelSchedulerIn, user=Depends(auth.get_current_user)):
    ch = await db.channels.find_one({"id": ch_id})
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден")
    interval = max(1, int(payload.interval_minutes))
    upd = {"enabled": bool(payload.enabled), "interval_minutes": interval, "auto_enqueue": bool(payload.auto_enqueue)}
    upd["next_run_at"] = (datetime.now(timezone.utc) + timedelta(minutes=interval)).isoformat() if payload.enabled else None
    await db.channels.update_one({"id": ch_id}, {"$set": upd})
    return await _channel_out({**ch, **upd})


@api_router.delete("/channels/{ch_id}")
async def delete_channel(ch_id: str, user=Depends(auth.get_current_user)):
    await db.channels.delete_one({"id": ch_id})
    await db.posts.update_many({"channel_ref": ch_id, "in_queue": True}, {"$set": {"in_queue": False, "queue_order": None}})
    return {"status": "ok"}


@api_router.get("/channels/{ch_id}/queue")
async def channel_queue(ch_id: str, user=Depends(auth.get_current_user)):
    queue = await db.posts.find(
        {"in_queue": True, "channel_ref": ch_id, "published": {"$ne": True}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "queue_order": 1, "photo_count": 1, "video_count": 1, "cover_url": 1},
    ).sort("queue_order", 1).to_list(500)
    return {"queue": queue, "queue_count": len(queue)}


@api_router.put("/channels/{ch_id}/queue")
async def reorder_channel_queue(ch_id: str, payload: QueueOrderIn, user=Depends(auth.get_current_user)):
    for i, pid in enumerate(payload.order):
        await db.posts.update_one({"id": pid, "in_queue": True, "channel_ref": ch_id}, {"$set": {"queue_order": i + 1}})
    return {"status": "ok"}


@api_router.post("/channels/{ch_id}/publish-all")
async def channel_publish_all(ch_id: str, user=Depends(auth.get_current_user)):
    ch = await db.channels.find_one({"id": ch_id})
    if not ch:
        raise HTTPException(status_code=404, detail="Канал не найден")
    rows = await db.posts.find(
        {"status": "ready", "published": {"$ne": True}, "scheduled_at": None, "channel_ref": ch_id},
        {"id": 1},
    ).sort([("in_queue", -1), ("queue_order", 1), ("created_at", 1)]).to_list(2000)
    ids = [r["id"] for r in rows]
    if not ids:
        raise HTTPException(status_code=400, detail="Нет готовых постов для этого канала")
    asyncio.create_task(_publish_all_task(ids))
    return {"started": len(ids)}


@api_router.delete("/posts/{post_id}")
async def delete_post(post_id: str, delete_channel: bool = False, delete_media: bool = True, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if delete_channel:
        msg_ids = post.get("channel_message_ids") or ([post["channel_message_id"]] if post.get("channel_message_id") else [])
        if msg_ids:
            channel = await _resolve_channel(post)
            if channel:
                for mid in msg_ids:
                    try:
                        await telegram_api.delete_message(channel["channel_id"], mid)
                    except Exception as e:
                        logger.warning("delete channel message failed: %s", e)
            else:
                logger.warning("delete channel message skipped: канал не найден для поста %s", post_id)
    if delete_media:
        bucket = get_gridfs()
        for mid in post.get("media_ids", []):
            try:
                await bucket.delete(ObjectId(mid))
            except Exception:
                pass
        if storage.r2_enabled():
            for key in post.get("r2_keys", []):
                try:
                    await asyncio.to_thread(storage.delete_file, key)
                except Exception:
                    logger.warning("R2 delete failed for key %s", key)
    await db.posts.delete_one({"id": post_id})
    return {"status": "deleted"}


@api_router.get("/posts/{post_id}/edit")
async def get_post_for_edit(post_id: str, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.get("post_type") != "native" and not post.get("telegraph_path"):
        raise HTTPException(status_code=400, detail="Статья ещё создаётся, редактирование недоступно")
    blocks = post.get("blocks", [])
    media = [
        {"idx": i, "kind": b["type"], "url": b.get("url"), "caption": b.get("caption", ""), "is_cover": bool(b.get("is_cover"))}
        for i, b in enumerate(blocks) if b["type"] in ("photo", "video")
    ]
    raw_text = next((b.get("value", "") for b in blocks if b["type"] == "text"), "")
    tags = post.get("hashtags", [])
    tagline = " ".join(tags)
    description = raw_text[:-len(tagline)].rstrip() if tagline and raw_text.endswith(tagline) else raw_text
    return {
        "id": post["id"],
        "title": post["title"],
        "description": description,
        "hashtags": tags,
        "post_type": post.get("post_type", "telegraph"),
        "telegraph_url": post.get("telegraph_url"),
        "channel_ref": post.get("channel_ref"),
        "media": media,
    }


@api_router.put("/posts/{post_id}")
async def edit_post(post_id: str, payload: PostEditIn, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if post.get("post_type") != "native" and not payload.title.strip():
        raise HTTPException(status_code=400, detail="Укажите заголовок")
    if post.get("post_type") != "native" and not post.get("telegraph_path"):
        raise HTTPException(status_code=400, detail="Статья ещё создаётся, редактирование недоступно")
    blocks = post.get("blocks", [])
    kept = {m.idx: m for m in payload.media}

    new_blocks = []
    removed_media_ids, removed_r2_keys = [], []
    for i, b in enumerate(blocks):
        if b["type"] in ("photo", "video"):
            if i in kept:
                b["caption"] = kept[i].caption or ""
                b["is_cover"] = bool(kept[i].is_cover)
                new_blocks.append(b)
            else:
                if b.get("media_id"):
                    removed_media_ids.append(b["media_id"])
                if b.get("r2_key"):
                    removed_r2_keys.append(b["r2_key"])
        else:
            new_blocks.append(b)
    blocks = new_blocks

    # Добавляем новые медиа (загружены заранее через POST /posts/{id}/media)
    for nm in payload.new_media:
        if nm.kind not in ("photo", "video") or not nm.url:
            continue
        blocks.append({
            "type": nm.kind,
            "is_cover": bool(nm.is_cover),
            "caption": nm.caption or "",
            "url": nm.url,
            "media_id": nm.media_id,
            "r2_key": nm.r2_key,
            "pending": False,
        })

    tags = _normalize_tags(payload.hashtags)
    desc = (payload.description or "").strip()
    text_idx = next((i for i, b in enumerate(blocks) if b["type"] == "text"), None)
    if text_idx is not None:
        if desc:
            blocks[text_idx]["value"] = desc
        else:
            blocks.pop(text_idx)
    elif desc:
        blocks.insert(0, {"type": "text", "value": desc})

    text_blocks, photos, videos, cover = _split_media(blocks)
    title = payload.title.strip()

    async def _cleanup_removed():
        if removed_media_ids or removed_r2_keys:
            bucket = get_gridfs()
            for mid in removed_media_ids:
                try:
                    await bucket.delete(ObjectId(mid))
                except Exception:
                    pass
            if storage.r2_enabled():
                for key in removed_r2_keys:
                    try:
                        await asyncio.to_thread(storage.delete_file, key)
                    except Exception:
                        logger.warning("R2 delete failed for key %s", key)

    # Нативный пост — без Telegraph, только обновляем данные и чистим удалённые файлы
    if post.get("post_type") == "native":
        media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
        r2_keys = [b["r2_key"] for b in blocks if b.get("r2_key")]
        await db.posts.update_one(
            {"id": post_id},
            {"$set": {
                "title": title,
                "blocks": blocks,
                "hashtags": tags,
                "channel_ref": payload.channel_ref or post.get("channel_ref"),
                "cover_url": cover["url"] if cover else None,
                "cover_urls": _cover_urls(blocks),
                "media_ids": media_ids,
                "r2_keys": r2_keys,
                "photo_count": len(photos),
                "video_count": len(videos),
                "media_count": len(photos) + len(videos),
                "preview": desc[:200],
            }},
        )
        await _cleanup_removed()
        return {"status": "updated"}

    photos_url, photos_paths = post.get("photos_url"), post.get("photos_paths") or ([post["photos_path"]] if post.get("photos_path") else [])
    videos_url, videos_paths = post.get("videos_url"), post.get("videos_paths") or ([post["videos_path"]] if post.get("videos_path") else [])
    title = payload.title.strip()
    try:
        if photos_paths or videos_paths:
            # Текст идёт в фото-статью, если фото есть; иначе — в видео-статью.
            pcontent = (text_blocks + photos) if photos else []
            vcontent = (videos if photos else text_blocks + videos) if videos else []
            # Фото-статья: правим существующую или создаём новую (если фото добавили впервые).
            if photos:
                if photos_paths:
                    photos_url, photos_paths = await edit_paginated_page(photos_paths, title, pcontent, BASE_URL)
                else:
                    photos_url, photos_paths = await create_paginated_page(title, pcontent, BASE_URL)
            else:
                photos_url, photos_paths = None, []
            # Видео-статья: аналогично.
            if videos:
                if videos_paths:
                    videos_url, videos_paths = await edit_paginated_page(videos_paths, title, vcontent, BASE_URL, max_items=10)
                else:
                    videos_url, videos_paths = await create_paginated_page(title, vcontent, BASE_URL, max_items=10)
            else:
                videos_url, videos_paths = None, []
        else:
            # Легаси-пост с единственной статьёй
            ordered = ([cover] + [b for b in blocks if b is not cover]) if cover else blocks
            photos_url, photos_paths = await edit_paginated_page([post["telegraph_path"]], title, ordered, BASE_URL)
    except Exception as e:
        logger.exception("edit telegraph failed")
        raise HTTPException(status_code=500, detail=f"Ошибка Telegraph: {e}")

    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    r2_keys = [b["r2_key"] for b in blocks if b.get("r2_key")]
    await db.posts.update_one(
        {"id": post_id},
        {"$set": {
            "title": title,
            "blocks": blocks,
            "hashtags": tags,
            "channel_ref": payload.channel_ref or post.get("channel_ref"),
            "telegraph_url": photos_url or videos_url,
            "telegraph_path": (photos_paths or videos_paths or [None])[0],
            "photos_url": photos_url,
            "photos_path": photos_paths[0] if photos_paths else None,
            "photos_paths": photos_paths,
            "videos_url": videos_url,
            "videos_path": videos_paths[0] if videos_paths else None,
            "videos_paths": videos_paths,
            "cover_url": cover["url"] if cover else None,
            "cover_urls": _cover_urls(blocks),
            "media_ids": media_ids,
            "r2_keys": r2_keys,
            "photo_count": len(photos),
            "video_count": len(videos),
            "media_count": len(photos) + len(videos),
            "preview": desc[:200],
        }},
    )

    # Удаляем файлы убранных медиа с хостинга
    await _cleanup_removed()

    return {"status": "updated", "telegraph_url": photos_url or videos_url}


# ---------- Upload ----------
@api_router.post("/upload")
async def upload(file: UploadFile = File(...), user=Depends(auth.get_current_user)):
    content = await file.read()
    ctype = file.content_type or "application/octet-stream"
    kind = "video" if ctype.startswith("video") else "photo"

    # Водяной знак — только для фото
    if kind == "photo":
        wm = await db.app_config.find_one({"_id": "watermark"})
        if wm and wm.get("enabled"):
            content = await asyncio.to_thread(watermark.apply_watermark, content, wm)
            ctype = "image/jpeg"

    ext = os.path.splitext(file.filename or "")[1] or (".mp4" if kind == "video" else ".jpg")
    if kind == "photo" and ctype == "image/jpeg":
        ext = ".jpg"

    if storage.r2_enabled():
        key = f"{kind}/{uuid.uuid4()}{ext}"
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp.write(content)
        tmp.close()
        try:
            url = await asyncio.to_thread(storage.upload_file, tmp.name, key, ctype)
        finally:
            os.unlink(tmp.name)
        return {"url": url, "type": kind}

    bucket = get_gridfs()
    oid = await bucket.upload_from_stream(
        file.filename or kind, content, metadata={"content_type": ctype}
    )
    return {"url": f"{BASE_URL}/api/media/{oid}", "media_id": str(oid), "type": kind}


# ---------- Media (public, so Telegraph can fetch when using GridFS) ----------
@api_router.get("/media/{media_id}")
async def get_media(media_id: str):
    bucket = get_gridfs()
    try:
        stream = await bucket.open_download_stream(ObjectId(media_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Media not found")
    data = await stream.read()
    content_type = "application/octet-stream"
    if stream.metadata and stream.metadata.get("content_type"):
        content_type = stream.metadata["content_type"]
    return Response(content=data, media_type=content_type, headers={"Cache-Control": "public, max-age=31536000"})


# ---------- Channel settings ----------
@api_router.get("/settings")
async def get_settings(user=Depends(auth.get_current_user)):
    channel = await db.app_config.find_one({"_id": "channel"})
    if not channel:
        return {"channel_id": None, "channel_title": None}
    return {"channel_id": channel.get("channel_id"), "channel_title": channel.get("channel_title")}


@api_router.post("/settings/channel")
async def set_channel(payload: ChannelIn, user=Depends(auth.get_current_user)):
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        raise HTTPException(status_code=400, detail="Не задан TELEGRAM_BOT_TOKEN на сервере")
    try:
        chat = await telegram_api.get_chat(payload.identifier.strip())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось получить канал: {e}. Бот должен быть админом.")
    title = chat.get("title") or chat.get("username") or str(chat.get("id"))
    await db.app_config.update_one(
        {"_id": "channel"},
        {"$set": {"channel_id": chat["id"], "channel_title": title, "channel_username": chat.get("username")}},
        upsert=True,
    )
    return {"channel_id": chat["id"], "channel_title": title}


@api_router.delete("/settings/channel")
async def remove_channel(user=Depends(auth.get_current_user)):
    await db.app_config.delete_one({"_id": "channel"})
    return {"status": "removed"}


# ---------- Watermark settings ----------
class WatermarkIn(BaseModel):
    enabled: bool = False
    type: str = "text"
    text: Optional[str] = ""
    color: str = "white"
    logo_b64: Optional[str] = ""
    position: str = "bottom-right"
    size: int = 15
    opacity: int = 50


@api_router.get("/settings/watermark")
async def get_watermark(user=Depends(auth.get_current_user)):
    cfg = await db.app_config.find_one({"_id": "watermark"}, {"_id": 0})
    return cfg or watermark.DEFAULT


@api_router.put("/settings/watermark")
async def set_watermark(payload: WatermarkIn, user=Depends(auth.get_current_user)):
    cfg = payload.model_dump()
    await db.app_config.update_one({"_id": "watermark"}, {"$set": cfg}, upsert=True)
    return cfg


@api_router.post("/settings/watermark/preview")
async def preview_watermark(payload: WatermarkIn, user=Depends(auth.get_current_user)):
    img = await asyncio.to_thread(watermark.make_preview, payload.model_dump())
    return {"image": img}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _scheduler_tick():
    await _migrate_channels()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # (A) Посты с точным временем публикации, срок которых наступил (любой канал).
    due = await db.posts.find({
        "scheduled_at": {"$ne": None, "$lte": now_iso},
        "status": "ready",
        "published": {"$ne": True},
    }).to_list(50)
    for post in due:
        try:
            await _publish_and_store(post)
            logger.info("scheduled published %s", post["id"])
        except Exception as e:
            logger.warning("scheduled publish failed %s: %s", post.get("id"), e)
            await db.posts.update_one({"id": post["id"]}, {"$set": {"scheduled_at": None, "error": f"Отложенная публикация не удалась: {e}"}})

    # (B) Очередь-«капельница» — по одному посту за интервал для КАЖДОГО канала.
    channels = await db.channels.find({"enabled": True}).to_list(100)
    for ch in channels:
        next_run = ch.get("next_run_at")
        if next_run and now_iso < next_run:
            continue
        interval = max(1, int(ch.get("interval_minutes") or 60))
        post = await db.posts.find_one(
            {"in_queue": True, "status": "ready", "published": {"$ne": True}, "channel_ref": ch["id"]},
            sort=[("queue_order", 1)],
        )
        if post:
            try:
                await _publish_and_store(post)
                logger.info("queue published %s -> %s", post["id"], ch.get("channel_title"))
            except Exception as e:
                logger.warning("queue publish failed %s: %s", post.get("id"), e)
                await db.posts.update_one({"id": post["id"]}, {"$set": {"in_queue": False, "queue_order": None, "error": f"Публикация из очереди не удалась: {e}"}})
        # Держим ритм канала: следующий слот через интервал (даже если очередь пуста).
        await db.channels.update_one({"id": ch["id"]}, {"$set": {"next_run_at": (now + timedelta(minutes=interval)).isoformat()}})


async def _scheduler_loop():
    while True:
        try:
            await _scheduler_tick()
        except Exception:
            logger.exception("scheduler tick error")
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_startup():
    await auth.seed_admin()
    asyncio.create_task(_scheduler_loop())
    logger.info("Scheduler loop started")
    if os.environ.get("ENABLE_BOT_POLLING") == "1" and os.environ.get("TELEGRAM_BOT_TOKEN"):
        from telegram_bot import start_bot
        asyncio.create_task(start_bot())
        logger.info("Bot polling enabled")
    else:
        logger.info("Bot polling disabled (dashboard-only mode)")
