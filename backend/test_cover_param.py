"""Проверка, что sendVideo/sendMediaGroup передают полноразмерный `cover`
и корректно откатываются без него, если Local Bot API вернул ошибку (старая версия)."""
import asyncio, os, tempfile
import telegram_api


class _Resp:
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


class _FakeClient:
    """Ловит multipart-запросы; первый ответ настраивается (для проверки fallback)."""
    posts = []
    first_ok = True

    def __init__(self, *a, **k):
        pass
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, url, data=None, files=None, json=None):
        _FakeClient.posts.append({"url": url, "data": dict(data or {}), "files": list((files or {}).keys())})
        # первый вызов: если first_ok=False и есть cover -> ошибка, чтобы сработал fallback
        idx = len(_FakeClient.posts)
        if idx == 1 and not _FakeClient.first_ok:
            return _Resp({"ok": False, "description": "Bad Request: unknown field \"cover\""})
        return _Resp({"ok": True, "result": {"message_id": 100 + idx}})


def _mkfile(suffix):
    fd, p = tempfile.mkstemp(suffix=suffix)
    os.write(fd, b"x" * 10)
    os.close(fd)
    return p


async def scenario(first_ok):
    _FakeClient.posts = []
    _FakeClient.first_ok = first_ok
    telegram_api.httpx.AsyncClient = _FakeClient
    vid = _mkfile(".mp4"); thumb = _mkfile(".jpg"); cover = _mkfile(".jpg")
    try:
        res = await telegram_api.send_video_file(-100, vid, "v.mp4", "cap",
                                                  thumb=thumb, width=1280, height=720, duration=5, cover=cover)
        return res, list(_FakeClient.posts)
    finally:
        for p in (vid, thumb, cover):
            os.unlink(p)


async def main():
    # 1) cover поддерживается: первый пост содержит cover в form и files
    res, posts = await scenario(first_ok=True)
    assert res["message_id"], res
    assert len(posts) == 1, f"ожидался 1 запрос, было {len(posts)}"
    assert posts[0]["data"].get("cover") == "attach://cover", posts[0]["data"]
    assert "cover" in posts[0]["files"], posts[0]["files"]
    assert posts[0]["data"].get("thumbnail") == "attach://thumb"
    print("PASS: cover передан в sendVideo (form+files)")

    # 2) старый Bot API отклонил cover -> fallback без cover, публикация успешна
    res2, posts2 = await scenario(first_ok=False)
    assert res2["message_id"], res2
    assert len(posts2) == 2, f"ожидался fallback (2 запроса), было {len(posts2)}"
    assert posts2[0]["data"].get("cover") == "attach://cover"     # 1-я попытка с cover
    assert "cover" not in posts2[1]["data"]                        # 2-я без cover
    assert "cover" not in posts2[1]["files"]
    print("PASS: fallback без cover при ошибке старого Local Bot API")

    print("ALL PASS")


if __name__ == "__main__":
    asyncio.run(main())
