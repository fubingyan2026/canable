/**
 * @file control.c
 * @brief Slcan 命令解析与控制：SLCAN ASCII 命令的分发、执行与错误上报
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Nakanishi Kiyomaro / Normadotcom
    https://netcult.ch/elmue/CANable Firmware Update
*/

#include "settings.h"
#include "buffer.h"
#include "can.h"
#include "utils.h"
#include "error.h"
#include "led.h"
#include "dfu.h"
#include "control.h"

extern eUserFlags USER_Flags;

/** @brief 打开适配器时使用的 FDCAN 模式（普通/静默/回环），可由命令修改 */
uint32_t can_mode = FDCAN_MODE_NORMAL; // normal, silent, loopback modes

/**
 * @brief 解析并执行一条 SLCAN 命令
 * @param[in] buf 命令字符串（不含结尾 '\r'）
 * @param[in] len 命令长度
 * @return eFeedback 执行结果
 */
eFeedback control_parse_str (char buf[], int len);

/**
 * @brief 解析过滤器设置命令（"F7E0,7FF;..."）
 * @param[in] buf 命令字符串
 * @param[in] len 命令长度
 * @return eFeedback 执行结果
 */
eFeedback control_set_filter(char buf[], uint8_t len);

// ==================================================================================================================

/**
 * @brief 初始化用户标志（Slcan 默认值）
 */
void control_init()
{
    // all the other flags must be enabled by the user
    USER_Flags = USR_SlcanDefault;
}

/**
 * @brief 解析并执行一条 SLCAN 命令，按反馈设置回送结果
 * @param[in] buf 命令字符串
 * @param[in] len 命令长度
 * @details 反馈模式（USR_Feedback）开启时：成功回 "#\r"，失败回 "#<错误码>\r"，
 *          FBK_RetString 表示命令已自行写入响应字符串
 */
void control_parse_command(char buf[], int len)
{
    eFeedback e_Ret = control_parse_str(buf, len);
    if ((USER_Flags & USR_Feedback) == 0)
        return;

    switch (e_Ret)
    {
        case FBK_RetString:
            break; // response has already been written with buf_enqueue_cdc()
        case FBK_Success:
            buf_enqueue_cdc("#\r", 2); // return "#\r" for success
            break;
        default:
        {
            char s8_Error[3] = { '#', e_Ret, '\r' }; // return "#4\r" for error 4
            buf_enqueue_cdc(s8_Error, 3);
            break;
        }
    }
}

/**
 * @brief 解析一条来自 USB CDC 端口的 SLCAN 命令
 * @param[in] buf 命令字符串（结尾 '\r' 已被移除）
 * @param[in] len 命令长度
 * @return eFeedback 执行结果
 * @details 首字符决定命令类型：A/M/O/C/V/S/Y/s/y/F/f/L/* 为控制命令，
 *          其余按发送帧命令解析（t/T/r/R/d/D/b/B）
 */
