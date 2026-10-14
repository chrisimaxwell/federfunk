#!/usr/bin/env python3
"""Reproduce six exact-species historical illustration cutouts.

No painted or generated pixels are introduced. Coordinates refer to each
preserved source scaled to 600 pixels wide. Only alpha, crop, explicit
right-angle orientation, and final sizing are changed.
"""
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    sources = {source['id']: source for source in json.loads((ROOT / 'ingestion-fragment.json').read_text())}
    assets = []
    for spec in json.loads((ROOT / 'crops-fragment.json').read_text()):
        source = sources[spec['source_id']]
        with Image.open(ROOT / source['source_file']) as original:
            picture = original.convert('RGBA')
        scale = picture.width / 600
        mask = Image.new('L', picture.size, 0)
        draw = ImageDraw.Draw(mask)
        for polygon in spec['polygons']:
            draw.polygon([(round(x * scale), round(y * scale)) for x, y in polygon], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(.35 * scale))
        picture.putalpha(mask)
        bounds = mask.getbbox()
        picture = picture.crop(bounds)
        rotation = spec.get('rotation_degrees', 0)
        if rotation:
            picture = picture.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        picture.thumbnail((1400, 1400), Image.Resampling.LANCZOS)
        path = ROOT / 'prepared' / (spec['id'] + '.png')
        picture.save(path, optimize=True)
        row = {key: value for key, value in spec.items() if key not in ('polygons', 'source_id')}
        row.update({key: value for key, value in source.items() if key != 'id'})
        row.update(file=str(path.relative_to(ROOT)), source_sha256=digest(ROOT / source['source_file']),
                   sha256=digest(path), width=picture.width, height=picture.height,
                   variant='default',
                   processing={'method': 'Manual contour alpha mask; original pigment preserved; cropped and resized',
                               'recipe': 'crops-fragment.json', 'reference_width': 600,
                               'source_crop_box': list(bounds), 'rotation_degrees': rotation,
                               'alpha_edge_blur_reference_pixels': .35})
        for field in ('file', 'source_file'):
            row[field] = 'additions/' + row[field]
        row['processing']['recipe'] = 'additions/crops-fragment.json'
        assets.append(row)
    (ROOT / 'manifest.json').write_text(json.dumps({'schema_version': 1, 'assets': assets}, indent=2) + '\n')
    print(f'Prepared {len(assets)} exact-species illustrations.')


if __name__ == '__main__':
    main()
