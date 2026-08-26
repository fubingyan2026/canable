/**
 * @file candlelight_def.h
 * @brief USB-CAN 协议定义：传统 GS 协议与 ElmueSoft CANable 2.5 协议的命令、标志、帧结构
 */

/*
    The MIT License
    传统 USB GS 类（Geschwister Schneider 协议）与新 ElmueSoft CANable 2.5 协议的实现
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once

#include <stdint.h>

// GCC 兼容的紧凑结构体属性宏
// HAL 头(stm32g4xx_hal_def.h)只定义了 __packed，未定义 __aligned；
// 此处自包含定义，避免依赖 HAL 头链的包含顺序
#ifndef __packed
#define __packed __attribute__((__packed__))
#endif
#ifndef __aligned
#define __aligned(x) __attribute__((aligned(x)))
#endif

/**
 * @brief 主机通过 SETUP 请求发送的命令（8 位传输）
 */
typedef enum
{
    // ---------- Geschwister Schneider 的 GS 命令 -----------
    GS_ReqSetHostFormat = 0, /**< 定义大/小端字节序（仅支持小端） */
    GS_ReqSetBitTiming, /**< 设置 CAN 经典帧/标称位时序（波特率 + 采样点） */
    GS_ReqSetDeviceMode, /**< 启动/停止 CAN 设备并设置设备标志 */
    GS_ReqBerrReport, /**< 未实现、无文档 */
    GS_ReqGetCapabilities, /**< 获取经典帧能力与处理器时序限制 */
    GS_ReqGetDeviceVersion, /**< 获取版本号 */
    GS_ReqGetTimestamp, /**< 获取固件 1 µs 时间戳（需溢出检测，一小时后溢出） */
    GS_ReqIdentify, /**< 闪烁 LED 以识别设备（参数被忽略） */
    GS_ReqGetUserID, /**< 未实现、无文档 */
    GS_ReqSetUserID, /**< 未实现、无文档 */
    GS_ReqSetBitTimingFD, /**< 设置 FD 数据位时序（数据波特率 + 采样点） */
    GS_ReqGetCapabilitiesFD, /**< 获取 CAN FD 能力与处理器时序限制 */
    GS_ReqSetTermination, /**< 使能 120Ω 终端电阻（如果电路板支持） */
    GS_ReqGetTermination, /**< 获取 120Ω 终端电阻状态（如果电路板支持） */
    GS_ReqGetState, /**< 未实现、无文档 */

    // ----------- ElmueSoft 添加的 ELM 命令 -----------
    ELM_ReqGetBoardInfo = 20, /**< 获取目标板与处理器的名称信息 */
    ELM_ReqSetFilter, /**< 设置最多 8 个接受掩码过滤器 */
    ELM_ReqGetLastError, /**< 获取上一条 SETUP 命令的 eFeedback 错误 */
    ELM_ReqSetBusLoadReport, /**< 使能总线负载（百分比）按用户定义的间隔上报 */
    ELM_ReqSetPinStatus, /**< 设置、复位、使能、禁用等处理器引脚操作 */
    ELM_ReqGetPinStatus, /**< 接收：SETUP.wValue = ePinID；发送：2 字节 ePinStatus */
} eUsbRequest;

/**
 * @brief 设备特性标志
 * @details 用于 GS_ReqSetDeviceMode 使能/禁用模式，同时经 GS_ReqGetCapabilities
 *          和 GS_ReqGetCapabilitiesFD 返回给主机（32 位传输）
 */
