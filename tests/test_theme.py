"""Composed Qt controls remain readable under window-directed input events.

The default QWindow route tests Qt hit testing, hover state, and actual widget
painting without moving the shared operating-system cursor. It does not test
the OS mouse driver. Set MOYLE_TEST_SYSTEM_POINTER=1 for that separate manual,
foreground-desktop check; it requires exclusive use of the physical cursor.
"""
import os
import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QObject, QEvent
from PySide6.QtGui import QColor, QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSpinBox


THEME_IDS = ('midnight', 'blossom', 'terminal')
SYSTEM_POINTER = os.environ.get('MOYLE_TEST_SYSTEM_POINTER') == '1'


def move_pointer(window, widget):
    if SYSTEM_POINTER:
        QTest.mouseMove(widget)
    else:
        # Qt 6.11's QWidget overload calls QCursor.setPos for unpressed moves;
        # the QWindow overload delivers through Qt's window-system interface.
        # https://github.com/qt/qtbase/blob/6.11/src/testlib/qtestmouse.h
        QTest.mouseMove(window.windowHandle(), widget.mapTo(window, widget.rect().center()))


class PointerTrace(QObject):
    """Record only this test's widgets when native hover delivery fails."""
    def __init__(self, window, button, guide):
        super().__init__(window)
        self.window = window
        self.button = button
        self.guide = guide
        self.initial_cursor = QCursor.pos().toTuple()
        self.events = []
        for widget in (window, button, guide):
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.Leave, QEvent.Type.MouseMove,
                            QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate,
                            QEvent.Type.Move, QEvent.Type.Resize):
            position = QCursor.pos()
            self.events.append((watched.objectName() or type(watched).__name__, event.type().name,
                                position.x(), position.y(), self.button.underMouse()))
        return False

    def snapshot(self):
        cursor = QCursor.pos()
        target = self.button.mapToGlobal(self.button.rect().center())
        hit = QApplication.widgetAt(cursor)
        active = QApplication.activeWindow()
        result = {'cursor': cursor.toTuple(), 'target': target.toTuple(),
                  'input_mode': 'system_cursor' if SYSTEM_POINTER else 'qt_window_events',
                  'cursor_before_moves': self.initial_cursor,
                  'guide_target': self.guide.mapToGlobal(self.guide.rect().center()).toTuple(),
                  'guide_under_mouse': self.guide.underMouse(),
                  'button_global_rect': QRect(self.button.mapToGlobal(QPoint()), self.button.size()).getRect(),
                  'our_widget_at_cursor': None if hit is None else (hit.objectName() or type(hit).__name__),
                  'test_window_active': active is self.window, 'window_exposed': self.window.windowHandle().isExposed(),
                  'button_under_mouse': self.button.underMouse(), 'hover_mix': getattr(self.button, '_hover_mix', None),
                  'events': self.events[-30:]}
        if QApplication.platformName() == 'windows':
            import ctypes
            ctypes.windll.user32.GetForegroundWindow.restype = ctypes.c_void_p
            result['test_window_is_foreground'] = ctypes.windll.user32.GetForegroundWindow() == int(self.window.winId())
        return result


