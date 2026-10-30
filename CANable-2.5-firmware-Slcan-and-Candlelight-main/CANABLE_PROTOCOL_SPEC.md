# CANable 2.5 USB-CAN 协议规范

基于 ElmueSoft Candlelight 固件源码整理，涵盖 Legacy GS 协议和 ElmueSoft 扩展协议。

## 1. USB 设备信息

| 项目 | 值 |
|------|-----|
| VID | `0x1D50` |
| PID | `0x606F` |
| 接口 | 0x00 = Candlelight, 0x01 = DFU |
| EP_IN | `0x81` (Bulk IN) |
| EP_OUT | `0x02` (Bulk OUT) |
| USB 速度 | Full Speed (12 Mbps) |

---

## 2. 控制请求 (eUsbRequest)

所有请求通过 Vendor 类控制传输发送，`bmRequestType` = `0x41`（OUT）或 `0xC1`（IN），Recipient = Interface。

### 2.1 GS 标准命令

| 值 | 名称 | 方向 | 数据 | 说明 |
|----|------|------|------|------|
| 0 | `GS_ReqSetHostFormat` | OUT | `uint32_t` | 设置字节序，必须写入 `0x0000BEEF`（小端） |
| 1 | `GS_ReqSetBitTiming` | OUT | `kBitTiming` (20 bytes) | 设置 Classic/Nominal 位时序 |
| 2 | `GS_ReqSetDeviceMode` | OUT | `kDeviceMode` (8 bytes) | 启动/停止 CAN 控制器 |
| 3 | `GS_ReqBerrReport` | — | — | 未实现 |
| 4 | `GS_ReqGetCapabilities` | IN | `kCapabilityClassic` (44 bytes) | 查询 Classic 能力 |
| 5 | `GS_ReqGetDeviceVersion` | IN | `kDeviceVersion` (16 bytes) | 查询固件/硬件版本 |
| 6 | `GS_ReqGetTimestamp` | IN | `uint32_t` (4 bytes) | 获取固件 1μs 时间戳（约1小时翻转） |
| 7 | `GS_ReqIdentify` | OUT | `uint32_t` | LED 闪烁识别（1=开始, 0=停止） |
| 8 | `GS_ReqGetUserID` | — | — | 未实现 |
| 9 | `GS_ReqSetUserID` | — | — | 未实现 |
| 10 | `GS_ReqSetBitTimingFD` | OUT | `kBitTiming` (20 bytes) | 设置 CAN FD 数据相位位时序 |
| 11 | `GS_ReqGetCapabilitiesFD` | IN | `kCapabilityFD` (72 bytes) | 查询 CAN FD 能力 |
| 12 | `GS_ReqSetTermination` | OUT | `uint32_t` | 设置 120Ω 终端电阻 (0=OFF, 1=ON) |
| 13 | `GS_ReqGetTermination` | IN | `uint32_t` (4 bytes) | 读取终端电阻状态 |
| 14 | `GS_ReqGetState` | — | — | 未实现（错误帧已替代） |

### 2.2 ElmueSoft 扩展命令

| 值 | 名称 | 方向 | 数据 | 说明 |
|----|------|------|------|------|
| 20 | `ELM_ReqGetBoardInfo` | IN | `kBoardInfo` (55 bytes) | 获取 MCU/板卡名称 |
| 21 | `ELM_ReqSetFilter` | OUT | `kFilter` (17 bytes) | 设置硬件验收过滤器（最多8个） |
| 22 | `ELM_ReqGetLastError` | IN | `uint8_t` (1 byte) | 获取上一条命令的执行结果 |
| 23 | `ELM_ReqSetBusLoadReport` | OUT | `uint8_t` (1 byte) | 启用总线负载百分比报告 (0=关闭) |
| 24 | `ELM_ReqSetPinStatus` | OUT | `kPinStatus` (12 bytes) | 控制处理器引脚 |
| 25 | `ELM_ReqGetPinStatus` | IN | `uint16_t` (2 bytes) | 读取引脚状态（PinID 在 `wValue` 中传递） |

---

## 3. 数据结构

### 3.1 kDeviceMode (8 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | mode | eDeviceMode: 0=Reset, 1=Start |
| 4 | 4 | flags | eDeviceFlags 的组合 |

