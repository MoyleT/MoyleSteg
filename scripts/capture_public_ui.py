"""Capture five publishable Qt UI illustrations using only fixed demo content.

Run from source after UI validation. These are documentation illustrations,
not encryption or verification evidence. The capture is QWidget.grab(), never
a desktop/screen capture, so other application windows cannot enter the PNGs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if __package__:
    from .package_project import PUBLIC_SCREENSHOTS
else:
    sys.path.insert(0, str(ROOT))
    from scripts.package_project import PUBLIC_SCREENSHOTS


DEMO_ROOT = 'C:/MoyleDemo'
DEMO_PATHS = frozenset({DEMO_ROOT + '/hidden.png', DEMO_ROOT + '/restored',
                        DEMO_ROOT + '/restored/example.txt'})
DEMO_NOTICE = '合成界面演示 · 非验证记录 / Synthetic UI demo · not verification evidence'
SCENES = dict(zip(PUBLIC_SCREENSHOTS, ('midnight', 'blossom', 'terminal', 'completion', 'compact')))


def prepare_scene(window, scene):
    """Populate actual widgets without reading any demo path or running a task."""
    from PySide6.QtCore import QSignalBlocker
    from moyle_steg.service import OperationResult

    if scene not in SCENES.values():
        raise ValueError('Unknown public demonstration scene')
    window.set_language('zh_CN')
    window.set_reduce_motion(True)
    window.set_text_size('large' if scene == 'compact' else 'standard')
    window.set_theme(scene if scene in ('midnight', 'blossom', 'terminal') else 'midnight')
    window.show_page('extract' if scene == 'completion' else 'hide')
    # Explicit sizes are still bounded by the app's normal screen-fit behavior.
    window.resize(900, 550) if scene == 'compact' else window.resize(1220, 820)
    if scene == 'completion':
        form = window.forms['extract']
        for field, value in ((form['input'].edit, DEMO_ROOT + '/hidden.png'),
                             (form['output'].edit, DEMO_ROOT + '/restored')):
            # The fixed paths are examples, not filesystem inputs. Blocking
            # these edits prevents preview/probe/suggestion filesystem work.
            with QSignalBlocker(field):
                field.setText(value)
        window.last_result = OperationResult(
            operation='extract', title='extract_success',
            input_path=DEMO_ROOT + '/hidden.png',
            output_path=DEMO_ROOT + '/restored/example.txt',
            completed_at='2026-01-01T12:00:00+00:00',
            details={'filename': 'example.txt', 'original_size': '1024',
                     'sha256': hashlib.sha256(b'Synthetic public UI demonstration').hexdigest(),
                     'algorithm': 'AES-256-GCM'},
        )
        window._result_page = 'extract'
        window._render_result()
        window.result_summary.setText('演示结果 / Demonstration only\n\n' + window.result_summary.text())
        window.details_toggle.setChecked(False)
    window.status_label.setText(DEMO_NOTICE)


def assert_public_data(window):
    """Fail closed if a future scene accidentally exposes credentials or paths."""
    from PySide6.QtWidgets import QLabel, QLineEdit, QComboBox, QTextBrowser, QWidget

    for form in window.forms.values():
        for name in ('password', 'confirm'):
            if name in form and form[name].text():
                raise ValueError('Public screenshots must not contain credentials')
        if 'key' in form and form['key'].edit.text():
            raise ValueError('Public screenshots must not contain a selected key')
        for field in form.values():
            if hasattr(field, 'edit') and hasattr(field, 'browse'):
                value = field.edit.text().replace('\\', '/')
                if value and value not in DEMO_PATHS:
                    raise ValueError('Public screenshots only permit fixed synthetic paths')
    if window.status_label.text() != DEMO_NOTICE:
        raise ValueError('Public screenshot demonstration notice is missing')
    texts = [window.windowTitle()]
    for control in window.findChildren(QWidget):
        # Also inspect hidden content: opening details must not reveal a private
        # path simply because the current screenshot had that section collapsed.
        if isinstance(control, QTextBrowser):
            texts.append(control.toPlainText())
        elif isinstance(control, QComboBox):
            texts.extend(control.itemText(index) for index in range(control.count()))
        elif isinstance(control, (QLabel, QLineEdit)):
            texts.append(control.text())
    for text in texts:
        for match in re.finditer(r'''[A-Za-z]:[\\/][^\s<>"']+|\\\\[^\s<>"']+''', text):
            if match.group().replace('\\', '/') not in DEMO_PATHS:
                raise ValueError('Public widget content includes a non-demo filesystem path')
    if window.last_result is not None:
        result = window.last_result
        if (result.input_path != DEMO_ROOT + '/hidden.png'
                or result.output_path != DEMO_ROOT + '/restored/example.txt'
                or result.completed_at != '2026-01-01T12:00:00+00:00'
                or '演示结果' not in window.result_summary.text()):
            raise ValueError('Public completion summary must be the fixed demonstration')


def _settle(app, window, scene):
    from PySide6.QtCore import QEventLoop, QPoint, QRect
    from moyle_steg.diagnostics import _measure_ancestor_bounds

    previous = None
    stable = 0
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if scene == 'completion':
            window.scroll.ensureWidgetVisible(window.result_card, 0, 12)
        else:
            window.scroll.verticalScrollBar().setValue(0)
        shape = (window.size().toTuple(), window.scroll.widget().size().toTuple(),
                 window.scroll.verticalScrollBar().value(), window.status_label.geometry().getRect())
        stable = stable + 1 if shape == previous else 0
        previous = shape
        if stable >= 3:
            _measure_ancestor_bounds(app, window)
            notice = QRect(window.status_label.mapTo(window, QPoint()), window.status_label.size())
            if not window.status_label.isVisible() or not window.rect().contains(notice):
                raise AssertionError('Public demonstration label is outside the captured window')
            if scene == 'completion':
                summary = QRect(window.result_summary.mapTo(window.scroll.viewport(), QPoint()),
                                window.result_summary.size())
                if not window.scroll.viewport().rect().contains(summary):
                    raise AssertionError('Public completion summary is clipped by the viewport')
            return
        time.sleep(.01)
    raise TimeoutError('Public screenshot layout did not settle')


def _checked_output(root, force):
    root = Path(root).resolve()
    directory = root / 'docs/screenshots'
    for path in (root / 'docs', directory, *(directory / name for name in PUBLIC_SCREENSHOTS)):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise ValueError('Public screenshot paths cannot be links')
        if not path.resolve(strict=False).is_relative_to(root):
            raise ValueError('Public screenshot output escaped its project')
    if not force and any((directory / name).exists() for name in PUBLIC_SCREENSHOTS):
        raise FileExistsError('Public screenshots already exist; use --force to regenerate those five files')
    return directory


def _write_png(image, path, force):
    from PySide6.QtCore import QBuffer, QIODevice, QSaveFile

    if image.textKeys():
        raise ValueError('Public screenshot unexpectedly contains text metadata')
    if force:
        destination = QSaveFile(str(path))
        if not destination.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError('Cannot prepare public screenshot output')
        if not image.save(destination, 'PNG'):
            destination.cancelWriting()
            raise OSError('Cannot encode public screenshot')
        if not destination.commit():
            raise OSError('Cannot commit public screenshot')
    else:
        buffer = QBuffer()
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, 'PNG'):
            raise OSError('Cannot encode public screenshot')
        with path.open('xb') as output:
            output.write(bytes(buffer.data()))


def generate_public_screenshots(root=ROOT, *, force=False):
    """Write only the five allowlisted documentation PNGs; return safe metrics."""
    directory = _checked_output(root, force)
    from PySide6.QtCore import QEvent, QSettings, QSize
    from PySide6.QtWidgets import QApplication
    from moyle_steg.layout import fit_window_to_screen
    from moyle_steg.window import MainWindow

    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    captures = []
    with tempfile.TemporaryDirectory(prefix='moyle-public-ui-') as private_settings:
        for name, scene in SCENES.items():
            settings = QSettings(str(Path(private_settings) / (scene + '.ini')), QSettings.Format.IniFormat)
            settings.setFallbacksEnabled(False)
            window = MainWindow(settings)
            try:
                prepare_scene(window, scene)
                window.show()
                app.processEvents()
                fit_window_to_screen(window, preferred_size=QSize(900, 550) if scene == 'compact' else QSize(1220, 820))
                _settle(app, window, scene)
                assert_public_data(window)
                image = window.grab().toImage()
                if image.isNull():
                    raise OSError('Public window capture is empty')
                captures.append((name, image))
            finally:
                window.close()
                window.deleteLater()
                app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    # Validate every scene before publishing any image. No screenshots, logs,
    # settings, or reports from the private temporary directory are copied out.
    directory.mkdir(parents=True, exist_ok=True)
    for name, image in captures:
        _write_png(image, directory / name, force)
    return {'synthetic_demo': True, 'verification_performed': False,
            'images': [{'name': name, 'width': image.width(), 'height': image.height(),
                        'demo_label_visible': True} for name, image in captures]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--force', action='store_true', help='Replace only the five named public screenshots')
    arguments = parser.parse_args(argv)
    print(json.dumps(generate_public_screenshots(force=arguments.force), indent=2))


if __name__ == '__main__':
    main()
