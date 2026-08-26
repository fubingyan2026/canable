/**
 * @file usb_class.c
 * @brief WinUSB 类实现：描述符、类回调、端点 IN/OUT 传输与微软 OS 请求
 */

/*
    The MIT License
    USB GS 类（Geschwister Schneider）的实现
    Copyright (c) 2025 ElmueSoft / Hubert Denkmair
    https://netcult.ch/elmue/CANable Firmware Update
*/

#include "usb_class.h"
#include "buffer.h"
#include "can.h"
#include "control.h"
#include "dfu.h"
#include "system.h"
#include "usb_core.h"
#include "usb_ctrlreq.h"
#include "usb_lowlevel.h"
#include "utils.h"

/** @brief 批量 IN 端点（设备 -> 主机） */
#define GSUSB_ENDPOINT_IN 0x81
/** @brief 批量 OUT 端点（主机 -> 设备） */
#define GSUSB_ENDPOINT_OUT 0x02
/** @brief 端点 81 + 02 的最大包大小 */
#define CAN_DATA_MAX_PACKET_SIZE 64
/** @brief CAN 接口号 */
#define CANDLE_INTERFACE_NUMBER 0
/** @brief CAN 接口字符串描述符索引 */
#define CANDLE_INTERFACE_STR_INDEX 20
/** @brief 固件升级（DFU）接口号 */
#define DFU_INTERFACE_NUMBER 1
/** @brief DFU 接口字符串描述符索引 */
#define DFU_INTERFACE_STR_INDEX 0xE0
/** @brief 配置描述符总长度 */
#define USB_CAN_CONFIG_DESC_SIZE 50
/** @brief 微软 OS 厂商请求代码 */
#define USBD_MS_OS_VENDOR_CODE 0x20

extern USB_BufHandleTypeDef USB_BufHandle;
extern USBD_HandleTypeDef USB_Device;
extern uint8_t USBD_StrDesc[USBD_MAX_STR_DESC_SIZE];
extern eUserFlags USER_Flags;

/** @brief DFU 状态，用于响应 DFU_RequGetStatus 请求 */
kDfuStatus DFU_Status = { 0 };

// 各静态回调的前向声明（实现见下文）
static uint8_t USBD_GS_Init(USBD_HandleTypeDef* pdev, uint8_t cfgidx);
static uint8_t USBD_GS_DeInit(USBD_HandleTypeDef* pdev, uint8_t cfgidx);
static uint8_t USBD_GS_Setup(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req);
static uint8_t USBD_GS_DataIn(USBD_HandleTypeDef* pdev, uint8_t epnum);
static uint8_t USBD_GS_DataOut(USBD_HandleTypeDef* pdev, uint8_t epnum);
static uint8_t USBD_GS_EP0_RxReady(USBD_HandleTypeDef* pdev);
static uint8_t* USBD_GS_GetFSConfigDesc(uint16_t* length);
static uint8_t* USBD_GS_GetUserStringDescr(USBD_HandleTypeDef* pdev, uint8_t index, uint16_t* length);
static void USBD_GS_Vendor_Request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req);
static bool USBD_GS_DFU_Request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req);
static bool USBD_GS_CustomRequest(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req);
/*
// 全速 USB 设备不使用
static uint8_t  *USBD_GS_GetHSCfgDesc(uint16_t *length);
static uint8_t  *USBD_GS_GetOtherSpeedCfgDesc(uint16_t *length);
static uint8_t  *USBD_GS_GetDeviceQualifierDescriptor(uint16_t *length);
*/

/**
 * @brief WinUSB 类回调结构体
 * @details 这些函数均由 usb_core 和 usb_lowlevel 从 PCD_EP_ISR_Handler() 中断调用
 */
USBD_ClassTypeDef USBD_ClassCallbacks = {
    .Init = USBD_GS_Init,
    .DeInit = USBD_GS_DeInit,
    .Setup = USBD_GS_Setup,
    .EP0_RxReady = USBD_GS_EP0_RxReady,
    .DataIn = USBD_GS_DataIn,
    .DataOut = USBD_GS_DataOut,
    .SOF = NULL,
    .GetHSConfigDescriptor = NULL, // 全速 USB 设备不使用
    .GetFSConfigDescriptor = USBD_GS_GetFSConfigDesc,
    .GetOtherSpeedConfigDescriptor = NULL, // 全速 USB 设备不使用
    .GetDeviceQualifierDescriptor = NULL, // 全速 USB 设备不使用
    .GetUsrStrDescriptor = USBD_GS_GetUserStringDescr,
};

