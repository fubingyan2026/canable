/**
 * @file buffer.c
 * @brief CAN 帧缓冲池管理：USB<->CAN 双向转发、Tx 回显、错误帧上报
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#include "buffer.h"
#include "can.h"
#include "candlelight_def.h"
#include "control.h"
#include "error.h"
#include "settings.h"
#include "system.h"
#include "usb_class.h"
#include "utils.h"

/**
 * @brief CAN 方向（USB->CAN）帧缓冲池大小
 * @note 主机缓冲比 CAN 缓冲大（见 HOST_QUEUE_SIZE），以避免 ACK 突发时
 *       待发往主机的 Tx 事件溢出（APP_UsbInOverflow）
 */
#define CAN_QUEUE_SIZE 64
/** @brief 主机方向（CAN->USB）帧缓冲池大小 */
#define HOST_QUEUE_SIZE 70

extern eUserFlags USER_Flags;
/** @brief USB 缓冲区句柄（全局单例） */
USB_BufHandleTypeDef USB_BufHandle = { 0 };

/** @brief CAN 方向帧缓冲池（USB->CAN） */
kHostFrameObject can_pool_buffer[CAN_QUEUE_SIZE];
/** @brief 主机方向帧缓冲池（CAN->USB） */
kHostFrameObject host_pool_buffer[HOST_QUEUE_SIZE];

/**
 * @brief 把 list_to_host 中的报文发送给主机
 */
void buf_process_host();
/**
 * @brief 把 list_to_can 中的报文发送到 CAN 总线
 */
void buf_process_can_bus();
/**
 * @brief 清空缓冲并把帧对象重新挂回空闲池
 * @param[in] clear_can  是否清空 CAN 方向（USB->CAN）
 * @param[in] clear_host 是否清空主机方向（CAN->USB）
 */
void buf_clear_buffers(bool clear_can, bool clear_host);

/**
 * @brief 初始化所有缓冲区
 * @details 把全部帧对象放入两个空闲池链表
 */
void buf_init()
{
    buf_clear_buffers(true, true);
}

/**
 * @brief 仅清空 CAN 方向（USB->CAN）的缓冲
 */
void buf_clear_can_buffer()
{
    buf_clear_buffers(true, false);
}

/**
 * @brief 清空缓冲区：将帧对象重新挂回对应的空闲池链表
 * @param[in] clear_can  是否清空 CAN 方向
 * @param[in] clear_host 是否清空主机方向
 */
void buf_clear_buffers(bool clear_can, bool clear_host)
{
    if (clear_can) {
        // 初始化 CAN 方向的空闲池与待发送链表
        list_init(&USB_BufHandle.list_can_pool);
        list_init(&USB_BufHandle.list_to_can);

        // 把全部帧对象加入空闲池环形链表
        for (unsigned i = 0; i < CAN_QUEUE_SIZE; i++) {
            list_add_tail(&can_pool_buffer[i].list, &USB_BufHandle.list_can_pool);
        }
    }
    if (clear_host) {
        // 初始化主机方向的空闲池与待发送链表
        list_init(&USB_BufHandle.list_host_pool);
        list_init(&USB_BufHandle.list_to_host);

        for (unsigned i = 0; i < HOST_QUEUE_SIZE; i++) {
            list_add_tail(&host_pool_buffer[i].list, &USB_BufHandle.list_host_pool);
        }
    }
}

/**
 * @brief 缓冲处理主函数，主循环周期调用（约每毫秒 100 次）
 * @param[in] tick_now 当前 1 µs 时基
 * @details 分别处理主机方向与 CAN 方向的转发；空闲池为空时持续上报溢出，
 *          使绿+蓝 LED 常亮提示问题（APP_xxx 错误发出后被清，需在此刷新）
 */
void buf_process(uint32_t tick_now)
{
    buf_process_host();
    buf_process_can_bus();

    if (list_is_empty(&USB_BufHandle.list_can_pool))
        error_assert(APP_CanTxOverflow, false);
    if (list_is_empty(&USB_BufHandle.list_host_pool))
        error_assert(APP_UsbInOverflow, false);
}

/**
 * @brief 若 list_to_host 有数据，则向主机发送一个 CAN 报文
 * @details 等 USB IN 空闲后取一帧经 USBD_SendFrameToHost 发出，随即归还空闲池
 */
