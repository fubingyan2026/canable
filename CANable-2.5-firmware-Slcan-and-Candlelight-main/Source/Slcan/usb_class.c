  /******************************************************************************
  * @file    usb_class.c
  * @author  MCD Application Team
  * @brief   This file provides the high layer firmware functions to manage the
  *          following functionalities of the USB CDC Class:
  *           - Initialization and Configuration of high and low layer
  *           - Enumeration as CDC Device (and enumeration for each implemented memory interface)
  *           - OUT/IN data transfer
  *           - Command IN transfer (class requests management)
  *           - Error management
  *
  *          ===================================================================
  *                                CDC Class Driver Description
  *          ===================================================================
  *           This driver manages the "Universal Serial Bus Class Definitions for Communications Devices
  *           Revision 1.2 November 16, 2007" and the sub-protocol specification of "Universal Serial Bus
  *           Communications Class Subclass Specification for PSTN Devices Revision 1.2 February 9, 2007"
  *           This driver implements the following aspects of the specification:
  *             - Device descriptor management
  *             - Configuration descriptor management
  *             - Enumeration as CDC device with 2 data endpoints (IN and OUT) and 1 command endpoint (IN)
  *             - Requests management (as described in section 6.2 in specification)
  *             - Abstract Control Model compliant
  *             - Union Functional collection (using 1 IN endpoint for control)
  *             - Data interface class
  *
  *           These aspects may be enriched or modified for a specific user application.
  *
  *            This driver doesn't implement the following aspects of the specification
  *            (but it is possible to manage these features with some modifications on this driver):
  *             - Any class-specific aspect relative to communication classes should be managed by user application.
  *             - All communication classes other than PSTN are not managed
  *
  *  @endverbatim
  *
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

/* BSPDependencies
- "stm32xxxxx_{eval}{discovery}{nucleo_144}.c"
- "stm32xxxxx_{eval}{discovery}_io.c"
EndBSPDependencies */


#include "usb_class.h"
#include "usb_ctrlreq.h"
#include "usb_interface.h"

static uint8_t  USBD_CDC_Init(USBD_HandleTypeDef *pdev,  uint8_t cfgidx);
static uint8_t  USBD_CDC_DeInit(USBD_HandleTypeDef *pdev, uint8_t cfgidx);
static uint8_t  USBD_CDC_Setup(USBD_HandleTypeDef *pdev,  USBD_SetupReqTypedef *req);
static uint8_t  USBD_CDC_DataIn(USBD_HandleTypeDef *pdev,  uint8_t epnum);
static uint8_t  USBD_CDC_DataOut(USBD_HandleTypeDef *pdev,  uint8_t epnum);
static uint8_t  USBD_CDC_EP0_RxReady(USBD_HandleTypeDef *pdev);
static uint8_t* USBD_CDC_GetFSCfgDesc(uint16_t *length);

#if !USB_DEVICE_FULL_SPEED
static uint8_t  *USBD_CDC_GetHSCfgDesc(uint16_t *length);
static uint8_t  *USBD_CDC_GetOtherSpeedCfgDesc(uint16_t *length);
static uint8_t  *USBD_CDC_GetDeviceQualifierDescriptor(uint16_t *length);
#endif

/** @brief CDC 类句柄（全局，4 字节对齐） */
USBD_CDC_HandleTypeDef __aligned(4) USBD_CDC_Handle;

/**
 * @brief CDC 类回调结构体
 * @details 这些函数由 usb_core 和 usb_lowlevel 从 PCD_EP_ISR_Handler() 中断调用
 */
USBD_ClassTypeDef  USBD_ClassCallbacks =
{
  .Init                          = USBD_CDC_Init,
  .DeInit                        = USBD_CDC_DeInit,
  .Setup                         = USBD_CDC_Setup,
  .EP0_TxSent                    = NULL,
  .EP0_RxReady                   = USBD_CDC_EP0_RxReady,
  .DataIn                        = USBD_CDC_DataIn,
  .DataOut                       = USBD_CDC_DataOut,
  .SOF                           = NULL,
  .IsoINIncomplete               = NULL,
  .IsoOUTIncomplete              = NULL,
#if !USB_DEVICE_FULL_SPEED
  .GetHSConfigDescriptor         = USBD_CDC_GetHSCfgDesc,
#else
  .GetHSConfigDescriptor         = NULL, // 全速设备：不使用高速配置描述符
#endif
  .GetFSConfigDescriptor         = USBD_CDC_GetFSCfgDesc,
#if !USB_DEVICE_FULL_SPEED
  .GetOtherSpeedConfigDescriptor = USBD_CDC_GetOtherSpeedCfgDesc,
  .GetDeviceQualifierDescriptor  = USBD_CDC_GetDeviceQualifierDescriptor,
#else
  .GetOtherSpeedConfigDescriptor = NULL, // 全速设备：不使用其它速率描述符
  .GetDeviceQualifierDescriptor  = NULL,
#endif
};

