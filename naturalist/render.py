"""Deterministic naturalist prints and FederFunk's existing packed wire format."""
import hashlib
import io
import json
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, PngImagePlugin
import qrcode
from schedule import DEFAULT_SCHEDULE, validate_schedule

ROOT = Path(__file__).resolve().parent
COLORS = [(0, 0, 0), (255, 255, 255), (255, 255, 0),
          (255, 0, 0), (0, 0, 255), (0, 255, 0)]
CODES = bytes([0, 1, 2, 3, 5, 6] + [1] * 250)
DISPLAY_SATURATION = 1.30
DISPLAY_VALUE_GAMMA = .75
QR_INK = (20, 20, 20)
DEFAULTS = dict(show_names=False, show_scientific=False, show_counts=False,
                show_title=True, show_qr=True, show_all=True, scale="log", max_birds=8,
                style="collage", classic_media="photos", orientation="portrait",
                dashboard_url="http://localhost:8001/", variants={}, schedule=DEFAULT_SCHEDULE)


def catalogue(directory=None):
    directory = directory or ROOT / "artwork"
    manifest = json.loads((directory / "manifest.json").read_text())
    assets = manifest["assets"]
    seen = set()
    for asset in assets:
        if asset.get("review", {}).get("status") != "reviewed":
            raise ValueError("Artwork needs a recorded visual review before display")
        if asset["id"] in seen:
            raise ValueError("Duplicate artwork id")
        seen.add(asset["id"])
        path = (directory / asset["file"]).resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file():
            raise ValueError("Invalid artwork file")
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError("Artwork checksum mismatch")
    return assets


def validate_settings(patch, current, assets):
    from urllib.parse import urlsplit
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError("Unknown display setting")
    settings = {**DEFAULTS, **current, **patch}
    settings["schedule"] = validate_schedule(patch.get("schedule", {}), current.get("schedule"))
    for key in ("show_names", "show_scientific", "show_counts", "show_title", "show_qr", "show_all"):
        if type(settings[key]) is not bool:
            raise ValueError(f"{key} must be true or false")
    if settings["scale"] not in ("log", "linear", "equal"):
        raise ValueError("Choose logarithmic, linear, or equal sizing")
    if type(settings["max_birds"]) is not int or not 1 <= settings["max_birds"] <= 12:
        raise ValueError("Choose between 1 and 12 birds")
    if settings["orientation"] not in ("portrait", "landscape"):
        raise ValueError("Choose portrait or landscape")
    if settings["style"] not in ("collage", "classic", "field_guide"):
        raise ValueError("Choose a supported presentation style")
    if settings["classic_media"] not in ("photos", "drawings"):
        raise ValueError("Choose photos or historical drawings for the classic display")
    url = settings["dashboard_url"]
    if not isinstance(url, str) or len(url) > 200:
        raise ValueError("Dashboard URL must be at most 200 characters")
    parsed = urlsplit(url)
    if url:
        _ = parsed.port  # Validate malformed and out-of-range ports as well.
    if url and (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or any(ord(c) < 33 for c in url)):
        raise ValueError("Use a complete http(s) dashboard URL without credentials")
    if settings["show_qr"] and not url:
        raise ValueError("Enter the dashboard URL before enabling its QR code")
    variants = settings["variants"]
    choices = {a["id"]: a["scientific_name"] for a in assets}
    if not isinstance(variants, dict) or len(variants) > len(assets):
        raise ValueError("Invalid artwork choices")
    for species, variant in variants.items():
        if not isinstance(variant, str) or choices.get(variant) != species:
            raise ValueError("Artwork variant does not match this species")
    return settings


def area_weight(count, mode):
    count = max(0, count)
    return 1.0 if mode == "equal" else math.log1p(count) if mode == "log" else float(count)


@lru_cache(maxsize=64)
def font(size, italic=False):
    names = ["/usr/share/fonts/truetype/dejavu/DejaVuSerif" + ("-Italic" if italic else "") + ".ttf",
             "/System/Library/Fonts/Supplemental/Times New Roman" + (" Italic" if italic else "") + ".ttf"]
    for name in names:
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


