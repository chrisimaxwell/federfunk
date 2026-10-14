"""Pixel-level checks for the print output, QR readability and quiet footer."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageChops, ImageEnhance, ImageFilter
import qrcode
import render

try:
    import zxingcpp
except ImportError:
    zxingcpp = None


def qr_canvas(url="http://192.0.2.67:8001/", size=(1200, 1600)):
    code = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,
                         box_size=2, border=4)
    code.add_data(url)
    code.make(fit=True)
    qr = code.make_image(fill_color=render.QR_INK, back_color="white").convert("RGB")
    binary = code.make_image(fill_color="black", back_color="white").convert("RGB")
    canvas = Image.new("RGB", size, "white")
    x, y = size[0]-qr.width-24, size[1]-qr.height-24
    canvas.paste(qr, (x, y))
    canvas.info["QR bounds"] = (x, y, x+qr.width, y+qr.height)
    return canvas, binary


class DisplayRenderTests(unittest.TestCase):
    def test_color_boost_is_a_copy_and_keeps_neutrals_shadows_and_qr_unchanged(self):
        canvas = Image.new("RGB", (10, 2), "white")
        for position, color in [((0, 0), (0, 0, 0)), ((1, 0), (128, 128, 128)),
                                ((2, 0), (180, 110, 70)), ((4, 0), (90, 140, 160)),
                                ((6, 0), (35, 39, 33)), ((7, 0), (128, 132, 136)),
                                ((8, 0), (12, 18, 24)), ((9, 0), (55, 95, 150))]:
            canvas.putpixel(position, color)
        canvas.info["QR bounds"] = (4, 0, 6, 2)
        canvas.info["Artwork sources"] = "[]"
        before = canvas.tobytes()
        output = render.display_colors(canvas)
        self.assertIsNot(output, canvas)
        self.assertEqual(canvas.tobytes(), before)
        for position in ((0, 0), (1, 0), (3, 0), (6, 0), (7, 0), (8, 0)):
            self.assertEqual(output.getpixel(position), canvas.getpixel(position))
        for position in ((2, 0), (9, 0)):
            old, new = canvas.getpixel(position), output.getpixel(position)
            self.assertGreater(max(new)-min(new), max(old)-min(old))
            self.assertGreater(max(new), max(old))
            self.assertLess(max(new)-max(old), 40)
            self.assertLess(sum(abs(a-b) for a, b in zip(old, new)), 90)
        self.assertEqual(output.crop(canvas.info["QR bounds"]).tobytes(),
                         canvas.crop(canvas.info["QR bounds"]).tobytes())
        self.assertEqual(output.info, canvas.info)

    def test_colored_feathers_use_more_pigment_and_less_black_overall(self):
        palette = Image.new("P", (1, 1))
        palette.putpalette([v for color in render.COLORS for v in color] + [255] * 750)
        black_counts = [0, 0]
        for color, pigment in (((160, 65, 45), (255, 0, 0)),
                               ((170, 145, 55), (255, 255, 0)),
                               ((45, 75, 160), (0, 0, 255))):
            with self.subTest(color=color):
                canvas = Image.new("RGB", (128, 128), color)
                previous = ImageEnhance.Color(canvas).enhance(1.18)
                current = render.display_colors(canvas)
                counts = []
                for output in (previous, current):
                    quantized = output.quantize(palette=palette,
                                                 dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")
                    counts.append({rgb: count for count, rgb in quantized.getcolors()})
                self.assertGreater(counts[1].get(pigment, 0), counts[0].get(pigment, 0))
                for index, count in enumerate(counts):
                    black_counts[index] += count.get((0, 0, 0), 0)
        # Individual saturated reds can use black instead of white for shading;
        # across these hues the added pigment must displace more black overall.
        self.assertLess(black_counts[1], black_counts[0])

    def test_preview_matches_every_packed_pixel_in_both_orientations(self):
        wire_palette = [255] * 768
        for code, color in zip((0, 1, 2, 3, 5, 6), render.COLORS):
            wire_palette[3*code:3*code+3] = color
        for size in ((1200, 1600), (1600, 1200)):
            with self.subTest(size=size):
                canvas, _ = qr_canvas(size=size)
                for index, color in enumerate(render.COLORS):
                    canvas.paste(color, (index*25, 0, index*25+20, 20))
                canvas.paste((145, 103, 51), (90, 200, 190, 280))
                before = canvas.tobytes()
                frame, preview_bytes = render.pack(canvas)
                preview = Image.open(io.BytesIO(preview_bytes)).convert("RGB")
                self.assertEqual(len(frame), 960000)
                self.assertEqual(canvas.tobytes(), before)
                colors = {color for _, color in preview.getcolors(maxcolors=256)}
                self.assertEqual(colors, set(render.COLORS))
                pixels = bytearray(len(frame)*2)
                pixels[::2] = bytes(value >> 4 for value in frame)
                pixels[1::2] = bytes(value & 15 for value in frame)
                self.assertLessEqual(set(pixels), {0, 1, 2, 3, 5, 6})
                decoded = Image.frombytes("P", (1600, 1200), bytes(pixels))
                decoded.putpalette(wire_palette)
                decoded = decoded.convert("RGB")
                if size == (1200, 1600):
                    decoded = decoded.transpose(Image.Transpose.ROTATE_270)
                self.assertEqual(decoded.size, preview.size)
                self.assertIsNone(ImageChops.difference(decoded, preview).getbbox())

    def test_qr_finders_and_quiet_zone_are_exact_but_data_stays_softened(self):
        canvas, binary = qr_canvas()
        _, preview_bytes = render.pack(canvas)
        actual = Image.open(io.BytesIO(preview_bytes)).crop(canvas.info["QR bounds"])
        width, height = actual.size
        for box in ((0, 0, 24, 24), (width-24, 0, width, 24), (0, height-24, 24, height)):
            self.assertEqual(actual.crop(box).tobytes(), binary.crop(box).tobytes())
        for box in ((0, 0, width, 8), (0, height-8, width, height),
                    (0, 0, 8, height), (width-8, 0, width, height)):
            self.assertEqual(actual.crop(box).getextrema(), ((255, 255),)*3)
        self.assertIsNotNone(ImageChops.difference(actual, binary).getbbox())
        self.assertLessEqual({color for _, color in actual.getcolors(maxcolors=256)},
                             {(0, 0, 0), (255, 255, 255)})

    def test_provenance_survives_export_without_printing_a_footer(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "bird.png"
            Image.new("RGBA", (80, 110), (145, 103, 51, 255)).save(path)
            source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            asset = dict(id="example", scientific_name="Example species", common_name="Example",
                         file="bird.png", title="Historical illustration", creator="Example artist",
                         date="1900", rights="CC BY 2.0", attribution="Example source credit",
                         source_url="https://example.org/source", rights_url="https://example.org/rights")
            birds = [dict(scientific_name="Example species", common_name="Example", count=5)]
            settings = {**render.DEFAULTS, "show_title": False, "show_qr": False}
            canvas, _ = render.compose(birds, settings, [asset], directory)
            alternative, _ = render.compose(birds, settings, [{**asset, "rights": "Public domain"}], directory)
            self.assertEqual(canvas.tobytes(), alternative.tobytes())
            footer = canvas.crop((0, 1440, 1200, 1600))
            self.assertEqual(footer.getextrema(), ((255, 255),)*3)
            _, preview_bytes = render.pack(canvas)
            for exported in (render.png(canvas), preview_bytes):
                reopened = Image.open(io.BytesIO(exported))
                sources = json.loads(reopened.info["Artwork sources"])
                self.assertEqual(sources[0]["creator"], asset["creator"])
                self.assertEqual(sources[0]["rights_url"], asset["rights_url"])
                self.assertEqual(sources[0]["attribution"], asset["attribution"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source_hash)

    @unittest.skipIf(zxingcpp is None, "Optional local ZXing decoder is unavailable")
    def test_dimmed_qr_decodes_from_final_preview(self):
        urls = ("http://192.0.2.67:8001/", "https://example.org/" + "abcdefghij12"*5,
                "https://example.org/" + "abcdefghij12"*15)
        for url in urls:
            canvas, _ = qr_canvas(url)
            _, preview_bytes = render.pack(canvas)
            qr = Image.open(io.BytesIO(preview_bytes)).crop(canvas.info["QR bounds"])
            for blur in (0, .4, .6):
                with self.subTest(length=len(url), blur=blur):
                    image = qr if not blur else qr.filter(ImageFilter.GaussianBlur(blur))
                    decoded = zxingcpp.read_barcode(image)
                    self.assertIsNotNone(decoded)
                    self.assertEqual(decoded.text, url)


if __name__ == "__main__":
    unittest.main()
