#!/usr/bin/env python3
"""A local BirdNET-Go companion: historical bird prints, stats, and controls."""
import argparse
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import render
from schedule import schedule_state
from audit_library import audit_history

LOG = logging.getLogger("federfunk-naturalist")
ROOT = Path(__file__).resolve().parent


def clean(value, limit=180):
    return " ".join(str(value or "").split())[:limit]


def daily_birds(payload, threshold):
    if not isinstance(payload, list) or len(payload) > 2000:
        raise ValueError("Unexpected daily analytics response")
    birds = []
    seen = set()
    for row in payload:
        name = clean(row.get("scientific_name"))
        confidence = float(row.get("max_confidence", 0))
        count = int(row.get("count", 0))
        if not name or name in seen or not math.isfinite(confidence) or not 0 <= confidence <= 1 or count < 0:
            raise ValueError("Invalid species analytics")
        seen.add(name)
        if confidence < threshold or count == 0:
            continue
        hourly = row.get("hourly_counts", [])
        if len(hourly) != 24 or any(type(c) is not int or c < 0 for c in hourly):
            hourly = []
        # Deliberate allowlist: never persist recordings/source credentials.
        birds.append(dict(scientific_name=name, common_name=clean(row.get("common_name")) or name,
                          count=count, latest_heard=clean(row.get("latest_heard"), 8),
                          max_confidence=confidence, hourly_counts=hourly))
    return sorted(birds, key=lambda b: (-b["count"], b["scientific_name"]))


def get_json(base, path):
    request = Request(base.rstrip("/") + path, headers={"User-Agent": "FederFunk-Naturalist/1.0"})
    with urlopen(request, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Upstream response too large")
    return json.loads(body)


def validate_frame(frame):
    valid = {0, 1, 2, 3, 5, 6}
    if len(frame) != 960000 or any(b >> 4 not in valid or b & 15 not in valid for b in frame):
        raise ValueError("Invalid packed frame")


def save_bundle(directory, bundle):
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix="current-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "wb") as output:
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                for key, filename in (("frame", "current_large.bin"), ("preview", "preview.png"), ("art", "art.png")):
                    archive.writestr(filename, bundle[key])
                archive.writestr("state.json", json.dumps(bundle["state"]))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / "current.zip")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_bundle(directory):
    try:
        with zipfile.ZipFile(directory / "current.zip") as archive:
            if any(info.file_size > 16_000_000 for info in archive.infolist()):
                return None
            bundle = {"frame": archive.read("current_large.bin"), "preview": archive.read("preview.png"),
                      "art": archive.read("art.png"), "state": json.loads(archive.read("state.json"))}
            validate_frame(bundle["frame"])
            if not isinstance(bundle["state"], dict) or not isinstance(bundle["state"].get("settings"), dict) or not isinstance(bundle["state"].get("stats"), dict):
                return None
            stats = bundle["state"]["stats"]
            if not isinstance(stats.get("species"), list) or not isinstance(stats.get("date"), str) or not isinstance(stats.get("observed_at"), str):
                return None
            return bundle
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return None