/**
 * @brief CDC 设备描述符
 * @details VID 0x16D0（MCS）/ PID 0x117E（CANable Slcan），bDeviceClass 为 CDC（虚拟串口）
 */
__ALIGN_BEGIN uint8_t USBD_DeviceDesc[USB_LEN_DEV_DESC] __ALIGN_END =
{
    0x12,                              // bLength
    USB_DESC_TYPE_DEVICE,              // bDescriptorType = 设备描述符
    0x00,                              // bcdUSB 版本低字节
    0x02,                              // bcdUSB 版本 = 2.0
    0x02,                              // bDeviceClass    = CDC 控制类（虚拟串口）
    0x02,                              // bDeviceSubClass = 抽象控制模型（ACM）
    0x00,                              // bDeviceProtocol
    USB_MAX_EP0_SIZE,                  // bMaxPacketSize  = 64 字节
    LOBYTE(0x16D0),                    // idVendor  厂商 ID MCS
    HIBYTE(0x16D0),                    // idVendor  厂商 ID MCS
    LOBYTE(0x117E),                    // idProduct 产品 ID CANable Slcan
    HIBYTE(0x117E),                    // idProduct 产品 ID CANable Slcan
    LOBYTE(FIRMWARE_VERSION_BCD >> 8), // bcdDevice 固件版本，见 settings.h
    HIBYTE(FIRMWARE_VERSION_BCD >> 8), // bcdDevice 固件版本，见 settings.h
    USBD_IDX_MFC_STR,                  // 厂商字符串描述符索引
    USBD_IDX_PRODUCT_STR,              // 产品字符串描述符索引
    USBD_IDX_SERIAL_STR,               // 序列号字符串描述符索引
    USBD_MAX_NUM_CONFIGURATION         // bNumConfigurations
};

#if !USB_DEVICE_FULL_SPEED
/**
 * @brief USB CDC 设备高速配置描述符（仅高速设备编译）
 * @details 内容与全速配置描述符一致，仅 wMaxPacketSize/bInterval 等按高速参数
 */
