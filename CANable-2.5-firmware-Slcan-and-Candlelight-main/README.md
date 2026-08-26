# CANable 2.5 固件（Slcan + Candlelight）

为 CANable 适配器打造的两款高性能、经过速度优化的固件，将 **Slcan** 与 **Candlelight** 合并到同一代码库，并带来大量新特性。

![CANable Adapter](Images/CANable%20Adapter.jpg)

这是首个将 CANable 的 **Slcan** 与 **Candlelight** 两款固件合并到同一代码库的项目：

- 修复了大量原有缺陷
- 新增了大量功能
- 这是首个支持 **CAN FD** 且运行稳定的 STM32G431 Candlelight 固件
- 新固件 **100% 向后兼容**传统 Slcan / Candlelight 固件
- 已在 MKS Makerbase 隔离板（STM32G431）上验证，总线速率最高 **10 Mbaud**
- 架构设计易于扩展，可移植到未来的处理器与开发板
- 预编译的二进制固件可通过固件升级器一键刷写到 CANable

![CANable STM32 固件升级器](Images/CANable%20STM32%20Firmware%20Updater.png)

## 固件变体与目标板

固件通过 makefile 按「固件变体 × 目标板」组合选择编译目标，各 makefile 设置 `TARGET_FIRMWARE` / `TARGET_BOARD` 后统一包含 `Make_Rules.mk`：

| 变体 | 说明 |
|------|------|
| **Candlelight** | 原生 USB candleLight 协议（GSUSB，端点 0x81/0x02），供上位机 pyusb SDK 使用 |
| **Slcan** | USB CDC 虚拟串口，ASCII SLCAN 协议 |

| 目标板 | 说明 |
|--------|------|
| **MksMakerbase** | MKS Makerbase 隔离板（绿色 LED 接 A0 引脚） |
| **Openlightlabs** | Openlightlabs 板 |

对应 makefile：`Make_G431_<Candle|Slcan>_<Board>`（例如 `Make_G431_Candle_MksMakerbase`）。

## 目录结构

```
Source/
├── main.c              # 主循环，约每毫秒 100 次迭代
├── can.c, system.c, dfu.c, led.c
├── usb_core.c, usb_lowlevel.c, ...
├── Candlelight/        # Candlelight 固件专属：usb_class.c / control.c / buffer.c
└── Slcan/              # Slcan 固件专属：usb_class.c / control.c / buffer.c
STM32/
├── STM32G4xx_HAL_Driver, CMSIS
└── STM32G431xx_Config/ # 链接脚本 .ld、启动文件、系统时钟、HAL 配置头
Documentation/          # 文档与 CAN FD 时序参考资料
SampleApplication C++/  # WinUSB 上位机示例（CANableDemo，VS 工程）
Images/                 # 文档图片素材
```

编译时 `Make_Rules.mk` 通过 `-ISource/$(TARGET_FIRMWARE)` 仅编译所选变体的源码，公共核心代码位于 `Source/` 根目录。

## 编译

需要 ARM 工具链：`arm-none-eabi-gcc`（例如 `sudo apt install gcc-arm-none-eabi`）。

### Linux / Git Bash

```bash
# 默认编译 Candlelight (MksMakerbase)
./build.sh

# 指定目标板 / 固件
./build.sh -b Openlightlabs          # Candlelight (Openlightlabs)
./build.sh -f Slcan                  # Slcan (MksMakerbase)

# 编译并烧录（DFU 模式）
./build.sh --flash

# 清理编译输出
./build.sh --clean
```

Slcan 专用一键脚本：`./build_slcan.sh`（参数同 `build.sh`，但固定编译 Slcan 变体，仅支持 `-b` 选择目标板）。

### Windows

运行 `Build_Candlelight.cmd` 或 `Build_Slcan.cmd`。需要安装 **MinGW** 与 **STM32 Cube CLT**。
`Make_Rules.mk` 在 Windows 下需要 `mmkdir`：将 MinGW 目录下的 `mkdir.exe` 重命名为 `mmkdir.exe` 即可。

### 直接使用 make

```bash
make -s -f Make_G431_Candle_MksMakerbase
```

编译产物输出到 `Build_STM32G431xx_<Firmware>_<Board>/` 目录：
`STM32G431_<Firmware>2.5_<Board>.{bin,hex,elf}`（例如 `STM32G431_Candlelight2.5_MksMakerbase.bin`）。

## 烧录（DFU）

1. 按住 **BOOT** 键插入 USB，使设备进入 DFU 模式
2. 使用 `dfu-util` 烧写：

```bash
dfu-util -w -d 0483:df11 -c 1 -i 0 -a 0 -s 0x08000000:leave -D \
  Build_STM32G431xx_Candlelight_MksMakerbase/STM32G431_Candlelight2.5_MksMakerbase.bin
```

> 也可以使用仓库根目录上位机 CANable 2.5 GUI 的固件升级插件一键刷写。

## 文档

详细文档请参考：

- 用户手册（User Manual）
- Slcan 开发手册（Slcan Developer Manual）
- Candlelight 开发手册（Candlelight Developer Manual）
- 固件开发手册（Firmware Developer Manual）

https://netcult.ch/elmue/CANable%20Firmware%20Update/

> 本固件配套的 Windows 上位机（CANable 2.5 GUI）位于仓库根目录，支持 Classic CAN / CAN FD 监控、周期发送、过滤器与固件升级，见 `../README.md`。