def centered(draw, text, x, y, width, size=24, italic=False):
    while size > 12 and draw.textlength(text, font=font(size, italic)) > width:
        size -= 1
    while text and draw.textlength(text, font=font(size, italic)) > width:
        text = text[:-2] + "…"
    draw.text((x, y), text, anchor="mt", font=font(size, italic), fill=(35, 39, 33))


def choose_birds(birds, settings, assets):
    by_species = {}
    for asset in assets:  # Manifest order defines each species' curated default.
        by_species.setdefault(asset["scientific_name"], []).append(asset)
    chosen = []
    for bird in sorted(birds, key=lambda b: (-b["count"], b["scientific_name"])):
        options = by_species.get(bird["scientific_name"], [])
        if not options or bird["count"] <= 0:
            continue
        preferred = settings["variants"].get(bird["scientific_name"])
        asset = next((a for a in options if a["id"] == preferred), options[0])
        chosen.append((bird, asset))
        if not settings.get("show_all", True) and len(chosen) >= settings["max_birds"]:
            break
    return chosen


def compose(birds, settings, assets, artwork_dir=None):
    artwork_dir = artwork_dir or ROOT / "artwork"
    portrait = settings["orientation"] == "portrait"
    width, height = (1200, 1600) if portrait else (1600, 1200)
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    if settings["show_title"]:
        centered(draw, "H E A R D   T O D A Y", width / 2, height * .12, width * .7, 30)
    selected = choose_birds(birds, settings, assets)
    if not selected:
        centered(draw, "Listening for visitors", width / 2, height / 2, width * .7, 26, True)
    # All birds share one length multiplier. Thus visible ink area, rather
    # than width or bounding-box area, is proportional to the chosen weight.
    items = []
    for bird, asset in selected:
        with Image.open(artwork_dir / asset["file"]) as original:
            image = original.convert("RGBA")
        bounds = image.getbbox()
        if not bounds:
            continue
        image = image.crop(bounds)
        ink_area = sum(value * count for value, count in enumerate(image.getchannel("A").histogram())) / 255
        unit = math.sqrt(area_weight(bird["count"], settings["scale"]) / max(1, ink_area))
        items.append(dict(bird=bird, asset=asset, image=image,
                          w=image.width * unit, h=image.height * unit, weight=area_weight(bird["count"], settings["scale"])))
    if settings.get("style") == "field_guide":
        from field_guide import arrange
    else:
        from collage import arrange
    label_lines = int(settings["show_names"]) + int(settings["show_scientific"]) + int(settings["show_counts"])
    region = (width*.12, height*.23, width*.76, height*.64)
    for placement in arrange(items, region, label_lines):
        item = placement["item"]
        im = item["image"].resize((placement["w"], placement["h"]), Image.Resampling.LANCZOS)
        canvas.paste(im, (round(placement["x"]), round(placement["y"])), im)
        label_y = placement["y"] + placement["h"] + 10
        label_size = placement.get("label_size", 24)
        line_height = placement.get("label_line_height", 29)
        labels = [(item["bird"]["common_name"] if settings["show_names"] else "", False),
                  (item["bird"]["scientific_name"] if settings["show_scientific"] else "", True),
                  (f'{item["bird"]["count"]:,} heard' if settings["show_counts"] else "", False)]
        for text, italic in labels:
            if text:
                centered(draw, text, placement["cx"], label_y, placement["label_width"]-4,
                         max(12, label_size-2) if italic else label_size, italic)
                label_y += line_height
    add_qr(canvas, settings)
    attribution = []
    for _, asset in selected:
        attribution.append({key: asset.get(key) for key in ("title", "creator", "date", "source_url", "rights", "rights_url", "attribution")})
    canvas.info["Artwork sources"] = json.dumps(attribution, ensure_ascii=False)
    # The QR leads to full source/artist/license credits on the dashboard.
    # Preserve provenance in exported PNG metadata without printing a footer.
    return canvas, selected