/**
 * @brief Candlelight 设备描述符
 * @details VID 0x1D50（OpenMoko）/ PID 0x606F（CANable Candlelight），bcdDevice 为固件版本
 */
__ALIGN_BEGIN uint8_t USBD_DeviceDesc[USB_LEN_DEV_DESC] __ALIGN_END = {
    0x12, // bLength：设备描述符长度 18
    USB_DESC_TYPE_DEVICE, // bDescriptorType = 设备描述符
    0x00, // bcdUSB 版本低字节
    0x02, // bcdUSB 版本 = 2.0
    0x00, // bDeviceClass = 类别在接口描述符中定义
    0x00, // bDeviceSubClass
    0x00, // bDeviceProtocol
    USB_MAX_EP0_SIZE, // bMaxPacketSize = 64 字节
    LOBYTE(0x1D50), // idVendor  厂商 ID OpenMoko
    HIBYTE(0x1D50), // idVendor  厂商 ID OpenMoko
    LOBYTE(0x606F), // idProduct 产品 ID CANable Candlelight
    HIBYTE(0x606F), // idProduct 产品 ID CANable Candlelight
    LOBYTE(FIRMWARE_VERSION_BCD >> 8), // bcdDevice 固件版本，见 settings.h
    HIBYTE(FIRMWARE_VERSION_BCD >> 8), // bcdDevice 固件版本，见 settings.h
    USBD_IDX_MFC_STR, // 厂商字符串描述符索引
    USBD_IDX_PRODUCT_STR, // 产品字符串描述符索引
    USBD_IDX_SERIAL_STR, // 序列号字符串描述符索引
    USBD_MAX_NUM_CONFIGURATION // bNumConfigurations 配置数量
};

/**
 * @brief 配置描述符（含 CAN 接口 + DFU 接口，共 50 字节）
 */
__ALIGN_BEGIN uint8_t USBD_ConfigDescr[USB_CAN_CONFIG_DESC_SIZE] __ALIGN_END = {
    // 配置描述符
    0x09, // bLength
    USB_DESC_TYPE_CONFIGURATION, // bDescriptorType
    USB_CAN_CONFIG_DESC_SIZE, // wTotalLength 总长度
    0x00,
    0x02, // bNumInterfaces 接口数量（CAN + DFU）
    0x01, // bConfigurationValue
    USBD_IDX_CONFIG_STR, // iConfiguration
    0x80, // bmAttributes: 总线供电
    0x4B, // MaxPower 150 mA
    //-----------------------------
    // GS_USB 接口描述符（CAN 接口）
    0x09, // bLength
    USB_DESC_TYPE_INTERFACE, // bDescriptorType
    CANDLE_INTERFACE_NUMBER, // bInterfaceNumber = 0
    0x00, // bAlternateSetting
    0x02, // bNumEndpoints（2 个端点）
    0xFF, // bInterfaceClass:    厂商自定义
    0xFF, // bInterfaceSubClass: 厂商自定义
    0xFF, // bInterfaceProtocol: 厂商自定义
    CANDLE_INTERFACE_STR_INDEX, // iInterface
    //-----------------------------
    // EP1 描述符（IN）
    0x07, // bLength
    USB_DESC_TYPE_ENDPOINT, // bDescriptorType
    GSUSB_ENDPOINT_IN, // bEndpointAddress  0x81
    0x02, // bmAttributes: 批量传输
    LOBYTE(CAN_DATA_MAX_PACKET_SIZE), // wMaxPacketSize
    HIBYTE(CAN_DATA_MAX_PACKET_SIZE),
    0x00, // bInterval
    //-----------------------------
    // EP2 描述符（OUT）
    0x07, // bLength
    USB_DESC_TYPE_ENDPOINT, // bDescriptorType
    GSUSB_ENDPOINT_OUT, // bEndpointAddress  0x02
    0x02, // bmAttributes: 批量传输
    LOBYTE(CAN_DATA_MAX_PACKET_SIZE), // wMaxPacketSize
    HIBYTE(CAN_DATA_MAX_PACKET_SIZE),
    0x00, // bInterval
    //--------------------------
    // DFU 接口描述符（固件升级）
    0x09, // bLength
    USB_DESC_TYPE_INTERFACE, // bDescriptorType
    DFU_INTERFACE_NUMBER, // bInterfaceNumber = 1
    0x00, // bAlternateSetting
    0x00, // bNumEndpoints（无端点，用控制传输）
    0xFE, // bInterfaceClass: 厂商自定义（DFU 类）
    0x01, // bInterfaceSubClass
    0x01, // bInterfaceProtocol: Runtime（运行）模式
    DFU_INTERFACE_STR_INDEX, // iInterface
    //---------------------------
    // DFU 功能描述符
    0x09, // bLength
    0x21, // bDescriptorType: DFU FUNCTIONAL
    0x0B, // bmAttributes: 支持 detach、upload、download
    0xFF,
    0x00, // wDetachTimeOut
    0x00,
    0x08, // wTransferSize
    0x1a,
    0x01, // bcdDFUVersion: 1.1a
};

