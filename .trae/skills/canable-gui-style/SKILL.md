---
name: "canable-gui-style-optimized"
description: "Design style, performance, and JSON-i18n guide for CANable 2.5 PyQt6 GUI. Focuses on professional macaron aesthetics, fluid multi-threading, High-DPI details, and externalized localization."
---

# CANable 2.5 上位机外观、性能与国际化设计指南

本指南定义了 CANable 2.5 上位机的商业级视觉美学体系、高频数据流渲染规范以及外置 JSON 国际化架构，旨在指导 AI 构建兼具“低开销、高流畅度”与“精致工业感”的分析界面。

---

## 一、 商业级视觉与美学系统

### 1.1 马卡龙色系主题（Light / Dark）

**浅色主题（Light）**：
| 变量      | 值      | 用途                    |
| --------- | ------- | ----------------------- |
| BG_MAIN   | #F5F0E8 | 窗口主背景（温暖柔和）  |
| BG_CARD   | #FFFFFF | 卡片/卡套底色           |
| BG_INPUT  | #FDFCFA | 输入框背景              |
| BG_HEADER | #EDE6DA | 表头/边侧工具栏         |
| BG_HOVER  | #D2F0E3 | 鼠标悬停色（薄荷淡绿）  |
| BG_SELECT | #BAE6D3 | 选中项背景              |
| BG_ACCENT | #7EC8A0 | 强调色/连接成功色       |
| FG_TEXT   | #3A3A3A | 主文字                  |
| FG_DIM    | #9E9E9E | 次要/占位文本           |
| FG_WARN   | #D4A24C | 警告状态/数据更新高亮色 |
| FG_ERROR  | #D4655C | 错误/断开状态           |
| BORDER    | #E4DED4 | 细边框                  |

**深色主题（Dark）**：
| 变量      | 值      | 用途          |
| --------- | ------- | ------------- |
| BG_MAIN   | #222222 | 窗口主背景    |
| BG_CARD   | #2B2B2B | 卡片/面板底色 |
| BG_INPUT  | #1E1E1E | 输入框背景    |
| BG_HEADER | #2F2F2F | 表头背景      |
| BG_HOVER  | #2A4035 | 悬停背景      |
| BG_SELECT | #244C3A | 选中背景      |
| FG_TEXT   | #DDDDDD | 主文字        |
| FG_DIM    | #777777 | 次要文本      |
| FG_ACCENT | #6ED8A0 | 强调色        |
| FG_WARN   | #D4A24C | 警告色        |
| FG_ERROR  | #D4655C | 错误色        |
| BORDER    | #333333 | 细边框        |

---

### 1.2 高分屏与精细化交互规范

1. **High-DPI 与矢量化适配**：
   * 应用程序初始化时必须执行以下适配策略，防止高分屏下布局错位：
     ```python
     QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
     ```
   * 界面所有图标、指示灯按钮等元素**必须采用 SVG 格式**，严禁使用 PNG 等像素格式。
2. **QDockWidget 弹性布局**：
   * 将控制区、发送区、统计区等封装为 `QDockWidget`，允许用户拖动、浮动和拼合，提供多显示器自适应体验。
3. **呼吸灯与动态微动效**：
   * 连接状态指示器（LED）需应用 `QGraphicsDropShadowEffect`，连接成功时展示微弱的绿色发光（Glow）效果。
   * 按钮 Hover 态采用 `QVariantAnimation` 渐变切换，避免视觉上的生硬跳变。

---

## 二、 极限性能渲染规范

在高频总线负载下，界面必须维持在流畅帧率（如 30fps~60fps），严禁卡死和丢帧。

### 2.1 生产者-消费者解耦架构

* **原则**：严禁“一收报文就发 Qt 信号并刷新 TableView”的驱动模式。
* **实现**：
  1. **后台线程（只收数据）**：从硬件通道拉取原始数据，压入线程安全的双端队列 `collections.deque(maxlen=10000)`。
  2. **UI 线程（批量更新）**：启动一个 $30\text{ms}$ 的 `QTimer`。定时器触发时，单次从队列中批量提取积累的所有报文，在 `QAbstractTableModel` 中执行一轮集中更新并仅触发一次 `layoutChanged.emit()`。

### 2.2 `QAbstractTableModel` 优化

```python
# 数据预处理：在插入 Model 缓存之前，后台线程提前完成数据格式化，data() 仅做极速返回。
class CanMsgModel(QAbstractTableModel):
    def data(self, index, role):
        if not index.isValid():
            return None
        # 仅响应高频渲染的核心 Role，其他不关心的 Role 立即返回 None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._cache[index.row()][index.column()] # 预转换后的纯 String
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        # 用于实现数据突变高亮
        elif role == Qt.ItemDataRole.BackgroundRole:
            return self._get_aging_color(index.row())
        return None
```

