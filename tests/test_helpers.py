import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generator = load_script("generate_test_frame")
bootstrap = load_script("bootstrap")


class TestFrame(unittest.TestCase):
    def test_both_sizes_colors_and_orientation_markers(self):
        for name, (width, height) in generator.PANEL_SIZES.items():
            with self.subTest(panel=name):
                data = generator.make_frame(width, height)
                self.assertEqual(len(data), 192000 if name == "small" else 960000)
                self.assertTrue(all(
                    (byte >> 4) in generator.COLORS and (byte & 15) in generator.COLORS
                    for byte in data
                ))

                def pixel(x, y):
                    byte = data[y * (width // 2) + x // 2]
                    return byte & 15 if x & 1 else byte >> 4

                marker = max(8, width // 40)
                self.assertEqual(pixel(marker + 1, marker + 1), 3)
                self.assertEqual(pixel(width - marker - 2, marker + 1), 5)
                self.assertEqual(pixel(marker + 1, height - marker - 2), 6)
                self.assertEqual(pixel(0, 0), 0)
                self.assertEqual(pixel(3, 3), 1)
                for band, color in enumerate(generator.COLORS):
                    self.assertEqual(pixel(width * (2 * band + 1) // 12, height // 2), color)

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "existing.bin"
            output.write_bytes(b"preserve this file")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/generate_test_frame.py"),
                 "--panel", "small", "--output", str(output)],
                capture_output=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b"preserve this file")


class CredentialGuard(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "src").mkdir()
        self.password = "dummy-password-for-test-only"
        (self.root / "src/BirdDisplayConfig.h").write_text(
            'static constexpr char wifiSsid[] = "dummy-network-for-test-only";\n'
            f'static constexpr char wifiPassword[] = "{self.password}";\n',
            encoding="utf-8",
        )
        (self.root / "README.md").write_text("Safe example source.\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)

    def tearDown(self):
        self.directory.cleanup()

    def check(self):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/check_private_config.py")],
            cwd=self.root, text=True, capture_output=True,
        )

    def test_untracked_private_config_is_allowed(self):
        self.assertEqual(self.check().returncode, 0)

    def test_public_placeholders_are_not_treated_as_secrets(self):
        template = (ROOT / "src/config.example.h").read_bytes()
        (self.root / "src/config.example.h").write_bytes(template)
        (self.root / "src/BirdDisplayConfig.h").write_bytes(template)
        subprocess.run(["git", "add", "src/config.example.h"], cwd=self.root, check=True)
        self.assertEqual(self.check().returncode, 0)

    def test_private_config_is_rejected_without_printing_password(self):
        subprocess.run(["git", "add", "src/BirdDisplayConfig.h"], cwd=self.root, check=True)
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(self.password, result.stdout + result.stderr)

    def test_password_copied_to_public_file_is_rejected(self):
        (self.root / "README.md").write_text(self.password, encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=self.root, check=True)
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wifiPassword", result.stderr)
        self.assertNotIn(self.password, result.stdout + result.stderr)

    def test_inspects_staged_content_not_working_copy(self):
        # An un-staged edit is not part of the commit under review.
        (self.root / "README.md").write_text(self.password, encoding="utf-8")
        self.assertEqual(self.check().returncode, 0)

    def test_staged_firmware_is_rejected(self):
        (self.root / "firmware.bin").write_bytes(b"configured firmware")
        subprocess.run(["git", "add", "firmware.bin"], cwd=self.root, check=True)
        self.assertNotEqual(self.check().returncode, 0)


class BootstrapConfig(unittest.TestCase):
    def test_preserves_existing_private_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            private = root / "src/BirdDisplayConfig.h"
            private.write_text("preserve owner settings", encoding="utf-8")
            with mock.patch.object(bootstrap, "__file__", str(root / "scripts/bootstrap.py")), \
                    mock.patch.object(bootstrap.subprocess, "run"), \
                    mock.patch("builtins.print"):
                bootstrap.main()
            self.assertEqual(private.read_text(encoding="utf-8"), "preserve owner settings")

    def test_creates_only_placeholder_config_for_new_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            template = root / "src/config.example.h"
            template.write_text('wifiSsid = "YOUR_WIFI_SSID";', encoding="utf-8")
            with mock.patch.object(bootstrap, "__file__", str(root / "scripts/bootstrap.py")), \
                    mock.patch.object(bootstrap.subprocess, "run"), \
                    mock.patch("builtins.print"):
                bootstrap.main()
            self.assertEqual(
                (root / "src/BirdDisplayConfig.h").read_bytes(), template.read_bytes()
            )


if __name__ == "__main__":
    unittest.main()
