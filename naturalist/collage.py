"""Deterministic silhouette packing for a loose natural-history collage.

Every drawing uses one shared length multiplier, including the fallback.
Labels have a real size floor: repeatedly shrinking the birds alone cannot
make a greedy packing reliable. A bounded shelf search handles that case.
"""
import math
from statistics import median

from PIL import Image, ImageDraw, ImageChops, ImageFilter

UNIT = 8  # Only collision maps are coarse; drawings stay full resolution.
GAP = 16
ANCHORS = [(.35, .29), (.67, .42), (.36, .65), (.66, .76),
           (.62, .13), (.22, .48), (.38, .88), (.77, .59),
           (.20, .14), (.80, .26), (.15, .77), (.75, .91)]


def _labels(lines, size):
    line_height = max(16, round(size * 29 / 24))
    return dict(label_size=size, label_line_height=line_height,
                label_height=lines * line_height + (18 if lines else 0),
                min_width=max(128, round(245 * size / 24)) if lines else 0)


def _dimensions(item, factor, labels):
    width = max(1, round(item["w"] * factor))
    height = max(1, round(item["h"] * factor))
    return width, height, max(width, labels["min_width"]), height + labels["label_height"]


def _footprint(item, size, labels):
    width, height, box_width, box_height = size
    mw, mh = math.ceil(box_width / UNIT), math.ceil(box_height / UNIT)
    footprint = Image.new("L", (mw, mh))
    # Threshold before reducing so fine feet and feather tips are retained.
    shape = item["image"].getchannel("A").point(lambda p: 255 if p else 0)
    alpha = shape.resize((math.ceil(width / UNIT), math.ceil(height / UNIT)), Image.Resampling.BOX)
    alpha = alpha.point(lambda p: 255 if p else 0)
    footprint.paste(alpha, (max(0, (mw - alpha.width) // 2), 0))
    if labels["label_height"]:
        ImageDraw.Draw(footprint).rectangle((0, height // UNIT, mw, mh), fill=255)
    return footprint.filter(ImageFilter.MaxFilter(3))


def _placement(item, size, box_x, y, labels):
    width, height, box_width, _ = size
    return dict(item=item, x=box_x + (box_width - width) / 2, y=y,
                w=width, h=height, label_width=box_width, cx=box_x + box_width / 2,
                label_size=labels["label_size"], label_line_height=labels["label_line_height"],
                label_height=labels["label_height"])


def _anchors(count):
    if count <= len(ANCHORS):
        return ANCHORS[:count]
    # A sunflower spiral distributes larger collections around the oval,
    # instead of sending every thirteenth bird to an occupied anchor.
    golden_angle = math.pi * (3 - math.sqrt(5))
    return [(.5 + .42 * math.sqrt((i + .5) / count) * math.cos(i * golden_angle),
             .5 + .45 * math.sqrt((i + .5) / count) * math.sin(i * golden_angle))
            for i in range(count)]


def _silhouette_layout(items, region, labels, factor, anchors):
    left, top, width, height = region
    grid_w, grid_h = int(width // UNIT), int(height // UNIT)
    occupied = Image.new("L", (grid_w, grid_h))
    placements = []
    dimensions = [_dimensions(item, factor, labels) for item in items]
    # Place the hardest footprints first, without changing their anchor.
    order = sorted(range(len(items)), key=lambda i: dimensions[i][2] * dimensions[i][3], reverse=True)
    for index in order:
        item, size = items[index], dimensions[index]
        mw, mh = math.ceil(size[2] / UNIT), math.ceil(size[3] / UNIT)
        if mw >= grid_w - 1 or mh >= grid_h - 1:
            return None
        footprint = _footprint(item, size, labels)
        ax, ay = anchors[index]
        target_x, target_y = ax * grid_w, ay * grid_h
        candidates = [(x, y) for y in range(1, grid_h - mh, 2) for x in range(1, grid_w - mw, 2)]
        candidates.sort(key=lambda p: (p[0] + mw / 2 - target_x) ** 2 + (p[1] + mh / 2 - target_y) ** 2)
        for x, y in candidates:
            cx, cy = (x + mw / 2) / grid_w, (y + mh / 2) / grid_h
            if ((cx - .5) / .53) ** 2 + ((cy - .5) / .56) ** 2 > 1:
                continue
            if ImageChops.multiply(occupied.crop((x, y, x + mw, y + mh)), footprint).getbbox():
                continue
            occupied.paste(255, (x, y), footprint)
            placement = _placement(item, size, left + x * UNIT, top + y * UNIT, labels)
            placement["collision"] = (x, y, footprint)
            placements.append(placement)
            break
        else:
            return None
    return placements


def _rows(dimensions, width):
    """Find the least total height of contiguous shelves at a shared scale."""
    count = len(dimensions)
    best = [(math.inf, None)] * (count + 1)
    best[count] = (0, [])
    for start in range(count - 1, -1, -1):
        row_width = row_height = 0
        for end in range(start, count):
            _, _, box_width, box_height = dimensions[end]
            row_width += box_width + (GAP if end > start else 0)
            if row_width > width:
                break
            row_height = max(row_height, box_height)
            remaining_height, remaining_rows = best[end + 1]
            total = row_height + (GAP if end + 1 < count else 0) + remaining_height
            if total < best[start][0]:
                best[start] = (total, [(start, end + 1, row_width, row_height)] + remaining_rows)
    return best[0]


def _shelf_layout(items, region, labels, upper_factor):
    left, top, width, height = region
    inner_width, inner_height = width - 2 * UNIT, height - 2 * UNIT

    def layout_at(factor):
        dimensions = [_dimensions(item, factor, labels) for item in items]
        used_height, rows = _rows(dimensions, inner_width)
        return dimensions, used_height, rows

    dimensions, used_height, rows = layout_at(0)
    if rows is None or used_height > inner_height:
        return None
    low, high = 0, upper_factor
    # Feasibility is monotonic. Eighteen bisections are finer than an output
    # pixel at these canvas sizes; rounding is included in each check.
    for _ in range(18):
        middle = (low + high) / 2
        trial_dimensions, trial_height, trial_rows = layout_at(middle)
        if trial_rows is not None and trial_height <= inner_height:
            low = middle
            dimensions, used_height, rows = trial_dimensions, trial_height, trial_rows
        else:
            high = middle
    placements = []
    extra_y = (inner_height - used_height) / (len(rows) + 1)
    row_y = top + UNIT + extra_y
    for row_index, (start, end, row_width, row_height) in enumerate(rows):
        slack = inner_width - row_width
        # Stagger using only unused shelf space, preserving proven bounds.
        spread = slack * .45 / max(1, end - start - 1) if end - start > 1 else 0
        margin = slack * (1 - (.45 if spread else 0))
        box_x = left + UNIT + margin * (.35 if row_index % 2 else .65)
        for index in range(start, end):
            size = dimensions[index]
            vertical = (.2, .7, .4)[(index + row_index) % 3]
            y = row_y + (row_height - size[3]) * vertical
            placement = _placement(items[index], size, box_x, y, labels)
            footprint = _footprint(items[index], size, labels)
            placement["collision"] = (int((box_x - left) // UNIT), int((y - top) // UNIT), footprint)
            placements.append(placement)
            box_x += size[2] + GAP + spread
        row_y += row_height + GAP + extra_y
    return placements


def arrange(items, region, label_lines):
    if not items:
        return []
    _, _, width, height = region
    if width <= 2 * UNIT or height <= 2 * UNIT or label_lines not in range(4):
        raise ValueError("Invalid collage region or label count")
    if any(item["w"] <= 0 or item["h"] <= 0 or item["weight"] <= 0 for item in items):
        raise ValueError("Illustration sizes and weights must be positive")
    factor = math.sqrt(width * height * (.28 if label_lines else .38) / sum(item["weight"] for item in items))
    profiles = [_labels(label_lines, size) for size in (24, 22, 20, 18, 16, 14, 12)]
    # Dense labels need smaller type too. Leave most of the region for art.
    profile_index = next((index for index, profile in enumerate(profiles)
                          if len(items) * profile["min_width"] * profile["label_height"] <= width * height * .4), len(profiles) - 1)
    labels = profiles[profile_index]
    anchors = _anchors(len(items))
    trial_factor = factor
    for _ in range(20 if not label_lines else 12):
        placements = _silhouette_layout(items, region, labels, trial_factor, anchors)
        if placements is not None:
            return placements
        trial_factor *= .90
    # Fixed label rectangles can trap a greedy search. The fallback proves
    # the whole collection fits without dropping or independently resizing birds.
    candidate = None
    for labels in profiles[profile_index:]:
        placements = _shelf_layout(items, region, labels, factor)
        if placements is not None:
            candidate = placements
            if median(placement["h"] for placement in placements) >= 70 or not label_lines:
                return placements
    if candidate is not None:
        return candidate
    raise ValueError("The collection has more labels than this print region can hold")
