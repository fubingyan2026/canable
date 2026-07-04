# Plan: Refactor zdt_canable.py into canable_sdk package

## Decisions

- Package name: `canable_sdk` (pip name: `canable-sdk`)
- Split into 6 modules based on logical boundaries
- Backward compatibility: update all 11 import sites (scripts + cangui/)
- Also: remove orphaned `pyserial` from requirements.txt

## Files to create

```
canable_sdk/
├── __init__.py       # Re-export: ZDTCanable, CANFrame, logger, key constants
├── constants.py      # USB IDs, message types, control requests, flags, error codes, DLC maps
├── frame.py          # CANFrame dataclass + DLC helper functions
├── bitrate.py        # NOMINAL_BITTIMING, DATA_BITTIMING tables
├── protocol.py       # _ElmueProtocol parser (USB byte stream → CANFrame)
├── driver.py         # ZDTCanable class (device lifecycle, comms, callbacks)
├── cli.py            # _cli(), _cli_fd_demo() CLI entrypoints
└── py.typed          # PEP 561 marker
```

```
pyproject.toml        # NEW: pip-installable project metadata
```

## Files to modify

All 11 sites change `from zdt_canable import` → `from canable_sdk import`:

| File | New import |
|------|-----------|
| `example.py:15` | `from canable_sdk import ZDTCanable, CANFrame, logger` |
| `debug_can_bus.py:21` | `from canable_sdk import ZDTCanable, CANFrame` |
| `diagnose_can.py:15` | `from canable_sdk import ZDTCanable, CANFrame` |
| `test_canfd_receive.py:6` | `from canable_sdk import ZDTCanable, CANFrame` |
| `scan_data_bitrate.py:18` | `from canable_sdk import ZDTCanable` |
| `scan_fd_data_bitrate.py:18` | `from canable_sdk import ZDTCanable` |
| `cangui/main_window.py:18` | `from canable_sdk import ZDTCanable, CANFrame` |
| `cangui/worker.py:15` | `from canable_sdk import ZDTCanable, CANFrame` |
| `cangui/trace.py:14` | `from canable_sdk import CANFrame` |
| `cangui/send.py:15` | `from canable_sdk import CANFrame` |

Also:
- `requirements.txt` — remove `pyserial>=3.5` (orphaned from deleted slcan)
- `AGENTS.md` — update project structure section

## Files to delete

- `zdt_canable.py` (contents moved into canable_sdk/ modules)

## Module contents by source lines

| Module | Lines from zdt_canable.py | Content |
|--------|--------------------------|---------|
| `constants.py` | 1-137 | logger, USB IDs, message types, request codes, device flags, CAN ID flags, frame flags, error flags/enums, DLC mapping, LEGACY_FRAME_SIZE, MAX_ELMUE_MSG_SIZE |
| `bitrate.py` | 139-168 | NOMINAL_BITTIMING, DATA_BITTIMING tables |
| `frame.py` | 170-422 | `_pad_to_dlc()`, `_data_len_to_dlc()`, `_dlc_to_data_len()`, `CANFrame` class |
| `protocol.py` | 425-568 | `_ElmueProtocol` class |
| `driver.py` | 574-1137 | `ZDTCanable` class |
| `cli.py` | 1140-1207 | `_cli()`, `_cli_fd_demo()` |

## __init__.py public API

```python
"""CANable 2.5 Python SDK (canable_sdk)."""
__version__ = "0.1.0"

from .driver import ZDTCanable
from .frame import CANFrame
from .constants import logger, CANABLE_VID, CANABLE_PID, FRM_FDF, FRM_BRS, FRM_ESI

__all__ = ["ZDTCanable", "CANFrame", "logger"]
```

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "canable-sdk"
version = "0.1.0"
description = "Python USB-CAN driver for CANable 2.5 adapters (ElmueSoft firmware)"
requires-python = ">=3.9"
dependencies = ["pyusb>=1.2.1"]

[project.optional-dependencies]
gui = ["PySide6>=6.5"]

[tool.setuptools.packages.find]
include = ["canable_sdk*"]
```

## Validation

1. `python -c "from canable_sdk import ZDTCanable, CANFrame; print('OK')"`
2. `python cangui.py` — GUI launches without import errors
3. `python example.py` — lists examples without import errors
4. `pip install -e .` — editable install works

## Implementation order

1. Create `canable_sdk/` directory
2. Create `constants.py` (lines 1-137, remove `import usb` if it was there... no, usb import is only in driver.py)
3. Create `bitrate.py` (lines 139-168)
4. Create `frame.py` (lines 170-422, import from .constants and .bitrate)
5. Create `protocol.py` (lines 425-568, import from .constants and .frame)
6. Create `driver.py` (lines 574-1137, import from .constants, .frame, .protocol, .bitrate)
7. Create `cli.py` (lines 1140-1207)
8. Create `__init__.py` with re-exports
9. Create `py.typed` (empty file)
10. Create root `pyproject.toml`
11. Update all 11 import sites
12. Update `requirements.txt` (remove pyserial)
13. Update `AGENTS.md` (project structure section)
14. Delete `zdt_canable.py`
15. Clear `__pycache__/` directories
16. Run validation
