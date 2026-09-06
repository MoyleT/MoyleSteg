"""The distribution check must exercise both engine and actual Qt rendering."""

import json

import pytest


@pytest.mark.parametrize('missing', ['input', 'time', 'scope'])
def test_verification_context_rejects_summary_missing_provenance(tmp_path, missing):
    from types import SimpleNamespace
    from datetime import datetime
    from moyle_steg.diagnostics import _verification_context
    from moyle_steg.i18n import tr

    container = tmp_path / 'synthetic.png'
    stamp = '2026-09-05T10:20:30+08:00'
    displayed = datetime.fromisoformat(stamp).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
    parts = {'input': str(container), 'time': displayed, 'scope': tr('result_capture_status', 'en_US')}
    text = '\n'.join(value for name, value in parts.items() if name != missing)
    window = SimpleNamespace(result_summary=SimpleNamespace(text=lambda: text),
                             t=lambda key: tr(key, 'en_US'))
    result = SimpleNamespace(input_path=str(container), completed_at=stamp)
    with pytest.raises(AssertionError, match='summary'):
        _verification_context(window, result, container)


def _dropdown_window(qtbot, tmp_path):
    from PySide6.QtCore import QSettings
    from moyle_steg.window import MainWindow

    window = MainWindow(settings=QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat))
    qtbot.addWidget(window)
    window.set_reduce_motion(True)
    window.show()
    return window


