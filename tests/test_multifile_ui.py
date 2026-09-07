"""Native Qt selection and retained-session result behavior."""
from PySide6.QtCore import QSettings
from pathlib import Path
import pytest
from moyle_steg.window import MainWindow


def test_hide_input_accepts_multiple_files_and_removal(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    paths = [tmp_path / 'first.txt', tmp_path / 'second.txt']
    for path in paths:
        path.write_text('synthetic')
    field = window.forms['hide']['input']
    field.set_paths([str(path) for path in paths])
    assert field.paths() == tuple(map(str, paths))
    field.list.setCurrentRow(0)
    field.remove_selected()
    assert field.paths() == (str(paths[1]),)


def test_crypt_mode_disables_multi_input_for_decryption(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.forms['crypt']['mode'].setCurrentIndex(1)
    assert not window.forms['crypt']['input'].multiple


def authenticated_window(qtbot, tmp_path):
    from moyle_steg.service import OperationRequest, execute
    first, second = tmp_path / 'first.txt', tmp_path / 'second.txt'
    first.write_bytes(b'first synthetic content')
    second.write_bytes(b'second synthetic content')
    encrypted = tmp_path / 'input.saes'
    execute(OperationRequest('encrypt', input_paths=(str(first), str(second)), output_path=str(encrypted),
                              password='synthetic', password_confirm='synthetic'))
    window = MainWindow(QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    window.show_page('crypt')
    form = window.forms['crypt']
    form['mode'].setCurrentIndex(1)
    form['input'].edit.setText(str(encrypted))
    form['output'].edit.setText(str(tmp_path / 'output'))
    form['password'].setText('synthetic')
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is not None
    assert window.last_result.bundle is not None
    return window


def test_native_restore_select_save_all_then_cleanup_keeps_saved(qtbot, tmp_path):
    window = authenticated_window(qtbot, tmp_path)
    session = window.last_result.bundle
    assert window.forms['crypt']['password'].text() == ''
    assert not (tmp_path / 'output').exists()
    window._select_members(False)
    window._bundle_checks[2].setChecked(True)
    window.bundle_save_selected.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert list(session.saved) == [2]
    assert Path(session.saved[2].path).read_bytes() == b'second synthetic content'
    assert not window._bundle_checks[2].isEnabled()
    window.bundle_save_all.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert len(session.saved) == 2
    window._clear_bundle_result()
    assert session.closed
    assert not session.archive.exists()
    assert all(Path(value.path).is_file() for value in session.saved.values())


def test_save_failure_retries_without_credentials(qtbot, tmp_path, monkeypatch):
    window = authenticated_window(qtbot, tmp_path)
    session = window.last_result.bundle
    implementation = session._publish
    monkeypatch.setattr(session, '_publish', lambda *args: (_ for _ in ()).throw(PermissionError('synthetic')))
    window.bundle_save_all.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result.bundle is session
    assert '权限' in window.status_label.text()
    assert session.archive.is_file()
    assert not session.saved
    monkeypatch.setattr(session, '_publish', implementation)
    window.bundle_save_all.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert len(session.saved) == 2
    assert window.forms['crypt']['password'].text() == ''


def test_saved_member_paths_stay_compact_and_readable_inside_scroll(qtbot, tmp_path):
    from moyle_steg.widgets import ElidedPathLabel
    window = authenticated_window(qtbot, tmp_path)
    window.bundle_save_all.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    window.bundle_save_zip.click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    qtbot.wait(30)
    labels = window.bundle_panel.findChildren(ElidedPathLabel)
    assert len(labels) == 3
    assert window.bundle_member_scroll.verticalScrollBar().maximum() == 0
    assert window.bundle_member_scroll.geometry().bottom() < window.bundle_output.geometry().top()
    for label in labels:
        assert label.height() >= label.fontMetrics().height() + 2
        assert label.toolTip() in label.accessibleName()
        assert label.sizePolicy().hasHeightForWidth() is False
    window.set_text_size('large')
    qtbot.wait(30)
    assert window.bundle_member_scroll.verticalScrollBar().maximum() == 0


def test_rebuilt_member_list_hides_retired_rows_before_deferred_deletion(qtbot, tmp_path):
    window = authenticated_window(qtbot, tmp_path)
    previous = [window.bundle_members.itemAt(index).widget() for index in range(window.bundle_members.count())]
    assert all(row.isVisible() for row in previous)
    window._render_bundle_result()
    assert all(not row.isVisible() for row in previous)


@pytest.mark.parametrize('width,height,text_size', [(1220, 820, 'standard'), (760, 480, 'large')])
def test_hundred_saved_members_with_long_names_and_paths_scroll_without_compression(qtbot, tmp_path, width, height, text_size):
    from moyle_bundle import BundleEntry, BundleInfo
    from moyle_steg.bundles import SavedMember
    from moyle_steg.widgets import ElidedPathLabel
    window = authenticated_window(qtbot, tmp_path)
    session = window.last_result.bundle
    names = ['合成文档测试' * 8 + f'{index}.txt' for index in range(1, 101)]
    entries = tuple(BundleEntry(index, name, 3, '0' * 64) for index, name in enumerate(names, 1))
    session.info = BundleInfo(entries, 300, 1000)
    prefix = str(tmp_path / ('synthetic-output-' * 8))
    session.saved = {entry.index: SavedMember(entry.index, str(Path(prefix) / entry.name), entry.sha256)
                     for entry in entries}
    session.archive_saved = str(Path(prefix) / 'MoyleSteg-files.zip')
    window.resize(width, height)
    window.set_text_size(text_size)
    window._render_result()
    qtbot.wait(40)
    labels = window.bundle_panel.findChildren(ElidedPathLabel)
    assert len(labels) == 101
    assert window.bundle_member_scroll.verticalScrollBar().maximum() > 0
    for index in range(window.bundle_members.count()):
        row = window.bundle_members.itemAt(index).widget()
        assert row.height() >= row.minimumSizeHint().height()
    for label in labels:
        assert label.height() >= label.fontMetrics().height() + 2
        assert label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width()
        assert label.toolTip().startswith(prefix)
    first = window._bundle_checks[1]
    last = window._bundle_checks[100]
    assert first.toolTip() == names[0]
    assert names[0] in first.accessibleName()
    assert last.height() >= last.fontMetrics().height()
    window.bundle_member_scroll.ensureWidgetVisible(last, 0, 2)
    qtbot.wait(20)
    assert window.bundle_member_scroll.viewport().rect().contains(
        last.mapTo(window.bundle_member_scroll.viewport(), last.rect().center()))


def test_changing_container_invalidates_and_cleans_private_session(qtbot, tmp_path):
    window = authenticated_window(qtbot, tmp_path)
    session = window.last_result.bundle
    window.forms['crypt']['input'].edit.setText(str(tmp_path / 'different.saes'))
    assert window.last_result is None
    assert session.closed
    assert not session.archive.exists()


@pytest.mark.parametrize('theme', ['midnight', 'blossom', 'terminal'])
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_themes_languages_preserve_multi_selection_and_actions(qtbot, tmp_path, theme, language):
    window = authenticated_window(qtbot, tmp_path)
    session = window.last_result.bundle
    window._bundle_checks[1].setChecked(False)
    window.set_theme(theme)
    window.set_language(language)
    assert window.last_result.bundle is session
    assert not window._bundle_checks[1].isChecked()
    assert window._bundle_checks[2].isChecked()
    assert window.bundle_save_selected.text() in ('保存选中文件', 'Save selected files')
    window.resize(760, 480)
    window.set_text_size('large')
    qtbot.wait(20)
    window.scroll.ensureWidgetVisible(window.bundle_save_selected, 0, 8)
    assert window.bundle_save_selected.isEnabled()
    assert window.bundle_save_selected.width() > 0
    import os
    if capture := os.environ.get('MOYLE_CAPTURE_MULTIFILE_UI'):
        directory = Path(capture)
        directory.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(directory / f'{theme}-{language}-restore.png'))


def test_source_picker_state_survives_language_and_theme(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    field = window.forms['hide']['input']
    paths = (str(tmp_path / 'one.txt'), str(tmp_path / 'two.txt'))
    field.set_paths(paths)
    window.set_theme('blossom')
    window.set_language('en_US')
    assert field.paths() == paths
    assert field.summary.text().startswith('2 files selected')