typedef enum
{
    GS_DevFlagNone = 0,
    // ----------- Geschwister Schneider 的 GS 标志 -----------
    /** @brief 只听模式（不发送 ACK） */
    GS_DevFlagListenOnly = 0x00001,
    /** @brief 回环模式：与 ListenOnly 组合为内部回环，否则为外部回环 */
    GS_DevFlagLoopback = 0x00002,
    /** @brief 每 bit 采样 3 次（未实现） */
    GS_DevFlagTripleSample = 0x00004,
    /** @brief 单次发送：报文只发一次，不重发等 ACK */
    GS_DevFlagOneShot = 0x00008,
    /**
     * @brief 为 Rx 报文与 Tx 回显附带硬件时间戳（已弃用）
     * @details 全速 USB 下徒增流量，时间戳应在主机端接收时生成
     */
    GS_DevFlagTimestamp = 0x00010,
    /** @brief 闪烁 LED 以区分多个连接的设备 */
    GS_DevFlagIdentify = 0x00020,
    /** @brief 未实现、无文档 */
    GS_DevFlagUserID = 0x00040,
    /** @brief 总是发送 128 字节 USB 包（未实现） */
    GS_DevFlagPadPacketsToMaxSize = 0x00080,
    /** @brief 在特性中表示支持 CAN FD；在 kDeviceMode 中无用（数据波特率设置即自动启用） */
    GS_DevFlagCAN_FD = 0x00100,
    /** @brief LPC546XX USB.15 勘误变通（未实现） */
    GS_DevFlagQuirk_LPC546XX = 0x00200,
    /** @brief 支持设置 CAN FD 数据位时序 */
    GS_DevFlagBitTimingFD = 0x00400,
    /** @brief 120Ω 终端电阻可由命令开关（仅少数板支持） */
    GS_DevFlagTermination = 0x00800,
    /** @brief 未实现、无文档 */
    GS_DevFlagBerrReporting = 0x01000,
    /** @brief 未实现：错误经特殊错误帧自动上报，无需主机轮询 */
    GS_DevFlagGetState = 0x02000,

    // ----------- ElmueSoft 添加的 ELM 标志 -----------
    /** @brief 启用 ElmueSoft 新协议；在 Capabilities 中表示支持所有 ELM_ReqXXX 命令 */
    ELM_DevFlagProtocolElmue = 0x04000,
    /** @brief 关闭 Tx 回显（减少 USB 流量） */
    ELM_DevFlagDisableTxEcho = 0x08000,
} eDeviceFlags;

// ==============================================================================

/**
 * @brief 设备版本号结构（GS_ReqGetDeviceVersion 应答）
 */
typedef struct
{
    uint8_t reserved1; /**< 保留 */
    uint8_t reserved2; /**< 保留 */
    uint8_t reserved3; /**< 保留 */
    uint8_t icount; /**< 恒为零（无文档） */
    uint32_t sw_version_bcd; /**< 软件（固件）版本，BCD 格式 */
    uint32_t hw_version_bcd; /**< 硬件版本，BCD 格式 */
} __packed __aligned(4) kDeviceVersion;

// ---------------

/**
 * @brief 设备工作模式（GS_ReqSetDeviceMode，32 位传输）
 */
typedef enum
{
    GS_ModeReset = 0, /**< 关闭 CAN 接口 */
    GS_ModeStart, /**< 打开 CAN 接口 */
} eDeviceMode;

/**
 * @brief 设备模式命令载荷（GS_ReqSetDeviceMode）
 */
typedef struct
{
    uint32_t mode; /**< eDeviceMode */
    uint32_t flags; /**< eDeviceFlags */
} __packed __aligned(4) kDeviceMode;

// ---------------

/**
 * @brief 终端电阻状态（GS_ReqGetTermination / GS_ReqSetTermination，32 位传输）
 */
typedef enum
{
    GS_TerminationOFF = 0, /**< 关闭终端电阻 */
    GS_TerminationON, /**< 打开终端电阻 */
} eTermination;

// ---------------

/**
 * @brief CAN 位时序参数（GS_ReqSetBitTiming / GS_ReqSetBitTimingFD）
 */