/**
 * @brief 微软兼容 ID 特性描述符（Windows 自动安装 WinUSB 驱动用）
 * @details 为 CAN（接口 0）与 DFU（接口 1）两个接口声明兼容 ID "WINUSB"
 */
__ALIGN_BEGIN uint8_t USBD_MicrosoftFeatureDescr[] __ALIGN_END = {
    0x40, 0x00, 0x00, 0x00, // 长度
    0x00, 0x01, // 版本 1.0
    0x04, 0x00, // 描述符索引（0x0004）
    0x02, // 段的数量（2 个接口）
    0x00, 0x00, 0x00, 0x00, // 保留
    0x00, 0x00, 0x00,
    0x00, // 接口号 0 Candlelight
    0x01, // 保留 - 1 字节
    0x57, 0x49, 0x4E, 0x55, // 兼容 ID（"WINUSB\0\0"）- 8 字节
    0x53, 0x42, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, // 子兼容 ID - 8 字节
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, // 保留 - 6 字节
    0x00, 0x00,
    0x01, // 接口号 1 固件升级
    0x01, // 保留 - 1 字节
    0x57, 0x49, 0x4E, 0x55, // 兼容 ID（"WINUSB\0\0"）- 8 字节
    0x53, 0x42, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, // 子兼容 ID - 8 字节
    0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, // 保留 - 6 字节
    0x00, 0x00
};

/**
 * @brief 微软扩展属性描述符（为两个接口提供 DeviceInterfaceGUID）
 */
__ALIGN_BEGIN uint8_t USBD_MicrosoftExtPropertyDescr[] __ALIGN_END = {
    0x92, 0x00, 0x00, 0x00, // 长度
    0x00, 0x01, // 版本 1.0
    0x05, 0x00, // 描述符索引（0x0005）
    0x01, 0x00, // 段的数量（1 个属性）
    0x88, 0x00, 0x00, 0x00, // 属性段大小
    0x07, 0x00, 0x00, 0x00, // 属性数据类型 7: Unicode REG_MULTI_SZ
    0x2a, 0x00, // 属性名长度

    0x44, 0x00, 0x65, 0x00, // 属性名 "DeviceInterfaceGUIDs"（UTF-16）
    0x76, 0x00, 0x69, 0x00,
    0x63, 0x00, 0x65, 0x00,
    0x49, 0x00, 0x6e, 0x00,
    0x74, 0x00, 0x65, 0x00,
    0x72, 0x00, 0x66, 0x00,
    0x61, 0x00, 0x63, 0x00,
    0x65, 0x00, 0x47, 0x00,
    0x55, 0x00, 0x49, 0x00,
    0x44, 0x00, 0x73, 0x00,
    0x00, 0x00,

    0x50, 0x00, 0x00, 0x00, // 属性数据长度

    0x7b, 0x00, 0x63, 0x00, // 属性值："{c15b4308-04d3-11e6-b3ea-6057189e6443}\0\0" == 唯一的 Candlelight GUID
    0x31, 0x00, // <----- 偏移 70 处的这个 '1' 会在 DFU 接口时被替换为 '2'
    0x35, 0x00,
    0x62, 0x00, 0x34, 0x00,
    0x33, 0x00, 0x30, 0x00,
    0x38, 0x00, 0x2d, 0x00,
    0x30, 0x00, 0x34, 0x00,
    0x64, 0x00, 0x33, 0x00,
    0x2d, 0x00, 0x31, 0x00,
    0x31, 0x00, 0x65, 0x00,
    0x36, 0x00, 0x2d, 0x00,
    0x62, 0x00, 0x33, 0x00,
    0x65, 0x00, 0x61, 0x00,
    0x2d, 0x00, 0x36, 0x00,
    0x30, 0x00, 0x35, 0x00,
    0x37, 0x00, 0x31, 0x00,
    0x38, 0x00, 0x39, 0x00,
    0x65, 0x00, 0x36, 0x00,
    0x34, 0x00, 0x34, 0x00,
    0x33, 0x00, 0x7d, 0x00,
    0x00, 0x00, 0x00, 0x00
};

