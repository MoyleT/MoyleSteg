"""Qt keyboard/accessibility-interface regressions, not assistive-tech certification.

QTest's QWindow key events exercise Qt's focus routing without moving the OS
cursor. Running this module on Windows without QT_QPA_PLATFORM=offscreen adds
native window exposure; it still does not represent a screen-reader session.
Scale probes are isolated offscreen QT_SCALE_FACTOR simulations, not changes
to Windows display settings or proof about any particular physical monitor.
"""

import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from moyle_steg.service import OperationResult
from moyle_steg.window import MainWindow


LANGUAGES = ['zh_CN', 'en_US']
TEXT_SIZES = ['standard', 'large']
ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_INPUT = 'C:/synthetic-keyboard-tests/' + '/'.join(
    ['long-but-synthetic-input-folder-for-wrapping-' + 'x' * 35] * 4
) + '/synthetic-original-name-' + 'z' * 95 + '.png'


def _window(qtbot, tmp_path, language, text_size):
    settings = QSettings(str(tmp_path / 'keyboard.ini'), QSettings.Format.IniFormat)
    settings.setValue('language', language)
    settings.setValue('text_size', text_size)
    settings.setValue('reduce_motion', True)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.resize(760, 480)
    window.show()
    if QApplication.platformName() != 'offscreen':
        qtbot.waitExposed(window)
    qtbot.wait(30)
    assert window.size() == QSize(760, 480)
    return window


def _key(window, key, modifiers=Qt.KeyboardModifier.NoModifier):
    # Route genuine Qt key press/release through QWindow's event path, never
    # call focusNextChild or directly toggle the control under test.
    QTest.keyClick(window.windowHandle(), key, modifiers)
    QApplication.processEvents()


def _assert_focus_visible(window, control):
    assert QApplication.focusWidget() is control, (
        control.objectName(), getattr(QApplication.focusWidget(), 'objectName', lambda: None)())
    assert control.isVisible()
    parent = control.parentWidget()
    while parent is not None:
        # Including the viewport here is intentional: keyboard navigation must
        # itself reveal the entire focused control, without test-side scrolling.
        rect = QRect(control.mapTo(parent, QPoint()), control.size())
        assert parent.rect().contains(rect), (
            'focused control clipped', control.objectName(), rect,
            parent.metaObject().className(), parent.objectName(), parent.rect())
        parent = parent.parentWidget()
    assert window.scroll.horizontalScrollBar().maximum() == 0
    assert window.sidebar_scroll.horizontalScrollBar().maximum() == 0


