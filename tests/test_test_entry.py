"""Subprocess regressions for the Qt-free core test entry and clear GUI setup."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def isolated_pytest(arguments):
    # Treat every attempted Qt import as a failure, even on a development machine
    # where PySide6 is installed. The child still runs real in-place core tests.
    script = """
import builtins, sys
original_import = builtins.__import__
def no_qt(name, *args, **kwargs):
    if name == 'PySide6' or name.startswith('PySide6.') or name == 'pytestqt' or name.startswith('pytestqt.'):
        raise AssertionError('Unexpected Qt dependency import: ' + name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = no_qt
import pytest
code = pytest.main(sys.argv[1:])
assert not any(name == 'PySide6' or name.startswith('PySide6.') for name in sys.modules)
sys.exit(code)
"""
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    return subprocess.run([sys.executable, '-c', script, *arguments], cwd=ROOT,
                          env=env, text=True, capture_output=True, timeout=60)


def test_individual_core_tests_run_without_qt_or_pytestqt():
    result = isolated_pytest([
        'tests/test_png_steg_aes256.py::test_generated_key_file_roundtrips_256_bit_key',
        'tests/test_png_steg_aes256.py::test_standalone_aes256_file_encrypt_and_decrypt', '-q',
    ])
    assert result.returncode == 0, result.stdout + result.stderr
    assert '2 passed' in result.stdout
    assert 'Unknown config option' not in result.stdout + result.stderr


def test_gui_selection_without_plugin_has_actionable_setup_error():
    result = isolated_pytest(['tests/test_theme.py', '--collect-only', '-q'])
    assert result.returncode == 4, result.stdout + result.stderr
    assert 'requirements-test.txt' in result.stdout + result.stderr
    assert 'Unexpected Qt dependency import' not in result.stdout + result.stderr


def test_core_collection_never_imports_gui_modules():
    result = isolated_pytest(['--core', '--collect-only', '-q'])
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'test_png_steg_aes256.py::' in result.stdout
    assert 'test_service.py::' in result.stdout
    assert 'test_theme.py::' not in result.stdout
    assert 'test_window.py::' not in result.stdout


def test_core_mode_rejects_explicit_gui_selection():
    result = isolated_pytest(['--core', 'tests/test_theme.py', '-q'])
    assert result.returncode == 4, result.stdout + result.stderr
    assert '--core excludes GUI modules' in result.stdout + result.stderr


def test_runner_preserves_real_pytest_failure_and_success(tmp_path, monkeypatch):
    from scripts import run_tests
    import shutil

    # Real pytest processes, isolated synthetic data, no pip or Qt needed.
    (tmp_path / 'tests').mkdir()
    shutil.copyfile(ROOT / 'tests' / 'conftest.py', tmp_path / 'tests' / 'conftest.py')
    (tmp_path / 'tests' / 'test_probe.py').write_text(
        "import sys\ndef test_pass():\n    assert not any(n.startswith(('PySide6', 'pytestqt')) for n in sys.modules)\n"
        "def test_fail():\n    assert False, 'intentional test-runner exit-code probe'\n", encoding='utf-8')
    monkeypatch.setattr(run_tests, 'ROOT', tmp_path)
    monkeypatch.setattr(run_tests, 'PYTHON', Path(sys.executable))
    monkeypatch.setattr(sys, 'prefix', str(tmp_path / '.venv'))
    assert run_tests.main(['core', '--', 'tests/test_probe.py::test_pass', '-q']) == 0
    assert run_tests.main(['core', '--', 'tests/test_probe.py::test_fail', '-q']) == 1
    assert run_tests.main(['core', '--', 'tests/test_probe.py', '-k', 'absent', '-q']) == 5


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows batch entry')
def test_batch_entry_parses_with_native_cmd_and_rejects_invalid_mode():
    result = subprocess.run(
        [str(Path(os.environ['SystemRoot']) / 'System32' / 'cmd.exe'), '/d', '/c',
         '运行测试.bat invalid --no-pause'], cwd=ROOT, capture_output=True, timeout=15)
    output = (result.stdout + result.stderr).decode('utf-8', errors='replace')
    assert result.returncode == 2, output
    assert 'Usage:' in output
    assert 'is not recognized' not in output