__ALIGN_BEGIN uint8_t USBD_CDC_CfgHSDesc[USB_CDC_CONFIG_DESC_SIZ] __ALIGN_END =
{
  /* 配置描述符 */
  0x09,   /* bLength: 配置描述符大小 */
  USB_DESC_TYPE_CONFIGURATION,      /* bDescriptorType: 配置 */
  USB_CDC_CONFIG_DESC_SIZ,                /* wTotalLength: 返回字节数 */
  0x00,
  0x02,   /* bNumInterfaces: 2 个接口 */
  0x01,   /* bConfigurationValue: 配置值 */
  0x00,   /* iConfiguration: 配置字符串描述符索引 */
  0x80,   /* bmAttributes: 总线供电 */
  0x4B,   /* MaxPower 150 mA */

  /* --------------------------------------------------------------------------- */

  /* 通信类接口描述符 */
  0x09,   /* bLength: 接口描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: 接口 */
  0x00,   /* bInterfaceNumber: 接口号 0 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x01,   /* bNumEndpoints: 使用 1 个端点 */
  0x02,   /* bInterfaceClass: 通信接口类 */
  0x02,   /* bInterfaceSubClass: 抽象控制模型 */
  0x01,   /* bInterfaceProtocol: 通用 AT 命令 */
  0x00,   /* iInterface: */

  /* 头部功能描述符 */
  0x05,   /* bLength: 端点描述符大小 */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x00,   /* bDescriptorSubtype: 头部功能描述符 */
  0x10,   /* bcdCDC: 规范版本号 */
  0x01,

  /* 呼叫管理功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x01,   /* bDescriptorSubtype: 呼叫管理功能描述符 */
  0x00,   /* bmCapabilities: D0+D1 */
  0x01,   /* bDataInterface: 1 */

  /* ACM 功能描述符 */
  0x04,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x02,   /* bDescriptorSubtype: 抽象控制管理描述符 */
  0x02,   /* bmCapabilities */

  /* 联合功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x06,   /* bDescriptorSubtype: 联合功能描述符 */
  0x00,   /* bMasterInterface: 通信类接口 */
  0x01,   /* bSlaveInterface0: 数据类接口 */

  /* 端点 2 描述符（命令端点） */
  0x07,                           /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,   /* bDescriptorType: 端点 */
  CDC_CMD_EP,                     /* bEndpointAddress */
  0x03,                           /* bmAttributes: 中断传输 */
  LOBYTE(CDC_CMD_PACKET_SIZE),     /* wMaxPacketSize: */
  HIBYTE(CDC_CMD_PACKET_SIZE),
  CDC_HS_BINTERVAL,                           /* bInterval: */
  /* --------------------------------------------------------------------------- */

  /* 数据类接口描述符 */
  0x09,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: */
  0x01,   /* bInterfaceNumber: 接口号 1 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x02,   /* bNumEndpoints: 使用 2 个端点 */
  0x0A,   /* bInterfaceClass: CDC 数据类 */
  0x00,   /* bInterfaceSubClass: */
  0x00,   /* bInterfaceProtocol: */
  0x00,   /* iInterface: */

  /* 端点 OUT 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,      /* bDescriptorType: 端点 */
  CDC_OUT_EP,                        /* bEndpointAddress */
  0x02,                              /* bmAttributes: 批量传输 */
  LOBYTE(CDC_DATA_HS_MAX_PACKET_SIZE),  /* wMaxPacketSize: */
  HIBYTE(CDC_DATA_HS_MAX_PACKET_SIZE),
  0x00,                              /* bInterval: 批量传输忽略 */

  /* 端点 IN 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,      /* bDescriptorType: 端点 */
  CDC_IN_EP,                         /* bEndpointAddress */
  0x02,                              /* bmAttributes: 批量传输 */
  LOBYTE(CDC_DATA_HS_MAX_PACKET_SIZE),  /* wMaxPacketSize: */
  HIBYTE(CDC_DATA_HS_MAX_PACKET_SIZE),
  0x00                               /* bInterval: 批量传输忽略 */
} ;
#endif

/**
 * @brief USB CDC 全速配置描述符（含通信类接口 + 数据类接口，共 67 字节）
 */