typedef struct
{
    uint32_t prop; /**< 传播段（并入段 1；遗留字段，恒可为 0） */
    uint32_t seg1; /**< 时间段 1（采样点前的时间量子数） */
    uint32_t seg2; /**< 时间段 2（采样点后的时间量子数） */
    uint32_t sjw; /**< 同步跳转宽度，应为 min(seg1, seg2) */
    uint32_t brp; /**< 波特率预分频器 */
} __packed __aligned(4) kBitTiming;

// ---------------

/**
 * @brief 位时序最小/最大值（能力应答的一部分）
 */
typedef struct
{
    uint32_t seg1_min; /**< 时间段 1 最小值（恒为 1） */
    uint32_t seg1_max; /**< 时间段 1 最大值（含传播段） */
    uint32_t seg2_min; /**< 时间段 2 最小值（恒为 1） */
    uint32_t seg2_max; /**< 时间段 2 最大值 */
    uint32_t sjw_max; /**< 同步跳转宽度最大值 */
    uint32_t brp_min; /**< 波特率预分频器最小值 */
    uint32_t brp_max; /**< 波特率预分频器最大值 */
    uint32_t brp_inc; /**< 无文档 */
} __packed kTimeMinMax;

/**
 * @brief 经典帧能力（GS_ReqGetCapabilities 应答，所有设备必须返回）
 */
typedef struct
{
    uint32_t feature; /**< eDeviceFlags 特性标志 */
    uint32_t fclk_can; /**< CAN 时钟频率，被波特率预分频器分频 */
    kTimeMinMax time; /**< 经典帧位速率最小/最大值 */
} __packed __aligned(4) kCapabilityClassic;

/**
 * @brief CAN FD 能力（GS_ReqGetCapabilitiesFD 应答，仅 FD 设备支持）
 */
typedef struct
{
    uint32_t feature; /**< eDeviceFlags 特性标志 */
    uint32_t fclk_can; /**< CAN 时钟频率，被波特率预分频器分频 */
    kTimeMinMax time_nom; /**< FD 标称位速率最小/最大值 */
    kTimeMinMax time_data; /**< FD 数据位速率最小/最大值 */
} __packed __aligned(4) kCapabilityFD;

// ---------------

/*
// 以下内容从未在 Github 上的固件中实现过。
// 该结构体已被带 CAN_ID_Error 标志的错误报文取代。
// 其优点在于：错误只在出现时自动发送给主机。
// GS_ReqGetState / kDeviceState 很笨拙，因为主机必须轮询错误。

// 未使用（之前打算用此结构体配合 GS_ReqGetState）
typedef enum // 以 32 位传输
{
    GS_BusActive = 0, // 无 CAN 总线错误
    GS_ErrorWarning,  // >=  96 个错误
    GS_ErrorPassive,  // >= 128 个错误
    GS_BusOff,        // >= 248 个错误
    GS_Stopped,
    GS_Sleeping,
} eBusState;

// 未使用（之前打算用此结构体配合 GS_ReqGetState）
typedef struct
{
    uint32_t state;  // eBusState
    uint32_t rx_err; // RX 错误计数（0 ... 248）
    uint32_t tx_err; // TX 错误计数（0 ... 248）
} __packed __aligned(4) kDeviceState;

*/

// =========================== 错误上报 =============================

/**
 * @brief 错误帧数据布局
 * @details 错误经特殊错误帧的 CAN ID 与数据字节上报，最多 8 个数据字节：
 *          CanID = eErrFlagsCanID
 *          data[0] = 恒为零
 *          data[1] = eErrFlagsByte1
 *          data[2] = eErrFlagsByte2
 *          data[3] = eErrFlagsByte3（处理器未提供，恒为零）
 *          data[4] = eErrFlagsByte4_Hi + eErrFlagsByte4_Lo（处理器未提供，恒为零）
 *          data[5] = eErrorAppFlags（ElmueSoft 补充，见 settings.h）
 *          data[6] = Tx 错误计数
 *          data[7] = Rx 错误计数
 * @note 以下错误中的大多数 STM32 处理器并不支持
 */

