#!/usr/bin/env python3
"""Generate a native six-color landscape smoke-test frame without dependencies."""

import argparse
from pathlib import Path

PANEL_SIZES = {"small": (800, 480), "large": (1600, 1200)}
COLORS = (0x0, 0x1, 0x2, 0x3, 0x5, 0x6)


def make_frame(width, height):
    frame = bytearray(width * height // 2)
    marker = max(8, width // 40)

    def color_at(x, y):
        # White paper margin; black outline keeps the full canvas visible.
        if x < 2 or y < 2 or x >= width - 2 or y >= height - 2:
            return 0x0
        if x < marker or y < marker or x >= width - marker or y >= height - marker:
            return 0x1
        # Three distinct corner markers identify rotation/mirroring:
        # red top-left, blue top-right, green bottom-left.
        if x < marker * 3 and y < marker * 3:
            return 0x3
        if x >= width - marker * 3 and y < marker * 3:
            return 0x5
        if x < marker * 3 and y >= height - marker * 3:
            return 0x6
        return COLORS[min(x * len(COLORS) // width, len(COLORS) - 1)]

    for y in range(height):
        for x in range(0, width, 2):
            frame[y * (width // 2) + x // 2] = (
                color_at(x, y) << 4
            ) | color_at(x + 1, y)
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", choices=PANEL_SIZES, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.output.exists():
        parser.error("Output already exists; choose a new path to preserve it.")
    width, height = PANEL_SIZES[options.panel]
    options.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also prevents a race from overwriting another file.
    with options.output.open("xb") as output:
        output.write(make_frame(width, height))
    print(f"Created {width}x{height} test frame ({width * height // 2} bytes).")


if __name__ == "__main__":
    main()