eFeedback control_parse_str(char buf[], int len)
{
    // 总线关闭时短闪蓝色 LED，提示设备未在运行
    if (!can_is_opened())
        led_flash_RX(); // flash 15 ms

    // 空命令 "\r" 直接回 OK
    if (len == 0)
        return FBK_Success;

    // 在命令末尾补零，便于字符串操作
    buf[len] = 0;

    char tempbuf[200];

    eFeedback e_Ret = FBK_InvalidParameter;
    switch (buf[0])
    {
        // ---------- 设置自动重传（旧版命令） ----------
        case 'A':
            if (len != 2)
                return FBK_InvalidParameter;

            if (can_is_opened())
                return FBK_AdapterMustBeClosed;

            switch (buf[1])
            {
                case '0': USER_Flags &= ~USR_Retransmit; break; // "A0"（旧命令）启用单次发送
                case '1': USER_Flags |=  USR_Retransmit; break; // "A1"（旧命令）重试 128 次发送
                default:  return FBK_InvalidParameter;
            }
            return FBK_Success;

        // ---------- 设置模式：例如 "MEFS" 启用错误报告、反馈与 ESI 报告 ----------
        case 'M':
            if (len < 2)
                return FBK_InvalidParameter;

            // 逐字符解析模式开关
            for (int i=1; i<len; i++)
            {
                // NOTE: Slcan 未实现时间戳传输（一条时间戳需 16 字节，
                // 应在主机端生成，以免拖慢 USB 流量）
                switch (buf[i])
                {
                    case 'A':                                        // "MA"  启用自动重传（同旧命令 "A1"）
                        if (can_is_opened()) return FBK_AdapterMustBeClosed;
                        USER_Flags |=  USR_Retransmit;
                        break;
                    case 'a':                                        // "Ma"  禁用自动重传
                        if (can_is_opened()) return FBK_AdapterMustBeClosed;
                        USER_Flags &= ~USR_Retransmit;
                        break;
                    case 'D': USER_Flags |=  USR_DebugReport; break; // "MD"  启用字符串调试消息
                    case 'd': USER_Flags &= ~USR_DebugReport; break; // "Md"
                    case 'E': USER_Flags |=  USR_ErrorReport; break; // "ME"  启用 CAN 总线错误报告
                    case 'e': USER_Flags &= ~USR_ErrorReport; break; // "Me"
                    case 'F': USER_Flags |=  USR_Feedback;    break; // "MF"  启用命令执行反馈模式
                    case 'f': USER_Flags &= ~USR_Feedback;    break; // "Mf"
                    case 'M': USER_Flags |=  USR_ReportTX;    break; // "MT"  启用带 Marker 的 Tx 回显报告
                    case 'm': USER_Flags &= ~USR_ReportTX;    break; // "Mt"
                    case 'S': USER_Flags |=  USR_ReportESI;   break; // "MS"  启用 ESI 报告
                    case 's': USER_Flags &= ~USR_ReportESI;   break; // "Ms"
                    // -----------------------------------------------------
                    case 'I': led_blink_identify(true);       break; // "MI"  闪烁 LED 识别设备
                    case 'i': led_blink_identify(false);      break; // "Mi"  停止闪烁
                    case '0':                                        // "M0"  普通模式（旧命令）
                    case '1':                                        // "M1"  静默/总线监控模式（旧命令）
                        if (can_is_opened())
                            return FBK_AdapterMustBeClosed;
                        can_mode = (buf[i] == '1') ? FDCAN_MODE_BUS_MONITORING : FDCAN_MODE_NORMAL;
                        break;
                    case 'R':                                        // "MR"  启用 120Ω 终端电阻
                    case 'r':                                        // "Mr"  禁用 120Ω 终端电阻
                        if (!can_set_termination(buf[i] == 'R'))
                            return FBK_UnsupportedFeature;
                        break;
                    default:
                        return FBK_InvalidParameter;
                }
            }
            return FBK_Success;

        // ----------------------------

        // ---------- 打开适配器 ----------
        case 'O':
        {
            if (len > 2)
                return FBK_InvalidParameter;

            // 只有发了 2 个字符才修改 can_mode（避免与 "M" 命令相互干扰）
            if (len == 2)
            {
                switch (buf[1])
                {
                    case 'N': can_mode = FDCAN_MODE_NORMAL;            break; // "ON"
                    case 'S': can_mode = FDCAN_MODE_BUS_MONITORING;    break; // "OS"
                    case 'I': can_mode = FDCAN_MODE_INTERNAL_LOOPBACK; break; // "OI"
                    case 'E': can_mode = FDCAN_MODE_EXTERNAL_LOOPBACK; break; // "OE"
                    default:  return FBK_InvalidParameter;
                }
            }
            return can_open(can_mode); // returns error if already open
        }

        // ---------- 关闭适配器并复位变量 ----------
        // 注意：此命令即使反馈模式开启也不发送反馈，这是故意的——
        // 应用程序可在 Open 前执行它以确保所有变量已复位，而此时
        // 应用并不知道上次使用是否还残留反馈设置
        case 'C':
            if (len == 1)
            {
                can_close(); // 已关闭时无错误

                // 复位变量为默认值
                can_mode   = FDCAN_MODE_NORMAL;
                USER_Flags = USR_SlcanDefault;

                // 不调用 buf_enqueue_cdc() --> 绝不发送响应。
                // 这是唯一与旧命令行为一致的命令
                return FBK_RetString;
            }
            return e_Ret;

        // ----------------------------

        // ---------- 获取版本、处理器、时钟等信息 ----------
        case 'V':
            if (len == 1)
            {
                // 主机需要这些限制来计算波特率（命令 's' 和 'y'）
                bitlimits* lim = utils_get_bit_limits();

                // HAL_GetDEVID() 返回各处理器家族唯一标识（DBG_IDCODE）。
                // STM32G0xx 用 0x460/0x465/0x476/0x477，STM32G4xx 用 0x468/0x469/0x479。
                // 字符串响应以 '+' 开头，其余命令响应以 '#' 开头
                sprintf(tempbuf, "+Board: "      TARGET_BOARD            // MksMakerbase           (from MakeFile)
                                 "\tMCU: %s"                             // STM32G431              (from MakeFile)
                                 "\tDevID: %lu"                          // 0x468                  (from processor)
                                 "\tFirmware: %u"                        // 0x250814               (from settings.h)
                                 "\tSlcan: "     STR(SLCAN_VERSION)      // 100                    (from settings.h)
                                 "\tClock: %lu"                          // 160                    (from system variable)
                                 "\tLimits: %lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu\r",
                                 utils_get_MCU_name(),
                                 HAL_GetDEVID(),
                                 FIRMWARE_VERSION_BCD,
                                 system_get_can_clock() / 1000000,
                                 lim->nom_brp_max, lim->nom_seg1_max, lim->nom_seg2_max, lim->nom_sjw_max,
                                 lim->fd_brp_max,  lim->fd_seg1_max,  lim->fd_seg2_max,  lim->fd_sjw_max);

                buf_enqueue_cdc(tempbuf, strlen(tempbuf));
                return FBK_RetString;
            }
            return e_Ret;

        // ----------------------------

        // ---------- 按预置表设置波特率（采样点固定：标称 87.5%、数据 75%） ----------
        case 'S':
            if (len == 2) e_Ret = can_set_baudrate((can_nom_bitrate)(buf[1] - '0')); // "S1"
            return e_Ret;
        case 'Y':
            if (len == 2) e_Ret = can_set_data_baudrate((can_data_bitrate)(buf[1] - '0')); // "Y2"
            return e_Ret;

        // ---------- 任意采样点设置位时序 ----------
        case 's':
        case 'y':
        {
            int pos = 1;
            uint32_t BRP, Seg1, Seg2, Sjw;
            // 解析 "BRP,Seg1,Seg2,Sjw" 四个十进制数
            if (!utils_parse_next_decimal(buf, &pos, ',', &BRP)  ||
                !utils_parse_next_decimal(buf, &pos, ',', &Seg1) ||
                !utils_parse_next_decimal(buf, &pos, ',', &Seg2) ||
                !utils_parse_next_decimal(buf, &pos,  0,  &Sjw))
                    return FBK_InvalidParameter;

            if (buf[0] == 's') return can_set_nom_bit_timing (BRP, Seg1, Seg2, Sjw); // "s40,16,2,2"
            else               return can_set_data_bit_timing(BRP, Seg1, Seg2, Sjw);
        }

        // ----------------------------

        // ---------- 设置 CAN 过滤器 ----------
        case 'F':
            return control_set_filter(buf, len); // "F7E0,7FF"
        // 清除所有 CAN 过滤器
        case 'f':
            if (len == 1) return can_clear_filters(); // "f"
            return e_Ret;

        // ----------------------------

        // ---------- 使能总线负载上报（精度约 ±10%） ----------
        // 固件按用户定义间隔上报当前总线负载。
        // 命令 "L7\r" --> 每 700 ms 上报一次
        case 'L':
        {
            uint32_t interval;
            int pos = 1;
            if (!utils_parse_next_decimal(buf, &pos, 0, &interval)) // "L0", "L7", "L30"
                return FBK_InvalidParameter;

            return can_enable_busload(interval); // interval in 100ms steps
        }

        // ----------------------------

        // ---------- 特殊 ASCII 命令 ----------
        // 这些命令故意超过 2 个字符，避免被误执行
        case '*':
        {
            // 使能 BOOT0 引脚后把处理器切到 DFU 模式。
            // 引导加载程序延迟 300 ms 启动，因此主机仍能收到响应
            if (strcmp(buf, "*DFU") == 0)
                return dfu_switch_to_bootloader(); // closes adapter

            // 设置寄存器 OPTR，位 nSWBOOT0 = 0 --> 禁用 BOOT0 引脚 --> 总是从主 flash 启动
            // 参考 https://netcult.ch/elmue/CANable Firmware Update
            // "使能"无需在此实现：进入 DFU 时 dfu_switch_to_bootloader() 会自动使能
            if (strcmp(buf, "*Boot0:Off") == 0)
                return system_set_option_bytes(OPT_BOOT0_Disable);

            // 查询 BOOT0 引脚当前是否使能
            if (strcmp(buf, "*Boot0:?") == 0)
            {
                // 字符串响应以 '+' 开头，其余命令响应以 '#' 开头
                char* resp = system_is_option_enabled(OPT_BOOT0_Enable) ? "+1\r" : "+0\r";
                buf_enqueue_cdc(resp, 3);
                return FBK_RetString;
            }
            return FBK_InvalidParameter;
        }
        // 调试命令
        case '?':
        {
            return FBK_InvalidCommand;
            /*
            // This code was written by Nakanishi Kiyomaro.

            char* dbgstr = (char*)buf_get_cdc_dest();
            snprintf(dbgstr, SLCAN_MTU - 1, ">%02X-%02X-%01X-%04X%04X-%04X\r",
                                        (uint8_t)(can_get_cycle_ave_time_ns() >= 255000 ? 255 : can_get_cycle_ave_time_ns() / 1000),
                                        (uint8_t)(can_get_cycle_max_time_ns() >= 255000 ? 255 : can_get_cycle_max_time_ns() / 1000),
                                        (uint8_t)(HAL_FDCAN_GetState(can_get_handle())),
                                        (uint16_t)(HAL_FDCAN_GetError(can_get_handle()) >> 16),
                                        (uint16_t)(HAL_FDCAN_GetError(can_get_handle()) & 0xFFFF),
                                        (uint16_t)(error_get_register()));
            buf_comit_cdc_dest(23);
            */

            /*
            uint8_t cycle_ave = (uint8_t)(can_get_cycle_ave_time_ns() >= 255000 ? 255 : can_get_cycle_ave_time_ns() / 1000);
            uint8_t cycle_max = (uint8_t)(can_get_cycle_max_time_ns() >= 255000 ? 255 : can_get_cycle_max_time_ns() / 1000);

            char dbgstr[7];
            dbgstr[0] = '>'; // debug message
            dbgstr[1] = cycle_ave >> 4;
            dbgstr[2] = cycle_ave & 0xF;
            for (uint8_t j = 1; j <= 2; j++)
            {
                if (dbgstr[j] < 0xA) dbgstr[j] += 0x30;
                else                 dbgstr[j] += 0x37;
            }
            dbgstr[3] = '-';
            dbgstr[4] = cycle_max >> 4;
            dbgstr[5] = cycle_max & 0xF;
            for (uint8_t j = 4; j <= 5; j++)
            {
                if (dbgstr[j] < 0xA) dbgstr[j] += 0x30;
                else                 dbgstr[j] += 0x37;
            }
            dbgstr[6] = '\r';
            can_clear_cycle_time();

            buf_enqueue_cdc(dbgstr, 7);
            return FBK_RetString;
            */
        }
    }

    // ================ 发送帧命令 =================
    // "t600801020304050607083A\r"

    // 预置默认帧头，下面按命令逐项覆盖
    FDCAN_TxHeaderTypeDef* tx_header = buf_get_can_dest_header();
    uint8_t*               tx_data   = buf_get_can_dest_data();

    if (tx_header == NULL || tx_data == NULL)
        return FBK_TxBufferFull;

    tx_header->TxFrameType         = FDCAN_DATA_FRAME;
    tx_header->FDFormat            = FDCAN_CLASSIC_CAN;
    tx_header->IdType              = FDCAN_STANDARD_ID;
    tx_header->BitRateSwitch       = FDCAN_BRS_OFF;
    tx_header->ErrorStateIndicator = can_is_passive() ? FDCAN_ESI_PASSIVE : FDCAN_ESI_ACTIVE;
    tx_header->TxEventFifoControl  = FDCAN_STORE_TX_EVENTS; // always! Tx Event flashes the green LED

    switch (buf[0])
    {
        // 发送远程帧
        case 'r':
            tx_header->TxFrameType   = FDCAN_REMOTE_FRAME;
            break;
        case 'R':
            tx_header->IdType        = FDCAN_EXTENDED_ID;
            tx_header->TxFrameType   = FDCAN_REMOTE_FRAME;
            break;

        // 发送数据帧（经典 CAN）
        case 'T':
            tx_header->IdType        = FDCAN_EXTENDED_ID;
            break;
        case 't':
            break;

        // CAN FD 发送 - 无 BRS
        case 'd':
            tx_header->FDFormat      = FDCAN_FD_CAN;
            break;
        case 'D':
            tx_header->FDFormat      = FDCAN_FD_CAN;
            tx_header->IdType        = FDCAN_EXTENDED_ID;
            break;

        // CAN FD 发送 - 带 BRS
        case 'b':
            tx_header->FDFormat      = FDCAN_FD_CAN;
            tx_header->BitRateSwitch = FDCAN_BRS_ON;
            break;
        case 'B':
            tx_header->FDFormat      = FDCAN_FD_CAN;
            tx_header->BitRateSwitch = FDCAN_BRS_ON;
            tx_header->IdType        = FDCAN_EXTENDED_ID;
            break;

        // 非法命令
        default:
            return FBK_InvalidCommand;
    }

    // 发送 FD 帧要求已设置数据波特率；数据波特率可与标称相同，
    // 以无 BRS 方式发送最多 64 字节
    if (tx_header->FDFormat == FDCAN_FD_CAN && !can_using_FD())
        return FBK_BaudrateNotSet;

    // 从第 2 字节开始解析（跳过命令字节）
    int parse_loc = 1;

    // 标准 3 位 / 扩展 8 位 ID
    uint8_t id_len = (tx_header->IdType == FDCAN_EXTENDED_ID) ? 8 : 3;

    // 解析 CAN ID
    if (!utils_parse_hex_value(buf, &parse_loc, id_len, &tx_header->Identifier))
        return FBK_InvalidParameter;

    // 校验 CAN ID 范围
    if (tx_header->IdType == FDCAN_STANDARD_ID && tx_header->Identifier > 0x7FF)
        return FBK_InvalidParameter;

    if (tx_header->IdType == FDCAN_EXTENDED_ID && tx_header->Identifier > 0x1FFFFFFF)
        return FBK_InvalidParameter;

    // 解析 DLC
    uint32_t dlc_code;
    if (!utils_parse_hex_value(buf, &parse_loc, 1, &dlc_code))
        return FBK_InvalidParameter;

    // 经典帧 DLC 允许 0...8
    if (tx_header->FDFormat == FDCAN_CLASSIC_CAN && dlc_code > 8)
        return FBK_InvalidParameter;

    // 远程帧不含数据字节
    if (tx_header->TxFrameType == FDCAN_REMOTE_FRAME && dlc_code > 0)
        return FBK_InvalidParameter;

    // 左移 16 位以直接存入 FIFO 寄存器（ST 未提供处理器无关的移位宏）
    tx_header->DataLength = dlc_code << 16;

    int8_t byte_count = utils_dlc_to_byte_count(dlc_code);
    // 解析数据字节
    for (uint8_t i = 0; i < byte_count && parse_loc < len; i++)
    {
        uint32_t byte_val;
        if (!utils_parse_hex_value(buf, &parse_loc, 2, &byte_val))
            return FBK_InvalidParameter;

        tx_data[i] = byte_val;
    }

    // 主机须为每个发送报文生成唯一的一字节 marker（可用递增计数器）。
    // Tx FIFO 存 3 个、缓冲队列存 64 个，3 + 64 种取值足以让每个等待
    // ACK 的报文拥有唯一 marker
    if (USER_Flags & USR_ReportTX)
    {
        if (!utils_parse_hex_value(buf, &parse_loc, 2, &tx_header->MessageMarker))
            return FBK_InvalidParameter;
    }

    // 把报文写入发送队列
    return buf_comit_can_dest();
}

