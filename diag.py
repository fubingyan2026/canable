#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断 ZDT_CANable 2.0 PRO 为什么找不到。
列出所有 USB 设备、检测 slcan 串口、内核模块、udev 规则，
并尝试多种已知 VID/PID。
"""
import os
import sys
import subprocess
import glob

# 让脚本既能 python diag.py 也能作为模块导入
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def section(title):
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


# ---------------------------------------------------------------------------
#  1. 已知 candleLight / CANable 兼容的 VID/PID
# ---------------------------------------------------------------------------
KNOWN_IDS = [
    (0x1D50, 0x606F, "candleLight 默认"),
    (0x1D50, 0x6069, "candleLight 派生"),
    (0x1D50, 0x606A, "candleLight 派生"),
    (0x1D50, 0x606B, "candleLight 派生"),
    (0x1D50, 0x606C, "candleLight 派生"),
    (0x1D50, 0x606D, "candleLight 派生"),
    (0x1D50, 0x606E, "candleLight 派生"),
    (0x1209, 0x2323, "pid.codes gs_usb"),
    (0x1209, 0x2322, "pid.codes 派生"),
    (0x16D0, 0x0FDB, "MDFLY CANable"),
    (0x1D50, 0x60AC, "cantact / CANAble (兼容)"),
]


# ---------------------------------------------------------------------------
#  2. 尝试 pyusb 查找
# ---------------------------------------------------------------------------
def find_with_pyusb():
    section("1. 尝试 pyusb 扫描")
    try:
        import usb.core
    except ImportError:
        print("✗ pyusb 未安装  (pip install pyusb)")
        return None

    # 1A: 按已知 VID/PID 查
    found = []
    for vid, pid, desc in KNOWN_IDS:
        dev = usb.core.find(idVendor=vid, idProduct=pid)
        if dev is not None:
            try:
                mfg = usb.util.get_string(dev, dev.iManufacturer) or ""
                prd = usb.util.get_string(dev, dev.iProduct) or ""
                ser = usb.util.get_string(dev, dev.iSerialNumber) or ""
            except Exception:
                mfg = prd = ser = ""
            found.append((vid, pid, desc, mfg, prd, ser))
            print(f"  ✓ 命中: {vid:04X}:{pid:04X}  {desc}")
            print(f"      Manufacturer: {mfg!r}  Product: {prd!r}")
            print(f"      Serial:       {ser!r}")
    if not found:
        print("  ✗ 已知 VID/PID 都未匹配")

    # 1B: 枚举所有 USB 设备，过滤可能和 CANable 相关的
    print("\n  --- 全部 USB 设备（粗筛关键字）---")
    keywords = ("can", "candle", "cantact", "gs_usb", "slcan",
                "zdt", "able", "stm32", "cdc")
    try:
        all_devs = list(usb.core.find(find_all=True))
    except Exception as e:
        print(f"  ✗ 枚举失败: {e}")
        return found

    for d in all_devs:
        try:
            mfg = usb.util.get_string(d, d.iManufacturer) or ""
            prd = usb.util.get_string(d, d.iProduct) or ""
        except Exception:
            mfg = prd = ""
        text = (mfg + " " + prd).lower()
        if any(k in text for k in keywords):
            print(f"  候选: {d.idVendor:04X}:{d.idProduct:04X}  "
                  f"{mfg!r}  {prd!r}")
    print(f"\n  共枚举 {len(all_devs)} 个 USB 设备")
    return found


# ---------------------------------------------------------------------------
#  3. 检查 /dev/ttyACM*（slcan 模式）
# ---------------------------------------------------------------------------
def find_ttyacm():
    section("2. 检查 slcan 模式（CDC ACM 串口）")
    ports = sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))
    if not ports:
        print("  ✗ 未发现 /dev/ttyACM* 或 /dev/ttyUSB*")
        print("     设备可能完全没插好，或没被识别为 USB 串口")
        return []
    for p in ports:
        try:
            st = os.stat(p)
            print(f"  · {p}  (mode={oct(st.st_mode & 0o777)})")
        except OSError as e:
            print(f"  · {p}  stat 失败: {e}")
    return ports


# ---------------------------------------------------------------------------
#  4. 内核模块检查
# ---------------------------------------------------------------------------
def check_kernel():
    section("3. 内核驱动/模块")
    for mod in ("gs_usb", "slcan", "cdc_acm", "can", "can_raw", "can_dev"):
        r = subprocess.run(["lsmod"], capture_output=True, text=True)
        loaded = any(line.split()[0] == mod for line in r.stdout.splitlines()
                     if line and not line.startswith("Module"))
        marker = "✓" if loaded else "·"
        print(f"  {marker} {mod:10s} {'已加载' if loaded else '未加载'}")

    # 检查 socketcan 接口
    print("\n  --- /sys/class/net 中的 CAN 接口 ---")
    for iface in sorted(glob.glob("/sys/class/net/can*")):
        name = os.path.basename(iface)
        print(f"  · {name}")


# ---------------------------------------------------------------------------
#  5. udev 规则检查
# ---------------------------------------------------------------------------
def check_udev():
    section("4. udev 规则")
    rules_dir = "/etc/udev/rules.d"
    matches = []
    if os.path.isdir(rules_dir):
        for fn in os.listdir(rules_dir):
            if not fn.endswith(".rules"):
                continue
            path = os.path.join(rules_dir, fn)
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        ll = line.lower()
                        if ("1d50" in ll and "606f" in ll) or "zdt" in ll \
                                or "canable" in ll or "candle" in ll:
                            matches.append(f"{path}: {line.strip()}")
            except OSError:
                pass
    if matches:
        for m in matches:
            print(f"  · {m}")
    else:
        print("  ✗ 没有发现 candleLight / ZDT / CANable 相关 udev 规则")
        print("    解决: sudo bash install_udev.sh")


# ---------------------------------------------------------------------------
#  6. lsusb 输出
# ---------------------------------------------------------------------------
def lsusb_dump():
    section("5. lsusb 输出")
    if not os.path.exists("/usr/bin/lsusb"):
        print("  · lsusb 不存在，跳过")
        return
    r = subprocess.run(["lsusb"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ✗ lsusb 失败: {r.stderr.strip()}")
        return
    for line in r.stdout.splitlines():
        print(f"  {line}")


# ---------------------------------------------------------------------------
#  7. 修复建议
# ---------------------------------------------------------------------------
def advice(found, ports):
    section("修复建议")
    if found:
        print("  ✓ 设备已通过 pyusb 找到，请检查 udev 权限（见 install_udev.sh）")
        return
    if ports:
        print("  ✓ 设备以 slcan (CDC ACM) 模式存在。")
        print("    你需要：")
        print("      a) 把它切换到 gs_usb 模式：")
        print("         - 检查设备是否有按钮/拨码/短接帽，按手册切换固件模式")
        print("         - 或者使用 slcan 后端（见下面的 python-can 替代方案）")
        print("      b) 把以下内容加进 /etc/udev/rules.d/99-cdc-acm.rules：")
        print('         KERNEL=="ttyACM[0-9]*", MODE="0666"')
        print("         然后 sudo udevadm control --reload-rules && "
              "sudo udevadm trigger")
        return
    print("  ✗ 没找到任何 CANable 形态的设备。请按顺序检查：")
    print("    1) 重新插拔 USB，看 dmesg | tail -20 是否有新设备")
    print("    2) lsusb 是否看到任何新设备？")
    print("    3) 设备可能需要外接 5V 供电（CANable 通常从 USB 取电，但有些版本需要）")
    print("    4) 尝试在另一台电脑/USB 口上测试")
    print("    5) 如果设备有模式开关，确认它在 gs_usb 模式")


# ---------------------------------------------------------------------------
def main():
    found = find_with_pyusb() or []
    ports = find_ttyacm()
    check_kernel()
    check_udev()
    lsusb_dump()
    advice(found, ports)


if __name__ == "__main__":
    main()
