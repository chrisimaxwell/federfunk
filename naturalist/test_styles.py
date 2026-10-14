"""Presentation choices preserve observations, provenance, and saved images."""
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

import classic
import field_guide
import render
import server


class StyleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.assets, self.birds = [], []
        for index in range(14):
            image = Image.new("RGBA", (60 + index * 3, 90 + index * 2))
            ImageDraw.Draw(image).ellipse((1, 1, image.width - 2, image.height - 2), fill=(20 + index * 9, 80, 50, 255))
            filename = f"bird-{index}.png"
            image.save(self.root / filename)
            self.assets.append(dict(id=f"art-{index}", scientific_name=f"Species {index}", common_name=f"Bird {index}",
                                    file=filename, sha256=hashlib.sha256((self.root / filename).read_bytes()).hexdigest(),
                                    title=f"Historical bird {index}", creator="Example naturalist", date="1890",
                                    source_url=f"https://example.invalid/plate/{index}", rights="Public domain",
                                    rights_url="https://example.invalid/rights"))
            if index < 13:
                self.birds.append(dict(scientific_name=f"Species {index}", common_name=f"Bird {index}",
                                       count=99 if index == 0 else index + 1, latest_heard=f"08:{index:02}:00",
                                       max_confidence=.99, hourly_counts=[]))
        self.feed = server.Feed("http://unused.invalid", self.root / "state", assets=self.assets, artwork_dir=self.root)
        self.feed.settings = render.validate_settings({"schedule": {"enabled": False}, "show_qr": False}, self.feed.settings, self.assets)
        blocker = patch.object(classic, "_fetch", side_effect=AssertionError("Style tests must never fetch photographs"))
        blocker.start()
        self.addCleanup(blocker.stop)

    def seed(self):
        self.feed.bundle = self.feed.build(self.birds, "2026-10-14", self.feed.settings, "2026-10-14T12:00:00-06:00")
        server.save_bundle(self.feed.directory, self.feed.bundle)
        return self.feed.bundle

    def test_legacy_settings_recover_to_collage_without_changing_the_saved_image(self):
        old = dict(self.feed.settings)
        old.pop("style")
        old.pop("classic_media")
        self.feed.settings = old
        original = self.seed()
        restored = server.Feed("http://unused.invalid", self.feed.directory, assets=self.assets, artwork_dir=self.root)
        self.assertEqual(restored.settings["style"], "collage")
        self.assertEqual(restored.settings["classic_media"], "photos")
        state = restored.state()
        for key in ("settings", "display_settings"):
            self.assertEqual(state[key]["style"], "collage")
            self.assertEqual(state[key]["classic_media"], "photos")
        self.assertFalse(state["pending_settings"])
        self.assertEqual(restored.bundle["frame"], original["frame"])
        self.assertEqual(restored.bundle["state"]["stats"], original["state"]["stats"])

    def test_style_and_classic_media_choices_are_validated(self):
        for style in ("collage", "classic", "field_guide"):
            for media in ("photos", "drawings"):
                settings = render.validate_settings({"style": style, "classic_media": media}, self.feed.settings, self.assets)
                self.assertEqual((settings["style"], settings["classic_media"]), (style, media))
        for key, value in (("style", "unknown"), ("style", None), ("style", True),
                           ("classic_media", "illustrations"), ("classic_media", 1), ("classic_media", [])):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                render.validate_settings({key: value}, self.feed.settings, self.assets)

    def test_field_guide_includes_all_covered_birds_and_preserves_ink_area_scaling(self):
        birds = self.birds + [dict(self.birds[0], scientific_name="Species 13", count=0),
                              dict(self.birds[0], scientific_name="Unillustrated visitor", count=700)]
        for mode, orientation in (("log", "portrait"), ("linear", "landscape"), ("equal", "portrait")):
            with self.subTest(mode=mode, orientation=orientation):
                settings = render.validate_settings(dict(style="field_guide", scale=mode, orientation=orientation,
                                                          show_names=True, show_scientific=True, show_counts=True),
                                                    self.feed.settings, self.assets)
                captured = {}
                original_arrange = field_guide.arrange

                def track(items, region, lines):
                    placements = original_arrange(items, region, lines)
                    captured.update(placements=placements, region=region)
                    return placements

                with patch.object(field_guide, "arrange", side_effect=track):
                    canvas, selected = render.compose(birds, settings, self.assets, self.root)
                self.assertEqual({b["scientific_name"] for b, _ in selected}, {b["scientific_name"] for b in self.birds})
                self.assertEqual(len(captured["placements"]), 13)
                self.assert_layout_pixels_and_labels(captured, canvas.size)
                # Actual source alpha and output dimensions must imply the
                # same common area multiplier, apart from pixel rounding.
                low, high = 0, math.inf
                for placement in captured["placements"]:
                    item = placement["item"]
                    alpha_area = sum(value * count for value, count in enumerate(item["image"].getchannel("A").histogram())) / 255
                    expected_weight = render.area_weight(item["bird"]["count"], mode)
                    normalized = math.sqrt(expected_weight / alpha_area)
                    for dimension, original in (("w", item["image"].width), ("h", item["image"].height)):
                        unit = original * normalized
                        low = max(low, (placement[dimension] - .5) / unit)
                        high = min(high, (placement[dimension] + .5) / unit)
                self.assertLessEqual(low, high + 1e-9)
                self.assertEqual(len(json.loads(canvas.info["Artwork sources"])), 13)

    def assert_layout_pixels_and_labels(self, captured, size):
        occupied = Image.new("L", size)
        left, top, width, height = captured["region"]
        for placement in captured["placements"]:
            item, bird = placement["item"], placement["item"]["bird"]
            resized = item["image"].resize((placement["w"], placement["h"]), Image.Resampling.LANCZOS)
            mask = Image.new("L", size)
            mask.paste(resized.getchannel("A").point(lambda value: 255 if value else 0),
                       (round(placement["x"]), round(placement["y"])))
            label_y = placement["y"] + placement["h"] + 10
            for text, italic in ((bird["common_name"], False), (bird["scientific_name"], True), (f'{bird["count"]:,} heard', False)):
                label_image = Image.new("RGB", size, "white")
                render.centered(ImageDraw.Draw(label_image), text, placement["cx"], label_y,
                                placement["label_width"] - 4,
                                max(12, placement["label_size"] - 2) if italic else placement["label_size"], italic)
                label_mask = ImageChops.difference(label_image, Image.new("RGB", size, "white")).convert("L").point(lambda value: 255 if value else 0)
                self.assertIsNotNone(label_mask.getbbox())
                self.assertIsNone(ImageChops.multiply(mask, label_mask).getbbox(), bird["scientific_name"])
                mask = ImageChops.lighter(mask, label_mask)
                label_y += placement["label_line_height"]
            bounds = mask.getbbox()
            self.assertGreaterEqual(bounds[0], left)
            self.assertGreaterEqual(bounds[1], top)
            self.assertLessEqual(bounds[2], left + width)
            self.assertLessEqual(bounds[3], top + height)
            self.assertIsNone(ImageChops.multiply(occupied, mask).getbbox(), bird["scientific_name"])
            occupied = ImageChops.lighter(occupied, mask)

    def test_classic_drawing_uses_latest_species_and_its_exact_variant(self):
        variant = {**self.assets[12], "id": "alternate-12", "file": "alternate.png"}
        Image.new("RGBA", (73, 117), (210, 20, 140, 255)).save(self.root / variant["file"])
        self.feed.assets.append(variant)
        settings = render.validate_settings(dict(style="classic", classic_media="drawings",
                                                  variants={"Species 12": "alternate-12"}), self.feed.settings, self.assets)
        with patch.object(classic, "photo") as fetch, patch.object(classic, "compose", wraps=classic.compose) as compose:
            bundle = self.feed.build(self.birds, "2026-10-14", settings, "2026-10-14T12:00:00-06:00")
        fetch.assert_not_called()
        self.assertEqual(compose.call_args.args[2].getpixel((20, 20)), (210, 20, 140, 255))
        self.assertEqual(compose.call_args.args[5]["scientific_name"], "Species 12")
        self.assertEqual(bundle["state"]["photo_credits"][0]["id"], "alternate-12")
        displayed = [b for b in bundle["state"]["stats"]["species"] if b["displayed"]]
        self.assertEqual([(b["scientific_name"], b["artwork_id"]) for b in displayed], [("Species 12", "alternate-12")])
        # A later species without a drawing must not borrow another bird's art.
        missing = dict(self.birds[0], scientific_name="Missing drawing", latest_heard="23:00:00")
        with patch.object(classic, "compose", wraps=classic.compose) as compose:
            unavailable = self.feed.build([*self.birds, missing], "2026-10-14", settings, "2026-10-14T12:00:00-06:00")
        self.assertIsNone(compose.call_args.args[2])
        self.assertEqual(unavailable["state"]["photo_credits"], [])
        self.assertEqual(unavailable["state"]["stats"]["illustrated_count"], 0)

    def test_classic_photo_preserves_dashboard_and_download_attribution(self):
        picture = Image.new("RGB", (180, 110), (40, 80, 190))
        credits = dict(id="photo-12", title="Bird photograph", creator="Example photographer", date="2020",
                       rights="CC BY 4.0", rights_url="https://creativecommons.org/licenses/by/4.0/",
                       source_url="https://example.invalid/photo", attribution="Example photographer, CC BY 4.0",
                       changes="Resized and converted to six colors for e-paper.")
        settings = render.validate_settings(dict(style="classic", classic_media="photos"), self.feed.settings, self.assets)
        with patch.object(classic, "photo", return_value=(picture, credits)) as photo:
            bundle = self.feed.build(self.birds, "2026-10-14", settings, "2026-10-14T12:00:00-06:00")
        photo.assert_called_once_with(self.feed.base, "Species 12")
        credit = bundle["state"]["photo_credits"][0]
        self.assertEqual(credit["scientific_name"], "Species 12")
        self.assertEqual(credit["creator"], "Example photographer")
        self.assertEqual(bundle["state"]["stats"]["species_count"], 13)
        self.assertEqual(bundle["state"]["stats"]["total_detections"], sum(b["count"] for b in self.birds))
        self.assertEqual(bundle["state"]["stats"]["illustrated_count"], 1)
        for key in ("art", "preview"):
            with Image.open(io.BytesIO(bundle[key])) as download:
                self.assertEqual(json.loads(download.info["Artwork sources"]), [credit])
        server.validate_frame(bundle["frame"])

    def test_failed_photo_change_retains_saved_bundle_and_settings(self):
        previous = self.seed()
        settings = copy.deepcopy(self.feed.settings)
        saved = (self.feed.directory / "current.zip").read_bytes()
        with patch.object(classic, "photo", side_effect=OSError("Photo unavailable")), self.assertRaises(OSError):
            self.feed.update_settings({"style": "classic", "classic_media": "photos"})
        self.assertIs(self.feed.bundle, previous)
        self.assertEqual(self.feed.settings, settings)
        self.assertEqual((self.feed.directory / "current.zip").read_bytes(), saved)

    def test_overnight_style_waits_for_resume_and_survives_restart(self):
        previous = self.seed()
        resting = dict(active=False, sleep_seconds=3600)
        with patch.object(server, "schedule_state", return_value=resting), patch.object(classic, "photo") as photo:
            state = self.feed.update_settings({"style": "classic", "classic_media": "drawings"})
            restored = server.Feed("http://unused.invalid", self.feed.directory, assets=self.assets, artwork_dir=self.root)
            self.assertEqual(restored.state()["settings"]["style"], "classic")
            self.assertEqual(restored.state()["display_settings"]["style"], "collage")
            self.assertTrue(restored.state()["pending_settings"])
            self.assertEqual(restored.bundle["frame"], previous["frame"])
            self.assertEqual(state["photo_credits"], previous["state"]["photo_credits"])
            photo.assert_not_called()
        with patch.object(server, "get_json", return_value=self.birds):
            resumed, _ = restored.frame_for_display()
        self.assertEqual(resumed["state"]["display_settings"]["style"], "classic")
        self.assertEqual(resumed["state"]["display_settings"]["classic_media"], "drawings")
        self.assertFalse(restored.state()["pending_settings"])
        self.assertNotEqual(resumed["frame"], previous["frame"])


if __name__ == "__main__":
    unittest.main()
