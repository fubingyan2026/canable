/**
 * @file control.h
 * @brief SETUP 厂商请求处理模块对外接口
 */

/*
    The MIT License
    USB GS 类（Geschwister Schneider）的实现
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once

#include "buffer.h"

/**
 * @brief 初始化设备信息（默认标志、版本号、能力描述、板信息）
 */
void control_init();

/**
 * @brief 周期上报总线错误
 * @param[in] tick_now 当前 1 µs 时基
 * @details 由主循环周期调用
 */
void control_process(uint32_t tick_now);

/**
 * @brief 向主机上报总线负载百分比
 * @param[in] busload_percent 总线负载百分比
 */
void control_report_busload(uint8_t busload_percent);

/**
 * @brief 向主机发送调试字符串
 * @param[in] message 调试消息
 * @return true 已入队；false 未启用调试上报或缓冲溢出
 */
bool control_send_debug_mesg(const char* message);

/**
 * @brief 处理 SETUP 厂商请求第一阶段（IN/OUT 分发）
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @return true 已处理；false 出错（置 ELM_LastError）
 */
bool control_setup_request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req);

/**
 * @brief 处理 SETUP 厂商请求第二阶段（OUT 数据）
 * @param[in] pdev USB 设备句柄
 */
void control_setup_OUT_data(USBD_HandleTypeDef* pdev);