/**
 * @brief CAN ID 中的错误标志（32 位传输）
 */
typedef enum
{
    ERID_Tx_Timeout = 0x0001, /**< 发送超时 */
    ERID_Arbitration_lost = 0x0002, /**< 仲裁丢失 */
    // ---------- 冗余标志（信息已编码在数据字节中，仅为兼容保留） ------------
    ERID_Controller_problem = 0x0004, /**< 总线状态变化（冗余，详情在 data[1]） */
    ERID_Protocol_violation = 0x0008, /**< 协议违规（冗余，详情在 data[2+3]） */
    ERID_Transceiver_error = 0x0010, /**< 收发器状态（冗余，详情在 data[4]） */
    // -------------------------------
    ERID_No_ACK_received = 0x0020, /**< 发送时未收到 ACK */
    ERID_Bus_is_off = 0x0040, /**< 总线关闭 */
    ERID_Bus_error = 0x0080, /**< 总线错误 */
    ERID_Controller_restarted = 0x0100, /**< 控制器已重启 */
    ERID_CRC_Error = 0x0200, /**< CRC 错误（ElmueSoft 新增） */
} eErrFlagsCanID;

/**
 * @brief 总线状态（数据字节 1 的标志，8 位传输）
 */
typedef enum
{
    ER1_Rx_Buffer_Overflow = 0x01, /**< RX 缓冲溢出（仅传统协议，新协议走 eErrorAppFlags） */
    ER1_Tx_Buffer_Overflow = 0x02, /**< TX 缓冲溢出（仅传统协议，新协议走 eErrorAppFlags） */
    ER1_Rx_Errors_at_warning_level = 0x04, /**< RX 错误数 > 96，达告警级别 */
    ER1_Tx_Errors_at_warning_level = 0x08, /**< TX 错误数 > 96，达告警级别 */
    ER1_Rx_Passive_status_reached = 0x10, /**< RX 错误数 > 128，达错误被动状态 */
    ER1_Tx_Passive_status_reached = 0x20, /**< TX 错误数 > 128，达错误被动状态 */
    ER1_Bus_is_back_active = 0x40, /**< 恢复错误主动状态（非错误） */
} eErrFlagsByte1;

/**
 * @brief 协议违规（数据字节 2 的标志，8 位传输）
 */
typedef enum eErrFlagsByte2
{
    ER2_Single_bit_error = 0x01, /**< 单比特错误 */
    ER2_Frame_format_error = 0x02, /**< 帧格式错误 */
    ER2_Bit_stuffing_error = 0x04, /**< 位填充错误 */
    ER2_Unable_to_send_dominant_bit = 0x08, /**< 无法发送显性位 */
    ER2_Unable_to_send_recessive_bit = 0x10, /**< 无法发送隐性位 */
    ER2_Bus_overload = 0x20, /**< 总线过载 */
    ER2_Active_error_announcement = 0x40, /**< 主动错误帧宣告 */
    ER2_Transmission_error = 0x80, /**< 传输过程中发生错误 */
} eErrFlagsByte2;

/**
 * @brief 协议违规的错误位置（数据字节 3，8 位传输）
 * @note 未使用：处理器不提供此类细节，且错误发生在哪个位并无意义
 */
