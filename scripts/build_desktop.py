"""Build the portable Windows directory and preserve dependency notices."""

import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def prepare_assets():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    from PIL import Image

    app = QApplication.instance() or QApplication([])
    canvas = QImage(256, 256, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    QSvgRenderer(str(ROOT / "assets" / "app.svg")).render(painter)
    painter.end()
    if not canvas.save(str(ROOT / "assets" / "app.png")):
        raise OSError("Could not render application icon")
    with Image.open(ROOT / "assets" / "app.png") as icon:
        icon.save(ROOT / "assets" / "app.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    app.processEvents()


def collect_notices():
    license_root = (ROOT / "build" / "third_party_licenses").resolve()
    if not license_root.is_relative_to(ROOT):
        raise ValueError("Build path escaped the project")
    license_root.mkdir(parents=True, exist_ok=True)
    for name in ("PySide6-Essentials", "shiboken6", "cryptography", "Pillow", "cffi", "pycparser", "pyinstaller"):
        package = importlib.metadata.distribution(name)
        destination = license_root / name
        destination.mkdir(exist_ok=True)
        (destination / "METADATA.txt").write_text(
            f"Name: {package.metadata['Name']}\nVersion: {package.version}\n"
            f"License-Expression: {package.metadata.get('License-Expression', '')}\n"
            f"License: {package.metadata.get('License', '')}\n",
            encoding="utf-8",
        )
        for file in package.files or ():
            if any(word in str(file).lower() for word in ("license", "copying", "notice")):
                source = Path(package.locate_file(file))
                if source.is_file():
                    shutil.copy2(source, destination / source.name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, license_root / "Python-LICENSE.txt")
    supplement = ROOT / "licenses"
    if supplement.is_dir():
        shutil.copytree(supplement, license_root / "supplemental", dirs_exist_ok=True)


def main():
    if __package__:
        from .package_project import project_version, write_runtime_manifest
    else:
        from package_project import project_version, write_runtime_manifest

    if sys.platform != "win32":
        raise SystemExit("Build the Windows release on Windows.")
    prepare_assets()
    collect_notices()
    release_root = (ROOT / "dist" / "MoyleSteg").resolve()
    if not release_root.is_relative_to(ROOT):
        raise ValueError("Release path escaped the project")
    # Dependency discovery otherwise searches every development tool on PATH.
    # In particular, Poppler's ICU78 DLL has the same name as Windows ICU but
    # different exports; bundling it prevents QtGui from importing at all.
    build_environment = os.environ.copy()
    windows_directory = Path(os.environ.get("WINDIR", r"C:\Windows"))
    build_environment["PATH"] = os.pathsep.join(str(path) for path in (
        Path(sys.executable).parent, Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs", windows_directory / "System32", windows_directory,
    ))
    build_environment.pop("PYTHONPATH", None)
    build_environment.pop("PYTHONHOME", None)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
                    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
                    str(ROOT / "MoyleSteg.spec")], cwd=ROOT, env=build_environment, check=True)
    for name in ("README_DESKTOP.md", "THIRD_PARTY_NOTICES.md", "requirements-lock.txt"):
        shutil.copy2(ROOT / name, release_root / name)
    release_docs = release_root / "docs"
    release_docs.mkdir(exist_ok=True)
    for name in ("RELEASE.md", "SECURITY_FIXES_1.2.md", "RELIABILITY_1.2.1.md", "VERIFICATION_1.2.2.md", "APPEARANCE_1.3.0.md", "RECOVERY_1.4.0.md", "RELIABILITY_1.4.1.md", "GIF_1.5.0.md", "RELIABILITY_1.5.1.md"):
        if (ROOT / "docs" / name).is_file():
            shutil.copy2(ROOT / "docs" / name, release_docs / name)
    (release_root / "RELEASE_VERSION.txt").write_text(project_version(ROOT) + "\n", encoding="utf-8")
    write_runtime_manifest(release_root)
    print(f"Portable application: {release_root / 'MoyleSteg.exe'}")


if __name__ == "__main__":
    main()
