#!/usr/bin/env python3
"""Install local build tools without overwriting private FederFunk settings."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    if sys.version_info < (3, 10):
        raise SystemExit("FederFunk setup requires Python 3.10 or newer.")
    environment = root / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run(
        [str(python), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")],
        check=True,
    )

    private_config = root / "src" / "BirdDisplayConfig.h"
    if private_config.exists():
        print("Preserved existing src/BirdDisplayConfig.h.")
    else:
        shutil.copyfile(root / "src" / "config.example.h", private_config)
        print("Created local src/BirdDisplayConfig.h with placeholder settings.")

    if (root / ".git").exists() and shutil.which("git"):
        result = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=root, text=True, capture_output=True, check=False,
        )
        hook_path = result.stdout.strip()
        if not hook_path:
            subprocess.run(
                ["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True
            )
            print("Enabled the credential-check commit hook.")
        elif hook_path == ".githooks":
            print("Credential-check commit hook is already enabled.")
        else:
            print("Preserved existing Git hooks; run the credential check manually.")

    print("Next: fill the local configuration, identify the board, and select a profile.")
    print("Build tool:", python, "-m platformio")


if __name__ == "__main__":
    main()
