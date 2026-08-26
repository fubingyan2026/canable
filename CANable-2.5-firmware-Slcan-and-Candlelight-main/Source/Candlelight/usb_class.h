/**
 * @file usb_class.h
 * @brief WinUSB 类回调与端点传输对外接口
 */

/*
    The MIT License
    USB GS 类（Geschwister Schneider）的实现
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once

#include "usb_core.h"
#include "usb_def.h"

/**
 * @brief 在 IN 端点 81 向主机发送一帧
 * @param[in] frame 帧指针（kHostFrameLegacy 或 kHeader）
 * @note 仅在 USBD_IsTxBusy() 返回 false 后由主循环调用
 */
void USBD_SendFrameToHost(void* frame);

/**
 * @brief 查询向主机的 IN 传输是否仍在进行
 * @return true 表示 IN 传输进行中
 */
bool USBD_IsTxBusy();

/**
 * @brief 配置所有端点的 PMA（包内存区）
 * @param[in] pdev USB 设备句柄
 * @details 在 USBD_LL_Init() 初始化期间调用
 */
void USBD_ConfigureEndpoints(USBD_HandleTypeDef* pdev);

/**
 * @brief 处理 SETUP 阶段请求（含微软 OS 请求）
 * @param[in] hpcd PCD（USB 外设控制器）句柄
 * @return true 已处理
 */
bool USBD_SetupStageRequest(PCD_HandleTypeDef* hpcd);
