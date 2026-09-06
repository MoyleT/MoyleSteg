#!/usr/bin/env python3
"""Recover fresh Kotlin GIF outputs with the bundled desktop 1.5.0 reference.

Uses only synthetic test files, writes no recovered plaintext, and compares every
displayed animation frame with Pillow. Requires Pillow and cryptography.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def load_reference(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frames(path):
    result = []
    with Image.open(path) as image:
        loop = image.info.get('loop')
        for index in range(image.n_frames):
            image.seek(index)
            result.append({
                'size': image.size,
                'duration_ms': image.info.get('duration', 0),
                'disposal': getattr(image, 'disposal_method', 0),
                'rgba_sha256': hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest(),
            })
    return loop, result


def verify(outputs):
    load_reference('gif_carrier', ROOT / 'tools/reference/gif_carrier.py')
    desktop = load_reference('moyle_gif_desktop_reference', ROOT / 'tools/reference/desktop_1_5_0.py')
    source = (outputs / 'source.bin').read_bytes()
    cover_path = outputs / 'animated-cover.gif'
    cover = cover_path.read_bytes()
    assert cover[:6] in (b'GIF87a', b'GIF89a') and cover[-1:] == b';'
    expected_prefix = b'GIF89a' + cover[6:-1]
    expected_loop, expected_frames = frames(cover_path)
    results = []
    for mode in ('key', 'password'):
        path = outputs / f'gif-{mode}.gif'
        container = path.read_bytes()
        credential = (desktop.Credential.from_key_file(outputs / 'synthetic.stegkey')
                      if mode == 'key' else desktop.Credential.from_password('synthetic-gif-password'))
        decoded = desktop.decode_image(path, credential=credential)
        assert decoded.filename == 'synthetic-gif.bin' and decoded.data == source, mode
        assert container[:len(expected_prefix)] == expected_prefix, 'Original animation blocks changed'
        loop, actual_frames = frames(path)
        assert loop == expected_loop and actual_frames == expected_frames, 'Decoded animation changed'
        results.append({
            'file': path.name, 'mode': mode, 'pass': True,
            'restored_bytes': len(source), 'frames': len(actual_frames), 'loop': loop,
            'original_animation_bytes_preserved': True,
            'pillow_all_frames_rgba_timing_disposal_equal': True,
            'restored_sha256': hashlib.sha256(decoded.data).hexdigest(),
            'container_sha256': hashlib.sha256(container).hexdigest(),
        })
    return {'direction': 'Kotlin-to-Python', 'desktop_reference': '1.5.0',
            'synthetic_only': True, 'kotlin_to_python_gif_cases': len(results),
            'all_passed': True, 'results': results}


if __name__ == '__main__':
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'core/build/gif-output'
    print(json.dumps(verify(output), ensure_ascii=False, indent=2))
