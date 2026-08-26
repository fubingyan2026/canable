/**
 * @file buffer.h
 * @brief CAN 帧缓冲管理：双向环形链表、帧对象空闲池与 USB 缓冲区句柄
 */

/*
 * Copyright (c) 2010 Isilon Systems, Inc.
 * Copyright (c) 2010 iX Systems, Inc.
 * Copyright (c) 2010 Panasas, Inc.
 * Copyright (c) 2013-2016 Mellanox Technologies, Ltd.
 * All rights reserved.
 *
 * FreeBSD License
 */

#pragma once
#include "candlelight_def.h"
#include "error.h"
#include "system.h"
#include "usb_def.h"

// ----------------------------------------------------------------------------------------

/**
 * @brief 由结构体成员指针反推出宿主结构体起始地址
 * @param ptr 成员指针
 * @param type 宿主结构体类型
 * @param member 成员名
 * @return 宿主结构体指针
 * @note 内核经典宏，__typeof 为 GCC 扩展
 */
#define container_of(ptr, type, member)              \
    ({                                               \
        __typeof(((type*)0)->member)* _p = (ptr);    \
        (type*)((char*)_p - offsetof(type, member)); \
    })

/** @brief 由链表结点推导宿主结构体指针 */
#define list_entry(ptr, type, field) container_of(ptr, type, field)
/** @brief 取链表头结点（转成宿主结构体指针） */
#define list_get_head(ptr, type, member) list_entry((ptr)->next, type, member)
/** @brief 取链表头结点，空表返回 NULL */
#define list_get_head_or_null(ptr, type, member) (!list_is_empty(ptr) ? list_get_head(ptr, type, member) : NULL)

/**
 * @brief 双向链表结点
 * @details 用作环形缓冲：头结点 next/prev 指向自身即空表
 */
typedef struct list_item {
    struct list_item* next; /**< 后继 */
    struct list_item* prev; /**< 前驱 */
} list_item;

// --------------

/**
 * @brief 置空链表
 * @param[out] head 头结点（其 next/prev 指向自身）
 */
static inline void list_init(list_item* head)
{
    head->next = head;
    head->prev = head;
}

/**
 * @brief 判断链表是否为空
 * @param[in] head 头结点
 * @return true 为空
 */
static inline bool list_is_empty(const list_item* head)
{
    return head->next == head;
}

// static inline bool list_is_full(const list_item *head)
// {
//     链表永不会满：结点只在"空闲池 <-> 工作链表"间流转，
//     初始化后空闲池满、工作链表空。
// }

/**
 * @brief 统计当前链表结点数（调试用）
 * @param[in] head 头结点
 * @return 结点数，范围 0 ... CAN_QUEUE_SIZE / HOST_QUEUE_SIZE
 */
static inline int count_free_entries(const list_item* head)
{
    list_item* item = head->next;
    for (int i = 0; true; i++) {
        if (item == head) // 绕回表头即数完一圈
            return i;

        item = item->next;
    }
}

/**
 * @brief 摘链：把 entry 的前驱与后继直接相连
 * @param[in] entry 要移除的结点
 */
static inline void list_remove(list_item* entry)
{
    entry->next->prev = entry->prev;
    entry->prev->next = entry->next;
}

/**
 * @brief 在 prev、next 之间插入 item（需改 4 个指针）
 * @param[in] item 待插入结点
 * @param[in] prev 前驱结点
 * @param[in] next 后继结点
 */
static inline void list_insert(list_item* item, list_item* prev, list_item* next)
{
    next->prev = item;
    item->next = next;
    item->prev = prev;
    prev->next = item;
}

/**
 * @brief 头插
 * @param[in] item 待插入结点
 * @param[in] head 头结点
 */
static inline void list_add_head(list_item* item, list_item* head)
{
    list_insert(item, head, head->next);
}

/**
 * @brief 头插（关中断版，供中断上下文使用）
 * @param[in] entry 待插入结点
 * @param[in] head 头结点
 */
static inline void list_add_head_locked(list_item* entry, list_item* head)
{
    system_disable_irq();
    list_add_head(entry, head);
    system_enable_irq();
}

