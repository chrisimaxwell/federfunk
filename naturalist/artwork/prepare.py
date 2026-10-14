#!/usr/bin/env python3
"""Rebuild transparent historical-art crops without painting or synthesizing pixels.

Curated contours in crops.json are traced against a 600-pixel-wide reference
of the whole preserved source. The original RGB pixels are retained; only
alpha, bounding crop, recorded orientation, and a final maximum-size resize change.
"""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter
ROOT = Path(__file__).resolve().parent

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    sources = {row['id']: row for row in json.loads((ROOT/'ingestion.json').read_text())}
    assets = []
    for spec in json.loads((ROOT/'crops.json').read_text()):
        source = sources[spec['source_id']]
        with Image.open(ROOT/source['source_file']) as original:
            picture = original.convert('RGBA')
        scale = picture.width / 600
        mask = Image.new('L', picture.size, 0)
        draw = ImageDraw.Draw(mask)
        for polygon in spec['polygons']:
            draw.polygon([(round(x*scale), round(y*scale)) for x,y in polygon], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(0.35*scale))
        picture.putalpha(mask)
        bounds = mask.getbbox()
        picture = picture.crop(bounds)
        rotation = spec.get('rotation_degrees', 0)
        if rotation:
            picture = picture.rotate(rotation, Image.Resampling.BICUBIC, expand=True)
            picture = picture.crop(picture.getchannel('A').getbbox())
        picture.thumbnail((1400,1400), Image.Resampling.LANCZOS)
        path = ROOT/'prepared'/(spec['id']+'.png')
        picture.save(path, optimize=True)
        row = {k:v for k,v in spec.items() if k not in ('polygons','source_id')}
        row.update({k:v for k,v in source.items() if k != 'id'})
        row.update(file=str(path.relative_to(ROOT)), rights=source.get('rights', 'Public domain'),
                   rights_url=source.get('rights_url', source['source_url']+'#Licensing'),
                   source_sha256=digest(ROOT/source['source_file']), sha256=digest(path),
                   width=picture.width, height=picture.height,
                   processing={'method':'Manual contour alpha mask; original pigment preserved; tightly cropped and resized',
                               'recipe':'crops.json', 'reference_width':600,
                               'source_crop_box':list(bounds), 'rotation_degrees':rotation,
                               'alpha_edge_blur_reference_pixels':0.35})
        assets.append(row)
    # Independently curated supplements use paths relative to this artwork root.
    supplement = ROOT/'additions'/'manifest.json'
    if supplement.exists():
        extra = json.loads(supplement.read_text()).get('assets', [])
        ids = {row['id'] for row in assets}
        for row in extra:
            if row['id'] in ids:
                raise ValueError(f'Duplicate supplemental artwork id: {row["id"]}')
            assets.append(row)
            ids.add(row['id'])
    (ROOT/'manifest.json').write_text(json.dumps({'schema_version':1,'assets':assets},indent=2)+'\n')
    print(f'Prepared {len(assets)} assets covering {len({a["scientific_name"] for a in assets})} species.')
if __name__ == '__main__':
    main()
