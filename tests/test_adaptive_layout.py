"""Logical screen bounds and form-preserving responsive columns; no display changes."""

import pytest
from PySide6.QtCore import QMargins, QPoint, QRect, QSize
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget


@pytest.mark.parametrize('available', [
    QRect(0, 0, 1280, 680), QRect(0, 0, 1093, 574),
    QRect(0, 0, 2560, 1400), QRect(-1280, -680, 1280, 680),
    QRect(-1536, 32, 1093, 574),
])
def test_client_geometry_accounts_for_frame_and_negative_screen_origins(available):
    from moyle_steg.layout import bounded_client_geometry

    frame = QMargins(8, 31, 8, 8)
    client = bounded_client_geometry(available, QSize(1220, 820), frame, margin=12)
    outer = client.marginsAdded(frame)
    assert available.adjusted(12, 12, -12, -12).contains(outer)
    assert client.width() <= 1220 and client.height() <= 820
    assert abs(outer.center().x() - available.center().x()) <= 1
    assert abs(outer.center().y() - available.center().y()) <= 1
    if available.width() > 2000:
        assert client.size() == QSize(1220, 820)


def test_requested_position_is_clamped_without_assuming_primary_screen_origin():
    from moyle_steg.layout import bounded_client_geometry

    available = QRect(-1400, 80, 1280, 680)
    frame = QMargins(8, 31, 8, 8)
    client = bounded_client_geometry(available, QSize(760, 480), frame,
                                     margin=12, position=QPoint(700, -900))
    assert available.adjusted(12, 12, -12, -12).contains(client.marginsAdded(frame))
    assert client.top() == available.top() + 12 + frame.top()
    assert client.right() == available.right() - 12 - frame.right()


@pytest.mark.parametrize('available', [QRect(0, 0, 1280, 680), QRect(-1093, 40, 1093, 574)])
def test_real_qt_window_frame_fits_logical_screen(qtbot, available):
    from moyle_steg.layout import fit_window_to_screen

    window = QWidget()
    window.setMinimumSize(760, 480)
    window.resize(1220, 820)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)
    fitted = fit_window_to_screen(window, available_geometry=available)
    qtbot.wait(10)
    assert window.geometry() == fitted
    assert available.adjusted(12, 12, -12, -12).contains(window.frameGeometry())
    assert window.width() >= 760 and window.height() >= 480


def test_screen_api_is_read_in_logical_pixels_and_oversized_minimum_is_capped(qtbot):
    from moyle_steg.layout import fit_window_to_screen

    available = QRect(60, 40, 730, 450)

    class Screen:
        def availableGeometry(self):
            return available

        def devicePixelRatio(self):
            pytest.fail('Screen geometry is already logical; do not multiply by DPR')

    window = QWidget()
    window.setMinimumSize(760, 480)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(10)
    fit_window_to_screen(window, Screen(), preferred_size=QSize(1220, 820))
    qtbot.wait(10)
    assert available.adjusted(12, 12, -12, -12).contains(window.frameGeometry())
    assert window.minimumSize().width() <= window.width()
    assert window.minimumSize().height() <= window.height()


def _panel(text):
    widget = QWidget()
    body = QVBoxLayout(widget)
    label = QLabel(text)
    label.setWordWrap(True)
    body.addWidget(label)
    edit = QLineEdit('keep this input / 保留输入')
    body.addWidget(edit)
    return widget, edit


def test_columns_stack_without_recreating_or_clipping_fields(qtbot):
    from moyle_steg.layout import ResponsiveColumns

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    page = QWidget()
    body = QVBoxLayout(page)
    columns = ResponsiveColumns(breakpoint=720)
    first, first_edit = _panel('A saved file remains selected while the window becomes narrower. ' * 4)
    second, second_edit = _panel('输入文件、输出文件和凭据设置应当保持原样。' * 8)
    columns.addWidget(first, 1)
    columns.addWidget(second, 1)
    body.addWidget(columns)
    body.addStretch()
    scroll.setWidget(page)
    qtbot.addWidget(scroll)
    scroll.resize(980, 700)
    scroll.show()
    qtbot.wait(30)
    assert not columns.is_stacked
    assert first.geometry().right() < second.geometry().left()
    original_widgets = (first_edit, second_edit)

    scroll.resize(540, 460)
    qtbot.wait(30)
    assert columns.is_stacked
    assert first.geometry().bottom() < second.geometry().top()
    assert columns.rect().contains(first.geometry())
    assert columns.rect().contains(second.geometry())
    assert scroll.horizontalScrollBar().maximum() == 0
    assert first_edit.text() == second_edit.text() == 'keep this input / 保留输入'
    assert tuple(columns.findChildren(QLineEdit)) == original_widgets

    scroll.resize(980, 700)
    qtbot.wait(30)
    assert not columns.is_stacked
    assert first.geometry().right() < second.geometry().left()
    assert tuple(columns.findChildren(QLineEdit)) == original_widgets


def test_layout_adapter_preserves_children_and_honors_their_minimum_width(qtbot):
    from moyle_steg.layout import ResponsiveColumns

    columns = ResponsiveColumns(breakpoint=600, spacing=16)
    first_layout = QVBoxLayout()
    edit = QLineEdit('existing layout')
    first_layout.addWidget(edit)
    first = columns.addLayout(first_layout, 1)
    second, _ = _panel('Second column')
    first.setMinimumWidth(340)
    second.setMinimumWidth(340)
    columns.addWidget(second, 1)
    qtbot.addWidget(columns)
    columns.resize(680, 260)
    columns.show()
    qtbot.wait(20)
    assert columns.is_stacked  # 340 + 16 + 340 does not fit, despite the threshold.
    assert columns.width() == 680
    assert columns.rect().contains(first.geometry())
    assert columns.rect().contains(second.geometry())
    assert edit.text() == 'existing layout'


def test_changed_child_minimum_reflows_without_window_resize(qtbot):
    from moyle_steg.layout import ResponsiveColumns

    columns = ResponsiveColumns(breakpoint=600)
    first, _ = _panel('First localized panel')
    second, _ = _panel('Second localized panel')
    first.setMinimumWidth(340)
    second.setMinimumWidth(340)
    columns.addWidget(first)
    columns.addWidget(second)
    qtbot.addWidget(columns)
    columns.resize(760, 260)
    columns.show()
    qtbot.wait(20)
    assert not columns.is_stacked
    first.setMinimumWidth(440)
    qtbot.wait(20)
    assert columns.width() == 760
    assert columns.is_stacked
    assert first.geometry().bottom() < second.geometry().top()


def test_parent_layout_item_receives_a_real_height_for_nonwrapping_columns(qtbot):
    from moyle_steg.layout import ResponsiveColumns

    parent = QWidget()
    body = QVBoxLayout(parent)
    columns = ResponsiveColumns(breakpoint=600)
    columns.addWidget(QLabel('Nonwrapping header'))
    combo = QComboBox()
    combo.addItems(['First', 'Second'])
    columns.addWidget(combo)
    body.addWidget(columns)
    body.addStretch()
    qtbot.addWidget(parent)
    parent.resize(900, 300)
    parent.show()
    qtbot.wait(20)
    expected = columns.heightForWidth(columns.width())
    assert expected > 0
    assert body.itemAt(0).heightForWidth(columns.width()) == expected
    assert columns.height() >= expected
