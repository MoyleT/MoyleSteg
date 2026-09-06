"""Keep synthetic test data inside the project, isolated across parallel sessions."""

import ast
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def desktop_application_style(request):
    """Exercise the same Qt style selected by the actual desktop entry point."""
    if {"qtbot", "qapp"}.intersection(request.fixturenames):
        qapp = request.getfixturevalue("qapp")
        if qapp.style().objectName().lower() != "fusion":
            qapp.setStyle("Fusion")


@lru_cache(maxsize=None)
def _uses_qt(path):
    """Inspect dependencies without importing test modules or Qt."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(n.name.split(".")[0] in {"PySide6", "pytestqt"} for n in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in {"PySide6", "pytestqt"}:
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(arg.arg in {"qapp", "qtbot"} for arg in node.args.args + node.args.kwonlyargs):
                return True
    return False


def pytest_addoption(parser):
    parser.addoption("--core", action="store_true", help="Run Qt-free core, service and tooling tests only.")


def pytest_ignore_collect(collection_path, config):
    if config.getoption("--core") and collection_path.name.startswith("test_") and collection_path.suffix == ".py":
        return _uses_qt(str(collection_path))


def pytest_report_header(config):
    if config.getoption("--core"):
        return "CORE mode: GUI tests excluded; this is not a full desktop validation."


def pytest_configure(config):
    selected_gui = []
    for argument in config.args:
        path = Path(argument.split("::", 1)[0])
        candidates = path.rglob("test_*.py") if path.is_dir() else [path]
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix == ".py" and _uses_qt(str(candidate)):
                if config.getoption("--core") and path.is_dir():
                    continue
                selected_gui.append(candidate)
    if selected_gui and config.getoption("--core"):
        raise pytest.UsageError("--core excludes GUI modules; remove the explicit GUI test path or use full mode.")
    if selected_gui and not config.pluginmanager.hasplugin("pytestqt.plugin") and not config.pluginmanager.hasplugin("pytest-qt"):
        raise pytest.UsageError("GUI tests require pytest-qt and PySide6. Install requirements-test.txt in .venv, then use scripts/run_tests.py full; use --core for Qt-free tests.")
    if not config.option.basetemp:
        run_root = Path(__file__).resolve().parents[1] / "artifacts" / "test-runs"
        run_root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(run_root / uuid4().hex)
