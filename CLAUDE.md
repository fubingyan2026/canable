# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CANable 2.5 GUI — a PySide6/Qt6 desktop application for the CANable 2.5 USB-CAN adapter (ElmueSoft Candlelight firmware). Supports Classic CAN and CAN FD with bilingual UI (Chinese/English) and light/dark themes.

Two Python packages:
- **`cangui/`** — PySide6 GUI (main window, trace/send/filter panels, worker thread)
- **`canable_sdk/`** — USB-CAN driver SDK wrapping pyusb (device enumeration, ElmueSoft protocol, CAN frame serialization)

## Build & run commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the GUI (either works)
python cangui.py
python -m cangui

# Run the SDK CLI (CAN monitor)
python -m canable_sdk          # Classic CAN
python -m canable_sdk --fd     # CAN FD mode

# Package as Windows EXE (onedir mode, UPX disabled for faster startup)
pyinstaller --clean --noconfirm CANable2.5.spec
# Output: dist/CANable2.5/CANable2.5.exe
```

There are no test suites, linters, or CI pipelines in this repository.

## Architecture

### Thread model

The app uses **two threads** to keep USB I/O off the Qt main thread:

1. **Main thread** — Qt event loop, all UI rendering, `_batch_timer` (100ms) polls `CANWorker.take_batch()` for new frames
2. **Worker thread** (`CANWorker` via `QThread`) — blocking `bus.receive(timeout=0.01)` loop, USB send, bus load calculation, filter pipeline

Thread safety boundaries:
- `CANWorker._frame_buffer` — `deque(maxlen=10000)` protected by `_buffer_mutex`, written by worker thread, read by main thread via `take_batch()`
- `CANWorker._send_queue` — `deque` protected by `_send_mutex`, written by main thread (`send()`), consumed by worker thread (`_process_send_queue()`)
- State flags (`_running`, `_connected`, `_filters`) protected by `_mutex`
- Worker has **no parent** QObject (required for `moveToThread`)

### Data flow

```
USB device → worker thread (receive loop, filter, buffer)
                ↓ batch (100ms timer)
           main thread (trace table append, stats update, UI refresh)
                ↓ send queue
           worker thread (USB send)
```

### Key classes

| Class | File | Role |
|-------|------|------|
| `MainWindow` | `cangui/main_window.py` | QMainWindow with dock layout, device connect/disconnect lifecycle, settings persistence (2s debounced JSON) |
| `CANWorker` | `cangui/worker.py` | QObject running in QThread — owns `ZDTCanable`, runs receive loop, manages send queue, emits `bus_stats`/`error`/`noack_warning` signals |
| `TracePanel` | `cangui/trace.py` | CAN message table with `TraceModel` (QAbstractTableModel), supports collapse-by-ID mode, autoscroll, CSV/JSONL/ASC export |
| `SendPanel` | `cangui/send.py` | Single-frame and periodic send table, CSV persistence to `send_list.csv`, FD-aware DLC range |
| `FilterPanel` | `cangui/filters.py` | ID-range filters (pass/discard actions), integrated per-ID statistics table |
| `CANFilter` | `cangui/worker.py` | Filter rule: ID min/max, extended flag, pass_or_discard action |
| `ZDTCanable` | `canable_sdk/driver.py` | Main driver — device open/close, bitrate config, send/receive, FD support, termination, filters, pin control |
| `CANFrame` | `canable_sdk/frame.py` | Data class with ElmueSoft + Legacy dual-protocol serialization, error frame detection |
| `_ElmueProtocol` | `canable_sdk/protocol.py` | Variable-length protocol stream parser (internal use) |

### USB backend on Windows

`canable_sdk/__init__.py` calls `os.add_dll_directory()` to add the project root to the DLL search path. The `libusb-1.0.dll` must be in the project root directory. This happens at import time so pyusb can find the backend.

### Signal wiring

The main window wires signals from sub-panels to the worker:
- `SendPanel.request_send` → `MainWindow._on_send_frame()` → `worker.send()` (queued)
- `FilterPanel.filters_changed` → `MainWindow._on_filters_changed()` → `worker.set_filters()`
- `CANWorker.state_changed` → `MainWindow._on_state_changed()` (connected/disconnected)
- `CANWorker.error` → `MainWindow._on_error()`
- `CANWorker.bus_stats` → `MainWindow._on_bus_stats()` (load%, fps)

### Firmware protocol dual-support

The SDK auto-detects and adapts to two protocols:
1. **ElmueSoft variable-length protocol** (preferred) — message header `{size, msg_type}`, 1-byte TX echo marker, supports FD/timestamps/bus-load
2. **Legacy fixed 80-byte protocol** — backward compatible with old firmware

## Development conventions

### Internationalization (i18n)

All user-visible strings must use `_()` from `cangui/i18n.py`. The `_TR` dict maps dot-notation keys to `{zh, en}` dictionaries. Key format: `Area.Description` (e.g., `Menu.File`, `Send.Add`, `Error.ConnectFailed`).

When adding UI text, follow three steps:
1. Register the key in `_TR`
2. Use `_()` when creating the widget
3. Add refresh logic in the panel's `refresh_language()` method

Full spec: [CANGUI_I18N_SPEC.md](CANGUI_I18N_SPEC.md)

### Theming

All colors must use exported constants from `cangui/style.py` (`BG_CARD`, `FG_ACCENT`, `BORDER`, etc.) — never hardcode hex values. The `set_theme()` function switches between light/dark palettes and `get_qss()` returns the full QSS stylesheet. Widgets that depend on theme via property selectors must call `style().unpolish()` + `style().polish()` after property changes.

### Settings persistence

`MainWindow` persists state to `settings.json` (in the exe directory) with a 2-second debounce timer. Settings include bitrate, FD mode, window geometry, dock layout, column widths, filters, theme, and language. Panels read/write settings via `MainWindow._get()`/`MainWindow._set()`.

### CAN FD requirements

- `fd_mode` must be set **before** `start()`
- Data bitrate must be higher than nominal bitrate for BRS to work
- Data phase timing has hardware limits: TSEG1≤15, TSEG2≤15, SJW≤15 (STM32G4)
