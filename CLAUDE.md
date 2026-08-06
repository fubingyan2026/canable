# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

CANable 2.5 GUI — a PySide6/Qt6 desktop application for the CANable 2.5 USB-CAN adapter (ElmueSoft Candlelight firmware). Supports Classic CAN and CAN FD with a bilingual UI (Chinese/English). Styling deliberately uses Qt's native look — a custom theme/frameless-window system was removed and is not coming back.

Two Python packages:
- **`cangui/`** — PySide6 GUI (main window, trace/send/filter panels, worker thread, plugin host)
- **`canable_sdk/`** — USB-CAN driver SDK wrapping pyusb (device enumeration, ElmueSoft protocol, CAN frame serialization, bitrate tables)

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

# Package as Windows EXE (onefile mode, UPX disabled for faster startup)
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
- `CANWorker._frame_buffer` — `deque(maxlen=10000)` protected by `_buffer_mutex`, written by worker thread, read by main thread via `take_batch()`. `take_batch()` returns *all* buffered frames and clears the buffer; the main window then truncates to the last `MAX_BATCH=1000` to bound UI work.
- `CANWorker._send_queue` — `deque` protected by `_send_mutex`, written by main thread (`send()`), consumed by worker thread (`_process_send_queue()`)
- `CANWorker._upgrade_task` — single-slot task protected by `_upgrade_task_mutex`; the run loop picks it up at its next iteration (see Upgrade task below)
- State flags (`_running`, `_connected`, `_filters`) protected by `_mutex`
- Worker has **no parent** QObject (required for `moveToThread`)
- `MainWindow._disconnecting` flag prevents reconnection during async disconnect operations

**Upgrade task (worker exclusive mode):** plugins hand a task object to the worker via `PluginContext.start_upgrade(task)`. The task must implement `run(bus: ZDTCanable)`. On the next run-loop iteration the worker calls `task.run()` with the already-open bus; while it runs, normal CAN send/receive is suspended. This is what the `boot_upgrade` plugin uses to drive its synchronous firmware-upgrade state machine (see `plugins/boot_upgrade/upgrader.py`).

### Data flow

```
USB device → worker thread (receive loop, filter, buffer)
                ↓ batch (100ms timer, max 1000 frames)
           main thread (trace table append, stats update, UI refresh)
                ↓ send queue
           worker thread (USB send)
```

### Window layout

Standard native `QMainWindow` (no custom title bar, no frameless window — `cangui/title_bar.py` is dead code kept only for reference):

- **Menu bar** — File (open/save trace, exit), Windows (dock toggles), Tools (language), Help (About), Plugins (populated at runtime by `PluginHost`)
- **Left sidebar** (inside a `QSplitter`) — a card with bus config (bitrate, CAN FD checkbox, data bitrate, sample point) above a device list (scan + connect/disconnect toggle button)
- **Center `QTabWidget`** — the trace panel as tab 0 (non-closable) plus one tab per active plugin. Tabs carry a stable key (`"trace"`, `"plugin.<name>"`, `"widget.<idx>"`); the last selected key is persisted as `active_tab` and restored after plugins load.
- **Docks** — bottom `SendDock` and right `FilterDock` (movable/closable; may dock bottom or right). Dock geometry is persisted, including floating position.
- **`QStatusBar`** — connection status, bitrate, fps, bus load (colored by level via a property selector), total frame count

Dock animations are disabled (`AnimatedDocks` off) for performance.

### High DPI & fonts

`QApplication.setHighDpiScaleFactorRoundingPolicy(PassThrough)` is set in `cangui/__main__.py` for accurate fractional scaling. `_pick_app_font()` picks the best available CJK-capable font: SF Pro Display → SF Pro Text → PingFang SC → Noto Sans CJK SC → Microsoft YaHei → Noto Sans → Helvetica Neue → Segoe UI → system default.

### Key classes

