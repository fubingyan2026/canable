# 捷电机 CAN FD 控制插件实现计划

## 目标

基于 `juxie_canfd_cmd.md` 协议，创建 CANable 2.5 GUI 插件，实现：
- 单执行器控制（标准 6 模式 + MIT 模式）
- 多控广播（标准 8 轴 + MIT 6 轴）
- 执行器反馈报文解析与显示

## 文件结构

```
plugins/juxie_motor/
├── __init__.py        # __version__ = "0.1.0"
├── plugin.py          # Plugin 子类 + create_plugin() 工厂
├── protocol.py        # 纯协议逻辑：帧构造器 + 反馈解析器
└── widget.py          # UI 面板（控制 + 反馈显示）
```

## 协议参数

- 仲裁段 1 Mbps，数据段 5 Mbps（CAN FD BRS）
- 标准帧（11-bit ID）
- 单控 TX ID: `0x100 | Dev_ID`（7 字节）
- 多控 TX ID: `0x200`（64 字节，CAN FD，8 子包）
- MIT 单控 TX ID: `0x110 | Dev_ID`（9 字节）
- MIT 多控 TX ID: `0x210`（64 字节，CAN FD，6 子包）
- 反馈 RX ID: `0x300 | Dev_ID`（12 或 16 字节，CAN FD）

---

## 1. protocol.py — 纯协议层

无 Qt 依赖，可独立测试。

### 常量

```python
# CAN ID 基址
SINGLE_ID_BASE = 0x100
MULTI_ID       = 0x200
MIT_SINGLE_BASE= 0x110
MIT_MULTI_ID   = 0x210
FEEDBACK_ID_BASE=0x300

# 控制模式
MODE_PROFILE_POS  = 0x01
MODE_PROFILE_VEL  = 0x02
MODE_CSP_POS      = 0x03
MODE_CSV_VEL      = 0x04
MODE_CURRENT      = 0x05
MODE_TORQUE       = 0x06
MODE_MIT          = 0x06  # MIT 模式值同为 0x06，但使用 MIT 帧格式

# 控制字节位掩码
BIT_ENABLE     = 0x80  # bit7
BIT_BRAKE      = 0x40  # bit6
BIT_CLEAR_ERR  = 0x20  # bit5
MODE_MASK      = 0x1E  # bit4~1
```

### 帧构造器

```python
def build_single_control(dev_id: int, enable: bool, brake: bool,
                         clear_err: bool, mode: int,
                         param1: int, param2: int, feedforward: int) -> bytes:
    """构造单执行器控制帧 payload（7 字节）"""

def build_mit_single_control(dev_id: int, enable: bool, brake: bool,
                             clear_err: bool, position: int, velocity: int,
                             kp: int, kd: int, torque: int) -> bytes:
    """构造 MIT 单轴控制帧 payload（9 字节），12-bit 字段跨字节打包"""

def build_multi_control(commands: list[MultiCmd]) -> bytes:
    """构造多控广播帧 payload（64 字节，CAN FD）
    commands: 最多 8 个 MultiCmd（标准）或 6 个（MIT）
    每个 MultiCmd: (dev_id, enable, brake, clear_err, mode, p1, p2, ff)
    返回: 56 字节子包 + 8/6 字节 ID + 填充
    """
```

### 反馈解析器

```python
@dataclass
class FeedbackData:
    position: float       # °（已由 int16 换算）
    speed: int            # RPM
    current: int          # mA
    error_code: int       # uint16
    temperature: float    # ℃（已除 0.1）
    torque: float | None  # Nm（仅 16 字节帧），None 表示 12 字节帧
    mode_feedback: int    # uint8
    status: int           # uint8（原始值）
    # 状态位派生
    enabled: bool
    brake_released: bool
    has_error: bool
    position_reached: bool

def parse_feedback(data: bytes) -> FeedbackData | None:
    """解析 12 或 16 字节反馈帧。长度不符返回 None。"""
```

### MIT 12-bit 打包/ unpacking

MIT 帧使用 12-bit 字段跨字节边界，需位操作：
- `pack_12bit(high_byte, low_nibble, value)` → 写入字节
- `extract_12bit(high_byte, next_byte, low_nibble_count)` → value

---

## 2. widget.py — UI 面板

### 布局