### 3.2 kBitTiming (20 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | prop | 传播段（通常为0，已合并到 seg1） |
| 4 | 4 | seg1 | 时间段1（采样点前的时间量子数） |
| 8 | 4 | seg2 | 时间段2（采样点后的时间量子数） |
| 12 | 4 | sjw | 同步跳转宽度（应 ≤ min(seg1, seg2)） |
| 16 | 4 | brp | 比特率预分频器 |

CAN 时钟 = 160 MHz。比特率 = 160,000,000 / brp / (1 + seg1 + seg2)。

### 3.3 kCapabilityClassic (44 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | feature | eDeviceFlags 能力位 |
| 4 | 4 | fclk_can | CAN 时钟频率 (Hz) |
| 8 | 4 | time.seg1_min | 段1最小值 (始终1) |
| 12 | 4 | time.seg1_max | 段1最大值 |
| 16 | 4 | time.seg2_min | 段2最小值 (始终1) |
| 20 | 4 | time.seg2_max | 段2最大值 |
| 24 | 4 | time.sjw_max | SJW最大值 |
| 28 | 4 | time.brp_min | 预分频器最小值 |
| 32 | 4 | time.brp_max | 预分频器最大值 |
| 36 | 4 | time.brp_inc | 预分频器增量 |
| 40 | 4 | (padding) | — |

### 3.4 kCapabilityFD (72 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | feature | eDeviceFlags 能力位 |
| 4 | 4 | fclk_can | CAN 时钟频率 (Hz) |
| 8-39 | 32 | time_nom | kTimeMinMax: Nominal 位时序范围 |
| 40-71 | 32 | time_data | kTimeMinMax: Data 位时序范围 |

### 3.5 kDeviceVersion (16 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | reserved1 | — |
| 1 | 1 | reserved2 | — |
| 2 | 1 | reserved3 | — |
| 3 | 1 | icount | 始终0 |
| 4 | 4 | sw_version_bcd | 固件版本 (BCD, 如 0x251023 = "25.10.23") |
| 8 | 4 | hw_version_bcd | 硬件版本 (BCD) |
| 12 | 4 | (padding) | — |

### 3.6 kBoardInfo (55 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 2 | McuDeviceID | MCU 设备ID (如 0x468 = STM32G431) |
| 2 | 25 | McuName | MCU 名称 (如 "STM32G431xx") |
| 27 | 25 | BoardName | 板卡名称 (如 "MksMakerbase", "OpenlightLabs") |

字符串为 null 终止的 ASCII。

### 3.7 kFilter (17 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | Operation | eFilterOperation |
| 1 | 4 | Filter | 过滤器值 (如 0x7E0)，FIL_ClearAll 时忽略 |
| 5 | 4 | Mask | 掩码值 (如 0x7FF)，FIL_ClearAll 时忽略 |
| 9 | 4 | Reserved1 | — |
| 13 | 4 | Reserved2 | — |

### 3.8 kPinStatus (12 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 2 | Operation | ePinOperation |
| 2 | 2 | PinID | ePinID |
| 4 | 4 | Reserved1 | — |
| 8 | 4 | Reserved2 | — |

---

## 4. 设备标志 (eDeviceFlags)

### 4.1 GS 标准标志

| 值 | 名称 | 说明 |
|----|------|------|
| 0x0001 | `GS_DevFlagListenOnly` | 静默模式（不发送 ACK） |
| 0x0002 | `GS_DevFlagLoopback` | 回环模式。与 ListenOnly 组合=内部回环，否则=外部回环 |
| 0x0004 | `GS_DevFlagTripleSample` | 三次采样（未实现） |
| 0x0008 | `GS_DevFlagOneShot` | 单次发送（不重传，等 ACK 失败即止） |
| 0x0010 | `GS_DevFlagTimestamp` | 发送硬件时间戳（已弃用，增加 USB 开销） |
| 0x0020 | `GS_DevFlagIdentify` | LED 闪烁识别 |
| 0x0040 | `GS_DevFlagUserID` | 未实现 |
| 0x0080 | `GS_DevFlagPadPacketsToMaxSize` | 128字节填充（未实现，危险） |
| 0x0100 | `GS_DevFlagCAN_FD` | CAN FD 支持（能力标志）/ 启用 CAN FD（模式标志） |
| 0x0200 | `GS_DevFlagQuirk_LPC546XX` | LPC546XX 修复（未实现） |
| 0x0400 | `GS_DevFlagBitTimingFD` | 数据位时序设置支持 |
| 0x0800 | `GS_DevFlagTermination` | 终端电阻可控 |
| 0x1000 | `GS_DevFlagBerrReporting` | 未实现 |
| 0x2000 | `GS_DevFlagGetState` | 未实现（错误帧已替代） |