// =========================================================================================================

/**
 * @brief 配置所有端点的 PMA（包内存区）
 * @param[in] pdev USB 设备句柄
 * @details 在 USBD_LL_Init() 初始化期间调用
 */
void USBD_ConfigureEndpoints(USBD_HandleTypeDef* pdev)
{
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x00, PCD_SNG_BUF, 0x18); // EP 0 OUT（最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x80, PCD_SNG_BUF, 0x58); // EP 0 IN （最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x81, PCD_SNG_BUF, 0xd8); // EP 1 IN （最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x02, PCD_DBL_BUF, 0x015801d8); // EP 2 OUT（最大包大小 = 64 字节，双缓冲地址 158 + 1D8）
}

// =========================================================================================================

/**
 * @brief 中断回调：初始化 GS 类
 * @param[in] pdev USB 设备句柄
 * @param[in] cfgidx 配置索引
 * @return USB 状态
 * @details 打开批量端点 81/02、初始化 TxBusy 与 DFU 状态、准备接收首个 CAN 帧
 */
static uint8_t USBD_GS_Init(USBD_HandleTypeDef* pdev, uint8_t cfgidx)
{
    pdev->pClassData = &USB_BufHandle; // 保存缓冲区句柄，供其他回调使用

    // 打开批量端点 81（IN）和 02（OUT）
    USBD_LL_OpenEP(pdev, GSUSB_ENDPOINT_IN, USBD_EP_TYPE_BULK, CAN_DATA_MAX_PACKET_SIZE);
    USBD_LL_OpenEP(pdev, GSUSB_ENDPOINT_OUT, USBD_EP_TYPE_BULK, CAN_DATA_MAX_PACKET_SIZE);

    USB_BufHandle.TxBusy = false; // 初始化为非忙碌

    // 初始化对 DFU_RequGetStatus 请求的默认响应
    DFU_Status.Status = DfuStatus_OK; // 无错误
    DFU_Status.State = DfuState_AppIdle; // 处于应用模式且空闲
    DFU_Status.StringIdx = 0xFF; // 无字符串描述符

    // 准备在 OUT 端点接收来自主机的第一个 CAN 帧
    return USBD_LL_PrepareReceive(pdev, GSUSB_ENDPOINT_OUT, USB_BufHandle.from_host_buf, sizeof(USB_BufHandle.from_host_buf));
}

/**
 * @brief 中断回调：反初始化 GS 类
 * @param[in] pdev USB 设备句柄
 * @param[in] cfgidx 配置索引
 * @return USB 状态
 * @details 关闭批量端点 81/02
 */
static uint8_t USBD_GS_DeInit(USBD_HandleTypeDef* pdev, uint8_t cfgidx)
{
    USBD_LL_CloseEP(pdev, GSUSB_ENDPOINT_IN);
    USBD_LL_CloseEP(pdev, GSUSB_ENDPOINT_OUT);
    return USBD_OK;
}

/**
 * @brief 中断回调：收到 SETUP 请求
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @return USB 状态（调用方忽略）
 * @details 由 usb_ctrlreq.c 的 USBD_StdDevReq() 调用；类/厂商请求转交
 *          USBD_GS_Vendor_Request()，标准请求仅响应 GET_INTERFACE
 */
static uint8_t USBD_GS_Setup(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req)
{
    static uint8_t ifalt = 0; // GET_INTERFACE 的默认备用设置

    switch (req->bmRequest & USB_REQ_TYPE_MASK) {
    case USB_REQ_TYPE_CLASS: // 类请求（如 DFU）
    case USB_REQ_TYPE_VENDOR: // 厂商请求（GS/ELM 命令）
        USBD_GS_Vendor_Request(pdev, req);
        break;

    case USB_REQ_TYPE_STANDARD: // 标准请求
        switch (req->bRequest) {
        case USB_REQ_GET_INTERFACE:
            USBD_CtlSendData(pdev, &ifalt, 1);
            break;
        }
        break;
    }
    return USBD_OK; // 被忽略
}