class Feed:
    def __init__(self, base, directory, interval=300, threshold=.8,
                 timezone="America/Denver", demo=False, assets=None, artwork_dir=None,
                 dashboard_url=None):
        self.base, self.directory, self.interval, self.threshold = base, directory, interval, threshold
        self.timezone, self.demo = ZoneInfo(timezone), demo
        self.assets = render.catalogue(artwork_dir) if assets is None else assets
        self.artwork_dir = artwork_dir or ROOT / "artwork"
        self.lock = threading.RLock()
        self.refresh_lock = threading.Lock()
        initial = {"schedule": {"timezone": timezone}}
        if dashboard_url is not None:
            initial["dashboard_url"] = dashboard_url
        initial = render.validate_settings({}, initial, self.assets)
        self.bundle = load_bundle(directory)
        if self.bundle:
            self.bundle["state"].setdefault("display_settings", self.bundle["state"]["settings"])
        if self.bundle and self.bundle["state"].get("demo") != demo:
            self.bundle = None  # Never serve sample observations as live detections.
        try:
            self.settings = render.validate_settings({}, self.bundle["state"]["settings"] if self.bundle else initial, self.assets)
        except (ValueError, TypeError, KeyError):
            self.bundle = None  # Recover from an incompatible/deleted artwork selection.
            self.settings = initial
        self.error = "Waiting for a fresh BirdNET update" if not demo else None
        self.last_success = None
        # A restored or overnight print needs fresh observations before its
        # first active frame response, even if the polling thread is asleep.
        self.resume_pending = bool(self.bundle)
        if self.bundle and not self.schedule()["active"]:
            self.error = None  # An intentional scheduled pause is not a fetch failure.
            try:
                self.last_success = datetime.fromisoformat(self.bundle["state"]["stats"]["observed_at"]).timestamp()
            except ValueError:
                pass
        self.csrf_token = secrets.token_urlsafe(32)
        self.library_lock = threading.Lock()
        self.library = None
        self.library_updated = 0

    def library_state(self):
        with self.library_lock:
            if self.library and time.time() - self.library_updated < 3600:
                return self.library
            payload = json.loads((ROOT / "demo.json").read_text()) if self.demo else get_json(self.base, "/api/v2/analytics/species/summary?limit=1000")
            report = audit_history(payload, {"assets": self.assets})
            reviewed = {a["id"] for a in self.assets if a.get("review", {}).get("status") == "reviewed"}
            for row in report["rows"]:
                row["artwork_reviewed"] = bool(row["artwork_ids"]) and all(key in reviewed for key in row["artwork_ids"])
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.directory / "library-audit.tmp"
            temporary.write_text(json.dumps(report, indent=2))
            temporary.replace(self.directory / "library-audit.json")
            self.library, self.library_updated = report, time.time()
            return report

    def state(self):
        with self.lock:
            current = dict(self.bundle["state"]) if self.bundle else {"settings": self.settings, "stats": None, "revision": None}
            return {**current, "artworks": self.assets, "error": self.error,
                    "last_success": self.last_success, "demo": self.demo,
                    "schedule": self.schedule(),
                    "pending_settings": bool(self.bundle and self.settings != self.bundle["state"].get("display_settings", self.settings))}

    def schedule(self):
        return schedule_state(self.settings["schedule"], datetime.now(self.timezone))

    def build(self, birds, date, settings, observed_at, observation_timezone=None):
        canvas, selected = render.compose(birds, settings, self.assets, self.artwork_dir)
        frame, preview = render.pack(canvas)
        selected_ids = {b["scientific_name"]: a["id"] for b, a in selected}
        available = {a["scientific_name"] for a in self.assets}
        stats = dict(date=date, species=[{**b, "artwork_id": selected_ids.get(b["scientific_name"]),
                                         "illustrated": b["scientific_name"] in selected_ids,
                                         "artwork_available": b["scientific_name"] in available} for b in birds],
                     total_detections=sum(b["count"] for b in birds), species_count=len(birds),
                     illustrated_count=len(selected), confidence_threshold=self.threshold,
                     observed_at=observed_at,
                     timezone=observation_timezone or settings["schedule"]["timezone"])
        state = dict(settings=settings, display_settings=settings, stats=stats,
                     revision=hashlib.sha256(frame).hexdigest(), demo=self.demo)
        return dict(frame=frame, preview=preview, art=render.png(canvas), state=state)

    def refresh(self, resume_only=False):
        # A sunrise request may coincide with the regular poll. Share the work
        # and only return the newly published bundle to a waiting display.
        with self.refresh_lock:
            if resume_only:
                with self.lock:
                    if not self.resume_pending:
                        return
            self._refresh()

    def _refresh(self):
        with self.lock:
            if not self.schedule()["active"] and self.bundle:
                self.resume_pending = True
                return  # Preserve both print and its observations across midnight.
            zone = ZoneInfo(self.settings["schedule"]["timezone"])
        now = datetime.now(zone)
        if self.demo:
            payload = json.loads((ROOT / "demo.json").read_text())
        else:
            # Query the station's configured local day, never the health API's
            # UTC calendar day (which can be tomorrow in the evening).
            # BirdNET's query is a percentage (80), while per-row confidence
            # is a fraction (.8). Filtering only max_confidence would include
            # every low-confidence call for a species with one confident hit.
            payload = get_json(self.base, "/api/v2/analytics/species/daily?" + urlencode({
                "date": now.date().isoformat(), "min_confidence": self.threshold * 100}))
        birds = daily_birds(payload, self.threshold)
        with self.lock:
            if not self.schedule()["active"] and self.bundle:
                self.resume_pending = True
                return  # The cutoff may have passed while the request was in flight.
            bundle = self.build(birds, now.date().isoformat(), self.settings, now.isoformat(), str(zone))
            save_bundle(self.directory, bundle)
            self.bundle = bundle
            self.last_success = time.time()
            self.error = None
            self.resume_pending = False

    def frame_for_display(self):
        with self.lock:
            status = self.schedule()
            if not status["active"]:
                self.resume_pending = bool(self.bundle)
                return self.bundle, status["sleep_seconds"]
            refresh_needed = self.resume_pending and bool(self.bundle)
        if refresh_needed:
            # Do not serve the old ETag at sunrise: the device would otherwise
            # skip it and sleep for another full refresh interval.
            self.refresh(resume_only=True)
        with self.lock:
            status = self.schedule()
            if not status["active"]:
                self.resume_pending = bool(self.bundle)
            return self.bundle, status["sleep_seconds"]

    def update_settings(self, patch):
        with self.lock:
            settings = render.validate_settings(patch, self.settings, self.assets)
            if not self.bundle:
                raise ValueError("Wait for the first BirdNET update before saving")
            stats = self.bundle["state"]["stats"]
            birds = stats["species"]
            active = schedule_state(settings["schedule"], datetime.now(self.timezone))["active"]
            if active:
                bundle = self.build(birds, stats["date"], settings, stats["observed_at"], stats.get("timezone"))
            else:
                bundle = {**self.bundle, "state": {**self.bundle["state"], "settings": settings}}
            # Persist settings and all images together before publishing to
            # concurrent request handlers. Failure leaves the old state intact.
            save_bundle(self.directory, bundle)
            self.settings, self.bundle = settings, bundle
            if not active:
                self.resume_pending = True
            return self.state()

    def run(self):
        while True:
            try:
                self.refresh()
            except Exception as exc:
                with self.lock:
                    self.error = type(exc).__name__
                LOG.warning("BirdNET update failed (%s); preserving last print", type(exc).__name__)
            time.sleep(self.interval)


