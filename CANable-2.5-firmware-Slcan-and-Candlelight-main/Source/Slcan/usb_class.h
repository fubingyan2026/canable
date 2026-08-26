/**
  ******************************************************************************
  * @file    usbd_cdc.h
  * @author  MCD Application Team
  * @brief   header file for the usbd_cdc.c file.
  ******************************************************************************
  * @attention
  *
  * <h2><center>&copy; Copyright (c) 2015 STMicroelectronics.
  * All rights reserved.</center></h2>
  *
  * This software component is licensed by ST under Ultimate Liberty license
  * SLA0044, the "License"; You may not use this file except in compliance with
  * the License. You may obtain a copy of the License at:
  *                      www.st.com/SLA0044
  *
  ******************************************************************************
*/

#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#include  "usb_ioreq.h"

/**
 * @brief 目标设备是否为全速 USB
 * @details 置 1：只编译全速 USB 代码（高速/其它速率描述符与分支不编译），
 *          STM32G431 无高速 PHY，仅支持全速，默认即 1；
 *          置 0：同时编译高速与其它速率代码（需处理器带高速 PHY）。
 *          可在编译选项或 settings.h 中用该宏覆盖此默认值
 */
#ifndef USB_DEVICE_FULL_SPEED
    #define USB_DEVICE_FULL_SPEED 1U
#endif

/** @brief 数据 IN 端点（EP1） */
#define CDC_IN_EP                                   0x81U  /* EP1 for data IN */
/** @brief 数据 OUT 端点（EP1） */
#define CDC_OUT_EP                                  0x01U  /* EP1 for data OUT */
/** @brief 命令端点（EP2，CDC 命令） */
#define CDC_CMD_EP                                  0x82U  /* EP2 for CDC commands */

#ifndef CDC_HS_BINTERVAL
    #define CDC_HS_BINTERVAL                        0x10U
#endif

#ifndef CDC_FS_BINTERVAL
    #define CDC_FS_BINTERVAL                        0x10U
#endif

// CDC 端点参数：可根据所需波特率与性能微调。
// EMZ 本参数未使用，与 FS 相同。端点 IN & OUT 包大小
#define CDC_DATA_HS_MAX_PACKET_SIZE                 CDC_DATA_FS_MAX_PACKET_SIZE
/** @brief 数据端点 IN & OUT 包大小 */
#define CDC_DATA_FS_MAX_PACKET_SIZE                 64U  // Endpoint IN & OUT Packet size
/** @brief 命令端点包大小 */
#define CDC_CMD_PACKET_SIZE                         8U   // Control Endpoint Packet size

/** @brief 配置描述符总长度 */
#define USB_CDC_CONFIG_DESC_SIZ                     67U
#define CDC_DATA_HS_IN_PACKET_SIZE                  CDC_DATA_HS_MAX_PACKET_SIZE
#define CDC_DATA_HS_OUT_PACKET_SIZE                 CDC_DATA_HS_MAX_PACKET_SIZE

#define CDC_DATA_FS_IN_PACKET_SIZE                  CDC_DATA_FS_MAX_PACKET_SIZE
#define CDC_DATA_FS_OUT_PACKET_SIZE                 CDC_DATA_FS_MAX_PACKET_SIZE

/** @brief 封装命令请求代码 */
#define CDC_SEND_ENCAPSULATED_COMMAND               0x00U
/** @brief 获取封装响应请求代码 */
#define CDC_GET_ENCAPSULATED_RESPONSE               0x01U
#define CDC_SET_COMM_FEATURE                        0x02U
#define CDC_GET_COMM_FEATURE                        0x03U
#define CDC_CLEAR_COMM_FEATURE                      0x04U
/** @brief 设置线路编码请求代码 */
#define CDC_SET_LINE_CODING                         0x20U
/** @brief 获取线路编码请求代码 */
#define CDC_GET_LINE_CODING                         0x21U
/** @brief 设置控制线状态请求代码 */
#define CDC_SET_CONTROL_LINE_STATE                  0x22U
/** @brief 发送中止（Break）请求代码 */
#define CDC_SEND_BREAK                              0x23U

/**
 * @brief CDC 线路编码参数（串口参数）
 */
typedef struct
{
  uint32_t bitrate; /**< 波特率（bit/s） */
  uint8_t  format; /**< 停止位格式 */
  uint8_t  paritytype; /**< 校验类型 */
  uint8_t  datatype; /**< 数据位宽度 */
} USBD_CDC_LineCodingTypeDef;

/**
 * @brief CDC 接口回调集（由用户应用实现并注册）
 */
typedef struct _USBD_CDC_Itf
{
  int8_t (* Init)(void); /**< 初始化回调 */
  int8_t (* DeInit)(void); /**< 反初始化回调 */
  int8_t (* Control)(uint8_t cmd, uint8_t *pbuf, uint16_t length); /**< 类请求控制回调 */
  int8_t (* Receive)(uint8_t *Buf, uint32_t *Len); /**< 数据接收回调 */

} USBD_CDC_ItfTypeDef;

/**
 * @brief CDC 类内部句柄
 */
typedef struct
{
  uint32_t data[CDC_DATA_HS_MAX_PACKET_SIZE / 4U];      /**< 端点 0 数据区（强制 32 位对齐） */
  uint8_t  CmdOpCode; /**< 命令操作码 */
  uint8_t  CmdLength; /**< 命令数据长度 */
  uint8_t  *RxBuffer; /**< 接收缓冲指针 */
  uint8_t  *TxBuffer; /**< 发送缓冲指针 */
  uint32_t RxLength; /**< 接收数据长度 */
  uint32_t TxLength; /**< 发送数据长度 */

  __IO uint32_t TxState; /**< 发送状态（0 空闲 / 1 传输中） */
  __IO uint32_t RxState; /**< 接收状态 */
}
USBD_CDC_HandleTypeDef;

/**
 * @brief 设置发送缓冲与长度
 * @param[in] pdev USB 设备句柄
 * @param[in] pbuff 发送缓冲
 * @param[in] length 数据长度
 * @return USB 状态
 */
uint8_t  USBD_CDC_SetTxBuffer(USBD_HandleTypeDef *pdev, uint8_t *pbuff, uint16_t length);

/**
 * @brief 设置接收缓冲
 * @param[in] pdev USB 设备句柄
 * @param[in] pbuff 接收缓冲
 * @return USB 状态
 */
uint8_t  USBD_CDC_SetRxBuffer(USBD_HandleTypeDef *pdev, uint8_t *pbuff);

/**
 * @brief 准备接收一个数据包
 * @param[in] pdev USB 设备句柄
 * @return USB 状态
 */
uint8_t  USBD_CDC_ReceivePacket(USBD_HandleTypeDef *pdev);

/**
 * @brief 在 IN 端点发送一个数据包
 * @param[in] pdev USB 设备句柄
 * @return USB 状态（传输中返回 USBD_BUSY）
 */
uint8_t  USBD_CDC_TransmitPacket(USBD_HandleTypeDef *pdev);

/**
 * @brief 处理 SETUP 阶段请求（Slcan 未使用，恒返回 false）
 * @param[in] hpcd PCD 句柄
 * @return false
 */
bool USBD_SetupStageRequest(PCD_HandleTypeDef *hpcd);

/**
 * @brief 配置所有端点的 PMA（包内存区）
 * @param[in] pdev USB 设备句柄
 */
void USBD_ConfigureEndpoints(USBD_HandleTypeDef *pdev);

#ifdef __cplusplus
}
#endif

