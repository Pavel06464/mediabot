import os
import uuid
import asyncio
import tempfile
import logging
from datetime import datetime, timezone
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
    media: List[MediaDesc] = []


class MediaEdit(BaseModel):
    idx: int
    caption: Optional[str] = ""
    is_cover: bool = False


class PostEditIn(BaseModel):
    title: str
    description: Optional[str] = ""
    media: List[MediaEdit] = []


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
async def get_stats(user=Depends(auth.get_current_user)):
    total_posts = await db.posts.count_documents({})
    total_published = await db.posts.count_documents({"published": True})
    pipeline = [{"$group": {"_id": None, "media": {"$sum": "$media_count"}}}]
    agg = await db.posts.aggregate(pipeline).to_list(1)
    total_media = agg[0]["media"] if agg else 0
    channel = await db.app_config.find_one({"_id": "channel"})
    return {
        "total_posts": total_posts,
        "total_published": total_published,
        "total_drafts": total_posts - total_published,
        "total_media": total_media,
        "channels_configured": 1 if channel else 0,
    }


# ---------- Posts ----------
@api_router.get("/posts")
async def get_posts(limit: int = 100, user=Depends(auth.get_current_user)):
    return await db.posts.find({}, {"_id": 0, "blocks": 0}).sort("created_at", -1).to_list(limit)


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
    """Разбивает блоки на текст / фото / видео и определяет обложку (первое is_cover фото)."""
    text_blocks = [b for b in blocks if b.get("type") == "text" and (b.get("value") or "").strip()]
    photos = [b for b in blocks if b.get("type") == "photo" and b.get("url")]
    videos = [b for b in blocks if b.get("type") == "video" and b.get("url")]
    cover = next((b for b in photos if b.get("is_cover")), None) or (photos[0] if photos else None)
    if cover and photos:
        photos = [cover] + [b for b in photos if b is not cover]
    return text_blocks, photos, videos, cover


def _publish_caption(post: dict) -> str:
    photos_url = post.get("photos_url")
    videos_url = post.get("videos_url")
    parts = [f"<b>{post['title']}</b>", ""]
    if photos_url:
        parts.append(f"📷 Фото: {photos_url}")
    if videos_url:
        parts.append(f"🎬 Видео: {videos_url}")
    if not photos_url and not videos_url:
        parts.append(post.get("telegraph_url") or "")
    return "\n".join(parts)


async def _do_publish(post: dict, channel: dict):
    caption = _publish_caption(post)
    if post.get("cover_url"):
        try:
            await telegram_api.send_photo(channel["channel_id"], post["cover_url"], caption)
        except Exception as e:
            logger.warning("sendPhoto failed, fallback to sendMessage: %s", e)
            await telegram_api.send_message(channel["channel_id"], caption)
    else:
        await telegram_api.send_message(channel["channel_id"], caption)


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
    blocks = post.get("blocks", [])
    text_blocks, photos, videos, cover = _split_media(blocks)
    photos_url = photos_path = videos_url = videos_path = None
    photos_paths = videos_paths = []
    try:
        # Статья с фото (или текстовая, если медиа нет вовсе). Текст идёт в фото-статью.
        if photos or not videos:
            photos_url, photos_paths = await create_paginated_page(post["title"], text_blocks + photos, BASE_URL)
        # Отдельная статья с видео. Текст сюда — только если фото нет.
        if videos:
            vcontent = videos if photos else (text_blocks + videos)
            videos_url, videos_paths = await create_paginated_page(post["title"], vcontent, BASE_URL)
    except Exception as e:
        logger.exception("finalize telegraph failed")
        await db.posts.update_one({"id": post_id}, {"$set": {"status": "failed", "error": str(e)}})
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
        "media_ids": media_ids,
        "status": "ready",
    }
    published = False
    channel_title = None
    if post.get("publish_after"):
        channel = await db.app_config.find_one({"_id": "channel"})
        if channel:
            try:
                merged = {**post, **upd}
                await _do_publish(merged, channel)
                published = True
                channel_title = channel.get("channel_title")
                upd["status"] = "published"
            except Exception as e:
                logger.warning("auto-publish failed: %s", e)
                upd["error"] = f"Публикация не удалась: {e}"
    upd["published"] = published
    upd["channel_title"] = channel_title
    await db.posts.update_one({"id": post_id}, {"$set": upd})


