"""The previous local FederFunk photo layout, adapted to both orientations.

The older layout came from bird-feed/feed.py, not an upstream Thomas renderer.
Photos are fetched only through the configured BirdNET-Go image proxy. Credits
remain in exported PNG metadata and the dashboard; no footer is drawn here.
"""

from datetime import date as calendar_date
from functools import lru_cache
import io
import json
import math
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageDraw, ImageFont, ImageOps


MAX_PHOTO_BYTES = 10_000_000
MAX_INFO_BYTES = 128_000
MAX_PHOTO_PIXELS = 20_000_000
HTTP_TIMEOUT = 8
BLUE = (0, 0, 255)
BLACK = (0, 0, 0)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None  # Never follow a proxy redirect to an external image host.


def _fetch(base, path, limit):
    parsed = urlsplit(base)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Use a BirdNET base URL without credentials, query, or fragment")
    parsed.port
    request = Request(base.rstrip("/") + path, headers={"User-Agent": "FederFunk-Classic/1.0"})
    with build_opener(_NoRedirect()).open(request, timeout=HTTP_TIMEOUT) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("BirdNET photo response is too large")
    return data


def _text(value, limit=500):
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _link(value):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return ""
    try:
        parsed = urlsplit(value)
        parsed.port
        if parsed.scheme in ("http", "https") and parsed.hostname and not (parsed.username or parsed.password):
            return value
    except ValueError:
        pass
    return ""


@lru_cache(maxsize=8)
def _cached_photo(base, name):
    if not isinstance(name, str) or not name.strip() or len(name) > 200 or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid species name")
    info = json.loads(_fetch(base, "/api/v2/media/species-image/info?" + urlencode({"name": name}), MAX_INFO_BYTES))
    if not isinstance(info, dict):
        raise ValueError("Invalid photo attribution response")
    author, rights = _text(info.get("authorName")), _text(info.get("licenseName"))
    license_url = _link(info.get("licenseURL"))
    if not author or not rights or not license_url:
        raise ValueError("Photo attribution or license information is unavailable")
    image_path = "/api/v2/media/image/" + quote(name, safe="")
    data = _fetch(base, image_path, MAX_PHOTO_BYTES)
    with Image.open(io.BytesIO(data)) as original:
        if (original.format not in ("JPEG", "PNG", "WEBP") or original.width <= 0
                or original.height <= 0 or original.width * original.height > MAX_PHOTO_PIXELS
                or getattr(original, "is_animated", False)):
            raise ValueError("Unsupported or oversized species photograph")
        original.load()  # Reject truncated/corrupt files before putting them in cache.
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        background = Image.new("RGB", image.size, "white")
        background.paste(image, (0, 0), image.getchannel("A"))
    author_url = _link(info.get("authorURL"))
    source_url = _link(info.get("sourceURL")) or _link(info.get("url"))
    # Source URLs are links only; image content always comes from image_path.
    # Do not retain arbitrary API fields, recordings, or the private base URL.
    credits = dict(title=f"{name} — species photograph", creator=author,
                   rights=rights, rights_url=license_url, source_url=source_url,
                   author_url=author_url, source_provider=_text(info.get("sourceProvider")),
                   image_path=image_path, scientific_name=name,
                   attribution=f"{author}; {rights}. Resized, chromatic boost applied, and converted to six colors for e-paper.")
    return background, credits


def photo(base, name):
    """Return an owned image and credit dict, backed by an eight-species cache."""
    image, credits = _cached_photo(base, name)
    return image.copy(), dict(credits)


@lru_cache(maxsize=64)
def _font(size, bold=False):
    filename = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    candidates = ["/usr/share/fonts/truetype/dejavu/" + filename,
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
                  else "/System/Library/Fonts/Supplemental/Arial.ttf"]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    from render import font
    return font(size)


def _label(draw, xy, text, size, width, bold=False, fill=BLACK):
    text = _text(text, 600)
    while size > 8 and draw.textlength(text, font=_font(size, bold)) > width:
        size -= 1
    while text and draw.textlength(text, font=_font(size, bold)) > width:
        text = text[:-2] + "…" if len(text) > 1 else ""
    draw.text(xy, text, font=_font(size, bold), fill=fill)


def _positive_birds(birds, settings):
    rows = sorted((bird for bird in birds if bird.get("count", 0) > 0),
                  key=lambda bird: (-bird["count"], bird["scientific_name"]))
    return rows if settings.get("show_all", True) else rows[:settings.get("max_birds", 8)]


