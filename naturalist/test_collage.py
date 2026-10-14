"""Geometry regressions for real art and awkward, thin silhouettes."""
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from collage import arrange


PORTRAIT = (144, 368, 912, 1024)
LANDSCAPE = (192, 276, 1216, 768)


def item(image, weight, identity):
    image = image.crop(image.getbbox())
    area = sum(value * count for value, count in enumerate(image.getchannel("A").histogram())) / 255
    unit = math.sqrt(weight / area)
    return dict(image=image, w=image.width * unit, h=image.height * unit,
                weight=weight, identity=identity)


class CollageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parent / "artwork"
        # Deliberately read the repository art directly: these tests verify
        # geometric behavior, independently of catalogue publication status.
        assets = json.loads((root / "manifest.json").read_text())["assets"]
        cls.drawings = {}
        for asset in assets:
            if asset["scientific_name"] not in cls.drawings:
                with Image.open(root / asset["file"]) as original:
                    cls.drawings[asset["scientific_name"]] = original.convert("RGBA")

    def assert_layout(self, items, region, lines, placements):
        self.assertEqual(len(placements), len(items))
        self.assertEqual({p["item"]["identity"] for p in placements}, {i["identity"] for i in items})
        left, top, width, height = region
        occupied = Image.new("L", (math.ceil(left + width + 2), math.ceil(top + height + 2)))
        scale_lower, scale_upper = 0, math.inf
        for placement in placements:
            # Verify actual rendered pixels, not the implementation's coarse
            # collision map. Thin toes and antialiased outlines count too.
            picture = placement["item"]["image"].resize((placement["w"], placement["h"]), Image.Resampling.LANCZOS)
            alpha = picture.getchannel("A").point(lambda value: 255 if value else 0)
            mask = Image.new("L", occupied.size)
            mask.paste(alpha, (round(placement["x"]), round(placement["y"])))
            if lines:
                self.assertGreaterEqual(placement["label_size"], 12)
                self.assertGreaterEqual(placement["label_line_height"], placement["label_size"])
                ImageDraw.Draw(mask).rectangle((round(placement["cx"] - placement["label_width"] / 2),
                                               round(placement["y"] + placement["h"] + 10),
                                               round(placement["cx"] + placement["label_width"] / 2),
                                               round(placement["y"] + placement["h"] + placement["label_height"])), fill=255)
            bounds = mask.getbbox()
            self.assertIsNotNone(bounds)
            self.assertGreaterEqual(bounds[0], left)
            self.assertGreaterEqual(bounds[1], top)
            self.assertLessEqual(bounds[2], left + width)
            self.assertLessEqual(bounds[3], top + height)
            self.assertIsNone(ImageChops.multiply(mask, occupied).getbbox(), placement["item"]["identity"])
            occupied = ImageChops.lighter(occupied, mask)
            # There must be one common multiplier consistent with every
            # output dimension, allowing only final integer-pixel rounding.
            for dimension in ("w", "h"):
                unit = placement["item"][dimension]
                pixels = placement[dimension]
                scale_lower = max(scale_lower, (pixels - .5) / unit if pixels > 1 else 0)
                scale_upper = min(scale_upper, (pixels + .5) / unit)
        self.assertLessEqual(scale_lower, scale_upper + 1e-9)

    def actual_items(self, mode="equal", maximum=None):
        names = sorted(self.drawings, key=lambda name: (name != "Haemorhous mexicanus", name))
        items = []
        for index, name in enumerate(names[:maximum]):
            detections = 1_000_000 if index == 0 else max(1, 25 - index)
            weight = 1 if mode == "equal" else math.log1p(detections) if mode == "log" else detections
            items.append(item(self.drawings[name], weight, name))
        return items

    def test_real_twelve_and_full_collection_with_every_label(self):
        self.assertGreater(len(self.drawings), 12)
        for maximum in (12, None):
            for region in (PORTRAIT, LANDSCAPE):
                with self.subTest(maximum=maximum, region=region):
                    items = self.actual_items(maximum=maximum)
                    self.assert_layout(items, region, 3, arrange(items, region, 3))

    def test_frequency_scaling_and_sparse_label_combinations(self):
        # All distinct label counts are exercised; names, scientific names
        # and counts share the same reserved line geometry.
        for mode, count, lines, region in (("log", None, 0, PORTRAIT),
                                           ("linear", None, 0, LANDSCAPE),
                                           ("equal", 1, 1, PORTRAIT),
                                           ("log", 2, 2, LANDSCAPE),
                                           ("linear", 8, 3, PORTRAIT)):
            with self.subTest(mode=mode, count=count, lines=lines):
                items = self.actual_items(mode, count)
                self.assert_layout(items, region, lines, arrange(items, region, lines))

    def test_fallback_keeps_thin_legs_long_tails_and_all_birds(self):
        items = []
        for index in range(25):
            width, height = ((35, 180), (180, 40), (90, 110))[index % 3]
            image = Image.new("RGBA", (width, height))
            draw = ImageDraw.Draw(image)
            draw.ellipse((2, 2, width - 3, height * .65), fill=(50, 70, 40, 255))
            draw.line((width // 2, height // 2, width - 1, height - 1), fill=(30, 40, 30, 255), width=1)
            draw.line((width // 2, height // 2, 0, height - 1), fill=(30, 40, 30, 255), width=1)
            items.append(item(image, 1 + index % 4, str(index)))
        # A heuristic is permitted to fail. Its fallback must still preserve
        # every silhouette and all labels at a common scale in either canvas.
        with patch("collage._silhouette_layout", return_value=None):
            for region in (PORTRAIT, LANDSCAPE):
                with self.subTest(region=region):
                    placements = arrange(items, region, 3)
                    self.assert_layout(items, region, 3, placements)
                    self.assertGreater(min(p["h"] for p in placements), 10)

    def test_empty_collection(self):
        self.assertEqual(arrange([], PORTRAIT, 0), [])


if __name__ == "__main__":
    unittest.main()
