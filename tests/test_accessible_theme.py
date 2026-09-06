"""Rendered input boundaries, readable type, and stable task icon semantics."""
import pytest

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QComboBox, QFrame, QLabel, QLineEdit, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout,
)

from moyle_steg.theme import THEMES, build_stylesheet
from moyle_steg.widgets import line_icon


def contrast(a, b):
    def luminance(value):
        color = QColor(value)
        channels = (color.redF(), color.greenF(), color.blueF())
        return sum((c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4) * w
                   for c, w in zip(channels, (.2126, .7152, .0722)))
    low, high = sorted((luminance(a), luminance(b)))
    return (high + .05) / (low + .05)


def form(qtbot, theme_id, control_type=QLineEdit, on_card=False):
    host = QFrame()
    host.setObjectName('card' if on_card else 'workspace')
    host.setStyleSheet(build_stylesheet(theme_id))
    layout = QVBoxLayout(host)
    label = QLabel('文件 / File')
    label.setProperty('role', 'fieldLabel')
    control = control_type()
    if isinstance(control, QComboBox):
        control.addItems(['PNG', 'SAES'])
    control.setMinimumWidth(280)
    other = QPushButton('Next')
    progress = QProgressBar()
    progress.setTextVisible(False)
    for widget in (label, control, other, progress):
        layout.addWidget(widget)
    qtbot.addWidget(host)
    host.show()
    other.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(other.hasFocus)
    return host, label, control, other, progress


def edge_pixel(control):
    image = control.grab().toImage()
    # Straight left edge avoids rounded corners, glyphs, and arrow subcontrols.
    return image.pixelColor(0, image.height() // 2)


@pytest.mark.parametrize('theme_id', THEMES)
@pytest.mark.parametrize('on_card', [False, True])
@pytest.mark.parametrize('control_type', [QLineEdit, QComboBox, QSpinBox, QPlainTextEdit])
def test_empty_input_boundary_is_visible_against_both_sides(qtbot, theme_id, on_card, control_type):
    host, _, control, _, _ = form(qtbot, theme_id, control_type, on_card)
    theme = THEMES[theme_id]
    painted_edge = edge_pixel(control)
    for background in (theme.input_bg, theme.bg, theme.surface):
        assert contrast(painted_edge, background) >= 3, (theme_id, control_type, painted_edge.name(), background)
    # Surface decoration keeps the previous, softer hierarchy.
    assert contrast(theme.border, theme.surface) < 3


@pytest.mark.parametrize('theme_id', THEMES)
@pytest.mark.parametrize('control_type', [QLineEdit, QComboBox, QSpinBox, QPlainTextEdit])
def test_keyboard_focus_has_distinct_edge_without_moving_the_control(qtbot, theme_id, control_type):
    host, _, control, _, _ = form(qtbot, theme_id, control_type)
    normal_edge = edge_pixel(control)
    geometry, hint = control.geometry(), control.sizeHint()
    control.setFocus(Qt.FocusReason.TabFocusReason)
    qtbot.waitUntil(control.hasFocus)
    focused_edge = edge_pixel(control)
    assert focused_edge != normal_edge
    for background in (THEMES[theme_id].input_bg, THEMES[theme_id].bg, THEMES[theme_id].surface):
        assert contrast(focused_edge, background) >= 3
    assert control.geometry() == geometry
    assert control.sizeHint() == hint


@pytest.mark.parametrize('theme_id', THEMES)
def test_large_type_enlarges_real_fonts_and_retains_the_thin_progress(qtbot, theme_id):
    host, label, control, button, progress = form(qtbot, theme_id)
    title = QLabel('恢复文件 / Restore file', host)
    title.setObjectName('pageTitle')
    host.layout().insertWidget(0, title)
    selector = QComboBox(host)
    selector.setObjectName('theme_selector')
    selector.addItem('星夜 / Midnight')
    host.layout().insertWidget(1, selector)
    qtbot.waitUntil(lambda: title.isVisible() and selector.isVisible())
    host.adjustSize()
    standard = {widget: widget.font().pixelSize() for widget in (label, control, button, title, selector)}
    assert standard[label] == 11 and standard[control] == 13
    for mode in ('large', 'standard'):
        host.setStyleSheet(build_stylesheet(theme_id, text_size=mode))
        host.adjustSize()
        qtbot.wait(10)
        for widget, original in standard.items():
            assert widget.font().pixelSize() == original + (2 if mode == 'large' else 0)
            assert widget.height() >= widget.fontMetrics().height()
        assert progress.height() == 16
        assert control.grab().toImage().isNull() is False


@pytest.mark.parametrize('name', ['hide', 'extract'])
@pytest.mark.parametrize('state', [QIcon.State.Off, QIcon.State.On])
def test_task_icons_keep_their_functional_silhouette_in_every_theme(qapp, name, state):
    # The named line glyphs express image/hide and outward-arrow/extract. Only
    # their theme tint may vary; a fruit silhouette must not replace the task.
    reference = line_icon(name, '#FFFFFF').pixmap(72, 72, QIcon.Mode.Normal, state).toImage()
    other_name = 'extract' if name == 'hide' else 'hide'
    other = line_icon(other_name, '#FFFFFF').pixmap(72, 72, QIcon.Mode.Normal, state).toImage()
    assert reference != other
    for theme_id in THEMES:
        actual = line_icon(name, '#FFFFFF', theme_id=theme_id).pixmap(72, 72, QIcon.Mode.Normal, state).toImage()
        assert actual == reference, (theme_id, name)