/**
 * @brief 尾插
 * @param[in] item 待插入结点
 * @param[in] head 头结点
 */
static inline void list_add_tail(list_item* item, list_item* head)
{
    list_insert(item, head->prev, head);
}

/**
 * @brief 尾插（关中断版）
 * @param[in] entry 待插入结点
 * @param[in] head 头结点
 */
static inline void list_add_tail_locked(list_item* entry, list_item* head)
{
    system_disable_irq();
    list_add_tail(entry, head);
    system_enable_irq();
}

// ----------------------------------------------------------------------------------------

/**
 * @brief 缓冲池帧对象：链表结点 + 一帧数据
 * @note frame 按传统协议 kHostFrameLegacy 大小分配，足以容纳新 ElmueSoft 协议的任一帧结构
 */
typedef struct
{
    list_item list; /**< 链表结点 */
    kHostFrameLegacy frame; /**< 帧数据 */
} kHostFrameObject;

/**
 * @brief USB 缓冲区句柄：集中管理各链表与传输状态
 * @details 旧固件用指针指向环形缓冲，缓冲满时既不设错误也不发错误帧，
 *          结果设备"假死"甚至崩溃；这里改用两块固定缓冲区（ElmueSoft 修复）
 */
typedef struct
{
    /**< 端点 0 数据缓冲区（64 字节），存放 SETUP 请求 OUT 阶段的接收数据 */
    uint8_t __aligned(4) ep0_buf[USB_MAX_EP0_SIZE];

    /**< 正在向主机发送 IN 包 --> 忙，须等空闲再发下一个 */
    __IO bool TxBusy;
    /**< IN 传输结束后需补发零长度包（ZLP） */
    __IO bool SendZLP;

    // 4 条链表：两个空闲池 + 两个工作 FIFO
    list_item list_can_pool; /**< CAN 方向空闲池（USB->CAN 用） */
    list_item list_host_pool; /**< 主机方向空闲池（CAN->USB 用） */
    list_item list_to_can; /**< 待发往 CAN 总线的帧（USB --> CAN） */
    list_item list_to_host; /**< 待发往主机的帧（CAN --> USB） */

    /**< 存放待发往主机的 IN 数据 */
    uint8_t to_host_buf[sizeof(kHostFrameLegacy)];
    /**< 存放主机发来的 OUT 数据 */
    uint8_t from_host_buf[sizeof(kHostFrameLegacy)];

    /**< 带 OUT 数据的 SETUP 分两阶段执行，此变量把请求从第一阶段传给第二阶段 */
    USBD_SetupReqTypedef last_setup_request;
} __attribute__((aligned(4))) USB_BufHandleTypeDef;

// ----------------------------------------------------------------------------------------

/**
 * @brief 初始化各链表（把全部帧对象放入两个空闲池）
 */
void buf_init();

/**
 * @brief 主循环周期调用：USB<->CAN 收发转发 + 缓冲溢出上报
 * @param[in] tick_now 当前 1 µs 时基
 */
void buf_process(uint32_t tick_now);

/**
 * @brief 清空 CAN 方向（USB->CAN）缓冲
 */
void buf_clear_can_buffer();

/**
 * @brief 生成错误帧挂入 list_to_host
 */
void buf_store_error();

/**
 * @brief 把收到的 CAN 帧保存进 list_to_host
 * @param[in] rx_header FDCAN 接收描述符
 * @param[in] frame_data 接收到的数据字节（64 字节缓冲区）
 */
void buf_store_rx_packet(FDCAN_RxHeaderTypeDef* rx_header, uint8_t* frame_data);

/**
 * @brief 把 Tx 回显标记保存进 list_to_host
 * @param[in] tx_event FDCAN Tx 事件（含发送时使用的 MessageMarker）
 */
void buf_store_tx_echo(FDCAN_TxEventFifoTypeDef* tx_event);

/**
 * @brief 关中断地从链表取一个帧对象并移除
 * @param[in] list_head 目标链表头
 * @return 帧对象指针；链表为空时返回 NULL
 */
kHostFrameObject* buf_get_frame_locked(list_item* list_head);
