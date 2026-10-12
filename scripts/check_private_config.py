#!/usr/bin/env python3
"""Reject private settings/artifacts and local credentials in staged content."""

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath


def git(*args):
    return subprocess.check_output(["git", *args])


def read_values(settings):
    if not settings.is_file():
        return {}
    # Read locally, never emit values. These settings use literal C++ strings.
    source = settings.read_text(encoding="utf-8")
    found = {}
    for name in ("wifiSsid", "wifiPassword", "imageUrl", "largeImageUrl"):
        match = re.search(
            rf'\b{name}\s*\[\s*\]\s*=\s*"((?:[^"\\]|\\.)*)"', source
        )
        if match:
            found[name] = match.group(1).encode("utf-8")
    return found


def local_values(root):
    private = read_values(root / "src" / "BirdDisplayConfig.h")
    example = read_values(root / "src" / "config.example.h")
    # Fresh bootstrap settings are public placeholders, not private data.
    return {
        name: value for name, value in private.items()
        if value and not value.startswith(b"YOUR_") and value != example.get(name)
    }


def main():
    root = Path(git("rev-parse", "--show-toplevel").decode().strip())
    # Deletions have no staged blob. Inspect all files in the index so an
    # unchanged tracked secret cannot slip through a later commit.
    names = git("ls-files", "-z").decode("utf-8").split("\0")
    private = local_values(root)
    errors = []
    for name in filter(None, names):
        path = PurePosixPath(name)
        forbidden = (
            path.name == "BirdDisplayConfig.h"
            or any(part in {".pio", ".venv"} for part in path.parts)
            or path.suffix.lower() in {".bin", ".elf", ".hex", ".map", ".log", ".pem", ".key", ".p12", ".pfx"}
            or (path.name.startswith(".env") and path.name != ".env.example")
        )
        if forbidden:
            errors.append(f"{name}: private configuration or build artifact is staged")
            continue
        content = git("show", f":{name}")
        for setting, value in private.items():
            if value in content:
                errors.append(f"{name}: contains the local {setting} value")
    if errors:
        print("FederFunk credential check failed:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        print("Remove private data from the Git index before committing.", file=sys.stderr)
        return 1
    print("FederFunk credential check passed; private configuration and artifacts excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
