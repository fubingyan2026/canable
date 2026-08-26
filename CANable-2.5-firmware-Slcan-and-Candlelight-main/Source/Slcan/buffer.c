/**
 * @file buffer.c
 * @brief Slcan 缓冲管理：CDC 接收命令解析、CDC 发送、CAN 发送队列与 SLCAN ASCII 帧格式化
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Nakanishi Kiyomaro / Normadotcom
    https://netcult.ch/elmue/CANable Firmware Update
    TODO: Check IRQ handling which seems wrong.
*/

#include "usb_interface.h"
#include "buffer.h"
#include "error.h"
#include "control.h"
#include "system.h"
#include "utils.h"

extern eUserFlags USER_Flags;

/** @brief CDC 发送三缓冲（全局） */
volatile struct buf_cdc_tx buf_cdc_tx = {0};
/** @brief CDC 接收环形缓冲（全局） */
volatile struct buf_cdc_rx buf_cdc_rx = {0};
/** @brief CAN 发送队列（静态） */
static   struct buf_can_tx buf_can_tx = {0};
/** @brief 正在拼接的 SLCAN 命令行缓冲 */
static uint8_t slcan_str[SLCAN_MTU];
/** @brief 已拼接的命令行字符数 */
static uint8_t slcan_str_index = 0;

/**
 * @brief 把一帧 CAN 报文格式化为 SLCAN ASCII 行
 * @param[in] buf 输出缓冲
 * @param[in] b_TX 是否为发送方向（未使用）
 * @param[in] rx_header FDCAN 接收描述符
 * @param[in] frame_data 数据字节
 * @return 生成的行长度
 */
int32_t buf_frame_to_ascii(uint8_t *buf, bool b_TX, FDCAN_RxHeaderTypeDef *rx_header, uint8_t *frame_data);

/**
 * @brief 初始化各缓冲
 */
void buf_init()
{
    buf_cdc_rx.head = 0;
    buf_cdc_rx.tail = 0;

    // 初始让 head 落后 tail 一个槽，保证逻辑上为空
    buf_cdc_tx.head = 1;
    buf_cdc_tx.msglen[buf_cdc_tx.head] = 0;
    buf_cdc_tx.tail = 0;
    buf_cdc_tx.msglen[buf_cdc_tx.tail] = 0;

    buf_can_tx.head = 0;
    buf_can_tx.send = 0;
    buf_can_tx.tail = 0;
    buf_can_tx.full = 0;
}

/**
 * @brief 清空 CAN 发送队列
 */
void buf_clear_can_buffer()
{
    buf_can_tx.tail = buf_can_tx.head;
    buf_can_tx.send = buf_can_tx.head;
    buf_can_tx.full = 0;
}

/**
 * @brief 缓冲处理主函数（主循环周期调用，约每毫秒 100 次）
 * @param[in] tick_now 当前 1 µs 时基
 * @details 依次处理：①CDC 接收缓冲（拼命令，遇 \r 交给 control_parse_command）
 *          ②CDC 发送缓冲（经 CDC_Transmit_FS 发给主机）③CAN 发送队列（写入 FDCAN FIFO）
 */
