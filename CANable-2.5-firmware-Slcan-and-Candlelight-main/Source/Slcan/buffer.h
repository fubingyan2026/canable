/**
 * @file buffer.h
 * @brief Slcan 缓冲管理：CDC 接收/发送环形缓冲与 CAN 发送队列
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Nakanishi Kiyomaro / Normadotcom
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once
#include "can.h"
#include "usb_class.h"

/** @brief 最大命令长度：z/Z 帧头 1 + 帧数据 138 + 时间戳 8 + ESI 1 + \r 1 + 余量 16 */
#define SLCAN_MTU (1 + 138 + 8 + 1 + 1 + 16)

/** @brief CDC 接收缓冲数量（环形缓冲的槽数） */
#define BUF_CDC_RX_NUM_BUFS    8
/** @brief CDC 接收缓冲项大小（= 64 字节 USB 包大小） */
#define BUF_CDC_RX_BUF_SIZE    CDC_DATA_FS_MAX_PACKET_SIZE // = 64 Size of RX buffer item

/** @brief CDC 发送缓冲数量（报文 + 调试消息共用） */
#define BUF_CDC_TX_NUM_BUFS    3
/** @brief CDC 发送缓冲项大小（设为 64 * 64 以容纳最大单包） */
#define BUF_CDC_TX_BUF_SIZE    4096 // Set to 64 * 64 for max single packet size

/** @brief CAN 发送队列长度（分配的缓冲区数量） */
#define BUF_CAN_TXQUEUE_LEN    64   // Number of buffers allocated
/** @brief CAN 最大数据长度，CAN FD 需要 64 */
#define CAN_MAX_DATALEN        64   // CAN maximum data length. Must be 64 for canfd.

/**
 * @brief CDC 接收环形缓冲（FIFO）
 * @details buf_cdc_rx 在中断处理函数 CDC_Receive_FS() 中写入（接收 ASCII 字符）；
 *          主循环遇到回车（\r）时把整条命令交给 control_parse_command()
 */
struct buf_cdc_rx
{
	uint8_t  data  [BUF_CDC_RX_NUM_BUFS][BUF_CDC_RX_BUF_SIZE]; /**< 环形缓冲数据区 */
	uint32_t msglen[BUF_CDC_RX_NUM_BUFS]; /**< 每槽的字节数 */
	uint32_t head; /**< 写指针（中断中更新） */
	uint32_t tail; /**< 读指针（主循环中更新） */
};

/**
 * @brief CDC 发送三缓冲
 * @details buf_cdc_tx 在 buf_enqueue_cdc() 中写入，固件向主机发送 ASCII 字符
 */
struct buf_cdc_tx
{
	uint8_t  data  [BUF_CDC_TX_NUM_BUFS][BUF_CDC_TX_BUF_SIZE]; /**< 三缓冲数据区 */
	uint32_t msglen[BUF_CDC_TX_NUM_BUFS]; /**< 每缓冲的字节数 */
	uint32_t head; /**< 写指针 */
	uint32_t tail; /**< 读指针 */
};

/**
 * @brief CAN 发送帧环形队列
 * @details buf_can_tx 在 control_parse_command() -> buf_comit_can_dest() 中写入
 */
struct buf_can_tx
{
    FDCAN_TxHeaderTypeDef header[BUF_CAN_TXQUEUE_LEN];   /**< 帧头缓冲 */
    uint8_t  data[BUF_CAN_TXQUEUE_LEN][CAN_MAX_DATALEN]; /**< 帧数据缓冲 */
    uint16_t head;                                       /**< 写指针 */
    uint16_t send;                                       /**< 已提交待发送指针 */
    uint16_t tail;                                       /**< 读（已发送）指针 */
    uint8_t  full;                                       /**< 队列满标志，tail 前移时清除 */
};

extern volatile struct buf_cdc_tx buf_cdc_tx;
extern volatile struct buf_cdc_rx buf_cdc_rx;

/**
 * @brief 初始化各缓冲
 */
void buf_init();

/**
 * @brief 缓冲处理主函数（主循环周期调用，约每毫秒 100 次）
 * @param[in] tick_now 当前 1 µs 时基
 */
void buf_process(uint32_t tick_now);

/**
 * @brief 追加数据到 CDC 发送缓冲
 * @param[in] buf 数据指针
 * @param[in] len 数据长度
 */
void buf_enqueue_cdc(char* buf, uint16_t len);

/**
 * @brief 获取 CDC 发送缓冲的写入起点指针
 * @return 写入起点指针；缓冲不足以容纳一帧时返回 NULL
 */
uint8_t *buf_get_cdc_dest();

/**
 * @brief 提交已写入 CDC 发送缓冲的字节数
 * @param[in] len 新增字节数
 */
void buf_comit_cdc_dest(uint32_t len);

/**
 * @brief 获取 CAN 发送帧头缓冲的写入位置
 * @return 帧头指针；队列满时返回 NULL
 */
FDCAN_TxHeaderTypeDef *buf_get_can_dest_header();

/**
 * @brief 获取 CAN 发送帧数据缓冲的写入位置
 * @return 数据指针；队列满时返回 NULL
 */
uint8_t *buf_get_can_dest_data();

/**
 * @brief 提交当前 CAN 发送槽（前移 head 指针）
 * @return FBK_Success 成功；FBK_TxBufferFull 队列已满；其它为发送不允许
 */
eFeedback buf_comit_can_dest();

/**
 * @brief 清空 CAN 发送缓冲
 */
void buf_clear_can_buffer();

/**
 * @brief 把 Tx 回显标记发送给主机
 * @param[in] tx_event FDCAN Tx 事件（含发送时使用的 MessageMarker）
 */
void buf_store_tx_echo(FDCAN_TxEventFifoTypeDef* tx_event);

/**
 * @brief 把收到的 CAN 帧转成 SLCAN ASCII 并加入 CDC 发送缓冲
 * @param[in] frame_header FDCAN 接收描述符
 * @param[in] frame_data 接收到的数据字节（64 字节缓冲区）
 */
void buf_store_rx_packet(FDCAN_RxHeaderTypeDef *frame_header, uint8_t *frame_data);