__ALIGN_BEGIN uint8_t USBD_CDC_CfgFSDesc[USB_CDC_CONFIG_DESC_SIZ] __ALIGN_END =
{
  /* 配置描述符 */
  0x09,   /* bLength: 配置描述符大小 */
  USB_DESC_TYPE_CONFIGURATION,      /* bDescriptorType: 配置 */
  USB_CDC_CONFIG_DESC_SIZ,                /* wTotalLength: 返回字节数 */
  0x00,
  0x02,   /* bNumInterfaces: 2 个接口 */
  0x01,   /* bConfigurationValue: 配置值 */
  0x00,   /* iConfiguration: 配置字符串描述符索引 */
  0x80,   /* bmAttributes: 总线供电 */
  0x4B,   /* MaxPower 150 mA */

  /*---------------------------------------------------------------------------*/

  /* 通信类接口描述符 */
  0x09,   /* bLength: 接口描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: 接口 */
  /* Interface descriptor type */
  0x00,   /* bInterfaceNumber: 接口号 0 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x01,   /* bNumEndpoints: 使用 1 个端点 */
  0x02,   /* bInterfaceClass: 通信接口类 */
  0x02,   /* bInterfaceSubClass: 抽象控制模型 */
  0x01,   /* bInterfaceProtocol: 通用 AT 命令 */
  0x00,   /* iInterface: */

  /* 头部功能描述符 */
  0x05,   /* bLength: 端点描述符大小 */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x00,   /* bDescriptorSubtype: 头部功能描述符 */
  0x10,   /* bcdCDC: 规范版本号 */
  0x01,

  /* 呼叫管理功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x01,   /* bDescriptorSubtype: 呼叫管理功能描述符 */
  0x00,   /* bmCapabilities: D0+D1 */
  0x01,   /* bDataInterface: 1 */

  /* ACM 功能描述符 */
  0x04,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x02,   /* bDescriptorSubtype: 抽象控制管理描述符 */
  0x02,   /* bmCapabilities */

  /* 联合功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x06,   /* bDescriptorSubtype: 联合功能描述符 */
  0x00,   /* bMasterInterface: 通信类接口 */
  0x01,   /* bSlaveInterface0: 数据类接口 */

  /* 端点 2 描述符（命令端点） */
  0x07,                           /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,   /* bDescriptorType: 端点 */
  CDC_CMD_EP,                     /* bEndpointAddress */
  0x03,                           /* bmAttributes: 中断传输 */
  LOBYTE(CDC_CMD_PACKET_SIZE),     /* wMaxPacketSize: */
  HIBYTE(CDC_CMD_PACKET_SIZE),
  CDC_FS_BINTERVAL,                           /* bInterval: */
  /*---------------------------------------------------------------------------*/

  /* 数据类接口描述符 */
  0x09,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: */
  0x01,   /* bInterfaceNumber: 接口号 1 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x02,   /* bNumEndpoints: 使用 2 个端点 */
  0x0A,   /* bInterfaceClass: CDC 数据类 */
  0x00,   /* bInterfaceSubClass: */
  0x00,   /* bInterfaceProtocol: */
  0x00,   /* iInterface: */

  /* 端点 OUT 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,      /* bDescriptorType: 端点 */
  CDC_OUT_EP,                        /* bEndpointAddress */
  0x02,                              /* bmAttributes: 批量传输 */
  LOBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),  /* wMaxPacketSize: */
  HIBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),
  0x00,                              /* bInterval: 批量传输忽略 */

  /* 端点 IN 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,      /* bDescriptorType: 端点 */
  CDC_IN_EP,                         /* bEndpointAddress */
  0x02,                              /* bmAttributes: 批量传输 */
  LOBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),  /* wMaxPacketSize: */
  HIBYTE(CDC_DATA_FS_MAX_PACKET_SIZE),
  0x00                               /* bInterval: 批量传输忽略 */
} ;

#if !USB_DEVICE_FULL_SPEED
/**
 * @brief USB CDC 其它速率配置描述符（仅高速设备编译）
 */