### 2.3 视图渲染减负

1. 对于大容量表格，启用统一行高，大幅降低高度重算开销：
   ```python
   table_view.setUniformRowHeights(True)
   ```
2. 禁用单元格虚线网格以提升重绘效率：
   ```python
   table_view.setShowGrid(False)
   ```
3. 动态限制 Table 视窗的最大行数（如保留最新 2000 行），将更早的数据静默释放，避免内存无限制增长。

---

## 三、 QSS 与视觉反馈（细节）

### 3.1 扁平化无嵌套选择器

为了避免 Qt 样式引擎在频繁重绘时遍历对象树带来的开销，QSS 样式应避免深度嵌套：

```css
/* 推荐：直接类名或 ID 选择器 */
QPushButton#actionBtn {
    background-color: #F2A999;
    color: #FFFFFF;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton#actionBtn:hover {
    background-color: #E29989;
}

/* 扁平化的 QScrollBar 滚动条，hover 时加宽，不占表格区域 */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #E4DED4;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #7EC8A0;
}
```

### 3.2 数据老化闪烁效果（Data Aging）

在“覆盖模式（Overwrite）”下，当某行 ID 的数据发生变动时，需要短暂高亮。
* **QSS 配合动态属性**：
  ```css
  QTableView::item[state="updated"] {
      background-color: rgba(242, 169, 153, 0.4); /* 淡粉橙色提示变动 */
      transition: background-color 0.3s;
  }
  ```
* **逻辑控制**：改变属性后，调用 `widget.style().unpolish(widget)` 及 `polish()` 进行快速重绘，并在 300ms 后清除该更新状态恢复默认。

---

## 四、 外置 JSON 国际化（i18n）架构

为了实现语言文本与业务逻辑的彻底解耦，必须将翻译文本外置于 JSON 文件中，并通过单例管理器加载。

### 4.1 JSON 语言包规范
语言文件集中存放于 `locales/` 目录下，命名为 `{lang_code}.json`（例如 `zh_CN.json`、`en_US.json`）。

```json
/* locales/zh_CN.json */
{
  "metadata": { "language": "zh_CN", "name": "简体中文" },
  "MainWindow": {
    "title": "CANable 2.5 分析仪",
    "menu_file": "文件(&F)",
    "menu_connect": "连接总线"
  },
  "TransmitPanel": {
    "send_btn": "发送",
    "period_ms": "周期(ms)"
  }
}
```

### 4.2 语言管理器（I18nManager）

通过全局单例管理器读取并提供翻译检索，避免重复的磁盘 I/O。

```python
import os
import json
from PyQt6.QtCore import QObject, pyqtSignal

class I18nManager(QObject):
    language_changed = pyqtSignal()  # 语言切换信号
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.translations = {}
        self.current_lang = "zh_CN"
        self.load_language(self.current_lang)

    def load_language(self, lang_code: str):
        file_path = f"locales/{lang_code}.json"
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations = json.load(f)
                self.current_lang = lang_code
                self.language_changed.emit()  # 通知所有界面重绘文本
            except Exception as e:
                print(f"Error loading translation: {e}")

    def tr(self, section: str, key: str, default: str = "") -> str:
        """多层级检索翻译文本，例如: tr('MainWindow', 'title')"""
        return self.translations.get(section, {}).get(key, default or f"[{key}]")
```

### 4.3 界面更新机制
每个 UI 组件/面板必须实现 `retranslate_ui()` 方法。当检测到 `language_changed` 信号时，统一触发刷新。

```python
class TransmitPanel(QDockWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        # 绑定语言变动事件
        I18nManager.instance().language_changed.connect(self.retranslate_ui)
        self.retranslate_ui()

    def retranslate_ui(self):
        m = I18nManager.instance()
        self.setWindowTitle(m.tr("TransmitPanel", "panel_title", "发送控制"))
        self.sendBtn.setText(m.tr("TransmitPanel", "send_btn", "发送"))
        self.periodLabel.setText(m.tr("TransmitPanel", "period_ms", "周期(ms)"))
```

---

## 五、 最佳实践指引

1. **外观交互**：
   * 必须为 TableView 等提供右键上下文菜单（右键复制、右键添加到发送列表等），且菜单项文本需同步注册在 `locales` 的 JSON 中。
   * 采用 `QDockWidget` 管理功能区域，利用 `saveState()` 在程序退出时记住用户的自定义停靠布局 [2.3]。
2. **性能与解耦基准**：
   * 严禁在 `retranslate_ui()` 之外硬编码任何带有语言属性的界面字符串。
   * 切换语言引发的界面文本变更应全部限制在 UI 线程的 `retranslate_ui()` 函数中同步执行，不允许干扰后台的数据接收缓冲。

---
### --- END OF FILE SKILL.md ---