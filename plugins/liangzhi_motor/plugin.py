"""Liangzhi motor plugin entry point and translations."""
from cangui.plugin_host import Plugin

from . import faults
from . import protocol as p
from .widget import MotorPanel, tr


_TEXT = {
    "Title": ("良志电机控制", "Liangzhi Motor Control"),
    "Node": ("节点 ID", "Node ID"),
    "Transport": ("帧格式", "Frame format"),
    "TransportHint": ("仲裁和数据段速率在 CANable 主界面设置。请使用设备固件实际支持的帧格式。",
                      "Set nominal and data bitrates in the main window. Choose the format supported by the drive firmware."),
    "Classic": ("Classic CAN", "Classic CAN"),
    "Fd": ("CAN FD", "CAN FD"),
    "Brs": ("CAN FD + BRS", "CAN FD + BRS"),
    "Simple": ("CAN Simple", "CAN Simple"),
    "Mit": ("MIT 控制", "MIT Control"),
    "Endpoints": ("端点参数", "Endpoints"),
    "Open": ("CANopen", "CANopen"),
    "Command": ("命令", "Command"),
    "Send": ("发送", "Send"),
    "Idle": ("退出闭环", "Request idle"),
    "Estop": ("急停", "Emergency stop"),
    "ClosedLoop": ("进入闭环", "Request closed loop"),
    "SetMit": ("设置 MIT 输入模式", "Set MIT input mode"),
    "MitHint": ("MIT 目标使用输出轴单位，量程须与驱动的 mit_max 参数一致。周期发送采用启动时的目标值，再次启动可更新该节点。发送时序受主机和 USB 调度影响。",
                "MIT targets use output-shaft units. Match the drive's mit_max values. Periodic send uses a snapshot of the targets. Start again to update the node. Timing depends on host and USB scheduling."),
    "Position": ("目标位置 (rad)", "Position (rad)"),
    "Velocity": ("目标速度 (rad/s)", "Velocity (rad/s)"),
    "Torque": ("目标 / 实际力矩", "Target / measured torque"),
    "TorqueTarget": ("前馈力矩 (Nm)", "Feedforward torque (Nm)"),
    "Kp": ("Kp (Nm/rad)", "Kp (Nm/rad)"),
    "Kd": ("Kd (Nm·s/rad)", "Kd (Nm·s/rad)"),
    "MaxPosition": ("位置量程 (rad)", "Position limit (rad)"),
    "MaxVelocity": ("速度量程 (rad/s)", "Velocity limit (rad/s)"),
    "MaxTorque": ("力矩量程 (Nm)", "Torque limit (Nm)"),
    "MaxKp": ("Kp 量程", "Kp limit"),
    "MaxKd": ("Kd 量程", "Kd limit"),
    "Period": ("发送周期", "Send period"),
    "StartCycle": ("启动 / 更新本节点周期发送", "Start / update this node"),
    "StopCycle": ("停止本节点发送", "Stop sending to this node"),
    "StopAll": ("停止全部周期发送", "Stop all periodic sends"),
    "Stopped": ("已停止周期发送。退出闭环请使用对应按钮。", "Periodic sending stopped. Use Request idle to exit closed loop."),
    "Running": ("周期发送节点：{nodes}", "Periodic nodes: {nodes}"),
    "Heartbeat": ("轴状态 / 故障 / 温度 / 心跳计数", "Axis state / fault / temperature / heartbeat count"),
    "AxisFault": ("轴故障及原因", "Axis faults and causes"),
    "HeartbeatFaultFlags": ("心跳故障标志", "Heartbeat fault flags"),
    "MitFaultFlags": ("MIT 故障标志", "MIT fault flags"),
    "ErrorDetail": ("详细故障（最近回复）", "Detailed fault (last reply)"),
    "NoFault": ("无故障", "No fault"),
    "UnknownFaultBits": ("手册未列出的故障位 0x{mask:X}。", "Fault bits not listed in the manual: 0x{mask:X}."),
    "FaultBusy": ("正在等待上一次详细故障查询的回复。", "Waiting for the previous detailed fault reply."),
    "FaultSource.Axis": ("轴", "Axis"),
    "FaultSource.Motor": ("电机", "Motor"),
    "FaultSource.Encoder": ("编码器", "Encoder"),
    "FaultSource.Controller": ("控制器", "Controller"),
    "FaultSource.System": ("系统", "System"),
    "FaultSource.Flags": ("模块标志", "Subsystem flags"),
    "MitFeedback": ("输出轴 MIT 位置 / 速度 / 力矩 / 故障 / 温度", "Output shaft MIT position / speed / torque / faults / temperature"),
    "Rotor": ("转子位置 / 速度", "Rotor position / velocity"),
    "Encoder": ("编码器多圈 / 单圈计数", "Encoder total / single-turn counts"),
    "Iq": ("目标 / 实际 Iq", "Target / measured Iq"),
    "Temperature": ("电机 / 驱动温度", "Motor / driver temperature"),
    "Bus": ("母线电压 / 电流", "Bus voltage / current"),
    "Power": ("电功率 / 机械功率", "Electrical / mechanical power"),
    "Feedback": ("反馈", "Feedback"),
    "Value": ("值", "Value"),
    "Search": ("搜索参数名称或地址", "Find by parameter name or address"),
    "Table": ("参数表", "Parameter table"),
    "ChooseTable": ("选择匹配固件的参数表", "Select the matching firmware table"),
    "Load": ("导入参数表", "Import parameter table"),
    "Read": ("读取", "Read"),
    "Write": ("写入", "Write"),
    "Call": ("调用选中函数", "Call selected function"),
    "Zero": ("将当前位置置零", "Set current position to zero"),
    "ZeroUnavailable": ("匹配的端点表没有 set_current_pos_zero。请按该固件的零点设置方式操作。",
                        "The selected table has no set_current_pos_zero. Use the procedure for this firmware."),
    "Save": ("保存配置并重启", "Save and reboot"),
    "Nmt": ("NMT 状态", "NMT state"),
    "Sync": ("发送 SYNC", "Send SYNC"),
    "Broadcast": ("广播 NMT", "Broadcast NMT"),
    "Servo": ("伺服控制字", "Servo controlword"),
    "ReadServo": ("读取状态字", "Read statusword"),
    "DefaultId": ("自定义 COB-ID (Hex)", "Custom COB-ID (hex)"),
    "SendPdo": ("发送 RPDO", "Send RPDO"),
    "Sdo": ("SDO 响应", "SDO response"),
    "Ready": ("选择节点、帧格式和操作。", "Select the node, frame format and operation."),
    "Disconnected": ("请先连接 CAN 适配器。", "Connect the CAN adapter first."),
    "NeedFd": ("请先在主界面启用 CAN FD。", "Enable CAN FD in the main window first."),
    "Queued": ("已提交 0x{can_id:03X}  {data}", "Queued 0x{can_id:03X}  {data}"),
    "Invalid": ("参数或文件无效。{detail}", "Invalid input or file. {detail}"),
    "NoEntries": ("参数表没有可通过 4 字节服务访问的条目。", "No entries usable with the four-byte service."),
    "ChooseParameter": ("请选择参数或函数。", "Select a parameter or function."),
    "Access": ("该条目不支持所选操作。", "The selected operation is unavailable for this entry."),
    "Busy": ("请等待当前参数请求完成。", "Wait for the pending parameter request."),
    "Timeout": ("参数请求超时。", "Parameter request timed out."),
    "Abort": ("SDO 中止 0x{code:08X}", "SDO abort 0x{code:08X}"),
    "SizeMismatch": ("返回长度与所选参数类型不一致。", "The response size differs from the selected type."),
    "Written": ("驱动确认写入 {name}。", "Drive acknowledged writing {name}."),
    "ReadValue": ("{name} = {value}", "{name} = {value}"),
    "RtrHint": ("此查询使用 Classic CAN RTR，需固件支持。周期上报可通过对应端点配置。",
                "This Classic CAN RTR query requires firmware support. Use the matching endpoints for periodic reports."),
    "RtrClassic": ("RTR 仅适用于 Classic CAN。请等待周期上报或读取对应端点。",
                   "RTR requires Classic CAN. Use periodic reports or read the corresponding endpoint."),
    "ManualAddress": ("手动地址 (Hex)", "Manual address (hex)"),
}