def handler_for(feed):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def send(self, code, body, kind="application/json", tag=None, head=False, hold_seconds=0):
            if tag and any(t.strip().removeprefix("W/") in (tag, "*") for t in self.headers.get("If-None-Match", "").split(",")):
                code = 304
            self.send_response(code)
            self.send_header("Content-Type", kind)
            if code != 304:
                self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache" if tag else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if tag:
                self.send_header("ETag", tag)
            if hold_seconds:
                self.send_header("X-FederFunk-Hold-Seconds", str(hold_seconds))
            self.end_headers()
            if code != 304 and not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        def json(self, code, payload, head=False):
            self.send(code, json.dumps(payload).encode(), head=head)

        def valid_host(self):
            try:
                hostname = urlsplit("http://" + self.headers.get("Host", "")).hostname
                if hostname in ("localhost", "127.0.0.1", "::1", urlsplit(feed.settings["dashboard_url"]).hostname):
                    return bool(hostname)
                ipaddress.ip_address(hostname)
                return True
            except ValueError:
                return False

        def do_HEAD(self):
            self.do_GET(head=True)

        def do_GET(self, head=False):
            if not self.valid_host():
                self.json(403, {"error": "Use the server's IP address or configured dashboard URL"}, head)
                return
            path = urlsplit(self.path).path
            bundle = feed.bundle
            if path == "/api/state":
                self.json(200, feed.state(), head)
            elif path == "/api/library":
                try:
                    self.json(200, feed.library_state(), head)
                except (OSError, ValueError, KeyError, TypeError):
                    self.json(503, {"error": "The species history is temporarily unavailable"}, head)
            elif path == "/api/settings":
                self.json(200, {"settings": feed.settings, "csrf_token": feed.csrf_token}, head)
            elif path == "/health":
                state = feed.state()
                healthy = bool(bundle) and (not state["schedule"]["active"] or (state["last_success"] and not state["error"]))
                self.json(200 if healthy else 503,
                          {**state, "ready": bool(bundle), "renderVersion": 3,
                           "frameBytes": len(bundle["frame"]) if bundle else 0,
                           "etag": render.etag(bundle["frame"]) if bundle else None}, head)
            elif path == "/credits":
                self.json(200, {"assets": feed.assets}, head)
            elif path in ("/api/v1/display/current_large.bin", "/preview.png", "/art.png"):
                hold = 0
                if path == "/api/v1/display/current_large.bin":
                    try:
                        bundle, hold = feed.frame_for_display()
                    except Exception as exc:
                        with feed.lock:
                            feed.error = type(exc).__name__
                        self.json(503, {"error": "The new print is not ready; the previous image is preserved"}, head)
                        return
                if not bundle:
                    self.json(503, {"error": "The first print is not ready"}, head)
                    return
                key = {"/preview.png": "preview", "/art.png": "art"}.get(path, "frame")
                data = bundle[key]
                self.send(200, data, "application/octet-stream" if key == "frame" else "image/png", render.etag(data), head, hold)
            elif path.startswith("/artwork/") and path.endswith(".png"):
                asset = next((a for a in feed.assets if path == "/artwork/" + a["id"] + ".png"), None)
                if not asset:
                    self.json(404, {"error": "Unknown artwork"}, head)
                else:
                    data = (feed.artwork_dir / asset["file"]).read_bytes()
                    self.send(200, data, "image/png", render.etag(data), head)
            elif path in ("/", "/app.js", "/style.css"):
                filename = "index.html" if path == "/" else path[1:]
                kind = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "style.css": "text/css; charset=utf-8"}[filename]
                self.send(200, (ROOT / "web" / filename).read_bytes(), kind, head=head)
            else:
                self.json(404, {"error": "Not found"}, head)

        def do_POST(self):
            self.close_connection = True
            if not self.valid_host() or urlsplit(self.path).path != "/api/settings":
                self.json(403, {"error": "Request not allowed"})
                return
            origin = self.headers.get("Origin")
            if (origin and urlsplit(origin).netloc != self.headers.get("Host")) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.json(403, {"error": "Use controls on the dashboard itself"})
                return
            if not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), feed.csrf_token):
                self.json(403, {"error": "Reload the page before saving settings"})
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if self.headers.get("Transfer-Encoding") or not 0 < size <= 16384 or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    raise ValueError("Send a JSON settings object (maximum 16 KB)")
                self.connection.settimeout(10)
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError("Incomplete settings request")
                result = feed.update_settings(json.loads(data))
                self.json(200, result)
            except (ValueError, TypeError, KeyError):
                self.json(400, {"error": "Invalid settings. Check the values, artwork choices, and QR URL."})
            except (OSError, RuntimeError):
                self.json(500, {"error": "Could not save the new print. The previous settings remain active."})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--birdnet", default=os.getenv("BIRDNET_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--bind", default=os.getenv("FEED_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FEED_PORT", "8001")))
    parser.add_argument("--state", type=Path, default=Path(os.getenv("STATE_DIRECTORY", str(ROOT / "state"))))
    parser.add_argument("--interval", type=int, default=int(os.getenv("FEED_INTERVAL", "300")))
    parser.add_argument("--confidence", type=float, default=float(os.getenv("MIN_CONFIDENCE", ".8")))
    parser.add_argument("--timezone", default=os.getenv("FEED_TIMEZONE", "America/Denver"))
    parser.add_argument("--dashboard-url", default=os.getenv("DASHBOARD_URL"),
                        help="Reachable dashboard URL for the QR code on a new installation; saved settings take precedence")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 30 or not 0 <= args.confidence <= 1:
        parser.error("Interval must be at least 30 seconds; confidence must be 0..1")
    if args.dashboard_url is not None:
        try:
            render.validate_settings({"show_qr": True, "dashboard_url": args.dashboard_url}, {}, [])
        except (ValueError, TypeError):
            # URL parsing errors can echo credentials or malformed port text.
            parser.error("Dashboard URL must be a valid HTTP(S) address without credentials")
    logging.basicConfig(level=logging.INFO)
    service = Feed(args.birdnet, args.state, args.interval, args.confidence, args.timezone, args.demo,
                   dashboard_url=args.dashboard_url)
    if args.once:
        service.refresh()
        return
    server = ThreadingHTTPServer((args.bind, args.port), handler_for(service))
    threading.Thread(target=service.run, daemon=True).start()
    LOG.info("Naturalist dashboard: http://%s:%s/", args.bind, args.port)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
