# CANable 2.5 GUI

基于 PySide6 / Qt 6 的 CANable 2.5 USB-CAN 适配器上位机，支持 Classic CAN 和 CAN FD。

## 目录

- [CANable 2.5 GUI](#canable-25-gui)
  - [目录](#目录)
  - [硬件需求](#硬件需求)
  - [功能特性](#功能特性)
  - [环境搭建](#环境搭建)
    - [Windows](#windows)
    - [Linux](#linux)
  - [运行](#运行)
  - [打包 EXE](#打包-exe)
  - [目录结构](#目录结构)
  - [开发规范](#开发规范)
    - [国际化（i18n）](#国际化i18n)
    - [主题](#主题)
    - [设置持久化](#设置持久化)
    - [日志系统](#日志系统)
  - [常见问题](#常见问题)
    - [扫描不到设备](#扫描不到设备)
    - [CAN FD 无法接收 BRS 帧](#can-fd-无法接收-brs-帧)
    - [RX 超时错误](#rx-超时错误)

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
- **参数持久化** — 窗口布局、比特率、过滤器、发送列表等自动保存恢复
- **Trace 导出** — 支持 CSV / JSON Lines / ASC 格式
- **插件系统** — 中心 Tab 支持加载自定义插件（`plugins/` 目录）
- **日志系统** — 每次启动生成独立日志文件（`logs/canable_YYYYMMDD_HHMMSS.log`），终端 INFO + 文件 DEBUG

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

# 2. 使用 spec 文件打包（onedir 模式，UPX 已禁用以加快启动）
pyinstaller --clean --noconfirm CANable2.5.spec
```

输出：`dist/CANable2.5/CANable2.5.exe`

`CANable2.5.spec` 已配置：
- 资源文件：`logo.svg`、`check.svg`、`close.svg`、`close_hover.svg`、`libusb-1.0.dll`
- 隐藏导入：`usb.backend.libusb1`、`usb.backend.libusb0`、`PySide6.QtXml`

`settings.json` 和 `send_list.csv` 保存在 exe 同目录下，持久化不丢失。

## 目录结构

```
canable/
├── cangui.py                  # 入口脚本
├── cangui/                    # PySide6 GUI 模块
│   ├── __main__.py            # 模块入口（日志系统 + SIGINT 处理）
│   ├── main_window.py         # 主窗口（标准 QMainWindow，Dock 布局）
│   ├── title_bar.py           # 自定义标题栏（已废弃，保留兼容）
│   ├── worker.py              # CAN 工作线程
│   ├── trace.py               # Trace 面板（消息流表格）
│   ├── send.py                # 发送面板（单帧/周期发送，toggle 启停按钮）
│   ├── filters.py             # 过滤器 + 统计面板
│   ├── plugin_host.py         # 插件宿主（中心 Tab 加载插件）
│   ├── icons.py               # SVG 图标渲染（QSvgRenderer）
│   ├── i18n.py                # 中/英国际化
│   ├── style.py               # 样式（最小化 QSS，功能性样式）
│   └── logo.svg               # 应用图标
├── plugins/                   # 用户插件目录（自动加载）
├── canable_sdk/               # Python SDK
│   ├── driver.py              # ZDTCanable 主驱动
│   ├── frame.py               # CANFrame 数据类
│   ├── protocol.py            # ElmueSoft 协议解析
│   ├── constants.py           # USB ID、枚举常量
│   ├── bitrate.py             # 位时序表
│   └── cli.py                 # CLI 命令行工具
├── logs/                      # 运行日志（每次启动新建一个 .log）
├── CANGUI_I18N_SPEC.md        # 国际化开发规范
├── CANable2.5.spec            # PyInstaller 打包配置
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

样式使用 Qt 默认风格，`style.py` 仅定义必要的颜色常量（用于程序逻辑）和最小化 QSS（用于状态栏连接状态、总线负载级别等功能性样式）。控件不再使用自定义 QSS，保持原生平台外观。

### 设置持久化

主窗口的设置通过 `settings.json` 保存（2 秒防抖写入），包括：
- 比特率、CAN FD 模式、数据比特率
- 窗口几何信息、Dock 布局、表格列宽
- 过滤器、自动滚动、折叠模式
- 主题和语言偏好

对话框的几何信息通过 `QSettings` 自动保存恢复。

### 日志系统

每次应用启动会在 `logs/` 目录创建独立日志文件（`canable_YYYYMMDD_HHMMSS.log`）：
- **终端输出**：INFO 级别及以上
- **文件输出**：DEBUG 级别及以上（完整诊断信息）
- **格式**：`%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s`

日志规范：
- 只记录事件切换（连接/断开、启动/停止、错误、配置变更）
- 禁止记录高频逐帧数据（USB raw bytes、TX/RX 帧详情、协议解析细节）
- 第三方库（urllib3、PIL、usb._debug）默认压制到 WARNING 级别

## 常见问题

### 扫描不到设备

- **Windows**: 确认已用 Zadig 安装 WinUSB 驱动，设备管理器中 CANable 显示为 `WinUSB Device`
- **Linux**: 确认已执行 `install_udev.sh` 并重新插拔设备；ModemManager 可能干扰，规则已包含 `ID_MM_DEVICE_IGNORE`

### CAN FD 无法接收 BRS 帧

数据比特率必须高于名义比特率，否则 FDCAN 硬件不启用 BRSE 位，BRS=1 的 FD 帧会被丢弃。

### RX 超时错误

Windows 上 USB 读取超时的 errno 为 `10060`（不同于 Linux 的 `110`），SDK 已同时兼容两者。