_ENUMS = {
    "Axis": {0: ("未定义", "Undefined"), 1: ("空闲", "Idle"), 3: ("完整校准", "Full calibration"),
             4: ("电机校准", "Motor calibration"), 7: ("编码器校准", "Encoder calibration"), 8: ("闭环", "Closed loop")},
    "Error": {0: ("电机", "Motor"), 1: ("编码器", "Encoder"), 3: ("控制器", "Controller"), 4: ("系统", "System")},
    "Control": {0: ("电压", "Voltage"), 1: ("力矩", "Torque"), 2: ("速度", "Velocity"), 3: ("位置", "Position")},
    "Input": {0: ("闲置", "Inactive"), 1: ("直接", "Direct"), 2: ("速度斜坡", "Velocity ramp"),
              3: ("位置滤波", "Position filter"), 5: ("梯形轨迹", "Trapezoidal trajectory"),
              6: ("力矩斜坡", "Torque ramp"), 9: ("MIT", "MIT")},
    "Nmt": {1: ("进入运行", "Start"), 2: ("停止", "Stop"), 128: ("预运行", "Pre-operational"),
            129: ("复位节点", "Reset node"), 130: ("复位通信", "Reset communication")},
    "Servo": {0: ("禁用电压", "Disable voltage"), 6: ("准备启动", "Shutdown"), 7: ("接通", "Switch on"),
              15: ("使能运行", "Enable operation"), 2: ("快速停止", "Quick stop"), 128: ("故障复位", "Fault reset")},
}


