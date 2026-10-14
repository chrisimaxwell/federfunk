#!/usr/bin/env python3
"""Audit artwork against all reported BirdNET labels, without confirming sightings.

Examples (run from the repository root)::

    python3 naturalist/audit_library.py --history /path/to/history.json
    python3 naturalist/audit_library.py --birdnet http://birdnet.local:8080

Optional aliases are an explicit JSON object mapping a reported scientific name
to a scientific name in the artwork manifest. No fuzzy matching or substitutions
are performed. History exports may contain extra fields; only names, count, and
maximum confidence are retained in the report.
"""

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
MAX_BYTES = 8_000_000
REVIEW_CONFIDENCE = 0.8


def _name(value, field):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError(f"Invalid {field}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"Invalid {field}")
    return value.strip()


def audit_history(payload, manifest):
    """Return a JSON-safe coverage report; inputs are not changed.

    ``species_count`` counts distinct reported scientific-name labels, including
    explicit aliases as separate source labels. Confidence only adds a review
    flag: no label or detection is excluded from the all-history denominator.
    A missing exact match leaves taxonomy unresolved, not automatically wrong.
    """
    if not isinstance(payload, list) or len(payload) > 20_000:
        raise ValueError("Expected a list of reported species labels")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        raise ValueError("Expected an artwork manifest with an assets list")
    catalogue = {}
    asset_ids = set()
    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            raise ValueError("Invalid artwork entry")
        scientific = _name(asset.get("scientific_name"), "artwork scientific name")
        asset_id = _name(asset.get("id"), "artwork id")
        if asset_id in asset_ids:
            raise ValueError("Duplicate artwork id")
        asset_ids.add(asset_id)
        catalogue.setdefault(scientific, []).append(asset_id)
    aliases = manifest.get("aliases", {})
    if not isinstance(aliases, dict):
        raise ValueError("Aliases must map reported scientific names to catalogue names")
    for alias, target in aliases.items():
        if _name(alias, "alias") != alias or _name(target, "alias target") != target:
            raise ValueError("Alias names must not contain surrounding whitespace")
        if target not in catalogue or alias in catalogue:
            raise ValueError("Alias must point directly to a catalogue name and not replace an exact match")

    rows = []
    seen = set()
    for row in payload:
        if not isinstance(row, dict):
            raise ValueError("Invalid reported label")
        scientific = _name(row.get("scientific_name"), "reported scientific name")
        common = _name(row.get("common_name") or scientific, "reported common name")
        count, confidence = row.get("count"), row.get("max_confidence")
        if type(count) is not int or not 0 <= count <= 2**63 - 1:
            raise ValueError("Detection count must be a non-negative 64-bit integer")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1 or not math.isfinite(confidence):
            raise ValueError("Maximum confidence must be between zero and one")
        if scientific in seen:
            raise ValueError("Duplicate reported scientific-name label")
        seen.add(scientific)
        canonical = aliases.get(scientific, scientific)
        artworks = sorted(catalogue.get(canonical, []))
        rows.append({
            "scientific_name": scientific,
            "common_name": common,
            "count": count,
            "max_confidence": confidence,
            "artwork_ids": artworks,
            "covered": bool(artworks),
            "matched_scientific_name": canonical if artworks else None,
            "taxonomy_status": ("explicit_alias" if scientific in aliases else
                                "exact_match" if artworks else "unresolved"),
            "review_status": ("low_confidence_review" if confidence < REVIEW_CONFIDENCE
                              else "reported_label_not_verified"),
        })
    rows.sort(key=lambda row: (-row["count"], row["scientific_name"]))
    total = sum(row["count"] for row in rows)
    covered_detections = sum(row["count"] for row in rows if row["covered"])
    covered = sum(row["covered"] for row in rows)
    return {
        "schema_version": 1,
        "scope": "all_reported_labels",
        "note": "BirdNET classification labels are not verified bird sightings. Missing artwork does not resolve taxonomy.",
        "species_count": len(rows),
        "covered_species": covered,
        "missing_species": len(rows) - covered,
        "total_detections": total,
        "covered_detections": covered_detections,
        "detection_coverage_percent": round(100 * covered_detections / total, 2) if total else 0.0,
        "confidence_review_threshold": REVIEW_CONFIDENCE,
        "low_confidence_species": sum(row["max_confidence"] < REVIEW_CONFIDENCE for row in rows),
        "rows": rows,
    }


def _read_json(path):
    with Path(path).open("rb") as source:
        body = source.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("JSON file is too large")
    return json.loads(body)


def _history_from_birdnet(base):
    parsed = urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("BirdNET URL must be an HTTP(S) base URL without credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("BirdNET base URL must not contain a query or fragment")
    parsed.port  # Validate malformed or out-of-range ports before requesting.
    endpoint = base.rstrip("/") + "/api/v2/analytics/species/summary"
    request = Request(endpoint, headers={"User-Agent": "FederFunk-Naturalist-Library-Audit/1.0"})
    with urlopen(request, timeout=30) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("BirdNET response is too large")
    return json.loads(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--history", type=Path, help="All-history BirdNET species-summary JSON file")
    source.add_argument("--birdnet", help="BirdNET-Go base URL; queries all history without date/confidence filters")
    parser.add_argument("--manifest", type=Path, default=ROOT / "artwork/manifest.json")
    parser.add_argument("--aliases", type=Path, help="Optional explicit scientific-name alias JSON object")
    parser.add_argument("--output", type=Path, default=ROOT / "state/library-audit.json")
    args = parser.parse_args()
    try:
        payload = _read_json(args.history) if args.history else _history_from_birdnet(args.birdnet)
        manifest = _read_json(args.manifest)
        if args.aliases:
            if not isinstance(manifest, dict):
                raise ValueError("Invalid artwork manifest")
            explicit = _read_json(args.aliases)
            if not isinstance(explicit, dict) or not isinstance(manifest.get("aliases", {}), dict):
                raise ValueError("Aliases must be a JSON object")
            existing = manifest.get("aliases", {})
            if any(key in existing and existing[key] != value for key, value in explicit.items()):
                raise ValueError("Conflicting explicit aliases")
            manifest = {**manifest, "aliases": {**existing, **explicit}}
        report = audit_history(payload, manifest)
        report["generated_at"] = datetime.now(timezone.utc).isoformat()
        report["source"] = {"kind": "history_file" if args.history else "birdnet_all_history",
                            "history_file": str(args.history.resolve()) if args.history else None,
                            "manifest_file": str(args.manifest.resolve()),
                            "aliases_file": str(args.aliases.resolve()) if args.aliases else None}
        # Local reports contain station history. The default directory is ignored.
        # Do not copy the private server address or source recording metadata.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix="library-audit-", suffix=".tmp", dir=args.output.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as output:
                json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
            os.replace(temporary, args.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    except (OSError, ValueError) as error:
        # A network exception may contain a private URL; report its type only.
        parser.exit(1, f"Library audit failed ({type(error).__name__}). Check the source and manifest.\n")
    print(args.output)


if __name__ == "__main__":
    main()
