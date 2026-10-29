#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
usage() {
    echo "用法：sudo $0 <新ID>，范围1～47，如2或0x02。"
    echo "只连接一只传感器并停止DHW；扫描通过后自动改号，无交互确认。"
}
if [[ $# -ne 1 ]]; then usage; exit 2; fi
if [[ $1 == --help || $1 == -h ]]; then usage; exit 0; fi
if [[ $1 =~ ^[0-9]{1,2}$ ]]; then
    target=$((10#$1))
elif [[ $1 =~ ^0[xX][0-9a-fA-F]{1,2}$ ]]; then
    target=$((16#${1:2}))
else
    usage; exit 2
fi
if (( target < 1 || target > 47 )); then usage; exit 2; fi
if (( EUID != 0 )); then echo '请使用sudo执行。' >&2; exit 2; fi
for tool in cmake cc make flock pgrep; do
    command -v "$tool" >/dev/null || { echo "缺少依赖：$tool" >&2; exit 1; }
done
exec 9>/run/lock/g0-torque-setid.lock
flock -n 9 || { echo '已有标ID程序运行，请勿重复执行。' >&2; exit 1; }
if pgrep -f '(^|/)(Driver_Hardware|DHW_Hardware_Test|g0_torque_set_id)( |$)' >/dev/null; then
    echo '请先停止DHW、硬件测试及其它标ID程序。' >&2
    exit 1
fi
echo "目标ID=$target；请确保CAN总线上只连接一只传感器。"
cmake -S "$SCRIPT_DIR" -B "$SCRIPT_DIR/build" -DCMAKE_BUILD_TYPE=Release
cmake --build "$SCRIPT_DIR/build" -j2
exec "$SCRIPT_DIR/build/g0_torque_set_id" "$target"
