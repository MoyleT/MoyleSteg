"""Moyle's bilingual native desktop workspace."""
from pathlib import Path
import time
from datetime import datetime

from PySide6.QtCore import Qt, QSettings, QTimer, QUrl, QTranslator, QLibraryInfo, QEvent, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QDesktopServices, QPalette, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QCheckBox, QDoubleSpinBox,
    QScrollArea, QFileDialog, QTextBrowser, QSizePolicy, QGraphicsOpacityEffect,
)

from .i18n import tr, TEXT
from . import __version__
from .theme import THEMES, DEFAULT_THEME, get_theme, build_stylesheet, build_palette
from .widgets import BrandMark, Card, FileField, ImagePreview, PageStack, ActionButton, FruitAccent, WrapTextLabel, line_icon
from .progress import ThemedProgressBar
from .recovery import RecoveryBudgetPanel
from .layout import ResponsiveColumns, fit_window_to_screen


class MainWindow(QMainWindow):
    PAGE_KEYS = ('hide', 'extract', 'crypt', 'verify', 'keygen', 'guide')

    def __init__(self, settings=None):
        super().__init__()
        from .fonts import configure_fonts
        configure_fonts(QApplication.instance())
        self.settings = settings if settings is not None else QSettings('Moyle', 'SteganographyStudio')
        self.language = str(self.settings.value('language', 'zh_CN'))
        if self.language not in ('zh_CN', 'en_US'):
            self.language = 'zh_CN'
        self.theme = get_theme(str(self.settings.value('theme', DEFAULT_THEME)))
        self.theme_id = self.theme.id
        self.reduce_motion = str(self.settings.value('reduce_motion', False)).lower() in ('true', '1')
        self.text_size = str(self.settings.value('text_size', 'standard'))
        if self.text_size not in ('standard', 'large'):
            self.text_size = 'standard'
        self.forms = {}
        self.pages = {}
        self.nav_buttons = {}
        self._bindings = []
        self._file_fields = []
        self._suggestions = {}
        self._output_contexts = {}
        self._output_values = {}
        self._thread = None
        self.busy = False
        self._cancel_requested = False
        self._stage = 'wait'
        self._stage_completed = None
        self._stage_total = None
        self._preflight_result = None
        self._active_operation = None
        self._close_when_finished = False
        self.last_result = None
        self._result_page = None
        self._active_page = None
        self._input_versions = {}
        self._active_input_version = None
        self._first_show = True
        self._feedback_key = 'ready'
        self._feedback_state = ''
        self._error_messages = None
        self._dimensions = None
        self._payload_bytes = None
        self._translator = QTranslator(self)
        self.resize(1220, 820)
        self.setMinimumSize(760, 480)
        self._build_ui()
        self._page_effect = QGraphicsOpacityEffect(self.stack)
        self._page_effect.setOpacity(1)
        self.stack.setGraphicsEffect(self._page_effect)
        self._page_animation = QPropertyAnimation(self._page_effect, b'opacity', self)
        self._page_animation.setDuration(160)
        self._page_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.set_theme(self.theme_id)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(500)
        self._elapsed_timer.timeout.connect(self._render_status)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(180)
        self._preview_timer.timeout.connect(self._refresh_preview)
        self.set_language(self.language)
        self.show_page('hide')
        self._apply_text_metrics()
        fit_window_to_screen(self, preferred_size=QSize(1220, 820))
        self._initial_size = self.size()

    def t(self, key, **values):
        return tr(key, self.language, **values)

    def set_theme(self, theme_id):
        """Remap presentation in place; never rebuild forms or restart a job."""
        self.theme = get_theme(theme_id)
        self.theme_id = self.theme.id
        self.settings.setValue('theme', self.theme_id)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(self.theme_combo.findData(self.theme_id))
        self.theme_combo.blockSignals(False)
        palette = build_palette(self.theme)
        self.setPalette(palette)
        self.setStyleSheet(build_stylesheet(self.theme, text_size=self.text_size))
        popup_palette = QPalette(palette)
        for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window):
            popup_palette.setColor(role, QColor(self.theme.surface))
        popup_palette.setColor(QPalette.ColorRole.Highlight, QColor(self.theme.nav_active))
        popup_palette.setColor(QPalette.ColorRole.HighlightedText, QColor(self.theme.accent))
        # The native popup shell paints its own menu panel outside the view.
        # Style it directly: the main window's sheet does not reliably reach
        # that top-level window, and a palette alone keeps Fusion's menu bevel.
        for combo in self.findChildren(QComboBox):
            combo.setPalette(palette)
            popup = combo.view().window()
            popup.setObjectName('combo_popup')
            popup.setPalette(popup_palette)
            popup.setStyleSheet(
                f'QFrame#combo_popup {{ background: {self.theme.surface}; border: none; }}')
            combo.view().setPalette(popup_palette)
            combo.view().viewport().setPalette(popup_palette)
            combo.view().viewport().setAutoFillBackground(True)
        self.brand_mark.set_theme(self.theme)
        self.preview.set_theme(self.theme)
        for ornament in self.findChildren(FruitAccent):
            ornament.set_theme(self.theme)
            ornament.set_reduce_motion(self.reduce_motion)
        self.progress.set_appearance(self.theme, self.reduce_motion)
        for button in self.findChildren(ActionButton):
            button.set_appearance(self.theme, self.reduce_motion)

        for key, button in self.nav_buttons.items():
            button.setIcon(line_icon(key, self.theme.muted, self.theme.accent, self.theme_id))
        for index, key in enumerate(THEMES):
            self.theme_combo.setItemIcon(index, line_icon(key, get_theme(key).accent))
        self._render_appearance()
        self._render_guide()
        self._sync_caption()

    def set_reduce_motion(self, reduce):
        self.reduce_motion = bool(reduce)
        self.settings.setValue('reduce_motion', self.reduce_motion)
        self.motion_toggle.blockSignals(True)
        self.motion_toggle.setChecked(self.reduce_motion)
        self.motion_toggle.blockSignals(False)
        if self.reduce_motion and hasattr(self, '_page_animation'):
            self._page_animation.stop()
            self._page_effect.setOpacity(1)
        for ornament in self.findChildren(FruitAccent):
            ornament.set_reduce_motion(self.reduce_motion)
        self.progress.set_appearance(self.theme, self.reduce_motion)
        for button in self.findChildren(ActionButton):
            button.set_appearance(self.theme, self.reduce_motion)

    def _render_appearance(self):
        self.theme_combo.setAccessibleName(self.t('appearance'))
        self.theme_combo.setToolTip(self.t('appearance_tip'))
        for index, key in enumerate(THEMES):
            self.theme_combo.setItemText(index, self.t('theme_' + key))
        self.text_size_combo.setAccessibleName(self.t('text_size'))
        for index, key in enumerate(('standard', 'large')):
            self.text_size_combo.setItemText(index, self.t('text_' + key))
        for ornament in self.findChildren(FruitAccent):
            ornament.setAccessibleName(self.t('fruit_accent') if self.theme_id == 'blossom' else '')

    def _render_guide(self):
        self.guide_browser.setHtml(
            f'<style>h2 {{color:{self.theme.accent}; font-size:{19 if self.text_size == "large" else 17}px; margin-top:22px;}} '
            'p {line-height:1.7;}</style>' + self.t('guide_body'))

    def set_text_size(self, mode):
        if mode not in ('standard', 'large'):
            return
        self.text_size = mode
        self.settings.setValue('text_size', mode)
        self.text_size_combo.blockSignals(True)
        self.text_size_combo.setCurrentIndex(1 if mode == 'large' else 0)
        self.text_size_combo.blockSignals(False)
        self.set_theme(self.theme_id)
        self._apply_text_metrics()

    def _apply_text_metrics(self):
        large = self.text_size == 'large'
        self.sidebar_note.setFixedHeight(40 if large else 32)
        self.sidebar_version.setFixedHeight(20 if large else 16)
        self.page_eyebrow.setFixedHeight(24 if large else 20)
        self.theme_combo.setFixedWidth(196 if large else 180)
        self.language_combo.setFixedWidth(140 if large else 126)

    def _sync_caption(self):
        # Keep the system-drawn title bar consistent, without replacing native
        # dragging, window snapping, system buttons, or accessibility behavior.
        import sys
        if sys.platform != 'win32' or not self.isVisible() or QApplication.platformName() != 'windows':
            return
        try:
            import ctypes
            dark = ctypes.c_int(self.theme_id != 'blossom')
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(int(self.winId())), 20, ctypes.byref(dark), ctypes.sizeof(dark))
        except (AttributeError, OSError):
            pass  # Older Windows versions retain their native title bar.

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_caption()
        if self._first_show:
            self._first_show = False
            # Respect an explicit caller/user resize before first show; the
            # normal launch is fitted again once native frame margins exist.
            if self.size() == getattr(self, '_initial_size', self.size()):
                QTimer.singleShot(0, lambda: fit_window_to_screen(self, preferred_size=self.size()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'guide_browser'):
            QTimer.singleShot(0, self._fit_guide)

    def _fit_guide(self):
        if getattr(self, 'current_page', None) == 'guide':
            browser = self.guide_browser
            card_layout = browser.parentWidget().layout()
            browser_item = card_layout.itemAt(card_layout.indexOf(browser))
            # Measure title, card borders/margins and page spacing using the
            # current font. A fixed 240px floor can exceed the entire viewport
            # at the supported 760x480 window size with large text.
            overhead = self.pages['guide'].minimumSizeHint().height() - browser_item.minimumSize().height()
            margins = self.content_layout.contentsMargins()
            available = self.scroll.viewport().height() - overhead - margins.top() - margins.bottom()
            browser.setMinimumHeight(max(browser.minimumSizeHint().height(), available))

    def _bind(self, widget, key, method='setText'):
        self._bindings.append((widget, key, method))
        getattr(widget, method)(self.t(key))
        return widget

    def _label(self, key, role=None):
        label = QLabel()
        label.setWordWrap(True)
        if role:
            label.setProperty('role', role)
        return self._bind(label, key)

    def _build_ui(self):
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 24, 18, 20)
        side.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(4)
        self.brand_mark = BrandMark()
        brand_row.addWidget(self.brand_mark)
        brand = QLabel('MOYLE')
        brand.setObjectName('brand')
        brand_row.addWidget(brand)
        side.addLayout(brand_row)
        subtitle = self._label('studio')
        subtitle.setContentsMargins(6, 0, 0, 0)
        side.addWidget(subtitle)
        side.addSpacing(30)
        nav_group = self._label('nav_workspace', 'muted')
        nav_group.setObjectName('navGroup')
        side.addWidget(nav_group)
        side.addSpacing(6)
        for key in self.PAGE_KEYS:
            if key == 'guide':
                side.addSpacing(14)
            button = QPushButton()
            button.setObjectName('nav_' + key)
            button.setCheckable(True)
            button.setIconSize(QSize(20, 20))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
            self.nav_buttons[key] = button
            side.addWidget(button)
        side.addStretch()
        self.motion_toggle = self._bind(QCheckBox(), 'reduce_motion')
        self.motion_toggle.setObjectName('motion_toggle')
        self.motion_toggle.setChecked(self.reduce_motion)
        self.motion_toggle.toggled.connect(self.set_reduce_motion)
        self._bind(self.motion_toggle, 'reduce_motion_tip', 'setToolTip')
        side.addWidget(self.motion_toggle)
        side.addWidget(self._label('text_size', 'fieldLabel'))
        self.text_size_combo = QComboBox()
        self.text_size_combo.setObjectName('text_size_selector')
        self.text_size_combo.addItem('', 'standard')
        self.text_size_combo.addItem('', 'large')
        self.text_size_combo.setCurrentIndex(1 if self.text_size == 'large' else 0)
        self.text_size_combo.currentIndexChanged.connect(lambda: self.set_text_size(self.text_size_combo.currentData()))
        side.addWidget(self.text_size_combo)
        side.addSpacing(16)
        note = self._label('sidebar_note')
        note.setObjectName('sidebarCaption')
        # Reserve two caption lines in every theme. Consolas has different
        # native Windows metrics; switching styles must not move controls.
        note.setFixedHeight(32)
        self.sidebar_note = note
        side.addWidget(note)
        side.addSpacing(12)
        version = QLabel(f'AES-256-GCM   ·   {__version__}')
        version.setObjectName('sidebarCaption')
        version.setFixedHeight(16)
        self.sidebar_version = version
        side.addWidget(version)
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setFixedWidth(212)
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar_scroll.setWidget(sidebar)
        root_layout.addWidget(self.sidebar_scroll)

        workspace = QWidget()
        workspace.setObjectName('workspace')
        right = QVBoxLayout(workspace)
        right.setContentsMargins(28, 18, 24, 14)
        right.setSpacing(10)
        top = ResponsiveColumns(breakpoint=600, spacing=8)
        offline_badge = self._label('local_badge', 'muted')
        offline_badge.setObjectName('offlineBadge')
        offline_badge.setWordWrap(False)
        top.addWidget(offline_badge, 1)
        selectors = QHBoxLayout()
        selectors.setContentsMargins(0, 0, 0, 0)
        selectors.addStretch()
        self.theme_combo = QComboBox()
        self.theme_combo.setObjectName('theme_selector')
        self.theme_combo.setFixedWidth(180)
        self.theme_combo.setIconSize(QSize(18, 18))
        for theme_id in THEMES:
            self.theme_combo.addItem('', theme_id)
        self.theme_combo.currentIndexChanged.connect(lambda: self.set_theme(self.theme_combo.currentData()))
        selectors.addWidget(self.theme_combo)
        self.language_combo = QComboBox()
        self.language_combo.setObjectName('language_selector')
        self.language_combo.setAccessibleName('Language / 语言')
        self.language_combo.addItem('简体中文', 'zh_CN')
        self.language_combo.addItem('English', 'en_US')
        self.language_combo.setFixedWidth(126)
        self.language_combo.currentIndexChanged.connect(lambda: self.set_language(self.language_combo.currentData()))
        selectors.addWidget(self.language_combo)
        top.addLayout(selectors, 0)
        right.addWidget(top)
        self.page_eyebrow = QLabel()
        self.page_eyebrow.setObjectName('pageEyebrow')
        self.page_eyebrow.setContentsMargins(0, 6, 0, 0)
        self.page_eyebrow.setFixedHeight(20)
        right.addWidget(self.page_eyebrow)
        self.page_title = QLabel()
        self.page_title.setObjectName('pageTitle')
        self.page_title.setWordWrap(True)
        right.addWidget(self.page_title)
        self.page_description = QLabel()
        self.page_description.setProperty('role', 'description')
        self.page_description.setWordWrap(True)
        right.addWidget(self.page_description)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 0, 8, 8)
        self.content_layout.setSpacing(12)
        self.stack = PageStack()
        self.stack.setObjectName('pages')
        self.content_layout.addWidget(self.stack)
        for key in self.PAGE_KEYS:
            page = self._make_page(key)
            self.pages[key] = page
            self.stack.addWidget(page)
        self._build_result()
        self.content_layout.addStretch()
        self.scroll.setWidget(content)
        right.addWidget(self.scroll, 1)
        self.progress = ThemedProgressBar()
        self.progress.setObjectName('busy_progress')
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.progress, 1)
        self.cancel_button = self._bind(QPushButton(), 'cancel')
        self.cancel_button.setObjectName('cancel_operation')
        self.cancel_button.clicked.connect(self.cancel_operation)
        self.cancel_button.hide()
        progress_row.addWidget(self.cancel_button)
        right.addLayout(progress_row)
        self.status_label = QLabel()
        self.status_label.setObjectName('status')
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right.addWidget(self.status_label)
        root_layout.addWidget(workspace, 1)

    def _card(self, layout, title):
        card = Card()
        card.body.addWidget(self._label(title, 'sectionTitle'))
        layout.addWidget(card)
        return card.body

    def _file(self, layout, page, name, label, filter_key='all_filter', save=False):
        field = FileField(page + '_' + name, save=save)
        self._bind(field.label, label)
        self._bind(field.browse, 'browse')
        self._bind(field.edit, 'save_hint' if save else 'path_hint', 'setPlaceholderText')
        field.browse_requested.connect(lambda: self._browse(field, label, filter_key))
        self._file_fields.append((field, label))
        layout.addWidget(field)
        self.forms[page][name] = field
        return field

    def _make_page(self, key):
        page = QWidget()
        page.setObjectName('page_' + key)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        if key == 'guide':
            card = self._card(layout, 'guide')
            self.guide_browser = QTextBrowser()
            self.guide_browser.setObjectName('guide_text')
            self.guide_browser.setMinimumHeight(380)
            self.guide_browser.setOpenExternalLinks(False)
            card.addWidget(self.guide_browser)
            return page
        form = self.forms[key] = {}
        if key == 'hide':
            top = ResponsiveColumns(breakpoint=720)
            left = QVBoxLayout()
            left.setContentsMargins(0, 0, 0, 0)
            files = self._card(left, 'files_card')
            cover = self._file(files, key, 'cover', 'cover', 'images_filter')
            payload = self._file(files, key, 'input', 'payload')
            files.addWidget(self._label('transport_note', 'muted'))
            form['preflight'] = self._bind(QPushButton(), 'run_preflight')
            form['preflight'].setObjectName('hide_preflight')
            form['preflight'].clicked.connect(lambda: self.start_operation('hide', preflight=True))
            files.addWidget(form['preflight'])
            files.addWidget(self._label('preflight_order', 'muted'))
            top.addLayout(left, 1)
            preview_card = Card(kind='preview')
            preview_card.setMinimumWidth(300)
            preview_heading = QHBoxLayout()
            preview_heading.addWidget(self._label('preview', 'sectionTitle'))
            preview_heading.addStretch()
            self.fruit_accent = FruitAccent()
            preview_heading.addWidget(self.fruit_accent)
            preview_card.body.addLayout(preview_heading)
            self.preview = ImagePreview()
            self.preview.setMaximumWidth(155)
            preview_row = QHBoxLayout()
            preview_row.setSpacing(14)
            preview_row.addWidget(self.preview, 1)
            self.preview_details = QLabel()
            self.preview_details.setWordWrap(True)
            self.preview_details.setProperty('role', 'muted')
            preview_row.addWidget(self.preview_details, 1)
            preview_card.body.addLayout(preview_row)
            capacity_hint = self._label('capacity_short', 'muted')
            self._bind(capacity_hint, 'capacity_note', 'setToolTip')
            preview_card.body.addWidget(capacity_hint)
            self.preflight_label = self._label('preflight_unchecked', 'muted')
            preview_card.body.addWidget(self.preflight_label)
            top.addWidget(preview_card, 1)
            layout.addWidget(top)
            cover.path_changed.connect(lambda: self._preview_timer.start())
            payload.path_changed.connect(lambda: self._preview_timer.start())
            cover.path_changed.connect(self._invalidate_preflight)
            payload.path_changed.connect(self._invalidate_preflight)
        elif key in ('extract', 'crypt', 'verify'):
            files = self._card(layout, 'files_card')
            if key == 'crypt':
                mode_label = self._label('mode', 'fieldLabel')
                files.addWidget(mode_label)
                form['mode'] = QComboBox()
                form['mode'].setObjectName('crypt_mode')
                form['mode'].addItems(['', ''])
                mode_label.setBuddy(form['mode'])
                files.addWidget(form['mode'])
                form['mode'].currentIndexChanged.connect(lambda: self._mode_changed())
            self._file(files, key, 'input', 'stego_input' if key == 'extract' else ('verify_input' if key == 'verify' else 'input'),
                       'png_filter' if key == 'extract' else ('verify_filter' if key == 'verify' else 'all_filter'))
            form['budget'] = RecoveryBudgetPanel()
            files.addWidget(form['budget'])
        if 'input' in form:
            self._input_versions[key] = 0
            form['input'].path_changed.connect(lambda path, page=key: self._input_changed(page))
        # Adjacent decisions share a row in the workspace; each group has
        # its own reading order and the scroll area still handles long results.
        output_layout = layout
        if key in ('hide', 'extract', 'crypt', 'verify'):
            decisions = ResponsiveColumns(breakpoint=720)
            protection_layout, output_layout = QVBoxLayout(), QVBoxLayout()
            for column in (protection_layout, output_layout):
                column.setSpacing(0)
                column.setContentsMargins(0, 0, 0, 0)
                decisions.addLayout(column, 1)
            self._credentials(protection_layout, key)
            protection_layout.addStretch()
            layout.addWidget(decisions)
        if key == 'verify':
            body = self._card(output_layout, 'verify')
            body.addWidget(self._label('verify_note', 'description'))
            row = QHBoxLayout()
            row.addStretch()
            form['run'] = self._bind(ActionButton(), 'run_verify')
            form['run'].setObjectName('verify_run')
            form['run'].setProperty('role', 'primary')
            form['run'].clicked.connect(lambda: self.start_operation('verify'))
            row.addWidget(form['run'])
            body.addLayout(row)
            output_layout.addStretch()
            layout.addStretch()
            return page
        output = self._card(output_layout, 'key_card' if key == 'keygen' else 'output_card')
        if key in ('extract', 'crypt'):
            form['original_name'] = self._bind(QCheckBox(), 'restore_original_name')
            form['original_name'].setObjectName(key + '_original_name')
            form['original_name'].setChecked(True)
            output.addWidget(form['original_name'])
        self._file(output, key, 'output', 'output_png' if key == 'hide' else ('output_key' if key == 'keygen' else 'output'), 'png_filter' if key == 'hide' else ('key_filter' if key == 'keygen' else 'all_filter'), save=True)
        if key in ('extract', 'crypt'):
            form['restore_hint'] = self._label('restore_name_hint', 'muted')
            output.addWidget(form['restore_hint'])
            form['original_name'].toggled.connect(lambda checked, page=key: self._output_mode_changed(page))
            self._output_mode_changed(key)
        if key == 'keygen':
            output.addWidget(self._label('key_hint', 'description'))
        if key == 'hide':
            form['resize'] = self._bind(QCheckBox(), 'resize')
            form['resize'].setObjectName('hide_auto_resize')
            output.addWidget(form['resize'])
            fill_row = QHBoxLayout()
            fill_label = self._label('fill', 'fieldLabel')
            fill_row.addWidget(fill_label)
            fill_row.addStretch()
            form['fill'] = QDoubleSpinBox()
            form['fill'].setObjectName('hide_max_fill')
            form['fill'].setRange(5, 100)
            form['fill'].setDecimals(0)
            form['fill'].setValue(90)
            form['fill'].setSuffix(' %')
            form['fill'].setEnabled(False)
            self._bind(form['fill'], 'fill_tip', 'setToolTip')
            fill_label.setBuddy(form['fill'])
            fill_row.addWidget(form['fill'])
            output.addLayout(fill_row)
            form['resize'].toggled.connect(form['fill'].setEnabled)
            form['resize'].toggled.connect(self._invalidate_preflight)
            form['fill'].valueChanged.connect(self._invalidate_preflight)
        form['force'] = self._bind(QCheckBox(), 'overwrite')
        form['force'].setObjectName(key + '_overwrite')
        self._bind(form['force'], 'overwrite_tip', 'setToolTip')
        output.addWidget(form['force'])
        action_row = QHBoxLayout()
        if key == 'extract':
            form['inspect'] = self._bind(QPushButton(), 'run_inspect')
            form['inspect'].setObjectName('extract_inspect')
            form['inspect'].clicked.connect(lambda: self.start_operation('extract', inspect=True))
            action_row.addWidget(form['inspect'])
        action_row.addStretch()
        form['run'] = ActionButton()
        form['run'].setObjectName(key + '_run')
        form['run'].setProperty('role', 'primary')
        if key != 'crypt':
            self._bind(form['run'], 'run_' + key)
        form['run'].clicked.connect(lambda checked=False, page=key: self.start_operation(page))
        action_row.addWidget(form['run'])
        output.addLayout(action_row)
        if key in ('hide', 'extract', 'crypt'):
            output_layout.addStretch()
        if key in ('hide', 'extract', 'crypt'):
            form['input'].path_changed.connect(lambda path, page=key: self._suggest_output(page))
        layout.addStretch()
        return page

    def _credentials(self, layout, key):
        form = self.forms[key]
        body = self._card(layout, 'credential_card')
        label = self._label('credential', 'fieldLabel')
        body.addWidget(label)
        form['credential'] = QComboBox()
        form['credential'].setObjectName(key + '_credential_mode')
        form['credential'].addItems(['', ''])
        label.setBuddy(form['credential'])
        body.addWidget(form['credential'])
        password_box = QWidget()
        password_layout = QHBoxLayout(password_box)
        password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.setSpacing(14)
        form['password_box'] = password_box
        for name, text_key in [('password', 'password'), ('confirm', 'confirm')]:
            container = QWidget()
            column = QVBoxLayout(container)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(7)
            label = self._label(text_key, 'fieldLabel')
            column.addWidget(label)
            edit = QLineEdit()
            edit.setObjectName(key + '_' + name)
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._bind(edit, 'password_hint' if name == 'password' else 'confirm_hint', 'setPlaceholderText')
            label.setBuddy(edit)
            column.addWidget(edit)
            form[name] = edit
            form[name + '_box'] = container if name == 'confirm' else password_box
            password_layout.addWidget(container)
        body.addWidget(password_box)
        form['show'] = self._bind(QCheckBox(), 'show_password')
        form['show'].setObjectName(key + '_show_password')
        form['show'].toggled.connect(lambda checked, page=key: self._show_password(page, checked))
        body.addWidget(form['show'])
        self._file(body, key, 'key', 'key_file', 'key_filter')
        body.addWidget(self._label('credential_hint', 'muted'))
        form['credential'].currentIndexChanged.connect(lambda index, page=key: self._credential_changed(page))
        self._credential_changed(key)

    def _credential_changed(self, key):
        form = self.forms[key]
        password_mode = form['credential'].currentIndex() == 0
        form['password_box'].setVisible(password_mode)
        form['show'].setVisible(password_mode)
        form['key'].setVisible(not password_mode)
        encryption = key == 'hide' or (key == 'crypt' and form['mode'].currentIndex() == 0)
        form['confirm_box'].setVisible(password_mode and encryption)

    def _mode_changed(self):
        if 'run' not in self.forms['crypt']:
            return
        self._credential_changed('crypt')
        mode = 'encrypt' if self.forms['crypt']['mode'].currentIndex() == 0 else 'decrypt'
        self.forms['crypt']['run'].setText(self.t('run_' + mode))
        self._output_mode_changed('crypt')
        if getattr(self, '_crypt_mode', mode) != mode:
            self._input_changed('crypt')
        self._crypt_mode = mode
        self._update_budget('crypt')

    def _update_budget(self, page):
        form = self.forms[page]
        if 'budget' not in form:
            return
        restoring = page != 'crypt' or form['mode'].currentIndex() == 1
        form['budget'].setVisible(restoring)
        operation = 'decrypt' if page == 'crypt' else ('inspect' if page == 'extract' else 'verify')
        form['budget'].set_input(form['input'].edit.text().strip() if restoring else '', operation)

    def _input_changed(self, page):
        self._input_versions[page] = self._input_versions.get(page, 0) + 1
        self._update_budget(page)
        if self._result_page == page:
            self.last_result = None
            self._result_page = None
            self.result_card.hide()
            self.copy_button.setEnabled(False)
            self.copy_input_button.setEnabled(False)
        if not self.busy and getattr(self, 'current_page', None) == page:
            key = 'input_unverified' if page in ('extract', 'verify') or (page == 'crypt' and self.forms[page]['mode'].currentIndex() == 1) else 'input_changed_ready'
            self._set_feedback(key)

    def _automatic_restore(self, key):
        form = self.forms[key]
        restoring = key == 'extract' or (key == 'crypt' and form['mode'].currentIndex() == 1)
        return restoring and form['original_name'].isChecked()

    def _output_mode_changed(self, key):
        form = self.forms[key]
        restoring = key == 'extract' or form['mode'].currentIndex() == 1
        automatic = self._automatic_restore(key)
        context = ('restore_auto' if automatic else 'restore_manual') if restoring else 'encrypt'
        previous = self._output_contexts.get(key)
        target = form['output'].edit
        if previous != context:
            if previous is not None:
                self._output_values[(key, previous)] = (target.text(), self._suggestions.get(key))
            value, suggestion = self._output_values.get((key, context), ('', None))
            target.setText(value)
            self._suggestions[key] = suggestion
            self._output_contexts[key] = context
        form['original_name'].setVisible(restoring)
        form['restore_hint'].setVisible(restoring)
        form['restore_hint'].setText(self.t('restore_name_hint' if automatic else 'restore_custom_hint'))
        field = form['output']
        field.directory = automatic
        label_key = 'output_directory' if automatic else 'output'
        field.label.setText(self.t(label_key))
        field.edit.setPlaceholderText(self.t('directory_hint' if automatic else 'save_hint'))
        field.edit.setAccessibleName(self.t(label_key))
        field.browse.setAccessibleName(self.t('browse') + ' ' + self.t(label_key))
        self._suggest_output(key)

    def _show_password(self, key, checked):
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.forms[key]['password'].setEchoMode(mode)
        self.forms[key]['confirm'].setEchoMode(mode)

    def _suggest_output(self, key):
        form = self.forms[key]
        source = form['input'].edit.text().strip()
        if not source:
            return
        target = form['output'].edit
        if target.text() and target.text() != self._suggestions.get(key):
            return
        path = Path(source)
        if key == 'hide':
            suggestion = path.with_name(path.stem + '_hidden.png')
        elif self._automatic_restore(key):
            suffix = '_recovered' if key == 'extract' else '_decrypted'
            suggestion = path.with_name(path.stem + suffix)
        elif key == 'crypt' and form['mode'].currentIndex() == 0:
            suggestion = path.with_name(path.name + '.saes')
        else:
            # A custom name must be explicit. The authenticated original name is
            # used automatically only when the user selects folder restoration.
            return
        self._suggestions[key] = str(suggestion)
        target.setText(str(suggestion))

    def _browse(self, field, label_key, filter_key):
        # Finish queued translation events before adding a dialog;
        # otherwise it can reset our folder-selection labels during exec().
        QApplication.sendPostedEvents(None, QEvent.Type.LanguageChange)
        directory = field.directory
        if directory:
            label_key = 'output_directory'
        dialog = QFileDialog(self, self.t(label_key))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.setNameFilter(self.t(filter_key))
        chinese = self.language == 'zh_CN'
        dialog.setLabelText(QFileDialog.DialogLabel.FileName, ('文件夹：' if chinese else 'Folder:') if directory else ('文件名：' if chinese else 'File name:'))
        dialog.setLabelText(QFileDialog.DialogLabel.FileType, '文件类型：' if chinese else 'Files of type:')
        dialog.setLabelText(QFileDialog.DialogLabel.LookIn, '位置：' if chinese else 'Look in:')
        dialog.setLabelText(QFileDialog.DialogLabel.Reject, '取消' if chinese else 'Cancel')
        if directory:
            dialog.setFileMode(QFileDialog.FileMode.Directory)
            dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        elif field.save:
            dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            dialog.setOption(QFileDialog.Option.DontConfirmOverwrite, True)
            if filter_key == 'png_filter':
                dialog.setDefaultSuffix('png')
            elif filter_key == 'key_filter':
                dialog.setDefaultSuffix('stegkey')
        else:
            dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        # Qt resets this label when changing its file/accept mode.
        dialog.setLabelText(QFileDialog.DialogLabel.Accept, ('选择文件夹' if chinese else 'Select folder') if directory else (('保存' if chinese else 'Save') if field.save else ('打开' if chinese else 'Open')))
        if directory and field.edit.text():
            location = Path(field.edit.text())
            if not location.is_dir():
                location = location.parent
            dialog.setDirectory(str(location))
        elif field.edit.text():
            dialog.selectFile(field.edit.text())
        if dialog.exec() and dialog.selectedFiles():
            field.edit.setText(dialog.selectedFiles()[0])

    def show_page(self, key):
        changed = getattr(self, 'current_page', None) != key
        self.current_page = key
        self.stack.setCurrentWidget(self.pages[key])
        # Only the current page contributes its minimum height to the scroll area.
        for page_key, page in self.pages.items():
            page.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred if page_key == key else QSizePolicy.Policy.Ignored)
        for page_key, button in self.nav_buttons.items():
            button.setChecked(page_key == key)
        self.page_title.setText(self.t(key + '_title'))
        self.page_description.setText(self.t(key + '_desc'))
        self.page_eyebrow.setText(f'{self.PAGE_KEYS.index(key) + 1:02d}  /  {self.t("nav_workspace")}')
        self.stack.adjustSize()
        self.scroll.verticalScrollBar().setValue(0)
        if key == 'guide':
            QTimer.singleShot(0, self._fit_guide)
        self._page_animation.stop()
        if changed and self.isVisible() and not self.reduce_motion:
            self._page_effect.setOpacity(0.7)
            self._page_animation.setStartValue(0.7)
            self._page_animation.setEndValue(1.0)
            self._page_animation.start()
        else:
            self._page_effect.setOpacity(1)

    def set_language(self, code):
        if code not in ('zh_CN', 'en_US'):
            return
        self.language = code
        self.settings.setValue('language', code)
        app = QApplication.instance()
        app.removeTranslator(self._translator)
        if code == 'zh_CN':
            self._translator.load('qtbase_zh_CN', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
            app.installTranslator(self._translator)
        self.setWindowTitle(self.t('app_title'))
        self.language_combo.blockSignals(True)
        self.language_combo.setCurrentIndex(0 if code == 'zh_CN' else 1)
        self.language_combo.blockSignals(False)
        for widget, key, method in self._bindings:
            getattr(widget, method)(self.t(key))
        for key, button in self.nav_buttons.items():
            button.setText('  ' + self.t(key))
            button.setAccessibleName(self.t(key))
        for field, key in self._file_fields:
            field.edit.setAccessibleName(self.t(key))
            field.browse.setAccessibleName(self.t('browse') + ' ' + self.t(key))
        for key in ('hide', 'extract', 'crypt', 'verify'):
            form = self.forms[key]
            form['credential'].setItemText(0, self.t('password'))
            form['credential'].setItemText(1, self.t('key_file'))
            form['password'].setAccessibleName(self.t('password'))
            form['confirm'].setAccessibleName(self.t('confirm'))
            if 'budget' in form:
                form['budget'].set_language(code)
        self.forms['crypt']['mode'].setItemText(0, self.t('encrypt'))
        self.forms['crypt']['mode'].setItemText(1, self.t('decrypt'))
        self._mode_changed()
        self._output_mode_changed('extract')
        self._render_appearance()
        self._render_guide()
        if hasattr(self, 'current_page'):
            self.page_title.setText(self.t(self.current_page + '_title'))
            self.page_description.setText(self.t(self.current_page + '_desc'))
            self.page_eyebrow.setText(f'{self.PAGE_KEYS.index(self.current_page) + 1:02d}  /  {self.t("nav_workspace")}')
        self._render_preview()
        self._render_preflight()
        self._render_status()
        self._render_result()

    def _refresh_preview(self):
        self._dimensions = self.preview.load_path(self.forms['hide']['cover'].edit.text().strip())
        try:
            payload = Path(self.forms['hide']['input'].edit.text().strip())
            self._payload_bytes = payload.stat().st_size if payload.is_file() else None
        except OSError:
            self._payload_bytes = None
        self._render_preview()

    @staticmethod
    def _size(value):
        value = float(value)
        for unit in ('B', 'KiB', 'MiB', 'GiB'):
            if value < 1024 or unit == 'GiB':
                return f'{value:,.0f} {unit}' if unit == 'B' else f'{value:,.2f} {unit}'
            value /= 1024

    def _render_preview(self):
        if self.preview.state:
            self.preview.setText(self.t(self.preview.state))
        dimensions = '—'
        capacity = '—'
        if self._dimensions:
            width, height = self._dimensions
            dimensions = f'{width:,} × {height:,} px'
            capacity = self._size(width * height * 3 // 8)
        payload = self._size(self._payload_bytes) if self._payload_bytes is not None else '—'
        self.preview_details.setText(f"{self.t('dimensions')}  {dimensions}\n{self.t('capacity_label')}  {capacity}\n{self.t('payload_size')}  {payload}")

    def _invalidate_preflight(self, *unused):
        self._preflight_result = None
        self._render_preflight()
        if self.last_result is not None and self.last_result.operation == 'preflight':
            self.last_result = None
            self.result_card.hide()

    def _render_preflight(self):
        if self._preflight_result is None:
            self.preflight_label.setText(self.t('preflight_unchecked'))
            return
        values = self._preflight_result.details
        summary = self.t('preflight_fits' if values['fits'] == 'yes' else 'preflight_no_fit',
                         required=self._size(values['ciphertext_bytes']), capacity=self._size(values['capacity']))
        resources = self.t('preflight_resources', width=values['width'], height=values['height'],
                           memory=self._size(values['estimated_peak_bytes']), level=self.t(values['resource_level']))
        reason = self.t('reason_' + values['reason']) if values.get('reason') else ''
        self.preflight_label.setText('\n\n'.join(part for part in (summary, resources, reason, self.t('preflight_hint')) if part))

    def _set_feedback(self, key, state=''):
        self._feedback_key = key
        self._feedback_state = state
        self._error_messages = None
        self._render_status()

    def _render_status(self):
        if self.busy and self._cancel_requested:
            text = self.t('cancel_requested')
        elif self.busy and self._feedback_key != 'close_busy':
            stage = self.t('stage_' + self._stage.split('.')[-1])
            if stage.startswith('stage_'):
                stage = self.t('stage_unknown')
            if self._stage.startswith('verify.'):
                stage = self.t('stage_nested', stage=stage)
            seconds = int(time.monotonic() - self._started_at)
            if self._stage_total is not None and self._stage_total > 0 and self._stage_completed is not None:
                percent = max(0, min(100, int(100 * self._stage_completed / self._stage_total)))
                text = self.t('stage_progress', stage=stage, percent=percent, seconds=seconds)
            else:
                text = self.t('stage_indeterminate', stage=stage, seconds=seconds)
        elif self._error_messages:
            text = self._error_messages.get(self.language, self.t('failed'))
        else:
            text = self.t(self._feedback_key)
        self.status_label.setText(text)
        self.status_label.setProperty('state', self._feedback_state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def start_operation(self, page_key, inspect=False, preflight=False):
        if self.busy:
            return
        form = self.forms[page_key]
        operation = ('inspect' if inspect else 'extract') if page_key == 'extract' else page_key
        if preflight:
            operation = 'preflight'
        if page_key == 'crypt':
            operation = 'encrypt' if form['mode'].currentIndex() == 0 else 'decrypt'
        checks = []
        if page_key == 'hide':
            checks.append((form['cover'].edit.text().strip(), 'missing_cover'))
        if page_key != 'keygen':
            checks.append((form['input'].edit.text().strip(), 'missing_input'))
        automatic = self._automatic_restore(page_key) if page_key in ('extract', 'crypt') else False
        readonly = inspect or preflight or page_key == 'verify'
        if not readonly:
            checks.append((form['output'].edit.text().strip(), 'missing_directory' if automatic else 'missing_output'))
        for value, key in checks:
            if not value:
                self._set_feedback(key, 'error')
                return
        recovery = operation in ('extract', 'inspect', 'decrypt', 'verify')
        if recovery:
            panel = form['budget']
            problem = panel.validate()
            if problem:
                self._set_feedback(problem, 'error')
                QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(panel.confirm, 0, 12))
                return
        credential_mode = 'password'
        if page_key != 'keygen' and not preflight:
            credential_mode = 'password' if form['credential'].currentIndex() == 0 else 'key_file'
            if credential_mode == 'password':
                if not form['password'].text():
                    self._set_feedback('missing_password', 'error')
                    return
                if operation in ('hide', 'encrypt') and form['password'].text() != form['confirm'].text():
                    self._set_feedback('password_mismatch', 'error')
                    return
            elif not form['key'].edit.text().strip():
                self._set_feedback('missing_key', 'error')
                return
        from .service import OperationRequest
        from .worker import JobThread
        def path(name):
            value = form[name].edit.text().strip() if name in form else ''
            # Preserve the explicit destination so the service can reject
            # relative outputs instead of silently writing into the cwd.
            if name == 'output':
                return value
            return str(Path(value).expanduser().absolute()) if value else ''
        request = OperationRequest(
            operation=operation, input_path=path('input'), output_path='' if readonly or automatic else path('output'),
            output_directory=path('output') if automatic and not readonly else '',
            cover_path=path('cover'), credential_mode=credential_mode,
            password=form['password'].text() if page_key != 'keygen' and not preflight and credential_mode == 'password' else '',
            password_confirm=form['confirm'].text() if operation in ('hide', 'encrypt') and credential_mode == 'password' else '',
            key_path=path('key') if credential_mode == 'key_file' else '',
            auto_resize=form['resize'].isChecked() if page_key == 'hide' else False,
            max_fill=form['fill'].value() / 100 if page_key == 'hide' else 0.9,
            force=form['force'].isChecked() if 'force' in form and not readonly else False,
            **(form['budget'].limits() if recovery else {}),
        )
        self._started_at = time.monotonic()
        self._active_operation = operation
        self._active_page = page_key
        self._active_input_version = self._input_versions.get(page_key, 0)
        self._stage = 'wait'
        self._stage_completed = self._stage_total = None
        self._cancel_requested = False
        self.busy = True
        self._set_feedback('working')
        self.last_result = None
        self.result_card.hide()
        for key in self.forms:
            self.pages[key].setEnabled(False)
        self.progress.show()
        self.progress.setRange(0, 0)
        self.progress.set_running(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()
        self._elapsed_timer.start()
        self._thread = JobThread(request, language=self.language, parent=self, resource_preview=recovery)
        if recovery:
            self._thread.resource_ready.connect(self._show_recovery_resources)
        self._thread.succeeded.connect(self._succeeded)
        self._thread.failed.connect(self._failed)
        self._thread.progress.connect(self._progress_changed)
        self._thread.cancelled.connect(self._cancelled)
        self._thread.finished.connect(self._finished)
        self._thread.start()

    def _show_recovery_resources(self, info):
        thread = self._thread
        if thread is None or self._active_page is None:
            return
        request = thread.request
        if request is None or self._cancel_requested:
            return
        if self._input_versions.get(self._active_page, 0) == self._active_input_version:
            panel = self.forms[self._active_page]['budget']
            panel.display_resources(info, request.input_path, request.operation)
            self.scroll.ensureWidgetVisible(panel.resources_label, 0, 12)
        QTimer.singleShot(0, thread.acknowledge_resources)

    def _succeeded(self, result):
        if self._active_page is not None and self._input_versions.get(self._active_page, 0) != self._active_input_version:
            self.last_result = None
            self._set_feedback('input_unverified' if result.operation in ('verify', 'inspect', 'extract', 'decrypt') else 'input_changed_ready')
            return
        self.last_result = result
        self._result_page = self._active_page or {'inspect': 'extract', 'preflight': 'hide', 'encrypt': 'crypt', 'decrypt': 'crypt'}.get(result.operation, result.operation)
        self.details_toggle.setChecked(False)
        self.result_text.hide()
        self.copy_button.setEnabled(True)
        self.copy_input_button.setEnabled(True)
        if result.operation == 'preflight':
            self._preflight_result = result
            self._render_preflight()
        self._feedback_key = result.title if result.title in TEXT else result.operation + '_success'
        self._feedback_state = 'success'
        self._error_messages = None
        self._render_result()

    def _progress_changed(self, stage, completed, total):
        self._stage, self._stage_completed, self._stage_total = stage, completed, total
        if total is not None and total > 0 and completed is not None:
            self.progress.setRange(0, 1000)
            self.progress.setValue(max(0, min(1000, int(1000 * completed / total))))
        else:
            self.progress.setRange(0, 0)
        self._render_status()

    def cancel_operation(self):
        if self.busy and self._thread is not None and not self._cancel_requested:
            self._cancel_requested = True
            self.cancel_button.setEnabled(False)
            self._thread.request_cancel()
            self._render_status()

    def _cancelled(self):
        self.last_result = None
        self._feedback_key = 'cancelled'
        self._feedback_state = ''
        self._error_messages = None

    def _failed(self, message):
        self._feedback_key = 'failed'
        self._feedback_state = 'error'
        self._error_messages = getattr(self._thread, 'error_messages', None)
        if not self._error_messages:
            self._error_messages = {self.language: message}

    def _finished(self):
        # Unlock only on QThread.finished, never on its result/error signal.
        self.busy = False
        self._cancel_requested = False
        self._elapsed_timer.stop()
        self.progress.set_running(False)
        self.progress.hide()
        self.cancel_button.hide()
        for key, form in self.forms.items():
            self.pages[key].setEnabled(True)
            if 'password' in form:
                form['password'].clear()
                form['confirm'].clear()
                form['show'].setChecked(False)
            if 'budget' in form:
                form['budget'].confirm.setChecked(False)
        thread = self._thread
        self._thread = None
        self._active_page = None
        self._active_input_version = None
        thread.deleteLater()
        self._render_status()
        if self._close_when_finished:
            self._close_when_finished = False
            QTimer.singleShot(0, self.close)
            return
        if self.last_result:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.result_card, 0, 18))

    def _build_result(self):
        self.result_card = Card(kind='result')
        self.result_card.setObjectName('card')
        result_heading = QHBoxLayout()
        result_heading.addWidget(self._label('result', 'sectionTitle'), 1)
        result_heading.addWidget(FruitAccent(celebrate=True))
        self.result_card.body.addLayout(result_heading)
        self.result_summary = WrapTextLabel()
        self.result_summary.setObjectName('result_summary')
        self.result_card.body.addWidget(self.result_summary)
        self.open_folder_button = self._bind(QPushButton(), 'open_folder')
        self.open_folder_button.setObjectName('open_output_folder')
        self.open_folder_button.clicked.connect(self._open_folder)
        self.result_card.body.addWidget(self.open_folder_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.details_toggle = self._bind(QPushButton(), 'result_details_toggle')
        self.details_toggle.setCheckable(True)
        self.details_toggle.setObjectName('result_details_toggle')
        self.result_card.body.addWidget(self.details_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.result_text = WrapTextLabel()
        self.result_text.setObjectName('result_details')
        self.result_card.body.addWidget(self.result_text)
        self.result_text.hide()
        row = ResponsiveColumns(breakpoint=620, spacing=8)
        self.copy_button = self._bind(QPushButton(), 'copy_payload_sha')
        self.copy_button.setObjectName('copy_sha256')
        self.copy_button.clicked.connect(self._copy_sha)
        row.addWidget(self.copy_button)
        self.copy_input_button = self._bind(QPushButton(), 'copy_input_sha')
        self.copy_input_button.setObjectName('copy_input_sha256')
        self.copy_input_button.clicked.connect(self._copy_input_sha)
        row.addWidget(self.copy_input_button)
        self.result_card.body.addWidget(row)
        row.hide()
        self.details_toggle.toggled.connect(self.result_text.setVisible)
        self.details_toggle.toggled.connect(row.setVisible)
        self.content_layout.addWidget(self.result_card)
        self.result_card.hide()

    def _render_result(self):
        if not self.last_result:
            return
        result = self.last_result
        lines = []
        task = self.t('run_' + result.operation)
        if task == 'run_' + result.operation:
            task = self.t(result.operation)
        status = self.t('result_capture_status') if result.operation in ('verify', 'inspect') else self.t(result.title)
        summary = [self.t('result_task') + '  ·  ' + task, status]
        if result.input_path:
            summary.append(self.t('result_input') + '\n' + result.input_path)
        if result.completed_at:
            completed = datetime.fromisoformat(result.completed_at).astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
            summary.append(self.t('result_completed') + '  ·  ' + completed)
        if result.output_path:
            summary.append(self.t('result_path') + '\n' + result.output_path)
        self.result_summary.setText('\n\n'.join(summary))
        for key, value in result.details.items():
            if key == 'sha256' and 'payload_sha256' in result.details:
                continue
            rendered = str(value)
            if key in ('credential_mode', 'compressed', 'verified', 'algorithm', 'fits', 'exact', 'resource_level'):
                rendered = self.t(rendered)
            if key == 'reason':
                rendered = self.t('reason_' + rendered) if rendered else self.t('reason_none')
            if key == 'container_format':
                rendered = rendered.upper()
            if key == 'fill_ratio':
                try:
                    rendered = f'{float(rendered):.2%}'
                except ValueError:
                    pass
            if key in ('original_size', 'stored_size', 'capacity', 'input_size', 'ciphertext_bytes', 'estimated_peak_bytes'):
                try:
                    rendered = self._size(rendered)
                except ValueError:
                    pass
            lines.append(self.t(key) + '  ·  ' + rendered)
        self.result_text.setText('\n'.join(lines))
        self.open_folder_button.setVisible(bool(result.output_path))
        self.copy_button.setVisible(bool(result.details.get('payload_sha256') or result.details.get('sha256')))
        self.copy_input_button.setVisible(bool(result.details.get('input_sha256')))
        self.result_card.show()

    def _open_folder(self):
        if self.last_result and self.last_result.output_path:
            folder = str(Path(self.last_result.output_path).parent)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                self._set_feedback('open_failed', 'error')

    def _copy_sha(self):
        if self.last_result:
            digest = self.last_result.details.get('payload_sha256', self.last_result.details.get('sha256'))
            if digest:
                QApplication.clipboard().setText(str(digest))
                self._set_feedback('copied_payload', 'success')

    def _copy_input_sha(self):
        if self.last_result and self.last_result.details.get('input_sha256'):
            QApplication.clipboard().setText(str(self.last_result.details['input_sha256']))
            self._set_feedback('copied_input', 'success')

    def closeEvent(self, event):
        if self.busy or (self._thread is not None and self._thread.isRunning()):
            self._close_when_finished = True
            self.cancel_operation()
            event.ignore()
        else:
            QApplication.instance().removeTranslator(self._translator)
            event.accept()