/**
 * @brief 厂商 SETUP 请求第一阶段（分发到 DFU 或 CAN 控制）
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @details 从中断回调内部调用。请求目标为 DFU 接口时先按 DFU 请求处理，
 *          否则按 CAN 接口（接口 0）交给 control_setup_request()；
 *          两者都未处理则 stall 端点 0
 */
static void USBD_GS_Vendor_Request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req)
{
    // 如果请求目标是接口 1（DFU 接口），先尝试按 DFU 请求处理
    if ((req->bmRequest & USB_REQ_RECIPIENT_MASK) == USB_REQ_RECIPIENT_INTERFACE && (req->bmRequest & USB_REQ_TYPE_MASK) == USB_REQ_TYPE_CLASS && req->wIndex == DFU_INTERFACE_NUMBER) {
        if (USBD_GS_DFU_Request(pdev, req))
            return; // 成功
    }

    // 如果请求目标是接口 0（CAN 接口），交给 control_setup_request 处理
    if (req->wIndex == CANDLE_INTERFACE_NUMBER) {
        if (control_setup_request(pdev, req))
            return; // 成功
    }

    USBD_CtlError(pdev, 0); // 无法识别：中止（stall）端点 0
}

/**
 * @brief 中断回调：带 OUT 数据的 SETUP 请求第二阶段
 * @param[in] pdev USB 设备句柄
 * @return USB 状态（调用方忽略）
 * @details 由 usb_core.c 的 USBD_LL_DataOutStage() 调用，转交 control_setup_OUT_data()
 * @see control_setup_OUT_data()
 */
static uint8_t USBD_GS_EP0_RxReady(USBD_HandleTypeDef* pdev)
{
    control_setup_OUT_data(pdev); // 处理主机发来的 OUT 数据
    return USBD_OK; // 被忽略
}

/**
 * @brief DFU 接口请求处理（接口 1，固件升级）
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @return true 已处理
 * @details 支持 DFU_RequDetach（切到引导加载程序）与 DFU_RequGetStatus（返回状态）
 */
static bool USBD_GS_DFU_Request(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req)
{
    switch (req->bRequest) {
    case DFU_RequDetach:
        // 延迟 300 ms 进入 DFU 模式。若 BOOT0 已被禁用，须重新插拔 USB 触发硬件复位；
        // 通过状态 DfuSte_AppDetach 通知固件升级器当前无法自行进入 DFU 模式
        if (dfu_switch_to_bootloader() == FBK_ResetRequired)
            DFU_Status.State = DfuState_AppDetach; // 需要硬件复位
        return true;
    case DFU_RequGetStatus:
        USBD_CtlSendData(pdev, (uint8_t*)&DFU_Status, sizeof(DFU_Status));
        return true;
    default:
        return false;
    }
}

/**
 * @brief 中断回调：USB OUT 端点 02 收到数据（主机发来 CAN 帧）
 * @param[in] pdev USB 设备句柄
 * @param[in] epnum 端点号
 * @return USB 状态（调用方忽略）
 * @details 从 CAN 空闲池取帧对象存入数据并挂入 list_to_can；池空则立即上报
 *          APP_CanTxOverflow 让主机停止发送
 */
static uint8_t USBD_GS_DataOut(USBD_HandleTypeDef* pdev, uint8_t epnum)
{
    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)pdev->pClassData;

    // 从 CAN 空闲池取一个帧对象
    kHostFrameObject* pool_frame = buf_get_frame_locked(&hcan->list_can_pool);
    if (pool_frame) {
        // 复制主机数据并加入待发送到 CAN 总线的链表
        memcpy(&pool_frame->frame, hcan->from_host_buf, sizeof(hcan->from_host_buf));
        list_add_tail_locked(&pool_frame->list, &hcan->list_to_can);
    } else // CAN 缓冲溢出
    {
        // 缓冲溢出时立即通知主机，让主机停止发送更多报文并向用户显示错误
        error_assert(APP_CanTxOverflow, true);
    }

    // 把 from_host_buf 缓冲区交给 HAL 接收下一帧
    USBD_LL_PrepareReceive(pdev, GSUSB_ENDPOINT_OUT, hcan->from_host_buf, sizeof(hcan->from_host_buf));
    return USBD_OK; // 被忽略
}

