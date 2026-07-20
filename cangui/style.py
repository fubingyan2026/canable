"""CANable 2.5 style -- Qt default style with minimal functional overrides."""

# 简化的颜色定义（仅用于程序逻辑，不用于 QSS）
BG_TX = "#E8F8EC"
BG_ERROR = "#FFE5E5"
LOAD_LOW = "#34C759"
LOAD_MID = "#FF9500"
LOAD_HIGH = "#FF3B30"
FG_TEXT = "#1D1D1F"
FG_DIM = "#86868B"
FG_ACCENT = "#34C759"


def id_color(can_id: int, extended: bool = False) -> str:
    """CAN ID 着色：按哈希生成 HSL 色，同 ID 颜色一致、不同 ID 视觉可分。"""
    if extended:
        hue = ((can_id >> 16) ^ (can_id & 0xFFFF)) % 360
    else:
        hue = (can_id * 7) % 360
    return f"hsl({hue}, 55%, 55%)"


def _make_qss() -> str:
    """返回最小化 QSS，只保留功能性样式（状态栏连接状态、总线负载级别）。"""
    return """
/* ===== 状态栏连接状态指示 ===== */
QLabel#statusLabel[connected="true"] {
    color: #30D158;
    font-weight: 600;
}
QLabel#statusLabel[connected="false"] {
    color: #FF6B6B;
    font-weight: 600;
}

/* ===== 总线负载级别颜色 ===== */
QLabel#busLoad {
    color: #34C759;
    font-weight: 600;
}
QLabel#busLoad[level="mid"] { color: #FF9500; }
QLabel#busLoad[level="high"] { color: #FF3B30; }
"""


def get_qss() -> str:
    return _make_qss()


def set_theme(name: str):
    """主题切换（向后兼容，实际不做任何操作）。"""
    pass


def current_theme() -> str:
    """返回当前主题（向后兼容）。"""
    return "light"


QSS = get_qss()
