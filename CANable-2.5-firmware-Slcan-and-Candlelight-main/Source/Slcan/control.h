/**
 * @file control.h
 * @brief Slcan 命令解析与控制模块对外接口
 */

/*
    The MIT License
    Copyright (c) 2025 ElmueSoft / Nakanishi Kiyomaro / Normadotcom
    https://netcult.ch/elmue/CANable Firmware Update
*/

#pragma once

/**
 * @brief 初始化用户标志（Slcan 默认值）
 */
void control_init();

/**
 * @brief 解析并执行一条 SLCAN 命令
 * @param[in] buf 命令字符串（不含结尾 '\r'）
 * @param[in] len 命令长度
 */
void control_parse_command (char *buf, int len);

/**
 * @brief 周期上报总线错误（主循环周期调用）
 * @param[in] tick_now 当前 1 µs 时基
 */
void control_process(uint32_t tick_now);

/**
 * @brief 向主机发送总线负载百分比
 * @param[in] busload_percent 总线负载百分比
 */
void control_report_busload(uint8_t busload_percent);

/**
 * @brief 向主机发送调试字符串
 * @param[in] message 调试消息
 * @return true 已发送；false 调试上报未启用
 */
bool control_send_debug_mesg(const char* message);