class MotorPlugin(Plugin):
    name = "liangzhi_motor"
    version = "1.0.0"

    def __init__(self):
        super().__init__()
        self._panel = None

    def init(self, ctx):
        for key, (zh, en) in _TEXT.items():
            ctx.register_i18n(f"Liangzhi.{key}", zh, en)
        for prefix, entries in _ENUMS.items():
            for value, (zh, en) in entries.items():
                ctx.register_i18n(f"Liangzhi.{prefix}.{value}", zh, en)
        for source, table in faults.TABLES.items():
            for name, zh, en in table.values():
                ctx.register_i18n(f"Liangzhi.Fault.{source}.{name}", zh, en)
        for code, command in p.COMMANDS.items():
            ctx.register_i18n(f"Liangzhi.Command.{code}", command.zh, command.name.replace("_", " "))
            for field in command.fields:
                ctx.register_i18n(f"Liangzhi.Field.{field}", field, field)
        for index in range(1, 5):
            text = f"TPDO {index}"
            ctx.register_i18n(f"Liangzhi.Tpdo{index}", text, text)

    def display_title(self):
        return tr("Title")

    def build_widget(self, ctx):
        self._panel = MotorPanel(ctx)
        return self._panel

    def on_activated(self):
        if self._ctx.is_connected():
            self._panel.on_connect()
        else:
            self._panel.on_disconnect()

    def on_deactivating(self):
        self._panel.on_disconnect()

    def teardown_widget(self, widget):
        self._panel = None
        super().teardown_widget(widget)

    def on_connect(self):
        self._panel.on_connect()

    def on_disconnect(self):
        self._panel.on_disconnect()

    def on_frames(self, frames):
        self._panel.on_frames(frames)

    def refresh_language(self):
        if self._panel is not None:
            self._panel.refresh_language()


def create_plugin():
    return MotorPlugin()
