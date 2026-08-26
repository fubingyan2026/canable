/**
 * @file control.c
 * @brief SETUP 厂商请求的处理：能力/版本/板信息查询、设备启停、过滤器与引脚控制
 * @note 传统 GS 协议与新的 ElmueSoft CANable 2.5 协议共用本模块
 */

/*
    The MIT License
    USB GS 类（Geschwister Schneider）的实现
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#include "control.h"
#include "can.h"
#include "dfu.h"
#include "error.h"
#include "led.h"
#include "settings.h"
#include "usb_ioreq.h"
#include "utils.h"

extern USB_BufHandleTypeDef USB_BufHandle;
extern eUserFlags USER_Flags;

/** @brief 经典帧能力描述（传统 GS 协议，GS_ReqGetCapabilities 应答） */
kCapabilityClassic GS_CapabilityClassic;
/** @brief CAN FD 能力描述（传统 GS 协议，GS_ReqGetCapabilitiesFD 应答） */
kCapabilityFD GS_CapabilityFD;
/** @brief 软/硬件版本号（BCD 格式，GS_ReqGetDeviceVersion 应答） */
kDeviceVersion GS_DeviceVersion = { 0 };

/** @brief 板与处理器信息（新 ElmueSoft 协议，ELM_ReqGetBoardInfo 应答） */
kBoardInfo ELM_BoardInfo = { 0 };
/** @brief 上一条 SETUP 命令的反馈错误（ELM_ReqGetLastError 应答） */
eFeedback ELM_LastError = FBK_Success;

/**
 * @brief 初始化设备信息
 * @details 设置默认用户标志、版本号、能力描述与板信息
 * @note 位时序范围取自处理器实际限制（utils_get_bit_limits()），
 *       而非旧固件里编造的值
 */
void control_init()
{
    // 先复位为 Candlelight 默认标志，其余标志由主机通过 GS_ReqSetDeviceMode 按需开启
    USER_Flags = USR_CandleDefault;

    // 版本号用 BCD 表示：0x250814 显示为 "25.08.14"，0x200 显示为 "2.00"
    GS_DeviceVersion.sw_version_bcd = FIRMWARE_VERSION_BCD; // 固件版本
    GS_DeviceVersion.hw_version_bcd = 0x200; // 硬件版本 = CANable 2.0

    // ------------------------------------------------

    // 声明设备支持的全部特性（经典帧与 FD 共用同一份特性标志）
    GS_CapabilityClassic.feature = GS_DevFlagListenOnly | // 只听
        GS_DevFlagLoopback | // 回环
        GS_DevFlagOneShot | // 单次发送
        GS_DevFlagTimestamp | // 时间戳
        GS_DevFlagIdentify | // LED 识别
        GS_DevFlagCAN_FD | // CAN FD
        GS_DevFlagBitTimingFD | // FD 数据位时序
        ELM_DevFlagProtocolElmue | // ElmueSoft 新协议
        ELM_DevFlagDisableTxEcho; // 可关闭 Tx 回显
    // 仅当电路板真的带终端电阻控制引脚时才声明该能力
    if (TERMINATOR_Pin > 0)
        GS_CapabilityClassic.feature |= GS_DevFlagTermination;

    // ------------------------------------------------

    bitlimits* limits = utils_get_bit_limits();

    // 经典帧位时序范围
    GS_CapabilityClassic.fclk_can = system_get_can_clock(); // 被 brp 分频的 CAN 时钟
    GS_CapabilityClassic.time.seg1_min = 1;
    GS_CapabilityClassic.time.seg1_max = limits->nom_seg1_max;
    GS_CapabilityClassic.time.seg2_min = 1;
    GS_CapabilityClassic.time.seg2_max = limits->nom_seg2_max;
    GS_CapabilityClassic.time.brp_min = 1;
    GS_CapabilityClassic.time.brp_max = limits->nom_brp_max;
    GS_CapabilityClassic.time.brp_inc = 1;
    GS_CapabilityClassic.time.sjw_max = limits->nom_sjw_max;

    // ------------------------------------------------

    // FD 能力 = 经典帧能力，但数据相位单独用 FD 限制
    GS_CapabilityFD.fclk_can = GS_CapabilityClassic.fclk_can;
    GS_CapabilityFD.feature = GS_CapabilityClassic.feature;
    GS_CapabilityFD.time_nom = GS_CapabilityClassic.time;

    GS_CapabilityFD.time_data.seg1_min = 1;
    GS_CapabilityFD.time_data.seg1_max = limits->fd_seg1_max;
    GS_CapabilityFD.time_data.seg2_min = 1;
    GS_CapabilityFD.time_data.seg2_max = limits->fd_seg2_max;
    GS_CapabilityFD.time_data.brp_min = 1;
    GS_CapabilityFD.time_data.brp_max = limits->fd_brp_max;
    GS_CapabilityFD.time_data.brp_inc = 1;
    GS_CapabilityFD.time_data.sjw_max = limits->fd_sjw_max;

    // -------------- ElmueSoft 扩展 ----------------

    // 板信息：处理器 ID + 名称 + 板名称（后两者来自 makefile 宏）
    ELM_BoardInfo.McuDeviceID = (uint16_t)HAL_GetDEVID();
    strcpy(ELM_BoardInfo.McuName, utils_get_MCU_name()); // "STM32G431"
    strcpy(ELM_BoardInfo.BoardName, TARGET_BOARD); // "MksMakerbase" / "OpenlightLabs"
}

