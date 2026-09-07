"""Create an allowlisted public project ZIP from an already verified release.

Identical input bytes produce identical archive bytes in the same Python/zlib
environment. Building a reproducible EXE is a separate concern.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "1e3026a73822e65d236e2f2b158713262f8705b1"
PUBLIC_SCREENSHOTS = (
    "theme-midnight.png", "theme-blossom.png", "theme-terminal.png",
    "completion-summary.png", "compact-large.png",
)
ROOT_FILES = frozenset({
    "main.py", "png_steg_aes256.py", "gif_carrier.py", "moyle_bundle.py", "MoyleSteg.spec", "pytest.ini", ".gitignore",
    "README_DESKTOP.md", "README_AES256_三合一.md", "PROJECT_OVERVIEW.md",
    "THIRD_PARTY_NOTICES.md", "SHA256SUMS.txt", "requirements.txt",
    "requirements-dev.txt", "requirements-gui.txt", "requirements-build.txt", "requirements-test.txt",
    "requirements-lock.txt", "Build-Desktop.ps1", "Setup-Desktop.ps1",
    "启动桌面版.bat", "安装依赖.bat", "运行测试.bat",
})
# These globs are intentionally non-recursive. New data directories and new
# documentation are not published merely because they exist in the checkout.
SOURCE_RULES = {
    "moyle_steg": ("*.py",),
    "tests": ("test_*.py", "conftest.py"),
    "tests/fixtures": ("legacy-v1.png", "legacy-v1.saes", "legacy-posix-name.saes"),
    "tests/fixtures/bundle": ("kotlin-bundle.zip", "kotlin-expected.json"),
    "scripts": ("build_desktop.py", "package_project.py", "run_tests.py", "capture_public_ui.py"),
    "assets": ("app.svg", "app.png", "app.ico", "version_info.txt",
               "strawberry-sticker.png", "cherry-sticker.png",
               "ui-midnight-up.svg", "ui-midnight-down.svg", "ui-midnight-check.svg",
               "ui-blossom-up.svg", "ui-blossom-down.svg", "ui-blossom-check.svg",
               "ui-terminal-up.svg", "ui-terminal-down.svg", "ui-terminal-check.svg"),
    "licenses": ("*.txt",),
    "docs": ("RELEASE.md", "SECURITY_FIXES_1.2.md", "RELIABILITY_1.2.1.md", "VERIFICATION_1.2.2.md", "APPEARANCE_1.3.0.md", "RECOVERY_1.4.0.md", "RELIABILITY_1.4.1.md", "GIF_1.5.0.md", "RELIABILITY_1.5.1.md", "MULTIFILE_1.6.0.md"),
    "docs/screenshots": PUBLIC_SCREENSHOTS,
}
PRIVATE_PARTS = frozenset({
    "artifacts", "private", ".git", ".venv", "venv", "build", "cache", ".cache",
    "__pycache__", ".pytest_cache", ".superpowers", ".codex",
})
REQUIRED_FILES = frozenset({
    "moyle_bundle.py", "docs/MULTIFILE_1.6.0.md", "dist/MoyleSteg/docs/MULTIFILE_1.6.0.md",
    "tests/fixtures/bundle/kotlin-bundle.zip", "tests/fixtures/bundle/kotlin-expected.json",
    "main.py", "png_steg_aes256.py", "gif_carrier.py", "moyle_steg/__init__.py", "README_DESKTOP.md",
    "SHA256SUMS.txt", "docs/RELEASE.md", "docs/SECURITY_FIXES_1.2.md",
    "docs/RELIABILITY_1.2.1.md", "docs/VERIFICATION_1.2.2.md", "docs/APPEARANCE_1.3.0.md",
    "docs/RECOVERY_1.4.0.md", "dist/MoyleSteg/docs/RECOVERY_1.4.0.md",
    "docs/RELIABILITY_1.4.1.md", "dist/MoyleSteg/docs/RELIABILITY_1.4.1.md",
    "docs/GIF_1.5.0.md", "dist/MoyleSteg/docs/GIF_1.5.0.md",
    "assets/strawberry-sticker.png", "assets/cherry-sticker.png",
    "dist/MoyleSteg/docs/VERIFICATION_1.2.2.md", "dist/MoyleSteg/docs/APPEARANCE_1.3.0.md",
    "dist/MoyleSteg/MoyleSteg.exe", "dist/MoyleSteg/RELEASE_VERSION.txt",
    "dist/MoyleSteg/_internal/base_library.zip",
    "dist/MoyleSteg/_internal/assets/strawberry-sticker.png",
    "dist/MoyleSteg/_internal/assets/cherry-sticker.png",
    "dist/MoyleSteg/RUNTIME_MANIFEST.json",
})
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)

# Public screenshots are source documentation, never diagnostic/runtime output.
REQUIRED_FILES |= frozenset(f"docs/screenshots/{name}" for name in PUBLIC_SCREENSHOTS)


def project_version(root: Path) -> str:
    """Read the version without importing application or Qt code."""
    tree = ast.parse((root / "moyle_steg/__init__.py").read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets
        ):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
                return version
    raise ValueError("The project must declare a numeric release version")


def _is_link(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _safe_file(root, path):
    relative = path.relative_to(root)
    if any(part.casefold() in PRIVATE_PARTS for part in relative.parts):
        return False
    if path.suffix.lower() in {".stegkey", ".saes"} and relative.as_posix() not in {
        "tests/fixtures/legacy-v1.saes", "tests/fixtures/legacy-posix-name.saes"
    }:
        return False
    if (path.suffix.lower() == ".zip" and relative.parts[:3] != ("dist", "MoyleSteg", "_internal")
            and relative.as_posix() != "tests/fixtures/bundle/kotlin-bundle.zip"):
        return False
    for parent in (path, *path.parents):
        if parent == root:
            break
        if _is_link(parent):
            raise ValueError("Release inputs must not contain symbolic links or junctions")
    if not path.resolve().is_relative_to(root):
        raise ValueError("A release input escaped the project directory")
    return path.is_file()


def _digest_file(path):
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def write_runtime_manifest(runtime):
    """Called immediately after a clean build, before running local diagnostics."""
    records = []
    for path in sorted(runtime.rglob('*')):
        if path.is_file() and path.name != 'RUNTIME_MANIFEST.json':
            size, digest = _digest_file(path)
            records.append({'path': path.relative_to(runtime).as_posix(), 'size': size, 'sha256': digest})
    (runtime / 'RUNTIME_MANIFEST.json').write_text(
        json.dumps({'format': 1, 'files': records}, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def _runtime_files(root, runtime):
    manifest_path = runtime / 'RUNTIME_MANIFEST.json'
    if not manifest_path.is_file():
        raise ValueError('The portable runtime needs a clean-build manifest; rebuild it first')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('format') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('The portable runtime manifest is invalid')
    expected = {'RUNTIME_MANIFEST.json': None}
    for entry in manifest['files']:
        name = entry['path']
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or name in expected:
            raise ValueError('The portable runtime manifest contains unsafe paths')
        expected[name] = entry
    actual = {}
    for directory, folders, names in os.walk(runtime, followlinks=False):
        if any(_is_link(Path(directory) / folder) for folder in folders):
            raise ValueError('The portable runtime contains a linked directory')
        for name in names:
            path = Path(directory) / name
            actual[path.relative_to(runtime).as_posix()] = path
    if set(actual) != set(expected):
        raise ValueError('The portable runtime has extra or missing files; keep diagnostics outside it and rebuild')
    for name, path in actual.items():
        if not _safe_file(root, path):
            raise ValueError('The portable runtime contains a private or unsafe file')
        if name.startswith('docs/') and name.removeprefix('docs/') not in SOURCE_RULES['docs']:
            raise ValueError('The portable runtime contains local investigation documents')
        entry = expected[name]
        if entry is not None and _digest_file(path) != (entry['size'], entry['sha256']):
            raise ValueError('The portable runtime was changed after building; rebuild it first')
    return actual.values()


def _collect_files(root):
    selected = set()
    for name in ROOT_FILES:
        path = root / name
        if _safe_file(root, path):
            selected.add(path)
    for folder, patterns in SOURCE_RULES.items():
        directory = root / folder
        if _is_link(directory):
            raise ValueError("Release source directories must not be links")
        for pattern in patterns:
            for path in directory.glob(pattern):
                if _safe_file(root, path):
                    selected.add(path)
    runtime = root / "dist/MoyleSteg"
    if _is_link(runtime) or _is_link(runtime.parent):
        raise ValueError("The portable runtime directory must not be a link")
    # Preserve exactly the clean build's members, including base_library.zip.
    # A diagnostic saved anywhere in the runtime must never silently become public.
    selected.update(_runtime_files(root, runtime))
    relative_names = {path.relative_to(root).as_posix() for path in selected}
    if not REQUIRED_FILES <= relative_names:
        raise ValueError("The public project or verified portable runtime is incomplete")
    if len({name.casefold() for name in relative_names}) != len(relative_names):
        raise ValueError("Release paths collide on Windows")
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def _zip_info(name):
    info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    info._compresslevel = 9
    return info


def create_public_archive(root: Path, output: Path, *, force: bool = False) -> dict:
    root, output = Path(root).resolve(), Path(output).absolute()
    if _is_link(output):
        raise ValueError("The archive output must not be a link")
    output = output.resolve(strict=False)
    if not output.is_relative_to(root):
        raise ValueError("Write the public archive inside the project directory")
    if output.suffix.lower() != ".zip" or output.is_relative_to(root / "dist/MoyleSteg"):
        raise ValueError("Choose a ZIP destination outside the portable runtime directory")
    if output.exists():
        if not output.is_file():
            raise ValueError("The archive destination must be a file")
        if not force:
            raise FileExistsError("The public archive already exists")
    version = project_version(root)
    runtime_version = (root / "dist/MoyleSteg/RELEASE_VERSION.txt").read_text(encoding="utf-8-sig").strip()
    if runtime_version != version:
        raise ValueError("The portable runtime version does not match the source release")
    files = _collect_files(root)
    runtime_manifest_path = root / 'dist/MoyleSteg/RUNTIME_MANIFEST.json'
    runtime_manifest_bytes = runtime_manifest_path.read_bytes()
    runtime_expected = {'dist/MoyleSteg/' + entry['path']: (entry['size'], entry['sha256'])
                        for entry in json.loads(runtime_manifest_bytes)['files']}
    runtime_expected['dist/MoyleSteg/RUNTIME_MANIFEST.json'] = (
        len(runtime_manifest_bytes), hashlib.sha256(runtime_manifest_bytes).hexdigest())
    archive_root = f"MoyleSteg-{version}"
    manifest = {
        "manifest_format": 1, "project": "Moyle Steganography Studio", "version": version,
        "archive_root": archive_root,
        "baseline": {"git_commit": BASELINE_COMMIT, "checksums": "SHA256SUMS.txt",
                     "scope": "Original v1.0 baseline; not current release checksums"},
        "files": [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".public-release-", suffix=".zip", dir=output.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", allowZip64=True) as archive:
            for source in files:
                relative = source.relative_to(root).as_posix()
                digest, size = hashlib.sha256(), 0
                with source.open("rb") as incoming, archive.open(
                    _zip_info(f"{archive_root}/{relative}"), "w", force_zip64=True
                ) as outgoing:
                    while block := incoming.read(1024 * 1024):
                        digest.update(block)
                        size += len(block)
                        outgoing.write(block)
                if relative in runtime_expected and (size, digest.hexdigest()) != runtime_expected[relative]:
                    raise ValueError('The portable runtime changed while packaging; no archive was published')
                manifest["files"].append({"path": relative, "size": size, "sha256": digest.hexdigest()})
            content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            archive.writestr(_zip_info(f"{archive_root}/RELEASE_MANIFEST.json"), content.encode("utf-8"))
        verify_public_archive(temporary)
        if force:
            os.replace(temporary, output)
        else:
            # Exclusive creation also prevents overwriting a destination that
            # appeared while the archive was being prepared.
            with output.open("xb") as target:
                try:
                    with temporary.open("rb") as source:
                        shutil.copyfileobj(source, target, 1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                except Exception:
                    target.close()
                    output.unlink()
                    raise
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def verify_public_archive(path: Path) -> dict:
    """Verify exact member coverage and SHA-256 without extracting files."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        candidates = [name for name in names if name.endswith("/RELEASE_MANIFEST.json")]
        if len(candidates) != 1 or len(names) != len(set(names)):
            raise ValueError("The archive manifest or member names are invalid")
        manifest = json.loads(archive.read(candidates[0]))
        prefix = f"MoyleSteg-{manifest['version']}/"
        if manifest.get("manifest_format") != 1 or manifest.get("archive_root") != prefix[:-1]:
            raise ValueError("The archive manifest format is invalid")
        expected = {prefix + "RELEASE_MANIFEST.json"}
        for entry in manifest["files"]:
            relative = PurePosixPath(entry["path"])
            if relative.is_absolute() or ".." in relative.parts or "\\" in entry["path"] or ":" in entry["path"]:
                raise ValueError("The archive manifest contains an unsafe path")
            name = prefix + relative.as_posix()
            if name in expected:
                raise ValueError("The archive manifest contains duplicate paths")
            expected.add(name)
            digest, size = hashlib.sha256(), 0
            with archive.open(name) as member:
                while block := member.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
            if digest.hexdigest() != entry["sha256"] or size != entry["size"]:
                raise ValueError("The archive checksum or size does not match its manifest")
        if expected != set(names):
            raise ValueError("The archive contains unmanifested members")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Package an allowlisted public project release; no uploads.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true", help="Replace the explicitly selected archive")
    arguments = parser.parse_args(argv)
    result = create_public_archive(ROOT, arguments.output, force=arguments.force)
    print(f"Public release {result['version']}: {len(result['files'])} verified files")


if __name__ == "__main__":
    main()
