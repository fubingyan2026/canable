"""合壹电池 BMS 数据监视插件入口。

依据 docs/合壹电池CAN通讯协议中英文对照.md，导出 `create_plugin()` 供 PluginHost 加载。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cangui.plugin_host import Plugin, PluginContext
from cangui.i18n import _

from .widget import BatteryPanel, _I18N_KEYS


class BatteryMonitorPlugin(Plugin):
    """合壹电池：定时请求电压/电流状态/SOC/编号并显示。"""

    name = "battery_monitor"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[BatteryPanel] = None

    def init(self, ctx: PluginContext) -> None:
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self) -> str:
        return _("Batt.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = BatteryPanel(ctx)
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


def create_plugin() -> BatteryMonitorPlugin:
    return BatteryMonitorPlugin()
