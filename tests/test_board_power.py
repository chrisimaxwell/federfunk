"""Exercise actual firmware power cleanup using bounded fake I2C/GPIO."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BoardPowerTests(unittest.TestCase):
    def test_supported_profile_failure_cleanup_and_small_profile_isolation(self):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            self.skipTest("A C++ compiler is required for the firmware host test")
        with tempfile.TemporaryDirectory() as directory:
            for large, enabled in [(1, 1), (0, 1), (1, 0)]:
                executable = Path(directory) / f"board-power-{large}-{enabled}"
                subprocess.run([
                    compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-Itests/host", "-Isrc",
                    f"-DBIRDDISPLAY_PANEL_13IN3E6={large}",
                    f"-DBIRDDISPLAY_AUDIO_POWERDOWN={enabled}",
                    "tests/board_power_test.cpp", "-o", str(executable),
                ], cwd=ROOT, check=True, capture_output=True, text=True)
                subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