typedef enum
{
    ER3_at_ID_bits_28__21 = 0x02, /**< ID 位 28-21（标准帧：10-3） */
    ER3_at_SOF = 0x03, /**< 帧起始 */
    ER3_at_RTR_substitute = 0x04, /**< 替代 RTR（标准帧：RTR） */
    ER3_at_IDE_bit = 0x05, /**< 标识符扩展位 */
    ER3_at_ID_bits_20__18 = 0x06, /**< ID 位 20-18（标准帧：2-0） */
    ER3_at_ID_bits_17__13 = 0x07, /**< ID 位 17-13 */
    ER3_at_CRC_Sequence = 0x08, /**< CRC 序列 */
    ER3_at_Reserved_bit_0 = 0x09, /**< 保留位 0 */
    ER3_in_data_section = 0x0A, /**< 数据段 */
    ER3_at_DLC_bit = 0x0B, /**< 数据长度码位 */
    ER3_at_RTR_bit = 0x0C, /**< RTR 位 */
    ER3_at_Reserved_bit_1 = 0x0D, /**< 保留位 1 */
    ER3_at_ID_bits_4__0 = 0x0E, /**< ID 位 4-0 */
    ER3_at_ID_bits_12__5 = 0x0F, /**< ID 位 12-5 */
    ER3_Intermission = 0x12, /**< 帧间空间 */
    ER3_at_CRC_delimiter = 0x18, /**< CRC 界定符 */
    ER3_at_ACK_slot = 0x19, /**< ACK 槽 */
    ER3_at_EOF = 0x1A, /**< 帧结束 */
    ER3_at_ACK_delimiter = 0x1B, /**< ACK 界定符 */
} eErrFlagsByte3;

/**
 * @brief CAN 高线收发器错误（数据字节 4 高 4 位，4 位传输）
 * @note 未使用：处理器不提供此类细节
 */
typedef enum
{
    ER4_CAN_H_No_wire = 0x04, /**< CAN_H 无接线 */
    ER4_CAN_H_Shortcut_to_Bat = 0x05, /**< CAN_H 短路到电池 */
    ER4_CAN_H_Shortcut_to_VCC = 0x06, /**< CAN_H 短路到 VCC */
    ER4_CAN_H_Shortcut_to_GND = 0x07, /**< CAN_H 短路到 GND */
    // --------------------------------
    ER4_MASK_H = 0x0F, /**< 高 4 位掩码 */
} eErrFlagsByte4_Hi;

/**
 * @brief CAN 低线收发器错误（数据字节 4 低 4 位，4 位传输）
 * @note 未使用：处理器不提供此类细节
 */
typedef enum
{
    ER4_CAN_L_No_wire = 0x40, /**< CAN_L 无接线 */
    ER4_CAN_L_Shortcut_to_Bat = 0x50, /**< CAN_L 短路到电池 */
    ER4_CAN_L_Shortcut_to_VCC = 0x60, /**< CAN_L 短路到 VCC */
    ER4_CAN_L_Shortcut_to_GND = 0x70, /**< CAN_L 短路到 GND */
    ER4_CAN_L_Shortcut_CAN__H = 0x80, /**< CAN_L 与 CAN_H 短路 */
    // --------------------------------
    ER4_MASK_L = 0xF0, /**< 低 4 位掩码 */
} eErrFlagsByte4_Lo;

// 固件检测到的应用级标志（如缓冲溢出）在字节 5 传输，见 settings.h --> eErrorAppFlags

// ###############################################################################
//           传统 GS 传输协议（兼容 Geschwister Schneider）
// ###############################################################################

/**
 * @brief CAN ID 高 3 位的标志位
 */
typedef enum
{
    CAN_ID_Error = 0x20000000, /**< 该帧是错误帧，不包含 CAN 总线数据 */
    CAN_ID_RTR = 0x40000000, /**< 该帧是远程传输请求（远程帧） */
    CAN_ID_29Bit = 0x80000000, /**< 该帧具有 29 位扩展 CAN ID */
    CAN_MASK_11 = 0x000007FF, /**< 标准 11 位 ID 掩码 */
    CAN_MASK_29 = 0x1FFFFFFF, /**< 扩展 29 位 ID 掩码 */
} eCanIdFlags;

/**
 * @brief 帧标志（8 位）
 */
typedef enum
{
    FRM_Overflow = 0x01, /**< 未使用 */
    FRM_FDF = 0x02, /**< FDF：CAN FD 帧 */
    FRM_BRS = 0x04, /**< BRS：数据以更高波特率传输 */
    FRM_ESI = 0x08, /**< ESI：发送方上报错误 */
} eFrameFlags;

