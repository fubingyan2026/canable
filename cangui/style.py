"""CANable 2.5 theme -- macOS light / dark (Big Sur/Sonoma style).

参考 Apple Human Interface Guidelines：
- 浅色：#ECECEC 窗口背景 / #FFFFFF 卡片 / #007AFF 强调蓝
- 深色：#1E1E1E 窗口背景 / #2D2D2D 卡片 / #0A84FF 强调蓝
- 交通灯：#FF5F57 / #FEBC2E / #28C840（由 title_bar 单独绘制）
- 状态栏：深灰色（即使浅色主题也使用深色状态栏）
"""
import os

_HERE = os.path.dirname(os.path.abspath(__file__))

# ---- Apple 风格调色板 ----
_LIGHT = {
    # 背景层
    "BG_MAIN": "#ECECEC",      # 窗口主背景（macOS 浅灰）
    "BG_CARD": "#FFFFFF",      # 卡片/面板底色（纯白）
    "BG_INPUT": "#FFFFFF",     # 输入框背景
    "BG_HEADER": "#F5F5F5",    # 表头/工具栏背景
    "BG_HOVER": "#E5E5E5",     # 鼠标悬停色
    "BG_SELECT": "#DEEBFF",    # 选中项背景（淡蓝）
    "BG_SIDEBAR": "#E8E8E8",   # 侧栏背景（略深于主背景）
    "BG_STATUS": "#2B2B2B",    # 状态栏背景（深灰，浅色主题也使用）
    "BG_STATUS_FG": "#E5E5E5", # 状态栏文字
    # 强调色（Apple system colors）
    "BG_ACCENT": "#34C759",    # 系统绿（连接/主动作）
    "BG_ACCENT_H": "#28A745",  # 绿色 hover
    "BG_MACOS_BLUE": "#007AFF",# 系统蓝（按钮激活/链接）
    "BG_MACOS_BLUE_H": "#0066CC",
    "BG_CORAL": "#FF6B6B",     # 警告/珊瑚强调
    "BG_CORAL_H": "#FF5252",
    # 数据行底色
    "BG_TX": "#E8F8EC",        # 本机发送（TX）行背景
    "BG_ERROR": "#FFE5E5",     # 错误帧行背景
    # 文字色
    "FG_TEXT": "#1D1D1F",      # 主文字（近黑）
    "FG_DIM": "#86868B",       # 次要文本（Apple secondary label）
    "FG_ACCENT": "#34C759",    # 绿色强调文字
    "FG_MACOS_BLUE": "#007AFF",# 蓝色强调文字
    "FG_CORAL": "#FF6B6B",
    "FG_WARN": "#FF9500",      # Apple orange
    "FG_ERROR": "#FF3B30",     # Apple red
    "FG_LINK": "#007AFF",
    # 边框/分隔
    "BORDER": "#D1D1D6",       # Apple separator
    "BORDER_SOFT": "#E5E5E5",  # 更轻的分隔线
    # 总线负载色阶
    "LOAD_LOW": "#34C759",
    "LOAD_MID": "#FF9500",
    "LOAD_HIGH": "#FF3B30",
    # 交通灯
    "TL_RED": "#FF5F57",
    "TL_YELLOW": "#FEBC2E",
    "TL_GREEN": "#28C840",
    "TL_RED_GLYPH": "#BE2A22",
    "TL_YELLOW_GLYPH": "#9A6A00",
    "TL_GREEN_GLYPH": "#1AA631",
}

