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
from telegraph_service import create_post_page

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
        url, path = await create_post_page(payload.title, ordered, BASE_URL)
    except Exception as e:
        logger.exception("Telegraph create failed")
        raise HTTPException(status_code=500, detail=f"Ошибка Telegraph: {e}")

    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
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
        "block_count": len(blocks),
        "preview": (preview or "")[:200],
        "published": False,
        "channel_title": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.posts.insert_one(doc)
    doc.pop("_id", None)
    return doc


async def _do_publish(post: dict, channel: dict):
    caption = f"<b>{post['title']}</b>\n\n{post['telegraph_url']}"
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
        return url, None
    bucket = get_gridfs()
    oid = await bucket.upload_from_stream(filename or kind, content, metadata={"content_type": ctype})
    return f"{BASE_URL}/api/media/{oid}", str(oid)


async def _finalize_post(post_id: str):
    post = await db.posts.find_one({"id": post_id})
    if not post or post.get("status") not in ("uploading", "processing"):
        return
    blocks = post.get("blocks", [])
    cover_idx = next((i for i, b in enumerate(blocks) if b.get("is_cover") and b["type"] == "photo" and b.get("url")), None)
    if cover_idx is not None:
        ordered = [blocks[cover_idx]] + [b for i, b in enumerate(blocks) if i != cover_idx]
    else:
        ordered = blocks
    try:
        url, path = await create_post_page(post["title"], ordered, BASE_URL)
    except Exception as e:
        logger.exception("finalize telegraph failed")
        await db.posts.update_one({"id": post_id}, {"$set": {"status": "failed", "error": str(e)}})
        return
    cover_block = next((b for b in blocks if b.get("is_cover") and b["type"] == "photo" and b.get("url")), None)
    if not cover_block:
        cover_block = next((b for b in blocks if b["type"] == "photo" and b.get("url")), None)
    media_ids = [b["media_id"] for b in blocks if b.get("media_id")]
    upd = {
        "telegraph_url": url,
        "telegraph_path": path,
        "cover_url": cover_block["url"] if cover_block else None,
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

    content = await file.read()
    ctype = file.content_type or "application/octet-stream"
    kind = "video" if ctype.startswith("video") else "photo"
    if kind == "photo":
        wm = await db.app_config.find_one({"_id": "watermark"})
        if wm and wm.get("enabled"):
            content = await asyncio.to_thread(watermark.apply_watermark, content, wm)
            ctype = "image/jpeg"
    url, media_id = await _store_bytes(content, ctype, kind, file.filename or "")

    set_fields = {f"blocks.{idx}.url": url, f"blocks.{idx}.pending": False}
    if media_id:
        set_fields[f"blocks.{idx}.media_id"] = media_id
    await db.posts.update_one({"id": post_id}, {"$set": set_fields, "$inc": {"media_done": 1}})

    updated = await db.posts.find_one({"id": post_id})
    if updated["media_done"] >= updated["media_total"] and updated.get("status") == "uploading":
        await db.posts.update_one({"id": post_id}, {"$set": {"status": "processing"}})
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
    await db.posts.delete_one({"id": post_id})
    return {"status": "deleted"}


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
