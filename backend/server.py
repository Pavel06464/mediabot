import os
import asyncio
import logging

from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import Response
from starlette.middleware.cors import CORSMiddleware
from bson import ObjectId

from database import db, get_gridfs
from telegram_bot import start_bot

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Media Post Bot API")
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def root():
    return {"message": "Media Post Bot API"}


@api_router.get("/stats")
async def get_stats():
    total_posts = await db.posts.count_documents({})
    total_published = await db.posts.count_documents({"published": True})
    pipeline = [{"$group": {"_id": None, "media": {"$sum": "$media_count"}}}]
    agg = await db.posts.aggregate(pipeline).to_list(1)
    total_media = agg[0]["media"] if agg else 0
    channels = await db.settings.count_documents({})
    return {
        "total_posts": total_posts,
        "total_published": total_published,
        "total_drafts": total_posts - total_published,
        "total_media": total_media,
        "channels_configured": channels,
    }


@api_router.get("/posts")
async def get_posts(limit: int = 100):
    posts = await db.posts.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return posts


@api_router.get("/posts/{post_id}")
async def get_post(post_id: str):
    post = await db.posts.find_one({"id": post_id}, {"_id": 0})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@api_router.delete("/posts/{post_id}")
async def delete_post(post_id: str):
    post = await db.posts.find_one({"id": post_id})
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    bucket = get_gridfs()
    for mid in post.get("media_ids", []):
        try:
            await bucket.delete(ObjectId(mid))
        except Exception:
            pass
    await db.posts.delete_one({"id": post_id})
    return {"status": "deleted"}


@api_router.get("/channels")
async def get_channels():
    channels = await db.settings.find({}).to_list(100)
    return [
        {"user_id": c["_id"], "channel_id": c.get("channel_id"), "channel_title": c.get("channel_title")}
        for c in channels
    ]


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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    asyncio.create_task(start_bot())


@app.on_event("shutdown")
async def on_shutdown():
    pass
