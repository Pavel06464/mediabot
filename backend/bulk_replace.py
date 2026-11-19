"""Массовая замена текста в описаниях постов.

Поиск не только точный: для ссылок учитываются опечатка t.me/t.me/,
наличие/отсутствие https:// и то, что адрес лежит внутри markdown [текст](url).
Токены и пароли сюда не попадают и не логируются.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

# https://t.me/t.me/Foo и t.me/Foo — один и тот же бот-линк.
_SCHEME_HOST = re.compile(r"(?i)^(?:https?://)?(?:t\.me/)+")


def _looks_like_url(s: str) -> bool:
    t = (s or "").strip()
    if not t or any(ch.isspace() for ch in t):
        return False
    return bool(re.match(r"(?i)^(https?://|t\.me/)", t))


def normalize_tme_url(s: str) -> str:
    """Схлопывает https://t.me/t.me/X → https://t.me/X и добавляет https:// при необходимости."""
    t = (s or "").strip()
    if not t:
        return t
    if not _looks_like_url(t):
        return t
    rest = _SCHEME_HOST.sub("", t, count=1)
    return "https://t.me/" + rest


def url_pattern(find: str) -> Optional[re.Pattern]:
    """Регулярка, которая ловит все написания той же t.me-ссылки."""
    t = (find or "").strip()
    if not _looks_like_url(t):
        return None
    rest = _SCHEME_HOST.sub("", t, count=1)
    if not rest:
        return None
    return re.compile(r"(?i)(?:https?://)?(?:t\.me/)+" + re.escape(rest))


def contains_find(text: str, find: str) -> bool:
    text = text or ""
    find = (find or "").strip()
    if not find:
        return False
    if find in text:
        return True
    pat = url_pattern(find)
    return bool(pat and pat.search(text))


def apply_replace(text: str, find: str, replace: str) -> str:
    text = text or ""
    find = (find or "").strip()
    if not find:
        return text
    pat = url_pattern(find)
    if pat:
        return pat.sub(replace, text)
    return text.replace(find, replace)


def would_change(text: str, find: str, replace: str) -> bool:
    return apply_replace(text, find, replace) != (text or "")


def iter_searchable_parts(post: dict) -> list[tuple[str, str]]:
    """Поля, в которых ищем: текстовый блок и подписи к медиа."""
    parts = []
    for i, b in enumerate(post.get("blocks") or []):
        typ = b.get("type")
        if typ == "text":
            parts.append((f"blocks[{i}].value", b.get("value") or ""))
        elif typ in ("photo", "video") and (b.get("caption") or ""):
            parts.append((f"blocks[{i}].caption", b.get("caption") or ""))
    return parts


def post_matches(post: dict, find: str) -> bool:
    return any(contains_find(val, find) for _, val in iter_searchable_parts(post))


def post_would_change(post: dict, find: str, replace: str) -> bool:
    return any(would_change(val, find, replace) for _, val in iter_searchable_parts(post))


def apply_to_post_blocks(blocks: list, find: str, replace: str) -> list:
    """Возвращает копию blocks с заменой в text.value и caption."""
    out = []
    for b in blocks or []:
        nb = dict(b)
        typ = nb.get("type")
        if typ == "text":
            nb["value"] = apply_replace(nb.get("value") or "", find, replace)
        elif typ in ("photo", "video") and nb.get("caption"):
            nb["caption"] = apply_replace(nb.get("caption") or "", find, replace)
        out.append(nb)
    return out


def snippet_around(text: str, find: str, radius: int = 80) -> str:
    text = text or ""
    find = (find or "").strip()
    idx = text.find(find) if find else -1
    if idx < 0:
        pat = url_pattern(find)
        m = pat.search(text) if pat else None
        if not m:
            return text[: radius * 2]
        idx, end = m.start(), m.end()
    else:
        end = idx + len(find)
    a, b = max(0, idx - radius), min(len(text), end + radius)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def markdown_labels_for_url(text: str, find: str) -> list[str]:
    """Подписи markdown-ссылок, чей href совпадает с искомым (в т.ч. после нормализации)."""
    labels = []
    for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text or ""):
        href = m.group(2)
        if contains_find(href, find) or contains_find(m.group(0), find):
            labels.append(m.group(1))
    return labels


