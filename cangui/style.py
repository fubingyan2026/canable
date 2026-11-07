"""Light/dark palettes for Qt widgets, docks, models and plugin panels."""
import colorsys
from pathlib import Path

from PySide6.QtGui import QColor, QPalette


_LIGHT = dict(
    BG_MAIN="#F3F6FA", BG_CARD="#FFFFFF", BG_HEADER="#EEF3F7",
    BG_HOVER="#EDF5F5", BG_SELECT="#DDEFEF", BG_TX="#EAF5F1", BG_ERROR="#FFF0ED",
    BORDER="#DAE3EB", FG_TEXT="#253649", FG_DIM="#65788B", FG_ACCENT="#147D78",
    FG_ERROR="#B7473D", LOAD_LOW="#147D78", LOAD_MID="#A96C1B", LOAD_HIGH="#B7473D",
    BG_ALT="#F8FAFC", SELECT_TEXT="#164F50", FG_DISABLED="#8A99A8",
    BORDER_DISABLED="#E5EBF0", BORDER_HOVER="#A9C8C9", BORDER_SELECT="#A9CECA",
    BG_ACCENT="#147D78", ACCENT_HOVER="#106B67", ACCENT_PRESSED="#0C5C58",
    DANGER_BORDER="#E8C7C1", PRIMARY_DISABLED_BG="#E7EEEF",
    PRIMARY_DISABLED_FG="#879A9F", PRIMARY_DISABLED_BORDER="#DCE6E8",
    CHECK_BORDER="#B9C8D5", GRID="#E8EEF3", DEVICE_BG="#FAFCFD",
    SCROLL_HANDLE="#C7D3DE", SCROLL_HOVER="#9DB1C2", PROGRESS="#8FC9C1",
    TOOLTIP_BG="#253649", TOOLTIP_FG="#FFFFFF",
)
_DARK = dict(
    BG_MAIN="#141E2B", BG_CARD="#1C2938", BG_HEADER="#233345",
    BG_HOVER="#283D4C", BG_SELECT="#234B50", BG_TX="#1D3837", BG_ERROR="#402C33",
    BORDER="#35475A", FG_TEXT="#E1EAF2", FG_DIM="#A2B4C7", FG_ACCENT="#75D5C4",
    FG_ERROR="#F0A397", LOAD_LOW="#75D5C4", LOAD_MID="#E4BC78", LOAD_HIGH="#F0A397",
    BG_ALT="#202F40", SELECT_TEXT="#D1F4EF", FG_DISABLED="#7F94AA",
    BORDER_DISABLED="#2F4052", BORDER_HOVER="#648E98", BORDER_SELECT="#50858A",
    BG_ACCENT="#1C807A", ACCENT_HOVER="#23958B", ACCENT_PRESSED="#146963",
    DANGER_BORDER="#81544F", PRIMARY_DISABLED_BG="#2A3B48",
    PRIMARY_DISABLED_FG="#7F94AA", PRIMARY_DISABLED_BORDER="#3A4D60",
    CHECK_BORDER="#7A92A9", GRID="#304457", DEVICE_BG="#192635",
    SCROLL_HANDLE="#4B6177", SCROLL_HOVER="#658298", PROGRESS="#3B9F93",
    TOOLTIP_BG="#304359", TOOLTIP_FG="#EAF2F8",
)
_theme = "light"
globals().update(_LIGHT)

# Semantic labels use a property rather than retaining an inline literal color.
_TEXT_ROLES = ("FG_TEXT", "FG_DIM", "FG_ACCENT", "FG_ERROR", "LOAD_LOW", "LOAD_MID", "LOAD_HIGH")
_COLOR_ROLES = {}
for _palette in (_LIGHT, _DARK):
    for _role in _TEXT_ROLES:
        _COLOR_ROLES.setdefault(_palette[_role].upper(), _role)


def color_role(color):
    """Resolve even a cached color from the other theme to its semantic role."""
    name = color.upper() if isinstance(color, str) else color.name().upper()
    return _COLOR_ROLES.get(name)