/**
 * @brief 处理 SETUP 厂商请求的第一阶段（请求解析与分发）
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @return true 已处理；false 无法识别（置 ELM_LastError，上层会 stall 端点 0）
 * @details 调用链：中断 -> HAL_PCD_SetupStageCallback -> USBD_LL_SetupStage
 *          -> USBD_StdDevReq -> USBD_GS_Setup -> USBD_GS_Vendor_Request
 *          IN 请求（设备->主机）直接发回应答；OUT 请求（主机->设备）保存
 *          请求上下文并预置 ep0 接收缓冲，数据到齐后由 control_setup_OUT_data()
 *          进入第二阶段处理
 * @note 除"查询错误"本身外，任何新命令都会清除上一次的错误
 */
bool control_setup_request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req)
{
    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)pdev->pClassData;

    if (req->bRequest != ELM_ReqGetLastError)
        ELM_LastError = FBK_Success;

    // 总线关闭时短闪蓝色 LED，提示设备未在运行
    if (!can_is_opened())
        led_flash_RX(); // 闪 15 ms

    uint8_t value8; // 8 位应答缓冲区
    uint16_t value16; // 16 位应答缓冲区
    uint32_t value32; // 32 位应答缓冲区
    void* src = NULL; // IN 请求的应答数据指针
    uint16_t len = 0; // 应答长度
    switch (req->bRequest) {
    // ------- 主机 -> 设备（OUT，参数错误在第二阶段校验） --------
    case GS_ReqSetHostFormat: // 设置数据格式（仅支持小端）
        len = sizeof(uint32_t);
        break;
    case GS_ReqIdentify: // LED 识别（mode 参数被忽略）
        len = sizeof(uint32_t);
        break;
    case GS_ReqSetBitTiming: // 经典帧/标称位时序
    case GS_ReqSetBitTimingFD: // FD 数据位时序
        len = sizeof(kBitTiming);
        break;
    case GS_ReqSetDeviceMode: // 启动/停止 CAN
        len = sizeof(kDeviceMode);
        break;
    case GS_ReqSetTermination: // 开关终端电阻
        len = sizeof(uint32_t);
        break;
    case ELM_ReqSetFilter: // 设置接受掩码过滤器
        len = sizeof(kFilter);
        break;
    case ELM_ReqSetBusLoadReport: // 使能总线负载上报
        len = sizeof(uint8_t);
        break;
    case ELM_ReqSetPinStatus: // 引脚操作
        len = sizeof(kPinStatus);
        break;

    // -------- 设备 -> 主机（IN，立即应答） --------
    case GS_ReqGetCapabilities: // 经典帧能力
        src = &GS_CapabilityClassic;
        len = sizeof(kCapabilityClassic);
        break;
    case GS_ReqGetCapabilitiesFD: // FD 能力
        src = &GS_CapabilityFD;
        len = sizeof(kCapabilityFD);
        break;
    case GS_ReqGetDeviceVersion: // 版本号
        src = &GS_DeviceVersion;
        len = sizeof(kDeviceVersion);
        break;
    case GS_ReqGetTimestamp: // 1 µs 时间戳
        value32 = system_get_timestamp();
        src = &value32;
        len = sizeof(uint32_t);
        break;
    case GS_ReqGetTermination: // 终端电阻状态
    {
        bool bEnabled;
        if (!can_get_termination(&bEnabled)) {
            ELM_LastError = FBK_UnsupportedFeature;
            return false; // 该板不支持终端电阻
        }
        value32 = bEnabled ? GS_TerminationON : GS_TerminationOFF;
        src = &value32;
        len = sizeof(uint32_t);
        break;
    }
    case ELM_ReqGetBoardInfo: // 板信息
        src = &ELM_BoardInfo;
        len = sizeof(kBoardInfo);
        break;
    case ELM_ReqGetLastError: // 上一条命令的反馈错误
    {
        value8 = ELM_LastError;
        src = &value8;
        len = sizeof(uint8_t);
        break;
    }
    case ELM_ReqGetPinStatus: // 引脚状态
    {
        switch (req->wValue) // 引脚 ID 放在 wValue 中传输
        {
        case PINID_BOOT0: // 目前唯一支持的引脚
            value16 = system_is_option_enabled(OPT_BOOT0_Enable) ? PINST_Enabled : 0;
            break;
        default:
            ELM_LastError = FBK_InvalidParameter;
            return false;
        }
        src = &value16;
        len = sizeof(uint16_t);
        break;
    }
    default:
        ELM_LastError = FBK_InvalidCommand;
        return false;
    }

    // 主机缓冲区小于应答长度时返回部分数据（USB 规范允许）
    len = MIN(len, req->wLength);

    switch (req->bRequest) {
    // -------- 主机 -> 设备（OUT）：移交到第二阶段 --------
    case GS_ReqIdentify:
    case GS_ReqSetHostFormat:
    case GS_ReqSetBitTiming:
    case GS_ReqSetBitTimingFD:
    case GS_ReqSetDeviceMode:
    case GS_ReqSetTermination:
    case ELM_ReqSetFilter:
    case ELM_ReqSetBusLoadReport:
    case ELM_ReqSetPinStatus:
        // 保存请求上下文，预置 ep0 接收缓冲，等 OUT 数据到齐后处理
        hcan->last_setup_request = *req;
        USBD_CtlPrepareRx(pdev, hcan->ep0_buf, req->wLength);
        return true;

    // -------- 设备 -> 主机（IN）：直接发回应答 --------
    case GS_ReqGetCapabilities:
    case GS_ReqGetCapabilitiesFD:
    case GS_ReqGetDeviceVersion:
    case GS_ReqGetTimestamp:
    case GS_ReqGetTermination:
    case ELM_ReqGetBoardInfo:
    case ELM_ReqGetLastError:
    case ELM_ReqGetPinStatus:
        USBD_CtlSendData(pdev, (uint8_t*)src, len);
        return true;

    default:
        ELM_LastError = FBK_InvalidCommand;
        return false;
    }
}

