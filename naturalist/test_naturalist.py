import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

from PIL import Image
import render
import server


class NaturalistTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        picture = Image.new("RGBA", (80, 100), (60, 80, 20, 255))
        picture.save(self.root / "bird.png")
        self.assets = [{"id": "test-1", "scientific_name": "Test bird", "common_name": "Test",
                        "file": "bird.png", "sha256": hashlib.sha256((self.root / "bird.png").read_bytes()).hexdigest()}]
        self.birds = [{"scientific_name": "Test bird", "common_name": "Test", "count": 10,
                       "latest_heard": "09:12:00", "max_confidence": .9, "hourly_counts": []}]
        self.service = server.Feed("http://unused", self.root / "state", assets=self.assets, artwork_dir=self.root)
        self.service.settings = render.validate_settings({"schedule": {"enabled": False}}, self.service.settings, self.assets)
        bundle = self.service.build(self.birds, "2026-10-14", self.service.settings, "2026-10-14T12:00:00-06:00")
        self.service.bundle = bundle
        server.save_bundle(self.service.directory, bundle)

    def tearDown(self):
        self.temporary.cleanup()

    def test_area_mapping(self):
        self.assertAlmostEqual(render.area_weight(99, "log") / render.area_weight(9, "log"), 2)
        self.assertEqual(render.area_weight(20, "linear") / render.area_weight(10, "linear"), 2)
        self.assertEqual(render.area_weight(100, "equal"), render.area_weight(1, "equal"))
        self.assertEqual(render.area_weight(0, "log"), 0)

    def test_exact_palette_and_inverse_portrait_rotation(self):
        canvas = Image.new("RGB", (1200, 1600), "white")
        positions = [(0, 0), (1199, 0), (0, 1599), (1199, 1599), (598, 900), (599, 900)]
        for position, color in zip(positions, render.COLORS):
            canvas.putpixel(position, color)
        frame, preview = render.pack(canvas)
        server.validate_frame(frame)
        self.assertEqual(Image.open(io.BytesIO(preview)).size, canvas.size)
        for (native_x, native_y), code in zip(positions, [0, 1, 2, 3, 5, 6]):
            # Same mapping as PanelFrame13in3e.h; this checks the actual wire
            # offset, including odd/even nibbles and the two-controller seam.
            offset = (1199 - native_x) * 1600 + native_y
            packed = frame[offset // 2]
            self.assertEqual(packed >> 4 if offset % 2 == 0 else packed & 15, code)
        with self.assertRaises(ValueError):
            server.validate_frame(b"\x44" * 960000)

    def test_settings_validation_and_species_variant_binding(self):
        for bad in ({"show_names": "false"}, {"max_birds": True}, {"max_birds": 13},
                    {"show_qr": True, "dashboard_url": ""}, {"dashboard_url": "javascript:alert(1)"},
                    {"dashboard_url": "http://bird.local:invalid"}, {"dashboard_url": "http://bird.local:99999"},
                    {"variants": {"Other bird": "test-1"}}, {"unexpected": 3}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                render.validate_settings(bad, {}, self.assets)
        settings = render.validate_settings({"show_qr": True, "dashboard_url": "http://192.0.2.5:8001/"}, {}, self.assets)
        canvas, _ = render.compose(self.birds, settings, self.assets, self.root)
        self.assertEqual(canvas.size, (1200, 1600))

    def test_runtime_dashboard_url_seeds_new_settings_and_preserves_saved_choices(self):
        fresh = server.Feed("http://unused", self.root / "fresh", assets=self.assets, artwork_dir=self.root,
                            dashboard_url="http://192.0.2.20:8001/")
        self.assertEqual(fresh.settings["dashboard_url"], "http://192.0.2.20:8001/")
        self.assertTrue(fresh.settings["show_qr"])
        self.service.update_settings({"show_qr": False, "dashboard_url": "https://example.invalid/birds/"})
        restored = server.Feed("http://unused", self.service.directory, assets=self.assets, artwork_dir=self.root,
                               dashboard_url="http://192.0.2.21:8001/")
        self.assertFalse(restored.settings["show_qr"])
        self.assertEqual(restored.settings["dashboard_url"], "https://example.invalid/birds/")

    def test_runtime_dashboard_url_validation_does_not_echo_private_values(self):
        import contextlib
        for value in ("http://private-user:private-token@example.invalid/", "http://example.invalid:private-token/", ""):
            stderr = io.StringIO()
            with patch("sys.argv", ["server.py", "--dashboard-url", value]), \
                    patch.object(server, "Feed") as construct, contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
                server.main()
            construct.assert_not_called()
            self.assertNotIn("private-token", stderr.getvalue())
            self.assertNotIn("private-user", stderr.getvalue())

    def test_all_illustrated_species_are_default_and_subset_remains_optional(self):
        assets = [{"id": f"art-{index}", "scientific_name": f"Example bird {index}"} for index in range(14)]
        birds = [{"scientific_name": asset["scientific_name"], "count": index + 1} for index, asset in enumerate(assets)]
        defaults = render.validate_settings({}, {}, assets)
        self.assertEqual(len(render.choose_birds(birds, defaults, assets)), 14)
        subset = render.validate_settings({"show_all": False, "max_birds": 5}, defaults, assets)
        self.assertEqual([bird["count"] for bird, _ in render.choose_birds(birds, subset, assets)], [14, 13, 12, 11, 10])

    def test_saved_settings_recover_and_failed_write_is_atomic(self):
        original = self.service.bundle
        with patch.object(server, "save_bundle", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.service.update_settings({"show_counts": True})
        self.assertIs(self.service.bundle, original)
        self.assertFalse(self.service.settings["show_counts"])
        result = self.service.update_settings({"show_names": False, "show_counts": True})
        restored = server.Feed("http://unused", self.service.directory, assets=self.assets, artwork_dir=self.root)
        self.assertEqual(restored.settings, result["settings"])
        self.assertEqual(restored.bundle["frame"], self.service.bundle["frame"])
        self.assertNotEqual(original["state"]["revision"], result["revision"])

    def test_invalid_saved_state_and_removed_variant_recover(self):
        import zipfile
        self.service.update_settings({"variants": {"Test bird": "test-1"}})
        restored = server.Feed("http://unused", self.service.directory, assets=[], artwork_dir=self.root)
        self.assertIsNone(restored.bundle)
        self.assertEqual(restored.settings["variants"], {})
        with zipfile.ZipFile(self.service.directory / "current.zip", "w") as archive:
            archive.writestr("current_large.bin", b"\x11" * 960000)
            archive.writestr("art.png", b"png")
            archive.writestr("preview.png", b"png")
            archive.writestr("state.json", "[]")
        self.assertIsNone(server.load_bundle(self.service.directory))

    def test_counts_stats_filter_and_missing_art_are_honest(self):
        rows = server.daily_birds([*self.birds, {"scientific_name": "Missing art", "count": 4,
                                 "max_confidence": .99, "source": "private secret"},
                                 {"scientific_name": "Uncertain", "count": 1000, "max_confidence": .2}], .8)
        bundle = self.service.build(rows, "2026-10-14", self.service.settings, "now")
        stats = bundle["state"]["stats"]
        self.assertEqual(stats["total_detections"], 14)
        self.assertEqual(stats["species_count"], 2)
        self.assertFalse(stats["species"][1]["illustrated"])
        self.assertNotIn("private secret", json.dumps(stats))

    def test_no_data_is_empty_day_not_previous_birds(self):
        with patch.object(server, "get_json", return_value=[]) as fetch:
            self.service.refresh()
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(fetch.call_args.args[1]).query)
        self.assertEqual(query["min_confidence"], ["80.0"])
        self.assertEqual(query["date"], [server.datetime.now(self.service.timezone).date().isoformat()])
        self.assertEqual(self.service.bundle["state"]["stats"]["species_count"], 0)
        self.assertIsNone(self.service.error)

    def test_failed_fetch_retains_bundle(self):
        previous = self.service.bundle
        with patch.object(server, "get_json", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                self.service.refresh()
        self.assertIs(self.service.bundle, previous)

    def test_overnight_hold_keeps_print_and_pending_settings(self):
        inactive = {"active": False, "sleep_seconds": 3600}
        previous = self.service.bundle
        with patch.object(self.service, "schedule", return_value=inactive), patch.object(server, "get_json") as fetch:
            self.service.refresh()
            fetch.assert_not_called()
        with patch.object(server, "schedule_state", return_value=inactive):
            result = self.service.update_settings({"show_counts": True})
        self.assertEqual(self.service.bundle["frame"], previous["frame"])
        self.assertTrue(result["pending_settings"])
        self.assertFalse(self.service.bundle["state"]["display_settings"]["show_counts"])
        with patch.object(server, "get_json", return_value=self.birds):
            self.service.refresh()
        self.assertNotEqual(self.service.bundle["frame"], previous["frame"])
        self.assertFalse(self.service.state()["pending_settings"])

    def test_sunrise_request_gets_fresh_observations_before_etag(self):
        previous = self.service.bundle
        with patch.object(self.service, "schedule", return_value={"active": False, "sleep_seconds": 60}):
            frozen, hold = self.service.frame_for_display()
        self.assertIs(frozen, previous)
        self.assertEqual(hold, 60)
        with patch.object(server, "get_json", return_value=[]) as fetch:
            resumed, hold = self.service.frame_for_display()
            self.service.frame_for_display()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(hold, 0)
        self.assertEqual(resumed["state"]["stats"]["species_count"], 0)
        self.assertNotEqual(resumed["frame"], previous["frame"])
        self.assertFalse(self.service.resume_pending)

    def test_pending_settings_and_sunrise_requirement_survive_restart(self):
        inactive = {"active": False, "sleep_seconds": 3600}
        previous = self.service.bundle
        with patch.object(server, "schedule_state", return_value=inactive):
            self.service.update_settings({"show_counts": True})
            restored = server.Feed("http://unused", self.service.directory, assets=self.assets, artwork_dir=self.root)
            self.assertTrue(restored.state()["pending_settings"])
            self.assertTrue(restored.resume_pending)
            self.assertEqual(restored.bundle["frame"], previous["frame"])
        with patch.object(server, "get_json", return_value=self.birds):
            restored.frame_for_display()
        self.assertTrue(restored.bundle["state"]["display_settings"]["show_counts"])
        self.assertFalse(restored.state()["pending_settings"])

    def test_failed_sunrise_fetch_preserves_bundle_and_requires_retry(self):
        self.service.resume_pending = True
        previous = self.service.bundle
        with patch.object(server, "get_json", side_effect=OSError("private upstream detail")):
            with self.assertRaises(OSError):
                self.service.frame_for_display()
        self.assertIs(self.service.bundle, previous)
        self.assertTrue(self.service.resume_pending)

    def test_sunrise_request_shares_in_progress_refresh(self):
        self.service.resume_pending = True
        started, release = threading.Event(), threading.Event()
        outcomes, errors = [], []
        def fetch(*_):
            started.set()
            self.assertTrue(release.wait(5))
            return []
        def request_frame():
            try:
                outcomes.append(self.service.frame_for_display())
            except Exception as exc:
                errors.append(exc)
        with patch.object(server, "get_json", side_effect=fetch) as source:
            poll = threading.Thread(target=self.service.refresh)
            request = threading.Thread(target=request_frame)
            poll.start()
            try:
                self.assertTrue(started.wait(5))
                request.start()
            finally:
                release.set()
                poll.join(10)
                if request.ident:
                    request.join(10)
            self.assertFalse(poll.is_alive())
            self.assertFalse(request.is_alive())
            self.assertFalse(errors)
            self.assertEqual(source.call_count, 1)
        self.assertEqual(outcomes[0][0]["state"]["stats"]["species_count"], 0)

    def test_edited_timezone_controls_daily_query_and_observation_metadata(self):
        from datetime import datetime, timezone
        from urllib.parse import parse_qs, urlsplit
        original_timezone = self.service.bundle["state"]["stats"]["timezone"]
        self.service.update_settings({"schedule": {"timezone": "Pacific/Auckland"}})
        # Changing presentation settings must not relabel old observations.
        self.assertEqual(self.service.bundle["state"]["stats"]["timezone"], original_timezone)
        instant = datetime(2026, 10, 14, 14, 30, tzinfo=timezone.utc)
        with patch.object(server, "datetime") as clock, patch.object(server, "get_json", return_value=[]) as fetch:
            clock.now.side_effect = lambda zone: instant.astimezone(zone)
            self.service.refresh()
        query = parse_qs(urlsplit(fetch.call_args.args[1]).query)
        self.assertEqual(query["date"], ["2026-10-15"])
        self.assertEqual(self.service.bundle["state"]["stats"]["timezone"], "Pacific/Auckland")

    def test_same_visual_data_keeps_etag_even_when_stats_change(self):
        settings = {**self.service.settings, "scale": "equal", "show_counts": False}
        first = self.service.build(self.birds, "2026-10-14", settings, "morning")
        second = self.service.build([{**self.birds[0], "count": 100}], "2026-10-14", settings, "afternoon")
        self.assertEqual(first["frame"], second["frame"])
        self.assertNotEqual(first["state"]["stats"], second["state"]["stats"])

    def test_http_controls_csrf_etag_and_no_file_traversal(self):
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.service))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:" + str(http.server_port)
        try:
            with urlopen(base + "/api/settings") as response:
                token = json.load(response)["csrf_token"]
            for headers in ({}, {"X-CSRF-Token": token, "Origin": "http://evil.invalid"}):
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(base + "/api/settings", data=b'{"show_names":false}',
                                    headers={"Content-Type": "application/json", **headers}))
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            with urlopen(Request(base + "/api/settings", data=b'{"show_names":false}',
                                 headers={"Content-Type": "application/json", "X-CSRF-Token": token})) as response:
                self.assertFalse(json.load(response)["settings"]["show_names"])
            with urlopen(base + "/api/v1/display/current_large.bin") as response:
                self.assertEqual(len(response.read()), 960000)
                tag = response.headers["ETag"]
            with self.assertRaises(HTTPError) as unchanged:
                urlopen(Request(base + "/api/v1/display/current_large.bin", headers={"If-None-Match": "W/" + tag}))
            self.assertEqual(unchanged.exception.code, 304)
            unchanged.exception.close()
            with patch.object(self.service, "schedule", return_value={"active": False, "sleep_seconds": 43200}):
                with urlopen(base + "/api/v1/display/current_large.bin") as response:
                    self.assertEqual(response.headers["X-FederFunk-Hold-Seconds"], "43200")
                with self.assertRaises(HTTPError) as held:
                    urlopen(Request(base + "/api/v1/display/current_large.bin", headers={"If-None-Match": tag}))
                self.assertEqual(held.exception.code, 304)
                self.assertEqual(held.exception.headers["X-FederFunk-Hold-Seconds"], "43200")
                held.exception.close()
            # At sunrise an upstream outage cannot produce a stale304 that
            # would be mistaken for a successfully resumed print.
            with patch.object(server, "get_json", side_effect=OSError("private upstream token")):
                with self.assertRaises(HTTPError) as unavailable:
                    urlopen(Request(base + "/api/v1/display/current_large.bin", headers={"If-None-Match": tag}))
                self.assertEqual(unavailable.exception.code, 503)
                self.assertNotIn("private upstream", unavailable.exception.read().decode())
                self.assertIsNone(unavailable.exception.headers.get("X-FederFunk-Hold-Seconds"))
                unavailable.exception.close()
            with patch.object(server, "get_json", return_value=[]):
                with urlopen(Request(base + "/api/v1/display/current_large.bin", headers={"If-None-Match": tag})) as response:
                    self.assertEqual(response.status, 200)
                    self.assertNotEqual(response.headers["ETag"], tag)
                    self.assertIsNone(response.headers.get("X-FederFunk-Hold-Seconds"))
            with self.assertRaises(HTTPError) as missing:
                urlopen(base + "/../src/BirdDisplayConfig.h")
            self.assertEqual(missing.exception.code, 404)
            missing.exception.close()
            with self.assertRaises(HTTPError) as rebinding:
                urlopen(Request(base + "/api/settings", headers={"Host": "evil.invalid"}))
            self.assertEqual(rebinding.exception.code, 403)
            rebinding.exception.close()
        finally:
            http.shutdown()
            http.server_close()


if __name__ == "__main__":
    unittest.main()
