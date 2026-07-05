import html
import logging

from telegraph.aio import Telegraph

from database import db

logger = logging.getLogger("telegraph_service")

_telegraph = None


async def _get_telegraph() -> Telegraph:
    global _telegraph
    if _telegraph is not None:
        return _telegraph

    cfg = await db.app_config.find_one({"_id": "telegraph"})
    if cfg and cfg.get("access_token"):
        tg = Telegraph(access_token=cfg["access_token"])
    else:
        tg = Telegraph()
        await tg.create_account(short_name="MediaPostBot", author_name="Media Post Bot")
        await db.app_config.update_one(
            {"_id": "telegraph"},
            {"$set": {"access_token": tg.get_access_token()}},
            upsert=True,
        )
    _telegraph = tg
    return _telegraph


def _media_url(base_url: str, media_id: str) -> str:
    return f"{base_url}/api/media/{media_id}"


def build_html(blocks, base_url: str) -> str:
    parts = []
    for b in blocks:
        t = b.get("type")
        if t == "text":
            text = html.escape(b.get("value", "")).replace("\n", "<br>")
            if text.strip():
                parts.append(f"<p>{text}</p>")
        elif t == "photo":
            url = _media_url(base_url, b["media_id"])
            fig = f'<figure><img src="{url}"/>'
            cap = html.escape(b.get("caption") or "")
            if cap:
                fig += f"<figcaption>{cap}</figcaption>"
            fig += "</figure>"
            parts.append(fig)
        elif t == "video":
            url = _media_url(base_url, b["media_id"])
            fig = f'<figure><video src="{url}" controls></video>'
            cap = html.escape(b.get("caption") or "")
            if cap:
                fig += f"<figcaption>{cap}</figcaption>"
            fig += "</figure>"
            parts.append(fig)
    return "".join(parts) or "<p>&nbsp;</p>"


async def create_post_page(title: str, blocks, base_url: str, author_name: str = "Media Post Bot"):
    tg = await _get_telegraph()
    content = build_html(blocks, base_url)
    resp = await tg.create_page(
        title=(title or "Untitled")[:256],
        html_content=content,
        author_name=author_name[:128],
    )
    return resp["url"], resp["path"]


async def edit_post_page(path: str, title: str, blocks, base_url: str, author_name: str = "Media Post Bot"):
    tg = await _get_telegraph()
    content = build_html(blocks, base_url)
    resp = await tg.edit_page(
        path=path,
        title=(title or "Untitled")[:256],
        html_content=content,
        author_name=author_name[:128],
    )
    return resp["url"], resp["path"]
