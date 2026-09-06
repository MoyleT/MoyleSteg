"""Opt-in diagnostics that exercise actual desktop controls with synthetic files."""

import hashlib
import json
import os
import platform
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSettings, QSize, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractSpinBox, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton

from . import __version__


def _wait_until(app, condition, *, timeout=30.0, description="desktop operation"):
    deadline = time.monotonic() + timeout
    while True:
        app.processEvents()
        if condition():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for {description}")
        time.sleep(0.01)


def _save(image, path):
    if image.isNull() or not image.save(str(path)):
        raise OSError(f"Could not save rendered interface: {path.name}")


def _physical_crop(image, logical_rect):
    """Widget geometry is logical; captured pixels may be scaled by DPI."""
    ratio = image.devicePixelRatio()
    rect = QRect(round(logical_rect.x() * ratio), round(logical_rect.y() * ratio),
                 round(logical_rect.width() * ratio), round(logical_rect.height() * ratio))
    if rect.isEmpty() or not image.rect().contains(rect):
        raise AssertionError(f"The diagnostic control {rect} was outside captured surface {image.rect()}")
    return image.copy(rect)


def _measure_ancestor_bounds(app, window):
    """A viewport crop is normal; a form/card compressing its children is not."""
    app.processEvents()
    app.processEvents()
    headers = (window.theme_combo, window.language_combo)
    if any(not control.isVisible() for control in headers):
        raise AssertionError("A header appearance/language control is hidden")
    types = (QAbstractSpinBox, QCheckBox, QComboBox, QLabel, QLineEdit, QPushButton)
    controls = list(headers)
    for area in (window.pages[window.current_page], window.result_card):
        controls.extend(control for control in area.findChildren(QObject)
                        if isinstance(control, types) and control.isVisible())
    viewports = (window.scroll.viewport(), window.sidebar_scroll.viewport())
    checked = 0
    for control in controls:
        if control.width() <= 0 or control.height() <= 0:
            raise AssertionError(f"A visible diagnostic control has zero area: {control.objectName()}")
        child, parent = control, control.parentWidget()
        while parent is not None and parent not in viewports:
            rect = QRect(child.mapTo(parent, QPoint()), child.size())
            if not parent.rect().contains(rect):
                raise AssertionError(
                    f"A parent clips {control.objectName() or control.metaObject().className()}: "
                    f"{child.metaObject().className()} {rect} in "
                    f"{parent.objectName() or parent.metaObject().className()} {parent.rect()}")
            checked += 1
            child, parent = parent, parent.parentWidget()
    return {'header_controls_visible': True, 'current_form_ancestor_bounds': True,
            'visible_controls_checked': len(controls), 'ancestor_rectangles_checked': checked,
            'scroll_viewports_excluded': True}


def _pixels(image):
    converted = image.convertToFormat(image.Format.Format_RGBA8888)
    return Image.frombytes("RGBA", (converted.width(), converted.height()),
                           bytes(converted.bits()), "raw", "RGBA", converted.bytesPerLine())


def _near(pixel, color, tolerance):
    return pixel[3] >= 250 and all(abs(pixel[index] - color[index]) <= tolerance for index in range(3))


def _pixel_data(image):
    getter = getattr(image, "get_flattened_data", None)
    return getter() if getter is not None else image.getdata()


def _rgb(value):
    color = QColor(value)
    return color.red(), color.green(), color.blue()