def test_dropdown_capture_uses_actual_visible_popup_without_system_animation(qapp, qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from moyle_steg.diagnostics import _capture_dropdown

    window = _dropdown_window(qtbot, tmp_path)
    combo = window.language_combo
    show_popup = combo.showPopup
    effect = Qt.UIEffect.UI_AnimateCombo
    previous = qapp.isEffectEnabled(effect)
    observed = []

    def show():
        observed.append(qapp.isEffectEnabled(effect))
        show_popup()

    monkeypatch.setattr(combo, 'showPopup', show)
    metrics = _capture_dropdown(qapp, window, combo, tmp_path / 'popup.png')
    assert observed == [False]
    assert qapp.isEffectEnabled(effect) == previous
    assert metrics['capture_source'] == 'visible_popup_window'
    assert metrics['edge_background_ratio'] > .95
    assert metrics['popup_visible'] is True
    assert metrics['popup_exposed'] is True
    assert metrics['system_popup_animation'] is False
    assert metrics['background_ratio'] > 0.6
    assert metrics['text_pixels'] > 15
    assert metrics['opaque_probe'] is True
    assert not combo.view().isVisible()


def test_dropdown_capture_rejects_dark_shell_even_when_rows_are_readable(qapp, qtbot, tmp_path):
    from moyle_steg.diagnostics import _capture_dropdown

    window = _dropdown_window(qtbot, tmp_path)
    window.set_theme('blossom')
    combo = window.language_combo
    popup = combo.view().window()
    popup.setObjectName('broken_popup')
    popup.setStyleSheet('QFrame#broken_popup { background: #303030; border: none; }')
    with pytest.raises(AssertionError, match='Dropdown.*(edge|margin|shell)'):
        _capture_dropdown(qapp, window, combo, tmp_path / 'dark-shell.png')
    assert not combo.view().isVisible()


def test_dropdown_capture_rejects_dismissed_popup_with_context_and_restores_effect(qapp, qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from moyle_steg.diagnostics import _capture_dropdown

    window = _dropdown_window(qtbot, tmp_path)
    combo = window.language_combo
    show_popup = combo.showPopup
    previous = qapp.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo)
    calls = []

    def dismiss():
        calls.append('show')
        show_popup()
        combo.hidePopup()

    monkeypatch.setattr(combo, 'showPopup', dismiss)
    with pytest.raises(TimeoutError, match='Dropdown popup unavailable') as failure:
        _capture_dropdown(qapp, window, combo, tmp_path / 'interrupted-language.png')
    assert calls == ['show']  # No repeated attempts to outlast external input.
    assert 'interrupted-language.png' in str(failure.value)
    assert 'popup_visible' in str(failure.value)
    assert 'Hide' in str(failure.value)
    assert not (tmp_path / 'interrupted-language.png').exists()
    assert qapp.isEffectEnabled(Qt.UIEffect.UI_AnimateCombo) == previous


def test_result_layout_measurement_rejects_clipping_by_parent_even_inside_window(qapp, qtbot, tmp_path):
    from PySide6.QtCore import QPoint, QRect
    from moyle_steg.diagnostics import _measure_ancestor_bounds

    window = _dropdown_window(qtbot, tmp_path)
    qtbot.wait(20)
    header_container = window.theme_combo.parentWidget()
    header_container.setFixedHeight(0)
    qapp.processEvents()
    assert window.rect().contains(QRect(window.theme_combo.mapTo(window, QPoint()), window.theme_combo.size()))
    with pytest.raises(AssertionError, match='parent clips'):
        _measure_ancestor_bounds(qapp, window)


def test_runtime_self_test_produces_bilingual_render_and_real_roundtrip_report(qapp, tmp_path, monkeypatch):
    from moyle_steg.diagnostics import self_test
    from moyle_steg import window as window_module

    # Match main.py and the frozen executable, independently of OS defaults.
    qapp.setStyle("Fusion")

    clicked = []
    original_window = window_module.MainWindow

    class ObservedWindow(original_window):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            for page, form in self.forms.items():
                form["run"].clicked.connect(lambda checked=False, page=page: clicked.append(page))

    monkeypatch.setattr(window_module, "MainWindow", ObservedWindow)

    report = tmp_path / "diagnostics.json"
    exit_code = self_test(qapp, report)
    result = json.loads(report.read_text(encoding="utf-8"))
    assert exit_code == 0, result.get("error", result)
    assert result["status"] == "passed"
    assert {"png_password_roundtrip", "saes_key_roundtrip", "wrong_password_rejected",
            "ui_zh_CN", "ui_en_US"} <= set(result["checks"])
    assert {"ui_png_original_filename_roundtrip", "ui_saes_original_filename_roundtrip"} <= set(result["checks"])
    assert {"ui_exact_preflight", "ui_verify_png", "ui_verify_saes", "ui_safe_cancel"} <= set(result["checks"])
    assert {"verify_digest_association_png", "verify_digest_association_saes"} <= set(result["checks"])
    for kind in ("png", "saes"):
        association = result["verification_association"][kind]
        assert association["via"] == "service"
        assert association["mutation_triggered"] is True
        assert association["mutation_stage"] == "hash:0"
        assert association["same_size"] is True
        assert association["mtime_restored"] is True
        assert association["outcome"] in {"captured_original", "input_changed"}
    assert clicked == ["hide", "extract", "extract", "extract", "extract", "keygen", "crypt", "crypt", "verify", "verify", "crypt"]
    assert {'ui_recovery_pixel_budget_rejected', 'ui_recovery_same_png_after_budget_increase'} <= set(result['checks'])
    recovery = result['recovery_budget']
    assert recovery['via'] == 'ui'
    assert recovery['low_limit_pixels'] == 1024
    assert recovery['raised_limit_pixels'] == 50_000_000
    assert recovery['low_limit_rejected'] is True
    assert recovery['confirmation_used'] is True
    assert recovery['same_png_unchanged'] is True
    assert recovery['restored_bytes_equal'] is True
    assert recovery['input_sha256_before'] == recovery['input_sha256_after']
    for kind in ('png', 'saes'):
        assert f'ui_verified_summary_context_{kind}' in result['checks']
        context = result['verification_context'][kind]
        assert context['via'] == 'ui'
        assert context['summary_has_input_path'] is True
        assert context['summary_has_completion_time'] is True
        assert context['summary_has_capture_scope'] is True
        assert context['completed_at']
        assert f'ui_verify_input_change_invalidates_result_{kind}' in result['checks']
        invalidated = result['verification_input_change'][kind]
        assert invalidated == {'result_cleared': True, 'result_card_hidden': True,
                               'copy_buttons_disabled': True, 'unverified_status': True, 'via': 'ui'}
    for language in ('zh_CN', 'en_US'):
        assert f'ui_compact_large_hide_{language}' in result['checks']
        compact = result['compact_large'][language]
        assert compact['text_size'] == 'large'
        assert 0 < compact['client_width'] <= 900
        assert 0 < compact['client_height'] <= 550
        assert compact['action_visible'] is True
        assert compact['input_edges_reachable'] is True
        assert compact['sidebar_setting_reachable'] is True
        assert compact['horizontal_overflow'] is False
        assert (tmp_path / f'compact-large-{language}.png').stat().st_size > 1000
        assert (tmp_path / f'compact-large-action-{language}.png').stat().st_size > 1000
    measurements = [recovery['refused_layout'], recovery['restored_layout']]
    for kind in ('png', 'saes'):
        measurements.extend((result['verification_context'][kind]['layout'], result['roundtrips'][kind]['layout']))
    for measured in measurements:
        assert measured['header_controls_visible'] is True
        assert measured['current_form_ancestor_bounds'] is True
        assert measured['visible_controls_checked'] > 10
        assert measured['ancestor_rectangles_checked'] > measured['visible_controls_checked']
        assert measured['scroll_viewports_excluded'] is True
    assert result["qt_platform"] == qapp.platformName()
    assert result["dpr"] > 0
    assert result["runtime"] == "source"
    assert result["frozen"] is False
    for format_name, suffix in (("png", ".txt"), ("saes", ".pdf")):
        roundtrip = result["roundtrips"][format_name]
        assert roundtrip["original_filename"] == roundtrip["restored_filename"]
        assert roundtrip["restored_filename"].endswith(suffix)
        assert any(ord(character) > 127 for character in roundtrip["restored_filename"])
        assert roundtrip["bytes_equal"] is True
        assert roundtrip["via"] == "ui"
    for language in ("zh_CN", "en_US"):
        assert result["rendering"][language]["primary"]["text_pixels"] > 25
        for name in ("desktop", "primary", "dropdown-language", "dropdown-credential"):
            assert (tmp_path / f"{name}-{language}.png").stat().st_size > 100
        for name in ("language", "credential"):
            metrics = result["rendering"][language][f"dropdown_{name}"]
            assert metrics["background_ratio"] > 0.6
            assert metrics["text_pixels"] > 15
            assert metrics["opaque_probe"] is True
    from moyle_steg.theme import get_theme
    assert "ui_theme_and_motion_preferences" in result["checks"]
    for theme_id in ("midnight", "blossom", "terminal"):
        theme = get_theme(theme_id)
        assert f"ui_progress_{theme_id}" in result["checks"]
        assert result['progress_rendering'][theme_id] == {
            'animated': True, 'measured_value_unchanged': True,
            'reduce_motion_static': True, 'stopped_when_finished': True}
        assert (tmp_path / f"progress-{theme_id}.png").stat().st_size > 100
        for language in ("zh_CN", "en_US"):
            assert f"theme_{theme_id}_{language}" in result["checks"]
            assert (tmp_path / f"theme-{theme_id}-{language}.png").stat().st_size > 1000
            metrics = result["appearance"][theme_id][language]
            assert metrics["primary"]["theme"] == theme_id
            assert metrics["primary"]["foreground"] == theme.on_accent
            primary = metrics["primary"]
            assert primary["state_source"] == "captured_pixels"
            assert primary["observed_state"] in {"normal", "hover", "pressed"}
            expected_background = {"normal": theme.accent, "hover": theme.accent_hover,
                                   "pressed": theme.accent_pressed}[primary["observed_state"]]
            assert primary["background"] == expected_background
            assert primary["background_ratio"] == primary["state_background_ratios"][primary["observed_state"]]
            assert primary["contrast_ratio"] >= 4.5
            assert metrics["primary"]["background_ratio"] > 0.45
            assert metrics["primary"]["text_pixels"] > 25
            for name in ("language", "credential", "theme"):
                dropdown = metrics[f"dropdown_{name}"]
                assert dropdown["theme"] == theme_id
                assert dropdown["background"] == theme.surface
                assert dropdown["foreground"] == theme.text
                assert dropdown["background_ratio"] > 0.6
                assert dropdown["text_pixels"] > 15
                assert dropdown["opaque_probe"] is True
                assert dropdown['capture_source'] == 'visible_popup_window'
                assert dropdown['edge_background_ratio'] > .95
    for name in ('budget-pixels-rejected', 'budget-png-restored'):
        assert (tmp_path / f'{name}.png').stat().st_size > 1000
    assert (tmp_path / "result-png-original-name.png").stat().st_size > 1000
    assert (tmp_path / "result-saes-original-name.png").stat().st_size > 1000
    assert not list(tmp_path.glob("moyle-diagnostics-*"))
