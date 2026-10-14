"""An ordered natural-history plate, retaining shared frequency sizing."""
import math


def arrange(items, region, label_lines=0):
    if not items:
        return []
    left, top, width, height = region
    candidates = []
    for columns in range(1, len(items) + 1):
        rows = math.ceil(len(items) / columns)
        cell_w, cell_h = width / columns, height / rows
        label_size = max(12, min(24, int(cell_w / 11)))
        line_height = max(16, round(label_size * 29 / 24))
        label_h = label_lines * line_height + (18 if label_lines else 0)
        space_w, space_h = cell_w - 28, cell_h - 28 - label_h
        if space_w < 28 or space_h < 28:
            continue
        factor = min(min(space_w / item["w"], space_h / item["h"]) for item in items)
        candidates.append((factor, columns, rows, cell_w, cell_h, label_size, line_height, label_h))
    if not candidates:
        # The collage's bounded shelf fallback handles unusually large libraries.
        from collage import arrange as collage_arrange
        return collage_arrange(items, region, label_lines)
    factor, columns, rows, cell_w, cell_h, label_size, line_height, label_h = max(candidates)
    result = []
    for index, item in enumerate(items):
        row, column = divmod(index, columns)
        # Center the final incomplete row rather than leaving it left-heavy.
        in_row = min(columns, len(items) - row * columns)
        cx = left + (width - in_row * cell_w) / 2 + (column + .5) * cell_w
        w, h = max(1, round(item["w"] * factor)), max(1, round(item["h"] * factor))
        y = top + row * cell_h + (cell_h - h - label_h) / 2
        result.append(dict(item=item, x=cx-w/2, y=y, w=w, h=h,
                           cx=cx, label_width=cell_w-20, label_size=label_size,
                           label_line_height=line_height, label_height=label_h))
    return result