__ALIGN_BEGIN uint8_t USBD_CDC_OtherSpeedCfgDesc[USB_CDC_CONFIG_DESC_SIZ] __ALIGN_END =
{
  /* 配置描述符 */
  0x09,   /* bLength: 配置描述符大小 */
  USB_DESC_TYPE_OTHER_SPEED_CONFIGURATION,
  USB_CDC_CONFIG_DESC_SIZ,
  0x00,
  0x02,   /* bNumInterfaces: 2 个接口 */
  0x01,   /* bConfigurationValue: */
  0x04,   /* iConfiguration: */
  0x80,   /* bmAttributes: 总线供电 */
  0x4B,   /* MaxPower 150 mA */

  /* 通信类接口描述符 */
  0x09,   /* bLength: 接口描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: 接口 */
  0x00,   /* bInterfaceNumber: 接口号 0 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x01,   /* bNumEndpoints: 使用 1 个端点 */
  0x02,   /* bInterfaceClass: 通信接口类 */
  0x02,   /* bInterfaceSubClass: 抽象控制模型 */
  0x01,   /* bInterfaceProtocol: 通用 AT 命令 */
  0x00,   /* iInterface: */

  /* 头部功能描述符 */
  0x05,   /* bLength: 端点描述符大小 */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x00,   /* bDescriptorSubtype: 头部功能描述符 */
  0x10,   /* bcdCDC: 规范版本号 */
  0x01,

  /* 呼叫管理功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x01,   /* bDescriptorSubtype: 呼叫管理功能描述符 */
  0x00,   /* bmCapabilities: D0+D1 */
  0x01,   /* bDataInterface: 1 */

  /* ACM 功能描述符 */
  0x04,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x02,   /* bDescriptorSubtype: 抽象控制管理描述符 */
  0x02,   /* bmCapabilities */

  /* 联合功能描述符 */
  0x05,   /* bFunctionLength */
  0x24,   /* bDescriptorType: CS_INTERFACE */
  0x06,   /* bDescriptorSubtype: 联合功能描述符 */
  0x00,   /* bMasterInterface: 通信类接口 */
  0x01,   /* bSlaveInterface0: 数据类接口 */

  /* 端点 2 描述符（命令端点） */
  0x07,                           /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,         /* bDescriptorType: 端点 */
  CDC_CMD_EP,                     /* bEndpointAddress */
  0x03,                           /* bmAttributes: 中断传输 */
  LOBYTE(CDC_CMD_PACKET_SIZE),     /* wMaxPacketSize: */
  HIBYTE(CDC_CMD_PACKET_SIZE),
  CDC_FS_BINTERVAL,                           /* bInterval: */

  /*---------------------------------------------------------------------------*/

  /* 数据类接口描述符 */
  0x09,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_INTERFACE,  /* bDescriptorType: */
  0x01,   /* bInterfaceNumber: 接口号 1 */
  0x00,   /* bAlternateSetting: 备用设置 */
  0x02,   /* bNumEndpoints: 使用 2 个端点 */
  0x0A,   /* bInterfaceClass: CDC 数据类 */
  0x00,   /* bInterfaceSubClass: */
  0x00,   /* bInterfaceProtocol: */
  0x00,   /* iInterface: */

  /* 端点 OUT 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,      /* bDescriptorType: 端点 */
  CDC_OUT_EP,                        /* bEndpointAddress */
  0x02,                              /* bmAttributes: 批量传输 */
  0x40,                              /* wMaxPacketSize: */
  0x00,
  0x00,                              /* bInterval: 批量传输忽略 */

  /* 端点 IN 描述符 */
  0x07,   /* bLength: 端点描述符大小 */
  USB_DESC_TYPE_ENDPOINT,     /* bDescriptorType: 端点 */
  CDC_IN_EP,                        /* bEndpointAddress */
  0x02,                             /* bmAttributes: 批量传输 */
  0x40,                             /* wMaxPacketSize: */
  0x00,
  0x00                              /* bInterval */
};
#endif

#if !USB_DEVICE_FULL_SPEED
/**
 * @brief USB 设备限定符描述符（仅高速设备编译）
 */
__ALIGN_BEGIN static uint8_t USBD_CDC_DeviceQualifierDesc[USB_LEN_DEV_QUALIFIER_DESC] __ALIGN_END =
{
  USB_LEN_DEV_QUALIFIER_DESC,
  USB_DESC_TYPE_DEVICE_QUALIFIER,
  0x00,
  0x02,
  0x00,
  0x00,
  0x00,
  0x40,
  0x01,
  0x00,
};
#endif

// ============================================================================================================

/**
 * @brief 配置所有端点的 PMA（包内存区）
 * @param[in] pdev USB 设备句柄
 * @details 在 USBD_LL_Init() 初始化期间调用
 */
void USBD_ConfigureEndpoints(USBD_HandleTypeDef *pdev)
{
    // 为所有端点配置包内存区（PMA）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x00, PCD_SNG_BUF, 0x18);  // EP 0 OUT（SETUP，最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x80, PCD_SNG_BUF, 0x58);  // EP 0 IN （SETUP，最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x81, PCD_SNG_BUF, 0xC0);  // EP 1 IN （数据接口，最大包大小 = 64 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x82, PCD_SNG_BUF, 0x100); // EP 2 IN （控制接口，最大包大小 = 8 字节）
    HAL_PCDEx_PMAConfig((PCD_HandleTypeDef*)pdev->pData, 0x01, PCD_SNG_BUF, 0x110); // EP 1 OUT（数据接口，最大包大小 = 64 字节）
}

// ============================================================================================================

/**
  * @brief  初始化 CDC 接口
  * @param  pdev: 设备实例
  * @param  cfgidx: 配置索引
  * @retval 状态
  */
