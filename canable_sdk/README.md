# canable_sdk — CANable 2.5 驱动 SDK

Python USB-CAN 驱动，适用于 CANable 2.5 适配器（ElmueSoft Candlelight 固件）。

## 快速开始

```python
from canable_sdk import ZDTCanable, CANFrame

with ZDTCanable() as bus:
    bus.set_bitrate(500_000)
    bus.start()
    frame = bus.receive(timeout=1.0)
    if frame:
        print(frame)
```

## 安装

```bash
pip install -r requirements.txt   # pyusb, PySide6
```

Linux 需要 udev 规则免 root 访问：

```bash
sudo bash install_udev.sh && 重新插拔设备
```

Windows 需安装 WinUSB 驱动（ElmueSoft 固件支持自动安装），并将 `libusb-1.0.dll` 放在项目根目录或 `PATH` 中。

## 模块

| 模块 | 类/函数 | 说明 |
|------|---------|------|
| `driver.py` | `ZDTCanable` | 主驱动类：设备枚举、连接、位定时、收发、扩展功能 |
| `frame.py` | `CANFrame` | CAN 帧数据类 + ElmueSoft/Legacy 双协议序列化 |
| `protocol.py` | `_ElmueProtocol` | ElmueSoft 可变长度协议流解析器（内部使用） |
| `constants.py` | 常量 | USB ID、控制请求码、设备/帧/错误标志枚举、反馈码 |
| `bitrate.py` | 表 | 标称/数据相波特率时序表（160 MHz） |
| `cli.py` | `_cli()` | 命令行入口（`python -m canable_sdk`） |

## 公开 API

```python
from canable_sdk import ZDTCanable, CANFrame, CANableCommandError, logger, CANABLE_VID, CANABLE_PID
```

### ZDTCanable

#### 设备枚举与连接

| 方法 | 说明 |
|------|------|
| `list_devices()` | 静态方法，列出所有 CANable 设备（返回 dict 列表：vid/pid/manufacturer/product/serial） |
| `open()` | 打开设备连接（自动初始化、检测协议） |
| `close()` | 关闭连接（停止 CAN、释放 USB 资源） |
| 上下文管理器 | 支持 `with ZDTCanable() as bus:` |

`ZDTCanable(serial=..., port=(bus, address), backend=...)` 可按序列号或 USB 总线/设备地址选择设备；`backend` 接收 PyUSB backend 对象。`port` 不是串口名称。

#### CAN 控制器生命周期

| 方法 | 说明 |
|------|------|
| `start(loopback=None, disable_echo=None, one_shot=None)` | 启动 CAN 控制器；首次省略的选项默认为 False，后续省略则保留上次成功启动的选项 |
| `stop()` | 停止 CAN 控制器 |
| `recover()` | 复位 → 清缓冲 → 恢复位时序、启动选项、过滤器和负载报告 → 重启，启用 300ms TX 冷却；USB TX 错误恢复后为 500ms |

#### 位定时配置

| 方法 | 说明 |
|------|------|
| `set_bitrate(bps)` | 设置标称波特率（查 `NOMINAL_BITTIMING` 表，未命中则自动计算） |
| `set_data_bitrate(bps)` | 设置 CAN FD 数据相波特率（查 `DATA_BITTIMING` 表，未命中则自动计算） |

#### 收发

| 方法 | 说明 |
|------|------|
| `send(frame, timeout=1000)` | 发送一帧（自动处理 marker、ZLP、pipe 错误恢复） |
| `send_periodic(frame, interval_s=0.01, count=0)` | 周期发送（`count=0` 表示无限） |
| `receive(timeout=1.0)` | 阻塞接收一帧，超时返回 `None` |

#### 能力查询

| 方法 | 说明 |
|------|------|
| `check_fd_support()` | 查询固件是否支持 CAN FD（同时检查 `GS_DevFlagCAN_FD` 和 `GS_DevFlagBitTimingFD`） |
| `get_version()` | 返回固件版本字符串（如 `"25.10.23 (fw=0x..., hw=0x...)"`，BCD 解码） |
| `get_board_info()` | 返回板卡信息 dict：`{mcu_device_id, mcu_name, board_name}` |
| `get_timestamp()` | 读取固件 1μs 时间戳（32-bit，约 71.5 分钟翻转） |
| `read_error_register()` | 返回最后一次错误信息字符串 |

