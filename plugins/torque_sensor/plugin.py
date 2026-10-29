"""G0 双路扭矩传感器读取插件入口。

依据 torque_sensor_can_protocol_zh.md，导出 `create_plugin()` 供 PluginHost 加载。
负责：
1. 在 `init()` 中注册全部 i18n key（不修改 cangui/i18n.py）
2. `build_widget()` 创建 TorqueSensorPanel
3. 转发插件回调（on_connect / on_disconnect / on_frames / refresh_language）
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMessageBox, QWidget

from cangui.plugin_host import Plugin, PluginContext
from cangui.i18n import _

from .widget import TorqueSensorPanel, _I18N_KEYS


class TorqueSensorPlugin(Plugin):
    """双路扭矩传感器实时数据读取插件。"""

    name = "torque_sensor"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[TorqueSensorPanel] = None

    # ── 生命周期 ──
    def init(self, ctx: PluginContext) -> None:
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self) -> str:
        return _("Torque.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = TorqueSensorPanel(ctx)
        return self._panel

    def on_activated(self) -> None:
        if self._panel is not None:
            self._panel.on_activated()

    def on_deactivating(self) -> None:
        if self._panel is not None:
            self._panel.on_deactivating()

    def confirm_close(self) -> bool:
        """扫描/改号进行中不允许关闭 Tab（改号中途中断有风险）。"""
        if self._panel is not None and self._panel.is_busy():
            QMessageBox.warning(self._panel, _("Torque.Title"),
                                _("Torque.SetId.Busy"))
            return False
        return True

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


def create_plugin() -> TorqueSensorPlugin:
    """PluginHost 通过此工厂函数实例化插件。"""
    return TorqueSensorPlugin()
