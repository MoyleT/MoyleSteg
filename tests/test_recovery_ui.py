"""Recovery state must belong to the selected container and explicit budgets."""
from hashlib import sha256

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from moyle_steg.service import OperationRequest, execute
from moyle_steg.window import MainWindow


def verified_window(qtbot, tmp_path):
    source = tmp_path / 'payload.txt'
    source.write_bytes(b'captured content for UI verification')
    container = tmp_path / 'container-a.saes'
    execute(OperationRequest('encrypt', input_path=str(source), output_path=str(container),
                             password='test credential', password_confirm='test credential'))
    window = MainWindow(QSettings(str(tmp_path / 'ui.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show_page('verify')
    window.show()
    form = window.forms['verify']
    form['input'].edit.setText(str(container))
    form['password'].setText('test credential')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is not None
    return window, container, source


def test_changing_verified_input_invalidates_success_and_copy_actions(qtbot, tmp_path):
    window, container, source = verified_window(qtbot, tmp_path)
    window.forms['verify']['input'].edit.setText(str(tmp_path / 'container-b.saes'))
    assert window.last_result is None
    assert window.result_card.isHidden()
    assert '尚未验证' in window.status_label.text()
    QApplication.clipboard().setText('unchanged')
    window._copy_input_sha()
    assert QApplication.clipboard().text() == 'unchanged'
    window.forms['verify']['input'].edit.setText(str(container))
    assert window.last_result is None, 'Selecting A again must not revive a past success'


def test_completed_summary_identifies_input_time_and_keeps_distinct_digest_actions(qtbot, tmp_path):
    window, container, source = verified_window(qtbot, tmp_path)
    summary = window.result_summary.text()
    assert str(container) in summary
    assert '完成时间' in summary and '本次捕获的数据' in summary
    assert window.last_result.completed_at
    assert window.result_text.isHidden()
    window.details_toggle.click()
    assert not window.result_text.isHidden()
    window.copy_button.click()
    assert QApplication.clipboard().text() == sha256(source.read_bytes()).hexdigest()
    window.copy_input_button.click()
    assert QApplication.clipboard().text() == sha256(container.read_bytes()).hexdigest()
    window.set_language('en_US')
    assert str(container) in window.result_summary.text()
    assert 'Completed' in window.result_summary.text()


def test_preflight_is_before_credentials_and_large_text_keeps_form(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'ui.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    form = window.forms['hide']
    form['password'].setText('not persisted')
    from PySide6.QtCore import QPoint
    assert form['preflight'].mapTo(window.pages['hide'], QPoint()).y() < form['credential'].mapTo(window.pages['hide'], QPoint()).y()
    before = form['password'].font().pixelSize()
    window.set_text_size('large')
    assert form['password'].font().pixelSize() > before
    assert form['password'].text() == 'not persisted'
    assert window.settings.value('text_size') == 'large'


def test_raised_recovery_budget_needs_fresh_confirmation(qtbot, tmp_path):
    window, container, source = verified_window(qtbot, tmp_path)
    form = window.forms['verify']
    panel = form['budget']
    panel.pixels.setValue(panel.pixels.value() + 1)
    form['password'].setText('test credential')
    form['run'].click()
    assert not window.busy
    assert '确认' in window.status_label.text()
    panel.confirm.setChecked(True)
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is not None
    assert not panel.confirm.isChecked()
    window.settings.sync()
    assert not any('budget' in key or 'password' in key for key in window.settings.allKeys())


def test_input_changed_and_restored_during_job_does_not_publish_old_success(qtbot, tmp_path, monkeypatch):
    window, container, source = verified_window(qtbot, tmp_path)
    form = window.forms['verify']
    original_display = form['budget'].display_resources
    displayed = []

    def change_selection(info, path, operation):
        original_display(info, path, operation)
        displayed.append(path)
        form['input'].edit.setText(str(tmp_path / 'different.saes'))
        form['input'].edit.setText(str(container))

    monkeypatch.setattr(form['budget'], 'display_resources', change_selection)
    form['password'].setText('test credential')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert displayed == [str(container)]
    assert window.last_result is None
    assert window.result_card.isHidden()
    assert '尚未验证' in window.status_label.text()
    assert form['password'].text() == ''


def test_lower_pixel_budget_refuses_then_same_unmodified_png_verifies(qtbot, tmp_path):
    from PIL import Image
    source = tmp_path / 'small.txt'
    source.write_bytes(b'stable synthetic content')
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (96, 96), (30, 40, 60)).save(cover)
    container = tmp_path / 'original-stego.png'
    execute(OperationRequest('hide', input_path=str(source), cover_path=str(cover),
                             output_path=str(container), password='test credential',
                             password_confirm='test credential'))
    before = container.read_bytes()
    window = MainWindow(QSettings(str(tmp_path / 'ui.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show_page('verify')
    window.show()
    form = window.forms['verify']
    form['input'].edit.setText(str(container))
    form['budget'].pixels.setValue(1024)
    form['password'].setText('test credential')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is None
    assert '请勿缩放' in window.status_label.text()
    form['budget'].pixels.setValue(96 * 96)
    form['password'].setText('test credential')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result.details['verified'] == 'yes'
    assert window.last_result.details['input_sha256'] == sha256(before).hexdigest()
    assert container.read_bytes() == before


def test_old_worker_resource_snapshot_cannot_replace_new_input_preview(qtbot, tmp_path, monkeypatch):
    window, container, source = verified_window(qtbot, tmp_path)
    replacement = tmp_path / 'container-b.saes'
    replacement.write_bytes(container.read_bytes())
    form = window.forms['verify']
    original_progress = window._progress_changed
    original_display = form['budget'].display_resources
    displayed = []

    def change_at_resource_stage(stage, completed, total):
        original_progress(stage, completed, total)
        if stage == 'resources':
            form['input'].edit.setText(str(replacement))

    def capture_display(info, path, operation):
        displayed.append(path)
        original_display(info, path, operation)

    monkeypatch.setattr(window, '_progress_changed', change_at_resource_stage)
    monkeypatch.setattr(form['budget'], 'display_resources', capture_display)
    form['password'].setText('test credential')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is None
    assert displayed == []
    assert form['budget']._path == str(replacement)
