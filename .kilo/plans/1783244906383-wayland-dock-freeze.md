# Fix: Connect/Disconnect Button Reverts to Chinese After Language Switch

## Bug
After switching UI language to English, clicking Connect/Disconnect causes the button text to revert to Chinese (连接/断开).

## Root Cause
`_update_connect_ui()` at `cangui/main_window.py:419` uses hardcoded Chinese strings:

```python
self.connect_btn.setText("断开" if connected else "连接")
```

Every time a connection state change triggers `_update_connect_ui()`, it overwrites the i18n-aware text set by `_refresh_language()`, which already correctly uses:

```python
self.connect_btn.setText(_("Left.Disconnect") if self._connected else _("Left.Connect"))
```

The i18n keys `Left.Connect` ("连接"/"Connect") and `Left.Disconnect` ("断开"/"Disconnect") are already defined in `cangui/i18n.py`.

## Fix
Single line change in `cangui/main_window.py:419`:

```python
# Before:
self.connect_btn.setText("断开" if connected else "连接")
# After:
self.connect_btn.setText(_("Left.Disconnect") if connected else _("Left.Connect"))
```

## Validation
1. Launch `python cangui.py`
2. Switch language to English via menu: 工具 → 语言 → English
3. Click Connect → button text should be "Disconnect" (not "断开")
4. Click Disconnect → button text should be "Connect" (not "连接")
