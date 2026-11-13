"""Dual-axis position plugin and translations."""
from cangui.plugin_host import Plugin

from .widget import PositionPanel, tr


_TEXT = {
    "Title": ("良志双电机位置控制", "Liangzhi Dual Motor Position"),
    "Motor": ("电机 {node}", "Motor {node}"),
    "GearRatio": ("减速比（转子:输出轴）", "Gear ratio (rotor/output)"),
    "Transport": ("帧格式", "Frame format"),
    "Classic": ("Classic CAN", "Classic CAN"),
    "Fd": ("CAN FD", "CAN FD"),
    "Brs": ("CAN FD + BRS", "CAN FD + BRS"),
    "Mode": ("位置输入方式", "Position input mode"),
    "Filtered": ("位置滤波", "Position filter"),
    "Direct": ("直接输入", "Direct"),
    "Trapezoidal": ("梯形轨迹", "Trapezoidal trajectory"),
    "SetMode": ("设置位置模式", "Set position mode"),
    "ClosedLoop": ("进入闭环", "Enter closed loop"),
    "Idle": ("退出闭环 / 空闲", "Request idle"),
    "Clear": ("清除故障", "Clear faults"),
    "Estop": ("急停", "Emergency stop"),
    "Target": ("输出轴目标 (rad)", "Output target (rad)"),
    "Velocity": ("输出轴速度前馈 (rad/s)", "Output velocity FF (rad/s)"),
    "Torque": ("驱动力矩前馈 (Nm)", "Drive torque FF (Nm)"),
    "SendTarget": ("发送目标位置", "Send target position"),
    "TrajectorySpeed": ("轨迹限速 (rad/s)", "Speed limit (rad/s)"),
    "SetSpeed": ("设置轨迹限速", "Set trajectory limit"),
    "JogStep": ("点动步长 (rad)", "Jog step (rad)"),
    "JogMinus": ("负向点动", "Jog −"),
    "JogPlus": ("正向点动", "Jog +"),
    "SliderRange": ("滑块范围 (rad)", "Slider range (rad)"),
    "Slider": ("拖动发送位置", "Drag to send position"),
    "Waiting": ("等待轴状态心跳", "Waiting for the axis heartbeat"),
    "AxisState": ("轴状态 {state} · 故障 0x{error:08X}", "Axis state {state} · Fault 0x{error:08X}"),
    "StateIdle": ("空闲 (1)", "Idle (1)"),
    "StateClosed": ("闭环 (8)", "Closed loop (8)"),
    "Feedback": ("输出轴位置 {position:.4f} rad · 速度 {velocity:.4f} rad/s",
                 "Output position {position:.4f} rad · Velocity {velocity:.4f} rad/s"),
    "Queued": ("已提交 0x{can_id:03X}", "Queued 0x{can_id:03X}"),
    "PositionQueued": ("已提交位置 {position:g} rad · 0x{can_id:03X}", "Queued position {position:g} rad · 0x{can_id:03X}"),
    "Disconnected": ("CAN 未连接", "CAN disconnected"),
    "NeedFd": ("请先在主界面启用 CAN FD。", "Enable CAN FD in the main window first."),
    "InvalidRange": ("滑块下限须小于上限。", "The slider minimum must be below its maximum."),
    "JogNeedsPosition": ("点动需要位置反馈或已下发的目标位置。", "Jogging requires position feedback or a previously sent target."),
    "InvalidTarget": ("目标超出可设置范围。", "The target is outside the supported range."),
    "InvalidVelocity": ("速度前馈超出当前减速比下的范围（{low:.3f} 至 {high:.3f} rad/s）。",
                        "Velocity feedforward is outside the range at this ratio ({low:.3f} to {high:.3f} rad/s)."),
    "Firmware": ("固件参数表", "Firmware table"),
    "ChooseFirmware": ("选择对应固件", "Select matching firmware"),
    "ImportFirmware": ("导入端点表", "Import endpoints"),
    "NeedFirmware": ("请先选择与电机固件匹配的端点表。", "Select the endpoint table matching the drive firmware first."),
    "InvalidFirmware": ("无法读取端点表 {name}。", "Could not read endpoint table {name}."),
    "ZeroUnavailable": ("该端点表没有 set_current_pos_zero。请按该固件的标零流程操作。",
                        "This table has no set_current_pos_zero. Use the procedure for this firmware."),
    "Zero": ("标零当前位置", "Zero current position"),
    "ZeroHint": ("先退回空闲，将输出轴放到需要的零位。", "Request idle and place the output shaft at the desired zero position."),
    "ZeroQueued": ("已提交标零 0x{can_id:03X}。请查看位置反馈。", "Queued zero command 0x{can_id:03X}. Check position feedback."),
    "SaveDrive": ("保存驱动并重启", "Save drive and reboot"),
    "DriveSaveQueued": ("已提交保存并重启 0x{can_id:03X}。等待驱动恢复心跳。",
                        "Queued save and reboot 0x{can_id:03X}. Wait for the drive heartbeat."),
    "SaveSettings": ("保存界面设置", "Save UI settings"),
    "SettingsSaved": ("两轴界面设置已保存。", "UI settings for both axes saved."),
}


class PositionPlugin(Plugin):
    name = "liangzhi_position"
    version = "1.0.0"

    def init(self, ctx):
        for key, (zh, en) in _TEXT.items():
            ctx.register_i18n(f"LiangzhiPosition.{key}", zh, en)

    def display_title(self):
        return tr("Title")

    def build_widget(self, ctx):
        return PositionPanel(ctx)

    def teardown_widget(self, widget):
        widget.reset_feedback()
        super().teardown_widget(widget)

    def on_connect(self):
        self._widget.reset_feedback()

    def on_disconnect(self):
        self._widget.reset_feedback()

    def on_frames(self, frames):
        self._widget.on_frames(frames)

    def refresh_language(self):
        if self._widget is not None:
            self._widget.refresh_language()


def create_plugin():
    return PositionPlugin()
