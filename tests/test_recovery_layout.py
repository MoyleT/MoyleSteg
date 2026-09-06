"""Real-window recovery controls remain reachable in small logical work areas."""

import pytest
from PySide6.QtCore import QPoint, QRect, QSettings, QSize
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLineEdit

from moyle_steg.layout import fit_window_to_screen
from moyle_steg.window import MainWindow


AREAS = [QRect(0, 0, 1280, 680), QRect(0, 0, 1093, 574), QRect(-1093, 40, 1093, 574)]


def _window(qtbot, tmp_path, language='zh_CN', text_size='standard'):
    settings = QSettings(str(tmp_path / 'layout-settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('language', language)
    settings.setValue('text_size', text_size)
    settings.setValue('reduce_motion', True)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(30)  # Complete the first-show native-frame fit before explicit test bounds.
    return window


def _reachable(qtbot, scroll, widget, context):
    assert widget.isVisible(), (context, widget.objectName(), 'control hidden')
    # QScrollArea.ensureWidgetVisible(QLineEdit) targets its input-method cursor
    # rectangle, not the field border. Drive the actual vertical scrollbar to
    # the whole control's top; never scroll horizontally or relax containment.
    scroll.verticalScrollBar().setValue(widget.mapTo(scroll.widget(), QPoint()).y())
    qtbot.wait(5)
    viewport = scroll.viewport()
    rendered = QRect(widget.mapTo(viewport, QPoint()), widget.size())
    assert viewport.rect().contains(rendered), (context, widget.objectName(), rendered, viewport.rect())
    assert scroll.horizontalScrollBar().maximum() == 0, (context, 'horizontal overflow')


@pytest.mark.parametrize('available', AREAS)
@pytest.mark.parametrize('text_size', ['standard', 'large'])
@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
def test_small_work_area_keeps_window_and_all_task_controls_accessible(qtbot, tmp_path, available, text_size, language):
    window = _window(qtbot, tmp_path, language, text_size)
    fit_window_to_screen(window, available_geometry=available, preferred_size=QSize(1220, 820))
    qtbot.wait(30)
    assert available.adjusted(12, 12, -12, -12).contains(window.frameGeometry())
    fitted_size = window.size()
    for control in (window.theme_combo, window.language_combo):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))

    for page in ('hide', 'extract', 'crypt', 'verify', 'keygen'):
        window.show_page(page)
        form = window.forms[page]
        # Exercise the longer recovery form, including the advanced controls.
        if page == 'crypt':
            form['mode'].setCurrentIndex(1)
        if 'budget' in form:
            form['budget'].toggle.setChecked(True)
            form['budget'].pixels.setValue(50_000_000)  # Expose the acknowledgement used by larger recoveries.
        qtbot.wait(20)
        context = (available, language, text_size, page)
        for name in ('run', 'preflight', 'inspect'):
            if name in form:
                _reachable(qtbot, window.scroll, form[name], context + (name,))
        for widget in window.pages[page].findChildren(QLineEdit):
            if widget.isVisible():
                _reachable(qtbot, window.scroll, widget, context + ('input edge',))
        for field in form.values():
            if hasattr(field, 'browse') and field.browse.isVisible():
                _reachable(qtbot, window.scroll, field.browse, context + ('browse edge',))
        if 'budget' in form:
            for control in (form['budget'].toggle, form['budget'].confirm):
                _reachable(qtbot, window.scroll, control, context + ('budget',))
        assert window.size() == fitted_size, (context, 'form forced a larger window')
        assert available.contains(window.frameGeometry())

    for control in (*window.nav_buttons.values(), window.motion_toggle, window.text_size_combo):
        _reachable(qtbot, window.sidebar_scroll, control, ('sidebar', language, text_size))


@pytest.mark.parametrize('language', ['zh_CN', 'en_US'])
@pytest.mark.parametrize('text_size', ['standard', 'large'])
def test_declared_minimum_window_has_no_horizontal_field_or_action_clipping(qtbot, tmp_path, language, text_size):
    window = _window(qtbot, tmp_path, language, text_size)
    window.resize(760, 480)
    qtbot.wait(20)
    assert window.size() == QSize(760, 480)
    for page in ('hide', 'extract', 'crypt', 'verify', 'keygen'):
        window.show_page(page)
        qtbot.wait(20)
        form = window.forms[page]
        for name in ('run', 'preflight', 'inspect'):
            if name in form:
                _reachable(qtbot, window.scroll, form[name], ('minimum', language, text_size, page, name))
        for control in window.pages[page].findChildren(QLineEdit):
            if control.isVisible():
                _reachable(qtbot, window.scroll, control, ('minimum', language, text_size, page, 'input edge'))
        assert window.size() == QSize(760, 480)
    window.show_page('guide')
    qtbot.wait(20)
    _reachable(qtbot, window.scroll, window.guide_browser, ('minimum', language, text_size, 'guide'))


def _form_snapshot(window):
    snapshot = {}
    for page, form in window.forms.items():
        for name, widget in form.items():
            if hasattr(widget, 'edit') and isinstance(widget.edit, QLineEdit):
                snapshot[page, name] = (id(widget), widget.edit.text())
            elif isinstance(widget, QLineEdit):
                snapshot[page, name] = (id(widget), widget.text())
            elif isinstance(widget, QCheckBox):
                snapshot[page, name] = (id(widget), widget.isChecked())
            elif isinstance(widget, QComboBox):
                snapshot[page, name] = (id(widget), widget.currentIndex())
            elif isinstance(widget, QDoubleSpinBox):
                snapshot[page, name] = (id(widget), widget.value())
    return snapshot


def test_switching_themes_language_and_font_size_preserves_forms_at_small_size(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    fit_window_to_screen(window, available_geometry=AREAS[1], preferred_size=QSize(1220, 820))
    for page, form in window.forms.items():
        for name in ('input', 'cover', 'output', 'key'):
            if name in form:
                form[name].edit.setText(str(tmp_path / (page + '-' + name + '.synthetic')))
        for name in ('password', 'confirm'):
            if name in form:
                form[name].setText('synthetic layout password')
    window.forms['hide']['resize'].setChecked(True)
    window.forms['hide']['fill'].setValue(73)
    before = _form_snapshot(window)
    fitted_size = window.size()
    for theme in ('midnight', 'blossom', 'terminal'):
        for text_size in ('large', 'standard'):
            window.set_theme(theme)
            window.set_text_size(text_size)
            window.set_language('en_US' if text_size == 'large' else 'zh_CN')
            qtbot.wait(20)
            assert _form_snapshot(window) == before
            assert window.size() == fitted_size
            _reachable(qtbot, window.scroll, window.forms['hide']['run'], (theme, text_size))


def test_normal_first_show_refits_native_frame_and_respects_explicit_pre_show_resize(qtbot, tmp_path, monkeypatch):
    from moyle_steg import window as window_module

    available = AREAS[0]
    calls = []

    def observed_fit(window, **kwargs):
        calls.append(window.windowHandle() is not None)
        return fit_window_to_screen(window, available_geometry=available, **kwargs)

    monkeypatch.setattr(window_module, 'fit_window_to_screen', observed_fit)
    normal = _window(qtbot, tmp_path / 'normal')
    assert calls == [False, True]
    assert available.adjusted(12, 12, -12, -12).contains(normal.frameGeometry())

    calls.clear()
    custom = MainWindow(QSettings(str(tmp_path / 'custom.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(custom)
    custom.resize(940, 530)
    custom.show()
    qtbot.wait(30)
    assert custom.size() == QSize(940, 530)
    assert calls == [False], 'A caller resize before show must not be replaced by the launch fit'
