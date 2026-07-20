# CANable GUI 插件开发规范

> 本文档面向后续 AI 与人类开发者，描述如何为 CANable GUI 编写扩展插件。
>
> 参考实现：[`plugins/boot_upgrade/`](boot_upgrade/)（STM32G4 Bootloader 升级）
>
> 宿主实现：[`cangui/plugin_host.py`](../cangui/plugin_host.py)

---

## 目录

1. [设计目标](#1-设计目标)
2. [目录结构](#2-目录结构)
3. [插件生命周期](#3-插件生命周期)
4. [PluginContext 接口参考](#4-plugincontext-接口参考)
5. [Plugin 基类回调参考](#5-plugin-基类回调参考)
6. [编写一个新插件：最小步骤](#6-编写一个新插件最小步骤)
7. [i18n 规范](#7-i18n-规范)
8. [配置持久化规范](#8-配置持久化规范)
9. [CAN 收发规范](#9-can-收发规范)
10. [UI 集成规范](#10-ui-集成规范)
11. [线程模型与禁忌](#11-线程模型与禁忌)
12. [代码审查清单](#12-代码审查清单)
13. [常见错误](#13-常见错误)
14. [示例模板](#14-示例模板)

---

## 1. 设计目标

| 目标 | 实现 |
|---|---|
| **零侵入扩展** | 新增插件不修改 `cangui/` 任何核心文件 |
| **回调式解耦** | 插件通过实现可选方法订阅事件，宿主统一调度 |
| **生命周期可逆** | Tab 关闭即反初始化，重开即重建 |
| **配置统一管理** | 所有插件配置统一存到 `settings.json` |
| **插件隔离** | 单个插件异常不影响其他插件 |
| **自动发现** | 放到 `plugins/<name>/` 即被加载 |

---

## 2. 目录结构

项目根下：

```
canable/
├── cangui/                 # 核心代码（不应被插件修改）
│   ├── plugin_host.py      # PluginHost / Plugin / PluginContext
│   ├── main_window.py      # 主窗口（已接入插件宿主）
│   ├── i18n.py             # 翻译表 _TR（运行时可追加）
│   ├── worker.py           # CANWorker（线程安全队列）
│   └── ...
├── plugins/                # 插件根目录（自动扫描）
│   ├── __init__.py
│   ├── PLUGIN_DEV_GUIDE.md # 本文档
│   └── <plugin_name>/      # 每个插件一个子包
│       ├── __init__.py
│       ├── plugin.py       # 必须导出 create_plugin()
│       ├── widget.py       # UI 面板（可选，可拆分多个）
│       ├── protocol.py     # 协议层（可选，无 Qt 依赖）
│       └── ...
└── settings.json           # 主配置（含 plugin.* 命名空间）
```

### 命名约定

- **包名**：小写 + 下划线，如 `boot_upgrade`、`uds_diagnostics`、`dbc_viewer`
- **不以下划线开头**：`_xxx` 会被扫描器跳过
- **不以点开头**：隐藏目录会被跳过
- **必须含 `__init__.py`**：否则不被识别为 Python 包

---

## 3. 插件生命周期

```
应用启动
   ↓
load_all() 扫描 plugins/
   ↓
对每个插件：
   create_plugin()           # 工厂函数实例化
   plugin._bind(ctx)         # 注入 PluginContext
   plugin.init(ctx)          # 【子类可重写】注册 i18n key、读配置
   创建菜单 QAction           # checkable，默认未勾选
   ↓
从 settings.json 读取 plugin.active_list
   ↓
对上次 active 的插件：
   plugin.activate()         # 自动恢复 Tab
      ↓
      build_widget(ctx)     # 【子类必须实现】构造 UI
      ctx.add_tab(title, widget)
      on_activated()        # 【子类可重写】启动定时器等
      ↓
运行中（仅 active 插件接收事件）：
   on_connect()             # CAN 已连接
   on_disconnect()          # CAN 已断开
   on_frames(frames)        # 批量帧（100ms 节流）
   refresh_language()       # 语言切换
   ↓
用户关闭 Tab 或 取消菜单勾选：
   plugin.deactivate()
      ↓
      on_deactivating()     # 【子类可重写】停止定时器、发 CANCEL 等
      ctx.remove_tab(widget)
      teardown_widget(widget)  # 默认 widget.deleteLater()
      menu_action.setChecked(False)
   ↓
   写 settings.json：plugin.active_list 更新
   ↓
应用退出（closeEvent）：
   plugin.shutdown()         # 默认调 deactivate()
   plugin.active_list 立即落盘
```

### 状态可见性

| 状态 | `is_active()` | 接收 `on_frames`? | 接收 `on_connect`? | UI 存在? |
|---|---|---|---|---|
| 已加载未激活 | False | ❌ | ❌ | ❌ |
| 已激活 | True | ✅ | ✅ | ✅ |
| 关闭中 | — | ❌ | ❌ | 释放中 |

**关键原则**：插件 Tab 关闭后**完全停止接收事件**，不占用 CPU。

---

## 4. PluginContext 接口参考

`PluginContext` 是插件访问宿主能力的**唯一入口**。所有方法仅允许主线程调用。

### 4.1 Tab 管理

```python
def add_tab(self, title: str, widget: QWidget) -> int
```

将 widget 作为中心 Tab 添加，返回索引。Tab 自动获得关闭按钮（×）。

```python
def remove_tab(self, widget: QWidget) -> None
```

从中心 Tab 移除。通常无需手动调用，`deactivate()` 会自动处理。

```python
def set_tab_title(self, widget: QWidget, title: str) -> None
```

动态修改 Tab 标题（如显示当前文件名）。

### 4.2 CAN 收发

```python
def send_frame(self, frame: CANFrame) -> None
```

通过 worker 线程安全队列发送一帧。**线程安全**，可在主线程任意位置调用。

示例：
```python
from canable_sdk import CANFrame

frame = CANFrame(can_id=0x701, data=bytes([0x01, 0x00, 0x00, 0x40, 0x00, 0x01, 0x00, 0x40]),
                 extended=False, fd=False)
ctx.send_frame(frame)

# CAN FD 帧
frame = CANFrame(can_id=0x701, data=bytes(64), extended=False, fd=True)
frame.brs = True  # 比特率切换
ctx.send_frame(frame)
```

> ⚠️ **不要**自己创建 `ZDTCanable` 或调用 USB — 会与主 worker 冲突。

```python
def is_connected(self) -> bool
def is_fd_mode(self) -> bool       # 主界面 CAN FD 复选框状态
def get_bitrate(self) -> int       # 当前 nominal bitrate
```

### 4.3 配置持久化

```python
def get_setting(self, key: str, default=None)
def set_setting(self, key: str, value) -> None
```

自动加 `plugin.` 前缀，存到 `settings.json`。主程序 2s 防抖落盘，退出时立即 flush。

**命名约定**：`<plugin_name>.<field>`，例如 `boot_upgrade.host_id`，最终存为 `plugin.boot_upgrade.host_id`。

```python
# 读
host_id = ctx.get_setting("boot_upgrade.host_id", 0x701)

# 写（自动防抖）
ctx.set_setting("boot_upgrade.host_id", 0x7A5)
```

支持 JSON 可序列化的任意类型（int/float/str/list/dict/bool/None）。

### 4.4 UI 反馈

```python
def status_message(self, msg: str, timeout_ms: int = 0) -> None
```

- `timeout_ms > 0`：临时消息，timeout 后自动清除（适合"已发送"、"操作完成"）
- `timeout_ms == 0`：永久消息，覆盖状态栏左侧文本

### 4.5 i18n 国际化

```python
def register_i18n(self, key: str, zh: str, en: str) -> str
```

注册一个翻译 key 并返回当前语言文本。**应在 `init()` 中注册所有 key**。

```python
# plugin.py
def init(self, ctx):
    ctx.register_i18n("UDS.Title", "UDS 诊断", "UDS Diagnostics")
    ctx.register_i18n("UDS.Send", "发送请求", "Send Request")

def display_title(self):
    from cangui.i18n import _
    return _("UDS.Title")
```

### 4.7 Worker 线程独占任务 (v1.4.0+)

```python
def start_upgrade(self, task) -> None
```

将自定义任务提交到 **CAN worker 线程** 上执行。任务期间宿主暂停正常收发循环，
任务获得 `ZDTCanable` 的直接访问权。完成后 worker 自动恢复正常工作。

`task` 必须实现 `run(bus: ZDTCanable)` 方法。适用于需要帧级控制的长任务
（固件升级、诊断会话等）。

**使用模式**：

```python
from PySide6.QtCore import QObject, Signal

# 1) 定义信号载体 (QObject, 驻留主线程)
class MyTaskSignals(QObject):
    progress = Signal(int, int)
    log = Signal(str, str)
    finished = Signal(bool, str)

# 2) 定义任务 (plain object, 在 worker 线程执行)
class MyTask:
    def __init__(self, config, signals: MyTaskSignals):
        self._cfg = config
        self._sig = signals
        self.cancel_requested = False

    def cancel(self):
        """主线程调用：请求取消。"""
        self.cancel_requested = True

    def run(self, bus: ZDTCanable):
        """Worker 线程调用。bus 是宿主已打开的 ZDTCanable。
        期间可自由 send/receive，帧间需加 _poll_response() 节流。"""
        self._sig.log.emit("info", "task started")
        # ... 同步状态机 ...
        self._sig.finished.emit(True, "done")

# 3) Widget 中提交
self._signals = MyTaskSignals()
self._signals.progress.connect(self._on_progress)
self._signals.finished.connect(self._on_finished)
self._task = MyTask(config, self._signals)
ctx.start_upgrade(self._task)
```

**关键设计要点**：
- `task` 是 **plain object**（非 QObject），可在 worker 线程安全调用
- `signals` 是 **QObject**（驻留主线程），`emit()` 跨线程安全
- `task.run(bus)` 在 worker 线程同步执行，期间阻塞 worker 循环
- 帧间必须 `bus.receive(timeout=0.001)` 节流（1ms），防止板端帧间隔超时
- 取消通过 `task.cancel()` 设置标志位，`run()` 内周期性检查

参考实现：[`plugins/boot_upgrade/upgrader.py`](boot_upgrade/upgrader.py) 的 `UpgradeTask` +
`UpgradeSignals`。

### 4.8 只读主窗口访问

```python
@property
def main_window(self)
```

**仅用于只读访问**。

```python
# 允许
ctx.main_window.statusBar()
# 禁止
ctx.main_window._disconnect()
```

---

## 5. Plugin 基类回调参考

### 5.1 必须实现

```python
class MyPlugin(Plugin):
    name = "my_plugin"          # 唯一标识，小写下划线
    version = "0.1.0"           # 语义化版本

    def display_title(self) -> str:
        """Tab 标签与菜单显示文本。返回 i18n key 的翻译。"""
        from cangui.i18n import _
        return _("MyPlugin.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        """构造主 UI widget。每次 activate() 调用一次。"""
        return MyPluginPanel(ctx)
```

### 5.2 可选回调

所有回调都被 `try/except` 包裹，单个异常不影响其他插件，但会记录到日志。

```python
def init(self, ctx: PluginContext) -> None:
    """应用启动时调用一次。用于注册 i18n key、预加载资源。
    此时还未构建 UI，不能调用 ctx.add_tab()。"""

def on_activated(self) -> None:
    """Tab 已打开，UI 已显示。可在此启动 QTimer、订阅外部事件。
    on_connect 不会自动跟随，若启动时已连接，宿主会单独触发 on_connect。"""

def on_deactivating(self) -> None:
    """Tab 即将关闭。应停止定时器、发送 CANCEL、释放外部资源。
    widget 此时仍存在，但马上会被 deleteLater()。"""

def on_connect(self) -> None:
    """CAN 已连接。仅在 active 时收到。
    启动时已连接 → activate 后立即收到一次。"""

def on_disconnect(self) -> None:
    """CAN 已断开。仅在 active 时收到。
    应中止进行中的操作（如升级、诊断会话）。"""

def on_frames(self, frames: List[CANFrame]) -> None:
    """批量收到帧（100ms 节流，MAX_BATCH=1000）。
    包含 RX 与 TX echo。过滤 TX echo：if getattr(f, 'is_tx', False): continue"""

def refresh_language(self) -> None:
    """语言切换时调用。刷新所有可见文本。
    菜单文本与 Tab 标题由宿主自动刷新，子类只需刷新内部 widget。"""

def teardown_widget(self, widget: QWidget) -> None:
    """销毁 widget 前调用。默认 widget.deleteLater()。
    若有子线程或外部资源持有 widget 引用，应在此释放。
    注意：on_deactivating 已先执行，定时器应已停止。"""

def shutdown(self) -> None:
    """应用退出时调用。默认调 deactivate()。
    若插件需要单独清理（如关闭外部连接），可重写但必须调 super().shutdown()。"""
```

### 5.3 状态查询

```python
def is_active(self) -> bool
    """返回 True 当且仅当 Tab 已打开、widget 已构建。"""
```

---

## 6. 编写一个新插件：最小步骤

### 步骤 1：创建目录

```bash
mkdir plugins/my_plugin
touch plugins/my_plugin/__init__.py
```

### 步骤 2：编写 `plugin.py`

```python
# plugins/my_plugin/plugin.py
from __future__ import annotations
from typing import Optional

from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

from cangui.plugin_host import Plugin, PluginContext


class MyPluginPanel(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._ctx = ctx
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Hello from my plugin"))


class MyPlugin(Plugin):
    name = "my_plugin"
    version = "0.1.0"

    def init(self, ctx: PluginContext) -> None:
        ctx.register_i18n("MyPlugin.Title", "我的插件", "My Plugin")

    def display_title(self) -> str:
        from cangui.i18n import _
        return _("MyPlugin.Title")

    def build_widget(self, ctx: PluginContext) -> QWidget:
        return MyPluginPanel(ctx)


def create_plugin() -> MyPlugin:
    """PluginHost 通过此工厂函数实例化插件。必须导出。"""
    return MyPlugin()
```

### 步骤 3：测试

```bash
source .venv/bin/activate
python cangui.py
```

日志应显示：
```
[INFO] cangui.plugins: 已加载插件: my_plugin v0.1.0
```

菜单 **插件(P) → 我的插件** 勾选后，Tab 出现。

### 步骤 4：重启验证持久化

退出程序，重新启动 → 上次勾选的插件 Tab 自动恢复。

---

## 7. i18n 规范

### 7.1 Key 命名

格式：`<PluginName>.<Area>.<Meaning>`

| 示例 | 含义 |
|---|---|
| `Boot.Title` | Boot 插件总标题 |
| `Boot.Config` | Boot 插件配置区 |
| `Boot.FirmwareFile` | Boot 插件配置区·固件文件 |
| `UDS.ServiceID` | UDS 插件·服务 ID |

**前缀用大驼峰**（`Boot` 而非 `boot`），与主程序 `Menu.File` 风格一致。

### 7.2 注册时机

**必须在 `init()` 中注册所有 key**，不能等到 `build_widget()` 时再注册。原因：
- 菜单 QAction 在 `init()` 后立即创建，会调用 `display_title()`
- 若 key 未注册，`_("MyPlugin.Title")` 返回 key 本身（`"MyPlugin.Title"`）

### 7.3 使用方式

```python
# 注册
ctx.register_i18n("MyPlugin.Title", "我的插件", "My Plugin")

# 使用（任意位置）
from cangui.i18n import _
label.setText(_("MyPlugin.Title"))

# 切换语言时刷新
def refresh_language(self) -> None:
    self.label.setText(_("MyPlugin.Title"))
```

### 7.4 禁止事项

- ❌ 硬编码中文/英文字符串
- ❌ 修改 `cangui/i18n.py` 的 `_TR` dict（应通过 `ctx.register_i18n`）
- ❌ 在 `build_widget()` 中首次注册 key（时机已晚）

---

## 8. 配置持久化规范

### 8.1 命名空间

```
plugin.<plugin_name>.<field>
```

例如：
- `plugin.boot_upgrade.host_id`
- `plugin.boot_upgrade.fw_path`
- `plugin.uds_diagnostics.last_service`

### 8.2 使用模式

```python
# 写（自动 2s 防抖）
ctx.set_setting("my_plugin.field_name", value)

# 读（带默认值）
value = ctx.get_setting("my_plugin.field_name", default_value)
```

### 8.3 推荐封装

为避免每个控件都手写 key 字符串，推荐封装一个 `_ConfigStore`：

```python
class _ConfigStore:
    PLUGIN_NAME = "my_plugin"
    DEFAULTS = {"host_id": 0x701, "timeout_ms": 1000}

    def __init__(self, ctx):
        self._ctx = ctx

    def get(self, key: str):
        default = self.DEFAULTS.get(key)
        v = self._ctx.get_setting(f"{self.PLUGIN_NAME}.{key}", default)
        if isinstance(default, int) and isinstance(v, (int, float)):
            return int(v)
        return v

    def set(self, key: str, value) -> None:
        self._ctx.set_setting(f"{self.PLUGIN_NAME}.{key}", value)
```

参考：[`plugins/boot_upgrade/widget.py`](boot_upgrade/widget.py) 的 `_ConfigStore` 类。

### 8.4 类型校正

JSON 反序列化后 `int` 可能丢失，读取时应校正：

```python
v = ctx.get_setting("my_plugin.frame_size", 64)
if isinstance(v, (int, float)):
    v = int(v)
```

或用上面的 `_ConfigStore` 自动处理。

### 8.5 active 状态

插件 Tab 的开/关状态由 `PluginHost` 自动管理，存在 `plugin.active_list` 字段：

```json
{
  "plugin.active_list": ["boot_upgrade", "uds_diagnostics"]
}
```

**不要**自己读写这个字段。

---

## 9. CAN 收发规范

### 9.1 两种收发模式

| 模式 | 适用场景 | CAN 访问方式 | 帧间控制 |
|------|---------|-------------|---------|
| **普通模式** | 偶发帧、查询、监控 | `ctx.send_frame()` + `on_frames()` | 无 (宿主 100ms 批量) |
| **独占模式** | 批量传输、协议状态机 | `ctx.start_upgrade(task)` → `task.run(bus)` | 完全控制 (帧间节流、应答匹配) |

**普通模式**适合绝大多数插件。**独占模式**用于需要帧级时序控制的场景
（如固件升级中的 171 帧/块连续传输，需 1ms 帧间节流防止板端超时）。

### 9.2 发送 (普通模式)

```python
from canable_sdk import CANFrame

# Classic CAN
frame = CANFrame(can_id=0x701, data=b"\x01\x02\x03", extended=False, fd=False)
ctx.send_frame(frame)

# CAN FD
frame = CANFrame(can_id=0x701, data=bytes(64), extended=False, fd=True)
frame.brs = True  # 比特率切换（需主界面启用 CAN FD）
ctx.send_frame(frame)
```

### 9.3 接收 (普通模式)

通过 `on_frames` 回调，100ms 批量，最多 1000 帧/批：

```python
def on_frames(self, frames: List[CANFrame]) -> None:
    for f in frames:
        # 过滤 TX echo
        if getattr(f, "is_tx", False):
            continue
        # 过滤其他节点
        if f.can_id != self._expected_node_id:
            continue
        # 处理
        self._handle_response(f)
```

### 9.4 请求-响应模式 (普通模式)

CAN 是多主广播，没有内置的"请求-响应"。需要在插件内自己实现：

```python
class MyProtocol:
    def __init__(self):
        self._pending: Optional[asyncio.Future] = None  # 或自定义 Event

    def send_request(self, ctx, payload: bytes) -> "Future":
        self._pending = Future()
        ctx.send_frame(CANFrame(can_id=0x701, data=payload, extended=False, fd=False))
        # 启动超时定时器
        QTimer.singleShot(1000, self._on_timeout)
        return self._pending

    def on_response(self, frame: CANFrame):
        if self._pending is None or frame.can_id != 0x702:
            return
        self._pending.set_result(frame.data)
        self._pending = None

    def _on_timeout(self):
        if self._pending is not None:
            self._pending.set_exception(TimeoutError())
            self._pending = None
```

普通模式的请求-响应适合偶发帧。批量传输请用 §4.7 的独占模式。

### 9.5 CAN FD 模式检查

帧长 > 8 字节时，**必须**先检查主界面是否启用 CAN FD：

```python
if payload_len > 8 and not ctx.is_fd_mode():
    QMessageBox.warning(self, "错误", "请先在主界面勾选 CAN FD")
    return
```

---

## 10. UI 集成规范

### 10.1 主题适配

所有颜色必须用 `cangui.style` 的常量，**禁止**硬编码 hex：

```python
from cangui.style import BG_CARD, FG_ACCENT, FG_DIM, FG_WARN, FG_ERROR, BORDER

label.setStyleSheet(f"color: {FG_ACCENT};")
```

主题切换时主程序自动重新 apply QSS，但**手动 setStyleSheet 的样式不会被刷新**。建议：
- 优先用 QSS objectName 选择器（自动响应主题）
- 必须动态改色时，在 `refresh_language` 中也重设一次颜色

### 10.2 控件样式

用 QSS objectName 而非内联样式：

```python
btn = QPushButton("Start")
btn.setObjectName("primaryBtn")   # 在 style.py 中定义 #primaryBtn 样式
```

### 10.3 字体

等宽字体（日志区等）：

```python
from PySide6.QtGui import QFont
font = QFont("Monospace")
font.setStyleHint(QFont.StyleHint.TypeWriter)
log_view.setFont(font)
```

### 10.4 关闭确认

若插件有进行中操作（升级、诊断会话），重写 `confirm_close` 并在 `teardown_widget` 中处理：

```python
def confirm_close(self) -> bool:
    if self._busy:
        ret = QMessageBox.question(self, _("MyPlugin.Title"),
                                    _("MyPlugin.CloseConfirm"))
        return ret == QMessageBox.StandardButton.Yes
    return True

# plugin.py
def teardown_widget(self, widget):
    if self._panel and self._panel._busy:
        # 用户已确认，执行清理
        self._panel.abort_operation()
    widget.deleteLater()
```

---

## 11. 线程模型与禁忌

### 11.1 线程分布

| 对象 | 线程 |
|---|---|
| `Plugin` / `PluginContext` / UI widget | 主线程（Qt event loop） |
| `CANWorker` | worker 线程（QThread） |
| `Plugin.on_frames` | 主线程（100ms 定时器触发） |
| `UpgradeTask.run(bus)` | **worker 线程**（通过 `ctx.start_upgrade()` 提交） |

### 11.2 线程安全接口

| 接口 | 线程安全? | 说明 |
|---|---|---|
| `ctx.send_frame()` | ✅ | 内部走 worker `_send_queue`（带 mutex） |
| `ctx.start_upgrade(task)` | ✅ | task 提交到 worker，worker 取出执行 |
| `ctx.is_connected()` | ✅ | 读 bool，原子 |
| `ctx.get/set_setting()` | ✅ | 主线程 dict 读写 |
| 直接访问 `worker._xxx` | ❌ | 跨线程读写会 race |
| 直接调用 `worker.send()` | ❌ | 应通过 `ctx.send_frame()` |

### 11.3 长任务处理

#### 普通 QThread（无 CAN 访问）

适用于文件解析、数据计算等不涉及 CAN 的耗时操作：

```python
from PySide6.QtCore import QThread, Signal

class WorkerThread(QThread):
    progress = Signal(int)
    finished_ok = Signal(str)

    def run(self):
        for i in range(100):
            ...
            self.progress.emit(i)
        self.finished_ok.emit("done")

self._thread = WorkerThread()
self._thread.progress.connect(self._on_progress)
self._thread.start()
```

#### Worker 线程独占任务（需 CAN 帧级控制）

适用于固件升级、诊断会话等需要直接操作 CAN 总线的长任务。
**不需要创建新线程**，任务在宿主 worker 线程上执行：

```python
# 见 §4.7，task.run(bus) 在 worker 线程同步执行
ctx.start_upgrade(my_task)
```

优势：复用宿主已打开的 `ZDTCanable`，无需管理设备生命周期。

### 11.4 禁忌清单

- ❌ 创建第二个 `ZDTCanable` 实例（应通过 `ctx.start_upgrade(task)` 访问 bus）
- ❌ 在自己的 QThread 中打开 USB 设备
- ❌ 直接调用 `usb.core.find()` 或其他 USB API
- ❌ 修改 `cangui/` 核心文件（应通过 ctx 接口）
- ❌ 在 `init()` 中构建 UI（此时 Tab 还没注册）
- ❌ 在 `on_deactivating()` 后访问 `self._widget`（已被销毁）
- ❌ 跨线程访问 widget（widget 必须只在主线程操作）
- ❌ 重启 Qt 事件循环或调用 `QApplication.exec()`（主程序已在运行）

---

## 12. 代码审查清单

提交新插件前，逐项检查：

### 必须项

- [ ] 包名小写下划线，不以 `_` / `.` 开头
- [ ] 含 `__init__.py`
- [ ] `plugin.py` 导出 `create_plugin()` 函数
- [ ] `Plugin` 子类设置 `name` 和 `version`
- [ ] 实现 `display_title()` 返回 i18n 翻译文本
- [ ] 实现 `build_widget(ctx)` 返回 QWidget
- [ ] 所有用户可见文本用 `_()` 翻译，无硬编码中英文
- [ ] i18n key 在 `init()` 中注册

### 推荐项

- [ ] 实现了 `refresh_language()` 刷新所有文本
- [ ] 实现了 `on_connect()` / `on_disconnect()` 处理连接状态
- [ ] CAN 帧通过 `ctx.send_frame()` 发送，未直连 USB
- [ ] 配置通过 `ctx.get/set_setting()` 持久化
- [ ] 颜色用 `cangui.style` 常量
- [ ] 长任务用 QThread，未阻塞主线程

### 鲁棒性

- [ ] `on_frames` 中过滤 TX echo 与非目标 ID
- [ ] 有超时机制（CAN ACK 等待、外部资源）
- [ ] `on_deactivating` 中停止定时器、释放资源
- [ ] CAN FD 帧长 > 8 时检查 `ctx.is_fd_mode()`
- [ ] 异常被捕获，不让单个插件崩溃影响其他插件
- [ ] 关闭 Tab 时若有进行中操作，弹确认框

---

## 13. 常见错误

### 错误 1：`NameError: name 'os' is not defined`

**原因**：清理 import 时误删了用到的模块。

**修复**：检查所有 `import` 是否都被代码用到，反之亦然。Python 静态检查可用 `ruff` 或 `pyflakes`。

### 错误 2：Tab 关闭后再打开，状态丢失

**原因**：状态存在 widget 实例变量里，widget 被 `deleteLater()` 销毁。

**修复**：状态应存到 `ctx.set_setting()`，在 `build_widget()` 后从 `ctx.get_setting()` 恢复到新 widget。

### 错误 3：i18n key 切换语言后无变化

**原因**：`refresh_language()` 未重设控件文本，或 key 未在 `init()` 注册。

**修复**：
```python
def refresh_language(self) -> None:
    self.title_label.setText(_("MyPlugin.Title"))
    self.start_btn.setText(_("MyPlugin.Start"))
    # 所有 setText / setWindowTitle 都要重新调用
```

### 错误 4：插件加载失败

**日志**：`[ERROR] cangui.plugins: 加载插件 xxx 失败`

**原因**：
- `plugin.py` 语法错误 / import 错误
- 未导出 `create_plugin()` 函数
- `create_plugin()` 抛异常

**修复**：单独 `python -c "from plugins.xxx.plugin import create_plugin; create_plugin()"` 测试。

### 错误 5：发送帧后无响应

**排查**：
1. 主界面是否已连接？
2. `ctx.is_connected()` 返回 True?
3. CAN ID 是否正确？节点固件是否监听该 ID？
4. `on_frames` 是否被调用？加 `print(len(frames))` 调试
5. 帧过滤是否过严？检查 `f.can_id` 与 `is_tx`

### 错误 6：跨线程访问 widget 崩溃

**报错**：`QThread: Destroyed while thread is still running` 或 `QObject::setParent: ...`

**原因**：在 worker 线程直接操作 widget。

**修复**：用 `Signal` 将数据传到主线程：
```python
class Worker(QThread):
    result = Signal(str)
    def run(self):
        ...
        self.result.emit("done")  # 跨线程安全

# panel 中
worker.result.connect(self._on_result)  # 主线程槽
```

---

## 14. 示例模板

### 14.1 最小插件

见 [§6 编写一个新插件：最小步骤](#6-编写一个新插件最小步骤)。

### 14.2 完整功能插件

参考 [`plugins/boot_upgrade/`](boot_upgrade/)，包含：

| 文件 | 作用 |
|---|---|
| [`__init__.py`](boot_upgrade/__init__.py) | 包标识，声明 `__version__` |
| [`plugin.py`](boot_upgrade/plugin.py) | 插件入口，导出 `create_plugin()` |
| [`widget.py`](boot_upgrade/widget.py) | UI 面板 + `_ConfigStore` 配置管理 |
| [`protocol.py`](boot_upgrade/protocol.py) | 协议编解码（无 Qt 依赖） |
| [`upgrader.py`](boot_upgrade/upgrader.py) | 状态机 (`UpgradeSignals` QObject + `UpgradeTask` plain class) |

该插件实现了：
- 完整 Bootloader 协议（START / METADATA / DATA_START / DATA / DATA_END / VERIFY / REBOOT / CANCEL）
- **Worker 线程独占任务模式** (`ctx.start_upgrade(task)` → `task.run(bus)`)
- **帧间 1ms 节流** (`_poll_response`) + 中途 NACK 拦截
- **重同步机制** (`RESYNC_STATUS`: BLOCK_INDEX_MISMATCH / INVALID_FRAME / TIMEOUT)
- 同块校验重试 (`MAX_RETRIES=3`) + 同块重同步保护 (`MAX_SAME_BLOCK=5`)
- 节点失联检测 (`NODE_LOST_TIMEOUT=6s`)
- 会话级断点续传
- 响应过滤 (`_wait_block(expected_cmd)` 过滤过期帧)
- 配置持久化（CAN ID / HW ID / 版本 / 帧长 / 固件路径）
- 关闭确认 + 自动发 CANCEL
- 双语 i18n（中/英）+ 主题适配

可作为需要帧级 CAN 控制的插件的完整参考。
