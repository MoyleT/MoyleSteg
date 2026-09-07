"""Public releases must contain runtime files without local investigation data."""

import hashlib
import os
import zipfile
from pathlib import Path

import pytest

from scripts.package_project import create_public_archive, verify_public_archive


PUBLIC_UI_NAMES = ('theme-midnight.png', 'theme-blossom.png', 'theme-terminal.png',
                   'completion-summary.png', 'compact-large.png')


def _project(root: Path) -> Path:
    files = {
        "main.py": b"# synthetic desktop entry point\n",
        ".gitignore": b".venv/\n*.stegkey\n",
        "png_steg_aes256.py": b"# synthetic engine\n",
        "gif_carrier.py": b"# synthetic GIF carrier codec\n",
        "moyle_bundle.py": b"# synthetic multi-file bundle codec\n",
        "moyle_steg/__init__.py": b'__version__ = "1.2.2"\n',
        "README_DESKTOP.md": b"Public desktop instructions\n",
        "requirements-test.txt": b"# synthetic full-suite dependencies\n",
        "scripts/run_tests.py": b"# synthetic supported test entry point\n",
        "scripts/capture_public_ui.py": b"# synthetic public UI capture entry point\n",
        "SHA256SUMS.txt": b"original-v1-baseline-only\n",
        "docs/RELEASE.md": b"Public release instructions\n",
        "docs/SECURITY_FIXES_1.2.md": b"Synthetic public verification summary\n",
        "docs/RELIABILITY_1.2.1.md": b"Synthetic historical 1.2.1 reliability summary\n",
        "docs/VERIFICATION_1.2.2.md": b"Synthetic current verification summary\n",
        "docs/APPEARANCE_1.3.0.md": b"Synthetic current appearance summary\n",
        "docs/RECOVERY_1.4.0.md": b"Synthetic current recovery summary\n",
        "docs/RELIABILITY_1.4.1.md": b"Synthetic current reliability summary\n",
        "docs/GIF_1.5.0.md": b"Synthetic GIF protocol and verification notes\n",
        "docs/MULTIFILE_1.6.0.md": b"Synthetic multi-file protocol and verification notes\n",
        "tests/test_example.py": b"def test_example(): pass\n",
        "tests/fixtures/legacy-v1.png": b"synthetic legacy PNG fixture\n",
        "tests/fixtures/legacy-v1.saes": b"synthetic legacy SAES fixture\n",
        "tests/fixtures/legacy-posix-name.saes": b"synthetic POSIX filename fixture\n",
        "tests/fixtures/bundle/kotlin-bundle.zip": b"synthetic Kotlin bundle fixture\n",
        "tests/fixtures/bundle/kotlin-expected.json": b"{}\n",
        "assets/app.svg": b"<svg xmlns='http://www.w3.org/2000/svg'/>\n",
        "assets/strawberry-sticker.png": b"synthetic-strawberry-sticker\n",
        "assets/cherry-sticker.png": b"synthetic-cherry-sticker\n",
        "dist/MoyleSteg/MoyleSteg.exe": b"MZ-synthetic-runtime-only\n",
        "dist/MoyleSteg/RELEASE_VERSION.txt": b"1.2.2\n",
        "dist/MoyleSteg/docs/RELIABILITY_1.2.1.md": b"Synthetic historical 1.2.1 reliability summary\n",
        "dist/MoyleSteg/docs/VERIFICATION_1.2.2.md": b"Synthetic current verification summary\n",
        "dist/MoyleSteg/docs/APPEARANCE_1.3.0.md": b"Synthetic current appearance summary\n",
        "dist/MoyleSteg/docs/RECOVERY_1.4.0.md": b"Synthetic current recovery summary\n",
        "dist/MoyleSteg/docs/RELIABILITY_1.4.1.md": b"Synthetic current reliability summary\n",
        "dist/MoyleSteg/docs/GIF_1.5.0.md": b"Synthetic GIF protocol and verification notes\n",
        "dist/MoyleSteg/docs/MULTIFILE_1.6.0.md": b"Synthetic multi-file protocol and verification notes\n",
        "dist/MoyleSteg/_internal/base_library.zip": b"PK-synthetic-required-runtime-archive\n",
        "dist/MoyleSteg/_internal/assets/strawberry-sticker.png": b"synthetic-strawberry-sticker\n",
        "dist/MoyleSteg/_internal/assets/cherry-sticker.png": b"synthetic-cherry-sticker\n",
        "dist/MoyleSteg/_internal/PySide6/Qt6Core.dll": b"MZ-synthetic-qt\n",
    }
    files.update((f'docs/screenshots/{name}', b'synthetic public Qt illustration: ' + name.encode())
                 for name in PUBLIC_UI_NAMES)
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    # Synthetic equivalent of the file inventory captured by a clean build.
    import json
    runtime = root / 'dist/MoyleSteg'
    records = [{'path': path.relative_to(runtime).as_posix(), 'size': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted(runtime.rglob('*')) if path.is_file()]
    (runtime / 'RUNTIME_MANIFEST.json').write_text(json.dumps({'format': 1, 'files': records}), encoding='utf-8')
    return root


def test_public_archive_excludes_private_sentinels_but_keeps_nested_runtime_zip(tmp_path):
    root = _project(tmp_path / "project")
    sentinel = b"PRIVATE_RELEASE_SENTINEL_NOT_FOR_PUBLIC_ARCHIVES"
    private_paths = (
        "artifacts/private-report.json", "artifacts/screenshot.png", ".git/config",
        ".venv/token.txt", "private/notes.md", "build/private.exe", ".env",
        "docs/GITHUB_REFERENCES.md", "docs/VALIDATION.md", "old-project.zip",
        "dist/MoyleSteg-1.1.1-Full-Project.zip", "sample.stegkey", "notes.txt",
        "tests/fixtures/private.saes", "tests/fixtures/private.stegkey",
        "moyle_steg/__pycache__/module.pyc", "tests/private/test_secret.py",
        "assets/unapproved-sticker.png",
        "docs/screenshots/private-ui.png", "docs/screenshots/private-report.json",
        "docs/screenshots/nested/theme-midnight.png",
        "tests/fixtures/bundle/private.zip", "tests/fixtures/bundle/private.json",
    )
    for name in private_paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(sentinel)

    output = root / "releases/public.zip"
    manifest = create_public_archive(root, output)
    assert verify_public_archive(output) == manifest
    assert manifest["version"] == "1.2.2"
    assert manifest["baseline"]["git_commit"] == "1e3026a73822e65d236e2f2b158713262f8705b1"
    with zipfile.ZipFile(output) as archive:
        prefix = "MoyleSteg-1.2.2/"
        members = set(archive.namelist())
        assert prefix + "dist/MoyleSteg/_internal/base_library.zip" in members
        assert prefix + "docs/SECURITY_FIXES_1.2.md" in members
        assert prefix + "docs/RELIABILITY_1.2.1.md" in members
        assert prefix + "dist/MoyleSteg/docs/RELIABILITY_1.2.1.md" in members
        assert archive.read(prefix + "docs/VERIFICATION_1.2.2.md") == b"Synthetic current verification summary\n"
        assert archive.read(prefix + "dist/MoyleSteg/docs/VERIFICATION_1.2.2.md") == b"Synthetic current verification summary\n"
        assert archive.read(prefix + "docs/APPEARANCE_1.3.0.md") == b"Synthetic current appearance summary\n"
        assert archive.read(prefix + "dist/MoyleSteg/docs/APPEARANCE_1.3.0.md") == b"Synthetic current appearance summary\n"
        assert archive.read(prefix + "docs/RECOVERY_1.4.0.md") == b"Synthetic current recovery summary\n"
        assert archive.read(prefix + "dist/MoyleSteg/docs/RECOVERY_1.4.0.md") == b"Synthetic current recovery summary\n"
        assert archive.read(prefix + "docs/RELIABILITY_1.4.1.md") == b"Synthetic current reliability summary\n"
        assert archive.read(prefix + "dist/MoyleSteg/docs/RELIABILITY_1.4.1.md") == b"Synthetic current reliability summary\n"
        for fruit in ("strawberry", "cherry"):
            expected = f"synthetic-{fruit}-sticker\n".encode()
            assert archive.read(prefix + f"assets/{fruit}-sticker.png") == expected
            assert archive.read(prefix + f"dist/MoyleSteg/_internal/assets/{fruit}-sticker.png") == expected
        assert prefix + ".gitignore" in members
        assert prefix + "requirements-test.txt" in members
        assert prefix + "scripts/run_tests.py" in members
        assert prefix + "scripts/capture_public_ui.py" in members
        public_ui = {name.removeprefix(prefix + 'docs/screenshots/') for name in members
                     if name.startswith(prefix + 'docs/screenshots/')}
        assert public_ui == set(PUBLIC_UI_NAMES)
        for name in PUBLIC_UI_NAMES:
            assert archive.read(prefix + 'docs/screenshots/' + name) == b'synthetic public Qt illustration: ' + name.encode()
        assert prefix + "tests/test_example.py" in members
        assert prefix + "tests/fixtures/legacy-v1.saes" in members
        assert prefix + "tests/fixtures/legacy-posix-name.saes" in members
        assert prefix + "moyle_bundle.py" in members
        assert prefix + "docs/MULTIFILE_1.6.0.md" in members
        assert prefix + "dist/MoyleSteg/docs/MULTIFILE_1.6.0.md" in members
        assert archive.read(prefix + 'tests/fixtures/bundle/kotlin-bundle.zip') == b'synthetic Kotlin bundle fixture\n'
        assert archive.read(prefix + 'tests/fixtures/bundle/kotlin-expected.json') == b'{}\n'
        for path in private_paths:
            assert prefix + path not in members
        for name in members:
            assert sentinel not in archive.read(name)
        assert len(members) == len(manifest["files"]) + 1
        for entry in manifest["files"]:
            payload = archive.read(prefix + entry["path"])
            assert entry["size"] == len(payload)
            assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
        assert str(root).encode() not in archive.read(prefix + "RELEASE_MANIFEST.json")


@pytest.mark.parametrize('name', PUBLIC_UI_NAMES)
def test_public_archive_requires_each_named_ui_illustration(tmp_path, name):
    root = _project(tmp_path / 'project')
    (root / 'docs/screenshots' / name).unlink()
    with pytest.raises(ValueError, match='incomplete'):
        create_public_archive(root, root / 'releases/public.zip')


def test_archive_is_reproducible_from_same_bytes_and_preserves_existing_outputs(tmp_path):
    root = _project(tmp_path / "project")
    first, second = root / "releases/first.zip", root / "releases/second.zip"
    create_public_archive(root, first)
    for file in root.rglob("*"):
        if file.is_file():
            os.utime(file, (1_700_000_000, 1_700_000_000))
    create_public_archive(root, second)
    assert first.read_bytes() == second.read_bytes()
    prior = first.read_bytes()
    with pytest.raises(FileExistsError):
        create_public_archive(root, first)
    assert first.read_bytes() == prior


def test_packaging_rejects_stale_runtime_and_manifest_detects_modified_payload(tmp_path):
    root = _project(tmp_path / "project")
    version = root / "dist/MoyleSteg/RELEASE_VERSION.txt"
    version.write_text("1.1.1\n", encoding="utf-8")
    output = root / "releases/public.zip"
    with pytest.raises(ValueError, match="runtime version"):
        create_public_archive(root, output)
    assert not output.exists()
    version.write_bytes(b"1.2.2\n")
    create_public_archive(root, output)
    tampered = root / "releases/tampered.zip"
    with zipfile.ZipFile(output) as source, zipfile.ZipFile(tampered, "w") as target:
        for name in source.namelist():
            payload = source.read(name)
            if name.endswith("/main.py"):
                payload += b"# altered after packaging\n"
            target.writestr(name, payload)
    with pytest.raises(ValueError, match="checksum"):
        verify_public_archive(tampered)


def test_packaging_rejects_local_investigation_docs_left_in_portable_runtime(tmp_path):
    root = _project(tmp_path / "project")
    old_report = root / "dist/MoyleSteg/docs/VALIDATION.md"
    old_report.parent.mkdir(parents=True, exist_ok=True)
    old_report.write_text("Synthetic private investigation record", encoding="utf-8")
    output = root / "releases/public.zip"
    with pytest.raises(ValueError, match="runtime"):
        create_public_archive(root, output)
    assert not output.exists()


@pytest.mark.parametrize('relative', ['docs/VERIFICATION_1.2.2.md',
                                     'dist/MoyleSteg/docs/VERIFICATION_1.2.2.md',
                                     'docs/APPEARANCE_1.3.0.md',
                                     'dist/MoyleSteg/docs/APPEARANCE_1.3.0.md',
                                     'docs/RECOVERY_1.4.0.md',
                                     'dist/MoyleSteg/docs/RECOVERY_1.4.0.md'])
def test_packaging_requires_current_verification_doc_in_source_and_runtime(tmp_path, relative):
    from scripts.package_project import write_runtime_manifest
    root = _project(tmp_path / 'project')
    (root / relative).unlink()
    write_runtime_manifest(root / 'dist/MoyleSteg')
    output = root / 'releases/public.zip'
    with pytest.raises(ValueError, match='incomplete'):
        create_public_archive(root, output)
    assert not output.exists()


@pytest.mark.parametrize('relative', [
    'assets/strawberry-sticker.png', 'assets/cherry-sticker.png',
    'dist/MoyleSteg/_internal/assets/strawberry-sticker.png',
    'dist/MoyleSteg/_internal/assets/cherry-sticker.png',
])
def test_packaging_requires_both_stickers_in_source_and_runtime(tmp_path, relative):
    from scripts.package_project import write_runtime_manifest
    root = _project(tmp_path / 'project')
    (root / relative).unlink()
    write_runtime_manifest(root / 'dist/MoyleSteg')
    output = root / 'releases/public.zip'
    with pytest.raises(ValueError, match='incomplete'):
        create_public_archive(root, output)
    assert not output.exists()


def test_packaging_rejects_unapproved_runtime_doc_even_when_inventoried(tmp_path):
    from scripts.package_project import write_runtime_manifest
    root = _project(tmp_path / 'project')
    (root / 'dist/MoyleSteg/docs/VERIFICATION_PRIVATE.md').write_bytes(b'PRIVATE_SYNTHETIC_SENTINEL')
    write_runtime_manifest(root / 'dist/MoyleSteg')
    output = root / 'releases/public.zip'
    with pytest.raises(ValueError, match='local investigation documents'):
        create_public_archive(root, output)
    assert not output.exists()


@pytest.mark.parametrize('relative', ['diagnostics/report.json', 'report.json', '_internal/report.json',
                                     '_internal/PySide6/diagnostic.png', 'artifacts/local-report.json',
                                     '_internal/private.saes', 'old-project.zip'])
def test_rejects_diagnostic_files_anywhere_in_runtime(tmp_path, relative):
    root = _project(tmp_path / 'project')
    path = root / 'dist/MoyleSteg' / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'PRIVATE_SYNTHETIC_METADATA_SENTINEL')
    output = root / 'releases/public.zip'
    with pytest.raises(ValueError, match='runtime'):
        create_public_archive(root, output)
    assert not output.exists()


def test_rejects_overwritten_runtime_member(tmp_path):
    root = _project(tmp_path / 'project')
    (root / 'dist/MoyleSteg/MoyleSteg.exe').write_bytes(b'PRIVATE_SYNTHETIC_METADATA_SENTINEL')
    with pytest.raises(ValueError, match='runtime'):
        create_public_archive(root, root / 'releases/public.zip')


def test_runtime_changed_after_inventory_check_is_not_published(tmp_path, monkeypatch):
    from scripts import package_project
    root = _project(tmp_path / 'project')
    collect = package_project._collect_files
    def change_after_validation(root):
        result = collect(root)
        (root / 'dist/MoyleSteg/MoyleSteg.exe').write_bytes(b'PRIVATE_SYNTHETIC_METADATA_SENTINEL')
        return result
    monkeypatch.setattr(package_project, '_collect_files', change_after_validation)
    output = root / 'releases/public.zip'
    with pytest.raises(ValueError, match='runtime'):
        create_public_archive(root, output)
    assert not output.exists()