def set_text_color(widget, color, extra_qss=""):
    """Set a live theme-aware label color, preserving optional font styling."""
    role = color_role(color)
    changed = widget.property("themeForeground") != role
    widget.setProperty("themeForeground", role)
    qss = extra_qss if role else f"color: {color}; {extra_qss}"
    if widget.styleSheet() != qss:
        widget.setStyleSheet(qss)
    if changed:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def id_color(can_id: int, extended: bool = False) -> str:
    """Stable ID colors with enough contrast against a light table."""
    hue = (((can_id >> 16) ^ (can_id & 0xFFFF)) if extended else can_id * 7) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360, 0.69 if _theme == "dark" else 0.34, 0.46)
    return f"#{round(red * 255):02X}{round(green * 255):02X}{round(blue * 255):02X}"


def apply_style(app, theme=None):
    """Apply the chosen palette without recreating widgets or changing layout."""
    if theme is not None:
        set_theme(theme)
    appearance = f"{_theme}-v2"
    if app.property("canableAppearance") == appearance:
        return
    if not app.property("canableAppearance"):
        app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.Window: BG_MAIN, QPalette.WindowText: FG_TEXT,
        QPalette.Base: BG_CARD, QPalette.AlternateBase: BG_ALT,
        QPalette.Text: FG_TEXT, QPalette.Button: BG_CARD,
        QPalette.ButtonText: FG_TEXT, QPalette.Highlight: BG_SELECT,
        QPalette.HighlightedText: SELECT_TEXT, QPalette.PlaceholderText: FG_DIM,
        QPalette.Link: FG_ACCENT, QPalette.ToolTipBase: TOOLTIP_BG,
        QPalette.ToolTipText: TOOLTIP_FG, QPalette.Mid: BORDER,
        QPalette.Light: BG_HOVER, QPalette.Midlight: BG_HEADER,
        QPalette.Dark: BORDER, QPalette.BrightText: TOOLTIP_FG,
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(FG_DISABLED))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor(BG_MAIN))
    palette.setColor(QPalette.Disabled, QPalette.Button, QColor(BG_MAIN))
    app.setPalette(palette)
    app.setStyleSheet(get_qss())
    app.setProperty("canableAppearance", appearance)