void buf_process_host()
{
    if (USBD_IsTxBusy())
        return; // 向主机的 USB IN 传输仍在进行中

    kHostFrameObject* frame_to_host = buf_get_frame_locked(&USB_BufHandle.list_to_host);
    if (!frame_to_host)
        return; // 没有要发送的内容

    // 通过 USB IN 端点把帧发送给主机
    USBD_SendFrameToHost(&frame_to_host->frame);

    // 报文已发送 --> 将帧对象归还给主机空闲池
    list_add_tail_locked(&frame_to_host->list, &USB_BufHandle.list_host_pool);
}

/**
 * @brief 若 list_to_can 有数据，则向 CAN 总线发送一个主机报文
 * @details 按当前协议（新 ElmueSoft / 传统 GS）解析帧头，填充 FDCAN 发送描述符
 *          后调用 can_send_packet()。发送失败则放回链表稍后重试。
 *          新协议在报文真正上总线（收到 Tx 事件）时回显；传统协议立即伪造回显
 */
void buf_process_can_bus()
{
    if (HAL_FDCAN_GetTxFifoFreeLevel(can_get_handle()) == 0)
        return; // 所有 3 个 CAN Tx 缓冲区都已满

    kHostFrameObject* frame_to_can = buf_get_frame_locked(&USB_BufHandle.list_to_can);
    if (!frame_to_can)
        return; // 没有要发送的内容

    // ------------------------------

    uint32_t can_id; // CAN ID
    uint8_t can_dlc; // 数据长度码
    uint8_t flags; // 帧标志
    uint8_t marker; // TX 回显标记
    uint8_t* frame_data; // 数据指针
    if (USER_Flags & USR_ProtoElmue) // 新的 ElmueSoft 协议
    {
        kTxFrameElmue* tx_frame = (kTxFrameElmue*)&frame_to_can->frame;
        if (tx_frame->header.msg_type != MSG_TxFrame || can_is_tx_allowed() != FBK_Success) {
            // 主机发送了无效报文，或处于静默模式，或总线关闭
            error_assert(APP_CanTxFail, true);
            list_add_tail_locked(&frame_to_can->list, &USB_BufHandle.list_can_pool);
            return; // 不发送该报文
        }
        can_id = tx_frame->can_id; // 提取 CAN ID
        flags = tx_frame->flags; // 提取帧标志
        marker = tx_frame->marker; // 提取回显标记
        frame_data = tx_frame->data_start; // 数据起始指针
        // 数据字节数 = 消息总长 - 帧头结构体大小
        can_dlc = utils_byte_count_to_dlc(tx_frame->header.size - sizeof(kTxFrameElmue));
    } else // 传统 Geschwister Schneider 协议
    {
        kHostFrameLegacy* tx_frame = &frame_to_can->frame;
        can_id = tx_frame->can_id; // 提取 CAN ID
        flags = tx_frame->flags; // 提取帧标志
        frame_data = tx_frame->pack_FD.data; // 数据起始指针（用 64 字节联合体）
        can_dlc = tx_frame->can_dlc; // 传统协议直接携带 DLC
        marker = 0; // 不使用；传统协议用 echo_id 发送一个假回显
    }

    // ------------------------------

    // 填充 FDCAN 发送描述符
    FDCAN_TxHeaderTypeDef tx_header;
    tx_header.TxFrameType = FDCAN_DATA_FRAME;
    tx_header.FDFormat = FDCAN_CLASSIC_CAN;
    tx_header.IdType = FDCAN_STANDARD_ID;
    tx_header.BitRateSwitch = FDCAN_BRS_OFF;
    tx_header.TxEventFifoControl = FDCAN_STORE_TX_EVENTS; // 总是存储！Tx 事件会让绿色 LED 闪烁
    tx_header.ErrorStateIndicator = can_is_passive() ? FDCAN_ESI_PASSIVE : FDCAN_ESI_ACTIVE;
    tx_header.MessageMarker = marker;

    // 根据 CAN ID 标志设置 ID 类型
    if (can_id & CAN_ID_29Bit) {
        tx_header.IdType = FDCAN_EXTENDED_ID; // 29 位扩展 ID
        tx_header.Identifier = can_id & CAN_MASK_29;
    } else
        tx_header.Identifier = can_id & CAN_MASK_11; // 11 位标准 ID

    // 远程帧
    if (can_id & CAN_ID_RTR)
        tx_header.TxFrameType = FDCAN_REMOTE_FRAME;

    // CAN FD 帧
    if (flags & FRM_FDF) // 置位表示隐性（即启用 FD）
    {
        tx_header.FDFormat = FDCAN_FD_CAN;

        // BRS 位速率切换（原始代码此处有误，已修复）
        if (flags & FRM_BRS) // 置位表示隐性（即启用 BRS）
            tx_header.BitRateSwitch = FDCAN_BRS_ON;
    }

    // 将 DLC 左移 16 位以直接存入 FIFO 寄存器（ST 未提供处理器无关的宏）
    tx_header.DataLength = (can_dlc & 0xF) << 16;

    // 发送 CAN 报文
    if (!can_send_packet(&tx_header, frame_data)) {
        // 发送失败（可能总线忙）：把报文放回原链表，稍后重试
        list_add_head_locked(&frame_to_can->list, &USB_BufHandle.list_to_can);
        return;
    }

    // 此时 Tx 报文已在 CAN Tx FIFO 中，但尚未真正发送到 CAN 总线

    if (USER_Flags & USR_ProtoElmue) {
        // 新 ElmueSoft 固件在报文真正上总线时（HAL_FDCAN_GetTxEvent() 收到 Tx 事件）
        // 才发送回显，此处无需立即做任何事
    } else // 传统协议
    {
        // 传统协议在报文存入 Tx FIFO 时立即伪造一份带新时间戳的回显发给主机。
        // 该回显无法反映报文是否真的上总线（若在 FIFO 中等 ACK 久了，时间戳是错的），
        // 仅为向后兼容旧软件而保留
        // frame_to_can 来自 CAN 空闲池，不能把它发给主机，否则 CAN 空闲池会很快耗尽
        kHostFrameObject* frame_to_host = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
        if (frame_to_host) {
            // 复制报文并盖上新的时间戳
            memcpy(&frame_to_host->frame, &frame_to_can->frame, sizeof(kHostFrameLegacy));

            if (frame_to_host->frame.flags & FRM_FDF)
                frame_to_host->frame.pack_FD.timestamp_us = system_get_timestamp(); // FD 帧时间戳
            else // classic frame
                frame_to_host->frame.pack_classic.timestamp_us = system_get_timestamp(); // 经典帧时间戳

            // 向主机发送假回显
            list_add_tail_locked(&frame_to_host->list, &USB_BufHandle.list_to_host);
        }
    }

    // 把 CAN 帧归还给它来自的空闲池
    list_add_tail_locked(&frame_to_can->list, &USB_BufHandle.list_can_pool);
}

