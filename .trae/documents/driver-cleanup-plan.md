# 驱动清理计划：删除 slcan 并适配新 ElmueSoft 驱动

## 概述

固件已更新为 CANable 2.5 ElmueSoft 版本，`zdt_canable.py` 已完成 ElmueSoft 协议重写。现在需要清理旧 slcan 残留、修复兼容性问题、添加缺失 API。

## 当前状态

- `zdt_canable.py` — 已重写完成（1121行），ElmueSoft 协议
- `zdt_canable_slcan.py` — 旧 slcan 后端，588行，**无其他文件引用，完全孤立**
- `worker.py` — 已对齐新驱动，无 slcan 代码引用，但直接访问 `_fd_mode` 和 `_running` 私有属性
- `example.py` — 示例2调用 `send_periodic()` 但新驱动无此方法
- `cangui.py` — 注释过时（"后端选择 gs_usb / slcan"）
- `diag.py` — 诊断脚本，检查 slcan/CDC ACM 设备是合理功能，保留
- `main_window.py` — 注释提及 slcan M0/M1，可更新为 ElmueSoft 术语

## 修改计划

### 1. 删除 `zdt_canable_slcan.py`
- 整个文件删除，无任何代码依赖

### 2. `zdt_canable.py` — 添加 `send_periodic()` 方法
- `example.py` 示例2调用了 `bus.send_periodic(frame, interval_s=0.05, count=20)`
- 在 ZDTCanable 类中添加此方法，实现循环发送逻辑
- 签名: `def send_periodic(self, frame: CANFrame, interval_s: float = 0.01, count: int = 0)`

### 3. `zdt_canable.py` — 添加公共属性替代私有属性直接访问
- `worker.py` 第116行: `self._bus._fd_mode = True` — 直接设私有属性
- `worker.py` 第170行: `if not self._bus._running` — 直接读私有属性
- 在 ZDTCanable 中添加:
  - `running` 只读属性（返回 `self._running`）
  - `fd_mode` 可写属性（getter 返回 `self._fd_mode`，setter 设置 `self._fd_mode`）

### 4. `worker.py` — 改用公共属性
- 第116行: `self._bus._fd_mode = True` → `self._bus.fd_mode = True`
- 第170行: `if not self._bus._running` → `if not self._bus.running`

### 5. `cangui.py` — 更新过时注释
- 第5行: `"后端选择（gs_usb / slcan）"` → `"CAN 控制器状态（连接 / 启动 / 停止）"`

### 6. `main_window.py` — 更新 slcan 相关注释
- 第200-201行: 更新 Silent 模式注释，移除 slcan M0/M1 术语，改为 ElmueSoft 的 ListenOnly 模式说明

### 7. `zdt_canable.py` — `list_devices()` 返回值更新
- 第610行: `"backend": "gs_usb"` → `"backend": "elmue"`（新驱动使用 ElmueSoft 协议）

## 不修改的文件

- `diag.py` — 诊断脚本检查 slcan/CDC ACM 设备是合理功能，保留不变
- `install_udev.sh` — udev 规则与协议无关，保留
- `cangui/send.py`, `cangui/trace.py`, `cangui/filters.py`, `cangui/style.py` — 无需修改

## 验证步骤

1. `python -c "from zdt_canable import ZDTCanable, CANFrame"` — 导入正常
2. `python -c "from zdt_canable_slcan import ZDTCanableSLCAN"` — 应报错（已删除）
3. `python example.py 1` — 示例1语法正确
4. `python example.py 2` — 示例2 send_periodic 可调用
5. 检查 `worker.py` 中无 `_fd_mode` / `_running` 私有属性访问