```
┌──────────────────────────────────────────────────────┐
│ [设备配置]  Dev_ID: [0 ▲▼]   (0~127)                 │
├──────────────────────────────────────────────────────┤
│ [单轴控制]                                            │
│  模式: [轮廓位置 ▼] ◀ 7 模式（含 MIT）               │
│  ┌─ 控制 ─────────────────────────────────────────┐  │
│  │ [✓]上使能  [✓]抱闸释放  [ ]清除错误            │  │
│  └────────────────────────────────────────────────┘  │
│  ┌─ 目标参数（模式相关）──────────────────────────┐  │
│  │ 目标位置: [    0] °    目标速度: [    0] RPM   │  │
│  │ 目标电流: [    0] mA   目标力矩: [    0] Nm    │  │
│  │ 轮廓加减速: [2000] RPM/S  轮廓速度: [    5] RPM │  │
│  └────────────────────────────────────────────────┘  │
│  ┌─ MIT 参数（仅 MIT 模式显示）───────────────────┐  │
│  │ 目标位置: [    0]    目标速度: [    0]         │  │
│  │ Kp: [    0]          Kd: [    0]               │  │
│  │ 目标力矩: [    0]                               │  │
│  └────────────────────────────────────────────────┘  │
│           [ 发送单轴指令 ]                            │
├──────────────────────────────────────────────────────┤
│ [多控广播]  (0x200 / 0x210)                          │
│  ┌────────────────────────────────────────────────┐  │
│  │ # │ Dev_ID │ 使能 │ 模式    │ 目标参数1 │ ...  │  │
│  │ 1 │ [  0]  │ [✓] │ [位置▼] │ [    0]   │      │  │
│  │ 2 │ [  0]  │ [✓] │ [位置▼] │ [    0]   │      │  │
│  │ ...（最多 8 行标准 / 6 行 MIT）                │  │
│  └────────────────────────────────────────────────┘  │
│           [ 发送多控广播 ]                            │
├──────────────────────────────────────────────────────┤
│ [反馈显示]  (0x300 | Dev_ID)                         │
│  位置:    +45.00 °     速度:    120 RPM              │
│  电流:    250 mA       温度:    35.2 ℃               │
│  力矩:     1.50 Nm     错误码: 0x0000                │
│  模式反馈: CSP位置   状态: [已使能][抱闸释放][到位]  │
│  最后更新: 12:34:56                                  │
└──────────────────────────────────────────────────────┘
```

### 关键交互逻辑

1. **模式切换**：下拉框切换时，动态显示/隐藏标准参数区或 MIT 参数区
2. **发送前校验**：Dev_ID 范围 0~127；参数范围按模式校验
3. **反馈过滤**：`on_frames()` 中只处理 `can_id == 0x300 | dev_id` 且非 TX echo 的帧
4. **状态指示**：使用 `style.LOAD_LOW/MID/HIGH` 颜色标记错误/警告状态
5. **i18n**：所有文本通过 `_()` 获取，`refresh_language()` 重新设置

### 生命周期方法

- `on_activated()` / `on_deactivating()`：无需定时器（被动接收反馈）
- `on_connect()`：清空反馈显示，重置状态
- `on_disconnect()`：显示离线状态
- `on_frames(frames)`：过滤反馈帧 → 解析 → 更新显示
- `refresh_language()`：重设所有静态文本

### 配置持久化

使用 `_ConfigStore` 包装 `ctx.get_setting/set_setting`：
- `juxie_motor.dev_id` — 当前设备 ID
- `juxie_motor.mode` — 当前控制模式
- `juxie_motor.enable/brake` — 控制位状态

---

## 3. plugin.py — 插件入口

遵循 `power_monitor` 的薄适配器模式：

```python
class JuxieMotorPlugin(Plugin):
    name = "juxie_motor"
    version = "0.1.0"

    def init(self, ctx):
        for key, (zh, en) in _I18N_KEYS.items():
            ctx.register_i18n(key, zh, en)

    def display_title(self):
        return _("Juxie.Title")

    def build_widget(self, ctx):
        self._panel = JuxieMotorPanel(ctx)
        return self._panel

    # 转发 on_connect/on_disconnect/on_frames/refresh_language 到 panel
```

---

## 4. i18n 键（`Juxie.*` 命名空间）

