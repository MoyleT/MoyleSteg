"""Run full or Qt-free tests using only this project's virtual environment."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("full", "core"), nargs="?", default="full")
    parser.add_argument("--install", action="store_true", help="Install matching dependencies into project .venv.")
    arguments = list(sys.argv[1:] if argv is None else argv)
    separator = arguments.index("--") if "--" in arguments else len(arguments)
    options = parser.parse_args(arguments[:separator])
    pytest_args = arguments[separator + 1:]
    if not PYTHON.exists():
        if not options.install:
            parser.error("Project .venv is missing. Run again with --install.")
        code = subprocess.call([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        if code:
            return code
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        return subprocess.call([str(PYTHON), str(Path(__file__).resolve()), *arguments], cwd=ROOT)
    requirement = "requirements-test.txt" if options.mode == "full" else "requirements-dev.txt"
    if options.install:
        code = subprocess.call([str(PYTHON), "-m", "pip", "install", "-r", str(ROOT / requirement)], cwd=ROOT)
        if code:
            return code
    dependencies = ["pytest", "PIL", "cryptography"]
    if options.mode == "full":
        dependencies.extend(["PySide6", "pytestqt"])
    missing = [name for name in dependencies if importlib.util.find_spec(name) is None]
    if missing:
        print(f"Missing {', '.join(missing)}. Install {requirement}: run this command with --install.", file=sys.stderr)
        return 4
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    command = [str(PYTHON), "-m", "pytest"]
    if options.mode == "full":
        env["QT_API"] = "pyside6"
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        command.extend(["-p", "pytestqt.plugin"])
    else:
        command.append("--core")
    command.extend(pytest_args or ["-q"])
    print(f"{options.mode.upper()} tests | Python: {PYTHON}", flush=True)
    if options.mode == "core":
        print("GUI tests are excluded. This is not a full desktop validation.", flush=True)
    return subprocess.call(command, cwd=ROOT, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
