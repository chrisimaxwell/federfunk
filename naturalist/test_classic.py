import io
import json
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import classic


def encoded_image(mode="RGB", format="PNG"):
    output = io.BytesIO()
    Image.new(mode, (48, 32), "red").save(output, format=format)
    return output.getvalue()


class PhotoTests(unittest.TestCase):
    def setUp(self):
        classic._cached_photo.cache_clear()
        self.info = dict(authorName="Example photographer", authorURL="https://example.org/author",
                         licenseName="CC BY-SA 4.0", licenseURL="https://creativecommons.org/licenses/by-sa/4.0/",
                         sourceProvider="Example catalogue", url="https://example.org/original.jpg",
                         imagePath="https://untrusted.invalid/download", secret="do not retain")

    def test_proxy_only_cache_copies_and_attribution_allowlist(self):
        with patch.object(classic, "_fetch", side_effect=[json.dumps(self.info).encode(), encoded_image()]) as fetch:
            first, credits = classic.photo("http://station.invalid:8080", "Example bird/name")
            first.putpixel((0, 0), (0, 0, 0))
            credits["creator"] = "changed"
            second, preserved = classic.photo("http://station.invalid:8080", "Example bird/name")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args,
                         ("http://station.invalid:8080", "/api/v2/media/species-image/info?name=Example+bird%2Fname",
                          classic.MAX_INFO_BYTES))
        self.assertEqual(fetch.call_args_list[1].args,
                         ("http://station.invalid:8080", "/api/v2/media/image/Example%20bird%2Fname",
                          classic.MAX_PHOTO_BYTES))
        self.assertEqual(second.mode, "RGB")
        self.assertEqual(second.getpixel((0, 0)), (255, 0, 0))
        self.assertEqual(preserved["creator"], "Example photographer")
        self.assertEqual(preserved["source_url"], self.info["url"])
        self.assertEqual(preserved["author_url"], self.info["authorURL"])
        self.assertIn("chromatic boost", preserved["attribution"])
        self.assertNotIn("secret", preserved)
        self.assertNotIn("station.invalid", json.dumps(preserved))
        self.assertNotIn("untrusted.invalid", json.dumps(preserved))
        self.assertEqual(classic._cached_photo.cache_info().maxsize, 8)

    def test_required_attribution_is_never_invented(self):
        for key, value in (("authorName", ""), ("licenseName", None),
                           ("licenseURL", "javascript:alert(1)"), ("licenseURL", "https://secret:token@example.org")):
            with self.subTest(key=key, value=value), patch.object(
                    classic, "_fetch", return_value=json.dumps({**self.info, key: value}).encode()) as fetch:
                with self.assertRaises(ValueError):
                    classic.photo("http://station.invalid", "Example bird")
                self.assertEqual(fetch.call_count, 1)
        info = {key: value for key, value in self.info.items() if key not in ("url", "authorURL")}
        with patch.object(classic, "_fetch", side_effect=[json.dumps(info).encode(), encoded_image()]):
            _, credits = classic.photo("http://station.invalid", "Example bird")
        self.assertEqual(credits["source_url"], "")
        self.assertEqual(credits["author_url"], "")

    def test_bounded_fetch_timeout_and_redirect_refusal(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b"12345"
        opener = Mock()
        opener.open.return_value = response
        with patch.object(classic, "build_opener", return_value=opener) as build:
            with self.assertRaisesRegex(ValueError, "too large"):
                classic._fetch("http://station.invalid", "/image", 4)
        response.read.assert_called_once_with(5)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://station.invalid/image")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 8)
        handler = build.call_args.args[0]
        self.assertIsInstance(handler, classic._NoRedirect)
        self.assertIsNone(handler.redirect_request(request, None, 302, "", {}, "https://external.invalid"))
        for base in ("file:///tmp/example", "http://secret:token@example.org", "http://example.org?token=secret"):
            with self.subTest(base=base), patch.object(classic, "build_opener") as forbidden:
                with self.assertRaises(ValueError):
                    classic._fetch(base, "/image", 4)
                forbidden.assert_not_called()

    def test_invalid_corrupt_and_oversized_images_are_not_cached(self):
        for data in (b"not an image", encoded_image(format="GIF"), encoded_image()[:30]):
            with self.subTest(data=data[:8]), patch.object(
                    classic, "_fetch", side_effect=[json.dumps(self.info).encode(), data]):
                with self.assertRaises((ValueError, OSError)):
                    classic.photo("http://station.invalid", "Example bird")
        fake = Mock(format="PNG", width=10_000, height=10_000, is_animated=False)
        fake.__enter__ = Mock(return_value=fake)
        fake.__exit__ = Mock(return_value=False)
        with patch.object(classic, "_fetch", side_effect=[json.dumps(self.info).encode(), b"oversized"]), \
                patch.object(classic.Image, "open", return_value=fake):
            with self.assertRaisesRegex(ValueError, "oversized"):
                classic.photo("http://station.invalid", "Example bird")
        fake.load.assert_not_called()
        self.assertEqual(classic._cached_photo.cache_info().currsize, 0)


class ClassicLayoutTests(unittest.TestCase):
    def setUp(self):
        self.birds = [dict(scientific_name=f"Example species {i:02d}", common_name=f"Visitor {i:02d}", count=i + 1)
                      for i in range(13)]
        self.settings = dict(orientation="portrait", show_all=True, max_birds=5,
                             show_title=True, show_names=True, show_scientific=True, show_counts=True)
        self.picture = Image.new("RGBA", (80, 100), (80, 130, 30, 255))
        self.credits = dict(creator="Example artist", rights="Public domain", source_url="https://example.org/plate")

    def render(self, settings=None, birds=None, picture=None, featured=None):
        return classic.compose(self.birds if birds is None else birds, settings or self.settings,
                               self.picture if picture is None else picture, self.credits,
                               "2026-10-14", featured)

    def test_every_positive_species_shown_sorted_and_deterministic_in_both_orientations(self):
        birds = [*self.birds, dict(scientific_name="Not heard", common_name="Not heard", count=0)]
        for orientation, dimensions in (("portrait", (1200, 1600)), ("landscape", (1600, 1200))):
            with self.subTest(orientation=orientation), patch.object(classic, "_label", wraps=classic._label) as label:
                result = self.render({**self.settings, "orientation": orientation}, birds=birds)
                names = [call.args[2] for call in label.call_args_list if call.args[2].startswith("Visitor")]
            self.assertEqual(names, [f"Visitor {i:02d}" for i in reversed(range(13))])
            self.assertEqual(result.size, dimensions)
            self.assertEqual(result.mode, "RGB")
            repeat = self.render({**self.settings, "orientation": orientation}, birds=birds)
            self.assertEqual(result.tobytes(), repeat.tobytes())
            self.assertEqual(json.loads(result.info["Artwork sources"]), [self.credits])
            # Attribution and QR are web/shared-renderer responsibilities. The
            # entire bottom margin is clear in this pre-QR composition.
            footer = result.crop((0, dimensions[1] - 100, dimensions[0], dimensions[1]))
            self.assertEqual(footer.getextrema(), ((255, 255),) * 3)

    def test_optional_subset_limits_only_daily_list(self):
        with patch.object(classic, "_label", wraps=classic._label) as label:
            self.render({**self.settings, "show_all": False})
        names = [call.args[2] for call in label.call_args_list if call.args[2].startswith("Visitor")]
        self.assertEqual(names, [f"Visitor {i:02d}" for i in (12, 11, 10, 9, 8)])

    def test_hide_options_cover_feature_caption_and_daily_list(self):
        settings = {**self.settings, "show_title": False, "show_names": False,
                    "show_scientific": False, "show_counts": False}
        with patch.object(classic, "_label", wraps=classic._label) as label:
            self.render(settings, featured=self.birds[0])
        label.assert_not_called()

    def test_transparent_drawing_composites_on_white_and_empty_is_neutral(self):
        transparent = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
        settings = {**self.settings, "classic_media": "drawings"}
        result = self.render(settings, picture=transparent)
        self.assertEqual(result.getpixel((600, 530)), (255, 255, 255))
        with patch.object(classic, "_label", wraps=classic._label) as label:
            result = classic.compose(self.birds, settings, None, self.credits, "2026-10-14", self.birds[0])
        self.assertIn("Illustration not available", [call.args[2] for call in label.call_args_list])
        self.assertEqual(json.loads(result.info["Artwork sources"]), [])
        with patch.object(classic, "_label", wraps=classic._label) as label:
            result = classic.compose([], settings, None, {}, "2026-10-14", None)
        self.assertIn("Listening for visitors", [call.args[2] for call in label.call_args_list])
        self.assertEqual(result.size, (1200, 1600))


if __name__ == "__main__":
    unittest.main()
