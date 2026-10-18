"""Bring every uploaded video to an iOS-safe MP4 before it is stored.

Safari and the Telegram in-app browser only start playing a Telegraph <video>
(preload=auto) when the file is an H.264/AAC MP4 with the moov atom before
mdat. Phone recordings often have moov at the end, and HEVC/webm/wmv/avi need
a real transcode. Native Telegram sends reuse remux_faststart from here so
the ffmpeg invocation lives in one place.
"""
import asyncio
import json
import logging
import os
import shutil
import tempfile

logger = logging.getLogger("video_prep")

# Object key suffix and Content-Type for every video stored for Telegraph/R2.
MP4_EXTENSION = ".mp4"
MP4_CONTENT_TYPE = "video/mp4"


def video_object_key(file_id: str) -> str:
    """R2/S3 key for a normalized video. The suffix is always a lowercase .mp4."""
    return f"video/{file_id}{MP4_EXTENSION}"

_H264 = {"h264", "avc", "avc1"}
_AAC = {"aac", "mp4a"}
# yuvj420p is full-range 4:2:0 and plays on iOS; 10-bit (yuv420p10le) does not.
_YUV420 = {"yuv420p", "yuvj420p"}


class VideoPrepError(Exception):
    """Видео не удалось привести к MP4 H.264/AAC с moov перед mdat."""


def choose_normalize_action(video_codec, audio_codec, pix_fmt, moov) -> str:
    """Return 'remux' or 'transcode'.

    Remux (stream copy + faststart) only when the file is already H.264 with
    AAC or no audio, 4:2:0, and actually contains a moov atom (wherever it
    sits). HEVC, VP9/AV1, non-AAC audio, 10-bit, webm/wmv/avi, and files
    without a moov atom are transcoded to H.264 yuv420p + AAC.
    """
    vc = (video_codec or "").strip().lower()
    ac = (audio_codec or "").strip().lower()
    pix = (pix_fmt or "").strip().lower()
    if vc not in _H264:
        return "transcode"
    if ac and ac not in _AAC:
        return "transcode"
    if pix and pix not in _YUV420:
        return "transcode"
    if moov not in ("before", "after"):
        return "transcode"
    return "remux"


def remux_args(src: str, dest: str) -> list:
    """ffmpeg argv: repack into MP4 with moov before mdat, no re-encode."""
    return [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", src, "-c", "copy", "-movflags", "+faststart", "-f", "mp4", dest,
    ]


def transcode_args(src: str, dest: str) -> list:
    """ffmpeg argv: H.264 yuv420p + AAC MP4 with moov before mdat."""
    return [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error",
        "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "veryfast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-f", "mp4", dest,
    ]


def moov_position(path: str) -> str:
    """Where moov sits relative to mdat: 'before', 'after', or 'absent'.

    Reads only top-level box headers, so a multi-gigabyte mdat is not loaded.
    """
    try:
        file_size = os.path.getsize(path)
    except OSError:
        return "absent"
    moov_at = None
    mdat_at = None
    try:
        with open(path, "rb") as fh:
            offset = 0
            while offset + 8 <= file_size:
                fh.seek(offset)
                header = fh.read(8)
                if len(header) < 8:
                    break
                size = int.from_bytes(header[:4], "big")
                typ = header[4:8]
                header_len = 8
                if size == 1:
                    ext = fh.read(8)
                    if len(ext) < 8:
                        break
                    size = int.from_bytes(ext, "big")
                    header_len = 16
                elif size == 0:
                    size = file_size - offset
                if size < header_len or offset + size > file_size:
                    break
                if typ == b"moov" and moov_at is None:
                    moov_at = offset
                elif typ == b"mdat" and mdat_at is None:
                    mdat_at = offset
                if moov_at is not None and mdat_at is not None:
                    break
                offset += size
    except OSError:
        return "absent"
    if moov_at is None:
        return "absent"
    if mdat_at is None or moov_at < mdat_at:
        return "before"
    return "after"