@api_router.post("/posts/draft")
async def create_draft(payload: DraftIn, user=Depends(auth.get_current_user)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Укажите заголовок")
    blocks = []
    if payload.description and payload.description.strip():
        blocks.append({"type": "text", "value": payload.description.strip()})
    slots = []
    for m in payload.media:
        idx = len(blocks)
        blocks.append({
            "type": m.kind, "is_cover": m.is_cover, "caption": m.caption or "",
            "url": None, "media_id": None, "pending": True,
        })
        slots.append(idx)
    post_id = str(uuid.uuid4())
    doc = {
        "id": post_id,
        "user_id": user["id"],
        "title": payload.title.strip(),
        "telegraph_url": None,
        "telegraph_path": None,
        "cover_url": None,
        "blocks": blocks,
        "media_ids": [],
        "r2_keys": [],
        "media_count": len(slots),
        "media_total": len(slots),
        "media_done": 0,
        "block_count": len(blocks),
        "preview": (payload.description or "")[:200],
        "publish_after": payload.publish_after,
        "published": False,
        "channel_title": None,
        "status": "uploading" if slots else "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.posts.insert_one(doc)
    if not slots:
        await _finalize_post(post_id)
    return {"id": post_id, "slots": slots}


@api_router.post("/posts/{post_id}/media/{idx}")
async def upload_media_slot(post_id: str, idx: int, file: UploadFile = File(...), user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    blocks = post.get("blocks", [])
    if idx < 0 or idx >= len(blocks) or blocks[idx]["type"] not in ("photo", "video"):
        raise HTTPException(status_code=400, detail="Неверный слот")

    slot_kind = blocks[idx]["type"]
    ctype = file.content_type or "application/octet-stream"
    name = (file.filename or "").lower()
    file_kind = "video" if ctype.startswith("video") else ("photo" if ctype.startswith("image") else None)
    if file_kind is None:
        if name.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp", ".tiff")):
            file_kind = "photo"
        elif name.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpeg", ".mpg")):
            file_kind = "video"
    if file_kind != slot_kind:
        expected = "видео" if slot_kind == "video" else "изображение"
        raise HTTPException(status_code=400, detail=f"Ожидается {expected}, а получен файл «{file.filename or ctype}»")

    if slot_kind == "photo":
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
        if size > 2 * 1024 * 1024 * 1024:
            os.unlink(path)
            raise HTTPException(status_code=400, detail="Видео больше 2 ГБ")
        try:
            url, media_id, r2_key = await _store_temp(path, ctype, "video", file.filename or "")
        finally:
            os.unlink(path)

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


@api_router.post("/posts/{post_id}/publish")
async def publish_post(post_id: str, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if not post.get("telegraph_url"):
        raise HTTPException(status_code=400, detail="Статья ещё создаётся, подождите")
    channel = await db.app_config.find_one({"_id": "channel"})
    if not channel:
        raise HTTPException(status_code=400, detail="Сначала настройте канал в настройках")
    try:
        await _do_publish(post, channel)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка публикации: {e}")
    await db.posts.update_one(
        {"id": post_id},
        {"$set": {"published": True, "status": "published", "channel_title": channel.get("channel_title")}},
    )
    return {"status": "published", "channel_title": channel.get("channel_title")}


@api_router.delete("/posts/{post_id}")
async def delete_post(post_id: str, user=Depends(auth.get_current_user)):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
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
    if not post.get("telegraph_path"):
        raise HTTPException(status_code=400, detail="Статья ещё создаётся, редактирование недоступно")
    blocks = post.get("blocks", [])
    media = [
        {"idx": i, "kind": b["type"], "url": b.get("url"), "caption": b.get("caption", ""), "is_cover": bool(b.get("is_cover"))}
        for i, b in enumerate(blocks) if b["type"] in ("photo", "video")
    ]
    description = next((b.get("value", "") for b in blocks if b["type"] == "text"), "")
    return {
        "id": post["id"],
        "title": post["title"],
        "description": description,
        "telegraph_url": post.get("telegraph_url"),
        "media": media,
    }


@api_router.put("/posts/{post_id}")
async def edit_post(post_id: str, payload: PostEditIn, user=Depends(auth.get_current_user)):
    if not payload.title.strip():
        raise HTTPException(status_code=400, detail="Укажите заголовок")
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Пост не найден")
    if not post.get("telegraph_path"):
        raise HTTPException(status_code=400, detail="Статья ещё создаётся, редактирование недоступно")
    blocks = post.get("blocks", [])

    for m in payload.media:
        if 0 <= m.idx < len(blocks) and blocks[m.idx]["type"] in ("photo", "video"):
            blocks[m.idx]["caption"] = m.caption or ""
            blocks[m.idx]["is_cover"] = bool(m.is_cover)

    desc = (payload.description or "").strip()
    text_idx = next((i for i, b in enumerate(blocks) if b["type"] == "text"), None)
    if text_idx is not None:
        blocks[text_idx]["value"] = desc
    elif desc:
        blocks.insert(0, {"type": "text", "value": desc})

    text_blocks, photos, videos, cover = _split_media(blocks)
    photos_url, photos_paths = post.get("photos_url"), post.get("photos_paths") or ([post["photos_path"]] if post.get("photos_path") else [])
    videos_url, videos_paths = post.get("videos_url"), post.get("videos_paths") or ([post["videos_path"]] if post.get("videos_path") else [])
    title = payload.title.strip()
    try:
        if photos_paths or videos_paths:
            if photos_paths:
                photos_url, photos_paths = await edit_paginated_page(photos_paths, title, text_blocks + photos, BASE_URL)
            if videos_paths:
                vcontent = videos if photos else (text_blocks + videos)
                videos_url, videos_paths = await edit_paginated_page(videos_paths, title, vcontent, BASE_URL)
        else:
            # Легаси-пост с единственной статьёй
            ordered = ([cover] + [b for b in blocks if b is not cover]) if cover else blocks
            photos_url, photos_paths = await edit_paginated_page([post["telegraph_path"]], title, ordered, BASE_URL)
    except Exception as e:
        logger.exception("edit telegraph failed")
        raise HTTPException(status_code=500, detail=f"Ошибка Telegraph: {e}")

    await db.posts.update_one(
        {"id": post_id},
        {"$set": {
            "title": title,
            "blocks": blocks,
            "telegraph_url": photos_url or videos_url,
            "telegraph_path": (photos_paths or videos_paths or [None])[0],
            "photos_url": photos_url,
            "photos_path": photos_paths[0] if photos_paths else None,
            "photos_paths": photos_paths,
            "videos_url": videos_url,
            "videos_path": videos_paths[0] if videos_paths else None,
            "videos_paths": videos_paths,
            "cover_url": cover["url"] if cover else None,
            "preview": desc[:200],
        }},
    )
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
        {"$set": {"channel_id": chat["id"], "channel_title": title}},
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


@app.on_event("startup")
async def on_startup():
    await auth.seed_admin()
    if os.environ.get("ENABLE_BOT_POLLING") == "1" and os.environ.get("TELEGRAM_BOT_TOKEN"):
        from telegram_bot import start_bot
        asyncio.create_task(start_bot())
        logger.info("Bot polling enabled")
    else:
        logger.info("Bot polling disabled (dashboard-only mode)")
