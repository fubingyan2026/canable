"""捷电机控制插件入口。"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget

from cangui.plugin_host import Plugin, PluginContext
from cangui.i18n import _

from .widget import JuxieMotorPanel

_I18N_KEYS = {
    "Juxie.Title":              ("捷电机控制",          "Juxie Motor Control"),
    "Juxie.DevConfig":          ("设备配置",            "Device Config"),
    "Juxie.DevID":              ("设备 ID",             "Device ID"),
    "Juxie.MITControl":         ("MIT 控制",            "MIT Control"),
    "Juxie.Enable":             ("上使能",              "Enable"),
    "Juxie.Brake":              ("抱闸释放",            "Brake Release"),
    "Juxie.ClearError":         ("清除错误",            "Clear Error"),
    "Juxie.AutoSend":           ("滑动自动发送",        "Auto-send on slide"),
    "Juxie.PosMax":             ("位置最大",            "Max Position"),
    "Juxie.VelMax":             ("速度最大",            "Max Speed"),
    "Juxie.TorqueMax":          ("力矩最大",            "Max Torque"),
    "Juxie.TargetPos":          ("目标位置",            "Target Position"),
    "Juxie.TargetVel":          ("目标速度",            "Target Speed"),
    "Juxie.Kp":                 ("位置增益 Kp",         "Kp"),
    "Juxie.Kd":                 ("速度增益 Kd",         "Kd"),
    "Juxie.TargetTorque":       ("目标力矩",            "Target Torque"),
    "Juxie.SendMIT":            ("发送 MIT 指令",       "Send MIT Command"),
    "Juxie.RequestFeedback":    ("请求反馈",            "Request Feedback"),
    "Juxie.Feedback":           ("反馈显示",            "Feedback"),
    "Juxie.Position":           ("位置",                "Position"),
    "Juxie.Speed":              ("速度",                "Speed"),
    "Juxie.Current":            ("电流",                "Current"),
    "Juxie.Temperature":        ("温度",                "Temperature"),
    "Juxie.Torque":             ("力矩",                "Torque"),
    "Juxie.ErrorCode":          ("错误码",              "Error Code"),
    "Juxie.ModeFeedback":       ("模式反馈",            "Mode Feedback"),
    "Juxie.Status":             ("状态",                "Status"),
    "Juxie.LastUpdate":         ("最后更新",            "Last Update"),
    "Juxie.Offline":            ("离线",                "Offline"),
    "Juxie.NoData":             ("—",                   "—"),
    "Juxie.Mode.ProfilePos":    ("轮廓位置模式",        "Profile Position"),
    "Juxie.Mode.ProfileVel":    ("轮廓速度模式",        "Profile Velocity"),
    "Juxie.Mode.CSP":          ("CSP 位置模式",        "CSP Position"),
    "Juxie.Mode.CSV":          ("CSV 速度模式",        "CSV Velocity"),
    "Juxie.Mode.Current":       ("电流环模式",          "Current Loop"),
    "Juxie.Mode.Torque":        ("力矩环模式",          "Torque Loop"),
    "Juxie.Mode.MIT":          ("MIT 模式",            "MIT Mode"),
    "Juxie.Status.Enabled":     ("已使能",              "Enabled"),
    "Juxie.Status.Disabled":    ("下使能",              "Disabled"),
    "Juxie.Status.BrakeOn":     ("抱闸吸合",            "Brake On"),
    "Juxie.Status.BrakeOff":    ("抱闸释放",            "Brake Off"),
    "Juxie.Status.Error":       ("报错",                "Error"),
    "Juxie.Status.Normal":      ("正常",                "Normal"),
    "Juxie.Status.InPosition":  ("到位",                "In Position"),
    "Juxie.Status.Running":     ("运行中",              "Running"),
    "Juxie.Unit.Deg":          ("°",                   "°"),
    "Juxie.Unit.RPM":          ("RPM",                 "RPM"),
    "Juxie.Unit.mA":           ("mA",                  "mA"),
    "Juxie.Unit.Nm":           ("Nm",                  "Nm"),
    "Juxie.Unit.Celsius":      ("℃",                   "℃"),
    "Juxie.Err.NotConnected":  ("CAN 未连接",          "CAN not connected"),
}


class JuxieMotorPlugin(Plugin):
    name = "juxie_motor"
    version = "0.1.0"

    def __init__(self):
        super().__init__()
        self._panel: Optional[JuxieMotorPanel] = None

    def init(self, ctx: PluginContext) -> None:
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self) -> str:
        return _("Juxie.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        self._panel = JuxieMotorPanel(ctx)
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


def create_plugin() -> JuxieMotorPlugin:
    return JuxieMotorPlugin()