def summarize_scan(posts: list, find: str, replace: str, signatures: list | None = None) -> dict:
    find = (find or "").strip()
    replace = replace or ""
    samples = []
    exact = 0
    fuzzy = 0
    change = 0
    noop = 0
    labels = []
    for p in posts:
        parts = iter_searchable_parts(p)
        if not any(contains_find(val, find) for _, val in parts):
            continue
        fuzzy += 1
        if any(find in val for _, val in parts):
            exact += 1
        changes = post_would_change(p, find, replace)
        if changes:
            change += 1
        else:
            noop += 1
        blob = "\n".join(val for _, val in parts)
        for lab in markdown_labels_for_url(blob, find):
            if lab not in labels:
                labels.append(lab)
        if len(samples) < 5:
            samples.append({
                "id": p.get("id"),
                "title": (p.get("title") or "")[:80],
                "snippet": snippet_around(blob, find),
                "exact": any(find in val for _, val in parts),
                "would_change": changes,
                "labels": markdown_labels_for_url(blob, find),
            })

    sig_matched = sig_change = 0
    sig_samples = []
    for s in signatures or []:
        content = s.get("content") or ""
        if not contains_find(content, find):
            continue
        sig_matched += 1
        ch = would_change(content, find, replace)
        if ch:
            sig_change += 1
        sig_samples.append({
            "id": s.get("id"),
            "name": s.get("name"),
            "snippet": snippet_around(content, find),
            "would_change": ch,
        })

    norm = normalize_tme_url(find) if _looks_like_url(find) else find
    message = _human_message(find, norm, replace, exact, fuzzy, change, noop, labels, sig_matched, sig_change)
    return {
        "find": find,
        "find_normalized": norm if norm != find else None,
        "matched": fuzzy,
        "matched_exact": exact,
        "would_change": change,
        "noop": noop,
        "signatures_matched": sig_matched,
        "signatures_would_change": sig_change,
        "markdown_labels": labels,
        "samples": samples,
        "signature_samples": sig_samples,
        "message": message,
    }


def _human_message(find, norm, replace, exact, fuzzy, change, noop, labels, sig_matched, sig_change) -> str:
    if fuzzy == 0 and sig_matched == 0:
        return "Постов с таким текстом не найдено."
    parts = []
    if exact == 0 and fuzzy > 0 and norm and norm != find:
        label = f" «{'», «'.join(labels[:3])}»" if labels else ""
        parts.append(
            f"Точного текста нет, но в {fuzzy} постах уже есть похожая ссылка в виде {norm}"
            + (f", спрятанная в markdown за текстом{label}." if label else ".")
        )
    elif fuzzy > 0:
        parts.append(f"Найдено в {fuzzy} постах" + (f" (точное совпадение — {exact})." if exact != fuzzy else "."))
    if change == 0 and fuzzy > 0:
        parts.append("Замена ничего не изменит: в описаниях уже тот адрес, на который вы хотите заменить.")
    elif change:
        parts.append(f"Текст изменится в {change} постах.")
    if sig_matched:
        extra = f", изменится в {sig_change}" if sig_change else ", в подписях замена тоже ничего не изменит"
        parts.append(f"Эта ссылка также есть в {sig_matched} подписях{extra}.")
    return " ".join(parts)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_job_doc(summary: dict, payload: dict) -> dict:
    return {
        "id": payload["job_id"],
        "status": "running",
        "find": summary["find"],
        "replace": payload.get("replace") or "",
        "channel_ref": payload.get("channel_ref"),
        "update_live": bool(payload.get("update_live", True)),
        "include_signatures": bool(payload.get("include_signatures")),
        "total": summary["would_change"] + (summary["signatures_would_change"] if payload.get("include_signatures") else 0),
        "processed": 0,
        "updated_db": 0,
        "updated_telegram": 0,
        "skipped_noop": summary.get("noop") or 0,
        "signatures_updated": 0,
        "errors": [],
        "message": summary.get("message") or "",
        "samples": summary.get("samples") or [],
        "started_at": now_iso(),
        "finished_at": None,
    }
