import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit_library


class LibraryAuditTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"assets": [
            {"id": "bird-a", "scientific_name": "Example species"},
            {"id": "bird-b", "scientific_name": "Example species"},
        ]}
        self.row = {"scientific_name": "Example species", "common_name": "Example bird",
                    "count": 3, "max_confidence": .95}

    def test_no_substitution_by_common_name_or_similar_scientific_name(self):
        other = {**self.row, "scientific_name": "Example related"}
        result = audit_library.audit_history([other], self.manifest)
        self.assertFalse(result["rows"][0]["covered"])
        self.assertEqual(result["rows"][0]["artwork_ids"], [])
        self.assertEqual(result["rows"][0]["taxonomy_status"], "unresolved")
        manifest = {**self.manifest, "aliases": {"Example related": "Example species"}}
        result = audit_library.audit_history([other], manifest)
        self.assertTrue(result["rows"][0]["covered"])
        self.assertEqual(result["rows"][0]["artwork_ids"], ["bird-a", "bird-b"])
        self.assertEqual(result["rows"][0]["taxonomy_status"], "explicit_alias")
        self.assertEqual(result["rows"][0]["scientific_name"], "Example related")

    def test_all_reported_labels_and_low_confidence_counts_remain_in_denominator(self):
        # Entirely synthetic labels, unrelated to any station's actual history.
        payload = [{**self.row, "scientific_name": f"Synthetic label {index}",
                    "count": 1, "max_confidence": .2} for index in range(95)]
        payload[0] = {**self.row, "count": 1}
        report = audit_library.audit_history(payload, self.manifest)
        self.assertEqual(report["species_count"], 95)
        self.assertEqual(report["total_detections"], 95)
        self.assertEqual(report["covered_species"], 1)
        self.assertEqual(report["missing_species"], 94)
        self.assertEqual(report["low_confidence_species"], 94)
        self.assertEqual(report["detection_coverage_percent"], 1.05)
        self.assertEqual(sum(row["review_status"] == "low_confidence_review" for row in report["rows"]), 94)

    def test_allowlist_excludes_recordings_and_credentials_without_mutation(self):
        payload = [{**self.row, "recording": "private-recording", "source": "private-source",
                    "thumbnail_url": "http://user:private-token@example.invalid/", "hourly_counts": [99]}]
        before = copy.deepcopy((payload, self.manifest))
        report = audit_library.audit_history(payload, self.manifest)
        encoded = json.dumps(report)
        for value in ("private-recording", "private-source", "private-token", "hourly_counts", "thumbnail_url"):
            self.assertNotIn(value, encoded)
        self.assertEqual((payload, self.manifest), before)
        self.assertEqual(report["rows"][0]["review_status"], "reported_label_not_verified")

    def test_malformed_values_and_ambiguous_aliases_are_rejected(self):
        for key, value in (("count", True), ("count", -1), ("count", 1.5), ("count", 10**1000),
                           ("max_confidence", True), ("max_confidence", float("nan")),
                           ("max_confidence", 1.1), ("max_confidence", 10**1000),
                           ("scientific_name", ""), ("common_name", 12)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                audit_library.audit_history([{**self.row, key: value}], self.manifest)
        for payload in (None, [None], [self.row, self.row], [self.row] * 20_001):
            with self.assertRaises(ValueError):
                audit_library.audit_history(payload, self.manifest)
        for aliases in ({"Other species": "Absent species"}, {"Example species": "Example species"}, []):
            with self.assertRaises(ValueError):
                audit_library.audit_history([self.row], {**self.manifest, "aliases": aliases})
        self.assertEqual(audit_library.audit_history([], self.manifest)["detection_coverage_percent"], 0)
        self.assertEqual(audit_library.audit_history([{**self.row, "count": 0}], self.manifest)["detection_coverage_percent"], 0)

    def test_source_bounds_and_network_errors_do_not_print_private_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (audit_library.MAX_BYTES + 1))
            with self.assertRaises(ValueError):
                audit_library._read_json(path)
        for url in ("file:///tmp/private", "http://user:private-token@example.invalid",
                    "http://example.invalid:99999", "https://example.invalid?token=private-token"):
            with self.assertRaises(ValueError):
                audit_library._history_from_birdnet(url)
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["audit_library.py", "--birdnet", "http://private-station.invalid"]), \
                patch.object(audit_library, "_history_from_birdnet", side_effect=OSError("private-token")), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            audit_library.main()
        self.assertEqual(stdout.getvalue(), "")
        self.assertNotIn("private-token", stderr.getvalue())
        self.assertNotIn("private-station", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