/**
 * @brief 处理 SETUP 厂商请求的第二阶段（主机发来的 OUT 数据）
 * @param[in] pdev USB 设备句柄
 * @details 调用链：中断 -> HAL_PCD_DataOutStageCallback -> USBD_LL_DataOutStage
 *          -> USBD_GS_EP0_RxReady -> 本函数
 * @note 进入此阶段后 HAL 已不允许 stall 端点 0，校验失败无法用 USB 协议层
 *       报错，只能存进 ELM_LastError，由主机在每条命令后调用
 *       ELM_ReqGetLastError 主动查询（新 ElmueSoft 协议机制）
 */
void control_setup_OUT_data(USBD_HandleTypeDef* pdev)
{
    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)pdev->pClassData;
    USBD_SetupReqTypedef* req = &hcan->last_setup_request;

    switch (req->bRequest) {
    case GS_ReqSetHostFormat: {
        // 原版 USB2CAN 用 0xbeef 协商字节序；开源 CandleLight 固定小端。
        // 这里只认小端，主机要求大端则报不支持
        uint32_t* format = (uint32_t*)hcan->ep0_buf;
        if (*format != 0xbeef)
            ELM_LastError = FBK_UnsupportedFeature;
        return;
    }
    case GS_ReqSetBitTiming: { // 经典帧/标称位时序（prop 并入 seg1）
        kBitTiming* timing = (kBitTiming*)hcan->ep0_buf;
        ELM_LastError = can_set_nom_bit_timing(timing->brp, timing->prop + timing->seg1, timing->seg2, timing->sjw);
        return;
    }
    case GS_ReqSetBitTimingFD: { // FD 数据相位位时序
        kBitTiming* timing = (kBitTiming*)hcan->ep0_buf;
        ELM_LastError = can_set_data_bit_timing(timing->brp, timing->prop + timing->seg1, timing->seg2, timing->sjw);
        return;
    }
    case GS_ReqSetDeviceMode: {
        // ---- 1) 参数校验 ----
        kDeviceMode* dev_Mode = (kDeviceMode*)hcan->ep0_buf;
        if (dev_Mode->mode != GS_ModeStart && dev_Mode->mode != GS_ModeReset) {
            ELM_LastError = FBK_InvalidParameter;
            return;
        }
        if (dev_Mode->mode == GS_ModeStart) {
            // 启动前设备必须处于关闭状态
            if (can_is_opened()) {
                ELM_LastError = FBK_AdapterMustBeClosed;
                return;
            }
            // CAN FD 由数据波特率隐式启用；主机要求 FD 却没配数据时序则拒绝
            if ((dev_Mode->flags & GS_DevFlagCAN_FD) > 0 && !can_using_FD()) {
                ELM_LastError = FBK_BaudrateNotSet;
                return;
            }
        }
        // ---- 2) 按 flags 更新用户标志（先复位默认值）----
        USER_Flags = USR_CandleDefault;
        if (dev_Mode->flags & GS_DevFlagOneShot)
            USER_Flags &= ~USR_Retransmit; // 单次发送：关闭自动重传
        if (dev_Mode->flags & GS_DevFlagTimestamp)
            USER_Flags |= USR_Timestamp; // 使能时间戳
        if (dev_Mode->flags & ELM_DevFlagDisableTxEcho)
            USER_Flags &= ~USR_ReportTX; // 关闭 Tx 回显
        if (dev_Mode->flags & ELM_DevFlagProtocolElmue)
            USER_Flags |= (USR_ProtoElmue | USR_DebugReport); // 启用新协议 + 调试输出

        // ---- 3) 打开 / 关闭 ----
        if (dev_Mode->mode == GS_ModeStart) {
            // 由 ListenOnly / Loopback 组合决定 FDCAN 工作模式
            uint32_t open_mode = FDCAN_MODE_NORMAL;
            if ((dev_Mode->flags & GS_DevFlagListenOnly) > 0) {
                open_mode = FDCAN_MODE_BUS_MONITORING; // 只听：不发 ACK
                if ((dev_Mode->flags & GS_DevFlagLoopback) > 0)
                    open_mode = FDCAN_MODE_INTERNAL_LOOPBACK; // 只听 + 回环：内部回环
            } else {
                if ((dev_Mode->flags & GS_DevFlagLoopback) > 0)
                    open_mode = FDCAN_MODE_EXTERNAL_LOOPBACK; // 回环：发总线 + 自收
            }
            ELM_LastError = can_open(open_mode);
            return;
        }
        if (dev_Mode->mode == GS_ModeReset) {
            can_close(); // 已关闭时重复关闭不算错误
            return;
        }
    }
    case GS_ReqIdentify: {
        uint32_t* mode = (uint32_t*)hcan->ep0_buf; // 非 0 闪烁，0 停止
        led_blink_identify(*mode); // 蓝/绿 LED 交替闪烁
        return;
    }
    case GS_ReqSetTermination: {
        uint32_t* termination = (uint32_t*)hcan->ep0_buf; // eTermination
        if (!can_set_termination(*termination == GS_TerminationON))
            ELM_LastError = FBK_UnsupportedFeature; // 板级不支持
        return;
    }
    case ELM_ReqSetFilter: {
        kFilter* filter = (kFilter*)hcan->ep0_buf;
        switch (filter->Operation) {
        case FIL_ClearAll: // 清空全部过滤器
            ELM_LastError = can_clear_filters();
            return;
        case FIL_AcceptMask11bit: // 添加 11 位接受掩码过滤器
        case FIL_AcceptMask29bit: // 添加 29 位接受掩码过滤器
            ELM_LastError = can_set_mask_filter(filter->Operation == FIL_AcceptMask29bit, filter->Filter, filter->Mask);
            return;
        default:
            ELM_LastError = FBK_InvalidParameter;
            return;
        }
    }
    case ELM_ReqSetBusLoadReport: {
        uint8_t interval = hcan->ep0_buf[0]; // 上报间隔，单位 100 ms
        if ((USER_Flags & USR_ProtoElmue) == 0)
            ELM_LastError = FBK_InvalidParameter; // 总线负载上报依赖新协议
        else
            ELM_LastError = can_enable_busload(interval);
        return;
    }
    case ELM_ReqSetPinStatus: {
        kPinStatus* pin_status = (kPinStatus*)hcan->ep0_buf;

        // 目前只支持禁用 BOOT0（写 Option Bytes）。
        // "使能"无需在此实现——进入 DFU 时 dfu_switch_to_bootloader() 会自行处理
        if (pin_status->PinID == PINID_BOOT0 && pin_status->Operation == PINOP_Disable) {
            ELM_LastError = system_set_option_bytes(OPT_BOOT0_Disable);
            return;
        }
        ELM_LastError = FBK_InvalidParameter;
        return;
    }
    }
}

