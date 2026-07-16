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
from canable_sdk import ZDTCanable, CANFrame, logger, CANABLE_VID, CANABLE_PID
```

### ZDTCanable

#### 设备枚举与连接

| 方法 | 说明 |
|------|------|
| `list_devices()` | 静态方法，列出所有 CANable 设备（返回 dict 列表：vid/pid/manufacturer/product/serial） |
| `open()` | 打开设备连接（自动初始化、检测协议） |
| `close()` | 关闭连接（停止 CAN、释放 USB 资源） |
| 上下文管理器 | 支持 `with ZDTCanable() as bus:` |

#### CAN 控制器生命周期

| 方法 | 说明 |
|------|------|
| `start(loopback=False, disable_echo=False, one_shot=False)` | 启动 CAN 控制器，自动按 `fd_mode`/`silent` 设置标志 |
| `stop()` | 停止 CAN 控制器 |
| `recover()` | 从 bus-off 恢复：复位 → 清缓冲 → 重新设置位定时 → 重启，并启用 500ms TX 冷却 |

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
| `set_bus_load_report(interval)` | 启用/关闭总线负载百分比报告（0=off, 1..255=周期） |
| `set_pin_status(pin_id, operation)` | 控制处理器引脚（如 BOOT0：`PINOP_Reset`/`PINOP_Set`/`PINOP_Tristate` 等） |
| `get_pin_status(pin_id)` | 读取引脚状态位标志（`PINST_High`/`PINST_Enabled`） |

#### 回调与后台监听

| 方法 | 说明 |
|------|------|
| `on_receive(callback)` | 注册接收回调（参数为 `CANFrame`） |
| `on_overflow(callback)` | 注册溢出回调 |
| `start_listening()` | 启动后台接收线程，自动分发到已注册回调 |

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
| `to_legacy_bytes()` | 序列化为 Legacy 80 字节帧 |
| `from_legacy_bytes(raw)` (classmethod) | 从 Legacy 80 字节帧解析（含错误帧识别） |

## FD 模式配置顺序

```python
bus.fd_mode = True                        # 1. 开启 FD
bus.set_bitrate(500_000)                  # 2. 标称波特率
bus.set_data_bitrate(2_000_000)           # 3. 数据相波特率（必须 > 标称以启用 BRS）
bus.start()                               # 4. 启动
```

⚠️ **关键约束**：

- `set_data_bitrate()` 必须在 `start()` **之前**调用，启动后设置会静默失败
- `start()` 时会自动在 flags 中加上 `GS_DevFlagCAN_FD`，否则 STM32 FDCAN 运行在 Classic 模式会丢弃 FD 帧
- 若对端使用 BRS（数据波特率 > 标称），`data_bitrate` **必须大于** `nominal_bitrate`，否则固件不会置 BRSE 位，FDCAN 会丢弃所有 BRS=1 的帧
- 数据相时序限制：TSEG1≤15, TSEG2≤15, SJW≤15（STM32G4 硬件限制），固件内置值为 Seg1=5、Seg2=2、采样点 75%
- 错误的 Seg1 会触发 `FBK_InvalidParameter` (eFeedback=50)，导致数据比特率未存储，启动时返回 `FBK_BaudrateNotSet` (58)

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
- **Legacy 固定 80 字节协议**：向后兼容旧固件，TX 始终回显不可关闭，错误帧每秒重复数百次

## 错误处理

- 每个 `ctrl_out` 命令后自动调用 `ELM_ReqGetLastError` 检查执行结果，失败时通过 logger 输出 `eFeedback` 名称
- `send()` 遇到 USB pipe 错误时自动清除 STALL、调用 `recover()`、设置 500ms TX 冷却期
- `receive()` 遇到 USB overflow 时自动清空端点缓冲
- 错误帧解析支持 `eErrFlagsCanID` 全部位（`Bus-off`/`No-ACK`/`CRC-Err`/`Arbitration lost` 等）和 Byte1-Byte5 详细字段

## 命令行工具

```bash
python -m canable_sdk           # Classic CAN 模式监听
python -m canable_sdk --fd      # CAN FD 模式监听（2M 数据相）
```

启动后会列出所有设备，自动以 500kbps（FD 模式外加 2Mbps 数据相）启动并打印所有收到的帧，`Ctrl+C` 退出。

## 平台支持

- **Linux**：udev 规则 + libusb（`apt install libusb-1.0-0`）
- **Windows**：WinUSB 驱动（固件支持自动安装）+ `libusb-1.0.dll`
- **macOS**：`brew install libusb`