/**
 * @brief 中断回调：返回全速配置描述符
 * @param[out] length 描述符长度
 * @return 配置描述符指针
 */
static uint8_t* USBD_GS_GetFSConfigDesc(uint16_t* length)
{
    *length = sizeof(USBD_ConfigDescr);
    return USBD_ConfigDescr;
}

/**
 * @brief 中断回调：按索引获取 Unicode 字符串描述符
 * @param[in] pdev USB 设备句柄
 * @param[in] index 字符串描述符索引
 * @param[out] length 字符串长度
 * @return 字符串描述符指针；无效索引返回 NULL 并 stall 端点 0
 * @details 接口名称是 Windows 安装驱动时显示的文本，须用易懂的名字
 */
uint8_t* USBD_GS_GetUserStringDescr(USBD_HandleTypeDef* pdev, uint8_t index, uint16_t* length)
{
    switch (index) {
    // 此名称很重要：Windows 在安装驱动时会显示它
    case CANDLE_INTERFACE_STR_INDEX:
        USBD_GetString((uint8_t*)"CAN FD Interface", USBD_StrDesc, length);
        return USBD_StrDesc;

    // 此名称很重要：Windows 在安装驱动时会显示它
    case DFU_INTERFACE_STR_INDEX:
        USBD_GetString((uint8_t*)"Firmware Update Interface", USBD_StrDesc, length);
        return USBD_StrDesc;

    case 0xEE: // 微软 OS 字符串描述符请求 --> "MSFT100" + 厂商代码
        USBD_GetString((uint8_t*)"MSFT100x", USBD_StrDesc, length);
        USBD_StrDesc[16] = USBD_MS_OS_VENDOR_CODE; // 把 'x' 替换为厂商代码
        return USBD_StrDesc;

    default:
        *length = 0;
        USBD_CtlError(pdev, 0); // 中止端点 0
        return 0;
    }
}

// =========================================================================================================

/**
 * @brief 处理 SETUP 阶段请求
 * @param[in] hpcd PCD（USB 外设控制器）句柄
 * @return true 已处理
 * @details 从中断处理程序 PCD_EP_ISR_Handler --> HAL_PCD_SetupStageCallback 调用
 */
bool USBD_SetupStageRequest(PCD_HandleTypeDef* hpcd)
{
    USBD_HandleTypeDef* pdev = (USBD_HandleTypeDef*)hpcd->pData;
    // 解析 SETUP 包
    USBD_ParseSetupRequest((USBD_SetupReqTypedef*)&pdev->request, (uint8_t*)hpcd->Setup);

    switch (pdev->request.bmRequest & USB_REQ_RECIPIENT_MASK) {
    case USB_REQ_RECIPIENT_DEVICE: // 设备请求
    case USB_REQ_RECIPIENT_INTERFACE: // 接口请求
        return USBD_GS_CustomRequest(pdev, &pdev->request);
    default:
        return false;
    }
}

/**
 * @brief 处理微软 OS SETUP 请求
 * @param[in] pdev USB 设备句柄
 * @param[in] req SETUP 请求
 * @return true 已处理
 * @details Windows 自动安装 WinUSB 驱动所必需。Windows 发送接口请求，
 *          但为兼容 WinUSB 测试工具，设备请求也以相同方式应答
 */
bool USBD_GS_CustomRequest(USBD_HandleTypeDef* pdev, USBD_SetupReqTypedef* req)
{
    if (req->bRequest != USBD_MS_OS_VENDOR_CODE || req->wValue > DFU_INTERFACE_NUMBER)
        return false;

    switch (req->wIndex) // wIndex = 请求的描述符类型
    {
    case 4: // 微软 OS 特性请求
        USBD_CtlSendData(pdev, USBD_MicrosoftFeatureDescr, MIN(sizeof(USBD_MicrosoftFeatureDescr), req->wLength));
        return true;

    case 5: // 微软 OS 扩展属性请求
        // 重要：若不给 DFU 接口（接口 1）返回 GUID，Windows 不会安装 WinUSB 驱动，
        // 固件升级器也就无法把 CANable 切换到 DFU 模式！
        // 接口 0（Candlelight）返回 GUID "{c15b4308-04d3-11e6-b3ea-6057189e6443}"
        // 接口 1（Firmware Update）返回 GUID "{c25b4308-04d3-11e6-b3ea-6057189e6443}"
        memcpy(USBD_StrDesc, USBD_MicrosoftExtPropertyDescr, sizeof(USBD_MicrosoftExtPropertyDescr));
        if (req->wValue == DFU_INTERFACE_NUMBER) // wValue = 0 --> Candlelight 接口，1 --> DFU 接口
            USBD_StrDesc[70] = '2'; // 把 GUID 中的 '1' 改成 '2'

        USBD_CtlSendData(pdev, USBD_StrDesc, MIN(sizeof(USBD_MicrosoftExtPropertyDescr), req->wLength));
        return true;
    }
    return false;
}

