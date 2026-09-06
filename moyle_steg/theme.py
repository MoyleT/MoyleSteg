"""Native desktop color tokens and complete, switchable Qt styles.

All widget colors come from one immutable theme. Popup palettes are provided
separately because native Qt popup windows do not always inherit the owner.
"""
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QPalette


_ASSETS = Path(__file__).resolve().parent.parent / 'assets'
DEFAULT_THEME = 'midnight'


@dataclass(frozen=True)
class Theme:
    id: str
    bg: str
    surface: str
    surface_alt: str
    input_bg: str
    border: str
    input_border: str
    focus: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_pressed: str
    on_accent: str
    disabled_bg: str
    disabled_text: str
    sidebar: str
    nav_active: str
    secondary: str
    secondary_hover: str
    error: str
    success: str
    preview_bg: str


THEMES = {
    'midnight': Theme(
        id='midnight', bg='#0D1020', surface='#171C33',
        surface_alt='#1E2440', input_bg='#111629', border='#333B5B',
        input_border='#65749E', focus='#E0D4FF',
        text='#EEF0FF', muted='#ACB4D2', accent='#B9A6FF',
        accent_hover='#CDBEFF', accent_pressed='#A28AEF', on_accent='#201637',
        disabled_bg='#252B43', disabled_text='#A0ABCB', sidebar='#101327',
        nav_active='#2A2549', secondary='#20263E', secondary_hover='#303750',
        error='#FFABA9', success='#87DEC4', preview_bg='#151A30',
    ),
    'blossom': Theme(
        id='blossom', bg='#FFF4F7', surface='#FFFCF8',
        surface_alt='#FFE9EF', input_bg='#FFFAF7', border='#D5A4B8',
        input_border='#AC718B', focus='#8E1851',
        text='#432B39', muted='#795665', accent='#B82E66',
        accent_hover='#A02258', accent_pressed='#861B49', on_accent='#FFFFFF',
        disabled_bg='#F0E2E8', disabled_text='#745967', sidebar='#FBE7EF',
        nav_active='#FBE3ED', secondary='#F8EAF0', secondary_hover='#F0D9E4',
        error='#AD334C', success='#236D55', preview_bg='#FFFAF7',
    ),
    'terminal': Theme(
        id='terminal', bg='#080F0C', surface='#101E17',
        surface_alt='#172B20', input_bg='#0A1510', border='#304A3B',
        input_border='#597D68', focus='#B4FBCF',
        text='#E4F6E9', muted='#A0BDAB', accent='#79E5A5',
        accent_hover='#A1F1BE', accent_pressed='#54C788', on_accent='#0A2818',
        disabled_bg='#1C2D23', disabled_text='#9CB7A6', sidebar='#0B1610',
        nav_active='#173A26', secondary='#182B20', secondary_hover='#263E30',
        error='#FFA7A7', success='#79E5A5', preview_bg='#0C1911',
    ),
}


def get_theme(theme_id: str | None) -> Theme:
    """Resolve saved preferences safely, including obsolete or invalid values."""
    return THEMES.get(theme_id, THEMES[DEFAULT_THEME])


def _resolve(theme: Theme | str | None) -> Theme:
    return theme if isinstance(theme, Theme) else get_theme(theme)


def build_palette(theme: Theme | str | None = DEFAULT_THEME) -> QPalette:
    """Provide explicit colors for popups, dialogs and unstyled native controls."""
    t = _resolve(theme)
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: t.bg,
        QPalette.ColorRole.WindowText: t.text,
        QPalette.ColorRole.Base: t.input_bg,
        QPalette.ColorRole.AlternateBase: t.surface_alt,
        QPalette.ColorRole.ToolTipBase: t.surface,
        QPalette.ColorRole.ToolTipText: t.text,
        QPalette.ColorRole.Text: t.text,
        QPalette.ColorRole.Button: t.secondary,
        QPalette.ColorRole.ButtonText: t.text,
        QPalette.ColorRole.BrightText: t.on_accent,
        QPalette.ColorRole.Light: t.surface_alt,
        QPalette.ColorRole.Midlight: t.border,
        QPalette.ColorRole.Dark: t.sidebar,
        QPalette.ColorRole.Mid: t.border,
        QPalette.ColorRole.Shadow: t.bg,
        QPalette.ColorRole.Highlight: t.accent,
        QPalette.ColorRole.HighlightedText: t.on_accent,
        QPalette.ColorRole.Link: t.accent,
        QPalette.ColorRole.LinkVisited: t.accent_pressed,
        QPalette.ColorRole.PlaceholderText: t.muted,
        QPalette.ColorRole.Accent: t.accent,
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.PlaceholderText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled_text))
    for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Button):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.disabled_bg))
    return palette


