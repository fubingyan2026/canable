"""cangui 主题与色板（深色，cangaroo 风格）"""

# 背景 / 前景
BG_DARK     = "#1e1e1e"
BG_PANEL    = "#252526"
BG_INPUT    = "#1b1b1b"
BG_HEADER   = "#2d2d30"
BG_TOOLBAR  = "#333337"
BG_HOVER    = "#094771"
BG_SELECT   = "#04395e"

FG_TEXT     = "#d4d4d4"
FG_DIM      = "#858585"
FG_ACCENT   = "#4ec9b0"
FG_WARN     = "#d7ba7d"
FG_ERROR    = "#f48771"
FG_LINK     = "#569cd6"

BORDER      = "#3c3c3c"

# 总线负载颜色
LOAD_LOW    = "#4ec9b0"
LOAD_MID    = "#d7ba7d"
LOAD_HIGH   = "#f48771"

# Trace 按 CAN ID 的色相
def id_color(can_id: int, extended: bool = False) -> str:
    """按 CAN ID 生成稳定 HSL 颜色。"""
    if extended:
        hue = ((can_id >> 16) ^ (can_id & 0xFFFF)) % 360
    else:
        hue = (can_id * 7) % 360
    return f"hsl({hue}, 55%, 70%)"

# 全局 QSS
QSS = f"""
QWidget {{
    background-color: {BG_DARK};
    color: {FG_TEXT};
    font-family: "Consolas", "Menlo", "Monaco", "Courier New", monospace;
    font-size: 10pt;
}}

QMainWindow, QDialog {{
    background-color: {BG_DARK};
}}

QToolBar {{
    background-color: {BG_TOOLBAR};
    border-bottom: 1px solid {BORDER};
    spacing: 4px;
    padding: 4px;
}}

QStatusBar {{
    background-color: {BG_TOOLBAR};
    border-top: 1px solid {BORDER};
    color: {FG_TEXT};
}}

QMenuBar {{
    background-color: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
}}

QMenuBar::item:selected {{
    background-color: {BG_HOVER};
}}

QMenu {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
}}

QMenu::item:selected {{
    background-color: {BG_HOVER};
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background-color: {BG_PANEL};
}}

QTabBar::tab {{
    background-color: {BG_PANEL};
    color: {FG_TEXT};
    padding: 6px 14px;
    border: 1px solid {BORDER};
    border-bottom: none;
}}

QTabBar::tab:selected {{
    background-color: {BG_HEADER};
    color: {FG_ACCENT};
}}

QPushButton {{
    background-color: {BG_HEADER};
    color: {FG_TEXT};
    border: 1px solid {BORDER};
    padding: 4px 12px;
    border-radius: 2px;
}}

QPushButton:hover {{
    background-color: {BG_HOVER};
}}

QPushButton:pressed {{
    background-color: {BG_SELECT};
}}

QPushButton:checked {{
    background-color: {BG_HOVER};
    color: {FG_ACCENT};
}}

QPushButton#connectBtn:checked {{
    background-color: #2d6e2d;
    color: white;
    border-color: #4ec94e;
}}

QPushButton#connectBtn {{
    font-weight: bold;
}}

QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {BG_INPUT};
    color: {FG_TEXT};
    border: 1px solid {BORDER};
    padding: 3px 6px;
    selection-background-color: {BG_HOVER};
}}

QComboBox::drop-down {{
    border-left: 1px solid {BORDER};
    width: 18px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_PANEL};
    selection-background-color: {BG_HOVER};
}}

QHeaderView::section {{
    background-color: {BG_HEADER};
    color: {FG_TEXT};
    padding: 4px 6px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
}}

QTableView, QTableWidget, QTreeView, QListWidget {{
    background-color: {BG_INPUT};
    color: {FG_TEXT};
    gridline-color: {BORDER};
    selection-background-color: {BG_SELECT};
    selection-color: white;
    border: 1px solid {BORDER};
}}

QTableView::item, QTableWidget::item, QTreeView::item, QListWidget::item {{
    padding: 2px 4px;
}}

QTableView::item:selected, QTableWidget::item:selected,
QTreeView::item:selected, QListWidget::item:selected {{
    background-color: {BG_SELECT};
    color: white;
}}

QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {BG_PANEL};
    border: none;
    width: 12px;
    height: 12px;
}}

QScrollBar::handle {{
    background-color: {BG_HEADER};
    border-radius: 4px;
    min-height: 20px;
    min-width: 20px;
}}

QScrollBar::handle:hover {{
    background-color: {BG_HOVER};
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    color: {FG_TEXT};
}}

QDockWidget::title {{
    background-color: {BG_TOOLBAR};
    padding: 4px 8px;
    border-bottom: 1px solid {BORDER};
    text-align: left;
}}

QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 2px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    color: {FG_ACCENT};
}}

QLabel#statusLabel[connected="true"] {{
    color: {LOAD_LOW};
    font-weight: bold;
}}

QLabel#statusLabel[connected="false"] {{
    color: {FG_ERROR};
    font-weight: bold;
}}

QLabel#busLoad {{
    color: {LOAD_LOW};
    font-weight: bold;
}}

QLabel#busLoad[level="mid"] {{
    color: {LOAD_MID};
}}

QLabel#busLoad[level="high"] {{
    color: {LOAD_HIGH};
}}

QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER};
    background-color: {BG_INPUT};
}}

QCheckBox::indicator:checked {{
    background-color: {FG_ACCENT};
}}

QSplitter::handle {{
    background-color: {BORDER};
}}

QSplitter::handle:horizontal {{
    width: 2px;
}}

QSplitter::handle:vertical {{
    height: 2px;
}}
"""