_DARK = {
    # 背景层
    "BG_MAIN": "#1E1E1E",      # 窗口主背景（macOS 深色）
    "BG_CARD": "#2D2D2D",      # 卡片底色
    "BG_INPUT": "#1A1A1A",     # 输入框背景（更深）
    "BG_HEADER": "#3A3A3A",    # 表头背景
    "BG_HOVER": "#3A3A3A",     # 悬停色
    "BG_SELECT": "#1B3D5F",    # 选中项背景（深蓝）
    "BG_SIDEBAR": "#252525",   # 侧栏背景
    "BG_STATUS": "#1A1A1A",    # 状态栏背景（更深）
    "BG_STATUS_FG": "#E5E5E5", # 状态栏文字
    # 强调色（Apple system colors - dark mode）
    "BG_ACCENT": "#30D158",    # 系统绿
    "BG_ACCENT_H": "#28B84C",
    "BG_MACOS_BLUE": "#0A84FF",# 系统蓝（深色模式）
    "BG_MACOS_BLUE_H": "#0974E0",
    "BG_CORAL": "#FF6B6B",
    "BG_CORAL_H": "#FF5252",
    # 数据行底色
    "BG_TX": "#1F3325",        # TX 行背景（深绿）
    "BG_ERROR": "#3D1F1F",     # 错误帧行背景
    # 文字色
    "FG_TEXT": "#F5F5F7",      # 主文字（近白）
    "FG_DIM": "#98989D",       # 次要文本
    "FG_ACCENT": "#30D158",
    "FG_MACOS_BLUE": "#0A84FF",
    "FG_CORAL": "#FF6B6B",
    "FG_WARN": "#FF9F0A",
    "FG_ERROR": "#FF453A",
    "FG_LINK": "#0A84FF",
    # 边框
    "BORDER": "#38383A",
    "BORDER_SOFT": "#2A2A2A",
    # 总线负载色阶
    "LOAD_LOW": "#30D158",
    "LOAD_MID": "#FF9F0A",
    "LOAD_HIGH": "#FF453A",
    # 交通灯（深色模式下颜色保持一致，但稍亮）
    "TL_RED": "#FF5F57",
    "TL_YELLOW": "#FEBC2E",
    "TL_GREEN": "#28C840",
    "TL_RED_GLYPH": "#7A0E0E",
    "TL_YELLOW_GLYPH": "#7A4F00",
    "TL_GREEN_GLYPH": "#0A6C1A",
}

_current_theme = "light"
_p = _LIGHT.copy()

# 动态导出符号（向后兼容旧调用）
BG_MAIN = _p["BG_MAIN"]
BG_CARD = _p["BG_CARD"]
BG_INPUT = _p["BG_INPUT"]
BG_HEADER = _p["BG_HEADER"]
BG_HOVER = _p["BG_HOVER"]
BG_SELECT = _p["BG_SELECT"]
BG_ACCENT = _p["BG_ACCENT"]
BG_ACCENT_H = _p["BG_ACCENT_H"]
BG_MACOS_BLUE = _p["BG_MACOS_BLUE"]
BG_MACOS_BLUE_H = _p["BG_MACOS_BLUE_H"]
BG_CORAL = _p["BG_CORAL"]
BG_CORAL_H = _p["BG_CORAL_H"]
BG_SIDEBAR = _p["BG_SIDEBAR"]
BG_STATUS = _p["BG_STATUS"]
BG_STATUS_FG = _p["BG_STATUS_FG"]
BG_TX = _p["BG_TX"]
BG_ERROR = _p["BG_ERROR"]
FG_TEXT = _p["FG_TEXT"]
FG_DIM = _p["FG_DIM"]
FG_ACCENT = _p["FG_ACCENT"]
FG_MACOS_BLUE = _p["FG_MACOS_BLUE"]
FG_CORAL = _p["FG_CORAL"]
FG_WARN = _p["FG_WARN"]
FG_ERROR = _p["FG_ERROR"]
FG_LINK = _p["FG_LINK"]
BORDER = _p["BORDER"]
BORDER_SOFT = _p["BORDER_SOFT"]
LOAD_LOW = _p["LOAD_LOW"]
LOAD_MID = _p["LOAD_MID"]
LOAD_HIGH = _p["LOAD_HIGH"]
TL_RED = _p["TL_RED"]
TL_YELLOW = _p["TL_YELLOW"]
TL_GREEN = _p["TL_GREEN"]
TL_RED_GLYPH = _p["TL_RED_GLYPH"]
TL_YELLOW_GLYPH = _p["TL_YELLOW_GLYPH"]
TL_GREEN_GLYPH = _p["TL_GREEN_GLYPH"]