def _tmp_mp4() -> str:
    fd, path = tempfile.mkstemp(prefix="vidnorm_", suffix=MP4_EXTENSION)
    os.close(fd)
    return path


def _unlink(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


def _stderr_tail(text: str, limit: int = 300) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[-limit:]


async def _ffmpeg_to_file(args: list, dest: str):
    """Run ffmpeg. Returns (ok, stderr_text). ok requires a non-empty dest."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
    except Exception as e:
        return False, str(e)
    text = (err or b"").decode("utf-8", "replace").strip()
    ok = proc.returncode == 0 and os.path.exists(dest) and os.path.getsize(dest) > 0
    return ok, text


async def probe_media(path: str) -> dict:
    """ffprobe the first video/audio streams. Empty dict if probe fails."""
    if not shutil.which("ffprobe"):
        return {}
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error",
            "-show_entries", "stream=codec_type,codec_name,pix_fmt",
            "-of", "json", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            return {}
        info = json.loads(out or b"{}")
    except Exception:
        return {}
    video = audio = pix = None
    for st in info.get("streams") or []:
        if st.get("codec_type") == "video" and video is None:
            video = (st.get("codec_name") or "").lower() or None
            pix = (st.get("pix_fmt") or "").lower() or None
        elif st.get("codec_type") == "audio" and audio is None:
            audio = (st.get("codec_name") or "").lower() or None
    return {"video_codec": video, "audio_codec": audio, "pix_fmt": pix}


async def remux_faststart(path: str):
    """Best-effort faststart remux for native Telegram sends.

    Returns a new temp path, or None if ffmpeg is missing or the remux failed.
    Callers then send the original file. Does not raise.
    """
    if not shutil.which("ffmpeg"):
        return None
    dest = _tmp_mp4()
    try:
        ok, _err = await _ffmpeg_to_file(remux_args(path, dest), dest)
        if ok:
            return dest
    except Exception:
        logger.warning("faststart remux failed", exc_info=True)
    _unlink(dest)
    return None


async def _run_plan(args_fn, src: str):
    """Run one ffmpeg plan. Returns (path, stderr) on success, (None, stderr) on failure."""
    dest = _tmp_mp4()
    ok, err = await _ffmpeg_to_file(args_fn(src, dest), dest)
    if ok and moov_position(dest) == "before":
        return dest, err
    _unlink(dest)
    return None, err


async def normalize_video(path: str) -> str:
    """Return a new temp MP4 (moov before mdat) ready to store.

    The caller owns the returned file and must delete it. The source is not
    modified. Raises VideoPrepError if the file cannot be made iOS-safe —
    callers must not upload the original or publish a Telegraph page.
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise VideoPrepError(
            "Не удалось подготовить видео: на сервере нет ffmpeg. "
            "Установите ffmpeg и повторите загрузку."
        )
    info = await probe_media(path)
    moov = moov_position(path)
    action = choose_normalize_action(
        info.get("video_codec"), info.get("audio_codec"), info.get("pix_fmt"), moov,
    )
    logger.info(
        "normalize video action=%s codec=%s audio=%s pix=%s moov=%s",
        action, info.get("video_codec"), info.get("audio_codec"), info.get("pix_fmt"), moov,
    )
    errors = []
    if action == "remux":
        dest, err = await _run_plan(remux_args, path)
        if dest:
            return dest
        if err:
            errors.append(err)
        logger.warning("faststart remux unusable, transcoding instead")
    dest, err = await _run_plan(transcode_args, path)
    if dest:
        return dest
    if err:
        errors.append(err)
    tail = _stderr_tail(errors[-1]) if errors else ""
    msg = "Не удалось подготовить видео для iOS (нужен MP4 H.264/AAC с moov в начале)."
    if tail:
        msg = f"{msg} {tail}"
    raise VideoPrepError(msg)