// ==================================== IN 传输 ==========================================

/**
 * @brief 在 IN 端点 81 上向主机发送一帧
 * @param[in] frame 帧指针（kHostFrameLegacy 或 kHeader）
 * @details 仅在 USBD_IsTxBusy() 返回 false 后由主循环调用。新协议按消息头
 *          长度只发有效字节；传统协议固定 80 字节（非 FD/无时间戳时缩减）。
 * @note USBD_LL_Transmit 不复制数据，故先 memcpy 到 to_host_buf 保证缓冲区
 *       在传输完成前保持不变
 */
void USBD_SendFrameToHost(void* frame)
{
    uint16_t len;
    if (USER_Flags & USR_ProtoElmue) // 新的 ElmueSoft 协议
    {
        // 新协议按实际数据量发送（例如 2 字节数据就只发 2 字节），
        // 所有消息共用同一 kHeader，无论 CAN 报文还是 ASCII 消息
        len = ((kHeader*)frame)->size; // 长度 = 消息头中的总大小
    } else // 传统 Geschwister Schneider 协议
    {
        // 传统协议时间戳放在固定 64 字节数据数组之后，FD 模式总是发 76/80 字节
        len = sizeof(kHostFrameLegacy); // 80 字节
        if (!can_using_FD())
            len -= 56; // 非 FD 则减去 FD 数据块
        if ((USER_Flags & USR_Timestamp) == 0)
            len -= 4; // 无时间戳则减去 4 字节
    }

    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)USB_Device.pClassData;
    hcan->TxBusy = true; // 标记发送忙碌
    hcan->SendZLP = len > 0 && (len % CAN_DATA_MAX_PACKET_SIZE) == 0; // 长度是最大包整数倍则需补 ZLP

    // 重要：USBD_LL_Transmit 不复制数据，HAL 需要指针指向一块在传输完成前
    // 保持不变的内存；数据超过 64 字节时会拆成多个 USB 包发送
    memcpy(hcan->to_host_buf, frame, len);

    // 总是返回 HAL_OK
    USBD_LL_Transmit(&USB_Device, GSUSB_ENDPOINT_IN, hcan->to_host_buf, len);
}

/**
 * @brief 中断回调：IN 端点 0x81 数据已发送给主机
 * @param[in] pdev USB 设备句柄
 * @param[in] epnum 端点号（0x01）
 * @return USB 状态
 * @details 发送长度恰为 64 字节（CAN_DATA_MAX_PACKET_SIZE）时需补发零长度包
 *          （ZLP）以标识传输结束，否则主机会继续等待数据（ElmueSoft 修复
 *          传统固件缺失的这段处理）
 */
static uint8_t USBD_GS_DataIn(USBD_HandleTypeDef* pdev, uint8_t epnum)
{
    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)pdev->pClassData;

    if (hcan->SendZLP) {
        hcan->SendZLP = false;

        // 发送 ZLP：当最后一个数据包恰为最大包大小时，主机无法判断是否还有
        // 后续数据，需用零长度包显式结束传输（否则主机将一直等待下一包）
        USBD_LL_Transmit(&USB_Device, GSUSB_ENDPOINT_IN, NULL, 0);
    } else {
        hcan->TxBusy = false; // 发送完成，清除忙碌标志
    }
    return USBD_OK;
}

/**
 * @brief 查询向主机（IN 端点 81）的传输是否仍在进行
 * @return true 表示传输进行中
 */
bool USBD_IsTxBusy()
{
    USB_BufHandleTypeDef* hcan = (USB_BufHandleTypeDef*)USB_Device.pClassData;
    return hcan->TxBusy;
}