static uint8_t USBD_CDC_Init(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
    pdev->pClassData = &USBD_CDC_Handle;

#if !USB_DEVICE_FULL_SPEED
    if (pdev->dev_speed == USBD_SPEED_HIGH)
    {
        // 高速：打开数据 IN 端点（HS 包大小）
        USBD_LL_OpenEP(pdev, CDC_IN_EP, USBD_EP_TYPE_BULK, CDC_DATA_HS_IN_PACKET_SIZE);

        pdev->ep_in[CDC_IN_EP & 0xFU].is_used = 1U;

        // 高速：打开数据 OUT 端点（HS 包大小）
        USBD_LL_OpenEP(pdev, CDC_OUT_EP, USBD_EP_TYPE_BULK, CDC_DATA_HS_OUT_PACKET_SIZE);

        pdev->ep_out[CDC_OUT_EP & 0xFU].is_used = 1U;
    }
    else
#endif
    {
        /* 打开数据 IN 端点 */
        USBD_LL_OpenEP(pdev, CDC_IN_EP, USBD_EP_TYPE_BULK, CDC_DATA_FS_IN_PACKET_SIZE);

        pdev->ep_in[CDC_IN_EP & 0xFU].is_used = 1U;

        /* 打开数据 OUT 端点 */
        USBD_LL_OpenEP(pdev, CDC_OUT_EP, USBD_EP_TYPE_BULK, CDC_DATA_FS_OUT_PACKET_SIZE);

        pdev->ep_out[CDC_OUT_EP & 0xFU].is_used = 1U;
    }

    /* 打开命令 IN 端点（中断传输） */
    USBD_LL_OpenEP(pdev, CDC_CMD_EP, USBD_EP_TYPE_INTR, CDC_CMD_PACKET_SIZE);
    pdev->ep_in[CDC_CMD_EP & 0xFU].is_used = 1U;

    USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;

    /* 初始化物理接口组件 */
    USBD_InterfaceCallbacks.Init();

    /* 初始化传输状态 */
    hcdc->TxState = 0U;
    hcdc->RxState = 0U;

#if !USB_DEVICE_FULL_SPEED
    if (pdev->dev_speed == USBD_SPEED_HIGH)
    {
      // 高速：准备 OUT 端点接收下一包（HS 包大小）
      USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, hcdc->RxBuffer, CDC_DATA_HS_OUT_PACKET_SIZE);
    }
    else
#endif
    {
      // 准备 OUT 端点接收下一包
      USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, hcdc->RxBuffer, CDC_DATA_FS_OUT_PACKET_SIZE);
    }
    return 0;
}

/**
  * @brief  反初始化 CDC 层
  * @param  pdev: 设备实例
  * @param  cfgidx: 配置索引
  * @retval 状态
  */
static uint8_t  USBD_CDC_DeInit(USBD_HandleTypeDef *pdev, uint8_t cfgidx)
{
  uint8_t ret = 0U;

  /* 关闭数据 IN 端点 */
  USBD_LL_CloseEP(pdev, CDC_IN_EP);
  pdev->ep_in[CDC_IN_EP & 0xFU].is_used = 0U;

  /* 关闭数据 OUT 端点 */
  USBD_LL_CloseEP(pdev, CDC_OUT_EP);
  pdev->ep_out[CDC_OUT_EP & 0xFU].is_used = 0U;

  /* 关闭命令 IN 端点 */
  USBD_LL_CloseEP(pdev, CDC_CMD_EP);
  pdev->ep_in[CDC_CMD_EP & 0xFU].is_used = 0U;

  /* 反初始化物理接口组件 */
  if (pdev->pClassData != NULL)
  {
      USBD_InterfaceCallbacks.DeInit();
      pdev->pClassData = NULL;
  }
  return ret;
}

/**
  * @brief  处理 CDC 特定请求
  * @param  pdev: 设备实例
  * @param  req: USB 请求
  * @retval 状态
  */
