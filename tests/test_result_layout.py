"""A visible result must add scrolling, never compress ancestors around inputs."""

import pytest
from PIL import Image
from PySide6.QtCore import QPoint, QRect, QSettings
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton


@pytest.fixture(scope='module')
def authenticated_result(tmp_path_factory):
    from png_steg_aes256 import Credential, hide_file
    from moyle_steg.service import OperationRequest, execute, probe_recovery_resources

    work = tmp_path_factory.mktemp('result-layout')
    cover, source = work / 'cover.png', work / 'source.txt'
    container = work / ('synthetic-provenance-for-result-card-and-wrapped-input-context-' + 'x' * 35 + '.png')
    Image.new('RGB', (96, 96), '#554488').save(cover)
    source.write_text('Synthetic result layout verification.\n' * 10, encoding='utf-8')
    hide_file(cover, source, container, credential=Credential.from_password('layout test password'))
    result = execute(OperationRequest(operation='verify', input_path=str(container), password='layout test password'))
    assert result.details['verified'] == 'yes'
    return container, result, probe_recovery_resources(container)


def _assert_ancestors_contain(control, window):
    if not control.isVisible():
        return
    child = control
    parent = child.parentWidget()
    # Cropping at the scroll viewport is expected; clipping by a form, card,
    # column, or the page stack is a defect even when widget.rect() is intact.
    viewports = (window.scroll.viewport(), window.sidebar_scroll.viewport())
    while parent is not None and parent not in viewports:
        rect = QRect(child.mapTo(parent, QPoint()), child.size())
        assert parent.rect().contains(rect), (
            control.objectName(), child.metaObject().className(), rect,
            parent.metaObject().className(), parent.objectName(), parent.rect())
        child, parent = parent, parent.parentWidget()


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
@pytest.mark.parametrize('text_size', ['standard', 'large'])
@pytest.mark.parametrize('width', [1220, 900])
def test_verified_result_show_hide_does_not_compress_form_ancestors(qtbot, tmp_path, authenticated_result, language, text_size, width):
    from moyle_steg.window import MainWindow
    from moyle_steg.layout import ResponsiveColumns

    container, result, resources = authenticated_result
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('language', language)
    settings.setValue('text_size', text_size)
    settings.setValue('reduce_motion', True)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.resize(width, 820)
    window.show()
    window.show_page('verify')
    window.forms['verify']['input'].edit.setText(str(container))
    window.forms['verify']['budget'].display_resources(resources, str(container), 'verify')
    qtbot.wait(40)

    for state in ('shown', 'expanded', 'hidden', 'shown_again'):
        if state in ('shown', 'shown_again'):
            window._succeeded(result)  # Render a real authenticated service result.
        elif state == 'expanded':
            window.details_toggle.setChecked(True)
        else:
            window.result_card.hide()
        qtbot.wait(30)
        for control in (window.theme_combo, window.language_combo,
                        *window.pages['verify'].findChildren(QLineEdit),
                        *window.pages['verify'].findChildren(QComboBox),
                        *window.pages['verify'].findChildren(QPushButton),
                        *window.pages['verify'].findChildren(QLabel)):
            _assert_ancestors_contain(control, window)
        for columns in window.findChildren(ResponsiveColumns):
            if columns.isVisible():
                assert columns.height() >= columns.heightForWidth(columns.width()), (state, columns.geometry())
        assert window.scroll.horizontalScrollBar().maximum() == 0