/**
 * @brief 回显 ID（32 位）
 * @details 仅 ECHO_RxData 表示真正的 Rx 报文；其他值由传统协议在接收时
 *          "回显"给主机（设计有缺陷，见下方说明）
 */
typedef enum
{
    ECHO_RxData = 0xFFFFFFFF, /**< 该帧是从总线接收的 Rx 报文 */
} eEchoID;

// ---------------------------

/**
 * @brief 传统协议经典帧数据包（标准 CAN）
 */
typedef struct
{
    uint8_t data[8]; /**< 最多 8 字节数据 */
    uint32_t timestamp_us; /**< 1 µs 精度时间戳（需溢出检测，一小时后溢出） */
} __packed kPacketClassic;

/**
 * @brief 传统协议 CAN FD 数据包
 * @note 设计缺陷：时间戳放在 64 字节数据之后，收到 8 字节 FD 帧也要
 *       经 USB 传 64 字节
 */
typedef struct
{
    uint8_t data[64]; /**< 最多 64 字节数据（CAN FD） */
    uint32_t timestamp_us; /**< 1 µs 精度时间戳（需溢出检测，一小时后溢出） */
} __packed kPacketFD;

// ---------------------------

/**
 * @brief 传统协议经 USB 与主机交换的报文（Rx / Tx，大小 = 80 字节）
 */
typedef struct
{
    uint32_t echo_id; /**< eEchoID 回显 ID */
    uint32_t can_id; /**< CAN ID + eCanIdFlags，或错误标志 */
    uint8_t can_dlc; /**< 数据长度码 0...15 */
    uint8_t channel; /**< 未使用，恒为零 */
    uint8_t flags; /**< eFrameFlags 帧标志 */
    uint8_t reserved; /**< 未使用 */
    union /**< 大小 = 68 字节 */
    {
        kPacketClassic pack_classic; /**< 经典帧数据包 */
        kPacketFD pack_FD; /**< CAN FD 数据包 */
        uint8_t raw_data[sizeof(kPacketFD)]; /**< 原始字节访问 */
    };
} __packed __aligned(4) kHostFrameLegacy;

// ###############################################################################
//     新 ElmueSoft CANable 2.5 协议（针对最大 USB 吞吐量优化）
// ###############################################################################

/*
 * 传统协议在设计上存在多处降低 USB 吞吐量的缺陷，新协议已逐一修复：
 *  1) FD 模式收到 8 字节数据也固定传 80 字节结构、64 字节数据
 *  2) kHostFrameLegacy 每帧多传 6 个无用字节
 *  3) Tx 帧总是被完整回显，且无法关闭
 *  4) 用单条全速 USB 连接承载多通道的想法本身不合理
 *  5) 总线错误以数百次/秒的洪泛方式重复发送
 *  6) 传统结构无法携带 CAN 报文/错误帧以外的数据
 *  7) 传统固件存在致命缺陷，甚至导致崩溃
 *
 * 出于向后兼容，传统 GS 协议仍完整保留；设置 ELM_DevFlagProtocolElmue
 * 即启用新协议（支持字符串消息、总线负载计算与大量缺陷修复）。
 * 详见 https://netcult.ch/elmue/CANable Firmware Update
 */

/**
 * @brief 板与处理器信息（ELM_ReqGetBoardInfo 应答）
 * @details McuDeviceID 来自 HAL_GetDEVID()（各处理器家族唯一，STM32G4xx 为 0x468 系列）
 */
typedef struct
{
    uint16_t McuDeviceID; /**< 处理器 ID，例如 0x468 */
    char McuName[25]; /**< 处理器名称，例如 "STM32G431xx"（来自 makefile） */
    char BoardName[25]; /**< 目标板名称，例如 "MksMakerbase"（来自 makefile） */
} __packed __aligned(1) kBoardInfo;

// -----------------------------------------