/**
 * @brief 保存一个收到的 CAN 帧（或成功上总线的 Tx 帧）到 list_to_host
 * @param[in] rx_header FDCAN 接收描述符
 * @param[in] frame_data 存放收到的数据字节的 64 字节缓冲区
 * @details 按当前协议打包：新 ElmueSoft 协议只发实际字节数并可省去时间戳；
 *          传统协议固定复制 64 字节并把时间戳放在数据之后
 */
void buf_store_rx_packet(FDCAN_RxHeaderTypeDef* rx_header, uint8_t* frame_data)
{
    kHostFrameObject* pool_frame = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
    if (!pool_frame)
        return; // 缓冲溢出！buf_process() 会向主机上报该错误

    // 从 FDCAN 接收描述符提取 CAN ID，并补上协议标志位
    uint32_t can_id;
    if (rx_header->IdType == FDCAN_EXTENDED_ID)
        can_id = (rx_header->Identifier & CAN_MASK_29) | CAN_ID_29Bit; // 29 位扩展 ID
    else
        can_id = (rx_header->Identifier & CAN_MASK_11); // 11 位标准 ID

    // 远程帧
    if (rx_header->RxFrameType == FDCAN_REMOTE_FRAME)
        can_id |= CAN_ID_RTR;

    // 提取帧标志
    uint8_t flags = 0;
    if (rx_header->FDFormat == FDCAN_FD_CAN) {
        flags |= FRM_FDF; // FD 帧
        if (rx_header->BitRateSwitch == FDCAN_BRS_ON)
            flags |= FRM_BRS; // BRS 位速率切换
        if (rx_header->ErrorStateIndicator == FDCAN_ESI_PASSIVE)
            flags |= FRM_ESI; // ESI 错误状态指示
    }

    // 从 FIFO 寄存器右移取出 DLC
    uint8_t can_dlc = (rx_header->DataLength >> 16) & 0xF;

    // ------------------------

    if (USER_Flags & USR_ProtoElmue) // 新的 ElmueSoft 协议
    {
        uint8_t byte_count = utils_dlc_to_byte_count(can_dlc); // DLC -> 实际字节数

        kRxFrameElmue* frame = (kRxFrameElmue*)&pool_frame->frame;
        frame->header.size = sizeof(kRxFrameElmue) + byte_count; // 消息总长（含数据）
        frame->header.msg_type = MSG_RxFrame;
        frame->flags = flags;
        frame->can_id = can_id;
        frame->timestamp = system_get_timestamp(); // 1 µs 时间戳

        // 数据起始位置取决于是否发送时间戳
        if (USER_Flags & USR_Timestamp) {
            memcpy(frame->data_use_stamp, frame_data, byte_count);
        } else {
            frame->header.size -= 4; // 不含时间戳则消息总长减 4
            memcpy(frame->data_no_stamp, frame_data, byte_count);
        }
    } else // 传统 Geschwister Schneider 协议
    {
        kHostFrameLegacy* frame = &pool_frame->frame;
        frame->channel = 0; // 通道未使用，恒为零
        frame->reserved = 0; // 保留字节
        frame->flags = flags;
        frame->can_id = can_id;
        frame->can_dlc = can_dlc;
        frame->echo_id = ECHO_RxData; // 标记为 Rx 数据
        memcpy(frame->raw_data, frame_data, 64); // 总是复制 64 字节（传统协议缺陷）

        // 时间戳放在数据后面（传统协议的愚蠢设计）
        if (rx_header->FDFormat == FDCAN_FD_CAN)
            frame->pack_FD.timestamp_us = system_get_timestamp(); // FD 帧时间戳
        else // classic frame
            frame->pack_classic.timestamp_us = system_get_timestamp(); // 经典帧时间戳
    }

    // 关中断地把帧加入 list_to_host
    list_add_tail_locked(&pool_frame->list, &USB_BufHandle.list_to_host);
}