def id_color(can_id: int, extended: bool = False) -> str:
    """CAN ID 着色：按哈希生成 HSL 色，同 ID 颜色一致、不同 ID 视觉可分。"""
    if extended:
        hue = ((can_id >> 16) ^ (can_id & 0xFFFF)) % 360
    else:
        hue = (can_id * 7) % 360
    return f"hsl({hue}, 55%, 55%)"


_FONT_STACK = (
    '"SF Pro Display", "SF Pro Text", -apple-system, '
    '"PingFang SC", "Noto Sans CJK SC", "Noto Sans", '
    '"Helvetica Neue", "Inter", "Microsoft YaHei", "Segoe UI", sans-serif'
)


def _make_qss(p: dict) -> str:
    _check_svg = os.path.join(_HERE, "check.svg").replace("\\", "/")
    _close_svg = os.path.join(_HERE, "close.svg").replace("\\", "/")
    _close_svg_hover = os.path.join(_HERE, "close_hover.svg").replace("\\", "/")
    # 下拉箭头：浅色/深色主题用不同颜色的菱形 SVG
    _arrow_svg = os.path.join(_HERE, "arrow_down.svg" if current_theme() == "light" else "arrow_down_dark.svg").replace("\\", "/")
    return f"""
/* ===== 全局 ===== */
QWidget {{
    background-color: {p['BG_MAIN']};
    color: {p['FG_TEXT']};
    font-family: {_FONT_STACK};
    font-size: 9pt;
}}

QMainWindow, QDialog {{
    background-color: {p['BG_MAIN']};
}}

/* ===== 卡片容器（包装侧栏/trace/过滤器/发送面板） ===== */
QFrame#card {{
    background-color: {p['BG_CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 10px;
}}
QFrame#cardFlat {{
    background-color: {p['BG_CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
}}

/* ===== 自定义标题栏 ===== */
QFrame#macTitleBar {{
    background-color: {p['BG_MAIN']};
    border-bottom: 1px solid {p['BORDER_SOFT']};
}}

QLabel#macTitleLabel {{
    background-color: transparent;
    color: {p['FG_TEXT']};
    font-size: 13px;
    font-weight: 600;
}}

QToolButton#trafficLight {{
    background-color: {p['TL_RED']};
    border: none;
    border-radius: 6px;
    min-width: 12px;
    min-height: 12px;
    max-width: 12px;
    max-height: 12px;
    margin: 0;
    padding: 0;
}}
QToolButton#trafficLight[yellow="true"] {{ background-color: {p['TL_YELLOW']}; }}
QToolButton#trafficLight[green="true"] {{ background-color: {p['TL_GREEN']}; }}
QToolButton#trafficLight:hover {{
    border: 1px solid rgba(0,0,0,0.15);
}}

/* ===== 菜单栏 ===== */
QMenuBar {{
    background-color: transparent;
    border-bottom: none;
    padding: 2px 6px;
    spacing: 2px;
}}
QMenuBar::item {{
    padding: 3px 8px;
    border-radius: 4px;
    background-color: transparent;
}}
QMenuBar::item:selected {{
    background-color: {p['BG_HOVER']};
}}
QMenuBar::item:pressed {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
}}

QMenu {{
    background-color: {p['BG_CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 5px 24px;
    border-radius: 4px;
    color: {p['FG_TEXT']};
}}
QMenu::item:selected {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
}}
QMenu::separator {{
    height: 1px;
    background-color: {p['BORDER_SOFT']};
    margin: 4px 8px;
}}

QToolBar {{
    background-color: transparent;
    border: none;
    spacing: 6px;
    padding: 4px;
}}

/* ===== 状态栏（始终深色，与 Apple 系统底栏风格一致） ===== */
QStatusBar {{
    background-color: {p['BG_STATUS']};
    color: {p['BG_STATUS_FG']};
    border-top: 1px solid #000000;
    font-size: 11px;
    padding: 2px 8px;
}}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{
    background-color: transparent;
    color: {p['BG_STATUS_FG']};
}}
QLabel#statusLabel[connected="true"] {{
    color: #30D158;
    font-weight: 600;
}}
QLabel#statusLabel[connected="false"] {{
    color: #FF6B6B;
    font-weight: 600;
}}
QLabel#busLoad {{
    color: {p['LOAD_LOW']};
    font-weight: 600;
}}
QLabel#busLoad[level="mid"] {{ color: {p['LOAD_MID']}; }}
QLabel#busLoad[level="high"] {{ color: {p['LOAD_HIGH']}; }}

/* ===== 中心分段控件（Segmented Control 样式的 Tab） ===== */
QTabWidget::pane {{
    border: none;
    background-color: transparent;
    top: 4px;
}}
QTabBar {{
    background-color: transparent;
}}
QTabBar::tab {{
    background-color: {p['BG_HOVER']};
    color: {p['FG_DIM']};
    padding: 4px 14px;
    border: 1px solid {p['BORDER']};
    border-radius: 5px;
    margin: 0 2px 3px 2px;
    min-width: 70px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background-color: {p['BG_CARD']};
    color: {p['FG_MACOS_BLUE']};
    border-color: {p['BORDER']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background-color: {p['BORDER_SOFT']};
    color: {p['FG_TEXT']};
}}
QTabBar::tab:disabled {{
    color: {p['FG_DIM']};
    background-color: transparent;
}}
/* 关闭按钮：× 图标，参考 dockCloseBtn 风格 */
QTabBar::close-button {{
    subcontrol-position: right;
    border: none;
    padding: 0;
    margin: 0 2px;
    background: transparent;
    width: 14px;
    height: 14px;
    border-radius: 3px;
    image: url("{_close_svg}");
}}
QTabBar::close-button:hover {{
    background-color: {p['BG_CORAL']};
    image: url("{_close_svg_hover}");
}}

/* ===== 按钮（macOS 胶囊圆角） ===== */
QPushButton {{
    background-color: {p['BG_CARD']};
    color: {p['FG_TEXT']};
    border: 1px solid {p['BORDER']};
    padding: 4px 12px;
    border-radius: 5px;
    min-height: 24px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {p['BG_HOVER']};
    border-color: {p['BORDER']};
}}
QPushButton:pressed {{
    background-color: {p['BG_SELECT']};
}}
QPushButton:disabled {{
    color: {p['FG_DIM']};
    background-color: {p['BG_HEADER']};
    border-color: {p['BORDER_SOFT']};
}}

/* 主蓝色按钮（默认动作） */
QPushButton#primaryBtn {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
    border: none;
    font-weight: 600;
}}
QPushButton#primaryBtn:hover {{ background-color: {p['BG_MACOS_BLUE_H']}; }}
QPushButton#primaryBtn:pressed {{ background-color: {p['BG_MACOS_BLUE_H']}; }}
QPushButton#primaryBtn:disabled {{
    background-color: {p['BG_HEADER']};
    color: {p['FG_DIM']};
}}

/* 连接按钮（绿色主动作） */
QPushButton#connectBtn {{
    font-size: 9.5pt;
    padding: 5px 14px;
    border-radius: 6px;
    font-weight: 600;
}}
QPushButton#connectBtn:checked {{
    background-color: {p['BG_ACCENT']};
    color: white;
    border: none;
}}
QPushButton#connectBtn:checked:hover {{ background-color: {p['BG_ACCENT_H']}; }}
QPushButton#connectBtn:!checked {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
    border: none;
}}
QPushButton#connectBtn:!checked:hover {{ background-color: {p['BG_MACOS_BLUE_H']}; }}

/* 发送一次按钮 */
QPushButton#sendBtn {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
    font-weight: 600;
    border: none;
    border-radius: 5px;
    padding: 4px 12px;
}}
QPushButton#sendBtn:hover {{ background-color: {p['BG_MACOS_BLUE_H']}; }}

/* 启停切换按钮：运行中（running=true）用绿色背景提示"点击停止" */
QPushButton#toggleBtn[running="true"] {{
    background-color: {p['BG_ACCENT']};
    color: white;
    font-weight: 600;
    border: none;
    border-radius: 5px;
    padding: 4px 12px;
}}
QPushButton#toggleBtn[running="true"]:hover {{ background-color: {p['BG_ACCENT_H']}; }}

/* 工具按钮（带图标） */
QToolButton#iconBtn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 10px 4px 8px;
    color: {p['FG_TEXT']};
    text-align: left;
    qproperty-toolButtonStyle: ToolButtonTextBesideIcon;
}}
QToolButton#iconBtn:hover {{
    background-color: {p['BG_HOVER']};
    border-color: {p['BORDER_SOFT']};
}}
QToolButton#iconBtn:pressed {{
    background-color: {p['BG_SELECT']};
}}
QToolButton#iconBtn:checked {{
    background-color: {p['BG_SELECT']};
    color: {p['FG_MACOS_BLUE']};
    border-color: {p['BG_MACOS_BLUE']};
}}

/* ===== 输入控件 ===== */
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit {{
    background-color: {p['BG_INPUT']};
    color: {p['FG_TEXT']};
    border: 1px solid {p['BORDER']};
    padding: 3px 6px;
    border-radius: 5px;
    selection-background-color: {p['BG_MACOS_BLUE']};
    selection-color: white;
}}
QComboBox:hover, QLineEdit:hover, QSpinBox:hover {{
    border-color: {p['BG_MACOS_BLUE']};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{
    border-color: {p['BG_MACOS_BLUE']};
}}
QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    background-color: {p['BG_HEADER']};
    color: {p['FG_DIM']};
    border-color: {p['BORDER_SOFT']};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    background-color: transparent;
}}
QComboBox::down-arrow {{
    image: url("{_arrow_svg}");
    width: 8px;
    height: 8px;
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['BG_CARD']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    selection-background-color: {p['BG_MACOS_BLUE']};
    selection-color: white;
    outline: none;
    padding: 4px;
    /* 下拉列表本身不要圆角 item，避免渲染异常；item 用 padding + hover 美化 */
}}
QComboBox QAbstractItemView::item {{
    padding: 5px 10px;
    min-height: 22px;
    border-radius: 4px;
    color: {p['FG_TEXT']};
    background-color: transparent;
}}
QComboBox QAbstractItemView::item:hover {{
    background-color: {p['BG_HOVER']};
    color: {p['FG_TEXT']};
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
}}

/* ===== 表格 =====
   表格嵌入到卡片/dock/tab 内，自身不再带圆角与边框，
   避免与外层卡片圆角嵌套产生"直角尖"。 */
QHeaderView::section {{
    background-color: {p['BG_HEADER']};
    color: {p['FG_DIM']};
    padding: 5px 6px;
    border: none;
    border-right: 1px solid {p['BORDER_SOFT']};
    border-bottom: 1px solid {p['BORDER']};
    font-weight: 600;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
}}

QTableView, QTableWidget {{
    background-color: {p['BG_CARD']};
    color: {p['FG_TEXT']};
    gridline-color: transparent;
    selection-background-color: {p['BG_MACOS_BLUE']};
    selection-color: white;
    border: none;
    border-radius: 0;
    outline: none;
}}
QTableView::item, QTableWidget::item {{
    background-color: transparent;
    padding: 2px 6px;
    border-bottom: 1px solid {p['BORDER_SOFT']};
}}
QTableView::item:selected, QTableWidget::item:selected {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
}}
QTableView::item:alternate, QTableWidget::item:alternate {{
    background-color: {p['BG_HEADER']};
}}

QTreeView, QListWidget {{
    background-color: {p['BG_CARD']};
    color: {p['FG_TEXT']};
    border: none;
    border-radius: 0;
    selection-background-color: {p['BG_MACOS_BLUE']};
    selection-color: white;
    outline: none;
    padding: 2px;
}}
QTreeView::item, QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid {p['BORDER_SOFT']};
    border-radius: 4px;
}}
QTreeView::item:selected, QListWidget::item:selected {{
    background-color: {p['BG_MACOS_BLUE']};
    color: white;
}}

/* ===== 滚动条（macOS overlay 风格） ===== */
QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: transparent;
    border: none;
    width: 8px;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle {{
    background-color: {p['FG_DIM']};
    border-radius: 4px;
    min-height: 30px;
    min-width: 30px;
}}
QScrollBar::handle:hover {{
    background-color: {p['FG_TEXT']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background-color: transparent;
}}

/* ===== GroupBox（卡片化） =====
   sidebarCard 内的 GroupBox 改为 flat 样式（无 border、无 radius），
   避免与 sidebarCard 的圆角嵌套产生直角尖。 */
QGroupBox {{
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    margin-top: 11px;
    padding: 10px 6px 6px 6px;
    font-weight: 600;
    background-color: {p['BG_CARD']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {p['FG_MACOS_BLUE']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
/* sidebarCard 内的 GroupBox：flat，无圆角无 border，避免嵌套尖角 */
QFrame#sidebarCard QGroupBox {{
    border: none;
    border-radius: 0;
    margin-top: 6px;
    padding: 4px 2px 2px 2px;
    background-color: transparent;
}}
QFrame#sidebarCard QGroupBox::title {{
    left: 4px;
    padding: 0 4px;
}}

/* ===== 复选框 ===== */
QCheckBox {{
    spacing: 6px;
    color: {p['FG_TEXT']};
    background-color: transparent;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {p['BORDER']};
    border-radius: 4px;
    background-color: {p['BG_INPUT']};
}}
QCheckBox::indicator:hover {{
    border-color: {p['BG_MACOS_BLUE']};
}}
QCheckBox::indicator:checked {{
    background-color: {p['BG_MACOS_BLUE']};
    border-color: {p['BG_MACOS_BLUE']};
    image: url("{_check_svg}");
}}

QGroupBox QLabel {{ background-color: transparent; }}
QGroupBox QCheckBox {{ background-color: transparent; }}
QLabel:disabled {{ color: {p['FG_DIM']}; }}

/* ===== Splitter & Dock Separator =====
   统一 splitter handle 和 QMainWindow::separator 的视觉风格：
   4px 拖动宽度 + 中间 1px 细线，左右间隔一致。 */
QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:horizontal {{
    width: 4px;
    background-color: transparent;
    border-left: 1px solid {p['BORDER_SOFT']};
    margin-left: 1px;
    margin-right: 1px;
}}
QSplitter::handle:vertical {{
    height: 4px;
    background-color: transparent;
    border-top: 1px solid {p['BORDER_SOFT']};
    margin-top: 1px;
    margin-bottom: 1px;
}}
QMainWindow::separator:horizontal {{
    width: 4px;
    background-color: transparent;
    border-left: 1px solid {p['BORDER_SOFT']};
    margin-left: 1px;
    margin-right: 1px;
}}
QMainWindow::separator:vertical {{
    height: 4px;
    background-color: transparent;
    border-top: 1px solid {p['BORDER_SOFT']};
    margin-top: 1px;
    margin-bottom: 1px;
}}
QMainWindow::separator:hover {{
    background-color: {p['BG_HOVER']};
}}

/* ===== Dock Widget =====
   dock 整体作为一个圆角卡片：dockTitleBar 顶部圆角 + 内容区底部圆角，
   中间无 border 分割，避免 titleBar 与内容圆角嵌套产生的尖角。 */
QFrame#sidebar {{
    background-color: transparent;
    border: none;
}}
QFrame#sidebarCard {{
    background-color: {p['BG_SIDEBAR']};
    border: 1px solid {p['BORDER_SOFT']};
    border-radius: 10px;
}}
QDockWidget {{
    border: 1px solid {p['BORDER_SOFT']};
    border-radius: 10px;
    background-color: {p['BG_CARD']};
}}
QDockWidget > QWidget {{
    background-color: {p['BG_CARD']};
    border-bottom-left-radius: 10px;
    border-bottom-right-radius: 10px;
}}
QFrame#dockTitleBar {{
    background-color: {p['BG_HEADER']};
    border: none;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    border-bottom: 1px solid {p['BORDER_SOFT']};
}}
QLabel#dockTitle {{
    color: {p['FG_MACOS_BLUE']};
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    background-color: transparent;
    padding-left: 4px;
}}
QToolButton#dockCloseBtn {{
    border: none;
    color: {p['FG_DIM']};
    font-weight: bold;
    font-size: 13px;
    background-color: transparent;
    border-radius: 4px;
    padding: 2px 6px;
}}
QToolButton#dockCloseBtn:hover {{
    background-color: {p['BG_CORAL']};
    color: white;
}}

/* 左侧 sidebar 收起后的浮动恢复按钮：窄长条，圆角右侧 */
QPushButton#sidebarRestoreBtn {{
    background-color: {p['BG_CARD']};
    color: {p['FG_DIM']};
    border: 1px solid {p['BORDER']};
    border-left: none;
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
    font-size: 12px;
    font-weight: bold;
    padding: 0;
}}
QPushButton#sidebarRestoreBtn:hover {{
    background-color: {p['BG_HOVER']};
    color: {p['FG_MACOS_BLUE']};
}}

/* ===== Tooltip ===== */
QToolTip {{
    background-color: {p['BG_CARD']};
    color: {p['FG_TEXT']};
    border: 1px solid {p['BORDER']};
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 11px;
}}

/* ===== 对话框 ===== */
QMessageBox {{
    background-color: {p['BG_CARD']};
}}
QMessageBox QLabel {{
    color: {p['FG_TEXT']};
    background-color: transparent;
    font-size: 13px;
}}
QMessageBox QPushButton {{
    min-width: 80px;
    padding: 6px 18px;
    border-radius: 6px;
}}

QFileDialog {{
    background-color: {p['BG_MAIN']};
}}
QFileDialog QPushButton {{
    min-width: 72px;
}}

QInputDialog {{
    background-color: {p['BG_CARD']};
}}
"""


