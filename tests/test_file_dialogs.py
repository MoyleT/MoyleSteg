"""Real save dialogs follow the app language and return a usable file path."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QFileDialog


@pytest.mark.parametrize("language,accept_label", [("zh_CN", "保存"), ("en_US", "Save")])
def test_save_dialog_follows_language_and_returns_path(qtbot, tmp_path, language, accept_label):
    from moyle_steg.window import MainWindow

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    qtbot.addWidget(window)
    window.set_language(language)
    window.show_page("keygen")
    window.show()
    selected = tmp_path / "chosen-key.stegkey"
    observed = {}

    def choose_file():
        dialog = QApplication.activeModalWidget()
        observed["is_dialog"] = isinstance(dialog, QFileDialog)
        if isinstance(dialog, QFileDialog):
            observed["accept"] = dialog.labelText(QFileDialog.DialogLabel.Accept)
            dialog.selectFile(str(selected))
            dialog.accept()

    QTimer.singleShot(0, choose_file)
    field = window.forms["keygen"]["output"]
    field.browse.click()
    assert observed == {"is_dialog": True, "accept": accept_label}
    assert Path(field.edit.text()) == selected
    assert not selected.exists()  # Choosing a destination must never write the key.