/**
 * @brief 保存 Tx 回显标记到 list_to_host
 * @param[in] tx_event FDCAN Tx 事件（含发送时使用的 MessageMarker）
 * @note 仅新 ElmueSoft 协议使用真实回显；传统协议走 buf_process_can_bus() 的假回显
 */
void buf_store_tx_echo(FDCAN_TxEventFifoTypeDef* tx_event)
{
    if ((USER_Flags & USR_ProtoElmue) == 0)
        return;

    kHostFrameObject* pool_frame = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
    if (!pool_frame)
        return; // 缓冲溢出！buf_process() 会向主机上报该错误

    // 构造 Tx 回显报文：仅携带标记与时间戳，无需整个数据帧
    kTxEchoElmue* frame = (kTxEchoElmue*)&pool_frame->frame;
    frame->header.size = sizeof(kTxEchoElmue);
    frame->header.msg_type = MSG_TxEcho;
    frame->marker = tx_event->MessageMarker; // 从 Tx 事件中取回发送时用的标记
    frame->timestamp = system_get_timestamp();

    // 未启用时间戳则消息总长减 4
    if ((USER_Flags & USR_Timestamp) == 0)
        frame->header.size -= 4;

    // 关中断地把帧加入 list_to_host
    list_add_tail_locked(&pool_frame->list, &USB_BufHandle.list_to_host);
}

/**
 * @brief 生成一个错误帧并追加到 list_to_host
 * @details 根据 error_get_state() 返回的控制器状态、最近协议错误与错误计数，
 *          分别按新/旧协议把错误编码进 CAN ID 与数据字节（见 candlelight_def.h）
 */
