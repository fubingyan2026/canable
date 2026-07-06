# CANable 2.5 GUI

基于 PySide6 的 CANable 2.5 USB-CAN 适配器上位机，支持 Classic CAN 和 CAN FD。

## 目录

- [硬件需求](#硬件需求)
- [环境搭建](#环境搭建)
  - [Windows](#windows)
  - [Linux](#linux)
- [运行](#运行)
- [打包 EXE](#打包-exe)
- [目录结构](#目录结构)
- [常见问题](#常见问题)

## 硬件需求

- CANable 2.5（ElmueSoft 固件）或兼容的 candleLight 设备
- USB 数据线
- CAN 总线（至少两个节点，含 120Ω 终端电阻）

## 环境搭建

### Windows

1. **安装 Python 3.12+**

   ```powershell
   winget install --id Python.Python.3.12
   ```

2. **安装依赖**

   ```powershell
   pip install -r requirements.txt
   ```

3. **安装 USB 驱动**

   用 [Zadig](https://zadig.akeo.ie/) 给 CANable 2.5 安装 WinUSB 驱动：

   - 选择设备 `CANable 2.5`（或 `USB-CAN`，VID `1D50` / PID `606F`）
   - 目标驱动选 `WinUSB`
   - 点 "Replace Driver"

   > 本项目根目录已自带 `libusb-1.0.dll`，SDK 会自动加载，无需额外安装。

### Linux

1. **安装 Python 与系统库**

   ```bash
   sudo apt install python3 python3-pip python3-venv libusb-1.0-0
   ```

2. **安装依赖**

   ```bash
   pip install -r requirements.txt
   ```

3. **安装 udev 规则（免 sudo 访问设备）**

   ```bash
   sudo bash install_udev.sh
   ```

   重新插拔设备后生效。

## 运行

```bash
# 方式一：入口脚本
python cangui.py

# 方式二：模块模式
python -m cangui
```

## 打包 EXE

```powershell
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 生成图标（如未存在）
python -c "from PIL import Image; Image.open('cangui/logo.jpg').save('cangui/logo.ico', format='ICO', sizes=[(32,32),(64,64),(128,128)])"

# 3. 打包
pyinstaller --clean --noconfirm `
    --onefile --windowed `
    --name "CANable2.5" `
    --icon "cangui/logo.ico" `
    --add-data "cangui/logo.jpg;cangui" `
    --add-data "libusb-1.0.dll;." `
    --hidden-import "usb.backend.libusb1" `
    --hidden-import "usb.backend.libusb0" `
    --hidden-import "PySide6.QtXml" `
    cangui.py
```

输出：`dist/CANable2.5.exe`

`settings.json` 和 `send_list.csv` 保存在 exe 同目录下，持久化不丢失。

## 目录结构

```
canable/
├── cangui.py                  # 入口脚本
├── cangui/                    # PySide6 GUI 模块
│   ├── __main__.py
│   ├── main_window.py
│   ├── worker.py              # CAN 工作线程
│   ├── trace.py               # Trace 面板
│   ├── send.py                # 发送面板
│   ├── filters.py             # 过滤器 + 统计面板
│   ├── i18n.py                # 中/英国际化
│   └── style.py               # 主题
├── canable_sdk/               # Python SDK
│   ├── driver.py              # ZDTCanable 主驱动
│   ├── frame.py               # CANFrame 数据类
│   ├── protocol.py            # ElmueSoft 协议解析
│   ├── constants.py           # USB ID、枚举常量
│   ├── bitrate.py             # 位时序表
│   └── cli.py                 # CLI 命令行工具
├── libusb-1.0.dll             # Windows USB 后端
├── install_udev.sh            # Linux udev 规则
└── requirements.txt
```

## 常见问题

### 扫描不到设备

- **Windows**: 确认已用 Zadig 安装 WinUSB 驱动，设备管理器中 CANable 显示为 `WinUSB Device`
- **Linux**: 确认已执行 `install_udev.sh` 并重新插拔设备；ModemManager 可能干扰，规则已包含 `ID_MM_DEVICE_IGNORE`

### CAN FD 无法接收 BRS 帧

数据比特率必须高于名义比特率，否则 FDCAN 硬件不启用 BRSE 位，BRS=1 的 FD 帧会被丢弃。

### RX 超时错误

Windows 上 USB 读取超时的 errno 为 `10060`（不同于 Linux 的 `110`），SDK 已同时兼容两者。