### 4.2 ElmueSoft 扩展标志

| 值 | 名称 | 说明 |
|----|------|------|
| 0x4000 | `ELM_DevFlagProtocolElmue` | 使用 ElmueSoft 可变长度协议（能力+模式标志） |
| 0x8000 | `ELM_DevFlagDisableTxEcho` | 禁止发送 TX Echo（减少 USB 流量） |

> `ELM_DevFlagProtocolElmue` 在 Capabilities 中表示"支持所有 ELM_ReqXXX 命令"，
> 在 `kDeviceMode.flags` 中表示"切换到 ElmueSoft 协议"。

---

## 5. 过滤器操作 (eFilterOperation)

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `FIL_ClearAll` | 清除所有过滤器 |
| 1 | `FIL_AcceptMask11bit` | 添加 11-bit ID 验收掩码过滤器 |
| 2 | `FIL_AcceptMask29bit` | 添加 29-bit ID 验收掩码过滤器 |

最多 8 个过滤器。过滤器基于 CAN 硬件验收滤波器，掩码位=1 表示"必须匹配"，掩码位=0 表示"忽略"。

---

## 6. 引脚操作

### 6.1 ePinOperation

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `PINOP_Reset` | 输出低电平 |
| 1 | `PINOP_Set` | 输出高电平 |
| 2 | `PINOP_Tristate` | 高阻态 |
| 3 | `PINOP_PullDown` | 启用下拉电阻 |
| 4 | `PINOP_PullUp` | 启用上拉电阻 |
| 5 | `PINOP_Disable` | 禁用引脚（用于 BOOT0 Option Bytes） |
| 6 | `PINOP_Enable` | 启用引脚 |

### 6.2 ePinID

| 值 | 名称 | 说明 |
|----|------|------|
| 1 | `PINID_BOOT0` | BOOT0 引脚（可通过 Option Bytes 禁用） |

### 6.3 ePinStatus（GetPinStatus 返回的位标志）

| 值 | 名称 | 说明 |
|----|------|------|
| 0x0001 | `PINST_High` | 引脚当前为高电平 |
| 0x0002 | `PINST_Enabled` | 引脚当前已启用 |

> `ELM_ReqGetPinStatus` 通过 SETUP.wValue 传递 PinID（不是 OUT 数据），
> 返回 2 字节的 ePinStatus 位标志。

---

## 7. 命令反馈码 (eFeedback)

`ELM_ReqGetLastError` 返回 1 字节，表示上一条 OUT 命令的执行结果。

| 值 | 名称 | 说明 |
|----|------|------|
| 1 | `FBK_RetString` | 已通过 USB 发送响应（仅内部使用） |
| 2 | `FBK_Success` | 命令成功执行 |
| 49 | `FBK_InvalidCommand` | 命令无效 |
| 50 | `FBK_InvalidParameter` | 参数无效 |
| 51 | `FBK_AdapterMustBeOpen` | 必须先打开适配器 |
| 52 | `FBK_AdapterMustBeClosed` | 必须先关闭适配器 |
| 53 | `FBK_ErrorFromHAL` | ST HAL 返回错误 |
| 54 | `FBK_UnsupportedFeature` | 不支持的功能 |
| 55 | `FBK_TxBufferFull` | 发送缓冲区已满（仅 Slcan） |
| 56 | `FBK_BusIsOff` | Bus-Off 状态，无法发送 |
| 57 | `FBK_NoTxInSilentMode` | 静默模式下无法发送 |
| 58 | `FBK_BaudrateNotSet` | 未设置比特率，无法启动 |
| 59 | `FBK_OptBytesProgrFailed` | Option Bytes 编程失败 |
| 60 | `FBK_ResetRequired` | 需要重新连接 USB 进入引导模式 |

> 重要：每条 `_ctrl_out` 命令后应调用 `ELM_ReqGetLastError` 检查执行结果。
> 返回 0 或 2 表示成功，其他值表示失败。

---

## 8. CAN ID 标志 (eCanIdFlags)

在帧的 `can_id` 字段中与实际 CAN ID 做 OR 运算：