def get_qss() -> str:
    assets = Path(__file__).resolve().parent.as_posix()
    arrow = "arrow_down_dark.svg" if _theme == "dark" else "arrow_down.svg"
    return f"""
QMainWindow, QDialog {{ background: {BG_MAIN}; }}
QMainWindow::separator {{ background: {BG_MAIN}; width: 7px; height: 7px; }}
QMainWindow::separator:hover {{ background: {BORDER}; }}
QWidget#workspace, QFrame#sidebar, QFrame#sidebarCard {{ background: transparent; }}
QWidget#tracePanel, QWidget#sendPanel, QWidget#filterPanel {{ background: {BG_CARD}; }}
QLabel {{ color: {FG_TEXT}; background: transparent; }}
QLabel:disabled {{ color: {FG_DISABLED}; }}
QLabel#appTitle {{ font-size: 16px; font-weight: 700; color: {FG_TEXT}; }}
QLabel#appSubtitle {{ font-size: 11px; color: {FG_DIM}; }}
QLabel#panelSummary {{ color: {FG_DIM}; padding: 3px 2px; }}
QGroupBox {{
    background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    margin-top: 12px; padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; subcontrol-position: top left;
    left: 12px; padding: 0 4px; color: {FG_DIM}; font-weight: 600;
}}
QGroupBox QLabel, QGroupBox QCheckBox {{ background: transparent; }}
QPushButton, QToolButton {{
    color: {FG_TEXT}; background: {BG_CARD}; border: 1px solid {BORDER};
    border-radius: 5px; padding: 6px 8px; min-height: 18px;
}}
QPushButton:hover, QToolButton:hover {{ background: {BG_HOVER}; border-color: {BORDER_HOVER}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BG_SELECT}; }}
QPushButton:focus, QToolButton:focus {{ border-color: {FG_ACCENT}; }}
QPushButton:checked, QToolButton:checked {{ background: {BG_SELECT}; color: {SELECT_TEXT}; border-color: {BORDER_SELECT}; }}
QPushButton:disabled, QToolButton:disabled {{ background: {BG_MAIN}; color: {FG_DISABLED}; border-color: {BORDER_DISABLED}; }}
QPushButton#connectBtn, QPushButton#sendBtn, QPushButton#primaryBtn {{
    background: {BG_ACCENT}; color: white; border-color: {BG_ACCENT}; font-weight: 600;
}}
QPushButton#connectBtn:hover, QPushButton#sendBtn:hover, QPushButton#primaryBtn:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#connectBtn:pressed, QPushButton#sendBtn:pressed, QPushButton#primaryBtn:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#connectBtn:checked, QPushButton#toggleBtn[running="true"] {{
    background: {BG_ERROR}; border-color: {DANGER_BORDER}; color: {FG_ERROR};
}}
QPushButton#connectBtn:disabled, QPushButton#sendBtn:disabled, QPushButton#primaryBtn:disabled {{
    background: {PRIMARY_DISABLED_BG}; color: {PRIMARY_DISABLED_FG}; border-color: {PRIMARY_DISABLED_BORDER};
}}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{
    background: {BG_CARD}; color: {FG_TEXT}; border: 1px solid {BORDER};
    border-radius: 5px; padding: 5px 8px; min-height: 18px;
    selection-background-color: {BG_SELECT}; selection-color: {FG_TEXT};
}}
QComboBox {{ padding-right: 20px; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {{ border-color: {FG_ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ background: {BG_MAIN}; color: {FG_DISABLED}; }}
QComboBox::drop-down {{ width: 20px; border: none; }}
QComboBox::down-arrow {{ image: url("{assets}/{arrow}"); width: 10px; height: 10px; }}
QComboBox QAbstractItemView {{ background: {BG_CARD}; color: {FG_TEXT}; selection-background-color: {BG_SELECT}; selection-color: {SELECT_TEXT}; border: 1px solid {BORDER}; padding: 4px; outline: none; }}
QCheckBox, QRadioButton {{ spacing: 7px; color: {FG_TEXT}; background: transparent; }}
QCheckBox::indicator {{ width: 14px; height: 14px; background: {BG_CARD}; border: 1px solid {CHECK_BORDER}; border-radius: 3px; }}
QCheckBox::indicator:hover {{ border-color: {FG_ACCENT}; }}
QCheckBox::indicator:checked {{ background: {BG_ACCENT}; border-color: {BG_ACCENT}; image: url("{assets}/check.svg"); }}
QCheckBox::indicator:disabled {{ background: {BG_MAIN}; border-color: {BORDER}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG_CARD}; border-radius: 7px; top: -1px; }}
QTabBar::tab {{
    color: {FG_DIM}; background: transparent; padding: 9px 14px;
    border: none; border-bottom: 2px solid transparent; margin-right: 3px;
}}
QTabBar::tab:hover {{ color: {FG_TEXT}; background: {BG_HOVER}; }}
QTabBar::tab:selected {{ color: {FG_ACCENT}; background: {BG_CARD}; border-bottom-color: {FG_ACCENT}; font-weight: 600; }}
QTabBar::close-button {{ image: url("{assets}/close.svg"); width: 12px; height: 12px; padding: 2px; }}
QTabBar::close-button:hover {{ background: {BG_SELECT}; border-radius: 3px; }}
QDockWidget {{ color: {FG_TEXT}; }}
QDockWidget::title {{ background: {BG_HEADER}; padding: 8px 10px; border-bottom: 1px solid {BORDER}; font-weight: 600; }}
QDockWidget::close-button, QDockWidget::float-button {{ padding: 3px; border-radius: 3px; }}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{ background: {BG_SELECT}; }}
QTableView, QTreeView, QListView {{
    background: {BG_CARD}; alternate-background-color: {BG_ALT};
    color: {FG_TEXT}; border: 1px solid {BORDER}; border-radius: 5px;
    selection-background-color: {BG_SELECT}; selection-color: {SELECT_TEXT};
    gridline-color: {GRID}; outline: none;
}}
QTableView::item {{ padding: 3px 7px; }}
QTableView::item:selected, QTreeView::item:selected {{ background: {BG_SELECT}; color: {SELECT_TEXT}; }}
QHeaderView::section {{
    background: {BG_HEADER}; color: {FG_DIM}; font-weight: 600;
    border: none; border-bottom: 1px solid {BORDER}; padding: 7px 6px;
}}
QTableCornerButton::section {{ background: {BG_HEADER}; border: none; }}
QListWidget#deviceList {{ border-color: {BORDER}; border-radius: 5px; background: {DEVICE_BG}; }}
QListWidget#deviceList::item {{ padding: 7px 8px; margin: 3px; border-radius: 4px; }}
QListWidget#deviceList::item:selected {{ background: {BG_SELECT}; color: {SELECT_TEXT}; }}
QListWidget#deviceList::item:hover {{ background: {BG_HOVER}; }}
QSplitter::handle {{ background: {BG_MAIN}; }}
QSplitter::handle:hover {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {SCROLL_HANDLE}; min-height: 28px; border-radius: 5px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL_HANDLE}; min-width: 28px; border-radius: 5px; }}
QScrollBar::handle:hover {{ background: {SCROLL_HOVER}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QMenuBar {{ background: {BG_CARD}; color: {FG_TEXT}; border-bottom: 1px solid {BORDER}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 5px 9px; background: transparent; }}
QMenuBar::item:selected {{ background: {BG_HOVER}; border-radius: 4px; }}
QMenu {{ background: {BG_CARD}; color: {FG_TEXT}; border: 1px solid {BORDER}; padding: 5px; }}
QMenu::item {{ padding: 7px 25px; border-radius: 4px; }}
QMenu::item:selected {{ background: {BG_SELECT}; color: {SELECT_TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
QStatusBar {{ background: {BG_CARD}; border-top: 1px solid {BORDER}; padding: 4px 8px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {FG_DIM}; padding: 3px 5px; }}
QLabel#statusLabel {{ border-radius: 4px; padding: 4px 9px; font-weight: 600; }}
QLabel#statusLabel[connected="true"] {{ color: {FG_ACCENT}; background: {BG_TX}; }}
QLabel#statusLabel[connected="false"] {{ color: {FG_DIM}; background: {BG_MAIN}; }}
QLabel#busLoad {{ color: {LOAD_LOW}; font-weight: 600; }}
QLabel#busLoad[level="mid"] {{ color: {LOAD_MID}; }}
QLabel#busLoad[level="high"] {{ color: {LOAD_HIGH}; }}
QProgressBar {{ border: 1px solid {BORDER}; border-radius: 4px; background: {BG_MAIN}; text-align: center; min-height: 18px; }}
QProgressBar::chunk {{ background: {PROGRESS}; border-radius: 3px; }}
QPlainTextEdit, QTextEdit {{ background: {BG_CARD}; color: {FG_TEXT}; border: 1px solid {BORDER}; border-radius: 5px; selection-background-color: {BG_SELECT}; selection-color: {SELECT_TEXT}; }}
QToolTip {{ background: {TOOLTIP_BG}; color: {TOOLTIP_FG}; border: none; padding: 6px 8px; }}
QPushButton[pluginCompact="true"], QToolButton[pluginCompact="true"] {{ padding: 2px 7px; min-height: 16px; }}
QLineEdit[pluginCompact="true"], QComboBox[pluginCompact="true"], QSpinBox[pluginCompact="true"], QDoubleSpinBox[pluginCompact="true"] {{ padding-top: 0px; padding-bottom: 0px; min-height: 16px; }}
QGroupBox[pluginCompact="true"] {{ margin-top: 9px; padding-top: 4px; border-radius: 6px; }}
QHeaderView[pluginCompact="true"]::section {{ padding: 4px 5px; }}
QTableView[pluginCompact="true"]::item {{ padding: 1px 5px; }}
QTabBar[pluginCompact="true"]::tab {{ padding: 5px 10px; }}
QWidget[pluginPage="true"] {{ background: {BG_CARD}; }}
QFrame#pluginDisclosure {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 5px; }}
QToolButton#disclosureHeader {{ background: {BG_HEADER}; color: {FG_DIM}; border: none; border-radius: 4px; text-align: left; font-weight: 600; }}
""" + "\n".join(f'QWidget[themeForeground="{role}"] {{ color: {globals()[role]}; }}'
                    for role in _TEXT_ROLES)


def set_theme(name: str):
    """Select the palette; apply_style installs it on the QApplication."""
    global _theme, QSS
    _theme = name if name in ("light", "dark") else "light"
    globals().update(_DARK if _theme == "dark" else _LIGHT)
    QSS = get_qss()


def current_theme() -> str:
    return _theme


QSS = get_qss()