def _assert_order(window, controls):
    controls[0].setFocus(Qt.FocusReason.TabFocusReason)
    QApplication.processEvents()
    _assert_focus_visible(window, controls[0])
    for control in controls[1:]:
        _key(window, Qt.Key.Key_Tab)
        _assert_focus_visible(window, control)
    for control in reversed(controls[:-1]):
        _key(window, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        _assert_focus_visible(window, control)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('text_size', TEXT_SIZES)
def test_form_tab_and_backtab_order_reveals_controls_without_manual_scroll(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    form = window.forms['hide']
    form['input'].edit.setText('C:/synthetic-keyboard-tests/source.txt')
    form['password'].setText('Synthetic keyboard password')
    form['confirm'].setText('Synthetic keyboard password')
    before = (form['input'].edit.text(), form['password'].text(), form['confirm'].text())
    _assert_order(window, [
        form['cover'].edit, form['cover'].browse,
        form['input'].edit, form['input'].browse, form['input'].list,
        form['input'].remove, form['input'].clear_files, form['preflight'],
        form['credential'], form['password'], form['confirm'], form['show'],
        form['output'].edit, form['output'].browse, form['resize'],
        form['force'], form['run'],
    ])
    assert not form['fill'].isEnabled()  # Disabled controls must not trap Tab.
    assert before == (form['input'].edit.text(), form['password'].text(), form['confirm'].text())


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('text_size', TEXT_SIZES)
def test_navigation_and_appearance_keyboard_order_in_both_directions(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    _assert_order(window, [
        *window.nav_buttons.values(), window.motion_toggle, window.text_size_combo,
        window.theme_combo, window.language_combo, window.scroll,
        window.forms['hide']['cover'].edit,
    ])
    assert window.current_page == 'hide'
    assert window.language == language
    assert window.text_size == text_size


def _accessible_name(widget):
    interface = QAccessible.queryAccessibleInterface(widget)
    assert interface is not None, widget.objectName()
    return interface.text(QAccessible.Text.Name)


def _label_for(window, widget):
    labels = [label for label in window.findChildren(QLabel) if label.buddy() is widget]
    assert len(labels) == 1, (widget.objectName(), len(labels))
    assert labels[0].text().strip()
    return labels[0]


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('text_size', TEXT_SIZES)
def test_translated_accessible_names_and_label_buddies(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    for page, form in window.forms.items():
        window.show_page(page)
        QApplication.processEvents()
        for field, _ in window._file_fields:
            if field.isVisible():
                assert field.label.buddy() is field.edit
                assert _accessible_name(field.edit) == field.label.text()
                assert _accessible_name(field.browse) == window.t('browse') + ' ' + field.label.text()
        for name, key in [('credential', 'credential'), ('password', 'password'), ('confirm', 'confirm')]:
            if name in form:
                assert _label_for(window, form[name]).text() == window.t(key)
                assert _accessible_name(form[name]) == window.t(key)
        if 'budget' in form:
            for label, spin, key in form['budget']._labels:
                assert label.buddy() is spin
                assert label.text() == window.t(key)
                assert _accessible_name(spin) == window.t(key)
    for page, button in window.nav_buttons.items():
        assert _accessible_name(button) == window.t(page)
    assert _accessible_name(window.theme_combo) == window.t('appearance')
    assert _accessible_name(window.text_size_combo) == window.t('text_size')
    assert _accessible_name(window.language_combo) == 'Language / 语言'
    _label_for(window, window.forms['hide']['fill'])
    _label_for(window, window.forms['crypt']['mode'])


def _render_synthetic_result(window):
    """A presentation fixture only; authentication is covered by service tests."""
    window.show_page('verify')
    window.forms['verify']['input'].edit.setText(SYNTHETIC_INPUT)
    window._succeeded(OperationResult(
        operation='verify', title='verify_success', input_path=SYNTHETIC_INPUT,
        completed_at='2026-09-06T12:30:00+08:00',
        details={'verified': 'yes', 'payload_sha256': 'a' * 64,
                 'input_sha256': 'b' * 64, 'original_name': 'synthetic-original.txt'},
    ))
    QApplication.processEvents()


def _assert_content_ancestors(window, control):
    parent = control.parentWidget()
    while parent is not None and parent is not window.scroll.viewport():
        rect = QRect(control.mapTo(parent, QPoint()), control.size())
        assert parent.rect().contains(rect), (control.objectName(), rect, parent.objectName(), parent.rect())
        parent = parent.parentWidget()


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('text_size', TEXT_SIZES)
def test_keyboard_expands_long_path_result_and_reaches_both_digest_actions(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    _render_synthetic_result(window)
    qtbot.wait(20)
    form = window.forms['verify']
    form['run'].setFocus(Qt.FocusReason.TabFocusReason)
    _key(window, Qt.Key.Key_Tab)
    _assert_focus_visible(window, window.details_toggle)
    _key(window, Qt.Key.Key_Space)
    assert window.details_toggle.isChecked()
    assert window.result_text.isVisible()
    qtbot.wait(20)
    _assert_order(window, [window.details_toggle, window.copy_button, window.copy_input_button])
    assert SYNTHETIC_INPUT in window.result_summary.text()
    assert 'a' * 64 in window.result_text.text()
    assert 'b' * 64 in window.result_text.text()
    for control in (window.result_summary, window.result_text, window.details_toggle,
                    window.copy_button, window.copy_input_button):
        _assert_content_ancestors(window, control)
    _key(window, Qt.Key.Key_Space)
    assert not window.details_toggle.isChecked()
    assert not window.result_text.isVisible()
    assert not window.copy_button.isVisible()
    assert form['input'].edit.text() == SYNTHETIC_INPUT
    assert window.size() == QSize(760, 480)


@pytest.mark.parametrize('language', LANGUAGES)
@pytest.mark.parametrize('text_size', TEXT_SIZES)
def test_result_text_layout_wraps_every_long_token_without_losing_characters(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    _render_synthetic_result(window)
    window.details_toggle.setChecked(True)
    qtbot.wait(30)
    for control in (window.result_summary, window.result_text):
        # Measure the actual text document used by the renderer. A label whose
        # rectangle fits can still silently clip a filename or an entire hash.
        document = control.document()
        assert document.toPlainText() == control.text()
        assert document.textWidth() > 0
        assert math.ceil(document.size().height()) <= control.viewport().height()
        block = document.begin()
        wrapped_blocks = 0
        while block.isValid():
            layout = block.layout()
            consumed = 0
            for index in range(layout.lineCount()):
                line = layout.lineAt(index)
                assert line.textStart() == consumed
                consumed += line.textLength()
                assert line.naturalTextWidth() <= document.textWidth(), (
                    control.objectName(), line.naturalTextWidth(), document.textWidth())
            assert consumed == len(block.text()), (control.objectName(), consumed, len(block.text()))
            wrapped_blocks += layout.lineCount() > 1
            block = block.next()
        assert wrapped_blocks > 0, (control.objectName(), 'long tokens did not wrap')
        assert control.horizontalScrollBar().maximum() == 0
        assert control.verticalScrollBar().maximum() == 0
        _assert_content_ancestors(window, control)
    assert SYNTHETIC_INPUT in window.result_summary.text()
    assert all(character * 64 in window.result_text.text() for character in ('a', 'b'))
    assert window.scroll.horizontalScrollBar().maximum() == 0


def _run_scale_probe(output_directory, scale):
    """Child-process entry: write only synthetic screenshots and measured sizes."""
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    settings = QSettings(str(output / 'scale.ini'), QSettings.Format.IniFormat)
    settings.setValue('language', 'en_US')
    settings.setValue('text_size', 'large')
    settings.setValue('reduce_motion', True)
    window = MainWindow(settings)
    window.resize(760, 480)
    window.show()
    QTest.qWait(30)  # Deliver initial exposure/layout before entering the form.
    _render_synthetic_result(window)
    QTest.qWait(20)
    window.forms['verify']['run'].setFocus(Qt.FocusReason.TabFocusReason)
    _key(window, Qt.Key.Key_Tab)
    _key(window, Qt.Key.Key_Space)
    QTest.qWait(20)  # Detail expansion changes the scroll range asynchronously.
    _key(window, Qt.Key.Key_Tab)
    _key(window, Qt.Key.Key_Tab)
    _assert_focus_visible(window, window.copy_input_button)
    for control in (window.result_summary, window.result_text, window.details_toggle,
                    window.copy_button, window.copy_input_button):
        _assert_content_ancestors(window, control)
    image = window.grab().toImage()
    dpr = image.devicePixelRatio()
    assert dpr == pytest.approx(float(scale))
    assert image.width() == round(window.width() * dpr)
    assert image.height() == round(window.height() * dpr)
    physical_controls = {}
    for control in (window.theme_combo, window.language_combo, window.copy_input_button):
        rect = QRect(control.mapTo(window, QPoint()), control.size())
        physical = QRect(round(rect.x() * dpr), round(rect.y() * dpr),
                         round(rect.width() * dpr), round(rect.height() * dpr))
        assert image.rect().contains(physical)
        physical_controls[control.objectName()] = [physical.x(), physical.y(), physical.width(), physical.height()]
    assert image.save(str(output / 'simulated-scale.png'))
    report = {
        'scope': 'Offscreen QT_SCALE_FACTOR simulation; no OS display-setting change or assistive-technology certification',
        'synthetic_result_fixture': True, 'scale_factor': float(scale), 'device_pixel_ratio': dpr,
        'logical_client': [window.width(), window.height()], 'physical_image': [image.width(), image.height()],
        'physical_control_rectangles': physical_controls,
        'focus_visible_without_manual_scroll': True, 'content_ancestor_bounds': True,
        'horizontal_overflow': window.scroll.horizontalScrollBar().maximum(),
    }
    (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    window.close()


@pytest.mark.parametrize('scale', ['1.25', '1.5', '2.0'])
def test_simulated_scale_preserves_logical_layout_and_physical_control_bounds(tmp_path, scale):
    output = tmp_path / ('simulated-scale-' + scale)
    code = "import runpy,sys; m=runpy.run_path(sys.argv[1]); m['_run_scale_probe'](sys.argv[2],sys.argv[3])"
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = 'offscreen'
    env['QT_SCALE_FACTOR'] = scale
    env.pop('QT_SCREEN_SCALE_FACTORS', None)
    completed = subprocess.run(
        [sys.executable, '-c', code, str(Path(__file__).resolve()), str(output), scale],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=35,
    )
    assert completed.returncode == 0, (completed.stdout, completed.stderr)
    report = json.loads((output / 'report.json').read_text(encoding='utf-8'))
    assert report['logical_client'] == [760, 480]
    assert report['device_pixel_ratio'] == float(scale)
    assert report['horizontal_overflow'] == 0
