"""Fault bit definitions from the Liangzhi drive protocol manual."""
from dataclasses import dataclass


AXIS = {
    0x00000001: ("INVALID_STATE", "请求的轴状态无效。", "The requested axis state is invalid."),
    0x00000040: ("MOTOR_FAILED", "电机子系统报告故障。读取「详细故障 → 电机」可查看具体原因。",
                 "The motor subsystem reported a fault. Read the detailed motor fault for the cause."),
    0x00000080: ("SENSORLESS_ESTIMATOR_FAILED", "无感估算器报告故障。", "The sensorless estimator reported a fault."),
    0x00000100: ("ENCODER_FAILED", "编码器子系统报告故障。读取「详细故障 → 编码器」可查看具体原因。",
                 "The encoder subsystem reported a fault. Read the detailed encoder fault for the cause."),
    0x00000200: ("CONTROLLER_FAILED", "控制器报告故障。读取「详细故障 → 控制器」可查看具体原因。",
                 "The controller reported a fault. Read the detailed controller fault for the cause."),
    0x00000800: ("WATCHDOG_TIMER_EXPIRED", "看门狗未在规定时间内收到刷新。", "The watchdog was not refreshed within its timeout."),
    0x00001000: ("MIN_ENDSTOP_PRESSED", "下限位开关触发。", "The lower limit switch was triggered."),
    0x00002000: ("MAX_ENDSTOP_PRESSED", "上限位开关触发。", "The upper limit switch was triggered."),
    0x00004000: ("ESTOP_REQUESTED", "驱动器收到急停请求。", "The drive received an emergency stop request."),
    0x00020000: ("HOMING_WITHOUT_ENDSTOP", "请求回零时缺少限位开关配置。", "Homing was requested without a configured limit switch."),
    0x00040000: ("OVER_TEMP", "轴因温度超过阈值而保护。", "Axis temperature exceeded the protection threshold."),
    0x00080000: ("UNKNOWN_POSITION", "驱动器无法确定当前位置。", "The drive could not determine the current position."),
    0x00100000: ("CAN_BUS_FAILED", "驱动器报告 CAN 总线故障。", "The drive reported a CAN bus fault."),
}

SYSTEM = {
    0x01: ("CONTROL_ITERATION_MISSED", "控制循环未按时执行。", "A control iteration missed its deadline."),
    0x02: ("DC_BUS_UNDER_VOLTAGE", "直流母线电压低于保护阈值。", "DC bus voltage fell below its protection threshold."),
    0x04: ("DC_BUS_OVER_VOLTAGE", "直流母线电压超过保护阈值。", "DC bus voltage exceeded its protection threshold."),
    0x08: ("DC_BUS_OVER_REGEN_CURRENT", "回灌到直流母线的电流超过限值。", "Regenerative current into the DC bus exceeded its limit."),
    0x10: ("DC_BUS_OVER_CURRENT", "直流母线电流超过限值。", "DC bus current exceeded its limit."),
    0x20: ("BRAKE_DEADTIME_VIOLATION", "制动斩波器死区时序异常。", "The brake chopper violated its dead-time timing."),
    0x40: ("BRAKE_DUTY_CYCLE_NAN", "制动斩波器占空比计算结果为 NaN。", "The brake chopper duty cycle evaluated to NaN."),
    0x80: ("INVALID_BRAKE_RESISTANCE", "制动电阻参数无效。", "The configured brake resistance is invalid."),
}

MOTOR = {
    0x00000001: ("PHASE_RESISTANCE_OUT_OF_RANGE", "电机校准测得的相电阻超出允许范围。", "Motor calibration measured phase resistance outside the allowed range."),
    0x00000002: ("PHASE_INDUCTANCE_OUT_OF_RANGE", "电机校准测得的相电感超出允许范围。", "Motor calibration measured phase inductance outside the allowed range."),
    0x00000008: ("DRV_FAULT", "功率驱动级报告故障。", "The power driver stage reported a fault."),
    0x00000010: ("CONTROL_DEADLINE_MISSED", "电机控制循环未在时限内完成。", "The motor control loop missed its deadline."),
    0x00000080: ("MODULATION_MAGNITUDE", "电压调制幅值超出允许范围。", "Voltage modulation magnitude exceeded its allowed range."),
    0x00000400: ("CURRENT_SENSE_SATURATION", "电流采样达到饱和。", "Current sensing saturated."),
    0x00001000: ("CURRENT_LIMIT_VIOLATION", "电机电流超过限值。", "Motor current exceeded its limit."),
    0x00010000: ("MODULATION_IS_NAN", "电压调制计算结果为 NaN。", "Voltage modulation evaluated to NaN."),
    0x00020000: ("MOTOR_THERMISTOR_OVER_TEMP", "电机温度传感器检测到过温。", "The motor thermistor reported overtemperature."),
    0x00040000: ("FET_THERMISTOR_OVER_TEMP", "功率管温度传感器检测到过温。", "The FET thermistor reported overtemperature."),
    0x00080000: ("TIMER_UPDATE_MISSED", "电机控制定时器更新超时。", "A motor control timer update was missed."),
    0x00100000: ("CURRENT_MEASUREMENT_UNAVAILABLE", "电流采样不可用。", "Current measurements are unavailable."),
    0x00200000: ("CONTROLLER_FAILED", "电机控制器报告故障。", "The motor controller reported a fault."),
    0x00400000: ("I_BUS_OUT_OF_RANGE", "母线电流超出允许范围。", "Bus current is outside the allowed range."),
    0x00800000: ("BRAKE_RESISTOR_DISARMED", "制动电阻输出已解除使能。", "The brake resistor output is disarmed."),
    0x01000000: ("SYSTEM_LEVEL", "电机受系统级故障影响。读取系统详细故障可进一步定位。", "A system-level fault affected the motor. Read the detailed system fault."),
    0x02000000: ("BAD_TIMING", "电机控制时序异常。", "Motor control timing is invalid."),
    0x04000000: ("UNKNOWN_PHASE_ESTIMATE", "电机电角度估算不可用。", "The electrical phase estimate is unavailable."),
    0x08000000: ("UNKNOWN_PHASE_VEL", "电角速度估算不可用。", "The electrical phase velocity is unavailable."),
    0x10000000: ("UNKNOWN_TORQUE", "电机控制所需的力矩值不可用。", "The torque value required for motor control is unavailable."),
    0x20000000: ("UNKNOWN_CURRENT_COMMAND", "电流指令不可用。", "The current command is unavailable."),
    0x40000000: ("UNKNOWN_CURRENT_MEASUREMENT", "电流测量值不可用。", "The measured current value is unavailable."),
    0x80000000: ("UNKNOWN_VBUS_VOLTAGE", "母线电压测量值不可用。", "The measured bus voltage is unavailable."),
    0x100000000: ("UNKNOWN_VOLTAGE_COMMAND", "电压指令不可用。", "The voltage command is unavailable."),
    0x200000000: ("UNKNOWN_GAINS", "电机控制增益不可用。", "Motor control gains are unavailable."),
    0x400000000: ("CONTROLLER_INITIALIZING", "电机控制器仍在初始化。", "The motor controller is still initializing."),
    0x800000000: ("UNBALANCED_PHASES", "驱动器检测到电机相不平衡。", "The drive detected unbalanced motor phases."),
}

