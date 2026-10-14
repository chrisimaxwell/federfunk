#!/usr/bin/env python3
"""Check every published artwork path, checksum and transparent PNG."""
import hashlib
import json
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parent

def checked_path(relative):
    p = (ROOT/relative).resolve()
    if ROOT not in p.parents:
        raise ValueError('Artwork path escapes the library')
    return p

def main():
    manifest = json.loads((ROOT/'manifest.json').read_text())
    assert manifest['schema_version'] == 1
    seen = set()
    for asset in manifest['assets']:
        assert asset['id'] not in seen
        seen.add(asset['id'])
        for required in ('scientific_name', 'common_name', 'creator', 'date', 'rights', 'rights_url', 'source_url'):
            assert asset[required], (asset['id'], required)
        review = asset.get('review', {})
        assert review.get('status') == 'reviewed', (asset['id'], 'not reviewed')
        for field in ('date', 'species_check', 'orientation', 'crop'):
            assert review.get(field), (asset['id'], 'review', field)
        if review.get('reviewed_sha256'):
            assert review['reviewed_sha256'] == asset['sha256'], (asset['id'], 'changed since visual review')
        for key, checksum in (('file', 'sha256'), ('source_file', 'source_sha256')):
            path = checked_path(asset[key])
            assert hashlib.sha256(path.read_bytes()).hexdigest() == asset[checksum], path
        with Image.open(checked_path(asset['file'])) as picture:
            assert picture.format == 'PNG' and picture.mode == 'RGBA'
            assert picture.size == (asset['width'], asset['height'])
            assert picture.getchannel('A').getextrema() == (0, 255)
            assert picture.width > 20 and picture.height > 20
    print(f'Verified {len(seen)} reviewed artwork variants, paths, source hashes, and alpha channels.')
if __name__ == '__main__':
    main()
