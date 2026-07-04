# Fix: CAN FD receiving fails when peer uses BRS

## Root cause

The firmware's `can_open()` (`can.c:172`) sets FDCAN FrameFormat based on `can_using_BRS()`:

```c
can_handle.Init.FrameFormat = can_using_BRS()
    ? FDCAN_FRAME_FD_BRS       // FDOE=1, BRSE=1
    : FDCAN_FRAME_FD_NO_BRS;   // FDOE=1, BRSE=0
```

`can_using_BRS()` returns `can_calc_baud(data) > can_calc_baud(nominal)` — i.e. `true` only when `data_rate > nominal_rate`. When both are equal (nominal=1M, data=1M), BRSE=0. Per M_CAN spec, any received FD frame with BRS=1 while BRSE=0 triggers a **protocol exception** — the frame is discarded by the FDCAN hardware, never enters any Rx FIFO, and is never reported to USB/host.

The peer device sends FD frames with BRS=1. Our receiver with BRSE=0 silently discards all of them.

## Full connection flow verified (no bugs found)

GUI flow (`main_window.py:320-328` → `worker.py:89-116` → `zdt_canable.py:786-816`):
1. `_connect()` reads combo values → `worker.data_bitrate = combo.currentData()`
2. `worker.connect()` calls `bus.set_data_bitrate(data_bitrate)` then `bus.fd_mode = True`
3. `bus.start()` assembles flags=0x4100 (ELM_DevFlagProtocolElmue | GS_DevFlagCAN_FD) and sends `GS_ReqSetDeviceMode` to firmware
4. Firmware `can_open()` checks `can_using_BRS()` → if data_rate > nominal_rate → FDCAN_FRAME_FD_BRS (FDOE=1, BRSE=1)

All three previously-applied code fixes are present in current source. No additional code changes are needed.

## Critical diagnostic: the "设备:" debug line

The firmware prints this line when can_open completes. It is the SINGLE source of truth for whether BRSE is enabled:

```
设备: Nominal: 1M baud, 87.5%; Data: 2M baud, 75.0%; Perfect match: No
                                    ^^^ 
                         If this says 1M baud instead of 2M baud,
                         BRSE=0 AND BRS FRAMES ARE SILENTLY DISCARDED
```

**If "Data: 1M baud"** → user selected data_bitrate=1M in GUI (same as nominal). MUST change to 2M (or whatever peer's data rate is). Disconnect, change combo, reconnect.

**If "Data: 2M baud"** → BRSE=1 is confirmed. FDCAN is in full FD+BRS mode. Proceed to standalone test.

## Verification: 4-step checklist

**Step 1 — Disconnect, then change GUI settings:**
- Set nominal bitrate to **peer's nominal bitrate** (e.g. `1,000,000 bps`)
- Check "CAN FD"
- Set data bitrate to **peer's data-phase bitrate** (e.g. `2,000,000 bps`, NOT the same as nominal)

**Step 2 — Reconnect and check the log for BRSE:**
The firmware debug output MUST show the data rate is higher than nominal:
```
设备: Nominal: 1M baud, 87.5%; Data: 2M baud, 75.0%; Perfect match: No
```
If `Data` shows the same rate as `Nominal` (e.g. both 1M), BRSE is NOT enabled and BRS frames WILL be silently discarded. Disconnect, fix data_bitrate, reconnect.

**Step 3 — Verify no eFeedback errors:**
No `eFeedback=50` or `eFeedback=58` warnings should appear. If they do, the data timing table isn't matching — re-verify the DATA_BITTIMING fix was applied.

**Step 4 — Test with the peer:**
Send FD frames from peer. They should appear in Trace with type `FD+BRS`. If still nothing, proceed to diagnostic section below.

## If still failing after step 4

**Step A — Clear stale bytecode cache:**
```bash
rm -rf /home/fubingyan/桌面/canable/__pycache__/zdt_canable.cpython*
rm -rf /home/fubingyan/桌面/canable/cangui/__pycache__/
```

**Step B — Run the standalone Python test (not the GUI):**
```bash
python -c "
import logging, time
logging.basicConfig(level=logging.INFO)
from zdt_canable import ZDTCanable, CANFrame

with ZDTCanable() as bus:
    bus.fd_mode = True
    bus.set_bitrate(1_000_000)
    bus.set_data_bitrate(2_000_000)  # MATCH PEER DATA RATE
    bus.start()
    print('Listening...')
    try:
        while True:
            f = bus.receive(timeout=1.0)
            if f:
                print(f'[{\"FD\" if f.fd else \"CAN\"}] {f}')
    except KeyboardInterrupt:
        pass
"
```

**Step C — Report the COMPLETE terminal output**, especially:
- The `设备: Nominal: ... Data: ...` debug line (confirms BRSE)
- Any `eFeedback=` warnings
- Any frames received (classic CAN, FD, or error frames)
- The peer's exact configuration (nominal rate, data rate, BRS on/off)

If the standalone test CAN receive FD frames but the GUI cannot, the issue is stale .pyc or GUI state.
If the standalone test also CANNOT receive FD frames (but CAN receive classic CAN), FDCAN hardware is misconfigured or peer is not sending FD.

## Code fixes already applied (all verified against firmware source)

1. `MAX_ELMUE_MSG_SIZE = 128` (`zdt_canable.py:40`) — handles 64-byte FD payloads (was 80, too tight)
2. `start()` includes `GS_DevFlagCAN_FD` (`zdt_canable.py:799`) — flag present in startup; redundant per firmware (FD auto-enabled when data bitrate set) but provides error feedback if data bitrate missed
3. `DATA_BITTIMING` matches firmware table (`zdt_canable.py:159-168`) — Seg1=5, Seg2=2 (75% sample point), passes STM32G4 data-phase limits (TSEG1≤15). Previously had nominal-phase values (Seg1=139 etc.) which caused `FBK_InvalidParameter` (eFeedback=50)

## Confirmed correct by firmware source review

- `can_open()` (`can.c:130-282`): properly sets FrameFormat=FDCAN_FRAME_FD_BRS when can_using_BRS(), configures TDC compensation, accepts all packets when no filter defined
- `buf_store_rx_packet()` (`Candlelight/buffer.c:228-298`): correctly formats FD frames into kRxFrameElmue with proper size calculation and flags (FDF, BRS, ESI)
- `from_elmue_rx()` (`zdt_canable.py:284-308`): correctly parses the FD frame format with flags byte at offset 2