// ================================================================================================================

/**
 * @brief 解析过滤器设置命令
 * @param[in] buf 命令字符串
 * @param[in] len 命令长度
 * @return eFeedback 执行结果
 * @details 格式：例如 "F7E0,7FF;1F005000,1FFFFFFF" -->
 *          11 位过滤器 0x7E0/掩码 0x7FF 与 29 位过滤器 0x1F005000。
 *          位数（3 或 8）决定是标准还是扩展过滤器，多组以 ';' 分隔
 */
eFeedback control_set_filter(char buf[], uint8_t len)
{
    int  pos = 1;
    bool abort = false;
    while (!abort)
    {
        uint32_t filter, mask;
        int digitsF, digitsM;
        if (!utils_parse_hex_delimiter(buf, &pos, ',', &digitsF, &filter))
        {
            if (buf[pos] == 0) break;  // string zero termination found after semicolon
            return FBK_InvalidParameter;
        }

        if (!utils_parse_hex_delimiter(buf, &pos, ';', &digitsM, &mask))
        {
            if (buf[pos] == 0) abort = true;  // string zero termination found after mask
            else return FBK_InvalidParameter; // invalid character
        }

        // 过滤器与掩码位数必须一致
        if (digitsF != digitsM)
            return FBK_InvalidParameter;

        bool extended;
             if (digitsF == 3) extended = false;
        else if (digitsF == 8) extended = true;
        else return FBK_InvalidParameter;

        eFeedback error = can_set_mask_filter(extended, filter, mask);
        if (error != FBK_Success)
            return error;
    }
    return FBK_Success;
}

