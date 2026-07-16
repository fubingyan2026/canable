---
name: "canable-gui-style-optimized"
description: "Design style, performance, and i18n guide for CANable 2.5 PySide6 GUI. Focuses on professional macaron aesthetics, thread-safe high-throughput rendering, High-DPI details, and dict-based localization."
---

# CANable 2.5 上位机外观、性能与国际化设计指南

本指南定义 CANable 2.5 上位机（PySide6 / Qt6）的视觉美学体系、高频数据流渲染规范以及内置字典国际化架构，反映 `cangui/` 与 `canable_sdk/` 的当前实现。

> 实际代码即权威：本文件描述的规范均已在代码中落地，修改代码时请同步更新本文件。

---

## 一、 商业级视觉与美学系统

### 1.1 马卡龙色系主题（Light / Dark）

主题由 [cangui/style.py](file:///home/fubingyan/桌面/canable/cangui/style.py) 的 `_LIGHT` / `_DARK` 字典定义，运行时通过 `set_theme(name)` 切换并 `_update_globals()` 同步导出符号。

**浅色主题（Light）**：

| 变量 | 值 | 用途 |
| --------- | ------- | ----------------------- |
| BG_MAIN | #F5F0E8 | 窗口主背景（温暖柔和） |
| BG_CARD | #FFFFFF | 卡片/面板底色 |
| BG_INPUT | #FDFCFA | 输入框背景 |
| BG_HEADER | #EDE6DA | 表头/边侧工具栏 |
| BG_HOVER | #D2F0E3 | 鼠标悬停色（薄荷淡绿） |
| BG_SELECT | #BAE6D3 | 选中项背景 |
| BG_ACCENT | #7EC8A0 | 强调色 / 连接成功色 |
| BG_CORAL | #F2A999 | 珊瑚强调色（发送按钮） |
| BG_CORAL_H | #ED9481 | 珊瑚悬停色 |
| BG_SIDEBAR | #F8F4EC | 侧栏背景 |
| BG_STATUS | #D8F0E2 | 状态栏成功背景 |
| BG_TX | #D2F0E3 | 本机发送（TX）行背景 |
| BG_ERROR | #FFDCDC | 错误帧行背景 |
| FG_TEXT | #3A3A3A | 主文字 |
| FG_DIM | #9E9E9E | 次要/占位/禁用文本 |
| FG_ACCENT | #4C9B73 | 强调文字色（TX、选中态） |
| FG_CORAL | #D4745C | 珊瑚文字色 |
| FG_WARN | #D4A24C | 警告状态 / 数据更新高亮色 |
| FG_ERROR | #D4655C | 错误/断开状态 |
| FG_LINK | #5B9BD5 | 链接色 |
| BORDER | #E4DED4 | 细边框 |
| LOAD_LOW | #4C9B73 | 总线负载低（<40%） |
| LOAD_MID | #D4A24C | 总线负载中（40-75%） |
| LOAD_HIGH | #D4655C | 总线负载高（≥75%） |

**深色主题（Dark）**：

| 变量 | 值 | 用途 |
| --------- | ------- | ------------- |
| BG_MAIN | #2B2B2B | 窗口主背景 |
| BG_CARD | #333333 | 卡片/面板底色 |
| BG_INPUT | #252525 | 输入框背景 |
| BG_HEADER | #3A3A3A | 表头背景 |
| BG_HOVER | #2A4035 | 悬停背景 |
| BG_SELECT | #2A4A3A | 选中背景 |
| BG_ACCENT | #7EC8A0 | 强调色 |
| BG_CORAL | #F2A999 | 珊瑚强调色 |
| BG_CORAL_H | #ED9481 | 珊瑚悬停色 |
| BG_SIDEBAR | #2E2E2E | 侧栏背景 |
| BG_STATUS | #253530 | 状态栏成功背景 |
| BG_TX | #2A4035 | TX 行背景 |
| BG_ERROR | #3A2020 | 错误帧行背景 |
| FG_TEXT | #DDDDDD | 主文字 |
| FG_DIM | #888888 | 次要文本 |
| FG_ACCENT | #6ED8A0 | 强调色 |
| FG_CORAL | #D4745C | 珊瑚文字色 |
| FG_WARN | #D4A24C | 警告色 |
| FG_ERROR | #D4655C | 错误色 |
| FG_LINK | #5B9BD5 | 链接色 |
| BORDER | #444444 | 细边框 |
| LOAD_LOW | #6ED8A0 | 负载低 |
| LOAD_MID | #D4A24C | 负载中 |
| LOAD_HIGH | #D4655C | 负载高 |

### 1.2 CAN ID 着色

按 ID 哈希生成 HSL 色，让同 ID 帧颜色一致、不同 ID 视觉可分：

```python
def id_color(can_id: int, extended: bool = False) -> str:
    if extended:
        hue = ((can_id >> 16) ^ (can_id & 0xFFFF)) % 360
    else:
        hue = (can_id * 7) % 360
    return f"hsl({hue}, 50%, 60%)"
```

在 [trace.py data()](file:///home/fubingyan/桌面/canable/cangui/trace.py) 的 `ForegroundRole` 中按 `id_color(frame.can_id, frame.extended)` 着色。

---

### 1.3 高分屏与精细化交互规范

1. **High-DPI 适配**：在 [cangui/__main__.py:25-27](file:///home/fubingyan/桌面/canable/cangui/__main__.py#L25-L27) 中于 `QApplication` 构造前调用：
   ```python
   QApplication.setHighDpiScaleFactorRoundingPolicy(
       Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
   )
   ```
2. **图标必须使用 SVG**：`logo.svg`（窗口图标）、`check.svg`（QCheckBox 选中态，通过 QSS `image: url(...)` 引入）。严禁 PNG。
3. **QDockWidget 弹性布局**：发送面板、过滤面板均封装为 `QDockWidget`，支持拖动、浮动、关闭，并允许在底部/右侧停靠区切换。
4. **状态联动**：连接状态通过 `QLabel#statusLabel[connected="true|false"]` 动态属性切换颜色；总线负载通过 `QLabel#busLoad[level="low|mid|high"]` 三档变色。

---

## 二、 极限性能渲染规范

目标：在 CAN FD 5Mbps 数据相满载（~6000-8000 fps）下维持 UI 流畅，不卡死、不丢帧（5000 fps 以内）。

### 2.1 生产者-消费者解耦架构

**严禁**“一收报文就 emit Qt 信号刷新 TableView”。

**实际实现**（[cangui/worker.py](file:///home/fubingyan/桌面/canable/cangui/worker.py) + [cangui/main_window.py](file:///home/fubingyan/桌面/canable/cangui/main_window.py)）：

1. **后台 worker 线程（`CANWorker.run()`）**：
   - `bus.receive(timeout=0.01)` 阻塞 10ms 拉取一帧
   - 命中 `_pass()` 过滤后，加锁压入 `deque(maxlen=10000)`（`_frame_buffer`）
   - `_process_send_queue()` 同步处理主线程投递的发送请求（线程安全发送队列，非直接跨线程调用 `bus.send`）
2. **主线程批量定时器 `_batch_timer`**：
   - 间隔 **100ms**（稳定性优先，见 [main_window.py:67-70](file:///home/fubingyan/桌面/canable/cangui/main_window.py#L67-L70)）
   - 触发 `_on_batch_frames()` → `worker.take_batch()` 一次性取出全部
   - 单批上限 `MAX_BATCH=1000`，超出部分丢弃最新（避免 UI 单次刷新耗时过长）
3. **批量日志写入**：trace 面板的 `_log_buffer` 同样走 `deque(maxlen=1000)`，5 秒定时落盘 + 5MB 轮转，避免高频写盘。

### 2.2 QAbstractTableModel 优化

实现见 [cangui/trace.py TraceModel](file:///home/fubingyan/桌面/canable/cangui/trace.py)：

- **预格式化**：`add_frame()` 在入队前调用 `_format_row()` 生成 11 列纯字符串列表存入 `_text` deque，`data()` 仅做 `self._text[row][col]` 返回，零运行时格式化。
- **ASCII 列优化**：使用模块级 `_ASCII_TRANSLATION = bytes.maketrans(...)` 预生成 256 字节查找表，`frame.data.translate(_ASCII_TRANSLATION)` 一次转换，避免逐字节 `chr()` 调用。
- **role 短路**：`data()` 仅响应 `DisplayRole`/`BackgroundRole`/`ForegroundRole`/`TextAlignmentRole`/`ToolTipRole`，其他立即返回 `None`。
- **行高统一**：`setUniformRowHeights(True)`。
- **网格隐藏**：`setShowGrid(False)` + QSS `gridline-color: transparent`。
- **最大行数**：`DEFAULT_MAX_ROWS = 1000`（[trace.py:22](file:///home/fubingyan/桌面/canable/cangui/trace.py#L22)），超出时 popleft 旧帧。
- **collapse 模式**：按 `(can_id, extended)` 折叠，重复 ID 只 `dataChanged` 更新，不新增行，CPU 降 50%。

### 2.3 字典清理（避免无限增长）

`_counts` / `_last_ts` / `_period` / `_id_vis` 在 deque evict 旧帧时同步清理（[trace.py:177-192](file:///home/fubingyan/桌面/canable/cangui/trace.py#L177-L192)）：

```python
old_cid = (old.can_id, old.extended)
self._id_vis[old_cid] = self._id_vis.get(old_cid, 0) - 1
if self._id_vis.get(old_cid, 0) <= 0:
    self._id_vis.pop(old_cid, None)
    self._counts.pop(old_cid, None)
    self._last_ts.pop(old_cid, None)
    self._period.pop(old_cid, None)
for k in list(self._id_vis.keys()):
    self._id_vis[k] -= 1
    if self._id_vis[k] < 0:
        self._id_vis.pop(k, None)
```

### 2.4 信号节流

- `bus_stats` 信号：仅在有帧或负载非零时 emit，100ms 节流（[worker.py:308-312](file:///home/fubingyan/桌面/canable/cangui/worker.py#L308-L312)）
- `noack_warning`：5 秒节流，避免 LEC 粘滞刷屏
- `error`（BUS-OFF）：2 秒节流；连续 10 次触发自动 `recover()`

### 2.5 极限吞吐量参考

详见 [PERFORMANCE_ANALYSIS.md](file:///home/fubingyan/桌面/canable/PERFORMANCE_ANALYSIS.md)。

| 场景 | 吞吐 | 评价 |
|------|------|------|
| 车载 CAN 总线 | <3000 fps | 完全够用 |
| 工业自动化 | 1000-5000 fps | 完全够用 |
| 实验室压力测试 | 5000-8000 fps | 临界可用 |
| 极限 FD 满载 | >8000 fps | 有丢帧 |

---

## 三、 QSS 与视觉反馈

### 3.1 扁平化无嵌套选择器

QSS 全部由 [style.py `_make_qss()`](file:///home/fubingyan/桌面/canable/cangui/style.py) 动态生成，使用 `f-string` 注入调色板。规则：

- **直接类名或 `#objectName` 选择器**，避免深度嵌套
- 唯一允许的嵌套：`QGroupBox QLabel` / `QGroupBox QCheckBox`（强制透明背景，避免突兀色块）
- 滚动条扁平化，hover 加宽、变色：

```css
QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background-color: #E4DED4;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background-color: #9E9E9E;
}
```

### 3.2 关键控件样式约定

- **`#connectBtn`**：`checked` 时 `BG_ACCENT` 绿底白字，未选中时普通卡片色
- **`#sendBtn`**：`BG_ACCENT` 绿底白字加粗，无 hover 颜色跳变
- **`QCheckBox::indicator:checked`**：`FG_ACCENT` 绿底 + `check.svg` 白色对勾
- **禁用态**：`QComboBox:disabled`/`QLineEdit:disabled` 等使用 `BG_HEADER` 背景 + `FG_DIM` 文字，视觉上明确不可用
- **错误/TX 行背景**：`BG_ERROR`（淡红）/`BG_TX`（淡绿），通过 `BackgroundRole` 返回

### 3.3 数据突变高亮

> 当前实现以 `id_color()` 着色 + TX 行绿色背景区分，尚未实现 300ms 老化闪烁。
> 如需新增：在 `add_frame()` 中对 collapse 模式覆盖更新时设置 `state="updated"` 动态属性，300ms 后清除。

---

## 四、 内置字典国际化（i18n）架构

实际实现位于 [cangui/i18n.py](file:///home/fubingyan/桌面/canable/cangui/i18n.py)。**不使用外部 JSON 文件**，翻译表内置在 Python 模块中，避免运行时磁盘 I/O。

### 4.1 翻译表结构

```python
_lang = "zh"  # 默认中文
_TR: dict[str, dict[str, str]] = {}

_TR.update({
    "Menu.File":      {"zh": "文件(&F)",  "en": "&File"},
    "Left.BPS":        {"zh": "bps",       "en": "bps"},
    "Trace.Clear":     {"zh": "清空",      "en": "Clear"},
    # ...
})
```

**键命名规范**：`模块.含义`，如 `Left.BPS`、`Trace.Clear`、`Error.NotConnected`、`File.SaveTraceTitle`。

### 4.2 翻译函数

```python
def _(key: str) -> str:
    entry = _TR.get(key)
    return entry.get(_lang, key) if entry else key
```

- 未命中返回 key 本身（便于发现遗漏）
- 支持中英双语：`zh` / `en`

### 4.3 语言切换信号

```python
class _Signal(QObject):
    lang_changed = Signal(str)

_signal = _Signal()
language_changed = _signal.lang_changed  # 模块级导出

def set_language(lang: str):
    global _lang
    _lang = lang
    language_changed.emit(lang)  # 通知所有界面刷新
```

### 4.4 界面刷新机制

每个 UI 面板必须实现 `refresh_language()`，监听 `language_changed` 信号统一刷新：

```python
# main_window.py
language_changed.connect(self._refresh_language)

def _refresh_language(self):
    self.setWindowTitle(_("App.Title"))
    self.connect_btn.setText(_("Left.ConnectDevice"))
    # 重建 combo 时必须 blockSignals，避免误触 currentIndexChanged
    self.bitrate_combo.blockSignals(True)
    self.bitrate_combo.clear()
    for b in self.BITRATES:
        self.bitrate_combo.addItem(f"{b:,} {_('Left.BPS')}", b)
    self.bitrate_combo.blockSignals(False)
    # 子面板
    self.trace_panel.refresh_language()
    self.send_panel.refresh_language()
    self.filter_panel.refresh_language()
```

**关键约束**：
- 所有用户可见字符串必须通过 `_("key")` 获取，严禁硬编码
- 重建 `QComboBox` 时必须 `blockSignals(True/False)`，避免误触发 `currentIndexChanged`
- 新增控件时同步在 `refresh_language()` 中更新

详见 [CANGUI_I18N_SPEC.md](file:///home/fubingyan/桌面/canable/CANGUI_I18N_SPEC.md)。

---

## 五、 线程安全与稳定性

### 5.1 跨线程发送

**严禁**主线程直接调用 `worker._bus.send()`（与子线程 `receive()` 竞争）。

实际实现（[worker.py:193-229](file:///home/fubingyan/桌面/canable/cangui/worker.py#L193-L229)）：

```python
@Slot(object)
def send(self, frame: CANFrame):
    """主线程调用：仅入队"""
    with QMutexLocker(self._send_mutex):
        self._send_queue.append(frame)

def _process_send_queue(self):
    """子线程 run() 中调用：实际发送"""
    with QMutexLocker(self._send_mutex):
        pending = list(self._send_queue)
        self._send_queue.clear()
    for frame in pending:
        self._bus.send(frame)
```

### 5.2 线程退出保障

`_disconnect()` 必须等待 worker 线程真正退出，避免僵尸线程（[main_window.py:421-439](file:///home/fubingyan/桌面/canable/cangui/main_window.py#L421-L439)）：

```python
with QMutexLocker(worker._mutex):
    worker._running = False
    worker._connected = False
thread.wait(2000)
if thread.isRunning():
    logger.warning("worker 线程未在 2s 内退出，强制终止")
    thread.terminate()
    thread.wait(1000)
```

### 5.3 USB 错误自愈

- pipe 错误（overflow）：清空 endpoint buffer，调用 `on_overflow` 回调
- BUS-OFF：连续 10 次自动 `recover()`
- NO-ACK：5 秒节流提示，不自动恢复（单设备无应答属正常）

### 5.4 日志与配置路径

打包后（PyInstaller）需用 `sys.frozen` 判断，避免写到临时解压目录：

```python
def _log_dir() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
```

- trace 日志：`<可执行目录>/trace_log.csv`，5MB 轮转
- 发送列表：`<可执行目录>/send_list.csv`
- 设置：`<可执行目录>/settings.json`
- 对话框几何：`QSettings` 存到系统标准位置（`~/.config/canable/CANable2.5.conf`）

---

## 六、 最佳实践指引

1. **外观交互**：
   - TableView 右键菜单（复制、添加到发送列表）需通过 `customContextMenuRequested` 信号实现
   - `QDockWidget` 布局通过 `saveState()`/`restoreState()` 持久化
2. **性能基准**：
   - 严禁在 `refresh_language()` 之外硬编码任何带语言属性的界面字符串
   - 严禁主线程直接访问 `worker._bus`
   - 严禁“一收报文就发 Qt 信号并刷新 TableView”
   - 所有缓冲区必须有 `maxlen`，所有计数字典必须有 evict 清理
3. **代码质量**：
   - 解包变量严禁用 `_`（会遮蔽 i18n 翻译函数），用 `_selected_filter` 等
   - `import` 必须在文件顶部，禁止在异常分支内 `import`
   - 布尔解析用宽松函数 `_parse_bool()`，兼容 `true/1/yes`

---

## 七、 关键文件索引

| 文件 | 作用 |
|------|------|
| [cangui.py](file:///home/fubingyan/桌面/canable/cangui.py) | 启动脚本，配置 logging |
| [cangui/__main__.py](file:///home/fubingyan/桌面/canable/cangui/__main__.py) | QApplication 入口，High-DPI 设置 |
| [cangui/main_window.py](file:///home/fubingyan/桌面/canable/cangui/main_window.py) | 主窗口，UI 布局 + 信号槽 + 批量刷新 |
| [cangui/worker.py](file:///home/fubingyan/桌面/canable/cangui/worker.py) | CAN I/O 工作线程，收发 + 过滤 + 负载统计 |
| [cangui/trace.py](file:///home/fubingyan/桌面/canable/cangui/trace.py) | Trace 面板，QAbstractTableModel + CSV 日志 |
| [cangui/send.py](file:///home/fubingyan/桌面/canable/cangui/send.py) | 发送面板，周期发送 + CSV 持久化 |
| [cangui/filters.py](file:///home/fubingyan/桌面/canable/cangui/filters.py) | 过滤器面板，ID 范围过滤 |
| [cangui/style.py](file:///home/fubingyan/桌面/canable/cangui/style.py) | 主题调色板 + QSS 生成 |
| [cangui/i18n.py](file:///home/fubingyan/桌面/canable/cangui/i18n.py) | 内置字典翻译表 + 语言切换信号 |
| [canable_sdk/](file:///home/fubingyan/桌面/canable/canable_sdk/) | USB-CAN 驱动 SDK |
| [PERFORMANCE_ANALYSIS.md](file:///home/fubingyan/桌面/canable/PERFORMANCE_ANALYSIS.md) | 极限吞吐量性能分析报告 |
| [CANGUI_I18N_SPEC.md](file:///home/fubingyan/桌面/canable/CANGUI_I18N_SPEC.md) | 国际化规范（键命名、刷新机制） |
| [CANABLE_PROTOCOL_SPEC.md](file:///home/fubingyan/桌面/canable/CANABLE_PROTOCOL_SPEC.md) | USB-CAN 协议规范（表格形式） |

---
### --- END OF FILE SKILL.md ---