| Class | File | Role |
|-------|------|------|
| `MainWindow` | `cangui/main_window.py` | Native QMainWindow: menubar, splitter + docks, device connect/disconnect lifecycle, settings persistence (2s debounced JSON), batch-timer dispatch |
| `CANWorker` | `cangui/worker.py` | QObject running in QThread — owns `ZDTCanable`, runs receive loop, manages send queue and upgrade task, emits `bus_stats`/`error`/`noack_warning` signals |
| `TracePanel` / `TraceModel` | `cangui/trace.py` | CAN message table (QAbstractTableModel), collapse-by-ID view layer, autoscroll, pause, clear. CSV/JSONL save/load lives in `MainWindow` |
| `SendPanel` | `cangui/send.py` | Single-frame and periodic send table, CSV persistence to `send_list.csv`, FD-aware DLC range, unified toggle button for start/stop (rejects start when disconnected) |
| `FilterPanel` | `cangui/filters.py` | ID-range filters (pass/discard actions), integrated per-ID statistics table |
| `PluginHost` | `cangui/plugin_host.py` | Loads, manages lifecycle of, and dispatches events to user plugins from `plugins/` directory |
| `Plugin` | `cangui/plugin_host.py` | Base class for user plugins — lifecycle hooks and event callbacks (see Plugin system) |
| `PluginContext` | `cangui/plugin_host.py` | Sandboxed API plugins use to interact with the host |
| `CANFilter` | `cangui/worker.py` | Filter rule: ID min/max, extended flag, pass_or_discard action |
| `ZDTCanable` | `canable_sdk/driver.py` | Main driver — device open/close, bitrate config, send/receive, FD support, termination, filters, pin control, USB error recovery |
| `CANFrame` | `canable_sdk/frame.py` | Data class with ElmueSoft + Legacy dual-protocol serialization, error frame detection |
| `_ElmueProtocol` | `canable_sdk/protocol.py` | Variable-length protocol stream parser (internal use) |

### Plugin system

Plugins live in `plugins/<name>/plugin.py` and must export a `create_plugin() -> Plugin` factory function. Each plugin sub-package needs an `__init__.py`. Full spec: [plugins/PLUGIN_DEV_GUIDE.md](plugins/PLUGIN_DEV_GUIDE.md). Reference implementation: `plugins/boot_upgrade/`.

Plugin lifecycle (managed by `PluginHost`):

```
init(ctx)              — app startup: register i18n keys, load config
activate()             — user opens tab: build_widget() → add_tab() → on_activated()
  on_connect()         — CAN connected (only when active)
  on_disconnect()      — CAN disconnected (only when active)
  on_frames(frames)    — batch frames at 100ms (only when active)
  refresh_language()   — language switch
deactivate()           — user closes tab: confirm_close() → on_deactivating() → remove_tab() → teardown_widget()
shutdown()             — app exit: force-deactivate all plugins (skips confirm_close)
```

Required overrides: `name`, `display_title()`, `build_widget(ctx)`.
Optional overrides: `init()`, `teardown_widget()`, `on_activated()`, `on_deactivating()`, `on_connect()`, `on_disconnect()`, `on_frames()`, `refresh_language()`, `confirm_close()`.

`PluginContext` provides a sandboxed API: `add_tab()`/`remove_tab()`/`set_tab_title()`, `send_frame()`, `is_connected()`/`is_fd_mode()`/`get_bitrate()`, `get_setting()`/`set_setting()` (auto-prefixed `plugin.`), `start_upgrade()` (see Thread model), `status_message()`, `register_i18n()`.

Plugin active state is persisted to `settings.json` under `plugin.active_list` with a 500ms debounce (separate from the 2s main settings debounce) and restored at startup; stale names of plugins that no longer exist are skipped.

### Signal wiring

The main window wires signals from sub-panels to the worker:
- `SendPanel.request_send` → `MainWindow._on_send_frame()` → `worker.send()` (queued)
- `FilterPanel.filters_changed` → `MainWindow._on_filters_changed()` → `worker.set_filters()`
- `CANWorker.state_changed` → `MainWindow._on_state_changed()` (connected/disconnected)
- `CANWorker.error` → `MainWindow._on_error()`
- `CANWorker.bus_stats` → `MainWindow._on_bus_stats()` (load%, fps)
- `CANWorker.noack_warning` → `MainWindow` status bar (auto-clears after 1s via `_noack_timer`)

Frames also dispatch to active plugins via `PluginHost.dispatch_frames()` in the batch timer callback. On connection-state changes, `PluginHost.dispatch_state()` calls `on_connect`/`on_disconnect` on active plugins.

### USB backend on Windows

`canable_sdk/__init__.py` calls `os.add_dll_directory()` to add the project root to the DLL search path. The `libusb-1.0.dll` must be in the project root directory. This happens at import time so pyusb can find the backend.

### Firmware protocol dual-support

The SDK auto-detects and adapts to two protocols:
1. **ElmueSoft variable-length protocol** (preferred) — message header `{size, msg_type}`, 1-byte TX echo marker, supports FD/timestamps/bus-load
2. **Legacy fixed 80-byte protocol** — backward compatible with old firmware

### USB error recovery