void buf_process(uint32_t tick_now)
{
    // 关中断读取 buf_cdc_rx.head，因为该变量在中断回调 CDC_Receive_FS() 中被修改
    system_disable_irq();
    uint32_t tmp_head = buf_cdc_rx.head;
    system_enable_irq();

    // ---------- 1) 处理 CDC 接收缓冲 ----------
    if (buf_cdc_rx.tail != tmp_head)
    {
        // 处理整个缓冲槽：逐字符拼接命令行
        for (uint32_t i = 0; i < buf_cdc_rx.msglen[buf_cdc_rx.tail]; i++)
	    {
            if (buf_cdc_rx.data[buf_cdc_rx.tail][i] == '\r')
            {
                // 收到回车：执行一条完整命令
                control_parse_command((char*)slcan_str, slcan_str_index);
                slcan_str_index = 0;
            }
            else
            {
                // 检查命令行缓冲是否溢出
                if (slcan_str_index >= SLCAN_MTU)
                {
                    // TODO: Return here and discard this CDC buffer?
                    slcan_str_index = 0;
                }
                slcan_str[slcan_str_index++] = buf_cdc_rx.data[buf_cdc_rx.tail][i];
            }
        }

        // 移到下一个接收槽
        system_disable_irq();
        buf_cdc_rx.tail = (buf_cdc_rx.tail + 1) % BUF_CDC_RX_NUM_BUFS;
        system_enable_irq();
    }

    // ---------- 2) 处理 CDC 发送缓冲 ----------
    uint32_t new_head = (buf_cdc_tx.head + 1) % BUF_CDC_TX_NUM_BUFS;
    if (new_head != buf_cdc_tx.tail)
    {
        if (0 < buf_cdc_tx.msglen[buf_cdc_tx.head])
        {
            // 当前写缓冲非空：前移 head，表示此槽已提交
            buf_cdc_tx.head = new_head;
            buf_cdc_tx.msglen[new_head] = 0;
        }
    }

    system_disable_irq();
    uint32_t new_tail = (buf_cdc_tx.tail + 1) % BUF_CDC_TX_NUM_BUFS;
    if (new_tail != buf_cdc_tx.head)
    {
        // 有已提交的槽可发送；USB 空闲时才前移 tail
        if (CDC_Transmit_FS((uint8_t *)buf_cdc_tx.data[new_tail], buf_cdc_tx.msglen[new_tail]) == USBD_OK)
        {
            buf_cdc_tx.tail = new_tail;
        }
    }
    system_enable_irq();

    // ---------- 3) 处理 CAN 发送队列 ----------
    // 队列非空（head != send 或满标志置位）且 FDCAN Tx FIFO 有空位时逐帧发送
    while ((buf_can_tx.send != buf_can_tx.head || buf_can_tx.full) && (HAL_FDCAN_GetTxFifoFreeLevel(can_get_handle()) > 0))
    {
        // Transmit can frame
        if (can_send_packet(&buf_can_tx.header[buf_can_tx.send], buf_can_tx.data[buf_can_tx.send]))
        {
            buf_can_tx.send = (buf_can_tx.send + 1) % BUF_CAN_TXQUEUE_LEN;
            buf_can_tx.tail = (buf_can_tx.tail + 1) % BUF_CAN_TXQUEUE_LEN;
            buf_can_tx.full = 0;
        }
    }

    // 队列持续满 --> 绿+蓝 LED 常亮提示
    if (buf_can_tx.full)
        error_assert(APP_CanTxOverflow, false);
}

/**
 * @brief 追加数据到 CDC 发送缓冲（发送给主机）
 * @param[in] buf 数据指针
 * @param[in] len 数据长度
 * @details 当前写槽剩余空间不足时报 APP_UsbInOverflow，否则拷贝追加
 */
void buf_enqueue_cdc(char* buf, uint16_t len)
{
    if (BUF_CDC_TX_BUF_SIZE - len < buf_cdc_tx.msglen[buf_cdc_tx.head])
    {
        error_assert(APP_UsbInOverflow, false); // The data does not fit in the buffer
    }
    else
    {
        // Copy data
        memcpy((uint8_t *)&buf_cdc_tx.data[buf_cdc_tx.head][buf_cdc_tx.msglen[buf_cdc_tx.head]], buf, len);
        buf_cdc_tx.msglen[buf_cdc_tx.head] += len;
    }
}

/**
 * @brief 获取 CDC 发送缓冲当前写入起点指针
 * @return 写入起点指针；剩余空间不足以容纳一帧时返回 NULL
 */
uint8_t *buf_get_cdc_dest()
{
    if (BUF_CDC_TX_BUF_SIZE - SLCAN_MTU < buf_cdc_tx.msglen[buf_cdc_tx.head])
    {
        error_assert(APP_UsbInOverflow, false); // The data will not fit in the buffer
        return NULL;
    }
    return (uint8_t *)&buf_cdc_tx.data[buf_cdc_tx.head][buf_cdc_tx.msglen[buf_cdc_tx.head]];
}

/**
 * @brief 提交已写入 CDC 发送缓冲的字节数
 * @param[in] len 新增字节数
 */
void buf_comit_cdc_dest(uint32_t len)
{
    buf_cdc_tx.msglen[buf_cdc_tx.head] += len;
}

/**
 * @brief 获取 CAN 发送帧头缓冲的写入位置
 * @return 帧头指针；队列满时返回 NULL
 */
FDCAN_TxHeaderTypeDef *buf_get_can_dest_header()
{
    if (buf_can_tx.full)
    {
        error_assert(APP_CanTxOverflow, false);
        return NULL;
    }
    return &buf_can_tx.header[buf_can_tx.head];
}

/**
 * @brief 获取 CAN 发送帧数据缓冲的写入位置
 * @return 数据指针；队列满时返回 NULL
 */
uint8_t *buf_get_can_dest_data()
{
    if (buf_can_tx.full)
    {
        error_assert(APP_CanTxOverflow, false);
        return NULL;
    }
    return buf_can_tx.data[buf_can_tx.head];
}

/**
 * @brief 提交当前 CAN 发送槽
 * @return FBK_Success 成功；FBK_TxBufferFull 队列已满；其它为当前不允许发送
 * @details 校验 can_is_tx_allowed() 后前移 head 指针；head 追上 tail 时置满标志
 */
