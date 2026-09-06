"""Bilingual controls for actual progress, cancellation, and read-only verification."""
from pathlib import Path
import pytest
from PySide6.QtCore import QSettings
from moyle_steg.window import MainWindow


def create_window(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'v12.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    return window


def test_verify_page_has_no_destination_and_keeps_fields_on_translation(qtbot, tmp_path):
    window = create_window(qtbot, tmp_path)
    window.nav_buttons['verify'].click()
    form = window.forms['verify']
    assert 'output' not in form and 'force' not in form
    form['input'].edit.setText(str(tmp_path / 'encrypted.saes'))
    form['password'].setText('temporary verification credential')
    window.set_language('en_US')
    assert window.page_title.text() == 'Verify an encrypted file'
    assert form['input'].edit.text().endswith('encrypted.saes')
    assert form['password'].text() == 'temporary verification credential'


def test_preflight_invalidates_on_settings_changes(qtbot, tmp_path):
    from PIL import Image
    window = create_window(qtbot, tmp_path)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (100, 100), '#506c58').save(cover)
    source = tmp_path / 'private.txt'
    source.write_bytes(b'preflight data' * 300)
    form = window.forms['hide']
    form['cover'].edit.setText(str(cover))
    form['input'].edit.setText(str(source))
    form['preflight'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window._preflight_result is not None
    assert window._preflight_result.details['fits'] == 'yes'
    form['resize'].setChecked(True)
    assert window._preflight_result is None
    window.set_language('en_US')
    assert 'Check actual capacity' in window.preflight_label.text()


@pytest.mark.parametrize('close_window', [False, True])
def test_cancel_button_and_close_wait_for_worker_finished(qtbot, tmp_path, close_window):
    import os
    window = create_window(qtbot, tmp_path)
    window.show_page('crypt')
    source = tmp_path / 'source.bin'
    source.write_bytes(os.urandom(1024 * 1024))
    output = tmp_path / 'canceled.saes'
    form = window.forms['crypt']
    form['input'].edit.setText(str(source))
    form['output'].edit.setText(str(output))
    form['password'].setText('test UI cancellation')
    form['confirm'].setText('test UI cancellation')
    form['run'].click()
    assert window.busy and window.cancel_button.isVisible()
    if close_window:
        assert not window.close()
    else:
        window.cancel_button.click()
    assert window.busy
    assert window._cancel_requested
    assert not window.cancel_button.isEnabled()
    window.set_language('en_US')
    assert 'Cancelling safely' in window.status_label.text()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    if close_window:
        qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    else:
        assert window.isVisible()
    assert not output.exists()
    assert window.last_result is None
    expected_password = '' if close_window else 'test UI cancellation'
    assert form['password'].text() == expected_password and form['confirm'].text() == expected_password
    assert window.status_label.text() == 'Operation cancelled.'


def test_real_verify_progress_and_two_copyable_checksums(qtbot, tmp_path):
    from hashlib import sha256
    from PySide6.QtWidgets import QApplication
    from moyle_steg.service import execute, OperationRequest
    source = tmp_path / 'payload.txt'
    source.write_bytes(b'original payload evidence' * 100)
    encoded = tmp_path / 'encoded.saes'
    execute(OperationRequest(operation='encrypt', input_path=str(source), output_path=str(encoded),
        password='GUI verification password', password_confirm='GUI verification password'))
    window = create_window(qtbot, tmp_path)
    window.show_page('verify')
    window.set_language('en_US')
    form = window.forms['verify']
    form['input'].edit.setText(str(encoded))
    form['password'].setText('GUI verification password')
    form['run'].click()
    assert window.busy
    observed = []
    window._thread.progress.connect(lambda stage, done, total: observed.append((stage, done, total, window.status_label.text())))
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result.operation == 'verify'
    assert any(total and done is not None and 'Stage' in label for stage, done, total, label in observed)
    assert form['password'].text() == ''
    assert 'Original-file SHA-256' in window.result_text.text()
    assert 'Whole input-file SHA-256' in window.result_text.text()
    assert window.result_text.text().count('SHA-256') == 2
    window.copy_button.click()
    assert QApplication.clipboard().text() == sha256(source.read_bytes()).hexdigest()
    window.copy_input_button.click()
    assert QApplication.clipboard().text() == sha256(encoded.read_bytes()).hexdigest()
    window.set_language('zh_CN')
    assert '完整输入文件 SHA-256 已复制' in window.status_label.text()
    assert '原始文件 SHA-256' in window.result_text.text()


def test_oriented_jpeg_preview_reports_display_dimensions(qtbot, tmp_path):
    from PIL import Image
    window = create_window(qtbot, tmp_path)
    path = tmp_path / 'oriented.jpg'
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (80, 40), '#556e60').save(path, exif=exif)
    window.forms['hide']['cover'].edit.setText(str(path))
    qtbot.waitUntil(lambda: window._dimensions is not None, timeout=5000)
    assert window._dimensions == (40, 80)
    assert not window.preview.pixmap().isNull()
