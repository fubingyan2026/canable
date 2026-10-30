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
    "Juxie.Mirror":             ("镜像",                "Mirror"),
    "Juxie.MirrorID":           ("镜像 ID",             "Mirror ID"),
    "Juxie.TargetMax":          ("角度上限",            "Angle Max"),
    "Juxie.Primary":            ("主电机",              "Primary"),
    "Juxie.MirrorTag":          ("镜像电机",            "Mirror"),
    "Juxie.MITControl":         ("MIT 控制",            "MIT Control"),
    "Juxie.Enable":             ("上使能",              "Enable"),
    "Juxie.Brake":              ("抱闸释放",            "Brake Release"),
    "Juxie.ClearError":         ("清除故障",            "Clear Fault"),
    "Juxie.ClearSent":          ("已发送清除故障指令…",  "Clear-fault command sent…"),
    "Juxie.ClearOk":            ("故障已清除",           "Fault cleared"),
    "Juxie.ClearFailed":        ("仍报错 {code}，请检查使能状态与故障源",
                                 "Still faulted {code}; check enable state and fault source"),
    "Juxie.ClearNoFeedback":    ("已发送清除指令，但未收到反馈",
                                 "Clear sent but no feedback received"),
    "Juxie.Zero":               ("标零",                 "Set Zero"),
    "Juxie.ZeroConfirm":        ("确认将两台电机当前位置设为零点？\n\n"
                                 "请在电机处于目标机械位置、且已停止运动时执行；"
                                 "标零会改变位置参考，可能导致后续目标位置跳变。",
                                 "Set both motors' current position as zero?\n\n"
                                 "Only do this at the desired mechanical position with the "
                                 "motors at rest; zeroing changes the position reference and "
                                 "may cause subsequent target jumps."),
    "Juxie.ZeroSent":           ("已发送标零命令（两台电机，SDO 0x2531=1）",
                                 "Zero command sent to both motors (SDO 0x2531=1)"),
    "Juxie.AutoSend":           ("滑动自动发送",        "Auto-send on slide"),
    "Juxie.PosMax":             ("位置最大",            "Max Position"),
    "Juxie.VelMax":             ("速度最大",            "Max Speed"),
    "Juxie.TorqueMax":          ("力矩最大",            "Max Torque"),
    "Juxie.TargetPos":          ("目标位置",            "Target Position"),
    "Juxie.TargetVel":          ("目标速度",            "Target Speed"),
    "Juxie.Kp":                 ("位置增益 Kp",         "Kp"),
    "Juxie.Kd":                 ("速度增益 Kd",         "Kd"),
    "Juxie.TargetTorque":       ("目标力矩",            "Target Torque"),
    "Juxie.ScaleReset":         ("「力矩最大」异常过小({v:g} Nm)，已恢复为默认 {d:g} Nm",
                                 "Torque Max was implausibly small ({v:g} Nm); "
                                 "restored to the default {d:g} Nm"),
    "Juxie.SendMIT":            ("发送 MIT 指令",       "Send MIT Command"),
    "Juxie.FrameTip":           ("最后一帧的原始 12bit 字段。tq=2048 表示前馈为 0 Nm；"
                                 "tq 到 0 或 4095 表示已饱和到满力矩（请检查「力矩最大」是否等于电机 T_Max）",
                                 "Raw 12-bit fields of the last frame. tq=2048 means 0 Nm "
                                 "feedforward; tq=0/4095 means saturated to full torque "
                                 "(check whether Torque Max equals the motor's T_Max)"),
    "Juxie.TorqueRaw":          ("力矩直发(raw)",       "Raw torque"),
    "Juxie.TorqueRawTip":       ("勾选后目标力矩改为直接下发 12bit 原始值 0~4095（不走 Nm 换算）。"
                                 "双极性映射下 2048≈0 Nm；若发现 0 才是零力矩，说明该电机用的是"
                                 "有符号/单极性映射，需要改换算。",
                                 "When checked, the torque field sends a raw 12-bit value "
                                 "(0-4095) directly. Under the bipolar mapping 2048 is ~0 Nm; "
                                 "if 0 turns out to be zero torque, the motor uses a "
                                 "signed/unipolar mapping and the conversion must change."),
    "Juxie.TorqueZero":         ("力矩零点",            "Torque Zero"),
    "Juxie.TorqueZeroOffset":   ("居中 2048=0",         "Offset 2048=0"),
    "Juxie.TorqueZeroSigned":   ("有符号 0=0",          "Signed 0=0"),
    "Juxie.TorqueZeroTip":      ("力矩字段的零点约定：居中=raw 2048 为零；"
                                 "有符号=12bit 二的补码，raw 0 为零。用「力矩直发」发 0 与 2048 各试一次，"
                                 "哪个让电机不出力就用哪个。",
                                 "Zero convention of the torque field: Offset = raw 2048 is "
                                 "zero; Signed = 12-bit two's complement with raw 0 as zero. "
                                 "Send 0 and 2048 via Raw torque to see which one frees the motor."),
    "Juxie.RequestFeedback":    ("请求反馈",            "Request Feedback"),
    "Juxie.AutoRequest":        ("定时请求",            "Auto Request"),
    "Juxie.ReqInterval":        ("间隔",                "Interval"),
    "Juxie.Continuous":         ("连续发送 MIT",        "Continuous MIT"),
    "Juxie.MitInterval":        ("周期",                "Period"),
    "Juxie.SlewRate":           ("斜坡",                "Slew"),
    "Juxie.AutoClear":          ("周期清错",            "Auto Clear Fault"),
    "Juxie.ClearInterval":      ("清错周期",            "Clear Period"),
    "Juxie.Wave":               ("周期往复",            "Reciprocating"),
    "Juxie.WaveAmp":            ("上限角",              "Amplitude"),
    "Juxie.WavePeriod":         ("运动周期",            "Move Period"),
    "Juxie.WaveHoldHi":         ("上限保持",            "Hold@Max"),
    "Juxie.WaveHoldLo":         ("0°保持",              "Hold@0°"),
    "Juxie.WaveInterval":       ("发送周期",            "Send Period"),
    "Juxie.WaveLog":            ("记录上限中点",        "Log Hold Midpoint"),
    "Juxie.WaveOpenCsv":        ("打开CSV",             "Open CSV"),
    "Juxie.WaveLogFile":        ("记录文件",            "Log file"),
    "Juxie.WaveLogNone":        ("未记录（未启动或未勾选）",
                                 "No log (not started or disabled)"),
    "Juxie.WaveLogFail":        ("创建记录文件失败",    "Failed to create log file"),
    "Juxie.WaveStart":          ("启动往复",            "Start Wave"),
    "Juxie.WaveStop":           ("停止往复",            "Stop Wave"),
    "Juxie.WaveRandStart":      ("启动随机往复",        "Start Random"),
    "Juxie.WaveRandStop":       ("停止随机往复",        "Stop Random"),
    "Juxie.WaveCurAmp":         ("本周期上限 {amp:.1f}°", "This cycle: {amp:.1f}°"),
    "Juxie.WaveRandRunning":    ("随机往复运行中：0° ↔ {amp:g}°，运动 {period:g}s，上限保持 {hi:g}s，0°保持 {lo:g}s，整周期 {total:g}s",
                                 "Random running: 0° ↔ {amp:g}°, move {period:g}s, hold@max {hi:g}s, hold@0° {lo:g}s, cycle {total:g}s"),
    "Juxie.WaveIdle":           ("待启动：0° ↔ {amp:g}°，运动 {period:g}s，上限保持 {hi:g}s，0°保持 {lo:g}s，整周期 {total:g}s",
                                 "Idle: 0° ↔ {amp:g}°, move {period:g}s, hold@max {hi:g}s, hold@0° {lo:g}s, cycle {total:g}s"),
    "Juxie.WaveRunning":        ("运行中：0° ↔ {amp:g}°，运动 {period:g}s，上限保持 {hi:g}s，0°保持 {lo:g}s，整周期 {total:g}s",
                                 "Running: 0° ↔ {amp:g}°, move {period:g}s, hold@max {hi:g}s, hold@0° {lo:g}s, cycle {total:g}s"),
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
    "Juxie.Unit.Ms":           ("ms", "ms"),
    "Juxie.Unit.S":            ("s", "s"),
    "Juxie.Unit.DegS":         ("°/s", "°/s"),
    "Juxie.Err.NotConnected":  ("CAN 未连接",          "CAN not connected"),
    "Juxie.Err.NeedFd":        ("需在主界面启用 CAN FD（MIT 帧为 9 字节）",
                                "Enable CAN FD in the main window (MIT frame is 9 bytes)"),
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