eFeedback buf_comit_can_dest()
{
    eFeedback e_Feedback = can_is_tx_allowed();
    if (e_Feedback != FBK_Success)
        return e_Feedback;

    if (buf_can_tx.full)
    {
        error_assert(APP_CanTxOverflow, false);
        return FBK_TxBufferFull;
    }

    // Increment the head pointer
    buf_can_tx.head = (buf_can_tx.head + 1) % BUF_CAN_TXQUEUE_LEN;
    if (buf_can_tx.head == buf_can_tx.tail)
        buf_can_tx.full = 1;

    return FBK_Success;
}

// ===========================================================================

/**
 * @brief 把收到的 CAN 帧转成 SLCAN ASCII 行并加入 CDC 发送缓冲
 * @param[in] rx_header FDCAN 接收描述符
 * @param[in] frame_data 接收到的数据字节（64 字节缓冲区）
 * @details 帧类型由首字符区分：t/r（经典数据/远程帧）、d/b（FD 无/有 BRS）；
 *          标准 11 位 ID 为小写、扩展 29 位 ID 为大写。随后拼接 ID、DLC、
 *          数据字节（远程帧无）、可选 ESI 标志和 '\r'
 */
void buf_store_rx_packet(FDCAN_RxHeaderTypeDef *rx_header, uint8_t *frame_data)
{
    uint8_t *buf = buf_get_cdc_dest();
    if (buf == NULL)
        return; // buffer is full

    // 经典帧：t/r 分别表示数据/远程帧
    if (rx_header->FDFormat == FDCAN_CLASSIC_CAN)
    {
        if (rx_header->RxFrameType == FDCAN_REMOTE_FRAME) buf[0] = 'r'; // 'R' for 29 bit (remote frame)
        else                                              buf[0] = 't'; // 'T' for 29 bit (FDCAN_DATA_FRAME)
    }
    else // CAN FD（FD 帧无远程帧），用 d/b 区分 BRS 是否启用
    {
        if (rx_header->BitRateSwitch == FDCAN_BRS_ON)     buf[0] = 'b'; // Frame with BRS enabled  'B' for 29 bit
        else                                              buf[0] = 'd'; // Frame with BRS disabled 'D' for 29 bit
    }

    uint8_t id_len = 3;
    if (rx_header->IdType == FDCAN_EXTENDED_ID)
    {
        id_len = 8;
        buf[0] -= 32; // 转为大写，表示 29 位 ID
    }

    // 拼接 CAN ID（从高到低每个十六进制位一个字符）
    uint32_t ident = rx_header->Identifier;
    for (uint8_t j = id_len; j > 0; j--)
    {
        buf[j] = utils_nibble_to_ascii(ident & 0xF);
        ident >>= 4;
    }
    uint8_t pos = 1 + id_len;

    // 拼接 DLC：从 FIFO 寄存器右移取出（ST 未提供处理器无关的移位宏）
    uint32_t dlc_code = rx_header->DataLength >> 16;
    buf[pos++]        = utils_nibble_to_ascii  (dlc_code);
    int8_t byte_count = utils_dlc_to_byte_count(dlc_code); // returns -1 if invalid

    // 拼接数据字节（远程帧不含数据）
    if (rx_header->RxFrameType != FDCAN_REMOTE_FRAME)
    {
        for (uint8_t j = 0; j < byte_count; j++)
        {
            buf[pos++] = utils_nibble_to_ascii(frame_data[j] >> 4);
            buf[pos++] = utils_nibble_to_ascii(frame_data[j] & 0x0F);
        }
    }

    // 可选：附加 ESI 错误被动状态标志
    if (USER_Flags & USR_ReportESI) // Append ESI Error Passive status if enabled by the user
    {
        if (rx_header->FDFormat            == FDCAN_FD_CAN &&
            rx_header->ErrorStateIndicator == FDCAN_ESI_PASSIVE)
            buf[pos++] = 'S';
    }

    buf[pos++] = '\r';
    buf_comit_cdc_dest(pos);
}

/**
 * @brief 把 Tx 回显标记发给主机（与发送报文时相同的 marker）
 * @param[in] tx_event FDCAN Tx 事件
 * @details 格式 "M%02X\r"，供主机把回显与发送的报文对应起来
 */
void buf_store_tx_echo(FDCAN_TxEventFifoTypeDef* tx_event)
{
    char* buf = (char*)buf_get_cdc_dest();
    if (buf == NULL)
        return; // buffer is full

    sprintf(buf, "M%02X\r", (uint8_t)tx_event->MessageMarker);
    buf_comit_cdc_dest(4);
}