static uint8_t USBD_CDC_Setup(USBD_HandleTypeDef *pdev, USBD_SetupReqTypedef *req)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;
  uint8_t ifalt = 0U;
  uint16_t status_info = 0U;
  uint8_t ret = USBD_OK;

  switch (req->bmRequest & USB_REQ_TYPE_MASK)
  {
    case USB_REQ_TYPE_CLASS :
      if (req->wLength)
      {
        if (req->bmRequest & 0x80U)
        {
          // 设备 -> 主机：调 Control 回调填充应答后经端点 0 返回
          USBD_InterfaceCallbacks.Control(req->bRequest, (uint8_t *)(void *)hcdc->data, req->wLength);

          USBD_CtlSendData(pdev, (uint8_t *)(void *)hcdc->data, req->wLength);
        }
        else
        {
          // 主机 -> 设备：保存命令码，准备接收 OUT 数据
          hcdc->CmdOpCode = req->bRequest;
          hcdc->CmdLength = (uint8_t)req->wLength;

          USBD_CtlPrepareRx(pdev, (uint8_t *)(void *)hcdc->data, req->wLength);
        }
      }
      else
      {
        USBD_InterfaceCallbacks.Control(req->bRequest, (uint8_t *)(void *)req, 0U);
      }
      break;

    case USB_REQ_TYPE_STANDARD:
      switch (req->bRequest)
      {
        case USB_REQ_GET_STATUS:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            USBD_CtlSendData(pdev, (uint8_t *)(void *)&status_info, 2U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_GET_INTERFACE:
          if (pdev->dev_state == USBD_STATE_CONFIGURED)
          {
            USBD_CtlSendData(pdev, &ifalt, 1U);
          }
          else
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        case USB_REQ_SET_INTERFACE:
          if (pdev->dev_state != USBD_STATE_CONFIGURED)
          {
            USBD_CtlError(pdev, req);
            ret = USBD_FAIL;
          }
          break;

        default:
          USBD_CtlError(pdev, req);
          ret = USBD_FAIL;
          break;
      }
      break;

    default:
      USBD_CtlError(pdev, req);
      ret = USBD_FAIL;
      break;
  }
  return ret;
}

/**
  * @brief  非控制 IN 端点数据已发送
  * @param  pdev: 设备实例
  * @param  epnum: 端点号
  * @retval 状态
  */
static uint8_t USBD_CDC_DataIn(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)pdev->pClassData;
  PCD_HandleTypeDef *hpcd = pdev->pData;

  if (pdev->pClassData != NULL)
  {
    // 发送长度恰为最大包大小的整数倍时，需补发零长度包（ZLP）
    // 以标识传输结束，否则主机会继续等待数据
    if ((pdev->ep_in[epnum].total_length > 0U) && ((pdev->ep_in[epnum].total_length % hpcd->IN_ep[epnum].maxpacket) == 0U))
    {
      // 复位包总长度
      pdev->ep_in[epnum].total_length = 0U;

      // 发送 ZLP
      USBD_LL_Transmit(pdev, epnum, NULL, 0U);
    }
    else
    {
      hcdc->TxState = 0U;
    }
    return USBD_OK;
  }
  else return USBD_FAIL;
}

/**
  * @brief  非控制 OUT 端点收到数据
  * @param  pdev: 设备实例
  * @param  epnum: 端点号
  * @retval 状态
  */
static uint8_t  USBD_CDC_DataOut(USBD_HandleTypeDef *pdev, uint8_t epnum)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;

  /* 获取接收数据长度 */
  hcdc->RxLength = USBD_LL_GetRxDataSize(pdev, epnum);

  /* USB 数据立即处理，以在应用传输结束前 NAK 后续 USB 流量 */
  if (pdev->pClassData != NULL)
  {
    USBD_InterfaceCallbacks.Receive(hcdc->RxBuffer, &hcdc->RxLength);
    return USBD_OK;
  }
  else return USBD_FAIL;
}

/**
  * @brief  处理端点 0 就绪事件
  * @param  pdev: 设备实例
  * @retval 状态
  */
static uint8_t  USBD_CDC_EP0_RxReady(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;

  if (hcdc->CmdOpCode != 0xFFU)
  {
     USBD_InterfaceCallbacks.Control(hcdc->CmdOpCode, (uint8_t *)(void *)hcdc->data, (uint16_t)hcdc->CmdLength);
     hcdc->CmdOpCode = 0xFFU;
  }
  return USBD_OK;
}

/**
  * @brief  返回全速配置描述符
  * @param  length: 数据长度指针
  * @retval 描述符缓冲区指针
  */
static uint8_t  *USBD_CDC_GetFSCfgDesc(uint16_t *length)
{
  *length = sizeof(USBD_CDC_CfgFSDesc);
  return USBD_CDC_CfgFSDesc;
}

/**
  * @brief  返回高速配置描述符
  * @param  length: 数据长度指针
  * @retval 描述符缓冲区指针
  */

