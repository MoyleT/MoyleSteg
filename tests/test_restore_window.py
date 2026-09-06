"""Recover actual original names through the visible desktop workflow."""
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from moyle_steg.service import OperationRequest, execute
from moyle_steg.window import MainWindow


def make_window(qtbot, tmp_path):
    window = MainWindow(QSettings(str(tmp_path / 'ui.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.show()
    return window


@pytest.mark.parametrize('operation', ['extract', 'decrypt'])
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_default_restore_keeps_original_name_and_extension(qtbot, tmp_path, operation, language):
    original = tmp_path / '原始文件 with spaces.tar.gz'
    original.write_bytes(bytes(range(256)) * 3)
    cover = tmp_path / 'cover.png'
    Image.new('RGB', (128, 128), '#56786e').save(cover)
    encrypted = tmp_path / ('unrelated-name.png' if operation == 'extract' else 'unrelated-name.saes')
    password = 'desktop filename regression'
    execute(OperationRequest(operation='hide' if operation == 'extract' else 'encrypt',
        input_path=str(original), cover_path=str(cover), output_path=str(encrypted),
        password=password, password_confirm=password))
    window = make_window(qtbot, tmp_path)
    page = 'extract' if operation == 'extract' else 'crypt'
    window.show_page(page)
    form = window.forms[page]
    if page == 'crypt':
        form['mode'].setCurrentIndex(1)
    assert form['original_name'].isChecked()
    assert form['output'].directory
    form['input'].edit.setText(str(encrypted))
    folder = Path(form['output'].edit.text())
    assert folder.is_absolute() and folder.parent == tmp_path
    assert not folder.name.endswith('.bin')
    window.set_language(language)
    assert form['output'].edit.text() == str(folder)
    form['password'].setText(password)
    form['run'].click()
    qtbot.waitUntil(lambda: not window.busy, timeout=15000)
    assert window.last_result is not None, window.status_label.text()
    restored = folder / original.name
    assert Path(window.last_result.output_path) == restored
    assert restored.read_bytes() == original.read_bytes()
    assert list(folder.iterdir()) == [restored]
    assert form['password'].text() == ''


def test_directory_and_custom_filename_choices_are_kept_separately(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    form = window.forms['extract']
    form['input'].edit.setText(str(tmp_path / 'hidden.png'))
    folder = str(tmp_path / 'chosen folder')
    form['output'].edit.setText(folder)
    form['original_name'].setChecked(False)
    assert not form['output'].directory
    assert form['output'].edit.text() == ''
    filename = str(tmp_path / 'renamed.pdf')
    form['output'].edit.setText(filename)
    form['original_name'].setChecked(True)
    assert form['output'].edit.text() == folder
    window.set_language('en_US')
    form['input'].edit.setText(str(tmp_path / 'another.png'))
    assert form['output'].edit.text() == folder
    assert form['output'].label.text() == 'Save folder'
    form['original_name'].setChecked(False)
    assert form['output'].edit.text() == filename
    assert form['output'].label.text() == 'Output file'


@pytest.mark.parametrize('language,label', [('zh_CN', '选择文件夹'), ('en_US', 'Select folder')])
def test_restore_browse_selects_a_directory(qtbot, tmp_path, language, label):
    window = make_window(qtbot, tmp_path)
    window.set_language(language)
    window.show_page('extract')
    folder = tmp_path / 'selected folder'
    folder.mkdir()
    observed = {}

    def choose_folder():
        dialog = QApplication.activeModalWidget()
        observed['mode'] = dialog.fileMode()
        observed['accept'] = dialog.labelText(QFileDialog.DialogLabel.Accept)
        dialog.setDirectory(str(folder))
        dialog.accept()

    QTimer.singleShot(0, choose_folder)
    field = window.forms['extract']['output']
    field.browse.click()
    assert observed == {'mode': QFileDialog.FileMode.Directory, 'accept': label}
    assert Path(field.edit.text()) == folder
    assert not list(folder.iterdir())
