#!/usr/bin/env python3
"""Generate public JPEG-to-PNG interop fixtures with the desktop's public API.

Pillow and cryptography are required. No private images or credentials are used.
Ciphertext bytes change between runs because normal random salts/nonces are kept.
"""
import argparse
import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
from PIL import Image, ImageDraw


ANDROID_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ANDROID_ROOT / 'core/src/test/resources/jpeg/interop'
CASES = ('normal', 'progressive', 'grayscale') + tuple(f'exif-{i}' for i in range(1, 9))
COLUMNS = ('name', 'width', 'height', 'key_png', 'password_png')
SOURCE_NAME = 'jpeg-互通.bin'
SOURCE_BYTES = bytes(range(256)) * 2
PUBLIC_KEY = bytes(range(32))
PUBLIC_PASSWORD = 'Synthetic JPEG interop 2026!'


def load_desktop(desktop_root=None):
    desktop_root = Path(desktop_root) if desktop_root else ANDROID_ROOT.parent
    current = desktop_root / 'png_steg_aes256.py'
    path = current if current.is_file() else ANDROID_ROOT / 'tools/reference/desktop_1_5_0.py'
    if not path.is_file():
        raise FileNotFoundError('Neither the current desktop core nor bundled 1.5.0 reference exists.')
    # Both supported cores import their adjacent gif_carrier module when needed.
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('moyle_jpeg_desktop_reference', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module, path


def expected_size(name):
    return (96, 144) if name in ('exif-5', 'exif-6', 'exif-7', 'exif-8') else (144, 96)


def carrier_filename(name):
    return name + ('.jpeg' if name in ('progressive', 'grayscale') else '.jpg')


def make_carrier(directory, name):
    """Recreate the same small asymmetric images used by the desktop GUI checks."""
    image = Image.new('RGB', (144, 96), '#476583')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 49, 31), fill='#ee2211')
    draw.rectangle((90, 0, 143, 45), fill='#22cc44')
    draw.rectangle((0, 70, 70, 95), fill='#1144dd')
    draw.polygon(((97, 61), (132, 80), (118, 94)), fill='#eedd33')
    if name == 'grayscale':
        gray = image.convert('L')
        image.close()
        image = gray
    options = {'format': 'JPEG', 'quality': 93, 'progressive': name == 'progressive'}
    if name.startswith('exif-'):
        exif = Image.Exif()
        exif[274] = int(name.split('-')[1])
        options['exif'] = exif
    path = directory / carrier_filename(name)
    image.save(path, **options)
    image.close()
    return path


def file_snapshot(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()


def generate(output, desktop_root=None, jpeg_dir=None):
    desktop, desktop_path = load_desktop(desktop_root)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'source.bin').write_bytes(SOURCE_BYTES)
    (output / 'password.txt').write_text(PUBLIC_PASSWORD, encoding='utf-8')
    key_path = output / 'synthetic.stegkey'
    key_path.write_bytes((desktop.KEY_FILE_HEADER + '\n' +
                          base64.urlsafe_b64encode(PUBLIC_KEY).decode('ascii') + '\n').encode('ascii'))
    credentials = {
        'key': desktop.Credential.from_key_file(key_path),
        'password': desktop.Credential.from_password(PUBLIC_PASSWORD),
    }
    rows, results = [], []
    # The only temporary directory is newly created inside the explicit output;
    # its source/carriers can be cleaned without touching existing fixture files.
    with tempfile.TemporaryDirectory(prefix='.jpeg-vectors-', dir=output) as temporary:
        work = Path(temporary).resolve()
        assert work.is_relative_to(output)
        source = work / SOURCE_NAME
        source.write_bytes(SOURCE_BYTES)
        source_before = file_snapshot(source)
        for name in CASES:
            carrier = Path(jpeg_dir) / carrier_filename(name) if jpeg_dir else make_carrier(work, name)
            carrier_before = file_snapshot(carrier)
            width, height = expected_size(name)
            for mode, credential in credentials.items():
                destination = output / f'{name}_{mode}.png'
                desktop.hide_file(carrier, source, destination, credential=credential, force=True)
                decoded = desktop.decode_image(destination, credential=credential)
                if decoded.filename != SOURCE_NAME or decoded.data != SOURCE_BYTES:
                    raise RuntimeError('Generated fixture failed authenticated recovery: ' + destination.name)
                with Image.open(destination) as image:
                    if image.format != 'PNG' or image.size != (width, height):
                        raise RuntimeError('Generated fixture has wrong format or orientation: ' + destination.name)
                results.append({'file': destination.name, 'pass': True,
                                'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()})
            if file_snapshot(carrier) != carrier_before or file_snapshot(source) != source_before:
                raise RuntimeError('Desktop generation changed a source input.')
            rows.append((name, width, height, f'{name}_key.png', f'{name}_password.png'))
    text = io.StringIO(newline='')
    writer = csv.writer(text, delimiter='\t', lineterminator='\n')
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    (output / 'cases.tsv').write_text(text.getvalue(), encoding='utf-8')
    core_sha = hashlib.sha256(desktop_path.read_bytes()).hexdigest()
    (output / 'README.md').write_text(
        '# Public synthetic JPEG carrier interoperability vectors\n\n'
        'These are test data, never credentials for private files. Eleven synthetic JPEG '
        'carriers (normal, progressive, grayscale, and EXIF orientations 1 through 8) '
        'were hidden using the desktop public hide_file API in key and password modes. '
        'Every resulting file is PNG, not JPEG.\n\n'
        '* cases.tsv is UTF-8 with a header: name, width, height, key_png, password_png.\n'
        '* width/height are the dimensions after applying EXIF orientation.\n'
        '* source.bin contains bytes(range(256)) repeated twice (512 bytes).\n'
        '* The authenticated original filename is jpeg-互通.bin.\n'
        '* synthetic.stegkey encodes the 32 public bytes 0 through 31.\n'
        '* password.txt contains the public password Synthetic JPEG interop 2026!\n'
        f'* Generator desktop module: {desktop_path.name}; SHA-256: {core_sha}.\n\n'
        'From the Android project, run python tools/generate_jpeg_vectors.py. '
        'An adjacent current desktop checkout is used when available; otherwise the '
        'bundled tools/reference/desktop_1_5_0.py is used. --desktop-root selects a '
        'desktop checkout; --jpeg-dir can reuse the shared synthetic JPEG directory. '
        'The default regenerates the same carrier designs without importing desktop tests.\n\n'
        'Salts and nonces remain random, so regeneration changes ciphertext bytes. '
        'The expected payload, name, dimensions, formats and authentication remain identical.\n',
        encoding='utf-8',
    )
    return {'synthetic_only': True, 'desktop_core': str(desktop_path), 'desktop_core_sha256': core_sha,
            'output_directory': str(output), 'carrier_cases': len(rows), 'png_cases': len(results),
            'all_passed': True, 'results': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop-root', type=Path, default=ANDROID_ROOT.parent)
    parser.add_argument('--output-dir', type=Path, default=FIXTURES)
    parser.add_argument('--jpeg-dir', type=Path, help='Reuse the eleven public synthetic JPEG carriers.')
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir, args.desktop_root, args.jpeg_dir), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