/**
 * @brief 过滤器操作（8 位 = 256 种可能）
 */
typedef enum
{
    FIL_ClearAll = 0, /**< 清除所有过滤器 */
    FIL_AcceptMask11bit, /**< 添加 11 位接受掩码过滤器 */
    FIL_AcceptMask29bit, /**< 添加 29 位接受掩码过滤器 */
    //  FIL_xxxx          // 未来可扩展
} eFilterOperation;

/**
 * @brief 过滤器设置（ELM_ReqSetFilter）
 */
typedef struct
{
    uint8_t Operation; /**< eFilterOperation 过滤器操作 */
    uint32_t Filter; /**< 过滤器（如 0x7E0）；FIL_ClearAll 时忽略 */
    uint32_t Mask; /**< 掩码（如 0x7FF）；FIL_ClearAll 时忽略 */
    uint32_t Reserved1; /**< 保留 */
    uint32_t Reserved2; /**< 保留 */
} __packed __aligned(1) kFilter;

// -----------------------------------------

/**
 * @brief 引脚操作（16 位 = 65536 种可能）
 */
typedef enum
{
    PINOP_Reset = 0, /**< 将引脚设为低电平 */
    PINOP_Set, /**< 将引脚设为高电平 */
    PINOP_Tristate, /**< 将引脚设为三态模式 */
    PINOP_PullDown, /**< 使能下拉电阻 */
    PINOP_PullUp, /**< 使能上拉电阻 */
    PINOP_Disable, /**< 禁用引脚（用于 Option Bytes 中的 BOOT0） */
    PINOP_Enable, /**< 使能引脚 */
    //  PINOP_xxxx          // 未来可扩展
} ePinOperation;

/**
 * @brief 可控制引脚 ID（16 位，需经 SETUP.wValue 传输）
 * @note 禁止允许用户任意设置处理器引脚（特殊功能引脚易致崩溃）。
 *       具体引脚需在 settings.h 的 #if defined(BoardName) 中定义，
 *       这里只定义 ID。目前仅实现 BOOT0
 */
typedef enum
{
    PINID_BOOT0 = 1, /**< BOOT0 引脚，可在 Option Bytes 中禁用 */
    //  PINID_xxxx          // 未来可扩展
} ePinID;

/**
 * @brief 引脚操作载荷（ELM_ReqSetPinStatus）
 */
typedef struct
{
    uint16_t Operation; /**< ePinOperation 引脚操作 */
    uint16_t PinID; /**< ePinID 引脚 ID */
    uint32_t Reserved1; /**< 保留 */
    uint32_t Reserved2; /**< 保留 */
} __packed __aligned(1) kPinStatus;

// -------------------

/**
 * @brief 引脚状态位标志（ELM_ReqGetPinStatus 应答，16 位）
 * @details USB 协议不允许同一 SETUP 请求既收 OUT 又回 IN 数据，
 *          故请求的引脚 ID 必须放在 SETUP.wValue，应答经 2 个数据字节返回
 */
typedef enum
{
    PINST_High = 0x0001, /**< 引脚当前为高电平；未设置则为低电平 */
    PINST_Enabled = 0x0002, /**< 引脚当前为使能；未设置则为禁用 */
    //  PINST_xxxx               // 未来可扩展
} ePinStatus;

// -----------------------------------------------------------------------------------------------

/**
 * @brief 消息类型（新协议消息头第二个字节，8 位）
 */
typedef enum
{
    // 从主机接收
    MSG_TxFrame = 10, /**< 包含要发送到 CAN 总线的帧（kTxFrameElmue） */
    // 发送到主机
    MSG_TxEcho, /**< 包含 Tx 帧的回显标记（kTxEchoElmue，可禁用） */
    MSG_RxFrame, /**< 包含从 CAN 总线接收的帧（kRxFrameElmue） */
    MSG_Error, /**< 包含多个错误标志（kErrorElmue，格式同传统协议） */
    MSG_String, /**< 包含要显示给用户的 ASCII 字符串（kStringElmue） */
    MSG_Busload, /**< 包含一个字节，即总线负载百分比（kBusloadElmue） */
    //  MSG_xxxx          // 未来可扩展
} eMessageType;