def _capture_primary(app, window, button, path):
    window.scroll.ensureWidgetVisible(button, 0, 18)
    app.processEvents()
    # A transparent button.grab() hides the actual card behind it. Capture the
    # composed window to test the colors the user really sees.
    surface = window.grab().toImage()
    origin = button.mapTo(window, QPoint(0, 0))
    rendered = _physical_crop(surface, QRect(origin, button.size()))
    _save(rendered, path)
    pixels = _pixels(rendered)
    theme = window.theme
    # The native pointer may change state between painting and observing the
    # widget. Classify this captured image, rather than combining pixels from
    # one moment with underMouse() from another. Exact state transitions are
    # exercised separately by the window-directed input/rendering tests.
    allowed = {"normal": theme.accent, "hover": theme.accent_hover,
               "pressed": theme.accent_pressed}
    ratios = {state: sum(_near(pixel, _rgb(color), 4) for pixel in _pixel_data(pixels))
                    / (pixels.width * pixels.height)
              for state, color in allowed.items()}
    observed_state = max(ratios, key=ratios.get)
    background = allowed[observed_state]
    def luminance(value):
        channels = (component / 255 for component in _rgb(value))
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        return sum(component * weight for component, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    low, high = sorted((luminance(theme.on_accent), luminance(background)))
    contrast = (high + 0.05) / (low + 0.05)
    edge = max(1, round(8 * surface.devicePixelRatio()))
    interior = pixels.crop((edge, edge, pixels.width - edge, pixels.height - edge))
    text_pixels = sum(_near(pixel, _rgb(theme.on_accent), 18) for pixel in _pixel_data(interior))
    metrics = {"theme": theme.id, "background": background, "foreground": theme.on_accent,
               "observed_state": observed_state, "state_source": "captured_pixels",
               "background_ratio": ratios[observed_state], "state_background_ratios": ratios,
               "text_pixels": text_pixels, "contrast_ratio": contrast,
               "dpr": surface.devicePixelRatio()}
    if metrics["background_ratio"] <= 0.45 or text_pixels <= 25 or contrast < 4.5:
        raise AssertionError(f"Primary button lacks its theme fill or readable label: {metrics}")
    return metrics


class _PopupTrace(QObject):
    """Observe only our controls; do not consume input or change popup state."""

    def __init__(self, window, combo, view):
        super().__init__()
        self.watched = {window: "main", combo: "combo", view: "view", view.window(): "popup"}
        self.events = []
        self.started = time.monotonic()

    def eventFilter(self, watched, event):
        if watched in self.watched and event.type() in {
            QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close,
            QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate,
            QEvent.Type.FocusIn, QEvent.Type.FocusOut,
            QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
        }:
            self.events.append({"control": self.watched[watched], "event": event.type().name,
                                "elapsed_ms": round((time.monotonic() - self.started) * 1000)})
            self.events = self.events[-64:]
        return False


def _capture_dropdown(app, window, combo, path):
    view = combo.view()
    popup = view.window()
    trace = _PopupTrace(window, combo, view)
    effect = Qt.UIEffect.UI_AnimateCombo
    previous_effect = app.isEffectEnabled(effect)

    def state():
        handle = popup.windowHandle()
        return {"view_visible": view.isVisible(), "popup_visible": popup.isVisible(),
                "popup_exposed": bool(handle and handle.isExposed()),
                "main_visible": window.isVisible(), "main_active": window.isActiveWindow(),
                "active_popup_matches": app.activePopupWidget() is popup}

    def ready():
        current = state()
        return current["view_visible"] and current["popup_visible"] and current["popup_exposed"]

    def unavailable():
        context = {"capture": path.name, "theme": window.theme_id, "language": window.language,
                   "system_popup_animation": False, **state(), "events": trace.events}
        return TimeoutError("Dropdown popup unavailable: " + json.dumps(context, ensure_ascii=False))

    app.installEventFilter(trace)
    try:
        # This reduced-motion diagnostic measures the real, exposed popup,
        # without Qt's transient QRollEffect surface. It neither positions the
        # system pointer nor retries a popup dismissed by external input.
        app.setEffectEnabled(effect, False)
        window.scroll.ensureWidgetVisible(combo, 0, 18)
        combo.setFocus()
        app.processEvents()
        combo.showPopup()
        try:
            _wait_until(app, ready, timeout=3.0, description="dropdown popup exposure")
        except TimeoutError:
            raise unavailable() from None
        view.setCurrentIndex(combo.model().index(combo.currentIndex(), 0))
        app.processEvents()
        if not ready():
            raise unavailable()
        captured_state = state()
        # Capture the whole exposed popup once. Viewport-only captures omit
        # the independent shell, where native dark top/bottom bands can leak.
        surface = popup.grab().toImage()
        if not ready():
            raise unavailable()
        _save(surface, path)
        row = 1 if combo.currentIndex() == 0 else 0
        # A style can give a virtual row slightly wider than the visible
        # viewport. Verify the actual visible pixels rather than padding the
        # capture with transparent pixels outside that surface.
        row_rect = view.visualRect(combo.model().index(row, 0)).intersected(view.viewport().rect())
        row_rect.translate(view.viewport().mapTo(popup, QPoint(0, 0)))
        rendered = _physical_crop(surface, row_rect)
        pixels = _pixels(rendered)
        theme = window.theme
        edge_ratios = []
        for y in (2, popup.height() - 5):
            edge = _pixels(_physical_crop(surface, QRect(3, y, popup.width() - 6, 3)))
            edge_ratios.append(sum(_near(pixel, _rgb(theme.surface), 4) and pixel[3] == 255
                                   for pixel in _pixel_data(edge)) / (edge.width * edge.height))
        fill = sum(_near(pixel, _rgb(theme.surface), 4) for pixel in _pixel_data(pixels))
        text_pixels = sum(_near(pixel, _rgb(theme.text), 25) for pixel in _pixel_data(pixels))
        probe = pixels.getpixel((max(0, pixels.width - 8), pixels.height // 2))
        metrics = {"theme": theme.id, "background": theme.surface, "foreground": theme.text,
                   "capture_source": "visible_popup_window", "system_popup_animation": False,
                   "popup_visible": captured_state["popup_visible"],
                   "popup_exposed": captured_state["popup_exposed"],
                   "background_ratio": fill / (pixels.width * pixels.height),
                   "edge_background_ratio": min(edge_ratios),
                   "text_pixels": text_pixels, "opaque_probe": probe[3] == 255,
                   "dpr": surface.devicePixelRatio(), "unselected_row": row}
        if metrics["background_ratio"] <= 0.6 or text_pixels <= 15 or not metrics["opaque_probe"]:
            raise AssertionError(f"Dropdown row lacks its opaque theme surface or readable text: {metrics}")
        if metrics["edge_background_ratio"] <= .95:
            raise AssertionError(f"Dropdown shell margins lack their opaque theme surface: {metrics}")
        return metrics
    finally:
        combo.hidePopup()
        app.processEvents()
        app.removeEventFilter(trace)
        app.setEffectEnabled(effect, previous_effect)


def _click_operation(app, window, page, *, expect_success=True):
    window.nav_buttons[page].click()
    button = window.forms[page]["run"]
    window.scroll.ensureWidgetVisible(button, 0, 18)
    app.processEvents()
    if not button.isEnabled():
        raise AssertionError(f"The {page} action is unexpectedly disabled")
    button.click()
    if not window.busy:
        raise AssertionError(f"The {page} button did not start a worker: {window.status_label.text()}")
    _wait_until(app, lambda: not window.busy, description=f"{page} worker completion")
    if not button.isEnabled():
        raise AssertionError(f"The {page} action stayed disabled after completion")
    if expect_success:
        if window.last_result is None:
            raise AssertionError(f"The {page} action failed: {window.status_label.text()}")
        return window.last_result
    if window.last_result is not None or window.status_label.property("state") != "error":
        raise AssertionError("The expected failed operation was not rejected by the UI")
    return None


def _set_credentials(form, password):
    form["credential"].setCurrentIndex(0)
    form["password"].setText(password)
    form["confirm"].setText(password)


def _roundtrip_result(original, directory, result):
    restored = Path(result.output_path)
    if restored != directory / original.name or restored.read_bytes() != original.read_bytes():
        raise AssertionError("Desktop restoration changed the original filename, extension, or bytes")
    return {"original_filename": original.name, "restored_filename": restored.name,
            "bytes_equal": True, "via": "ui", "sha256": hashlib.sha256(restored.read_bytes()).hexdigest()}


def _verification_context(window, result, container):
    """Check the visible summary against the result from the completed worker."""
    if Path(result.input_path).absolute() != container.absolute() or not result.completed_at:
        raise AssertionError("Verification summary has no matching input or completion time")
    try:
        completed = datetime.fromisoformat(result.completed_at)
    except ValueError as error:
        raise AssertionError("Verification summary has an invalid completion time") from error
    if completed.utcoffset() is None:
        raise AssertionError("Verification summary completion time has no timezone")
    displayed_time = completed.astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
    summary = window.result_summary.text()
    checks = {'summary_has_input_path': str(container) in summary,
              'summary_has_completion_time': displayed_time in summary,
              'summary_has_capture_scope': window.t('result_capture_status') in summary}
    if not all(checks.values()):
        raise AssertionError(f"Verification summary lacks its input/time/capture context: {checks}")
    return {'via': 'ui', 'input_filename': container.name,
            'completed_at': result.completed_at, **checks}


def _changed_verification_input(app, window, replacement):
    window.forms['verify']['input'].edit.setText(str(replacement))
    app.processEvents()
    checks = {'result_cleared': window.last_result is None,
              'result_card_hidden': not window.result_card.isVisible(),
              'copy_buttons_disabled': not window.copy_button.isEnabled() and not window.copy_input_button.isEnabled(),
              'unverified_status': window.status_label.text() == window.t('input_unverified')
                                   and window.status_label.property('state') != 'success'}
    if not all(checks.values()):
        raise AssertionError(f"Changing verification input retained an old success result: {checks}")
    return {**checks, 'via': 'ui'}


def _recovery_budget_roundtrip(app, window, original, hidden, work, report_path, password):
    """Use the same synthetic PNG before and after a real UI budget refusal."""
    before = hidden.read_bytes()
    destination = work / 'PNG预算恢复'
    form = window.forms['extract']
    form['input'].edit.setText(str(hidden))
    form['output'].edit.setText(str(destination))
    panel = form['budget']
    panel.toggle.setChecked(True)
    panel.pixels.setValue(1024)
    _set_credentials(form, password)
    _click_operation(app, window, 'extract', expect_success=False)
    message = window.status_label.text()
    if '恢复预算' not in message or '请勿缩放' not in message:
        raise AssertionError("Low pixel budget was not explained as a recovery limit preserving the PNG")
    if destination.exists() or hidden.read_bytes() != before:
        raise AssertionError("A budget refusal wrote recovery output or changed its input PNG")
    refused_layout = _measure_ancestor_bounds(app, window)
    _save(window.grab(), report_path.parent / 'budget-pixels-rejected.png')

    panel.pixels.setValue(50_000_000)
    if not panel.elevated() or not panel.confirm.isVisible():
        raise AssertionError("An elevated recovery budget did not expose its confirmation")
    panel.confirm.setChecked(True)
    _set_credentials(form, password)
    result = _click_operation(app, window, 'extract')
    restored = _roundtrip_result(original, destination, result)
    after = hidden.read_bytes()
    if after != before:
        raise AssertionError("Increasing the recovery budget changed the original PNG")
    restored_layout = _measure_ancestor_bounds(app, window)
    _save(window.grab(), report_path.parent / 'budget-png-restored.png')
    return {'via': 'ui', 'low_limit_pixels': 1024, 'raised_limit_pixels': 50_000_000,
            'low_limit_rejected': True, 'confirmation_used': True, 'same_png_unchanged': True,
            'restored_bytes_equal': restored['bytes_equal'],
            'refused_layout': refused_layout, 'restored_layout': restored_layout,
            'input_sha256_before': hashlib.sha256(before).hexdigest(),
            'input_sha256_after': hashlib.sha256(after).hexdigest()}


def _scroll_control_into_view(app, scroll, control):
    # For line edits, ensureWidgetVisible uses the text cursor rectangle.
    # Exercise the actual vertical scrollbar using the complete control edge.
    scroll.verticalScrollBar().setValue(control.mapTo(scroll.widget(), QPoint()).y())
    app.processEvents()
    rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
    if (not control.isVisible() or not scroll.viewport().rect().contains(rect)
            or scroll.horizontalScrollBar().maximum() != 0):
        raise AssertionError(f"Compact control is not fully reachable: {control.objectName()} {rect}")


def _capture_compact_large(app, window, report_path):
    """Bounded hide-form checks and screenshots, not a full accessibility audit."""
    from .layout import fit_window_to_screen

    window.text_size_combo.setCurrentIndex(1)
    if window.text_size != 'large':
        raise AssertionError("The text-size selector did not apply large text")
    fit_window_to_screen(window, preferred_size=QSize(900, 550))
    captures = {}
    for index, language in enumerate(('zh_CN', 'en_US')):
        window.language_combo.setCurrentIndex(index)
        window.nav_buttons['hide'].click()
        window.scroll.verticalScrollBar().setValue(0)
        window.sidebar_scroll.verticalScrollBar().setValue(0)
        app.processEvents()
        app.processEvents()
        if not window.screen().availableGeometry().contains(window.frameGeometry()):
            raise AssertionError("The compact diagnostic window exceeds its available screen")
        for selector in (window.theme_combo, window.language_combo):
            if not window.rect().contains(QRect(selector.mapTo(window, QPoint()), selector.size())):
                raise AssertionError("A compact header selector is outside the window")
        _save(window.grab(), report_path.parent / f'compact-large-{language}.png')
        form = window.forms['hide']
        for name in ('cover', 'input', 'output'):
            _scroll_control_into_view(app, window.scroll, form[name].edit)
            _scroll_control_into_view(app, window.scroll, form[name].browse)
        for name in ('password', 'confirm', 'preflight', 'run'):
            _scroll_control_into_view(app, window.scroll, form[name])
        _scroll_control_into_view(app, window.sidebar_scroll, window.text_size_combo)
        _save(window.grab(), report_path.parent / f'compact-large-action-{language}.png')
        captures[language] = {'text_size': window.text_size, 'client_width': window.width(),
                              'client_height': window.height(), 'action_visible': True,
                              'input_edges_reachable': True, 'sidebar_setting_reachable': True,
                              'horizontal_overflow': False}
    return captures


def _synthetic_pdf():
    """A valid, blank one-page PDF with no external document dependencies."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << >> >>"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, content in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode() + content + b"\nendobj\n")
    xref = len(data)
    data.extend(b"xref\n0 4\n0000000000 65535 f \n")
    for offset in offsets:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(data)


def _verify_digest_association(kind, container, source, work, *, password="", key_path=""):
    """Exercise the public service in source and frozen runtimes with disposable data."""
    import png_steg_aes256 as core
    from . import service

    original = container.read_bytes()
    original_digest = hashlib.sha256(original).hexdigest()
    payload_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    probe = work / ("digest-association-source." + kind)
    probe.write_bytes(original)
    initial = probe.stat()
    modified = False

    def change_source(stage, completed, total):
        nonlocal modified
        if stage == "hash" and completed == 0 and not modified:
            # Damage the PNG signature or SAES authentication tag in place.
            # Restoring mtime defeats a check based only on length and mtime.
            offset = 0 if kind == "png" else len(original) - 1
            with probe.open("r+b") as stream:
                stream.seek(offset)
                stream.write(bytes([original[offset] ^ 1]))
            os.utime(probe, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            modified = True

    request = service.OperationRequest(
        operation="verify", input_path=str(probe), password=password,
        credential_mode="key_file" if key_path else "password", key_path=str(key_path))
    try:
        result = service.execute(request, control=core.OperationControl(progress=change_source))
    except (ValueError, core.StegError) as error:
        if getattr(error, "code", "") != "input_changed":
            raise AssertionError(f"{kind.upper()} association regression failed unexpectedly") from error
        outcome = "input_changed"
    else:
        if result.output_path or result.details.get("verified") != "yes":
            raise AssertionError(f"{kind.upper()} association verification did not remain read-only")
        if (result.details.get("payload_sha256") != payload_digest
                or result.details.get("input_sha256") != original_digest):
            raise AssertionError(f"{kind.upper()} verification paired digests from different data")
        if result.details["input_sha256"] == hashlib.sha256(probe.read_bytes()).hexdigest():
            raise AssertionError(f"{kind.upper()} verification reported the damaged source digest")
        outcome = "captured_original"
    if not modified:
        raise AssertionError(f"{kind.upper()} association mutation callback did not run")
    final = probe.stat()
    if final.st_size != initial.st_size or final.st_mtime_ns != initial.st_mtime_ns:
        raise AssertionError(f"{kind.upper()} association mutation did not preserve size and mtime")
    if probe.read_bytes() == original or container.read_bytes() != original:
        raise AssertionError(f"{kind.upper()} association mutation did not stay within its disposable copy")
    return {"via": "service", "mutation_triggered": True, "mutation_stage": "hash:0",
            "same_size": True, "mtime_restored": True, "outcome": outcome}


def self_test(app, report_path: Path) -> int:
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    frozen = bool(getattr(sys, "frozen", False))
    report = {"version": __version__, "frozen": frozen,
              "runtime": "frozen" if frozen else "source", "qt_platform": app.platformName(),
              "python": platform.python_version(), "status": "failed", "checks": [],
              "rendering": {}, "appearance": {}, "roundtrips": {}, "verification_association": {},
              "verification_context": {}, "verification_input_change": {}}
    window = None
    try:
        # No user data is used. Settings and disposable files stay under the
        # explicitly selected report directory.
        with tempfile.TemporaryDirectory(prefix="moyle-diagnostics-", dir=report_path.parent) as folder:
            work = Path(folder).resolve()
            if not work.is_relative_to(report_path.parent):
                raise ValueError("Unexpected diagnostics temporary directory")
            from .window import MainWindow
            settings = QSettings(str(work / "diagnostic-settings.ini"), QSettings.Format.IniFormat)
            window = MainWindow(settings=settings)
            window.resize(1220, 820)
            window.show()
            report["dpr"] = window.devicePixelRatioF()
            # Use the real selectors, with reduced motion for reproducible
            # screenshots. The interface tests separately exercise animation.
            window.motion_toggle.setChecked(True)
            if not settings.value("reduce_motion", type=bool):
                raise AssertionError("Reduced-motion preference did not persist")
            for theme_id in ("midnight", "blossom", "terminal"):
                window.theme_combo.setCurrentIndex(window.theme_combo.findData(theme_id))
                if window.theme_id != theme_id or settings.value("theme") != theme_id:
                    raise AssertionError("Theme selector did not apply and persist its palette")
                theme_metrics = report["appearance"][theme_id] = {}
                for index, language in enumerate(("zh_CN", "en_US")):
                    window.language_combo.setCurrentIndex(index)
                    window.nav_buttons["hide"].click()
                    app.processEvents()
                    if window.language != language or window.theme_id != theme_id:
                        raise AssertionError("Language switching changed the selected theme")
                    window.scroll.verticalScrollBar().setValue(0)
                    app.processEvents()
                    surface = window.grab()
                    _save(surface, report_path.parent / f"theme-{theme_id}-{language}.png")
                    if theme_id == "midnight":
                        _save(surface, report_path.parent / f"desktop-{language}.png")
                    metrics = theme_metrics[language] = {}
                    suffix = language if theme_id == "midnight" else f"{theme_id}-{language}"
                    metrics["primary"] = _capture_primary(
                        app, window, window.forms["hide"]["run"], report_path.parent / f"primary-{suffix}.png")
                    report["checks"].append(f"primary_visible_{suffix}")
                    for name, combo in (("language", window.language_combo),
                                        ("credential", window.forms["hide"]["credential"]),
                                        ("theme", window.theme_combo)):
                        metrics[f"dropdown_{name}"] = _capture_dropdown(
                            app, window, combo, report_path.parent / f"dropdown-{name}-{suffix}.png")
                        report["checks"].append(f"dropdown_{name}_{suffix}")
                    if theme_id == "midnight":
                        report["rendering"][language] = metrics
                        report["checks"].append(f"ui_{language}")
                    report["checks"].append(f"theme_{theme_id}_{language}")
            report["checks"].append("ui_theme_and_motion_preferences")
            report["progress_rendering"] = {}
            # Exercise the shipped progress widget with a controlled 50% stage,
            # independently from the real file roundtrips below.
            for theme_id in ("blossom", "terminal", "midnight"):
                window.set_theme(theme_id)
                window.set_reduce_motion(False)
                bar = window.progress
                bar.setRange(0, 1000)
                bar.setValue(500)
                bar.show()
                bar.set_running(True)
                app.processEvents()
                before = bar.grab().toImage()
                _wait_until(app, lambda: bar.grab().toImage() != before,
                            timeout=2, description=theme_id + " progress animation")
                if bar.value() != 500:
                    raise AssertionError("Animation changed the measured progress")
                _save(bar.grab(), report_path.parent / f"progress-{theme_id}.png")
                window.set_reduce_motion(True)
                frozen_frame = bar.grab().toImage()
                end = time.monotonic() + .16
                _wait_until(app, lambda: time.monotonic() >= end, timeout=1)
                if frozen_frame != bar.grab().toImage() or any(timer.isActive() for timer in bar.findChildren(QTimer)):
                    raise AssertionError("Reduce motion did not stop progress decoration")
                bar.set_running(False)
                bar.hide()
                report["progress_rendering"][theme_id] = {
                    "animated": True, "measured_value_unchanged": True,
                    "reduce_motion_static": True, "stopped_when_finished": True}
                report["checks"].append("ui_progress_" + theme_id)
            window.theme_combo.setCurrentIndex(window.theme_combo.findData("midnight"))

            password = "Moyle diagnostic password"
            original = work / "隐写诊断说明.txt"
            original.write_text("Moyle desktop diagnostic / 中文原文件名恢复。\n" * 30, encoding="utf-8")
            cover, hidden = work / "cover.png", work / "hidden.png"
            Image.new("RGBA", (256, 256), (69, 124, 116, 217)).save(cover)
            window.language_combo.setCurrentIndex(0)
            form = window.forms["hide"]
            form["cover"].edit.setText(str(cover))
            form["input"].edit.setText(str(original))
            form["output"].edit.setText(str(hidden))
            window.nav_buttons["hide"].click()
            form["preflight"].click()
            _wait_until(app, lambda: not window.busy, description="exact capacity preflight")
            plan = window.last_result
            if plan is None or plan.operation != "preflight" or plan.details["exact"] != "yes" or plan.details["fits"] != "yes":
                raise AssertionError("Capacity preflight did not produce an exact feasible result")
            if hidden.exists():
                raise AssertionError("Capacity preflight created output")
            report["checks"].append("ui_exact_preflight")
            _set_credentials(form, password)
            _click_operation(app, window, "hide")
            recovered = work / "PNG原名恢复"
            form = window.forms["extract"]
            if not form["original_name"].isChecked():
                raise AssertionError("PNG extraction does not default to original filenames")
            form["input"].edit.setText(str(hidden))
            form["output"].edit.setText(str(recovered))
            _set_credentials(form, password)
            result = _click_operation(app, window, "extract")
            report["roundtrips"]["png"] = _roundtrip_result(original, recovered, result)
            report["roundtrips"]["png"]['layout'] = _measure_ancestor_bounds(app, window)
            report["checks"].extend(("png_password_roundtrip", "ui_png_original_filename_roundtrip"))
            app.processEvents()
            _save(window.grab(), report_path.parent / "result-png-original-name.png")

            bad_output = work / "wrong-password-output"
            form["output"].edit.setText(str(bad_output))
            _set_credentials(form, "Incorrect password")
            _click_operation(app, window, "extract", expect_success=False)
            if bad_output.exists():
                raise AssertionError("Authentication failure created an output destination")
            report["checks"].append("wrong_password_rejected")

            report['recovery_budget'] = _recovery_budget_roundtrip(
                app, window, original, hidden, work, report_path, password)
            report['checks'].extend(('ui_recovery_pixel_budget_rejected',
                                     'ui_recovery_same_png_after_budget_increase'))

            window.language_combo.setCurrentIndex(1)
            key = work / "sample.stegkey"
            window.forms["keygen"]["output"].edit.setText(str(key))
            _click_operation(app, window, "keygen")
            document, encrypted = work / "归档诊断文档.pdf", work / "document.saes"
            document.write_bytes(_synthetic_pdf())
            form = window.forms["crypt"]
            form["mode"].setCurrentIndex(0)
            form["credential"].setCurrentIndex(1)
            form["key"].edit.setText(str(key))
            form["input"].edit.setText(str(document))
            form["output"].edit.setText(str(encrypted))
            _click_operation(app, window, "crypt")
            decrypted = work / "SAES原名恢复"
            form["mode"].setCurrentIndex(1)
            if not form["original_name"].isChecked():
                raise AssertionError("SAES decryption does not default to original filenames")
            form["input"].edit.setText(str(encrypted))
            form["output"].edit.setText(str(decrypted))
            result = _click_operation(app, window, "crypt")
            report["roundtrips"]["saes"] = _roundtrip_result(document, decrypted, result)
            report["roundtrips"]["saes"]['layout'] = _measure_ancestor_bounds(app, window)
            report["checks"].extend(("saes_key_roundtrip", "ui_saes_original_filename_roundtrip"))
            app.processEvents()
            _save(window.grab(), report_path.parent / "result-saes-original-name.png")
            for kind, container, source in (("png", hidden, original), ("saes", encrypted, document)):
                form = window.forms["verify"]
                form["input"].edit.setText(str(container))
                if kind == "png":
                    _set_credentials(form, password)
                else:
                    form["credential"].setCurrentIndex(1)
                    form["key"].edit.setText(str(key))
                before = set(work.rglob("*"))
                result = _click_operation(app, window, "verify")
                if result.output_path or set(work.rglob("*")) != before:
                    raise AssertionError("Read-only verification created a file")
                if result.details["payload_sha256"] != hashlib.sha256(source.read_bytes()).hexdigest():
                    raise AssertionError("Payload digest differs from original file")
                if result.details["input_sha256"] != hashlib.sha256(container.read_bytes()).hexdigest():
                    raise AssertionError("Container digest differs from input file")
                if result.details.get('verified') != 'yes' or not window.result_summary.isVisible():
                    raise AssertionError("Completed verification did not display its authenticated summary")
                report["checks"].append("ui_verify_" + kind)
                report['verification_context'][kind] = _verification_context(window, result, container)
                report['verification_context'][kind]['layout'] = _measure_ancestor_bounds(app, window)
                report['checks'].append('ui_verified_summary_context_' + kind)
                _save(window.grab(), report_path.parent / ("verify-" + kind + ".png"))
                replacement = encrypted if kind == 'png' else hidden
                report['verification_input_change'][kind] = _changed_verification_input(app, window, replacement)
                report['checks'].append('ui_verify_input_change_invalidates_result_' + kind)

            for kind, container, source in (("png", hidden, original), ("saes", encrypted, document)):
                report["verification_association"][kind] = _verify_digest_association(
                    kind, container, source, work, password=password if kind == "png" else "",
                    key_path=key if kind == "saes" else "")
                report["checks"].append("verify_digest_association_" + kind)

            # Cancel through the visible button immediately after starting a
            # password operation, before its commit. No thread is terminated.
            cancel_source, cancel_output = work / "cancel-test.txt", work / "cancel-test.saes"
            cancel_source.write_bytes(b"synthetic cancellation payload\n" * 100000)
            form = window.forms["crypt"]
            form["mode"].setCurrentIndex(0)
            form["input"].edit.setText(str(cancel_source))
            form["output"].edit.setText(str(cancel_output))
            _set_credentials(form, password)
            window.nav_buttons["crypt"].click()
            form["run"].click()
            if not window.busy or not window.cancel_button.isEnabled():
                raise AssertionError("Cancellation control was unavailable")
            window.cancel_button.click()
            _wait_until(app, lambda: not window.busy, description="safe cancellation")
            if cancel_output.exists() or window.last_result is not None or window._feedback_key != "cancelled":
                raise AssertionError("Cancelled task unexpectedly published output or failed")
            if any(form["password"].text() for form in window.forms.values() if "password" in form):
                raise AssertionError("Credentials were retained after cancellation")
            report["checks"].append("ui_safe_cancel")
            report['compact_large'] = _capture_compact_large(app, window, report_path)
            report['checks'].extend('ui_compact_large_hide_' + language for language in ('zh_CN', 'en_US'))
            window.close()
            window.deleteLater()
            window = None
            app.processEvents()
            settings.sync()
            report["status"] = "passed"
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if window is not None:
            # Never explicitly destroy a QThread while it is still running.
            if window.busy:
                try:
                    _wait_until(app, lambda: not window.busy, description="diagnostic worker cleanup")
                except TimeoutError:
                    app._unfinished_diagnostic_window = window
            if not window.busy:
                window.close()
                window.deleteLater()
                app.processEvents()
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
