#!/usr/bin/env python3
"""Authenticate the 22 JPEG-carrier PNG outputs with the desktop public API.

By default reads Android app/build/jpeg-interop. Does not write recovered payloads
or modify inputs. --output writes a JSON report and failures return exit status 1.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from PIL import Image
from generate_jpeg_vectors import (
    ANDROID_ROOT, CASES, COLUMNS, FIXTURES, PUBLIC_KEY, PUBLIC_PASSWORD,
    SOURCE_BYTES, SOURCE_NAME, expected_size, file_snapshot, load_desktop,
)


def verify(inputs, fixtures=FIXTURES, desktop_root=None):
    inputs, fixtures = Path(inputs), Path(fixtures)
    desktop, desktop_path = load_desktop(desktop_root)
    with (fixtures / 'cases.tsv').open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle, delimiter='\t')
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError('Unexpected cases.tsv columns.')
        rows = list(reader)
    if tuple(row['name'] for row in rows) != CASES:
        raise ValueError('Expected exactly the eleven named synthetic JPEG cases.')
    if (fixtures / 'source.bin').read_bytes() != SOURCE_BYTES:
        raise ValueError('Unexpected public source fixture.')
    if (fixtures / 'password.txt').read_text(encoding='utf-8') != PUBLIC_PASSWORD:
        raise ValueError('Unexpected public password fixture.')
    key_path = fixtures / 'synthetic.stegkey'
    if desktop.read_key_file(key_path) != PUBLIC_KEY:
        raise ValueError('Unexpected public key fixture.')
    credentials = {'key': desktop.Credential.from_key_file(key_path),
                   'password': desktop.Credential.from_password(PUBLIC_PASSWORD)}
    results = []
    for row in rows:
        name = row['name']
        size = (int(row['width']), int(row['height']))
        if size != expected_size(name):
            raise ValueError('Unexpected fixture display dimensions: ' + name)
        for mode, credential in credentials.items():
            filename = row[mode + '_png']
            if filename != f'{name}_{mode}.png':
                raise ValueError('Unexpected fixture output filename.')
            path = inputs / filename
            result = {'file': filename, 'mode': mode, 'pass': False}
            try:
                before = file_snapshot(path)
                with path.open('rb') as handle:
                    if handle.read(8) != b'\x89PNG\r\n\x1a\n':
                        raise ValueError('Output does not have a PNG signature.')
                with Image.open(path) as image:
                    if image.format != 'PNG' or image.size != size:
                        raise ValueError('PNG format or oriented dimensions do not match.')
                decoded = desktop.decode_image(path, credential=credential)
                if decoded.filename != SOURCE_NAME or decoded.data != SOURCE_BYTES:
                    raise ValueError('Authenticated original name or content does not match.')
                if file_snapshot(path) != before:
                    raise ValueError('Verification changed the input container.')
                result.update({'pass': True, 'restored_bytes': len(decoded.data),
                               'original_filename': decoded.filename, 'width': size[0], 'height': size[1],
                               'restored_sha256': hashlib.sha256(decoded.data).hexdigest(),
                               'container_sha256': before[2], 'input_unchanged': True})
            except Exception as error:
                result['error_type'] = type(error).__name__
                result['error'] = str(error)
            results.append(result)
    passed = sum(result['pass'] for result in results)
    return {'synthetic_only': True, 'input_directory': str(inputs),
            'desktop_core': str(desktop_path),
            'desktop_core_sha256': hashlib.sha256(desktop_path.read_bytes()).hexdigest(),
            'expected_png_cases': 22, 'verified_png_cases': passed,
            'failed_png_cases': len(results) - passed, 'all_passed': passed == 22,
            'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', nargs='?', type=Path, default=ANDROID_ROOT / 'app/build/jpeg-interop')
    parser.add_argument('--fixtures-dir', type=Path, default=FIXTURES)
    parser.add_argument('--desktop-root', type=Path, default=ANDROID_ROOT.parent)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        report = verify(args.inputs, args.fixtures_dir, args.desktop_root)
    except Exception as error:
        report = {'synthetic_only': True, 'all_passed': False,
                  'error_type': type(error).__name__, 'error': str(error)}
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if report['all_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