#if !USB_DEVICE_FULL_SPEED
static uint8_t  *USBD_CDC_GetHSCfgDesc(uint16_t *length)
{
  *length = sizeof(USBD_CDC_CfgHSDesc);
  return USBD_CDC_CfgHSDesc;
}
#endif

/**
  * @brief  返回其它速率配置描述符
  * @param  length: 数据长度指针
  * @retval 描述符缓冲区指针
  */
#if !USB_DEVICE_FULL_SPEED
static uint8_t  *USBD_CDC_GetOtherSpeedCfgDesc(uint16_t *length)
{
  *length = sizeof(USBD_CDC_OtherSpeedCfgDesc);
  return USBD_CDC_OtherSpeedCfgDesc;
}
#endif

/**
* @brief  返回设备限定符描述符
* @param  length: 数据长度指针
* @retval 描述符缓冲区指针
*/
#if !USB_DEVICE_FULL_SPEED
uint8_t  *USBD_CDC_GetDeviceQualifierDescriptor(uint16_t *length)
{
  *length = sizeof(USBD_CDC_DeviceQualifierDesc);
  return USBD_CDC_DeviceQualifierDesc;
}
#endif

/**
  * @brief  设置发送缓冲与长度
  * @param  pdev: 设备实例
  * @param  pbuff: 发送缓冲
  * @param  length: 数据长度
  * @retval 状态
  */
uint8_t  USBD_CDC_SetTxBuffer(USBD_HandleTypeDef* pdev, uint8_t *pbuff, uint16_t length)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;
  hcdc->TxBuffer = pbuff;
  hcdc->TxLength = length;
  return USBD_OK;
}

/**
  * @brief  设置接收缓冲
  * @param  pdev: 设备实例
  * @param  pbuff: 接收缓冲
  * @retval 状态
  */
uint8_t USBD_CDC_SetRxBuffer(USBD_HandleTypeDef* pdev, uint8_t  *pbuff)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;
  hcdc->RxBuffer = pbuff;
  return USBD_OK;
}

/**
  * @brief  在 IN 端点发送数据包
  * @param  pdev: 设备实例
  * @retval 状态（上一次传输未完成返回 USBD_BUSY）
  */
uint8_t USBD_CDC_TransmitPacket(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_HandleTypeDef* hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;

  if (pdev->pClassData != NULL)
  {
    if (hcdc->TxState == 0U)
    {
      /* 标记传输进行中 */
      hcdc->TxState = 1U;

      /* 更新包总长度 */
      pdev->ep_in[CDC_IN_EP & 0xFU].total_length = hcdc->TxLength;

      /* 发送数据包 */
      USBD_LL_Transmit(pdev, CDC_IN_EP, hcdc->TxBuffer, (uint16_t)hcdc->TxLength);
      return USBD_OK;
    }
    else return USBD_BUSY;
  }
  else return USBD_FAIL;
}

/**
  * @brief  准备 OUT 端点接收数据
  * @param  pdev: 设备实例
  * @retval 状态
  */
uint8_t USBD_CDC_ReceivePacket(USBD_HandleTypeDef *pdev)
{
  USBD_CDC_HandleTypeDef   *hcdc = (USBD_CDC_HandleTypeDef *) pdev->pClassData;

  /* 挂起或恢复 USB 输出过程 */
  if (pdev->pClassData != NULL)
  {
#if !USB_DEVICE_FULL_SPEED
    if (pdev->dev_speed == USBD_SPEED_HIGH)
    {
      // 高速：准备 OUT 端点接收下一包（HS 包大小）
      USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, hcdc->RxBuffer, CDC_DATA_HS_OUT_PACKET_SIZE);
    }
    else
#endif
    {
      // 准备 OUT 端点接收下一包
      USBD_LL_PrepareReceive(pdev, CDC_OUT_EP, hcdc->RxBuffer, CDC_DATA_FS_OUT_PACKET_SIZE);
    }
    return USBD_OK;
  }
  else return USBD_FAIL;
}

/**
 * @brief 处理 SETUP 阶段请求
 * @param[in] hpcd PCD 句柄
 * @return true 已处理
 * @details 从 lowlevel.c 调用；Slcan 未使用，恒返回 false
 */
bool USBD_SetupStageRequest(PCD_HandleTypeDef *hpcd)
{
    return false;
}