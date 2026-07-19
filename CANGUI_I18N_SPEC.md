# CANable GUI 国际化（i18n）开发规范

## 核心原则

**所有用户可见文本必须通过 `_()` 函数获取，禁止硬编码字符串。**

这包括：按钮文本、标签、菜单项、对话框标题、工具提示、状态栏文本、表格表头、占位符文本、错误消息等。

---

## 1. 翻译键命名规范

### 格式：`模块.含义`

```
区域.功能描述
```

| 区域 | 说明 | 示例 |
|------|------|------|
| `Menu.*` | 菜单栏 | `Menu.File`, `Menu.Tools` |
| `File.*` | 文件操作 | `File.SaveTraceTitle`, `File.TraceSaved` |
| `Left.*` | 左侧面板 | `Left.Bitrate`, `Left.NoDevice` |
| `Send.*` | 发送面板 | `Send.Add`, `Send.HdrID` |
| `Send.Dlg*` | 发送对话框 | `Send.DlgID`, `Send.DlgFD` |
| `Trace.*` | 跟踪面板 | `Trace.Clear`, `Trace.ID` |
| `Filter.*` | 过滤面板 | `Filter.Add`, `Filter.Drop` |
| `Filter.Dlg*` | 过滤对话框 | `Filter.DlgTitle`, `Filter.DlgExt` |
| `Stat.*` | 统计面板 | `Stat.TotalFrames`, `Stat.HdrCount` |
| `Status.*` | 状态栏 | `Status.Connected`, `Status.FPS` |
| `Error.*` | 错误消息 | `Error.NotConnected`, `Error.BusOffRecover` |
| `Window.*` | 窗口/Dock 标题 | `Window.SendMessages` |
| `Theme.*` | 主题 | `Theme.Light`, `Theme.Dark` |
| `Lang.*` | 语言名称 | `Lang.Chinese`, `Lang.English` |

### 命名规则

- 使用 PascalCase，用点号分隔区域和具体键名
- 对话框内的控件用 `模块.Dlg` 前缀区分
- 表格表头用 `模块.Hdr` 前缀
- 状态文本用动词过去式或名词：`Send.StartAll` / `Send.StopAll`
- 错误消息以名词短语开头：`Error.NotConnected`

---

## 2. 添加新控件的完整步骤

### 步骤 1：在 `i18n.py` 中注册翻译键

```python
_TR.update({
    # ...
    "Send.DlgNewField":  {"zh": "新字段:",  "en": "New Field:"},
})
```

### 步骤 2：在 UI 代码中使用 `_()` 创建控件

```python
# ✅ 正确
self.my_label = QLabel(_("Send.DlgNewField"))

# ❌ 错误
self.my_label = QLabel("新字段:")
```

### 步骤 3：在 `refresh_language()` 中刷新控件文本

```python
def refresh_language(self):
    self.my_label.setText(_("Send.DlgNewField"))
```

**这一步不可省略！** `_()` 在创建时只执行一次，语言切换后不会自动更新。

---

## 3. 语言切换刷新清单

以下控件类型在语言切换时**必须**主动刷新：

| 控件类型 | 刷新方法 | 常见遗漏 |
|----------|----------|----------|
| QPushButton | `setText()` | - |
| QLabel | `setText()` | 表单标签（QFormLayout 的 label） |
| QCheckBox | `setText()` | - |
| QGroupBox | `setTitle()` | - |
| QTabWidget | `setTabText(idx, ...)` | **容易遗漏** |
| QDockWidget | `setWindowTitle()` | - |
| QMenu | `setTitle()` | - |
| QAction | `setText()` | - |
| QComboBox | `clear()` + 重新 `addItem()` | 需恢复当前选中项 |
| QTableWidget 表头 | `setHorizontalHeaderLabels()` | - |
| QAbstractTableModel 表头 | 更新 `_header_labels` + emit `headerDataChanged` | - |
| QStatusBar 标签 | `setText()` | 动态文本需用当前值重新格式化 |
| QLineEdit placeholder | `setPlaceholderText()` | - |
| QToolTip | 在 `refresh_language()` 中重新 `setToolTip()` | **容易遗漏** |
| QDialog title | `setWindowTitle()` | - |