#### 扩展功能（ElmueSoft 协议专属）

| 方法 | 说明 |
|------|------|
| `identify(duration_ms=1000)` | LED 闪烁识别设备 |
| `set_silent(enable)` | 监听模式（不发送 ACK），运行中调用会自动 stop→start |
| `set_filter(operation, can_id, mask)` | 硬件验收过滤器（`FIL_ClearAll`/`FIL_AcceptMask11bit`/`FIL_AcceptMask29bit`，最多 8 个） |
| `clear_filters()` | 清除所有过滤器 |
| `get_termination()` / `set_termination(enabled)` | 120Ω 终端电阻读写 |
| `set_bus_load_report(interval)` | 启用/关闭总线负载百分比报告（0=off, 1..100，单位 100ms） |
| `set_pin_status(pin_id, operation)` | 控制处理器引脚（如 BOOT0：`PINOP_Reset`/`PINOP_Set`/`PINOP_Tristate` 等） |
| `get_pin_status(pin_id)` | 读取引脚状态位标志（`PINST_High`/`PINST_Enabled`） |

#### 回调与后台监听

| 方法 | 说明 |
|------|------|
| `on_receive(callback)` | 注册接收回调（参数为 `CANFrame`） |
| `on_overflow(callback)` | 注册溢出回调 |
| `start_listening()` | 启动后台接收线程，自动分发到已注册回调 |
| `stop_listening()` | 停止回调并等待接收线程退出，保持 CAN 控制器运行 |

先调用 `start()` 再调用 `start_listening()`；重复启动监听不会创建额外线程。后台监听运行时由它独占 `receive()`，调用方通过回调接收帧。`stop()` / `close()` 会等待监听线程退出；回调应及时返回。`recover()` / 运行中切换静默模式会恢复此前的监听状态。

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `running` | bool | CAN 控制器是否已启动 |
| `fd_mode` | bool | 是否启用 CAN FD 模式（必须在 `start()` 前设置） |

### CANFrame

#### 字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `can_id` | int | 必填 | CAN ID（11 或 29 位） |
| `data` | bytes | `b""` | 数据字节 |
| `extended` | bool | False | 是否 29 位扩展帧 |
| `rtr` | bool | False | 是否远程帧 |
| `fd` | bool | False | 是否 CAN FD 帧 |
| `brs` | bool | False | 是否位速率切换 |
| `esi` | bool | False | 错误状态指示 |
| `timestamp` | float | 0.0 | 时间戳（秒） |
| `echo_id` | int | 0 | TX Echo marker（1-255） |
| `is_tx` | bool | False | 是否本机发送的回环帧 |
| `_error_info` | str | `""` | 错误帧描述（内部使用） |

#### 属性与方法

| 成员 | 说明 |
|------|------|
| `dlc` (property) | 计算 DLC 码（FD 帧按实际长度映射 9-15） |
| `is_error` (property) | 是否错误帧 |
| `dlc_to_len(dlc)` (staticmethod) | DLC 转实际字节数（0-64） |
| `to_elmue_bytes(marker)` | 序列化为 ElmueSoft TX 字节流 |
| `from_elmue_rx(raw, has_timestamp)` (classmethod) | 从 ElmueSoft RX 字节流解析 |
| `from_elmue_echo(raw, has_timestamp, tx_frames)` (classmethod) | 从 ElmueSoft TX Echo 解析 |
| `to_legacy_bytes()` | 序列化为 Legacy 帧（Classic TX 20 字节，FD TX 80 字节） |
| `from_legacy_bytes(raw, has_timestamp=None, fd_mode=None)` (classmethod) | 从 Legacy 帧解析；驱动显式传入协商模式，独立调用时可省略并按包长推断 |

发送前会校验 ID、长度和标志组合：Classic CAN 超过 8 字节、FD 超过 64 字节、FD+RTR、Classic+BRS/ESI 都会抛出 `ValueError`。FD 的 9/10/11 等非标准长度会补零至下一合法 DLC 长度；原始 `CANFrame.data` 不变，TX 回显返回实际上总线的数据（含补零）。

## FD 模式配置顺序