/**
 * @brief 周期上报总线错误（主循环周期调用，约每毫秒 100 次）
 * @param[in] tick_now 当前 1 µs 时基
 * @details 错误状态变化时每 100 ms 上报一次；不变时每 3000 ms 报一次。
 *          上报格式 "E%02X%02X%02X%02X\r"：总线状态+协议错误、应用标志、Tx/Rx 错误计数
 */
void control_process(uint32_t tick_now)
{
    if (!error_is_report_due(tick_now))
        return;

    // 取自上次 error_clear() 后仍存在的错误
    kCanErrorState* state = error_get_state();

    // 总线状态与最近协议错误（FDCAN_PROTOCOL_ERROR_ACK）取值少，合并进一个字节
    char tempbuf[20];
    sprintf(tempbuf, "E%02X%02X%02X%02X\r", (uint8_t)(state->bus_status | state->last_proto_err),
                                            (uint8_t)state->app_flags,
                                            (uint8_t)state->tx_err_count,
                                            (uint8_t)state->rx_err_count);
    buf_enqueue_cdc(tempbuf, 10);
    error_clear();
}

/**
 * @brief 按用户定义间隔把总线负载百分比发给主机
 * @param[in] busload_percent 总线负载百分比
 */
void control_report_busload(uint8_t busload_percent)
{
    char buf[10];
    sprintf(buf, "L%u\r", busload_percent);
    buf_enqueue_cdc(buf, strlen(buf));
}

/**
 * @brief 发送调试消息
 * @param[in] message 调试消息，最多 80 字符，可含 '\n' 换行
 * @return true 已发送；false 调试上报未启用
 * @note 启用 USR_DebugReport 后，该消息会显示在 HUD ECU Hacker 的 Trace 窗格
 */
bool control_send_debug_mesg(const char* message)
{
    if ((USER_Flags & USR_DebugReport) == 0)
        return false;

    int len = strlen(message);
    if (len > 80)
    {
        message = "*** Dbg msg too long";
        len = 20;
    }

    char buf[85];
    sprintf(buf, ">%s\r", message);

    buf_enqueue_cdc(buf, len + 2);
    return true;
}

