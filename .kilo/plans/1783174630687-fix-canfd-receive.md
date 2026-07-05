# i18n: Chinese/English language toggle

## Architecture

- `cangui/i18n.py` — global translation store + `tr()` function + `language_changed` Signal
- All UI files replace string literals with `tr("key")` calls
- `Tools > Language > 中文/English` toggles via `set_language()`
- When language changes: all widgets react to `language_changed` Signal and refresh text

## Implementation

### 1. Create `cangui/i18n.py`

```python
from PySide6.QtCore import QObject, Signal

_TR = {}   # key -> {zh: text, en: text}
_lang = "zh"
_signal = QObject()
language_changed = Signal(str)  # notifies widgets

def tr(key: str) -> str:
    entry = _TR.get(key, {})
    return entry.get(_lang, key)

def set_language(lang: str):
    global _lang
    _lang = lang
    language_changed.emit(lang)

# Translation data
_TR.update({
    # ---- Menus ----
    "menu_file":       {"zh": "文件(&F)",        "en": "&File"},
    "menu_windows":     {"zh": "窗口(&W)",        "en": "&Windows"},
    "menu_hardware":   {"zh": "硬件(&H)",        "en": "&Hardware"},
    "menu_tools":      {"zh": "工具(&T)",        "en": "&Tools"},
    "menu_help":       {"zh": "帮助(&H)",        "en": "&Help"},
    "menu_language":   {"zh": "语言",           "en": "Language"},
    "lang_zh":         {"zh": "中文",           "en": "Chinese"},
    "lang_en":         {"zh": "英文",           "en": "English"},
    ...
})
```

### 2. Update each UI file

Replace every visible string literal with `tr("key")`, connect to `language_changed` to refresh.

### 3. Files to modify
- `cangui/i18n.py` — NEW
- `cangui/main_window.py` — all menus, buttons, labels, status bar
- `cangui/trace.py` — toolbar, column headers, summary
- `cangui/send.py` — buttons, table headers, dialog
- `cangui/filters.py` — labels, buttons
- `cangui/worker.py` — status messages
