"""Seed data for channel gate / filtering tests.

Creates 2 channels (chan-alpha 'Канал Альфа', chan-beta 'Канал Бета') and 4 posts:
seed-a1 (published, telegraph, alpha), seed-a2 (ready draft, alpha), seed-a3 (ready in_queue, alpha),
seed-b1 (native ready, beta).
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone

from database import db


async def main():
    now = datetime.now(timezone.utc).isoformat()
    # channels
    await db.channels.delete_many({"id": {"$in": ["chan-alpha", "chan-beta"]}})
    await db.channels.insert_many([
        {"id": "chan-alpha", "channel_id": -1001111111111, "channel_title": "Канал Альфа",
         "channel_username": "alpha_test", "enabled": False, "interval_minutes": 60,
         "auto_enqueue": False, "next_run_at": None, "created_at": now},
        {"id": "chan-beta", "channel_id": -1002222222222, "channel_title": "Канал Бета",
         "channel_username": "beta_test", "enabled": False, "interval_minutes": 60,
         "auto_enqueue": False, "next_run_at": None, "created_at": now},
    ])
    # remove old seeds
    await db.posts.delete_many({"id": {"$in": ["seed-a1", "seed-a2", "seed-a3", "seed-b1"]}})
    base = {
        "user_id": "seed", "hashtags": [], "media_ids": [], "r2_keys": [], "blocks": [],
        "media_count": 1, "photo_count": 1, "video_count": 0, "media_total": 1, "media_done": 1,
        "block_count": 1, "preview": "", "publish_after": False, "channel_message_id": None,
        "in_queue": False, "queue_order": None, "scheduled_at": None,
    }
    docs = [
        {**base, "id": "seed-a1", "title": "Альфа пост 1", "channel_ref": "chan-alpha",
         "status": "published", "published": True, "post_type": "telegraph",
         "telegraph_url": "https://telegra.ph/a1", "telegraph_path": "a1",
         "cover_url": None, "channel_title": "Канал Альфа", "created_at": now},
        {**base, "id": "seed-a2", "title": "Альфа пост 2", "channel_ref": "chan-alpha",
         "status": "ready", "published": False, "post_type": "telegraph",
         "telegraph_url": "https://telegra.ph/a2", "telegraph_path": "a2",
         "created_at": now},
        {**base, "id": "seed-a3", "title": "Альфа пост 3", "channel_ref": "chan-alpha",
         "status": "ready", "published": False, "post_type": "telegraph",
         "telegraph_url": "https://telegra.ph/a3", "telegraph_path": "a3",
         "in_queue": True, "queue_order": 1, "created_at": now},
        {**base, "id": "seed-b1", "title": "Бета пост 1", "channel_ref": "chan-beta",
         "status": "ready", "published": False, "post_type": "native",
         "telegraph_url": None, "telegraph_path": None, "created_at": now},
    ]
    await db.posts.insert_many(docs)
    print("Seeded 2 channels + 4 posts")


if __name__ == "__main__":
    asyncio.run(main())
