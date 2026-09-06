#!/usr/bin/env python3
"""Restore synthetic, Kotlin-expanded PNGs using the unchanged desktop 1.4.1 core."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parents[1]
outputs = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'core/build/autoexpand-output'
spec = importlib.util.spec_from_file_location('moyle_autoexpand_reference', root / 'tools/reference/desktop_1_4_1.py')
reference = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference
spec.loader.exec_module(reference)
expected = (outputs / 'expanded-source.bin').read_bytes()
results = []
for mode in ('key', 'password'):
    credential = (reference.Credential.from_key_file(outputs / 'synthetic.stegkey') if mode == 'key'
                  else reference.Credential.from_password('synthetic-autoexpand-password'))
    path = outputs / f'expanded-{mode}.png'
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    decoded = reference.decode_image(path, credential=credential)
    assert decoded.filename == 'synthetic.bin'
    assert decoded.data == expected
    with Image.open(path) as image:
        width, height = image.size
        assert width > 16 and height > 16
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    results.append(dict(mode=mode, width=width, height=height, bytes=len(expected),
                        restored_sha256=hashlib.sha256(decoded.data).hexdigest(), passed=True))
print(json.dumps(dict(expanded_kotlin_to_python_cases=len(results), all_passed=True,
                      results=results), ensure_ascii=False, indent=2))
