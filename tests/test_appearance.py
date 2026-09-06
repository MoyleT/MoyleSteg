"""Theme preferences and live desktop controls preserve task state."""
import pytest
from PySide6.QtCore import QSettings, Qt, QTimer, QPoint, QRect
from PySide6.QtTest import QTest


def make_window(qtbot, tmp_path, **preferences):
    from moyle_steg.window import MainWindow
    settings = QSettings(str(tmp_path / 'appearance.ini'), QSettings.Format.IniFormat)
    for key, value in preferences.items():
        settings.setValue(key, value)
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.show()
    return window


def test_default_and_invalid_theme_fall_back_to_midnight(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path, theme='unknown-old-theme')
    assert window.theme_id == 'midnight'
    assert window.theme.id == 'midnight'
    assert window.theme_combo.currentData() == 'midnight'
    assert window.theme_combo.objectName() == 'theme_selector'


@pytest.mark.parametrize('theme_id', ['midnight', 'blossom', 'terminal'])
def test_theme_and_motion_preferences_survive_reopening(qtbot, tmp_path, theme_id):
    window = make_window(qtbot, tmp_path)
    window.set_theme(theme_id)
    window.motion_toggle.setChecked(True)
    window.settings.sync()
    assert window.settings.value('theme') == theme_id
    assert window.settings.value('reduce_motion', type=bool) is True
    window.close()
    reopened = make_window(qtbot, tmp_path)
    assert reopened.theme_id == theme_id
    assert reopened.theme_combo.currentData() == theme_id
    assert reopened.motion_toggle.isChecked()


def test_theme_language_and_keyboard_switches_preserve_form_values(qtbot, tmp_path):
    window = make_window(qtbot, tmp_path)
    form = window.forms['hide']
    form['input'].edit.setText(str(tmp_path / 'private-payload.txt'))
    form['output'].edit.setText(str(tmp_path / 'chosen-output.png'))
    form['password'].setText('keep until operation finishes')
    form['confirm'].setText('keep until operation finishes')
    form['resize'].setChecked(True)
    form['fill'].setValue(76)
    form['force'].setChecked(True)
    saved = (form['input'].edit.text(), form['output'].edit.text(), form['password'].text(),
             form['confirm'].text(), form['resize'].isChecked(), form['fill'].value(), form['force'].isChecked())
    labels = {}
    for language in ('zh_CN', 'en_US'):
        window.set_language(language)
        labels[language] = tuple(window.theme_combo.itemText(i) for i in range(window.theme_combo.count()))
        for theme_id in ('midnight', 'blossom', 'terminal'):
            window.set_theme(theme_id)
            assert window.theme_combo.currentData() == theme_id
            assert window.language == language
            assert saved == (form['input'].edit.text(), form['output'].edit.text(), form['password'].text(),
                             form['confirm'].text(), form['resize'].isChecked(), form['fill'].value(), form['force'].isChecked())
    assert labels['zh_CN'] != labels['en_US']
    selector = window.theme_combo
    selector.setFocus()
    QTest.keyClick(selector, Qt.Key.Key_Home)
    qtbot.waitUntil(lambda: selector.currentIndex() == 0)
    QTest.keyClick(selector, Qt.Key.Key_Down)
    qtbot.waitUntil(lambda: selector.currentIndex() == 1)
    assert window.theme_id == selector.currentData()
    assert window.settings.value('theme') == selector.currentData()


def test_theme_switch_during_a_job_preserves_lock_progress_and_safe_cancel(qtbot, tmp_path, monkeypatch):
    from threading import Event
    from moyle_steg import worker

    reached = Event()
    release = Event()

    def controlled_execute(request, *, control=None):
        control.report('read', 1, 4)
        reached.set()
        if not release.wait(10):
            raise AssertionError('The UI did not release its controlled worker')
        control.report('read', 2, 4)
        raise AssertionError('Cancellation should be observed before returning a result')

    monkeypatch.setattr(worker, 'execute', controlled_execute)
    window = make_window(qtbot, tmp_path)
    window.resize(1040, 720)
    window.show_page('crypt')
    form = window.forms['crypt']
    source = tmp_path / 'stable-source.txt'
    source.write_text('synthetic task input', encoding='utf-8')
    output = tmp_path / 'never-committed.saes'
    form['input'].edit.setText(str(source))
    form['output'].edit.setText(str(output))
    form['password'].setText('temporary task password')
    form['confirm'].setText('temporary task password')
    form['run'].click()
    try:
        qtbot.waitUntil(reached.is_set, timeout=3000)
        qtbot.waitUntil(lambda: window.progress.value() == 250, timeout=3000)
        for theme_id in ('blossom', 'terminal', 'midnight'):
            window.set_theme(theme_id)
            window.set_language('en_US')
            assert window.busy and window.progress.isVisible()
            assert window.progress.value() == 250
            assert window.progress.height() == 16
            for control in (window.progress, window.cancel_button, window.status_label):
                bounds = QRect(control.mapTo(window, QPoint()), control.size())
                assert window.rect().contains(bounds)
            assert any(timer.isActive() for timer in window.progress.findChildren(QTimer))
            window.set_reduce_motion(True)
            assert not any(timer.isActive() for timer in window.progress.findChildren(QTimer))
            window.set_reduce_motion(False)
            assert not form['run'].isEnabled()
            assert window.cancel_button.isEnabled()
            assert form['password'].text() == 'temporary task password'
            assert form['output'].edit.text() == str(output)
        window.cancel_button.click()
        assert window._cancel_requested
        assert not window.cancel_button.isEnabled()
    finally:
        if window.busy and not window._cancel_requested:
            window.cancel_operation()
        release.set()
        qtbot.waitUntil(lambda: not window.busy, timeout=5000)
    assert window._feedback_key == 'cancelled'
    assert not any(timer.isActive() for timer in window.progress.findChildren(QTimer))
    assert not output.exists()
    assert form['password'].text() == 'temporary task password'
    assert form['run'].isEnabled()


def test_reduced_motion_stops_page_animation_without_hiding_controls(qtbot, tmp_path):
    from PySide6.QtCore import QAbstractAnimation
    window = make_window(qtbot, tmp_path)
    window.show_page('crypt')
    assert window._page_animation.state() == QAbstractAnimation.State.Running
    window.motion_toggle.setChecked(True)
    assert window._page_animation.state() == QAbstractAnimation.State.Stopped
    assert window._page_effect.opacity() == 1.0
    for page in ('extract', 'verify', 'hide'):
        window.show_page(page)
        assert window._page_animation.state() == QAbstractAnimation.State.Stopped
        assert window._page_effect.opacity() == 1.0
        assert window.stack.currentWidget() is window.pages[page]
        assert window.pages[page].isVisible()
    window.motion_toggle.setChecked(False)
    window.show_page('guide')
    assert window._page_animation.state() == QAbstractAnimation.State.Running
    qtbot.waitUntil(lambda: window._page_animation.state() == QAbstractAnimation.State.Stopped, timeout=1000)
    assert window._page_effect.opacity() == 1.0
