"""CANable GUI 扩展插件根包。

每个子包为一个独立插件，需满足：
1. 包含 `__init__.py`
2. 包含 `plugin.py`，导出 `create_plugin() -> cangui.plugin_host.Plugin`

加载机制详见 `cangui/plugin_host.py`。
"""
