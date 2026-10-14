"""Battery telemetry stays optional and independent of the image response."""
from datetime import datetime, timezone
from email.message import Message
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import server


HEADERS = {"X-FederFunk-Battery-Percent": "62",
           "X-FederFunk-Battery-Voltage": "3.87",
           "X-FederFunk-Charging": "unknown"}
DEVICE_HEADERS = {**HEADERS, "User-Agent": "ESP32HTTPClient"}


class DeviceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.feed = server.Feed("http://unused", self.directory, assets=[])

    def tearDown(self):
        self.temporary.cleanup()

    def test_valid_bounds_and_unknown_charging(self):
        self.assertEqual(server.battery_headers(HEADERS), dict(battery_percent=62, battery_voltage=3.87, charging="unknown"))
        for percent, voltage in (("0", "2.5"), ("100", "4.5")):
            values = server.battery_headers({**HEADERS, "X-FederFunk-Battery-Percent": percent,
                                            "X-FederFunk-Battery-Voltage": voltage})
            self.assertEqual(values["battery_percent"], int(percent))
            self.assertEqual(values["battery_voltage"], float(voltage))

    def test_malformed_or_duplicate_headers_are_ignored_independently(self):
        for value in ("-1", "101", "1.5", "NaN", "true", "1\n2", "9" * 1000):
            with self.subTest(percent=value):
                self.assertNotIn("battery_percent", server.battery_headers({"X-FederFunk-Battery-Percent": value}))
        for value in ("nan", "inf", "2.49", "4.51", "4e0", "3.123456", "-3.7"):
            with self.subTest(voltage=value):
                self.assertNotIn("battery_voltage", server.battery_headers({"X-FederFunk-Battery-Voltage": value}))
        self.assertEqual(server.battery_headers({"X-FederFunk-Charging": "false"}), {})
        message = Message()
        message["X-FederFunk-Battery-Percent"] = "50"
        message["X-FederFunk-Battery-Percent"] = "100"
        message["X-FederFunk-Charging"] = "not_charging"
        self.assertEqual(server.battery_headers(message), {"charging": "not_charging"})

    def test_persists_separately_and_does_not_refresh_old_reading_on_headerless_request(self):
        (self.directory / "current.zip").write_bytes(b"unrelated image bundle")
        self.feed.record_device(HEADERS)
        first = dict(self.feed.device)
        self.assertEqual(first["reported_at"], first["last_seen"])
        self.assertEqual(datetime.fromisoformat(first["last_seen"]).utcoffset().total_seconds(), 0)
        self.feed.record_device({})
        self.assertEqual(self.feed.device["reported_at"], first["reported_at"])
        self.assertEqual(self.feed.device["battery_percent"], 62)
        self.assertGreaterEqual(self.feed.device["last_seen"], first["last_seen"])
        restored = server.Feed("http://unused", self.directory, assets=[])
        self.assertEqual(restored.device, self.feed.device)
        self.assertEqual((self.directory / "current.zip").read_bytes(), b"unrelated image bundle")
        self.assertFalse(list(self.directory.glob("device-*.tmp")))

    def test_partial_report_does_not_mix_new_and_old_measurements(self):
        self.feed.record_device(HEADERS)
        self.feed.record_device({"X-FederFunk-Battery-Percent": "55", "X-FederFunk-Charging": "bogus"})
        self.assertEqual(self.feed.device["battery_percent"], 55)
        self.assertIsNone(self.feed.device["battery_voltage"])
        self.assertEqual(self.feed.device["charging"], "unknown")

    def test_failed_persistence_keeps_current_reading_available(self):
        with patch.object(server, "save_device", side_effect=OSError("disk unavailable")), self.assertLogs(server.LOG, level="WARNING"):
            self.feed.record_device(HEADERS)
        self.assertEqual(self.feed.device["battery_percent"], 62)

    def test_malformed_saved_status_recovers_to_unknown(self):
        for contents in ("[]", "not json", " " * 4097,
                         json.dumps({"last_seen": "tomorrow"}),
                         json.dumps({"last_seen": "2026-10-14T12:00:00"}),
                         json.dumps({"reported_at": "2999-01-01T00:00:00+00:00"})):
            with self.subTest(contents=contents[:80]):
                (self.directory / "device.json").write_text(contents)
                recovered = server.load_device(self.directory)
                self.assertIsNone(recovered["battery_percent"])
                self.assertIsNone(recovered["reported_at"])
                self.assertEqual(recovered["charging"], "unknown")

    def test_age_and_expected_overnight_rest_are_separate(self):
        empty = self.feed.state()["device"]
        self.assertIsNone(empty["last_seen"])
        self.assertFalse(empty["stale"])
        self.feed.record_device(HEADERS)
        stamp = datetime.fromisoformat(self.feed.device["reported_at"]).timestamp()
        with patch.object(server.time, "time", return_value=stamp + server.DEVICE_STALE_SECONDS + 1), \
                patch.object(self.feed, "schedule", return_value={"active": False}):
            status = self.feed.state()["device"]
            self.assertTrue(status["stale"])
            self.assertTrue(status["resting"])
            self.assertEqual(status["charging"], "unknown")

    def test_frame_requests_record_on_200_304_hold_and_unavailable(self):
        frame = b"\x11" * 960000
        bundle = {"frame": frame, "state": {"settings": self.feed.settings, "stats": {}}}
        self.feed.bundle = bundle
        http = ThreadingHTTPServer(("127.0.0.1", 0), server.handler_for(self.feed))
        threading.Thread(target=http.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{http.server_port}"
        path = base + "/api/v1/display/current_large.bin"
        try:
            with urlopen(Request(base + "/api/state", headers=HEADERS)) as response:
                self.assertIsNone(json.load(response)["device"]["last_seen"])
            with patch.object(self.feed, "frame_for_display", return_value=(bundle, 0)):
                with urlopen(Request(path, headers=DEVICE_HEADERS, method="HEAD")) as response:
                    self.assertEqual(response.status, 200)
                self.assertIsNone(self.feed.device["last_seen"])
                # Health probes, browsers, and downloads do not announce a
                # frame wake, even if telemetry-like headers are present.
                for headers in ({}, HEADERS, {"User-Agent": "ESP32HTTPClient-other"}):
                    with urlopen(Request(path, headers=headers)) as response:
                        self.assertEqual(response.read(), frame)
                    self.assertIsNone(self.feed.device["last_seen"])
                with urlopen(Request(path, headers={"User-Agent": "ESP32HTTPClient"})) as response:
                    response.read()
                self.assertIsNotNone(self.feed.device["last_seen"])
                self.assertIsNone(self.feed.device["reported_at"])
                with urlopen(Request(path, headers=DEVICE_HEADERS)) as response:
                    self.assertEqual(response.read(), frame)
                    tag = response.headers["ETag"]
            self.assertEqual(self.feed.device["battery_percent"], 62)
            with patch.object(self.feed, "frame_for_display", return_value=(bundle, 43200)):
                with self.assertRaises(HTTPError) as unchanged:
                    urlopen(Request(path, headers={**DEVICE_HEADERS, "X-FederFunk-Battery-Percent": "61", "If-None-Match": tag}))
                self.assertEqual(unchanged.exception.code, 304)
                self.assertEqual(unchanged.exception.headers["X-FederFunk-Hold-Seconds"], "43200")
                unchanged.exception.close()
            self.assertEqual(self.feed.device["battery_percent"], 61)
            previous = dict(self.feed.device)
            with patch.object(self.feed, "frame_for_display", return_value=(bundle, 0)):
                with urlopen(Request(path, headers={"User-Agent": "ESP32HTTPClient", "X-FederFunk-Battery-Percent": "101",
                                                   "X-FederFunk-Battery-Voltage": "nan", "X-FederFunk-Charging": "false"})) as response:
                    self.assertEqual(response.read(), frame)
            self.assertEqual(self.feed.device["reported_at"], previous["reported_at"])
            self.assertEqual(self.feed.device["battery_percent"], 61)
            self.assertEqual(self.feed.device["charging"], "unknown")
            self.assertGreaterEqual(self.feed.device["last_seen"], previous["last_seen"])
            with patch.object(self.feed, "frame_for_display", return_value=(None, 0)):
                with self.assertRaises(HTTPError) as unavailable:
                    urlopen(Request(path, headers={**DEVICE_HEADERS, "X-FederFunk-Charging": "charging"}))
                self.assertEqual(unavailable.exception.code, 503)
                unavailable.exception.close()
            self.assertEqual(self.feed.device["charging"], "charging")
            self.assertIs(self.feed.bundle, bundle)
            self.assertEqual(self.feed.bundle["frame"], frame)
        finally:
            http.shutdown()
            http.server_close()


if __name__ == "__main__":
    unittest.main()