| 值 | 名称 | 说明 |
|----|------|------|
| 0x20000000 | `CAN_ID_Error` | 错误帧（不含 CAN 总线数据） |
| 0x40000000 | `CAN_ID_RTR` | 远程帧 |
| 0x80000000 | `CAN_ID_29Bit` | 扩展帧 (29-bit ID) |

掩码：
- `CAN_MASK_11` = `0x000007FF`（标准 ID 低 11 位）
- `CAN_MASK_29` = `0x1FFFFFFF`（扩展 ID 低 29 位）

---

## 9. 帧标志 (eFrameFlags)

| 值 | 名称 | 说明 |
|----|------|------|
| 0x01 | `FRM_Overflow` | 溢出（未使用） |
| 0x02 | `FRM_FDF` | CAN FD 帧 |
| 0x04 | `FRM_BRS` | 比特率切换 |
| 0x08 | `FRM_ESI` | 错误状态指示 |

---

## 10. Legacy 协议帧格式 (80 bytes fixed)

### 10.1 kHostFrameLegacy

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 4 | echo_id | eEchoID: 0xFFFFFFFF=RX帧, 其他=TX Echo |
| 4 | 4 | can_id | CAN ID + eCanIdFlags / 错误标志 |
| 8 | 1 | can_dlc | DLC (0-15) |
| 9 | 1 | channel | 未使用，始终0 |
| 10 | 1 | flags | eFrameFlags |
| 11 | 1 | reserved | 未使用 |
| 12-79 | 68 | union | kPacketClassic 或 kPacketFD |

### 10.2 kPacketClassic (12 bytes 有效 + 填充)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 12 | 8 | data[8] | 数据字节 |
| 20 | 4 | timestamp_us | 1μs 精度时间戳（在数据后面！） |

### 10.3 kPacketFD (68 bytes 有效)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 12 | 64 | data[64] | 数据字节（始终64字节，即使DLC<64！） |
| 76 | 4 | timestamp_us | 1μs 精度时间戳 |

> Legacy 协议的设计缺陷：
> - 8字节数据的 CAN FD 帧也传输 64 字节
> - 时间戳在数据后面（"stupid design"）
> - TX 帧始终回显，无法关闭
> - 错误帧反复发送（每秒数百次）

---

## 11. ElmueSoft 可变长度协议

### 11.1 消息类型 (eMessageType)

| 值 | 名称 | 方向 | 说明 |
|----|------|------|------|
| 10 | `MSG_TxFrame` | Host→Device | 发送 CAN 帧 |
| 11 | `MSG_TxEcho` | Device→Host | TX 发送确认（可用 DisableTxEcho 关闭） |
| 12 | `MSG_RxFrame` | Device→Host | 接收到的 CAN 帧 |
| 13 | `MSG_Error` | Device→Host | 错误帧 |
| 14 | `MSG_String` | Device→Host | ASCII 调试字符串 |
| 15 | `MSG_Busload` | Device→Host | 总线负载百分比 |

### 11.2 公共头部 (kHeader)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | 整条消息总长度（包含 header） |
| 1 | 1 | msg_type | eMessageType |

### 11.3 TX 帧 (MSG_TxFrame, kTxFrameElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = 8 + 数据长度 |
| 1 | 1 | msg_type | = 10 (MSG_TxFrame) |
| 2 | 1 | flags | eFrameFlags |
| 3 | 4 | can_id | CAN ID + eCanIdFlags |
| 7 | 1 | marker | 1字节标记（1-255），TX Echo 时原样返回 |
| 8 | N | data | 数据字节（长度 = size - 8） |

> DLC 字节不需要：数据长度 = `header.size - sizeof(kTxFrameElmue)`
>
> ZLP (Zero-Length Packet)：当 USB 传输大小为 64 的整数倍时，必须追加一个空包。

### 11.4 RX 帧 (MSG_RxFrame, kRxFrameElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = header + flags(1) + can_id(4) + [timestamp(4)] + data |
| 1 | 1 | msg_type | = 12 (MSG_RxFrame) |
| 2 | 1 | flags | eFrameFlags |
| 3 | 4 | can_id | CAN ID + eCanIdFlags |
| 7 | 0/4 | timestamp | 1μs 时间戳（仅当 GS_DevFlagTimestamp 已设置时存在） |
| 7/11 | N | data | 数据字节 |

