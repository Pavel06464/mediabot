"""Unit tests for iOS-safe Telegraph video pages.

Pagination (at most 4 videos, byte cap, continuation links) and the
remux-vs-transcode decision. ffmpeg/ffprobe are mocked. These tests do not
talk to a live server — unlike the other modules in this directory.
"""
import asyncio
import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "unit_test")

import pytest

import telegraph_service as ts
import video_prep as vp


def _video(i, size=1000, url=None):
    block = {"type": "video", "url": url or f"https://cdn.example/v{i}.mp4"}
    if size is not None:
        block["size"] = size
    return block


def _box(typ: bytes, payload: bytes = b"", large: bool = False) -> bytes:
    if large:
        size = 16 + len(payload)
        return (1).to_bytes(4, "big") + typ + size.to_bytes(8, "big") + payload
    return (8 + len(payload)).to_bytes(4, "big") + typ + payload


FASTSTART = _box(b"ftyp", b"isom") + _box(b"moov", b"hdr") + _box(b"mdat", b"media")
LATE_MOOV = _box(b"ftyp", b"isom") + _box(b"mdat", b"media") + _box(b"moov", b"hdr")
NO_MOOV = _box(b"ftyp", b"isom") + _box(b"mdat", b"media")


def _write(path, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


# ---------- pagination ----------

def test_video_page_constants():
    assert ts.MAX_VIDEOS_PER_PAGE == 4
    assert 30 * 1024 * 1024 <= ts.MAX_VIDEO_BYTES_PER_PAGE <= 40 * 1024 * 1024


def test_four_videos_stay_on_one_page():
    chunks = ts._chunk_blocks([_video(i) for i in range(4)], "https://x")
    assert len(chunks) == 1
    assert len(chunks[0]) == 4


def test_fifth_video_starts_a_continuation_page():
    chunks = ts._chunk_blocks([_video(i) for i in range(5)], "https://x")
    assert [len(c) for c in chunks] == [4, 1]
    assert chunks[1][0]["url"].endswith("v4.mp4")


def test_nine_videos_pack_as_four():
    chunks = ts._chunk_blocks([_video(i) for i in range(9)], "https://x")
    assert [len(c) for c in chunks] == [4, 4, 1]


def test_max_items_cannot_raise_the_video_cap():
    """The old max_items=10 must not put 10 videos on one iOS page."""
    chunks = ts._chunk_blocks([_video(i) for i in range(10)], "https://x", max_items=10)
    assert [len(c) for c in chunks] == [4, 4, 2]


def test_max_items_still_caps_tighter_than_the_video_limit():
    chunks = ts._chunk_blocks([_video(i) for i in range(5)], "https://x", max_items=2)
    assert [len(c) for c in chunks] == [2, 2, 1]


def test_text_does_not_consume_a_video_slot():
    blocks = [{"type": "text", "value": "описание"}] + [_video(i) for i in range(4)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert len(chunks) == 1
    assert sum(1 for b in chunks[0] if b["type"] == "video") == 4


def test_text_stays_with_the_first_video_page():
    blocks = [{"type": "text", "value": "описание"}] + [_video(i) for i in range(5)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert chunks[0][0]["type"] == "text"
    assert sum(1 for b in chunks[0] if b["type"] == "video") == 4
    assert [b["type"] for b in chunks[1]] == ["video"]


def test_byte_cap_splits_before_the_count_cap():
    half = ts.MAX_VIDEO_BYTES_PER_PAGE // 2
    blocks = [_video(i, size=half) for i in range(3)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    # two halves fill the budget exactly; the third video starts a new page
    assert [len(c) for c in chunks] == [2, 1]


def test_byte_cap_exact_fit_stays_together():
    limit = ts.MAX_VIDEO_BYTES_PER_PAGE
    blocks = [_video(0, size=limit // 2), _video(1, size=limit - limit // 2)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert len(chunks) == 1


def test_one_byte_over_the_budget_starts_a_new_page():
    limit = ts.MAX_VIDEO_BYTES_PER_PAGE
    blocks = [_video(0, size=limit), _video(1, size=1)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert [len(c) for c in chunks] == [1, 1]


def test_oversized_video_is_alone_then_the_next_ones_pack():
    huge = ts.MAX_VIDEO_BYTES_PER_PAGE + 1
    blocks = [_video(0, size=huge)] + [_video(i, size=1000) for i in range(1, 5)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert [len(c) for c in chunks] == [1, 4]


def test_unknown_size_does_not_force_a_byte_split():
    blocks = [_video(i, size=None) for i in range(5)]
    for b in blocks:
        b.pop("size", None)
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert [len(c) for c in chunks] == [4, 1]


def test_garbage_size_is_ignored():
    blocks = [_video(i, size="nope") for i in range(5)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert [len(c) for c in chunks] == [4, 1]


def test_photos_are_not_capped_at_four():
    blocks = [{"type": "photo", "url": f"https://cdn.example/p{i}.jpg"} for i in range(10)]
    chunks = ts._chunk_blocks(blocks, "https://x")
    assert len(chunks) == 1


def test_html_cap_still_splits_large_text():
    big = {"type": "text", "value": "а" * (ts.MAX_HTML + 50)}
    chunks = ts._chunk_blocks([big, big], "https://x")
    assert len(chunks) == 2


def test_empty_blocks_yield_one_empty_page():
    assert ts._chunk_blocks([], "https://x") == [[]]


def test_continuation_link_points_at_the_next_page(monkeypatch):
    created = []

    class FakeTG:
        async def create_page(self, title, html_content, author_name):
            n = len(created) + 1
            page = {
                "title": title,
                "html": html_content,
                "url": f"https://telegra.ph/Part-{n}",
                "path": f"Part-{n}",
            }
            created.append(page)
            return {"url": page["url"], "path": page["path"]}

    async def fake_tg():
        return FakeTG()

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(ts, "_get_telegraph", fake_tg)
    monkeypatch.setattr(ts.asyncio, "sleep", no_sleep)

    blocks = [_video(i) for i in range(5)]
    url, paths = asyncio.run(ts.create_paginated_page("Ролик", blocks, "https://cdn.example"))

    assert len(created) == 2
    assert len(paths) == 2
    # Pages are created last-to-first, so the returned url is the first page.
    first, second = created[1], created[0]
    assert url == first["url"]
    assert paths[0] == first["path"]
    assert first["title"] == "Ролик (1/2)"
    assert second["title"] == "Ролик (2/2)"
    assert "➡️ Продолжение — часть 2" in first["html"]
    assert second["url"] in first["html"]
    assert "Продолжение" not in second["html"]
    # 4 videos on the first page, the 5th only on the continuation.
    assert first["html"].count("<video ") == 4
    assert second["html"].count("<video ") == 1
    assert "v4.mp4" in second["html"]
    assert "v4.mp4" not in first["html"]


def test_single_page_has_no_continuation_link(monkeypatch):
    created = []

    class FakeTG:
        async def create_page(self, title, html_content, author_name):
            created.append({"title": title, "html": html_content})
            return {"url": "https://telegra.ph/Only", "path": "Only"}

    async def fake_tg():
        return FakeTG()

    monkeypatch.setattr(ts, "_get_telegraph", fake_tg)
    blocks = [_video(i) for i in range(4)]
    url, paths = asyncio.run(ts.create_paginated_page("Ролик", blocks, "https://cdn.example"))
    assert url == "https://telegra.ph/Only"
    assert paths == ["Only"]
    assert created[0]["title"] == "Ролик"
    assert "Продолжение" not in created[0]["html"]


# ---------- moov layout ----------

def test_moov_before_mdat(tmp_path):
    path = tmp_path / "fast.mp4"
    _write(path, FASTSTART)
    assert vp.moov_position(str(path)) == "before"


def test_moov_after_mdat(tmp_path):
    path = tmp_path / "late.mp4"
    _write(path, LATE_MOOV)
    assert vp.moov_position(str(path)) == "after"


def test_moov_absent(tmp_path):
    path = tmp_path / "none.bin"
    _write(path, NO_MOOV)
    assert vp.moov_position(str(path)) == "absent"


def test_moov_after_64bit_mdat(tmp_path):
    path = tmp_path / "large.mp4"
    data = _box(b"ftyp", b"isom") + _box(b"mdat", b"media", large=True) + _box(b"moov", b"hdr")
    _write(path, data)
    assert vp.moov_position(str(path)) == "after"


def test_free_atom_between_ftyp_and_moov(tmp_path):
    path = tmp_path / "free.mp4"
    data = _box(b"ftyp", b"isom") + _box(b"free", b"\x00" * 16) + _box(b"moov", b"hdr") + _box(b"mdat", b"m")
    _write(path, data)
    assert vp.moov_position(str(path)) == "before"


def test_missing_file_has_no_moov(tmp_path):
    assert vp.moov_position(str(tmp_path / "nope.mp4")) == "absent"


def test_truncated_box_does_not_loop(tmp_path):
    path = tmp_path / "bad.mp4"
    _write(path, b"\x00\x00\x00\x02moov" + b"trailing")
    assert vp.moov_position(str(path)) == "absent"


# ---------- normalize decision ----------

@pytest.mark.parametrize(
    "video,audio,pix,moov,expected",
    [
        ("h264", "aac", "yuv420p", "after", "remux"),
        ("h264", "aac", "yuv420p", "before", "remux"),
        ("h264", None, "yuv420p", "after", "remux"),
        ("h264", "aac", "yuvj420p", "before", "remux"),
        ("H264", "AAC", "YUV420P", "after", "remux"),
        ("h264", "aac", None, "after", "remux"),
        ("avc1", "mp4a", "yuv420p", "before", "remux"),
        ("h264", "aac", "yuv420p", "absent", "transcode"),
        ("hevc", "aac", "yuv420p", "before", "transcode"),
        ("h265", "aac", "yuv420p", "after", "transcode"),
        ("h264", "mp3", "yuv420p", "before", "transcode"),
        ("h264", "opus", "yuv420p", "before", "transcode"),
        ("h264", "vorbis", "yuv420p", "absent", "transcode"),
        ("vp9", "opus", None, "absent", "transcode"),
        ("vp8", None, None, "absent", "transcode"),
        ("av1", "aac", "yuv420p", "before", "transcode"),
        ("h264", "aac", "yuv420p10le", "before", "transcode"),
        (None, None, None, "absent", "transcode"),
        ("", "", "", "after", "transcode"),
    ],
)
def test_choose_normalize_action(video, audio, pix, moov, expected):
    assert vp.choose_normalize_action(video, audio, pix, moov) == expected


def test_stored_video_key_is_lowercase_mp4():
    assert vp.MP4_EXTENSION == ".mp4"
    assert vp.MP4_CONTENT_TYPE == "video/mp4"
    key = vp.video_object_key("abc-123")
    assert key == "video/abc-123.mp4"
    assert key.endswith(".mp4")
    assert ".MP4" not in key and ".mov" not in key


def test_ffmpeg_args_faststart_and_codecs():
    remux = vp.remux_args("in.MOV", "out.mp4")
    assert remux[0] == "ffmpeg"
    assert remux[remux.index("-c") + 1] == "copy"
    assert "+faststart" in remux
    assert "libx264" not in remux
    assert remux[-1] == "out.mp4"

    trans = vp.transcode_args("in.webm", "out.mp4")
    assert "libx264" in trans
    assert trans[trans.index("-pix_fmt") + 1] == "yuv420p"
    assert trans[trans.index("-c:a") + 1] == "aac"
    assert "+faststart" in trans
    assert trans[-1] == "out.mp4"


def _patch_tools(monkeypatch, probe, ffmpeg):
    monkeypatch.setattr(vp.shutil, "which", lambda name: f"/usr/bin/{name}")
    async def fake_probe(_path):
        return probe
    monkeypatch.setattr(vp, "probe_media", fake_probe)
    monkeypatch.setattr(vp, "_ffmpeg_to_file", ffmpeg)


def test_h264_aac_is_remuxed_not_transcoded(tmp_path, monkeypatch):
    src = tmp_path / "late.mp4"
    _write(src, LATE_MOOV)
    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        _write(dest, FASTSTART)
        return True, ""

    _patch_tools(monkeypatch, {"video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p"}, fake_ff)
    out = asyncio.run(vp.normalize_video(str(src)))
    try:
        assert vp.moov_position(out) == "before"
        assert len(calls) == 1
        assert "copy" in calls[0]
        assert "+faststart" in calls[0]
        assert "libx264" not in calls[0]
    finally:
        os.unlink(out)


def test_hevc_is_transcoded_to_h264_aac(tmp_path, monkeypatch):
    src = tmp_path / "clip.mp4"
    _write(src, FASTSTART)  # moov is fine, codec is not
    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        _write(dest, FASTSTART)
        return True, ""

    _patch_tools(monkeypatch, {"video_codec": "hevc", "audio_codec": "aac", "pix_fmt": "yuv420p"}, fake_ff)
    out = asyncio.run(vp.normalize_video(str(src)))
    try:
        assert "libx264" in calls[0]
        assert "yuv420p" in calls[0]
        assert "aac" in calls[0]
        assert "+faststart" in calls[0]
        assert "copy" not in calls[0]
        assert vp.moov_position(out) == "before"
    finally:
        os.unlink(out)


def test_file_without_moov_is_transcoded(tmp_path, monkeypatch):
    src = tmp_path / "clip.mkv"
    _write(src, NO_MOOV)
    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        _write(dest, FASTSTART)
        return True, ""

    _patch_tools(monkeypatch, {"video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p"}, fake_ff)
    out = asyncio.run(vp.normalize_video(str(src)))
    try:
        assert "libx264" in calls[0]
        assert "copy" not in calls[0]
    finally:
        os.unlink(out)


def test_remux_failure_falls_back_to_transcode(tmp_path, monkeypatch):
    src = tmp_path / "late.mp4"
    _write(src, LATE_MOOV)
    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        if "copy" in args:
            return False, "could not remux"
        _write(dest, FASTSTART)
        return True, ""

    _patch_tools(monkeypatch, {"video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p"}, fake_ff)
    out = asyncio.run(vp.normalize_video(str(src)))
    try:
        assert any("copy" in c for c in calls)
        assert any("libx264" in c for c in calls)
        assert vp.moov_position(out) == "before"
    finally:
        os.unlink(out)


def test_remux_without_leading_moov_is_discarded(tmp_path, monkeypatch):
    src = tmp_path / "late.mp4"
    _write(src, LATE_MOOV)
    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        _write(dest, NO_MOOV if "copy" in args else FASTSTART)
        return True, ""

    _patch_tools(monkeypatch, {"video_codec": "h264", "audio_codec": "aac", "pix_fmt": "yuv420p"}, fake_ff)
    out = asyncio.run(vp.normalize_video(str(src)))
    try:
        assert len(calls) == 2
        assert vp.moov_position(out) == "before"
    finally:
        os.unlink(out)


def test_ffmpeg_failure_raises_and_leaves_no_output(tmp_path, monkeypatch):
    src = tmp_path / "clip.webm"
    _write(src, NO_MOOV)
    made = []
    real_tmp = vp._tmp_mp4

    def track():
        path = real_tmp()
        made.append(path)
        return path

    async def fake_ff(args, dest):
        return False, "Error while opening encoder for output stream"

    monkeypatch.setattr(vp, "_tmp_mp4", track)
    _patch_tools(monkeypatch, {"video_codec": "vp9", "audio_codec": "opus", "pix_fmt": None}, fake_ff)

    with pytest.raises(vp.VideoPrepError) as exc:
        asyncio.run(vp.normalize_video(str(src)))
    assert "iOS" in str(exc.value)
    assert "encoder" in str(exc.value)
    assert made and all(not os.path.exists(p) for p in made)


def test_missing_ffmpeg_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda _name: None)
    with pytest.raises(vp.VideoPrepError) as exc:
        asyncio.run(vp.normalize_video("anything.mov"))
    assert "ffmpeg" in str(exc.value).lower()


def test_native_faststart_uses_the_shared_remux(tmp_path, monkeypatch):
    import telegram_api

    assert telegram_api.remux_faststart is vp.remux_faststart

    calls = []

    async def fake_ff(args, dest):
        calls.append(list(args))
        _write(dest, FASTSTART)
        return True, ""

    monkeypatch.setattr(vp.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(vp, "_ffmpeg_to_file", fake_ff)
    src = tmp_path / "in.mp4"
    _write(src, LATE_MOOV)
    out = asyncio.run(vp.remux_faststart(str(src)))
    try:
        assert out
        assert "+faststart" in calls[0]
        assert "copy" in calls[0]
        assert vp.moov_position(out) == "before"
    finally:
        if out:
            os.unlink(out)


def test_native_faststart_failure_returns_none(monkeypatch):
    made = []
    real_tmp = vp._tmp_mp4

    def track():
        path = real_tmp()
        made.append(path)
        return path

    async def fake_ff(_args, _dest):
        return False, "fail"

    monkeypatch.setattr(vp, "_tmp_mp4", track)
    monkeypatch.setattr(vp.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(vp, "_ffmpeg_to_file", fake_ff)
    assert asyncio.run(vp.remux_faststart("in.mp4")) is None
    assert made and all(not os.path.exists(p) for p in made)
