# Build on Windows using the project's isolated virtual environment.
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'assets'), 'assets'),
           (str(root / 'THIRD_PARTY_NOTICES.md'), '.'),
           (str(root / 'build' / 'third_party_licenses'), 'third_party_licenses')],
    hiddenimports=['moyle_steg.diagnostics'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtOpenGL',
              'tkinter', 'pytest', 'pytestqt', 'unittest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='MoyleSteg', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(root / 'assets' / 'app.ico'),
    version=str(root / 'assets' / 'version_info.txt'),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MoyleSteg')