时间戳模式由 `GS_DevFlagTimestamp` 决定：
- **无时间戳**：数据从 offset 7 开始
- **有时间戳**：4字节时间戳在 offset 7，数据从 offset 11 开始

### 11.5 TX Echo (MSG_TxEcho, kTxEchoElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = 2 + 1 + [4] = 3 或 7 |
| 1 | 1 | msg_type | = 11 (MSG_TxEcho) |
| 2 | 1 | marker | 与 kTxFrameElmue 中发送的 marker 相同 |
| 3 | 0/4 | timestamp | 1μs 时间戳（仅当 GS_DevFlagTimestamp 已设置时存在） |

### 11.6 错误帧 (MSG_Error, kErrorElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = 2 + 4 + 8 + [4] = 14 或 18 |
| 1 | 1 | msg_type | = 13 (MSG_Error) |
| 2 | 4 | err_id | eErrFlagsCanID |
| 6 | 8 | err_data | 见下表 |
| 14 | 0/4 | timestamp | 1μs 时间戳（仅当 GS_DevFlagTimestamp 已设置时存在） |

### 11.7 字符串消息 (MSG_String, kStringElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = 2 + 字符串长度 |
| 1 | 1 | msg_type | = 14 (MSG_String) |
| 2 | N | ascii_msg | ASCII 字符串 |

### 11.8 总线负载消息 (MSG_Busload, kBusloadElmue)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 1 | size | = 3 |
| 1 | 1 | msg_type | = 15 (MSG_Busload) |
| 2 | 1 | bus_load | 总线负载百分比 (0-100) |

---

## 12. 错误帧数据详细格式

错误帧的 `err_data[8]` 各字节含义：

| Byte | Name | Description |
|------|------|-------------|
| 0 | — | 始终为0 |
| 1 | Byte1 | 总线状态 + 错误等级 |
| 2 | Byte2 | 协议违规类型 |
| 3 | Byte3 | 协议违规位置（STM32不提供此细节） |
| 4 | Byte4 | 收发器错误（CAN-H/CAN-L 物理层故障） |
| 5 | Byte5 | ElmueSoft 应用错误标志 |
| 6 | Byte6 | TX 错误计数器 (TEC) |
| 7 | Byte7 | RX 错误计数器 (REC) |

### 12.1 eErrFlagsCanID (err_id, 32-bit)

| 位 | 名称 | 说明 |
|----|------|------|
| 0x0001 | `ERID_Tx_Timeout` | TX 超时 |
| 0x0002 | `ERID_Arbitration_lost` | 仲裁丢失 |
| 0x0004 | `ERID_Controller_problem` | 总线状态变化（冗余，Byte1 已包含） |
| 0x0008 | `ERID_Protocol_violation` | 协议违规（冗余，Byte2/3 已包含） |
| 0x0010 | `ERID_Transceiver_error` | 收发器错误（冗余，Byte4 已包含） |
| 0x0020 | `ERID_No_ACK_received` | 未收到 ACK |
| 0x0040 | `ERID_Bus_is_off` | Bus-Off |
| 0x0080 | `ERID_Bus_error` | 总线错误 |
| 0x0100 | `ERID_Controller_restarted` | 控制器已重启 |
| 0x0200 | `ERID_CRC_Error` | CRC 错误（ElmueSoft 新增） |

### 12.2 Byte1: 总线状态 + 错误等级

高 4 位 (bits 7:4) = eErrorBusStatus：

| 值 | 名称 | 说明 |
|----|------|------|
| 0x00 | `BUS_StatusActive` | 正常运行（无错误） |
| 0x10 | `BUS_StatusWarning` | >96 个错误，警告级别 |
| 0x20 | `BUS_StatusPassive` | >128 个错误，被动错误 |
| 0x30 | `BUS_StatusOff` | >248 个错误，Bus-Off |

低 4 位 (bits 3:0)：

| 位 | 名称 | 说明 |
|----|------|------|
| 0x01 | `ER1_Rx_Buffer_Overflow` | RX 缓冲区溢出（仅 Legacy） |
| 0x02 | `ER1_Tx_Buffer_Overflow` | TX 缓冲区溢出（仅 Legacy） |
| 0x04 | `ER1_Rx_Errors_at_warning_level` | RX 错误达到警告级别 |
| 0x08 | `ER1_Tx_Errors_at_warning_level` | TX 错误达到警告级别 |
| 0x10 | `ER1_Rx_Passive_status_reached` | RX 达到被动错误状态 |
| 0x20 | `ER1_Tx_Passive_status_reached` | TX 达到被动错误状态 |
| 0x40 | `ER1_Bus_is_back_active` | 恢复到 Active 状态（不是错误！） |

