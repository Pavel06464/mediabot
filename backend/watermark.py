import io
import os
import base64
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = os.path.join(os.path.dirname(__file__), "assets", "DejaVuSans-Bold.ttf")

DEFAULT = {
    "enabled": False,
    "type": "text",       # text | logo
    "text": "@mychannel",
    "color": "white",     # white | black
    "logo_b64": "",
    "position": "bottom-right",
    "size": 15,           # % of image width
    "opacity": 50,        # 0-100
}


def _pos_xy(pos, cw, ch, w, h, margin):
    parts = (pos or "bottom-right").split("-")
    v, hh = (parts + ["bottom", "right"])[:2] if len(parts) == 2 else ("bottom", "right")
    xmap = {"left": margin, "center": (cw - w) // 2, "right": cw - w - margin}
    ymap = {"top": margin, "middle": (ch - h) // 2, "bottom": ch - h - margin}
    return xmap.get(hh, cw - w - margin), ymap.get(v, ch - h - margin)


def apply_watermark(image_bytes: bytes, cfg: dict) -> bytes:
    if not cfg or not cfg.get("enabled"):
        return image_bytes
    try:
        base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    except Exception:
        return image_bytes

    cw, ch = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    opacity = max(0, min(255, int(255 * (cfg.get("opacity", 50) / 100))))
    size_pct = max(3, min(80, cfg.get("size", 15)))
    margin = int(min(cw, ch) * 0.02) + 6
    pos = cfg.get("position", "bottom-right")

    try:
        if cfg.get("type") == "logo" and cfg.get("logo_b64"):
            raw = base64.b64decode(cfg["logo_b64"].split(",")[-1])
            logo = Image.open(io.BytesIO(raw)).convert("RGBA")
            target_w = max(1, int(cw * size_pct / 100))
            ratio = target_w / logo.width
            logo = logo.resize((target_w, max(1, int(logo.height * ratio))))
            alpha = logo.split()[3].point(lambda p: int(p * opacity / 255))
            logo.putalpha(alpha)
            x, y = _pos_xy(pos, cw, ch, logo.width, logo.height, margin)
            overlay.paste(logo, (x, y), logo)
        else:
            text = cfg.get("text") or "watermark"
            font_size = max(12, int(cw * size_pct / 100))
            font = ImageFont.truetype(FONT_PATH, font_size)
            draw = ImageDraw.Draw(overlay)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x, y = _pos_xy(pos, cw, ch, tw, th + bbox[1], margin)
            rgb = (255, 255, 255) if cfg.get("color") == "white" else (0, 0, 0)
            shadow = (0, 0, 0) if cfg.get("color") == "white" else (255, 255, 255)
            draw.text((x + 2, y + 2), text, font=font, fill=(*shadow, int(opacity * 0.5)))
            draw.text((x, y), text, font=font, fill=(*rgb, opacity))
    except Exception:
        return image_bytes

    out = Image.alpha_composite(base, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_preview(cfg: dict) -> str:
    w, h = 640, 400
    img = Image.new("RGB", (w, h), (120, 132, 148))
    d = ImageDraw.Draw(img)
    d.rectangle([0, h // 2, w, h], fill=(38, 44, 56))
    try:
        f = ImageFont.truetype(FONT_PATH, 26)
        d.text((20, 18), "Пример фото", fill=(235, 235, 235), font=f)
    except Exception:
        pass
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    wm = apply_watermark(buf.getvalue(), {**DEFAULT, **(cfg or {}), "enabled": True})
    return "data:image/jpeg;base64," + base64.b64encode(wm).decode()
