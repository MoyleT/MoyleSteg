#!/usr/bin/env python3
"""Verify fresh Kotlin multi-file envelopes with the bundled desktop reference.

Run ``:core:bundleEnvelopeRegression`` first. This standalone source-package tool
needs Python, Pillow and cryptography, but no Windows project checkout. It checks
PNG/GIF/SAES in password and key modes, the complete original ZIP, and all five
synthetic members with Python's standard ZIP reader. It writes no recovered files.
The bundled pre-multifile desktop 1.5.0 reference demonstrates full-ZIP fallback;
current managed-bundle parser tests are separate from this compatibility check.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_reference(name: str, path: Path):
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def verify(outputs: Path) -> dict:
    reference = ROOT / "tools/reference/desktop_1_5_0.py"
    gif_reference = ROOT / "tools/reference/gif_carrier.py"
    load_reference("gif_carrier", gif_reference)
    desktop = load_reference("moyle_bundle_desktop_reference", reference)
    fixtures = ROOT / "core/src/test/resources/bundle"
    expected = json.loads((fixtures / "python-expected.json").read_text(encoding="utf-8"))
    expected_zip = fixtures / "python-bundle.zip"
    assert file_sha256(expected_zip) == expected["sha256"], "Synthetic ZIP fixture changed"
    expected_paths = [f"{entry['index']:04d}/{entry['name']}" for entry in expected["entries"]]
    assert len(expected_paths) == 5
    rows = []
    for mode in ("key", "password"):
        credential = (desktop.Credential.from_key_bytes(bytes(range(32))) if mode == "key"
                      else desktop.Credential.from_password("synthetic-bundle-password"))
        for format in ("png", "gif", "saes"):
            path = outputs / f"kotlin-{mode}.{format}"
            limits = dict(max_file_bytes=4 * 1024 * 1024, max_container_bytes=8 * 1024 * 1024)
            decoded = (desktop.decode_encrypted_file(path, credential=credential, **limits) if format == "saes"
                       else desktop.decode_image(path, credential=credential, max_pixels=1_000_000, **limits))
            assert decoded.filename == "MoyleSteg-files.zip", f"Wrong original filename: {path.name}"
            assert len(decoded.data) == expected_zip.stat().st_size, f"ZIP length mismatch: {path.name}"
            assert hashlib.sha256(decoded.data).hexdigest() == expected["sha256"], f"ZIP hash mismatch: {path.name}"
            with zipfile.ZipFile(io.BytesIO(decoded.data)) as archive:
                assert archive.comment == b"MOYLESTEG-BUNDLE-V1"
                assert archive.namelist() == expected_paths
                for index, entry in enumerate(expected["entries"]):
                    metadata = archive.getinfo(expected_paths[index])
                    assert metadata.file_size == entry["size"]
                    member = archive.read(metadata)  # zipfile also verifies the entry CRC32.
                    assert len(member) == entry["size"]
                    assert hashlib.sha256(member).hexdigest() == entry["sha256"]
            rows.append({"container": path.name, "format": format, "credential": mode,
                         "container_sha256": file_sha256(path), "payload_sha256": expected["sha256"],
                         "original_filename": decoded.filename, "members_checked": 5, "verified": True})
    return {"synthetic_only": True, "direction": "Kotlin-to-Python",
            "consumer": "bundled-desktop-1.5.0-full-ZIP-fallback", "all_passed": True,
            "reference_module_sha256": file_sha256(reference),
            "gif_reference_sha256": file_sha256(gif_reference),
            "cases_passed": len(rows), "member_checks": sum(row["members_checked"] for row in rows),
            "cases": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", nargs="?", type=Path, default=ROOT / "core/build/bundle-envelope-output")
    parser.add_argument("--output", type=Path, help="Optionally save the synthetic verification report as JSON.")
    options = parser.parse_args()
    report = json.dumps(verify(options.outputs), ensure_ascii=False, indent=2) + "\n"
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