### 12.3 Byte2: 协议违规类型

| 位 | 名称 | 说明 |
|----|------|------|
| 0x01 | `ER2_Single_bit_error` | 单比特错误 |
| 0x02 | `ER2_Frame_format_error` | 帧格式错误 |
| 0x04 | `ER2_Bit_stuffing_error` | 位填充错误 |
| 0x08 | `ER2_Unable_to_send_dominant_bit` | 无法发送显性位 |
| 0x10 | `ER2_Unable_to_send_recessive_bit` | 无法发送隐性位 |
| 0x20 | `ER2_Bus_overload` | 总线过载 |
| 0x40 | `ER2_Active_error_announcement` | 主动错误声明 |
| 0x80 | `ER2_Transmission_error` | 发送时发生错误 |

### 12.4 Byte3: 协议违规位置

STM32 处理器通常不提供此细节。常见值：

| 值 | 名称 |
|----|------|
| 0x02 | ID bits 28-21 (SFF: 10-3) |
| 0x03 | SOF |
| 0x04 | RTR substitute |
| 0x05 | IDE bit |
| 0x0A | 数据段 |
| 0x0B | DLC 位 |
| 0x12 | Intermission |
| 0x18 | CRC delimiter |
| 0x19 | ACK slot |
| 0x1A | EOF |

### 12.5 Byte4: 收发器物理层错误

高 4 位 = CAN-H 错误：

| 值 | 名称 | 说明 |
|----|------|------|
| 0x04 | `ER4_CAN_H_No_wire` | CAN-H 未接线 |
| 0x05 | `ER4_CAN_H_Shortcut_to_Bat` | CAN-H 短路到电池 |
| 0x06 | `ER4_CAN_H_Shortcut_to_VCC` | CAN-H 短路到 VCC |
| 0x07 | `ER4_CAN_H_Shortcut_to_GND` | CAN-H 短路到 GND |

掩码：`ER4_CAN_H_MASK = 0x0F`

低 4 位 = CAN-L 错误：

| 值 | 名称 | 说明 |
|----|------|------|
| 0x40 | `ER4_CAN_L_No_wire` | CAN-L 未接线 |
| 0x50 | `ER4_CAN_L_Shortcut_to_Bat` | CAN-L 短路到电池 |
| 0x60 | `ER4_CAN_L_Shortcut_to_VCC` | CAN-L 短路到 VCC |
| 0x70 | `ER4_CAN_L_Shortcut_to_GND` | CAN-L 短路到 GND |
| 0x80 | `ER4_CAN_L_Shortcut_CAN__H` | CAN-L 与 CAN-H 短路 |

掩码：`ER4_CAN_L_MASK = 0xF0`

### 12.6 Byte5: ElmueSoft 应用错误标志

| 位 | 名称 | 说明 |
|----|------|------|
| 0x01 | `APP_CanRxFail` | HAL 报告 CAN 接收错误 |
| 0x02 | `APP_CanTxFail` | 发送失败（静默模式/Bus-Off/未启动/HAL错误） |
| 0x04 | `APP_CanTxOverflow` | TX FIFO+缓冲区满（通常是被动错误导致） |
| 0x08 | `APP_UsbInOverflow` | USB IN 发送速度跟不上 CAN 流量 |
| 0x10 | `APP_CanTxTimeout` | 发送帧 500ms 内未收到 ACK，已中止并清空 TX 缓冲区 |

---

## 13. CAN FD DLC 映射

| DLC | 字节数 | DLC | 字节数 |
|-----|--------|-----|--------|
| 0 | 0 | 8 | 8 |
| 1 | 1 | 9 | 12 |
| 2 | 2 | 10 | 16 |
| 3 | 3 | 11 | 20 |
| 4 | 4 | 12 | 24 |
| 5 | 5 | 13 | 32 |
| 6 | 6 | 14 | 48 |
| 7 | 7 | 15 | 64 |

---

## 14. 位时序表

CAN 时钟 = 160 MHz，所有时序参数格式：(brp, seg1, seg2, sjw)。

### 14.1 Nominal Bit Timing

