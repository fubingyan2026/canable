# CANable 2.5 ElmueSoft 驱动完全重写计划

## Context

固件已从 kazu-321 candlelight 更新为 CANable 2.5 ElmueSoft 版本。新固件使用全新的 ElmueSoft 变长协议（可变长度、类型化消息），USB OUT 端点从 0x03 改为 0x02，新增过滤器、终端电阻、总线负载等功能。旧驱动完全不兼容，需要彻底重写。

## 核心变更

| 项目 | 旧驱动 (kazu-321) | 新驱动 (ElmueSoft) |
|------|-------------------|-------------------|
| 协议 | Legacy 80字节固定帧 | ElmueSoft 变长消息 (kHeader + 类型数据) |
| OUT端点 | 0x03 | **0x02** |
| ZLP | 不需要 | 64倍数长度时必须发送/接收ZLP |
| 位定时 | _calc_btr()动态计算 | 固件预定义表，发送kBitTiming结构 |
| TX echo | echo_id回环完整帧 | marker(1字节)确认 |
| 错误帧 | CAN_ERR_FLAG标志 | MSG_Error消息，eErrFlagsCanID |
| 控制请求 | GS_Req* (14个) | GS_Req* + ELM_Req* (19个) |
| 错误反馈 | 无 | 每次ctrl_out后必须调ELM_ReqGetLastError |
| FD启动 | 先start再设data bitrate | **必须先设data bitrate再start** |

## 修改文件

### 1. 重写: `zdt_canable.py`

保持 API 不变（ZDTCanable + CANFrame），内部完全重写：

- **CANFrame类**: 保留全部字段(can_id,data,extended,rtr,fd,brs,esi,timestamp,is_tx,echo_id,_error_info)和属性(is_error,dlc)
  - 新增: `to_elmue_bytes(marker)` / `from_elmue_rx()` / `from_elmue_echo()` / `from_legacy_bytes()`
  - 删除: `to_bytes()` / `from_bytes()`

- **_ElmueProtocol类**: 变长消息流解析器
  - 字节流缓冲区，按 {size, msg_type} 头解析消息边界
  - 分发: MSG_RxFrame→CANFrame, MSG_TxEcho→CANFrame(is_tx), MSG_Error→CANFrame(is_error), MSG_String→日志, MSG_Busload→日志

- **ZDTCanable类**: 保持所有方法签名
  - `open()`: VID=0x1D50/PID=0x606F, EP_IN=0x81/EP_OUT=0x02
  - `_ctrl_out_checked()`: 每次控制OUT后自动调ELM_ReqGetLastError
  - `start()`: flags包含ELM_DevFlagProtocolElmue, FD需先设data_bitrate
  - `set_bitrate()`: 用预定义表构造kBitTiming{prop=0,seg1,seg2,sjw,brp}
  - `send()`: ElmueSoft kTxFrameElmue格式 + marker + ZLP
  - `receive()`: 读256字节喂入_ElmueProtocol解析器
  - `recover()`: RESET→重新位定时→START
  - 删除: slcan后端(_is_slcan, _delegate, _slcan_obj)

- **位定时表** (从固件源码can.c提取):
  - 标称: 10k/20k/50k/100k/125k/250k/500k/800k/1M
  - 数据: 500k/1M/2M/4M/5M/8M

### 2. 删除: `zdt_canable_slcan.py`

整个文件删除，不再需要slcan后端。

### 3. 微调: `cangui/worker.py`

- 错误帧判断逻辑: 保持`"BUS-OFF"`/`"NO-ACK"`子串匹配（新驱动的MSG_Error解析生成相同格式）
- 删除slcan相关导入/检查（如果有的话）

### 4. 微调: `cangui/main_window.py`

- `list_devices()`返回格式保持不变（dict with backend/vid/pid/manufacturer/product/serial/path）
- `identify()`和`set_silent()`签名不变

## 关键实现细节

1. **ELM_ReqGetLastError**: 新固件无法在EP0数据阶段STALL，每次ctrl_out后必须读此请求确认成功。eFeedback=2表示成功，非2表示失败。

2. **ZLP处理**: TX时如果数据长度是64倍数，需额外write(b'')。RX时pyusb自动处理ZLP终止。

3. **CAN FD数据填充**: ElmueSoft协议TX帧数据按DLC边界填充(8,12,16,20,24,32,48,64)。RX时真实长度从header.size计算。

4. **marker机制**: TX时分配1-255循环marker，固件在MSG_TxEcho中回传同一marker。

5. **FD模式顺序**: 必须先set_data_bitrate()再start()，否则固件拒绝启动FD模式。

## 验证

1. 连接设备，验证open()成功（VID/PID/端点正确）
2. 设置1Mbps标称波特率，start()，验证RX接收正常
3. 发送经典CAN帧，验证TX成功
4. 设置2Mbps数据相波特率，勾选FD+BRS，验证FD帧收发
5. 断开CAN线，验证NO-ACK错误帧（不触发recover）
6. 发送64字节FD帧，验证ZLP处理
7. 验证Bus-Off后自动recover()
