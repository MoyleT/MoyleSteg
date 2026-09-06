"""Theme personality changes rendering and feedback without moving the task."""
import pytest
from PySide6.QtCore import QSettings, QPoint, QRect, Qt, QEvent, QAbstractAnimation
from PySide6.QtGui import QColor, QEnterEvent
from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QLineEdit, QDoubleSpinBox


def make_window(qtbot, tmp_path, language='zh_CN'):
    from moyle_steg.window import MainWindow
    window = MainWindow(QSettings(str(tmp_path / 'personality.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.set_reduce_motion(True)
    window.set_language(language)
    window.resize(1220, 820)
    window.show()
    return window


def test_primary_actions_use_the_theme_feedback_button(qtbot, tmp_path):
    from moyle_steg.widgets import ActionButton
    window = make_window(qtbot, tmp_path)
    for form in window.forms.values():
        assert isinstance(form['run'], ActionButton)
        assert form['run']._hover_animation is not None


def _geometry(window):
    widgets = {'theme': window.theme_combo, 'language': window.language_combo,
               'motion': window.motion_toggle, 'title': window.page_title}
    widgets.update(('nav-' + page, button) for page, button in window.nav_buttons.items())
    for page, form in window.forms.items():
        for name, field in form.items():
            if hasattr(field, 'edit') and hasattr(field, 'browse'):
                widgets[page + '-' + name + '-edit'] = field.edit
                widgets[page + '-' + name + '-browse'] = field.browse
            elif isinstance(field, (QAbstractButton, QComboBox, QLineEdit, QDoubleSpinBox)):
                widgets[page + '-' + name] = field
    return {name: QRect(widget.mapTo(window, QPoint()), widget.size()).getRect()
            for name, widget in widgets.items() if widget.isVisible()}


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_theme_switch_preserves_every_visible_control_geometry(qtbot, tmp_path, language):
    window = make_window(qtbot, tmp_path, language)
    form = window.forms['hide']
    form['input'].edit.setText(str(tmp_path / 'saved-task.txt'))
    form['password'].setText('same form while trying themes')
    form['confirm'].setText('same form while trying themes')
    for page in window.PAGE_KEYS:
        window.set_theme('midnight')
        window.show_page(page)
        qtbot.wait(100)
        baseline = _geometry(window)
        assert 'nav-hide' in baseline
        if page != 'guide':
            assert page + '-run' in baseline
        for theme_id in ('blossom', 'terminal', 'midnight'):
            window.set_theme(theme_id)
            qtbot.wait(100)
            assert _geometry(window) == baseline, (language, page, theme_id)
            assert window.size().width() == 1220
            assert window.size().height() == 820
    assert form['password'].text() == 'same form while trying themes'
    assert form['input'].edit.text().endswith('saved-task.txt')


def _capture_button(window, button, qtbot):
    window.scroll.ensureWidgetVisible(button, 0, 12)
    qtbot.wait(30)
    surface = window.grab().toImage()
    ratio = surface.devicePixelRatio()
    origin = button.mapTo(window, QPoint())
    return surface.copy(round(origin.x() * ratio), round(origin.y() * ratio),
                        round(button.width() * ratio), round(button.height() * ratio)), ratio


def _matches(color, expected, tolerance=6):
    target = QColor(expected)
    return max(abs(color.red() - target.red()), abs(color.green() - target.green()),
               abs(color.blue() - target.blue())) <= tolerance


def test_primary_corner_pixels_distinguish_soft_pink_from_terminal_shape(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    button = window.forms['hide']['run']
    coverage = {}
    sizes = []
    for theme_id in ('blossom', 'terminal'):
        window.set_theme(theme_id)
        QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
        image, ratio = _capture_button(window, button, qtbot)
        sizes.append(button.size())
        # A flat rectangular corner fills this patch; a larger rounded corner
        # exposes the page below it. Sample composed pixels, not QSS strings.
        edge = round(9 * ratio)
        coverage[theme_id] = sum(_matches(image.pixelColor(x, y), window.theme.accent)
                                 for y in range(edge) for x in range(edge)) / (edge * edge)
    assert sizes[0] == sizes[1]
    assert coverage['terminal'] > 0.8, coverage
    assert coverage['blossom'] < 0.6, coverage
    assert coverage['terminal'] - coverage['blossom'] > 0.3, coverage


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
def test_hover_animation_and_reduced_motion_do_not_touch_form_state(qtbot, tmp_path, theme_id):
    window = make_window(qtbot, tmp_path)
    window.set_theme(theme_id)
    window.set_reduce_motion(False)
    form = window.forms['hide']
    button = form['run']
    form['password'].setText('still private while hovering')
    form['output'].edit.setText(str(tmp_path / 'chosen.png'))
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    qtbot.waitUntil(lambda: button._hover_animation.state() == QAbstractAnimation.State.Stopped)
    assert button._hover_mix == 0.0
    point = button.rect().center().toPointF()
    event = QEnterEvent(point, point, button.mapToGlobal(button.rect().center()).toPointF())
    # Explicit enter events isolate feedback logic from the desktop cursor;
    # the existing native hover matrix verifies real pointer event delivery.
    QApplication.sendEvent(button, event)
    if theme_id == 'terminal':
        # Terminal feedback intentionally snaps; soft themes ease into place.
        assert button._hover_animation.state() == QAbstractAnimation.State.Stopped
    else:
        assert button._hover_animation.state() == QAbstractAnimation.State.Running
        qtbot.waitUntil(lambda: button._hover_animation.state() == QAbstractAnimation.State.Stopped, timeout=1000)
    assert button._hover_mix == 1.0
    rendered, ratio = _capture_button(window, button, qtbot)
    # Feedback has to reach the composed surface, not only an animation
    # counter. The reserved right padding contains the theme's small motif.
    motif = rendered.copy(round((button.width() - 18) * ratio),
                          round((button.height() / 2 - 7) * ratio),
                          round(16 * ratio), round(14 * ratio))
    motif_ink = sum(_matches(motif.pixelColor(x, y), window.theme.on_accent, tolerance=20)
                    for y in range(motif.height()) for x in range(motif.width()))
    assert motif_ink >= 5, (theme_id, motif_ink)
    assert form['password'].text() == 'still private while hovering'
    assert form['output'].edit.text() == str(tmp_path / 'chosen.png')
    assert not window.busy
    window.set_reduce_motion(True)
    QApplication.sendEvent(button, QEvent(QEvent.Type.Leave))
    assert button._hover_mix == 0.0
    assert button._hover_animation.state() == QAbstractAnimation.State.Stopped
    QApplication.sendEvent(button, event)
    assert button._hover_mix == 1.0
    assert button._hover_animation.state() == QAbstractAnimation.State.Stopped
    assert button.reduce_motion is True


def test_blossom_fruit_illustration_has_accessible_meaning_and_no_layout_shift(qtbot, tmp_path):
    from moyle_steg.widgets import FruitAccent
    window = make_window(qtbot, tmp_path)
    fruit = window.findChild(FruitAccent)
    assert fruit is not None
    window.set_theme('blossom')
    qtbot.wait(30)
    assert fruit.isVisible()
    surface = window.grab().toImage()
    ratio = surface.devicePixelRatio()
    origin = fruit.mapTo(window, QPoint())
    drawing = surface.copy(round(origin.x() * ratio), round(origin.y() * ratio),
                           round(fruit.width() * ratio), round(fruit.height() * ratio))
    red_pixels = green_pixels = 0
    for y in range(drawing.height()):
        for x in range(drawing.width()):
            color = drawing.pixelColor(x, y)
            red_pixels += (color.red() > 150 and color.red() > color.green() + 40
                           and color.red() > color.blue() + 10)
            green_pixels += (color.green() > color.red() + 20 and color.green() > color.blue() + 10)
    assert red_pixels > 40, 'The fruit bodies must be painted on the actual interface'
    assert green_pixels > 8, 'Fruit leaves/stems must be visible, not only an accessible label'
    description_zh = fruit.accessibleName() + ' ' + fruit.accessibleDescription()
    assert '草莓' in description_zh and '樱桃' in description_zh
    window.set_language('en_US')
    description_en = (fruit.accessibleName() + ' ' + fruit.accessibleDescription()).lower()
    assert 'strawberr' in description_en and 'cherr' in description_en
    geometry = fruit.geometry()
    window.set_theme('terminal')
    qtbot.wait(30)
    assert fruit.geometry() == geometry
