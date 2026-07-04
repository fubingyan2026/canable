# Fix: identify() LED blinking never stops

## Root cause

Firmware `led_blink_identify()` (`led.c:86-92`) has **no auto-timeout** — `led_identify` stays `true` permanently until host sends `GS_ReqIdentify(mode=0)`. Even `can_close()` doesn't clear it (`led_turn_TX()` is blocked by `if (led_identify) return;`).

Python `ZDTCanable.identify()` sends only `mode=1` and ignores `duration_ms`:

```python
def identify(self, duration_ms: int = 1500):
    self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 1))  # never sends mode=0
```

## Fix (2 changes in `canable_sdk/driver.py`)

**1. `identify()` — add sleep + stop sequence:**

```python
def identify(self, duration_ms: int = 1500):
    try:
        self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 1))
        time.sleep(duration_ms / 1000.0)
        self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 0))
    except usb.core.USBError:
        pass
```

**2. `close()` — send mode=0 before disposing device**, so blinking stops even if identify was interrupted early:

```python
def close(self):
    if self._running:
        try: self.stop()
        except Exception: pass
    try:
        self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 0))
    except Exception:
        pass
    if self.dev is not None:
        try: usb.util.dispose_resources(self.dev)
        except Exception: pass
        self.dev = None
    self.ep_in = self.ep_out = None
    self._running = False
```

## Validation

1. Click "LED 闪烁识别" in GUI → LEDs blink for ~1.5s then stop
2. Click "连接" then quickly "断开" during blinking → LEDs stop immediately
3. No behavioral change for other methods
