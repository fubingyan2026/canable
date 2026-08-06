"""主电源板监控插件入口。

导出 `create_plugin()` 供 PluginHost 加载。负责：
1. 在 `init()` 中注册全部 i18n key（避免修改 cangui/i18n.py）
2. `build_widget()` 创建 PowerMonitorPanel
3. 转发插件回调（on_connect / on_disconnect / on_frames / refresh_language）
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cangui.plugin_host import Plugin, PluginContext
from cangui.i18n import _

from .widget import PowerMonitorPanel, _I18N_KEYS, DESC_I18N, RAIL_DESC, FAULT_I18N


class PowerMonitorPlugin(Plugin):
    """主电源板实时监控插件。"""

    name = "power_monitor"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[PowerMonitorPanel] = None

    # ── 生命周期 ──
    def init(self, ctx: PluginContext) -> None:
        # 注册全部 i18n key（运行时合并到 cangui.i18n._TR）
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)
        for suffix, (zh, en) in DESC_I18N.items():
            ctx.register_i18n(f"Power.Desc.{suffix}", zh, en)
        for name, (zh, en) in RAIL_DESC.items():
            ctx.register_i18n(f"Power.Desc.Rail.{name}", zh, en)
        for field, (zh, en) in FAULT_I18N.items():
            ctx.register_i18n(f"Power.Fault.{field}", zh, en)

    def display_title(self) -> str:
        return _("Power.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = PowerMonitorPanel(ctx)
        return self._panel

    def on_activated(self) -> None:
        if self._panel is not None:
            self._panel.on_activated()

    def on_deactivating(self) -> None:
        if self._panel is not None:
            self._panel.on_deactivating()

    def teardown_widget(self, widget: QWidget) -> None:
        widget.deleteLater()
        self._panel = None

    # ── 回调转发 ──
    def on_connect(self) -> None:
        if self._panel is not None:
            self._panel.on_connect()

    def on_disconnect(self) -> None:
        if self._panel is not None:
            self._panel.on_disconnect()

    def on_frames(self, frames) -> None:
        if self._panel is not None:
            self._panel.on_frames(frames)

    def refresh_language(self) -> None:
        if self._panel is not None:
            self._panel.refresh_language()


def create_plugin() -> PowerMonitorPlugin:
    """PluginHost 通过此工厂函数实例化插件。"""
    return PowerMonitorPlugin()