// ========================= 错误上报 ===========================

/**
 * @brief 周期上报总线错误
 * @param[in] tick_now 当前 1 µs 时基
 * @details 主循环周期调用（约每毫秒 100 次）。错误状态变化时每 100 ms
 *          上报一次；不变时只每 3000 ms 报一次，避免刷屏
 */
void control_process(uint32_t tick_now)
{
    if (error_is_report_due(tick_now))
        buf_store_error();
}

/**
 * @brief 向主机发送总线负载百分比报文
 * @param[in] busload_percent 总线负载百分比
 * @note 由 can.c 在使能总线负载上报后周期触发
 */
void control_report_busload(uint8_t busload_percent)
{
    kHostFrameObject* pool_frame = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
    if (!pool_frame)
        return; // 缓冲溢出，由 buf_process() 统一上报

    kBusloadElmue* packet = (kBusloadElmue*)&pool_frame->frame;
    packet->header.size = sizeof(kBusloadElmue);
    packet->header.msg_type = MSG_Busload;
    packet->bus_load = busload_percent;

    list_add_tail_locked(&pool_frame->list, &USB_BufHandle.list_to_host);
}

/**
 * @brief 向主机发送调试字符串
 * @param[in] message 调试消息，最多 78 字符，可含 '\n' 换行
 * @return true 已入队；false 调试上报未启用或缓冲溢出
 * @note 需同时启用 ElmueSoft 新协议与调试上报（USR_DebugReport）
 */
bool control_send_debug_mesg(const char* message)
{
    if ((USER_Flags & USR_DebugReport) == 0)
        return false;

    kHostFrameObject* pool_frame = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
    if (!pool_frame)
        return false; // 缓冲溢出

    int len = strlen(message);
    if (len > sizeof(kHostFrameLegacy) - sizeof(kStringElmue)) {
        message = "*** Dbg msg too long"; // 过长则发固定提示
        len = 20;
    }

    kStringElmue* packet = (kStringElmue*)&pool_frame->frame;
    packet->header.size = sizeof(kStringElmue) + len;
    packet->header.msg_type = MSG_String;
    memcpy(packet->ascii_msg, message, len);

    list_add_tail_locked(&pool_frame->list, &USB_BufHandle.list_to_host);
    return true;
}
