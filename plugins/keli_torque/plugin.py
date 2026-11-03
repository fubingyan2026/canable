"""柯力扭矩传感器监视插件入口。

依据 docs/柯力扭矩传感器CAN协议帧V1.2.md，导出 create_plugin() 供 PluginHost 加载。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cangui.plugin_host import Plugin, PluginContext
from cangui.i18n import _

from .widget import KeliPanel, _I18N_KEYS


class KeliTorquePlugin(Plugin):
    """柯力传感器：连续/单次读数、归零、参数、版本、重启、波形与记录。"""

    name = "keli_torque"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[KeliPanel] = None

    def init(self, ctx: PluginContext) -> None:
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self) -> str:
        return _("Keli.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = KeliPanel(ctx)
        return self._panel

    def on_activated(self) -> None:
        if self._panel is not None:
            self._panel.on_activated()

    def on_deactivating(self) -> None:
        if self._panel is not None:
            self._panel.on_deactivating()

    def confirm_close(self) -> bool:
        if self._panel is not None:
            return self._panel.confirm_close()
        return True

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


def create_plugin() -> KeliTorquePlugin:
    return KeliTorquePlugin()
