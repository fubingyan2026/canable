  /*******************************************************************************
  * @file    usb_interface.c
  * @author  MCD Application Team
  * @brief   This file provides the CDC interface (virtual COM port).
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2015 STMicroelectronics.
  * All rights reserved.
  *
  * This software component is licensed by ST under Ultimate Liberty license
  * SLA0044, the "License"; You may not use this file except in compliance with
  * the License. You may obtain a copy of the License at: www.st.com/SLA0044
  *
  ******************************************************************************/

#include "usb_interface.h"
#include "buffer.h"
#include "error.h"
#include "system.h"

extern USBD_HandleTypeDef USB_Device;

static int8_t CDC_Init_FS(void);
static int8_t CDC_DeInit_FS(void);
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length);
static int8_t CDC_Receive_FS(uint8_t* pbuf, uint32_t *Len);

/** @brief CDC 接口回调集（注册到 USB 类驱动） */
USBD_CDC_ItfTypeDef USBD_InterfaceCallbacks =
{
    CDC_Init_FS,
    CDC_DeInit_FS,
    CDC_Control_FS,
    CDC_Receive_FS
};

/**
 * @brief 初始化 CDC 介质低层（全速 USB）
 * @return USB 状态
 * @details 把发送/接收缓冲分别指向 CDC 发送/接收环形缓冲的当前槽
 */
static int8_t CDC_Init_FS(void)
{
    USBD_CDC_SetTxBuffer(&USB_Device, (uint8_t *)buf_cdc_tx.data[buf_cdc_tx.tail], 0);
    USBD_CDC_SetRxBuffer(&USB_Device, (uint8_t *)buf_cdc_rx.data[buf_cdc_rx.head]);
    return (USBD_OK);
}

/**
 * @brief 反初始化 CDC 介质低层
 * @return USB 状态
 */
static int8_t CDC_DeInit_FS(void)
{
    return (USBD_OK);
}

/**
  * @brief  管理 CDC 类请求（线路编码等，Slcan 仅应答 GET_LINE_CODING）
  * @param  cmd: 命令码
  * @param  pbuf: 存放命令数据的缓冲（请求参数）
  * @param  length: 要发送的数据字节数
  * @retval 操作结果：USBD_OK 成功，否则 USBD_FAIL
  */
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t* pbuf, uint16_t length)
{
    switch (cmd)
    {
        case CDC_SEND_ENCAPSULATED_COMMAND:
            break;

        case CDC_GET_ENCAPSULATED_RESPONSE:
            break;

        case CDC_SET_COMM_FEATURE:
            break;

        case CDC_GET_COMM_FEATURE:
            break;

        case CDC_CLEAR_COMM_FEATURE:
            break;

  /*******************************************************************************/
  /* 线路编码结构                                                               */
  /*-----------------------------------------------------------------------------*/
  /* 偏移 | 字段        | 大小 | 值    | 说明                                   */
  /* 0    | dwDTERate   |  4  | 数值  | 数据终端速率（bit/s）                    */
  /* 4    | bCharFormat |  1  | 数值  | 停止位                                  */
  /*                                        0 - 1 个停止位                       */
  /*                                        1 - 1.5 个停止位                     */
  /*                                        2 - 2 个停止位                       */
  /* 5    | bParityType |  1  | 数值  | 校验                                   */
  /*                                        0 - 无                                */
  /*                                        1 - 奇校验                            */
  /*                                        2 - 偶校验                            */
  /*                                        3 - 标记                              */
  /*                                        4 - 空格                              */
  /* 6    | bDataBits   |  1  | 数值  | 数据位（5、6、7、8 或 16）                */
  /*******************************************************************************/
        case CDC_SET_LINE_CODING:
            break;

        case CDC_GET_LINE_CODING:
            // 应答固定为 115200/8/N/1（Slcan 不使用这些值，仅满足协议要求）
            pbuf[0] = (uint8_t)(115200);
            pbuf[1] = (uint8_t)(115200 >> 8);
            pbuf[2] = (uint8_t)(115200 >> 16);
            pbuf[3] = (uint8_t)(115200 >> 24);
            pbuf[4] = 0; // 停止位（1）
            pbuf[5] = 0; // 校验（无）
            pbuf[6] = 8; // 数据位（8）
            break;

        case CDC_SET_CONTROL_LINE_STATE:
            // 主机设置 DTR 或 RTS 线，此处无需处理
            break;

        case CDC_SEND_BREAK:
            break;
    }

    return (USBD_OK);
}

/**
  * @brief  通过 USB OUT 端点收到的数据经此函数交给 CDC 接口处理
  * @param  Buf: 收到的数据缓冲
  * @param  Len: 收到的数据字节数
  * @retval 操作结果：USBD_OK 成功，否则 USBD_FAIL
  * @note   本函数返回前会阻塞 OUT 端点接收；若在 CDC 传输完成前返回
  *         （如使用 DMA），可能导致上一批数据尚未发出又收到新数据
  */
static int8_t CDC_Receive_FS(uint8_t* Buf, uint32_t *Len)
{
    // 检查接收环形缓冲是否已满
    uint32_t new_head = (buf_cdc_rx.head + 1) % BUF_CDC_RX_NUM_BUFS;
    if (new_head == buf_cdc_rx.tail)
    {
        error_assert(APP_CanTxOverflow, false);

        // 仍在同一缓冲上监听，旧数据将被覆盖
        USBD_CDC_SetRxBuffer(&USB_Device, (uint8_t *)buf_cdc_rx.data[buf_cdc_rx.head]);
        USBD_CDC_ReceivePacket(&USB_Device);
        return HAL_ERROR;
    }
    else
    {
        // 保存数据长度并前移写指针
        buf_cdc_rx.msglen[buf_cdc_rx.head] = *Len;
        buf_cdc_rx.head = new_head;

        // 在下一个缓冲上监听，上一个缓冲由主循环处理
        USBD_CDC_SetRxBuffer(&USB_Device, (uint8_t *)buf_cdc_rx.data[buf_cdc_rx.head]);
        USBD_CDC_ReceivePacket(&USB_Device);
        return (USBD_OK);
    }
}

/**
 * @brief 通过 CDC 向主机发送数据
 * @param[in] Buf 数据指针
 * @param[in] Len 数据长度
 * @return USBD_OK 成功；USBD_BUSY 上一次传输未完成
 * @details 底层为 USBD_CDC_TransmitPacket()，发送期间返回 BUSY 供调用方重试
 */
uint8_t CDC_Transmit_FS(uint8_t* Buf, uint16_t Len)
{
    uint8_t result = USBD_OK;

    USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef*)USB_Device.pClassData;
    if (hcdc->TxState != 0)
        return USBD_BUSY;

    USBD_CDC_SetTxBuffer(&USB_Device, Buf, Len);
    result = USBD_CDC_TransmitPacket(&USB_Device);

    return result;
}