On USB pipe errors (EPIPE, errno 32/232), the driver auto-clears the STALL and calls `recover()`: stop CAN → flush endpoint buffer → reconfigure bitrate → restart. A `_tx_blocked_until` cooldown (0.3s after recover, 0.5s after pipe errors) prevents immediate re-send attempts during recovery. RX timeouts are handled silently (errno 110 on Linux, 10060 on Windows, plus string-matching for "timeout"); overflow errors (errno 75/121) are reported.

## Development conventions

### Internationalization (i18n)

All user-visible strings must use `_()` from `cangui/i18n.py`. The `_TR` dict maps dot-notation keys to `{zh, en}` dictionaries. Key format: `Area.Description` (e.g., `Menu.File`, `Send.Add`, `Error.ConnectFailed`).

The `language_changed` Signal is emitted when the language switches — connect to it for dynamic text updates in non-panel code.

When adding UI text, follow three steps:
1. Register the key in `_TR`
2. Use `_()` when creating the widget
3. Add refresh logic in the panel's `refresh_language()` method

Plugins register their own keys at runtime via `PluginContext.register_i18n()` instead of editing `cangui/i18n.py`.

Full spec: [CANGUI_I18N_SPEC.md](CANGUI_I18N_SPEC.md)

### Theming

The app intentionally uses **Qt's native style** — no custom theme system and no QSS-driven color palette. `cangui/style.py` is minimal:
- Color constants used for **program logic** (not stylesheets): `BG_TX`, `BG_ERROR`, `LOAD_LOW/MID/HIGH`, `FG_TEXT`, `FG_DIM`, `FG_ACCENT`
- `id_color(can_id, extended)` — deterministic per-ID color for the trace table
- `get_qss()` — a small functional QSS for state indicators only (status-bar connected color, bus-load level colors via property selectors)
- `set_theme()`/`current_theme()` are **no-op stubs** kept for backward compatibility — don't call them or build new code on them. A legacy `theme` key may linger in `settings.json` but is ignored.

Widgets driven by property selectors (e.g. `statusLabel[connected="..."]`, `busLoad[level="..."]`) must call `style().unpolish()` + `style().polish()` after changing the property.

### SVG icon system

Icons are embedded SVG templates in `cangui/icons.py` using `{color}` placeholders. `make_icon(name, color)` renders via `QSvgRenderer` at 2x resolution for HiDPI, caches by `(name, color)`. Color defaults to `FG_TEXT`. Available icons: trash, pause, play, stop, send, plus, pencil, scan, power, power_off. `clear_cache()` exists but is legacy (there is no theme switch anymore).

### Settings persistence

`MainWindow` persists state to `settings.json` (in the exe directory) with a 2-second debounce timer. Settings include bitrate, FD mode, data bitrate, sample point, autoscroll, collapse, language, filters, window geometry, dock layout (including floating dock geometry), splitter sizes, header state, active center tab, and plugin state (`plugin.active_list`, `plugin.<name>.*`). Panels read/write settings via `MainWindow._get()`/`MainWindow._set()`.

### CAN FD requirements

- `fd_mode` must be set **before** `start()`
- Data bitrate must be higher than nominal bitrate for BRS to work
- Data phase timing has hardware limits: TSEG1≤15, TSEG2≤15, SJW≤15 (STM32G4)

### PyInstaller packaging

`CANable2.5.spec` uses **onefile** mode with `upx=False` (UPX decompression slows startup). It bundles `libusb-1.0.dll`, SVG assets, and the app icon. ~50 unused PySide6 modules are excluded to reduce binary size. Hidden imports include `usb.backend.libusb1`, `PySide6.QtXml`, and the `plugins.boot_upgrade` submodules (dynamically imported, invisible to PyInstaller); the whole `plugins/` tree is collected via `Tree()`. When adding a plugin, add its submodules to `hiddenimports`.

### Logging

Logging is configured in `cangui/__main__.py:setup_logging()` and starts before any GUI module is imported:

- Each app launch creates `logs/canable_YYYYMMDD_HHMMSS.log`
- Terminal handler: INFO level
- File handler: DEBUG level
- Format: `%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s`
- Noisy third-party loggers (`urllib3`, `PIL`, `usb._debug`) suppressed to WARNING
- SIGINT is handled via `signal.signal(SIGINT, SIG_DFL)` + a 500ms `QTimer` to wake the Qt event loop, allowing clean Ctrl+C exit

Logging conventions:
- Log only **event transitions**: connection/disconnection, start/stop, errors, configuration changes
- **Never** log per-frame data (USB raw bytes, TX/RX frame dumps, protocol parse details) — these would flood the file at high fps
- Use `logger = logging.getLogger("cangui.<module>")` per module; SDK modules use `logging.getLogger("canable_sdk.<module>")`