def add_qr(canvas, settings):
    if settings["show_qr"]:
        width, height = canvas.size
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=2, border=4)
        qr.add_data(settings["dashboard_url"])
        qr.make(fit=True)
        im = qr.make_image(fill_color=QR_INK, back_color="white").convert("RGB")
        # Integer module sizing keeps the required quiet zone and crisp edges.
        module_count = len(qr.get_matrix())
        factor = 2  # Smallest practical modules at the panel's pixel density.
        im = im.resize((module_count*factor, module_count*factor), Image.Resampling.NEAREST)
        origin = (width-im.width-24, height-im.height-24)
        canvas.paste(im, origin)
        canvas.info["QR bounds"] = (*origin, origin[0]+im.width, origin[1]+im.height)


def png(image):
    output = io.BytesIO()
    metadata = PngImagePlugin.PngInfo()
    if "Artwork sources" in image.info:
        metadata.add_itxt("Artwork sources", image.info["Artwork sources"])
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def pack(canvas):
    if canvas.size not in ((1200, 1600), (1600, 1200)):
        raise ValueError("Unsupported print dimensions")
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for rgb in COLORS for v in rgb] + [255] * 750)
    output = display_colors(canvas)
    quantized = output.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
    restore_qr_finders(quantized, canvas, palette)
    quantized.info.update(canvas.info)
    # Driver already rotates landscape to native portrait. Encode the inverse
    # rotation here so a portrait print arrives upright, without firmware edits.
    wire = quantized.transpose(Image.Transpose.ROTATE_90) if canvas.width == 1200 else quantized
    codes = wire.tobytes().translate(CODES)
    frame = bytes((codes[i] << 4) | codes[i+1] for i in range(0, len(codes), 2))
    return frame, png(quantized.convert("RGB"))


def restore_qr_finders(quantized, canvas, palette):
    """Protect QR locator patterns while retaining softly dithered data modules."""
    bounds = canvas.info.get("QR bounds")
    if not bounds:
        return
    original = canvas.crop(bounds).convert("L")
    binary = original.point(lambda value: 0 if value < 128 else 255).convert("RGB")
    binary = binary.quantize(palette=palette, dither=Image.Dither.NONE)
    # compose() uses two-pixel modules with a four-module quiet zone.
    # Include that border, the seven-module finder and its one-module separator.
    span = (4 + 7 + 1) * 2
    width, height = binary.size
    for box in ((0, 0, span, span), (width-span, 0, width, span),
                (0, height-span, span, height)):
        quantized.paste(binary.crop(box), (bounds[0]+box[0], bounds[1]+box[1]))


def display_colors(canvas):
    """Lift colored feathers before dithering, preserving neutral ink and paper."""
    original = canvas.convert("RGB")
    hue, saturation, value = original.convert("HSV").split()
    red, green, blue = original.split()
    chroma = ImageChops.subtract(
        ImageChops.lighter(ImageChops.lighter(red, green), blue),
        ImageChops.darker(ImageChops.darker(red, green), blue))

    def ramp(low, high):
        return [round(255 * max(0, min(1, (i-low)/(high-low)))) for i in range(256)]

    # Fade in only on discernibly colored pixels. Protect muted feathers,
    # near-neutral lettering and deep shadows instead of lifting all blacks.
    mask = ImageChops.multiply(saturation.point(ramp(32, 96)), chroma.point(ramp(8, 32)))
    mask = ImageChops.multiply(mask, value.point(ramp(24, 64)))
    boosted = Image.merge("HSV", (
        hue,
        saturation.point([min(255, round(i * DISPLAY_SATURATION)) for i in range(256)]),
        value.point([round(255 * (i/255)**DISPLAY_VALUE_GAMMA) for i in range(256)]),
    )).convert("RGB")
    output = Image.composite(boosted, original, mask)
    # Keep the deliberately softened QR independent of artwork adjustments.
    if "QR bounds" in canvas.info:
        bounds = canvas.info["QR bounds"]
        output.paste(canvas.crop(bounds), bounds[:2])
    output.info.update(canvas.info)
    return output


def etag(data):
    return '"' + hashlib.sha256(data).hexdigest() + '"'