```python
bus.fd_mode = True                        # 1. 开启 FD
bus.set_bitrate(500_000)                  # 2. 标称波特率
bus.set_data_bitrate(2_000_000)           # 3. 数据相波特率（必须 > 标称以启用 BRS）
bus.start()                               # 4. 启动
```

⚠️ **关键约束**：

- 位时序和 `fd_mode` 必须在 `start()` **之前**设置，运行中修改会抛出异常。
- 当前固件通过数据相位时序隐式启用 FD；配置过数据时序后，启动时必须将 `fd_mode` 设为 True。切回 Classic 可先 `stop()`，再设 `fd_mode=False` 并 `start()`。
- SDK 从固件能力应答读取 CAN 时钟和位时序范围；缺少扩展能力时，数据相采用保守限制 TSEG1/TSEG2/SJW≤15、BRP≤32。
- 自定义时序按波特率误差、采样点误差、时间量子总数选择；波特率误差不得超过 1%。默认标称采样点 87.5%，数据相 75%，8Mbps 固定为 50%。
- `stop()` 会使固件清除位时序。SDK 在下次 `start()` 时自动恢复最后成功设置的配置。
- 固件返回 `FBK_InvalidParameter`、`FBK_BaudrateNotSet` 等错误时，SDK 抛出 `CANableCommandError`，其 `request` 和 `feedback` 字段保留命令和错误码。

## USB 标识

| 项目 | 值 |
|------|-----|
| VID | `0x1D50` |
| PID | `0x606F` |
| EP_IN | `0x81` (Bulk IN) |
| EP_OUT | `0x02` (Bulk OUT) |
| 包大小 | 64 字节（Full Speed） |

## 协议

驱动自动检测并适配两种协议：

- **ElmueSoft 变长协议**（优先，能力标志含 `ELM_DevFlagProtocolElmue`）：消息头 `{size, msg_type}`，类型包括 `MSG_TxFrame`/`MSG_TxEcho`/`MSG_RxFrame`/`MSG_Error`/`MSG_String`/`MSG_Busload`，TX 帧使用 1 字节 marker（1-255）做 Echo 匹配
- **Legacy 协议**：向后兼容旧固件，接收包长由控制器 FD/时间戳模式决定（20/24/76/80 字节），不可仅根据当前帧的 FD 标志推断时间戳。

## 错误处理

- ElmueSoft 模式下，控制写入和 `ELM_ReqGetLastError` 查询作为一个加锁事务执行，固件拒绝命令或反馈读取失败都会抛出异常；Legacy 模式不查询该扩展命令。
- `send()` 遇到 USB pipe 错误时通过端点 `clear_halt()` 清除 STALL；短写也视为失败并重置控制器。错误恢复后仍向调用方报告该次发送失败，不自动重发，以免重复发送可能已被设备接收的帧。
- 开启回显时最多保留 255 个在途 marker，收到回显后释放；全部占用时明确报错，不覆盖未确认记录。持续发送时应同步接收（或启用后台监听）；无需回显的 ElmueSoft 应用可用 `start(disable_echo=True)`。
- `receive()` 遇到 USB overflow 时丢弃中断的协议片段并调用溢出回调，保留下次读取的数据和未确认 TX 记录。
- `receive(timeout=0)` 做一次 USB 读取并将 USB 超时设为 1ms，不会把零传给 libusb 而无限等待。其他超时采用单调时钟，并等待正常帧而跳过负载报告等辅助消息。
- 错误帧解析支持 `eErrFlagsCanID` 全部位（`Bus-off`/`No-ACK`/`CRC-Err`/`Arbitration lost` 等）和 Byte1-Byte5 详细字段

## 命令行工具

```bash
python -m canable_sdk           # Classic CAN 模式监听
python -m canable_sdk --fd      # CAN FD 模式监听（2M 数据相）
```

启动后会列出所有设备，自动以 500kbps（FD 模式外加 2Mbps 数据相）启动并打印所有收到的帧，`Ctrl+C` 退出。

## 回归测试

无需连接设备，模拟 USB 端点及固件控制状态：

```bash
python -B -m unittest discover -s tests -v
```

## 平台支持

- **Linux**：udev 规则 + libusb（`apt install libusb-1.0-0`）
- **Windows**：WinUSB 驱动（固件支持自动安装）+ `libusb-1.0.dll`
- **macOS**：`brew install libusb`