### 特殊情况

- **QComboBox 刷新**：必须 `clear()` 后重新 `addItem()`，同时保存/恢复 `currentData()`
- **QListWidget 无设备项**：需要检查 `item.flags() & Qt.ItemIsEnabled` 判断是否为禁用项，然后 `item.setText()`
- **动态文本**（如 `f"已连接 @ {bitrate}"`）：需要在刷新时用当前状态值重新拼接

---

## 4. 常见错误与反面教材

### 错误 1：硬编码中文字符串

```python
# ❌ 错误
self.status_label.setText("未连接，无法发送")

# ✅ 正确
self.status_label.setText(_("Error.NotConnected"))
```

### 错误 2：创建时用了 `_()` 但忘记在 `refresh_language()` 中刷新

```python
# 创建时正确
self.my_btn = QPushButton(_("Send.Add"))

# ❌ 但 refresh_language() 中遗漏了
def refresh_language(self):
    self.other_btn.setText(_("Send.Edit"))
    # 忘记刷新 my_btn！

# ✅ 正确
def refresh_language(self):
    self.my_btn.setText(_("Send.Add"))
    self.other_btn.setText(_("Send.Edit"))
```

### 错误 3：Combo 选项切换语言后不刷新

```python
# ❌ 错误：combo 选项在切换语言后仍是旧语言
# ✅ 正确：在 refresh_language() 中重建 combo
def refresh_language(self):
    current = self.bitrate_combo.currentData()
    self.bitrate_combo.clear()
    bps = _("Left.BPS")
    for b in self.BITRATES:
        self.bitrate_combo.addItem(f"{b:,} {bps}", b)
    self.bitrate_combo.setCurrentIndex(self.bitrate_combo.findData(current))
```

### 错误 4：Tab 标签不刷新

```python
# ❌ Tab 标签只在创建时设置，切换语言后不变
center_tabs.addTab(self.trace_panel, _("Trace.TabLabel"))

# ✅ 在 refresh_language() 中添加
self._center_tabs.setTabText(0, _("Trace.TabLabel"))
```

### 错误 5：使用 `QListWidgetItem.isEnabled()`

```python
# ❌ PySide6 中 QListWidgetItem 没有 isEnabled() 方法
if item.isEnabled():

# ✅ 使用 flags 检查
if item.flags() & Qt.ItemIsEnabled:
```

---

## 5. 翻译键组织结构

在 `i18n.py` 中按功能模块分组，使用注释分隔：

```python
_TR.update({
    # Menus
    "Menu.File":             {...},
    "Menu.Tools":            {...},

    # File menu items
    "File.OpenTrace":        {...},

    # Send panel
    "Send.Add":              {...},

    # Send dialog form labels
    "Send.DlgID":            {...},

    # Error messages
    "Error.NotConnected":    {...},
})
```

### 翻译值格式

```python
"键名": {"zh": "中文文本", "en": "English text"},
```

- 快捷键用 `(&X)` 标记：`"Menu.File": {"zh": "文件(&F)", "en": "&File"}`
- 省略号用 `…`（Unicode U+2026）：`"File.OpenTrace": {"zh": "打开 Trace(&O)…", "en": "&Open Trace…"}`
- 冒号在标签后：`"Left.Bitrate": {"zh": "比特率:", "en": "Bitrate:"}`

---

## 6. 检查清单（Code Review）

新增或修改 UI 控件时，确认以下各项：

- [ ] 所有用户可见文本使用 `_()` 获取，无硬编码
- [ ] 翻译键已添加到 `i18n.py` 的 `_TR` 字典
- [ ] `refresh_language()` 中已添加该控件的文本刷新
- [ ] Combo/QListWidget 等容器的选项文本也能刷新
- [ ] 动态拼接文本（如状态栏）使用当前语言键重新格式化
- [ ] 新对话框的 `setWindowTitle()` 使用 `_()`
- [ ] 工具提示 `setToolTip()` 使用 `_()`
