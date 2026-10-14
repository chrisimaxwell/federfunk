from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ScheduleHoldTests(unittest.TestCase):
    def test_hold_parser_status_gating_and_sleep_duration(self):
        compiler = shutil.which("clang++") or shutil.which("g++")
        if not compiler:
            self.skipTest("A C++ compiler is required for the firmware host test")
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "schedule-hold"
            subprocess.run([
                compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-Isrc", "tests/schedule_hold_test.cpp",
                "-o", str(executable),
            ], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([str(executable)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
