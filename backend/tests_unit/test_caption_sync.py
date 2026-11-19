"""Юнит-тесты синхронизации подписей в Telegram. Сеть и Mongo не нужны."""
import asyncio
import logging

import caption_sync as cs
from telegram_api import TelegramError


def test_message_ids_order_and_unique():
    post = {"channel_message_id": 3921, "channel_message_ids": [3921, 3922, 3923]}
    assert cs.message_ids(post) == [3921, 3922, 3923]
    assert cs.message_ids({"channel_message_ids": [5, 6]}) == [5, 6]
    assert cs.message_ids({}) == []


def test_is_media_native_and_telegraph_cover():
    native = {"post_type": "native", "blocks": [{"type": "text", "value": "x"}, {"type": "video"}]}
    assert cs.is_media_post(native)
    text_only = {"post_type": "native", "blocks": [{"type": "text", "value": "x"}]}
    assert not cs.is_media_post(text_only)
    telegraph = {"post_type": "telegraph", "cover_url": "http://x", "blocks": [{"type": "text"}]}
    assert cs.is_media_post(telegraph)
    telegraph_text = {"post_type": "telegraph", "blocks": [{"type": "text", "value": "hi"}]}
    assert not cs.is_media_post(telegraph_text)


def test_telegram_error_not_modified_and_retry_after():
    e = TelegramError.from_payload({
        "ok": False, "error_code": 400,
        "description": "Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message",
    })
    assert e.is_not_modified() and cs.is_not_modified(e)
    e2 = TelegramError.from_payload({
        "ok": False, "error_code": 429,
        "description": "Too Many Requests: retry after 12",
        "parameters": {"retry_after": 12},
    })
    assert e2.retry_after == 12
    e3 = TelegramError.from_payload({"ok": False, "description": "Too Many Requests: retry after 7"})
    assert e3.retry_after == 7


def test_media_tries_caption_on_all_ids_never_text():
    calls = []

    async def cap(chat, mid, text):
        calls.append(("caption", mid))
        raise TelegramError("Bad Request: there is no caption in the message to edit")

    async def txt(chat, mid, text):
        calls.append(("text", mid))
        return True

    post = {"id": "p1", "post_type": "native",
            "blocks": [{"type": "photo"}],
            "channel_message_id": 1, "channel_message_ids": [1, 2, 3]}

    async def run():
        return await cs.push_caption(post, "<b>Hi</b>", -100, edit_caption=cap, edit_text=txt, sleep=fake_sleep)

    sleeps = []
    async def fake_sleep(s):
        sleeps.append(s)

    res = asyncio.run(run())
    assert res["status"] == "error"
    assert res["method"] == "caption"
    assert "id=1" in res["first_error"]
    assert calls == [("caption", 1), ("caption", 2), ("caption", 3)]


def test_media_succeeds_on_second_message_id():
    async def cap(chat, mid, text):
        if mid == 1:
            raise TelegramError("Bad Request: there is no caption in the message to edit")
        return True

    async def txt(*a, **k):
        raise AssertionError("text must not be called")

    post = {"id": "p", "post_type": "native", "blocks": [{"type": "video"}],
            "channel_message_id": 1, "channel_message_ids": [1, 2]}
    res = asyncio.run(cs.push_caption(post, "cap", 1, edit_caption=cap, edit_text=txt, sleep=_nosleep))
    assert res["status"] == "ok" and res["message_id"] == 2 and res["method"] == "caption"
    assert res["first_error"] and "id=1" in res["first_error"]


def test_text_post_uses_edit_message_text_only():
    calls = []

    async def cap(*a, **k):
        calls.append("caption")
        raise AssertionError("caption must not be called")

    async def txt(chat, mid, text):
        calls.append(("text", mid))
        return True

    post = {"id": "p", "post_type": "telegraph", "blocks": [{"type": "text", "value": "x"}],
            "channel_message_id": 9}
    res = asyncio.run(cs.push_caption(post, "hello", 1, edit_caption=cap, edit_text=txt, sleep=_nosleep))
    assert res["status"] == "ok" and res["method"] == "text" and calls == [("text", 9)]


def test_not_modified_is_already_same():
    async def cap(*a, **k):
        raise TelegramError("Bad Request: message is not modified")

    post = {"id": "p", "post_type": "native", "blocks": [{"type": "photo"}], "channel_message_id": 5}
    res = asyncio.run(cs.push_caption(post, "c", 1, edit_caption=cap, edit_text=_boom_text, sleep=_nosleep))
    assert res["status"] == "already_same"


def test_retry_after_honors_margin():
    waits = []
    n = {"i": 0}

    async def cap(*a, **k):
        n["i"] += 1
        if n["i"] < 3:
            raise TelegramError("Too Many Requests: retry after 3", error_code=429, retry_after=3)
        return True

    async def slp(s):
        waits.append(s)

    post = {"id": "p", "post_type": "native", "blocks": [{"type": "photo"}], "channel_message_id": 1}
    res = asyncio.run(cs.push_caption(post, "c", 1, edit_caption=cap, edit_text=_boom_text, sleep=slp))
    assert res["status"] == "ok"
    assert waits == [3 + cs.RETRY_MARGIN, 3 + cs.RETRY_MARGIN]


def test_skip_without_message_id():
    post = {"id": "p", "post_type": "native", "blocks": [{"type": "photo"}]}
    res = asyncio.run(cs.push_caption(post, "c", 1, edit_caption=_boom_cap, edit_text=_boom_text, sleep=_nosleep))
    assert res["status"] == "skip"


def test_first_caption_error_is_logged(caplog):
    async def cap(*a, **k):
        raise TelegramError("Bad Request: have no rights to edit")

    post = {"id": "abc", "post_type": "native", "blocks": [{"type": "photo"}], "channel_message_id": 8}
    with caplog.at_level(logging.WARNING, logger="caption_sync"):
        res = asyncio.run(cs.push_caption(post, "c", 1, edit_caption=cap, edit_text=_boom_text, sleep=_nosleep))
    assert res["status"] == "error"
    assert any("abc" in r.message and "8" in r.message and "have no rights" in r.message for r in caplog.records)


async def _nosleep(_):
    return None


async def _boom_text(*a, **k):
    raise AssertionError("editMessageText must not be used for media")


async def _boom_cap(*a, **k):
    raise AssertionError("unexpected caption call")


def test_last_sync_fields():
    fields = cs.last_sync_fields({"status": "ok", "message": "Подпись обновлена", "method": "caption", "message_id": 3921})
    assert "updated_at" in fields
    assert fields["last_sync"]["status"] == "ok"
    assert fields["last_sync"]["method"] == "caption"
    assert fields["last_sync"]["message_id"] == 3921
