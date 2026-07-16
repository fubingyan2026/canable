# CANable 2.5 GUI

基于 PySide6 / Qt 6 的 CANable 2.5 USB-CAN 适配器上位机，支持 Classic CAN 和 CAN FD。

## 目录

- [硬件需求](#硬件需求)
- [功能特性](#功能特性)
- [环境搭建](#环境搭建)
  - [Windows](#windows)
  - [Linux](#linux)
- [运行](#运行)
- [打包 EXE](#打包-exe)
- [目录结构](#目录结构)
- [开发规范](#开发规范)
- [常见问题](#常见问题)

## 硬件需求

- CANable 2.5（ElmueSoft 固件）或兼容的 candleLight 设备
- USB 数据线
- CAN 总线（至少两个节点，含 120Ω 终端电阻）

## 功能特性

- **CAN 消息跟踪** — 实时显示接收/发送帧，支持折叠模式（按 CAN ID 去重）
- **周期发送** — 支持单帧发送和定时周期发送，可配置周期、FD/BRS
- **过滤器** — 按 CAN ID 范围和帧类型过滤，支持丢弃/放行动作
- **统计面板** — 按 ID 统计帧数、周期、总线负载
- **CAN FD** — 支持 CAN FD + BRS，独立配置数据比特率
- **中/英双语** — 运行时切换，无需重启
- **浅色/深色主题** — 马卡龙色系主题，运行时切换
- **参数持久化** — 窗口布局、比特率、过滤器、发送列表等自动保存恢复
- **Trace 导出** — 支持 CSV / JSON Lines / ASC 格式

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

# 2. 打包
pyinstaller --clean --noconfirm `
    --onefile --windowed `
    --name "CANable2.5" `
    --icon "cangui/logo.svg" `
    --add-data "cangui/logo.svg;cangui" `
    --add-data "cangui/check.svg;cangui" `
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
│   ├── __main__.py            # 模块入口
│   ├── main_window.py         # 主窗口
│   ├── worker.py              # CAN 工作线程
│   ├── trace.py               # Trace 面板（消息流表格）
│   ├── send.py                # 发送面板（单帧/周期发送）
│   ├── filters.py             # 过滤器 + 统计面板
│   ├── i18n.py                # 中/英国际化
│   ├── style.py               # 主题（马卡龙浅色/深色）
│   ├── logo.svg               # 应用图标
│   └── check.svg              # 复选框勾选图标
├── canable_sdk/               # Python SDK
│   ├── driver.py              # ZDTCanable 主驱动
│   ├── frame.py               # CANFrame 数据类
│   ├── protocol.py            # ElmueSoft 协议解析
│   ├── constants.py           # USB ID、枚举常量
│   ├── bitrate.py             # 位时序表
│   └── cli.py                 # CLI 命令行工具
├── CANGUI_I18N_SPEC.md        # 国际化开发规范
├── libusb-1.0.dll             # Windows USB 后端
├── install_udev.sh            # Linux udev 规则
└── requirements.txt
```

## 开发规范

### 国际化（i18n）

所有用户可见文本必须通过 `_()` 函数获取，禁止硬编码字符串。详见 [CANGUI_I18N_SPEC.md](CANGUI_I18N_SPEC.md)。

```python
# ✅ 正确
self.my_btn = QPushButton(_("Send.Add"))

# ❌ 错误
self.my_btn = QPushButton("添加")
```

添加新控件时需三步：
1. 在 `i18n.py` 的 `_TR` 字典中注册翻译键
2. 在 UI 代码中使用 `_()` 创建控件
3. 在对应面板的 `refresh_language()` 方法中刷新控件文本

### 主题

颜色常量定义在 `style.py` 中，支持浅色/深色两套调色板。所有颜色必须使用 `style.py` 导出的常量（如 `BG_CARD`、`FG_ACCENT`），禁止硬编码颜色值，以确保主题切换时一致。

### 设置持久化

主窗口的设置通过 `settings.json` 保存（2 秒防抖写入），包括：
- 比特率、CAN FD 模式、数据比特率
- 窗口几何信息、Dock 布局、表格列宽
- 过滤器、自动滚动、折叠模式
- 主题和语言偏好

对话框的几何信息通过 `QSettings` 自动保存恢复。

## 常见问题

### 扫描不到设备

- **Windows**: 确认已用 Zadig 安装 WinUSB 驱动，设备管理器中 CANable 显示为 `WinUSB Device`
- **Linux**: 确认已执行 `install_udev.sh` 并重新插拔设备；ModemManager 可能干扰，规则已包含 `ID_MM_DEVICE_IGNORE`

### CAN FD 无法接收 BRS 帧

数据比特率必须高于名义比特率，否则 FDCAN 硬件不启用 BRSE 位，BRS=1 的 FD 帧会被丢弃。

### RX 超时错误

Windows 上 USB 读取超时的 errno 为 `10060`（不同于 Linux 的 `110`），SDK 已同时兼容两者。
