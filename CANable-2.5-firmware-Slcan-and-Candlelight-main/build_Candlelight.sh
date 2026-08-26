#!/bin/bash
set -e

FIRMWARE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

show_help() {
    echo "CANable 2.5 固件编译脚本"
    echo "Usage: $0 [options]"
    echo
    echo "Options:"
    echo "  -h, --help           显示帮助信息"
    echo "  -b, --board NAME     选择目标板 (默认: MksMakerbase)"
    echo "                       可选: MksMakerbase, Openlightlabs"
    echo "  -f, --firmware NAME  选择固件类型 (默认: Candlelight)"
    echo "                       可选: Candlelight, Slcan"
    echo "  -c, --clean          清理编译输出"
    echo "  -f, --flash          编译并烧录到设备 (DFU模式)"
    echo "  -v, --verbose        详细输出"
    echo
    echo "Examples:"
    echo "  $0                      # 编译 Candlelight (MksMakerbase)"
    echo "  $0 -b Openlightlabs     # 编译 Candlelight (Openlightlabs)"
    echo "  $0 -f Slcan             # 编译 Slcan (MksMakerbase)"
    echo "  $0 --flash              # 编译并烧录"
    echo "  $0 --clean              # 清理"
}

BOARD="MksMakerbase"
FIRMWARE="Candlelight"
DO_CLEAN=false
DO_FLASH=false
VERBOSE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            show_help
            exit 0
            ;;
        -b|--board)
            BOARD="$2"
            shift 2
            ;;
        -f|--firmware)
            FIRMWARE="$2"
            shift 2
            ;;
        -c|--clean)
            DO_CLEAN=true
            shift
            ;;
        --flash)
            DO_FLASH=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        *)
            echo "未知选项: $1"
            show_help
            exit 1
            ;;
    esac
done

FIRMWARE_SHORT="${FIRMWARE}"
if [[ "${FIRMWARE}" == "Candlelight" ]]; then
    FIRMWARE_SHORT="Candle"
fi
MAKEFILE="Make_G431_${FIRMWARE_SHORT}_${BOARD}"

if [[ ! -f "${FIRMWARE_DIR}/${MAKEFILE}" ]]; then
    echo "错误: Makefile 不存在: ${MAKEFILE}"
    echo "支持的组合:"
    echo "  - Candlelight + MksMakerbase"
    echo "  - Candlelight + Openlightlabs"
    echo "  - Slcan + MksMakerbase"
    echo "  - Slcan + Openlightlabs"
    exit 1
fi

if ! command -v arm-none-eabi-gcc &> /dev/null; then
    echo "错误: 未找到 arm-none-eabi-gcc，请先安装 ARM 工具链:"
    echo "  sudo apt install gcc-arm-none-eabi"
    exit 1
fi

cd "${FIRMWARE_DIR}"

if $DO_CLEAN; then
    echo "清理编译输出..."
    make -s -f "${MAKEFILE}" clean || true
    rm -rf Build_*
    echo "清理完成"
    exit 0
fi

MAKE_FLAGS="-s"
if $VERBOSE; then
    MAKE_FLAGS=""
fi

echo "编译 ${FIRMWARE} 固件 (${BOARD})..."
echo "----------------------------------------"

if $DO_FLASH; then
    make ${MAKE_FLAGS} -f "${MAKEFILE}" flash
else
    make ${MAKE_FLAGS} -f "${MAKEFILE}"
fi

BUILD_DIR="Build_STM32G431xx_${FIRMWARE}_${BOARD}"
TARGET_FILE="${BUILD_DIR}/STM32G431_${FIRMWARE}2.5_${BOARD}"

if [[ -f "${TARGET_FILE}.bin" ]]; then
    echo
    echo "编译成功!"
    echo "----------------------------------------"
    ls -la "${TARGET_FILE}".{bin,hex,elf}
    echo
    echo "输出文件:"
    echo "  二进制: ${TARGET_FILE}.bin"
    echo "  Hex:    ${TARGET_FILE}.hex"
    echo "  ELF:    ${TARGET_FILE}.elf"
    echo
    if ! $DO_FLASH; then
        echo "如需烧录，请先将 CANable 进入 DFU 模式（按住 BOOT 键重新插拔 USB），然后运行:"
        echo "  $0 --flash -b ${BOARD} -f ${FIRMWARE}"
        echo "或手动运行:"
        echo "  sudo dfu-util -w -d 0483:df11 -c 1 -i 0 -a 0 -s 0x08000000:leave -D ${TARGET_FILE}.bin"
    fi
else
    echo "编译失败!"
    exit 1
fi