def window_for_theme(qtbot, tmp_path, theme_id='midnight'):
    app = QApplication.instance()
    app.setStyle('Fusion')
    from moyle_steg.window import MainWindow
    window = MainWindow(settings=QSettings(str(tmp_path / 'theme.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.set_theme(theme_id)
    window.motion_toggle.setChecked(True)
    if app.platformName() == 'windows':
        if not SYSTEM_POINTER:
            window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        with qtbot.waitExposed(window, timeout=3000):
            window.show()
        if SYSTEM_POINTER:
            with qtbot.waitActive(window, timeout=3000):
                window.raise_()
                window.activateWindow()
    else:
        window.show()
    window.forms['hide']['credential'].setCurrentIndex(1)
    if not SYSTEM_POINTER:
        # Establish a window entry before traversing into a child control.
        # This is an input event, never a manual underMouse/hover flag change.
        app.processEvents()
        QTest.mouseMove(window.windowHandle(), QPoint(2, 2))
    return window


def rendered_control(window, control, qtbot):
    def fully_visible():
        content_position = control.mapTo(window.scroll.widget(), QPoint(0, 0))
        # ensureWidgetVisible may use QAbstractSpinBox's line-edit focus proxy,
        # which can leave the lower arrow outside the viewport.
        window.scroll.ensureVisible(content_position.x() + control.width() // 2,
                                    content_position.y() + control.height() // 2,
                                    control.width() // 2 + 12, control.height() // 2 + 12)
        position = control.mapTo(window.scroll.viewport(), QPoint(0, 0))
        return window.scroll.viewport().rect().contains(QRect(position, control.size()))
    # Layout reflow can change the scroll range after the first ensure call.
    # Never count pixels from a control clipped by the scroll viewport.
    qtbot.waitUntil(fully_visible, timeout=3000)
    image = window.grab().toImage()
    origin = control.mapTo(window, QPoint(0, 0))
    ratio = image.devicePixelRatio()
    return image.copy(round(origin.x() * ratio), round(origin.y() * ratio),
                      round(control.width() * ratio), round(control.height() * ratio)), ratio


def count_color(image, color, margin=0, tolerance=20):
    expected = QColor(color)
    count = 0
    for y in range(margin, image.height() - margin):
        for x in range(margin, image.width() - margin):
            pixel = image.pixelColor(x, y)
            if max(abs(pixel.red() - expected.red()), abs(pixel.green() - expected.green()),
                   abs(pixel.blue() - expected.blue())) <= tolerance:
                count += 1
    return count


@pytest.mark.parametrize('theme_id', THEME_IDS)
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
@pytest.mark.parametrize('state', ['default', 'hover', 'pressed', 'disabled'])
def test_primary_button_has_rendered_fill_and_visible_text(qtbot, tmp_path, theme_id, language, state):
    window = window_for_theme(qtbot, tmp_path, theme_id)
    theme = window.theme
    background = getattr(theme, {'default': 'accent', 'hover': 'accent_hover',
                                 'pressed': 'accent_pressed', 'disabled': 'disabled_bg'}[state])
    foreground = theme.disabled_text if state == 'disabled' else theme.on_accent
    window.set_language(language)
    button = window.forms['hide']['run']
    rendered_control(window, button, qtbot)
    trace = PointerTrace(window, button, window.nav_buttons['guide'])
    move_pointer(window, window.nav_buttons['guide'])
    if state == 'hover':
        try:
            qtbot.waitUntil(window.nav_buttons['guide'].underMouse, timeout=3000)
        except qtbot.TimeoutError as error:
            raise AssertionError({'phase': 'guide', **trace.snapshot()}) from error
        move_pointer(window, button)
        try:
            qtbot.waitUntil(button.underMouse, timeout=3000)
        except qtbot.TimeoutError as error:
            raise AssertionError({'phase': 'button', **trace.snapshot()}) from error
    elif state == 'pressed':
        move_pointer(window, button)
        QTest.mousePress(button, Qt.MouseButton.LeftButton)
    elif state == 'disabled':
        button.setEnabled(False)
    image, ratio = rendered_control(window, button, qtbot)
    if state == 'pressed':
        QTest.mouseRelease(button, Qt.MouseButton.LeftButton)
    background_count = count_color(image, background, tolerance=4)
    assert background_count > image.width() * image.height() * 0.45, (state, background_count)
    # Restrict to the interior: borders cannot masquerade as readable text.
    assert count_color(image, foreground, margin=round(8 * ratio), tolerance=18) > 25


@pytest.mark.parametrize('theme_id', THEME_IDS)
def test_card_inputs_keep_their_own_backgrounds_and_disabled_spinbox(qtbot, tmp_path, theme_id):
    window = window_for_theme(qtbot, tmp_path, theme_id)
    form = window.forms['hide']
    for control in (form['output'].edit, form['output'].browse, form['fill']):
        move_pointer(window, window.nav_buttons['guide'])
        image, ratio = rendered_control(window, control, qtbot)
        expected = window.theme.disabled_bg if control is form['fill'] else (
            window.theme.secondary if control is form['output'].browse else window.theme.input_bg)
        assert count_color(image, expected, tolerance=2) > image.width() * image.height() * 0.35
    spin = form['fill']
    disabled_image, ratio = rendered_control(window, spin, qtbot)
    assert count_color(disabled_image, window.theme.disabled_text, margin=round(6 * ratio), tolerance=18) > 10


@pytest.mark.parametrize('theme_id', THEME_IDS)
def test_spinbox_arrows_are_rendered_and_clickable(qtbot, tmp_path, theme_id):
    window = window_for_theme(qtbot, tmp_path, theme_id)
    form = window.forms['hide']
    form['resize'].setChecked(True)
    spin = form['fill']
    rendered_control(window, spin, qtbot)
    option = QStyleOptionSpinBox()
    spin.initStyleOption(option)
    up = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin)
    down = spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, spin)
    assert up.width() >= 20 and down.width() >= 20
    before = spin.value()
    QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
    assert spin.value() == before + spin.singleStep()
    QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=down.center())
    assert spin.value() == before
    image, ratio = rendered_control(window, spin, qtbot)
    for rect in (up, down):
        interior = rect.adjusted(5, 3, -5, -3)
        arrow = image.copy(round(interior.x() * ratio), round(interior.y() * ratio),
                           round(interior.width() * ratio), round(interior.height() * ratio))
        visible = count_color(arrow, window.theme.muted, tolerance=24)
        assert visible >= 7, 'The arrow must occupy visible foreground pixels, not a one-pixel dot'


@pytest.mark.parametrize('theme_id', THEME_IDS)
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
@pytest.mark.parametrize('combo_name', ['credential', 'language', 'theme'])
def test_expanded_combo_is_opaque_and_readable_under_hostile_os_palette(qtbot, tmp_path, theme_id, language, combo_name):
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    original_palette = app.palette()
    dark_palette = QPalette(original_palette)
    for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base,
                 QPalette.ColorRole.Button, QPalette.ColorRole.AlternateBase):
        dark_palette.setColor(role, QColor('#303030'))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        dark_palette.setColor(role, QColor('#dddddd'))
    app.setPalette(dark_palette)
    try:
        window = window_for_theme(qtbot, tmp_path, theme_id)
        window.set_language(language)
        combo = {'credential': window.forms['hide']['credential'],
                 'language': window.language_combo, 'theme': window.theme_combo}[combo_name]
        window.scroll.ensureWidgetVisible(combo, 12, 12)
        qtbot.wait(20)
        combo.showPopup()
        view = combo.view()
        # Windows paints a QRollEffect during its popup animation; inspect the
        # real item view only once that transition has actually completed.
        qtbot.waitUntil(view.isVisible, timeout=3000)
        unselected = (combo.currentIndex() + 1) % combo.count()
        rect = view.visualRect(view.model().index(unselected, 0)).intersected(view.viewport().rect())
        image = view.viewport().grab().toImage()
        ratio = image.devicePixelRatio()
        row = image.copy(round(rect.x() * ratio), round(rect.y() * ratio),
                         round(rect.width() * ratio), round(rect.height() * ratio))
        assert count_color(row, window.theme.surface, tolerance=4) > row.width() * row.height() * 0.60
        assert count_color(row, window.theme.text, tolerance=25) > 15
        # A transparent viewport would inherit the operating-system dark surface.
        assert row.pixelColor(max(0, row.width() - 15), row.height() // 2).alpha() == 255
        # The independent popup shell has top/bottom margins outside the item
        # view. A readable row alone used to miss the native dark menu bands.
        popup_image = view.window().grab().toImage()
        dpr = popup_image.devicePixelRatio()
        for y in (2, view.window().height() - 5):
            strip = popup_image.copy(round(3 * dpr), round(y * dpr),
                                     round((view.window().width() - 6) * dpr), round(3 * dpr))
            assert count_color(strip, window.theme.surface, tolerance=4) > strip.width() * strip.height() * .95, \
                'The complete popup must use its theme surface, including the top and bottom margins'
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
        qtbot.waitUntil(lambda: combo.currentIndex() == unselected, timeout=3000)
        qtbot.waitUntil(lambda: not view.isVisible(), timeout=3000)
    finally:
        app.setPalette(original_palette)


def contrast(foreground, background):
    def luminance(value):
        color = QColor(value)
        channels = [component / 255 for component in (color.red(), color.green(), color.blue())]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(foreground), luminance(background)))
    return (b + 0.05) / (a + 0.05)


@pytest.mark.parametrize('theme_id', THEME_IDS)
def test_text_palette_meets_readable_contrast_in_all_interaction_states(theme_id):
    from moyle_steg.theme import get_theme
    theme = get_theme(theme_id)
    pairs = [(theme.text, theme.surface), (theme.text, theme.input_bg),
             (theme.muted, theme.surface), (theme.muted, theme.bg),
             (theme.text, theme.secondary), (theme.text, theme.secondary_hover),
             (theme.disabled_text, theme.disabled_bg)]
    pairs.extend((theme.on_accent, background)
                 for background in (theme.accent, theme.accent_hover, theme.accent_pressed))
    for foreground, background in pairs:
        ratio = contrast(foreground, background)
        assert ratio >= 4.5, (theme_id, foreground, background, ratio)
