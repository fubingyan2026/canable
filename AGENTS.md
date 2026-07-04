# AGENTS.md — CANable 2.5

## Project

Python driver + Qt6 GUI for CANable 2.5 USB-CAN adapter (ElmueSoft firmware).

- `zdt_canable.py` — single-file USB driver (pyusb). Library entrypoint.
- `cangui/` — PySide6 GUI (cangaroo-style). Launch via `python cangui.py` or `python -m cangui`.
- `CANable-2.5-firmware-*/` — **separate C firmware project**, not Python code.

## Setup

```bash
pip install -r requirements.txt          # pyusb, pyserial, PySide6
sudo bash install_udev.sh && re-plug     # non-root USB access
```

ModemManager can interfere with slcan mode. The udev rules include `ID_MM_DEVICE_IGNORE`.

## Driver quirks (must know)

- **CAN FD bit timing must be set BEFORE `start()`** — setting it after start fails silently.
- **`start()` must include `GS_DevFlagCAN_FD` in flags when `.fd_mode == True`** — without it the STM32 FDCAN peripheral runs in Classic CAN mode and drops FD frames on RX. See `zdt_canable.py:798`.
- **`DATA_BITTIMING` values differ from nominal timing** — STM32G4 FDCAN data-phase limits: TSEG1≤15, TSEG2≤15, SJW≤15. Driver table must use firmware's built-in values (Seg1=5, Seg2=2, 75% sample point), NOT the same as nominal bit timing. Wrong Seg1 values cause `FBK_InvalidParameter` (eFeedback=50) from firmware → data bitrate never stored → `start()` returns `FBK_BaudrateNotSet` (eFeedback=58). See `zdt_canable.py:159`.
- **BRSE requires `data_bitrate > nominal_bitrate`** — firmware `can_using_BRS()` enables FDCAN BRSE bit only when data rate exceeds nominal rate. If they are equal, BRSE=0 and the FDCAN generates a protocol exception (drops) any received FD frame with BRS=1. To receive BRS frames from a peer, set data_bitrate to the peer's actual data-phase rate (e.g. nominal=1M, data=2M).
- **Zero-length packet (ZLP)** required when USB transfer size is a multiple of 64 bytes (see `send()` in `zdt_canable.py`).
- **Every `ctrl_out` must be followed by `ELM_ReqGetLastError` check** (`_ctrl_out_checked()` handles this).
- Protocol auto-detection: ElmueSoft (variable-length) vs Legacy (80-byte fixed). The parser in `_ElmueProtocol` handles both.
- TX frames use a `marker` (1-byte counter, 1–255) for echo matching. The `store_tx_frame()` buffer maps markers to `CANFrame` objects.
- USB VID:PID = `0x1D50:0x606F`, EP_IN = `0x81`, EP_OUT = `0x02`.

## Scripts (not part of GUI)

| Script | Purpose |
|--------|---------|
| `example.py [1-6]` | API usage demos (send, listen, loopback, request-response) |
| `debug_can_bus.py [bitrate] [data_bitrate]` | 3-step bus test (loopback → listen → send+echo) |
| `diag.py` | USB device diagnostic (pyusb scan, lsusb, kernel modules, udev rules) |
| `scan_data_bitrate.py` / `scan_fd_data_bitrate.py` | Bitrate scanning against a peer device |
| `diagnose_can.py` | Minimal RX test with raw USB hex dump |
| `test_canfd_receive.py` | CAN FD receive-only test |

## Firmware user manual

https://netcult.ch/elmue/CANable%20Firmware%20Update/

## Maintenance notes

- `zdt_canable_slcan.py` was deleted — the ElmueSoft protocol driver replaced it. No slcan dependencies remain.
- No tests exist (no test framework, no test directory).
- Code is bilingual: Chinese UI labels/comments, English code identifiers.
