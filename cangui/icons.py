"""SF Symbols 风格 SVG 图标集（嵌入式，主题感知）。

通过 :func:`make_icon` 生成 :class:`QIcon`，颜色随当前主题的 ``FG_TEXT`` 变化。
面板在 ``refresh_language`` / 主题切换时调用 ``refresh_icons`` 重新生成图标。

所有图标使用 16x16 viewBox，采用 Apple SF Symbols 的简化几何形状。
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

# SVG 模板：使用 {color} 占位符，运行时替换为实际颜色
_SVG_TEMPLATES: dict[str, str] = {
    # 清空 / 删除：垃圾桶
    "trash": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M5.2 5h5.6l-.5 8.2a1 1 0 01-1 .8H6.7a1 1 0 01-1-.8L5.2 5z" fill="{color}"/>
  <rect x="3.3" y="3.2" width="9.4" height="1.5" rx="0.7" fill="{color}"/>
  <path d="M6.5 3.2v-.6a.8.8 0 01.8-.8h1.4a.8.8 0 01.8.8v.6" stroke="{color}" stroke-width="1.2" fill="none" stroke-linecap="round"/>
</svg>''',
    # 暂停：两条竖线
    "pause": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="3.8" y="3" width="3" height="10" rx="1" fill="{color}"/>
  <rect x="9.2" y="3" width="3" height="10" rx="1" fill="{color}"/>
</svg>''',
    # 播放/继续/启动：三角形
    "play": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M4 2.8l9.2 5.2L4 13.2V2.8z" fill="{color}"/>
</svg>''',
    # 停止：方块
    "stop": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="3.5" y="3.5" width="9" height="9" rx="1.2" fill="{color}"/>
</svg>''',
    # 发送：纸飞机
    "send": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M14.5 1.5L1.5 7.5l4.5 1.3L7.3 13l2-3.3 3.2 2.2L14.5 1.5zM6.6 8.4l5.5-4-4 4.5-.4 2.2-1.1-2.7z" fill="{color}"/>
</svg>''',
    # 添加：加号
    "plus": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M7 3v4H3v2h4v4h2V9h4V7H9V3H7z" fill="{color}"/>
</svg>''',
    # 编辑：铅笔
    "pencil": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M11.2 1.8l2.7 2.7-8.5 8.5H2.7v-2.7l8.5-8.5z" fill="{color}"/>
  <path d="M10 3l2.7 2.7" stroke="#FFFFFF" stroke-width="0.6" fill="none"/>
</svg>''',
    # 扫描：循环箭头
    "scan": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M14 8a6 6 0 11-2.5-4.85L13.5 1.5v4h-4l1.7-1.7A5 5 0 1013 8h1z" fill="{color}"/>
</svg>''',
    # 连接：电源符号
    "power": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M8 2v5" stroke="{color}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <path d="M4.5 3.8a5.5 5.5 0 107 0" stroke="{color}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
</svg>''',
    # 断开：电源带斜线
    "power_off": '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M8 2v5" stroke="{color}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <path d="M4.5 3.8a5.5 5.5 0 107 0" stroke="{color}" stroke-width="1.6" fill="none" stroke-linecap="round"/>
  <path d="M2 2l12 12" stroke="{color}" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.6"/>
</svg>''',
}

# 图标缓存：(name, color) → QIcon。主题切换时清空
_cache: dict[tuple[str, str], QIcon] = {}


def _render_svg(svg: str, color: str, size: int = 16) -> QPixmap:
    """渲染 SVG 字符串为指定颜色的 QPixmap。"""
    svg_colored = svg.replace("{color}", color)
    renderer = QSvgRenderer(QByteArray(svg_colored.encode("utf-8")))
    if not renderer.isValid():
        # SVG 渲染失败时返回空 pixmap
        return QPixmap(size, size)
    # 2x 渲染保证 High-DPI 清晰
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return pixmap


def make_icon(name: str, color: str | None = None, size: int = 16) -> QIcon:
    """生成主题感知的图标。

    Args:
        name: 图标名（trash/pause/play/stop/send/plus/pencil/scan/power/power_off）
        color: 颜色（默认从当前主题取 ``FG_TEXT``）
        size: 像素尺寸（默认 16）
    """
    from .style import FG_TEXT
    color = color or FG_TEXT
    key = (name, color)
    if key in _cache:
        return _cache[key]
    svg = _SVG_TEMPLATES.get(name)
    if svg is None:
        return QIcon()
    pixmap = _render_svg(svg, color, size)
    icon = QIcon(pixmap)
    _cache[key] = icon
    return icon


def clear_cache() -> None:
    """清空图标缓存。主题切换时调用，强制重新渲染。"""
    _cache.clear()


def available_icons() -> list[str]:
    return list(_SVG_TEMPLATES.keys())