void buf_store_error()
{
    kHostFrameObject* pool_frame = buf_get_frame_locked(&USB_BufHandle.list_host_pool);
    if (!pool_frame)
        return; // 缓冲溢出！buf_process() 会向主机上报该错误

    // 同一块缓冲区可按两种协议解释
    kHostFrameLegacy* frame_gs = &pool_frame->frame;
    kErrorElmue* frame_elmue = (kErrorElmue*)&pool_frame->frame;
    memset(frame_gs, 0, sizeof(kHostFrameLegacy));

    uint8_t* frame_data;
    if (USER_Flags & USR_ProtoElmue) // 新的 ElmueSoft 协议
        frame_data = frame_elmue->err_data; // 数据写入 err_data[8]
    else // 传统 Geschwister Schneider 协议
        frame_data = frame_gs->pack_classic.data; // 数据写入经典帧的 data[8]

    uint32_t can_id = 0;

    // 总线状态（自上次 error_clear() 后仍未清除的错误）
    kCanErrorState* state = error_get_state();
    switch (state->bus_status) {
    case BUS_StatusOff:
        can_id |= ERID_Bus_is_off; // 总线关闭
        break;
    case BUS_StatusPassive:
        // 错误被动状态（>128 错误）
        if (state->tx_err_count > 0)
            frame_data[1] |= ER1_Tx_Passive_status_reached;
        if (state->rx_err_count > 0)
            frame_data[1] |= ER1_Rx_Passive_status_reached;
        break;
    case BUS_StatusWarning:
        if (state->tx_err_count > 0)
            frame_data[1] |= ER1_Tx_Errors_at_warning_level;
        if (state->rx_err_count > 0)
            frame_data[1] |= ER1_Rx_Errors_at_warning_level;
        break;
    default:
        // 总线从之前的 Warning、Passive 或 Off 状态恢复正常
        if (state->back_to_active) // 总线已恢复主动
            frame_data[1] |= ER1_Bus_is_back_active;
        break;
    }

    // 最近一次协议错误
    switch (state->last_proto_err) {
    case FDCAN_PROTOCOL_ERROR_ACK:
        can_id |= ERID_No_ACK_received; // 未收到 ACK
        break;
    case FDCAN_PROTOCOL_ERROR_CRC:
        can_id |= ERID_CRC_Error; // CRC 错误（ElmueSoft 新增）
        break;
    case FDCAN_PROTOCOL_ERROR_STUFF:
        frame_data[2] |= ER2_Bit_stuffing_error; // 位填充错误
        break;
    case FDCAN_PROTOCOL_ERROR_FORM:
        frame_data[2] |= ER2_Frame_format_error; // 帧格式错误
        break;
    case FDCAN_PROTOCOL_ERROR_BIT1:
        frame_data[2] |= ER2_Unable_to_send_recessive_bit; // 无法发送隐性位
        break;
    case FDCAN_PROTOCOL_ERROR_BIT0:
        frame_data[2] |= ER2_Unable_to_send_dominant_bit; // 无法发送显性位
        break;
    }

    if ((USER_Flags & USR_ProtoElmue) == 0) // 传统模式
    {
        // 传统协议没有可传输 APP_CanRxFail / APP_CanTxFail 的标志，
        // 只能把应用错误克隆到 CAN ID 和字节 1
        if (state->app_flags & APP_CanTxTimeout)
            can_id |= ERID_Tx_Timeout;
        if (state->app_flags & APP_UsbInOverflow)
            frame_data[1] |= ER1_Rx_Buffer_Overflow;
        if (state->app_flags & APP_CanTxOverflow)
            frame_data[1] |= ER1_Tx_Buffer_Overflow;

        // 这些标志是冗余的（信息已在字节 1/2），仅为兼容旧软件而设置
        if (frame_data[1] > 0)
            can_id |= ERID_Controller_problem;
        if (frame_data[2] > 0)
            can_id |= ERID_Protocol_violation;
    }

    // 字节 5-7 在传统固件中未使用；新固件在此传输更详细的错误信息
    frame_data[5] = state->app_flags; // 应用级错误标志
    frame_data[6] = state->tx_err_count; // Tx 错误计数
    frame_data[7] = state->rx_err_count; // Rx 错误计数

    if (USER_Flags & USR_ProtoElmue) // 新的 ElmueSoft 协议
    {
        frame_elmue->header.size = sizeof(kErrorElmue);
        frame_elmue->header.msg_type = MSG_Error;
        frame_elmue->err_id = can_id; // 因为是 MSG_Error，所以不需要 CAN_ID_Error 标志
        frame_elmue->timestamp = system_get_timestamp();

        // 未启用时间戳则消息总长减 4
        if ((USER_Flags & USR_Timestamp) == 0)
            frame_elmue->header.size -= 4;
    } else // 传统 Geschwister Schneider 协议
    {
        frame_gs->echo_id = ECHO_RxData;
        frame_gs->can_id = can_id | CAN_ID_Error; // 置 CAN_ID_Error 标记错误帧
        frame_gs->can_dlc = 8; // 固定 8 字节
        frame_gs->pack_classic.timestamp_us = system_get_timestamp();
    }

    // 关中断地把帧加入 list_to_host，并清除错误状态避免重复上报
    list_add_tail_locked(&pool_frame->list, &USB_BufHandle.list_to_host);
    error_clear();
}

/**
 * @brief 关中断地从链表取一个帧对象并移除
 * @param[in] list_head 目标链表头
 * @return 帧对象指针；链表为空时返回 NULL
 */
kHostFrameObject* buf_get_frame_locked(list_item* list_head)
{
    system_disable_irq();
    kHostFrameObject* frame_obj = list_get_head_or_null(list_head, kHostFrameObject, list);
    if (!frame_obj) {
        system_enable_irq();
        return NULL;
    }
    list_remove(&frame_obj->list); // 把 frame_obj 从其链表中移除
    system_enable_irq();
    return frame_obj;
}