CONTROLLER = {
    0x01: ("OVERSPEED", "电机速度超过保护限值。", "Motor speed exceeded its protection limit."),
    0x02: ("INVALID_INPUT_MODE", "控制器输入模式无效。", "The controller input mode is invalid."),
    0x04: ("UNSTABLE_GAIN", "控制器判定增益不稳定。", "The controller reported unstable gains."),
    0x08: ("INVALID_MIRROR_AXIS", "镜像控制的参考轴无效。", "The referenced mirror axis is invalid."),
    0x10: ("INVALID_LOAD_ENCODER", "负载编码器配置或来源无效。", "The load encoder source or configuration is invalid."),
    0x20: ("INVALID_ESTIMATE", "控制器收到无效的估算值。", "The controller received an invalid estimate."),
    0x40: ("INVALID_CIRCULAR_RANGE", "循环位置范围参数无效。", "The circular position range is invalid."),
    0x80: ("SPINOUT_DETECTED", "控制器检测到电机失控旋转。", "The controller detected a motor spinout."),
}

ENCODER = {
    0x001: ("UNSTABLE_GAIN", "编码器估算增益不稳定。", "The encoder estimator gain is unstable."),
    0x002: ("CPR_POLEPAIRS_MISMATCH", "编码器每转计数与电机极对数不匹配。", "Encoder counts per revolution and motor pole pairs do not match."),
    0x004: ("NO_RESPONSE", "编码器未返回有效响应。", "The encoder did not return a valid response."),
    0x008: ("UNSUPPORTED_ENCODER_MODE", "当前编码器模式不受支持。", "The selected encoder mode is unsupported."),
    0x010: ("ILLEGAL_HALL_STATE", "检测到无效的霍尔信号状态。", "An invalid Hall signal state was detected."),
    0x020: ("INDEX_NOT_FOUND_YET", "编码器尚未检测到索引信号。", "The encoder index pulse has not been found."),
    0x040: ("ABS_SPI_TIMEOUT", "绝对值编码器的 SPI 通信超时。", "SPI communication with the absolute encoder timed out."),
    0x080: ("ABS_SPI_COM_FAIL", "绝对值编码器的 SPI 通信失败。", "SPI communication with the absolute encoder failed."),
    0x100: ("ABS_SPI_NOT_READY", "绝对值编码器的 SPI 接口未就绪。", "The absolute encoder SPI interface is not ready."),
    0x200: ("HALL_NOT_CALIBRATED_YET", "霍尔编码器尚未校准。", "The Hall encoder has not been calibrated."),
    0x400: ("SEC_ENC_COM_FAIL", "第二编码器通信失败。", "Communication with the secondary encoder failed."),
}

FLAGS = {
    0x1: ("Motor_Flag", "电机异常标志置位。", "The motor fault flag is set."),
    0x2: ("Encoder_Flag", "编码器异常标志置位。", "The encoder fault flag is set."),
    0x4: ("Controller_Flag", "控制器异常标志置位。", "The controller fault flag is set."),
    0x8: ("System_Flag", "系统异常标志置位。", "The system fault flag is set."),
}

TABLES = {"Axis": AXIS, "System": SYSTEM, "Motor": MOTOR, "Controller": CONTROLLER,
          "Encoder": ENCODER, "Flags": FLAGS}
DETAIL_SOURCE = {0: "Motor", 1: "Encoder", 3: "Controller", 4: "System"}


@dataclass(frozen=True)
class Reading:
    source: str
    mask: int

    @property
    def width(self) -> int:
        return {"Motor": 16, "Flags": 2}.get(self.source, 8)

    def split(self) -> tuple[list[tuple[int, str]], int]:
        """Return set bits with documented names and a mask of unlisted bits."""
        known = []
        unknown = self.mask
        for bit, (name, _zh, _en) in TABLES[self.source].items():
            if self.mask & bit:
                known.append((bit, name))
                unknown &= ~bit
        return known, unknown
