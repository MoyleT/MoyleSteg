from pathlib import Path
from PySide6.QtCore import QSettings, Qt


def make_window(qtbot, tmp_path):
    from moyle_steg.window import MainWindow
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.show()
    return window


def test_language_switch_preserves_form_and_changes_validation(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    form = window.forms['hide']
    form['input'].edit.setText(str(tmp_path / 'secret.txt'))
    form['password'].setText('keep this secret')
    window.set_language('en_US')
    assert window.language == 'en_US'
    assert form['input'].edit.text().endswith('secret.txt')
    assert form['password'].text() == 'keep this secret'
    qtbot.mouseClick(form['run'], Qt.MouseButton.LeftButton)
    assert 'cover' in window.status_label.text().lower()
    window.set_language('zh_CN')
    assert '载体' in window.status_label.text()
    assert window.settings.value('language') == 'zh_CN'


def test_navigation_and_credentials(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    window.nav_buttons['extract'].click()
    assert window.current_page == 'extract'
    form = window.forms['extract']
    form['credential'].setCurrentIndex(1)
    assert not form['key'].isHidden()
    assert form['password_box'].isHidden()
    window.nav_buttons['crypt'].click()
    assert window.current_page == 'crypt'
    window.forms['crypt']['mode'].setCurrentIndex(1)
    assert window.forms['crypt']['confirm_box'].isHidden()


def test_keygen_async_and_result_retranslation(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    window.set_language('en_US')
    window.show_page('keygen')
    output = tmp_path / 'identity.stegkey'
    window.forms['keygen']['output'].edit.setText(str(output))
    window.forms['keygen']['run'].click()
    assert window.busy
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert output.exists()
    assert window.last_result.output_path == str(output)
    assert 'key' in window.status_label.text().lower()
    window.set_language('zh_CN')
    assert '密钥' in window.status_label.text()
    assert '256-bit random key' not in window.result_text.text()


def test_passwords_preserved_for_retry_after_async_failure(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    source = tmp_path / 'bad.saes'
    source.write_bytes(b'not encrypted')
    window.show_page('crypt')
    form = window.forms['crypt']
    form['mode'].setCurrentIndex(1)
    form['original_name'].setChecked(False)
    form['input'].edit.setText(str(source))
    form['output'].edit.setText(str(tmp_path / 'out.txt'))
    form['password'].setText('example password')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert form['password'].text() == 'example password'
    assert form['run'].isEnabled()
    assert not (tmp_path / 'out.txt').exists()


def test_real_hide_inspect_and_extract_with_responsive_window(qtbot, tmp_path):
    from PIL import Image
    from hashlib import sha256
    window = make_window(qtbot, tmp_path)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (160, 120), '#63927b').save(cover)
    payload = tmp_path / 'secret.txt'
    payload.write_bytes('Private message / 私密文件'.encode('utf-8') * 15)
    hidden = tmp_path / 'hidden.png'
    form = window.forms['hide']
    form['cover'].edit.setText(str(cover))
    form['input'].edit.setText(str(payload))
    form['output'].edit.setText(str(hidden))
    form['password'].setText('our test password')
    form['confirm'].setText('our test password')
    form['run'].click()
    assert window.busy
    assert not form['run'].isEnabled()
    window.set_language('en_US')
    window.show_page('guide')
    assert window.current_page == 'guide'
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert hidden.exists()
    assert form['password'].text() == ''
    assert window.last_result.details['sha256'] == sha256(payload.read_bytes()).hexdigest()
    window.copy_button.click()
    from PySide6.QtWidgets import QApplication
    assert QApplication.clipboard().text() == sha256(payload.read_bytes()).hexdigest()
    window.show_page('extract')
    form = window.forms['extract']
    form['input'].edit.setText(str(hidden))
    form['output'].edit.clear()
    form['password'].setText('our test password')
    form['inspect'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result.operation == 'inspect'
    assert window.last_result.details['filename'] == payload.name
    recovered = tmp_path / 'recovered.txt'
    form['original_name'].setChecked(False)
    form['output'].edit.setText(str(recovered))
    form['password'].setText('our test password')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert recovered.read_bytes() == payload.read_bytes()


def test_explicit_output_survives_input_and_mode_changes(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    form = window.forms['crypt']
    form['input'].edit.setText(str(tmp_path / 'first.txt'))
    assert form['output'].edit.text().endswith('first.txt.saes')
    manual = str(tmp_path / 'chosen.saes')
    form['output'].edit.setText(manual)
    form['input'].edit.setText(str(tmp_path / 'second.txt'))
    form['mode'].setCurrentIndex(1)
    window.set_language('en_US')
    assert form['output'].directory
    assert form['output'].edit.text() != manual
    form['mode'].setCurrentIndex(0)
    assert form['output'].edit.text() == manual


def test_existing_output_protected_and_error_retranslated(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    window.show_page('keygen')
    output = tmp_path / 'existing.stegkey'
    output.write_bytes(b'must remain unchanged')
    form = window.forms['keygen']
    form['output'].edit.setText(str(output))
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert output.read_bytes() == b'must remain unchanged'
    assert window.last_result is None
    chinese = window.status_label.text()
    window.set_language('en_US')
    english = window.status_label.text()
    assert english != chinese
    assert not any('\u4e00' <= character <= '\u9fff' for character in english)
    assert 'exist' in english.lower()


def test_drop_cover_updates_real_preview_and_capacity(qtbot, tmp_path):
    from PIL import Image
    from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    from PySide6.QtWidgets import QApplication
    window = make_window(qtbot, tmp_path)
    image = tmp_path / 'dropped.png'
    Image.new('RGB', (96, 80), '#286e54').save(image)
    field = window.forms['hide']['cover']
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(image))])
    drag = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(field, drag)
    assert drag.isAccepted()
    drop = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(field, drop)
    assert Path(field.edit.text()) == image
    qtbot.waitUntil(lambda: window._dimensions == (96, 80), timeout=5000)
    assert not window.preview.pixmap().isNull()
    assert '2.81 KiB' in window.preview_details.text()


def test_relative_plaintext_output_rejected_and_retranslated(qtbot, tmp_path, monkeypatch):
    from moyle_steg.service import OperationRequest, execute
    monkeypatch.chdir(tmp_path)
    source = tmp_path / 'private.txt'
    source.write_bytes(b'private plaintext must not land in the current directory')
    encrypted = tmp_path / 'private.saes'
    execute(OperationRequest(
        operation='encrypt', input_path=str(source), output_path=str(encrypted),
        password='correct test password', password_confirm='correct test password',
    ))
    window = make_window(qtbot, tmp_path)
    window.show_page('crypt')
    form = window.forms['crypt']
    form['mode'].setCurrentIndex(1)
    form['original_name'].setChecked(False)
    form['input'].edit.setText(str(encrypted))
    form['output'].edit.setText('relative-restored.txt')
    form['password'].setText('correct test password')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert not (tmp_path / 'relative-restored.txt').exists()
    assert window.last_result is None
    assert '绝对路径' in window.status_label.text()
    window.set_language('en_US')
    assert 'absolute' in window.status_label.text().lower()
    assert not any('\u4e00' <= character <= '\u9fff' for character in window.status_label.text())