def _daily_list(draw, birds, settings, region):
    if not birds:
        return
    x, y, width, height = region
    names, scientific, counts = (settings.get(key, False) for key in ("show_names", "show_scientific", "show_counts"))
    lines = max(1, int(names) + int(scientific))
    # Counts share the first line. Add columns only when one would make the
    # names too small; the complete daily list is never silently truncated.
    columns = 1
    for candidate in range(1, max(1, int(width // 140)) + 1):
        columns = candidate
        rows = math.ceil(len(birds) / columns)
        size = min(24, int((height / rows - 10) / lines) - 3)
        if size >= 18:
            break
    rows = math.ceil(len(birds) / columns)
    cell_height = height / rows
    size = max(8, min(24, int((cell_height - 8) / lines) - 2))
    cell_width = (width - 22 * (columns - 1)) / columns
    for index, bird in enumerate(birds):
        col, row = divmod(index, rows)
        left, top = x + col * (cell_width + 22), y + row * cell_height
        count_text = f'{bird["count"]:,}' if counts else ""
        count_width = draw.textlength(count_text, font=_font(size)) + 12 if counts else 0
        name_width = max(20, cell_width - count_width)
        if names:
            _label(draw, (left, top), bird.get("common_name") or bird["scientific_name"], size, name_width, True)
        if scientific:
            _label(draw, (left, top + (size + 3 if names else 0)), bird["scientific_name"],
                   max(8, size - 2), cell_width if names else name_width)
        if counts:
            _label(draw, (left + cell_width - count_width + 12, top), count_text, size, count_width)
        if not (names or scientific or counts):
            # With labels hidden, one quiet bar still represents each species.
            length = max(2, (cell_width - 12) * bird["count"] / birds[0]["count"])
            draw.rectangle((left, top + 5, left + length, top + 9), fill=BLUE)


def compose(birds, settings, picture, credits, date, featured):
    """Return a classic RGB canvas; the caller adds the shared corner QR."""
    portrait = settings.get("orientation", "portrait") == "portrait"
    width, height = (1200, 1600) if portrait else (1600, 1200)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    title = settings.get("show_title", True)
    try:
        day = calendar_date.fromisoformat(str(date)[:10]).strftime("%b %d, %Y")
    except ValueError:
        day = _text(str(date), 40)
    if title:
        _label(draw, (64, 44), "F E D E R F U N K", 27, width - 128, True, BLUE)
        _label(draw, (64, 94), "Backyard visitors", 62 if portrait else 70, width - 128, True)
        _label(draw, (64, 185), day, 24, width - 128)
    displayed = _positive_birds(birds, settings)
    if portrait:
        picture_box = (64, 250, 1072, 560)
        caption_y, caption_width = 834, 1072
        list_title, list_region = (64, 980), (64, 1070, 1072, 320)
    else:
        picture_box = (64, 270, 920, 650)
        caption_y, caption_width = 943, 950
        list_title, list_region = (1090, 235), (1090, 330, 446, 670)
        draw.line((1040, 229, 1040, 1090), fill=BLACK, width=2)
    px, py, pw, ph = picture_box
    if picture is not None:
        fitted = ImageOps.contain(picture.convert("RGBA"), (pw, ph), Image.Resampling.LANCZOS)
        canvas.paste(fitted, (px + (pw - fitted.width) // 2, py + (ph - fitted.height) // 2), fitted)
    else:
        message = ("Listening for visitors" if featured is None else
                   "Illustration not available" if settings.get("classic_media") == "drawings"
                   else "Photograph not available")
        _label(draw, (px + 24, py + ph // 2), message, 28, pw - 48)
    cursor = caption_y
    if featured:
        for enabled, text, size, bold in (
                (settings.get("show_names", False), featured.get("common_name") or featured["scientific_name"], 48, True),
                (settings.get("show_scientific", False), featured["scientific_name"], 26, False),
                (settings.get("show_counts", False), f'{featured["count"]:,} detections today', 24, False)):
            if enabled:
                _label(draw, (64, cursor), text, size, caption_width, bold)
                cursor += size + 8
    if title:
        _label(draw, list_title, "HEARD TODAY", 23, list_region[2], True, BLUE)
    if settings.get("show_counts", False):
        _label(draw, (list_title[0], list_title[1] + 34), f"{len(displayed)} species", 22, list_region[2])
    _daily_list(draw, displayed, settings, list_region)
    # No footer text: both QR/web credits and PNG metadata carry provenance.
    canvas.info["Artwork sources"] = json.dumps([dict(credits)] if credits and picture is not None else [], ensure_ascii=False)
    return canvas