def _update_globals(pal: dict):
    global BG_MAIN, BG_CARD, BG_INPUT, BG_HEADER, BG_HOVER, BG_SELECT
    global BG_ACCENT, BG_ACCENT_H, BG_MACOS_BLUE, BG_MACOS_BLUE_H
    global BG_CORAL, BG_CORAL_H, BG_SIDEBAR, BG_STATUS, BG_STATUS_FG
    global BG_TX, BG_ERROR
    global FG_TEXT, FG_DIM, FG_ACCENT, FG_MACOS_BLUE
    global FG_CORAL, FG_WARN, FG_ERROR, FG_LINK
    global BORDER, BORDER_SOFT
    global LOAD_LOW, LOAD_MID, LOAD_HIGH
    global TL_RED, TL_YELLOW, TL_GREEN
    global TL_RED_GLYPH, TL_YELLOW_GLYPH, TL_GREEN_GLYPH
    global _p
    _p = pal.copy()
    for k, v in pal.items():
        globals()[k] = v


def get_qss() -> str:
    return _make_qss(_p)


def set_theme(name: str):
    global _current_theme
    pal = _DARK if name == "dark" else _LIGHT
    _current_theme = name
    _update_globals(pal)


def current_theme() -> str:
    return _current_theme


# 初始 QSS
QSS = get_qss()
