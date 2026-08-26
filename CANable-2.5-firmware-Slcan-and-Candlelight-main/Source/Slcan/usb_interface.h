/**
 * @file usb_interface.h
 * @brief CDC 接口（虚拟串口）回调与发送接口
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Nakanishi Kiyomaro / Normadotcom
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once

#include "usb_class.h"

/** @brief CDC 接口回调集（由 usb_class.c 的类回调调用） */
extern USBD_CDC_ItfTypeDef USBD_InterfaceCallbacks;

/**
 * @brief 通过 CDC 向主机发送数据
 * @param[in] Buf 数据指针
 * @param[in] Len 数据长度
 * @return USBD_OK 成功；USBD_BUSY 上一次传输未完成
 */
uint8_t CDC_Transmit_FS(uint8_t* Buf, uint16_t Len);


