import html
import logging
import re

from telegraph.aio import Telegraph

from database import db

logger = logging.getLogger("telegraph_service")

_telegraph = None


def _inline_md(escaped: str) -> str:
    """Apply inline markdown on already HTML-escaped text: links, bold, italic."""
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", escaped)
    return escaped


def md_to_html(text: str) -> str:
    """Convert a lightweight markdown subset to Telegraph-safe HTML.
    Supports: # H3, ## H4, > quote, **bold**, *italic*, [text](url)."""
    out = []
    for line in (text or "").split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("## "):
            out.append(f"<h4>{_inline_md(html.escape(stripped[3:]))}</h4>")
        elif stripped.startswith("# "):
            out.append(f"<h3>{_inline_md(html.escape(stripped[2:]))}</h3>")
        elif stripped.startswith("> "):
            out.append(f"<blockquote>{_inline_md(html.escape(stripped[2:]))}</blockquote>")
        else:
            out.append(f"<p>{_inline_md(html.escape(line))}</p>")
    return "".join(out)


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
            frag = md_to_html(b.get("value", ""))
            if frag:
                parts.append(frag)
        elif t == "photo":
            url = b.get("url") or _media_url(base_url, b["media_id"])
            fig = f'<figure><img src="{url}"/>'
            cap = html.escape(b.get("caption") or "")
            if cap:
                fig += f"<figcaption>{cap}</figcaption>"
            fig += "</figure>"
            parts.append(fig)
        elif t == "video":
            url = b.get("url") or _media_url(base_url, b["media_id"])
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


# ---- Пагинация: Telegraph ограничивает контент (~64 КБ). Большие альбомы бьём на страницы. ----
MAX_HTML = 40000  # безопасный порог размера html одной страницы


def _chunk_blocks(blocks, base_url):
    chunks, cur, size = [], [], 0
    for b in blocks:
        bl = len(build_html([b], base_url))
        if cur and size + bl > MAX_HTML:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += bl
    if cur:
        chunks.append(cur)
    return chunks or [[]]


def _nav_html(next_url, part_no):
    if not next_url:
        return ""
    return f'<p><a href="{next_url}">➡️ Продолжение — часть {part_no}</a></p>'


async def create_paginated_page(title, blocks, base_url, author_name="Media Post Bot"):
    """Создаёт одну или несколько связанных Telegraph-страниц. Возвращает (url_первой, [paths])."""
    tg = await _get_telegraph()
    chunks = _chunk_blocks(blocks, base_url)
    total = len(chunks)
    base_title = (title or "Untitled")
    paths = [None] * total
    next_url = None
    for i in range(total - 1, -1, -1):
        part_title = base_title if total == 1 else f"{base_title} ({i + 1}/{total})"
        content = build_html(chunks[i], base_url) + _nav_html(next_url, i + 2)
        resp = await tg.create_page(title=part_title[:256], html_content=content, author_name=author_name[:128])
        paths[i] = resp["path"]
        next_url = resp["url"]
    return next_url, paths  # next_url после i=0 — это url первой страницы


async def edit_paginated_page(paths, title, blocks, base_url, author_name="Media Post Bot"):
    """Перерисовывает существующие страницы. Если чанков стало больше — создаёт недостающие.
    Возвращает (url_первой, [paths])."""
    tg = await _get_telegraph()
    chunks = _chunk_blocks(blocks, base_url)
    total = len(chunks)
    base_title = (title or "Untitled")
    out_paths = [None] * total
    next_url = None
    for i in range(total - 1, -1, -1):
        part_title = base_title if total == 1 else f"{base_title} ({i + 1}/{total})"
        content = build_html(chunks[i], base_url) + _nav_html(next_url, i + 2)
        if i < len(paths) and paths[i]:
            resp = await tg.edit_page(path=paths[i], title=part_title[:256], html_content=content, author_name=author_name[:128])
        else:
            resp = await tg.create_page(title=part_title[:256], html_content=content, author_name=author_name[:128])
        out_paths[i] = resp["path"]
        next_url = resp["url"]
    return next_url, out_paths