```python
_I18N_KEYS = {
    "Juxie.Title":              ("捷电机控制",          "Juxie Motor Control"),
    "Juxie.DevConfig":          ("设备配置",            "Device Config"),
    "Juxie.DevID":              ("设备 ID",             "Device ID"),
    "Juxie.SingleControl":      ("单轴控制",            "Single Control"),
    "Juxie.MultiControl":       ("多控广播",            "Multi-Control"),
    "Juxie.Feedback":           ("反馈显示",            "Feedback"),
    "Juxie.Mode":               ("控制模式",            "Control Mode"),
    "Juxie.Enable":             ("上使能",              "Enable"),
    "Juxie.Brake":              ("抱闸释放",            "Brake Release"),
    "Juxie.ClearError":         ("清除错误",            "Clear Error"),
    "Juxie.TargetPos":          ("目标位置",            "Target Position"),
    "Juxie.TargetVel":          ("目标速度",            "Target Speed"),
    "Juxie.TargetCurrent":      ("目标电流",            "Target Current"),
    "Juxie.TargetTorque":       ("目标力矩",            "Target Torque"),
    "Juxie.ProfileAccel":       ("轮廓加减速",          "Profile Accel"),
    "Juxie.ProfileSpeed":       ("轮廓速度",            "Profile Speed"),
    "Juxie.Kp":                 ("位置增益 Kp",         "Kp"),
    "Juxie.Kd":                 ("速度增益 Kd",         "Kd"),
    "Juxie.SendSingle":         ("发送单轴指令",        "Send Single"),
    "Juxie.SendMulti":          ("发送多控广播",        "Send Multi-Control"),
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
    # 模式名
    "Juxie.Mode.ProfilePos":    ("轮廓位置模式",        "Profile Position"),
    "Juxie.Mode.ProfileVel":    ("轮廓速度模式",        "Profile Velocity"),
    "Juxie.Mode.CSP":          ("CSP 位置模式",        "CSP Position"),
    "Juxie.Mode.CSV":          ("CSV 速度模式",        "CSV Velocity"),
    "Juxie.Mode.Current":       ("电流环模式",          "Current Loop"),
    "Juxie.Mode.Torque":        ("力矩环模式",          "Torque Loop"),
    "Juxie.Mode.MIT":          ("MIT 模式",            "MIT Mode"),
    # 状态位
    "Juxie.Status.Enabled":     ("已使能",              "Enabled"),
    "Juxie.Status.Disabled":    ("下使能",              "Disabled"),
    "Juxie.Status.BrakeOn":     ("抱闸吸合",            "Brake On"),
    "Juxie.Status.BrakeOff":    ("抱闸释放",            "Brake Off"),
    "Juxie.Status.Error":       ("报错",                "Error"),
    "Juxie.Status.Normal":      ("正常",                "Normal"),
    "Juxie.Status.InPosition":  ("到位",                "In Position"),
    "Juxie.Status.Running":     ("运行中",              "Running"),
    # 单位
    "Juxie.Unit.Deg":          ("°",                   "°"),
    "Juxie.Unit.RPM":          ("RPM",                 "RPM"),
    "Juxie.Unit.mA":           ("mA",                  "mA"),
    "Juxie.Unit.Nm":           ("Nm",                  "Nm"),
    "Juxie.Unit.Celsius":      ("℃",                   "℃"),
    "Juxie.Unit.RPMS":         ("RPM/S",               "RPM/S"),
    # 错误提示
    "Juxie.Err.NotConnected":  ("CAN 未连接",          "CAN not connected"),
    "Juxie.Err.InvalidDevID":  ("设备 ID 超出范围",    "Device ID out of range"),
    "Juxie.Err.ParamRange":    ("参数超出范围",        "Parameter out of range"),
}
```

---

## 5. PyInstaller 配置更新

在 `CANable2.5.spec` 的 `hiddenimports` 列表中添加：

```python
"plugins.juxie_motor.protocol",
"plugins.juxie_motor.widget",
```

---

## 实现步骤

1. **创建目录骨架**：`plugins/juxie_motor/` + `__init__.py`
2. **实现 `protocol.py`**：帧构造器 + 反馈解析器 + MIT 12-bit 打包
3. **实现 `widget.py`**：UI 布局 + 交互逻辑 + 反馈解析 + i18n
4. **实现 `plugin.py`**：薄适配器 + `create_plugin()`
5. **更新 `CANable2.5.spec`**：添加 hidden imports
6. **验证**：运行 GUI → 插件加载 → 功能测试

---

## 验证计划

1. **加载验证**：启动 GUI，Plugins 菜单出现"捷电机控制"，点击打开面板
2. **单轴控制验证**：
   - 设置 Dev_ID=7，模式=轮廓位置，参数按协议例 1（`0x107`, `0xC2`, `0x0000`, `0x07D0`, `0x0005`）
   - 发送后用 Trace 面板验证发送帧内容正确
3. **MIT 模式验证**：切换模式=MIT，验证 12-bit 字段打包正确
4. **多控验证**：填写 2 个轴参数，发送后验证 64 字节帧结构
5. **反馈解析验证**：用 SDK CLI 或 Send 面板模拟发送反馈帧（ID=`0x307`，16 字节），验证面板解析显示正确
6. **i18n 验证**：切换中英文，面板文本正确切换
7. **持久化验证**：重启 GUI，Dev_ID 和模式状态恢复
8. **连接生命周期**：连接/断开 CAN，面板状态正确切换

---

## 注意事项

- 所有 TX 帧使用 `ctx.send_frame(CANFrame(...))`，不直接操作 worker
- 反馈帧过滤：`f.is_tx == False and f.can_id == (0x300 | dev_id)`
- MIT 模式 12-bit 打包是跨字节的，需仔细测试位操作
- 多控帧是 CAN FD（64 字节 DLC），构造 `CANFrame` 时 `fd=True, brs=True`
- 单控帧（7 字节）和 MIT 单控帧（9 字节）：7 字节用经典 CAN，9 字节用 CAN FD
- 不记录 per-frame 日志（遵守日志规范）
- 不添加代码注释（遵守代码规范）