def build_stylesheet(theme: Theme | str | None = DEFAULT_THEME, text_size: str = 'standard') -> str:
    """Build colors and type together, without scaling geometry or motion art."""
    t = _resolve(theme)
    # Explicit text sizes grow together. Padding, border widths and the compact
    # progress strip stay unchanged; layouts use Qt's enlarged font metrics.
    def font(size):
        return size + (2 if text_size == 'large' else 0)
    down = (_ASSETS / f'ui-{t.id}-down.svg').as_posix()
    up = (_ASSETS / f'ui-{t.id}-up.svg').as_posix()
    check = (_ASSETS / f'ui-{t.id}-check.svg').as_posix()
    # Shape is part of appearance, while every layout-affecting value remains
    # shared. Switching themes must never move controls or change hit targets.
    input_radius, button_radius, panel_radius, check_radius, nav_radius, scroll_radius, tool_radius = {
        'midnight': (8, 8, 12, 4, 9, 4, 5),
        'blossom': (12, 18, 18, 7, 18, 4, 9),
        'terminal': (2, 2, 4, 1, 3, 1, 2),
    }.get(t.id, (8, 8, 12, 4, 9, 4, 5))
    terminal_detail = (
        "QLabel#pageEyebrow, QWidget#sidebar QLabel#sidebarCaption { "
        "font-family: 'Consolas', 'Microsoft YaHei UI'; }\n"
        if t.id == 'terminal' else ''
    )
    return f"""
QWidget {{ background: transparent; color: {t.text}; font-size: {font(13)}px; }}
QMainWindow, QWidget#workspace {{ background: {t.bg}; }}
QWidget#sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
QWidget#sidebar QLabel {{ border: none; background: transparent; color: {t.muted}; }}
QWidget#sidebar QLabel#brand {{ color: {t.text}; font-size: {font(24)}px; font-weight: 700; letter-spacing: 2px; }}
QWidget#sidebar QLabel#brandEyebrow {{ color: {t.accent}; font-size: {font(10)}px; font-weight: 600; letter-spacing: 2px; }}
QWidget#sidebar QLabel#sidebarCaption {{ color: {t.muted}; font-size: {font(11)}px; }}
QLabel#navGroup {{ color: {t.muted}; font-size: {font(10)}px; letter-spacing: 1px; font-weight: 600; }}
QWidget#sidebar QPushButton {{ text-align: left; border: 1px solid transparent; border-radius: {nav_radius}px; background: transparent; color: {t.muted}; min-height: 26px; padding: 9px 12px; font-size: {font(13)}px; font-weight: 500; }}
QWidget#sidebar QPushButton:hover {{ background: {t.secondary}; color: {t.text}; }}
QWidget#sidebar QPushButton:checked {{ background: {t.nav_active}; color: {t.accent}; border: 1px solid {t.border}; font-weight: 600; }}
QWidget#sidebar QPushButton:focus {{ border: 1px solid {t.focus}; }}
QLabel#pageTitle {{ font-size: {font(29)}px; font-weight: 700; color: {t.text}; }}
QLabel#pageEyebrow {{ color: {t.accent}; font-size: {font(10)}px; font-weight: 600; letter-spacing: 2px; }}
QLabel#offlineBadge {{ color: {t.muted}; font-size: {font(11)}px; background: {t.surface}; border: 1px solid {t.border}; border-radius: {input_radius}px; padding: 5px 9px; }}
QLabel[role='muted'] {{ color: {t.muted}; font-size: {font(11)}px; background: transparent; }}
QLabel[role='description'] {{ color: {t.muted}; font-size: {font(12)}px; background: transparent; }}
QLabel[role='sectionTitle'] {{ font-weight: 600; font-size: {font(14)}px; color: {t.text}; background: transparent; }}
QLabel[role='fieldLabel'] {{ font-size: {font(11)}px; font-weight: 600; color: {t.muted}; background: transparent; }}
QLabel#stepLabel {{ color: {t.accent}; font-size: {font(11)}px; font-weight: 600; }}
QFrame#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {panel_radius}px; }}
QFrame#card[kind='section'] {{ background: transparent; border: none; border-top: 1px solid {t.border}; border-radius: 0; }}
QFrame#card[kind='preview'] {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {panel_radius}px; }}
QFrame#card[kind='result'] {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {panel_radius}px; }}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: {t.input_bg}; color: {t.text}; border: 1px solid {t.input_border}; border-radius: {input_radius}px; padding: 8px 11px; min-height: 18px; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QLineEdit, QTextEdit, QPlainTextEdit {{ placeholder-text-color: {t.muted}; }}
QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {t.muted}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {t.focus}; background: {t.surface}; }}
QLineEdit[dragActive='true'] {{ border: 1px dashed {t.accent}; background: {t.nav_active}; color: {t.text}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled, QSpinBox:disabled {{ color: {t.disabled_text}; background: {t.disabled_bg}; border-color: {t.border}; }}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{ placeholder-text-color: {t.disabled_text}; }}
QComboBox#theme_selector, QComboBox#language_selector, QComboBox#text_size_selector {{ font-size: {font(11)}px; padding: 7px 10px; background: {t.surface}; }}
QComboBox {{ padding-right: 27px; }}
QComboBox::drop-down {{ border: none; width: 25px; }}
QComboBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; outline: none; selection-background-color: {t.nav_active}; selection-color: {t.accent}; padding: 4px; }}
QComboBox QAbstractItemView::item {{ background: {t.surface}; color: {t.text}; padding: 7px 9px; min-height: 18px; border: none; }}
QComboBox QAbstractItemView::item:selected {{ background: {t.nav_active}; color: {t.accent}; }}
QDoubleSpinBox, QSpinBox {{ padding-right: 32px; }}
QDoubleSpinBox::up-button, QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 24px; height: 18px; border-left: 1px solid {t.border}; border-top-right-radius: {input_radius}px; background: {t.secondary}; }}
QDoubleSpinBox::down-button, QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 24px; height: 18px; border-left: 1px solid {t.border}; border-bottom-right-radius: {input_radius}px; background: {t.secondary}; }}
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover, QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {t.secondary_hover}; }}
QDoubleSpinBox::up-button:disabled, QDoubleSpinBox::down-button:disabled, QSpinBox::up-button:disabled, QSpinBox::down-button:disabled {{ background: {t.disabled_bg}; }}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{ image: url("{up}"); width: 14px; height: 14px; }}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{ image: url("{down}"); width: 14px; height: 14px; }}
QPushButton {{ background: {t.secondary}; color: {t.text}; border: 1px solid {t.border}; border-radius: {button_radius}px; padding: 8px 13px; min-height: 18px; font-weight: 600; }}
QPushButton:hover {{ background: {t.secondary_hover}; border-color: {t.muted}; }}
QPushButton:pressed {{ background: {t.nav_active}; }}
QPushButton:focus {{ border: 1px solid {t.focus}; }}
QPushButton[role='primary'] {{ background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent}; padding: 9px 20px; }}
QPushButton[role='primary']:hover {{ background: {t.accent_hover}; color: {t.on_accent}; border-color: {t.accent_hover}; }}
QPushButton[role='primary']:pressed {{ background: {t.accent_pressed}; color: {t.on_accent}; border-color: {t.accent_pressed}; }}
QPushButton[role='appearance'] {{ background: transparent; color: {t.muted}; border: 1px solid {t.border}; }}
QPushButton[role='appearance']:checked {{ background: {t.nav_active}; color: {t.accent}; border-color: {t.accent}; }}
QPushButton:disabled {{ background: {t.disabled_bg}; color: {t.disabled_text}; border-color: {t.border}; }}
QPushButton[role='primary']:disabled {{ background: {t.disabled_bg}; color: {t.disabled_text}; border: 1px solid {t.border}; }}
QCheckBox, QRadioButton {{ color: {t.text}; spacing: 8px; min-height: 20px; background: transparent; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {t.disabled_text}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {t.muted}; border-radius: {check_radius}px; background: {t.input_bg}; }}
QCheckBox::indicator:hover {{ border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border: 1px solid {t.accent}; image: url("{check}"); }}
QCheckBox::indicator:disabled {{ border-color: {t.border}; background: {t.disabled_bg}; }}
QCheckBox::indicator:checked:disabled {{ background: {t.accent_pressed}; image: url("{check}"); }}
QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {t.muted}; border-radius: 8px; background: {t.input_bg}; }}
QRadioButton::indicator:checked {{ background: {t.accent}; border: 4px solid {t.surface}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.border}; min-height: 32px; border-radius: {scroll_radius}px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t.border}; min-width: 32px; border-radius: {scroll_radius}px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QLabel#imagePreview {{ background: {t.preview_bg}; border: 1px solid {t.border}; border-radius: {input_radius}px; color: {t.muted}; }}
QLabel#status {{ color: {t.muted}; background: transparent; font-size: {font(11)}px; }}
QLabel#status[state='error'] {{ color: {t.error}; }}
QLabel#status[state='success'] {{ color: {t.success}; }}
QProgressBar {{ border: none; background: transparent; color: {t.text}; min-height: 16px; max-height: 16px; border-radius: 8px; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 2px; }}
QTextBrowser {{ border: none; background: transparent; color: {t.text}; font-size: {font(13)}px; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QTextEdit, QPlainTextEdit {{ background: {t.input_bg}; color: {t.text}; border: 1px solid {t.input_border}; border-radius: {input_radius}px; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QTextEdit:hover, QPlainTextEdit:hover {{ border-color: {t.muted}; }}
QTextEdit:focus, QPlainTextEdit:focus {{ border-color: {t.focus}; }}
QTextEdit:disabled, QPlainTextEdit:disabled {{ border-color: {t.border}; background: {t.disabled_bg}; color: {t.disabled_text}; }}
QTextBrowser#result_summary, QTextBrowser#result_details {{ background: transparent; color: {t.text}; border: none; border-radius: 0; padding: 0; }}
QAbstractItemView {{ background: {t.surface}; alternate-background-color: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border}; selection-background-color: {t.nav_active}; selection-color: {t.accent}; outline: none; }}
QAbstractItemView::item:selected {{ background: {t.nav_active}; color: {t.accent}; }}
QAbstractItemView::item:hover {{ background: {t.secondary}; }}
QHeaderView::section {{ background: {t.secondary}; color: {t.text}; border: none; border-bottom: 1px solid {t.border}; padding: 7px 9px; }}
QTreeView::branch {{ background: {t.surface}; }}
QDialog, QMessageBox, QFileDialog {{ background: {t.bg}; color: {t.text}; }}
QMenu {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: {tool_radius}px; }}
QMenu::item:selected {{ background: {t.nav_active}; color: {t.accent}; }}
QMenu::item:disabled {{ color: {t.disabled_text}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 7px; }}
QToolButton {{ background: {t.secondary}; color: {t.text}; border: 1px solid {t.border}; border-radius: {tool_radius}px; padding: 5px; }}
QToolButton:hover {{ background: {t.secondary_hover}; }}
QToolButton:focus {{ border-color: {t.focus}; }}
QToolButton:disabled {{ background: {t.disabled_bg}; color: {t.disabled_text}; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 7px; }}
""" + terminal_detail


# Backward-compatible entry point for callers that do not expose appearance.
STYLE = build_stylesheet(DEFAULT_THEME)