/**
 * @brief 所有新协议消息的公共头部
 * @details 便于未来轻松添加新特性
 */
typedef struct
{
    uint8_t size; /**< 此消息的总长度（结构体 + 附加数据字节） */
    uint8_t msg_type; /**< eMessageType 消息类型 */
} __packed __aligned(1) kHeader;

/**
 * @brief 发送到 CAN 总线的帧（在端点 02 OUT 上从主机接收）
 * @details 不需要 DLC 字节：数据字节数 = header.size - sizeof(kTxFrameElmue)
 * @see buf_process_can_bus()
 */
typedef struct
{
    kHeader header; /**< MSG_TxFrame 消息头 */
    uint8_t flags; /**< eFrameFlags 帧标志 */
    uint32_t can_id; /**< CAN ID + eCanIdFlags 标志 */
    uint8_t marker; /**< 单字节标记，报文收到 ACK 时经 MSG_TxEcho 返回给主机 */
    uint8_t data_start[0]; /**< 数据起始位置（零长数组） */
} __packed __aligned(1) kTxFrameElmue;

/**
 * @brief 从 CAN 总线接收的帧（在端点 81 IN 上传输给主机）
 * @details 不需要 DLC 字节：数据字节数 = header.size - sizeof(kRxFrameElmue)；
 *          未启用时间戳时再减 4 字节
 * @see buf_store_rx_packet()
 */
typedef struct
{
    kHeader header; /**< MSG_RxFrame 消息头 */
    uint8_t flags; /**< eFrameFlags 帧标志 */
    uint32_t can_id; /**< CAN ID + eCanIdFlags 标志 */
    uint8_t data_no_stamp[0]; /**< 时间戳关闭时的数据起始位置（最快传输） */
    uint32_t timestamp; /**< 1 µs 时间戳，仅启用 GS_DevFlagTimestamp 时发送，需溢出检测 */
    uint8_t data_use_stamp[0]; /**< 传输时间戳时的数据起始位置 */
} __packed __aligned(1) kRxFrameElmue;

/**
 * @brief Tx 回显标记（kTxFrameElmue 中 marker 的回传）
 * @see buf_store_tx_echo()
 */
typedef struct
{
    kHeader header; /**< MSG_TxEcho 消息头 */
    uint8_t marker; /**< 与发送时相同的标记，报文在总线上收到 ACK 时返回 */
    uint32_t timestamp; /**< 1 µs 时间戳，仅启用 GS_DevFlagTimestamp 时发送，需溢出检测 */
} __packed __aligned(1) kTxEchoElmue;

/**
 * @brief 错误报文（多个错误标志）
 * @see buf_store_error()
 */
typedef struct
{
    kHeader header; /**< MSG_Error 消息头 */
    uint32_t err_id; /**< eErrFlagsCanID 错误标志 */
    uint8_t err_data[8]; /**< 若干错误标志与错误计数 */
    uint32_t timestamp; /**< 1 µs 时间戳，仅启用 GS_DevFlagTimestamp 时发送，需溢出检测 */
} __packed __aligned(1) kErrorElmue;

/**
 * @brief 调试字符串消息
 * @see control_send_debug_mesg()
 */
typedef struct
{
    kHeader header; /**< MSG_String 消息头 */
    char ascii_msg[0]; /**< 字符串数据（零长数组） */
} __packed __aligned(1) kStringElmue;

/**
 * @brief 总线负载消息
 * @see control_report_busload()
 */
typedef struct
{
    kHeader header; /**< MSG_Busload 消息头 */
    uint8_t bus_load; /**< 当前总线负载百分比 */
} __packed __aligned(1) kBusloadElmue;