| 比特率 | brp | seg1 | seg2 | sjw | 采样点 |
|--------|-----|------|------|-----|--------|
| 10 kbps | 80 | 174 | 25 | 25 | 87.5% |
| 20 kbps | 40 | 174 | 25 | 25 | 87.5% |
| 50 kbps | 16 | 174 | 25 | 25 | 87.5% |
| 83.3 kbps | 10 | 167 | 24 | 24 | 87.5% |
| 100 kbps | 8 | 174 | 25 | 25 | 87.5% |
| 125 kbps | 8 | 139 | 20 | 20 | 87.5% |
| 250 kbps | 4 | 139 | 20 | 20 | 87.5% |
| 500 kbps | 2 | 139 | 20 | 20 | 87.5% |
| 800 kbps | 1 | 174 | 25 | 25 | 87.5% |
| 1 Mbps | 1 | 139 | 20 | 20 | 87.5% |

### 14.2 Data Bit Timing (CAN FD)

STM32G4 FDCAN 数据相位限制：TSEG1≤15, TSEG2≤15, SJW≤15。

固件内置值：Seg1=5, Seg2=2, 采样点=75%。

| 比特率 | brp | seg1 | seg2 | sjw | 采样点 |
|--------|-----|------|------|-----|--------|
| 500 kbps | 40 | 5 | 2 | 2 | 75% |
| 1 Mbps | 20 | 5 | 2 | 2 | 75% |
| 2 Mbps | 10 | 5 | 2 | 2 | 75% |
| 4 Mbps | 5 | 5 | 2 | 2 | 75% |
| 5 Mbps | 4 | 5 | 2 | 2 | 75% |
| 8 Mbps | 5 | 1 | 2 | 2 | 50% |

> **重要**：数据位时序必须使用固件内置值。错误的 Seg1 值会导致固件返回
> `FBK_InvalidParameter` (eFeedback=50)，数据比特率未存储，启动时返回
> `FBK_BaudrateNotSet` (eFeedback=58)。

---

## 15. 重要注意事项

### 15.1 CAN FD 启动顺序

1. 先设置 Nominal 位时序 (`GS_ReqSetBitTiming`)
2. 再设置 Data 位时序 (`GS_ReqSetBitTimingFD`)
3. 最后启动 (`GS_ReqSetDeviceMode` + `GS_DevFlagCAN_FD`)

**在 `start()` 之后设置数据位时序会静默失败。**

### 15.2 BRSE (Bit Rate Switch) 要求

- BRSE 仅在 `data_bitrate > nominal_bitrate` 时由固件启用
- 如果两者相等，BRSE=0，FDCAN 会丢弃所有 BRS=1 的 FD 帧
- 要接收对端 BRS 帧，必须设置 data_bitrate 为对端实际数据相位速率

### 15.3 ZLP (Zero-Length Packet)

当 USB 传输大小为 64 的整数倍时，必须发送一个空包作为短包终止，否则接收端无法确定传输结束。

### 15.4 命令错误检查

每个 `ctrl_out` 命令后应调用 `ELM_ReqGetLastError` 检查执行结果。忽略此步骤可能导致静默失败。

### 15.5 时间戳翻转

固件时间戳为 32-bit μs 精度，约 4294 秒（~71.5 分钟）后翻转。主机应实现翻转检测。

### 15.6 TX Marker

ElmueSoft 协议的 TX 帧使用 1 字节 marker (1-255)，TX Echo 时原样返回用于匹配。0 不使用。

---

## 16. 协议对比

| 特性 | Legacy (GS) | ElmueSoft |
|------|-------------|-----------|
| 帧大小 | 固定 80 字节 | 可变长度 |
| 8字节FD帧开销 | 80 字节 | 15 字节 |
| TX Echo | 强制，不可关闭 | 可用 DisableTxEcho 关闭 |
| 错误帧 | 重复发送（每秒数百次） | 状态变化时发送一次 |
| 时间戳 | 始终发送 | 可选（减少 USB 开销） |
| 调试字符串 | 不支持 | MSG_String |
| 总线负载 | 不支持 | MSG_Busload |
| 硬件过滤器 | 不支持 | ELM_ReqSetFilter |
| 板卡信息 | 不支持 | ELM_ReqGetBoardInfo |
| 引脚控制 | 不支持 | ELM_ReqSetPinStatus/GetPinStatus |
