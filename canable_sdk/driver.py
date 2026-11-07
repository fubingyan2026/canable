"""CANable 2.5 USB-CAN adapter driver (ElmueSoft protocol).

Main entrypoint: ZDTCanable class.
"""
from __future__ import annotations

import math
import struct
import threading
import time
from dataclasses import replace
from contextlib import contextmanager
from typing import Callable, List, Optional

import usb.core
import usb.util

from .constants import (
    CANABLE_VID, CANABLE_PID, EP_IN, EP_OUT, MAX_PACKET_SIZE,
    HOST_FORMAT_MAGIC,
    GS_ReqSetHostFormat, GS_ReqSetBitTiming, GS_ReqSetDeviceMode,
    GS_ReqGetCapabilities, GS_ReqGetDeviceVersion, GS_ReqGetTimestamp,
    GS_ReqIdentify, GS_ReqSetBitTimingFD, GS_ReqGetCapabilitiesFD,
    GS_ReqSetTermination, GS_ReqGetTermination,
    ELM_ReqGetBoardInfo, ELM_ReqSetFilter, ELM_ReqGetLastError,
    ELM_ReqSetBusLoadReport, ELM_ReqSetPinStatus, ELM_ReqGetPinStatus,
    GS_DevFlagListenOnly, GS_DevFlagLoopback, GS_DevFlagOneShot,
    GS_DevFlagTimestamp, GS_DevFlagCAN_FD, GS_DevFlagBitTimingFD,
    ELM_DevFlagProtocolElmue, ELM_DevFlagDisableTxEcho,
    GS_ModeStart, FIL_ClearAll,
    FEEDBACK_NAMES,
    logger,
)
from .bitrate import NOMINAL_BITTIMING, DATA_BITTIMING, TimingLimits, DATA_LIMITS, calculate_timing
from .frame import CANFrame
from .protocol import _ElmueProtocol


class CANableCommandError(RuntimeError):
    """A control transfer succeeded, but the firmware rejected its command."""

    def __init__(self, request: int, feedback: int):
        self.request = request
        self.feedback = feedback
        name = FEEDBACK_NAMES.get(feedback, f"unknown({feedback})")
        super().__init__(f"CAN command 0x{request:02X} failed: {name} (eFeedback={feedback})")


class ZDTCanable:
    def __init__(self, vid=None, pid=None, serial=None, port=None, backend=None):
        self.vid    = vid or CANABLE_VID
        self.pid    = pid or CANABLE_PID
        self.serial = serial
        if port is not None and (not isinstance(port, (tuple, list)) or len(port) != 2
                                 or not all(isinstance(v, int) and v >= 0 for v in port)):
            raise ValueError("port must be a USB (bus, address) pair")
        self._port = tuple(port) if port is not None else None
        self._backend = backend
        self.dev:    Optional[usb.core.Device] = None
        self.ep_out: Optional[usb.core.Endpoint] = None
        self.ep_in:  Optional[usb.core.Endpoint] = None

        self._lock       = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._receive_lock = threading.RLock()
        self._reader_lock = threading.Lock()
        self._listener_lock = threading.Lock()
        self._listen_stop = threading.Event()
        self._recv_thr = None
        self._running    = False
        self._session_id = 0
        self._fd_mode    = False
        self._bitrate:   Optional[int] = None
        self._sample_point: Optional[float] = None
        self._data_bitrate: Optional[int] = None
        self._data_sample_point: Optional[float] = None
        self._capabilities: int = 0
        self._capabilities_fd: int = 0
        self._protocol:  Optional[str] = None
        self._parser:    Optional[_ElmueProtocol] = None
        self._has_timestamp: bool = False
        self._listen_only: bool = False
        self._loopback: bool = False
        self._disable_echo: bool = False
        self._one_shot: bool = False
        self._nominal_configured = False
        self._data_configured = False
        self._needs_reconfigure = False
        self._filters = []
        self._bus_load_interval = 0
        self._can_clock = 160_000_000
        self._nominal_limits = TimingLimits()
        self._data_limits = DATA_LIMITS
        self._callbacks: List[Callable[[CANFrame], None]] = []
        self._overflow_cb: Optional[Callable[[], None]] = None
        self._last_error_info: Optional[str] = None
        self._tx_blocked_until: float = 0.0

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @contextmanager
    def _lifecycle(self):
        # A callback must be able to exit when another thread is stopping and
        # joining it. Never wait indefinitely on that thread's lifecycle lock.
        if threading.current_thread() is self._recv_thr:
            while not self._lifecycle_lock.acquire(timeout=0.05):
                if self._listen_stop.is_set():
                    raise RuntimeError("receive listener is stopping")
        else:
            self._lifecycle_lock.acquire()
        try:
            yield
        finally:
            self._lifecycle_lock.release()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def fd_mode(self) -> bool:
        return self._fd_mode

    @fd_mode.setter
    def fd_mode(self, value: bool):
        with self._lock:
            if self._running:
                raise RuntimeError("stop CAN before changing FD mode")
            self._fd_mode = bool(value)

    # ================================================================
    #  Device enumeration
    # ================================================================
    @staticmethod
    def list_devices() -> List[dict]:
        devs = []
        for d in usb.core.find(find_all=True, idVendor=CANABLE_VID, idProduct=CANABLE_PID):
            strings_ok = True
            try:
                mfg = usb.util.get_string(d, d.iManufacturer) or ""
                prd = usb.util.get_string(d, d.iProduct) or ""
                ser = usb.util.get_string(d, d.iSerialNumber) or ""
            except Exception:
                # 设备已被本进程打开（占用）时读取字符串可能失败；
                # 这不影响列举结果，上层会用 VID/PID/总线地址兜底显示。
                mfg = prd = ser = ""
                strings_ok = False
            devs.append({
                "backend": "elmue",
                "vid": CANABLE_VID, "pid": CANABLE_PID,
                "manufacturer": mfg, "product": prd, "serial": ser,
                "path": None,
                "bus": getattr(d, "bus", None),
                "address": getattr(d, "address", None),
                "strings_ok": strings_ok,
            })
        return devs

    # ================================================================
    #  Connection & disconnection
    # ================================================================
    def open(self):
        with self._lifecycle():
            self._open()

    def _open(self):
        if self.dev is not None:
            raise RuntimeError("USB device is already open")
        if self._recv_thr is not None and self._recv_thr.is_alive():
            raise RuntimeError("previous receive thread has not exited")
        kwargs = dict(idVendor=self.vid, idProduct=self.pid)
        if self._backend is not None:
            kwargs["backend"] = self._backend
        if self._port is not None:
            kwargs.update(bus=self._port[0], address=self._port[1])
        if self.serial:
            kwargs.setdefault("serial_number", self.serial)
        logger.debug("查找设备: VID=0x%04X PID=0x%04X", self.vid, self.pid)
        self.dev = usb.core.find(**kwargs)
        if self.dev is None:
            raise RuntimeError(f"CANable not found (VID=0x{self.vid:04X}, PID=0x{self.pid:04X})")

        # 获取设备序列号用于日志追踪
        try:
            sn = usb.util.get_string(self.dev, self.dev.iSerialNumber)
            logger.info("设备已打开: serial=%s", sn)
        except Exception:
            logger.info("设备已打开: serial=<unknown>")

        try:
            self._capabilities = self._capabilities_fd = 0
            self._protocol = None
            self._can_clock = 160_000_000
            self._nominal_limits = TimingLimits()
            self._data_limits = DATA_LIMITS
            self._setup_usb()
            self._init_device()
            self._clear_receive_buffers(drain=True)
            self._nominal_configured = self._data_configured = False
            self._needs_reconfigure = True
            self._tx_blocked_until = 0.0
            self._last_error_info = None
        except Exception:
            self.close()
            raise
        logger.debug("协议检测完成: protocol=%s", self._protocol)

    def close(self):
        with self._lifecycle():
            self._close()

    def _close(self):
        logger.debug("关闭设备")
        self.stop_listening()
        if self.dev is not None:
            try:
                # Also reset after an unconfirmed START: a failed feedback
                # read does not prove that the controller stayed stopped.
                with self._lock:
                    self._stop_controller()
            except Exception:
                logger.debug("CAN reset during close failed", exc_info=True)
        # 关闭 LED 识别（非关键操作，短超时避免阻塞断开）
        try:
            self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 0), timeout=100)
        except Exception:
            pass
        self._running = False
        self._session_id += 1
        with self._lock, self._receive_lock:
            if self.dev is not None:
                try:
                    usb.util.dispose_resources(self.dev)
                except Exception:
                    logger.debug("USB resource cleanup failed", exc_info=True)
                self.dev = None
            self.ep_in = self.ep_out = None
            self._nominal_configured = self._data_configured = False
            self._clear_receive_buffers()

    def _setup_usb(self):
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except (usb.core.USBError, NotImplementedError):
            pass

        try:
            self.dev.set_configuration()
        except usb.core.USBError:
            pass
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0, 0)]

        self.ep_in = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == EP_IN)
        self.ep_out = usb.util.find_descriptor(
            intf, custom_match=lambda e: e.bEndpointAddress == EP_OUT)

        if self.ep_out is None:
            self.ep_out = usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                                               == usb.util.ENDPOINT_OUT)
        if self.ep_in is None:
            self.ep_in = usb.util.find_descriptor(
                intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
                                               == usb.util.ENDPOINT_IN)

        if self.ep_out is None or self.ep_in is None:
            raise RuntimeError(f"USB endpoints not found (need EP_IN=0x81, EP_OUT=0x02)")

    def _init_device(self):
        self._reset_device()

        caps = self._ctrl_in(GS_ReqGetCapabilities, length=40)
        if caps and len(caps) >= 4:
            self._capabilities = struct.unpack_from('<I', bytes(caps), 0)[0]
            self._load_timing_limits(bytes(caps))
            logger.info("capabilities: 0x%X", self._capabilities)
        else:
            raise RuntimeError("device returned invalid capabilities")
        self._detect_protocol()
        self._ctrl_out_checked(GS_ReqSetHostFormat,
                               data=struct.pack('<I', HOST_FORMAT_MAGIC))

        ver = self._ctrl_in(GS_ReqGetDeviceVersion, length=16)
        if ver and len(ver) >= 12:
            sw = struct.unpack_from('<I', bytes(ver), 4)[0]
            hw = struct.unpack_from('<I', bytes(ver), 8)[0]
            logger.info("firmware: 0x%08X, hardware: 0x%08X", sw, hw)

    def _reset_device(self):
        flags = ELM_DevFlagProtocolElmue
        try:
            self._ctrl_out(GS_ReqSetDeviceMode,
                           data=struct.pack('<II', 0, flags))
            time.sleep(0.05)
        except usb.core.USBError:
            logger.debug("RESET failed (device may already be closed)")

    def _detect_protocol(self):
        if self._capabilities & ELM_DevFlagProtocolElmue:
            self._protocol = "elmue"
            self._parser = _ElmueProtocol()
            logger.info("using ElmueSoft variable-length protocol")
        else:
            self._protocol = "legacy"
            self._parser = None
            logger.info("using Legacy fixed-length protocol (80 bytes)")

    # ================================================================
    #  USB control transfers
    # ================================================================
    def _ctrl_out(self, req, value=0, index=0, data=None, timeout=1000):
        bmRequestType = (usb.util.CTRL_OUT
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        if data is None:
            data = []
        with self._lock:
            if self.dev is None:
                raise RuntimeError("USB device is not open")
            written = self.dev.ctrl_transfer(bmRequestType, req, value, index, data, timeout)
            if written != len(data):
                raise RuntimeError(f"short USB control write: {written}/{len(data)} bytes")
            return written

    def _ctrl_in(self, req, value=0, index=0, length=64, timeout=1000):
        bmRequestType = (usb.util.CTRL_IN
                         | usb.util.CTRL_TYPE_VENDOR
                         | usb.util.CTRL_RECIPIENT_INTERFACE)
        with self._lock:
            if self.dev is None:
                raise RuntimeError("USB device is not open")
            return self.dev.ctrl_transfer(bmRequestType, req, value, index, length, timeout)

    def _ctrl_out_checked(self, req, value=0, index=0, data=None, timeout=1000):
        # Keep SET + GetLastError atomic: any other SETUP request clears the
        # firmware feedback. Legacy firmware has no GetLastError command.
        with self._lock:
            self._ctrl_out(req, value, index, data, timeout)
            if self._protocol == "elmue":
                feedback = self._check_last_error()
                if feedback not in (0, 2):
                    raise CANableCommandError(req, feedback)

    def _check_last_error(self) -> int:
        result = self._ctrl_in(ELM_ReqGetLastError, length=1)
        if result is None or len(result) != 1:
            raise RuntimeError("device returned invalid command feedback")
        return result[0]

    # ================================================================
    #  CAN controller lifecycle
    # ================================================================
    def start(self, loopback: Optional[bool] = None, disable_echo: Optional[bool] = None,
              one_shot: Optional[bool] = None):
        with self._lifecycle(), self._lock:
            self._start(loopback, disable_echo, one_shot)

    def _start(self, loopback, disable_echo, one_shot):
        if self.dev is None:
            raise RuntimeError("USB device is not open")
        if self._running:
            raise RuntimeError("CAN is already started")
        if self._bitrate is None:
            raise RuntimeError("set nominal bitrate before starting CAN")
        if self._fd_mode and self._data_bitrate is None:
            raise RuntimeError("set data bitrate before starting CAN FD")
        loopback = self._loopback if loopback is None else bool(loopback)
        disable_echo = self._disable_echo if disable_echo is None else bool(disable_echo)
        one_shot = self._one_shot if one_shot is None else bool(one_shot)

        # FD is enabled implicitly by configuring data timing in this firmware.
        if self._data_configured and not self._fd_mode:
            raise RuntimeError("data timing is configured; enable FD mode before starting CAN")
        if not self._nominal_configured:
            self.set_bitrate(self._bitrate, self._sample_point)
        if self._fd_mode and not self._data_configured:
            self.set_data_bitrate(self._data_bitrate, self._data_sample_point)
        if self._needs_reconfigure and self._filters:
            self._ctrl_out_checked(ELM_ReqSetFilter, data=struct.pack('<BIIII', FIL_ClearAll, 0, 0, 0, 0))
            for operation, can_id, mask in self._filters:
                self._ctrl_out_checked(ELM_ReqSetFilter,
                                       data=struct.pack('<BIIII', operation, can_id, mask, 0, 0))
        self._clear_receive_buffers(drain=True)
        flags = 0
        if self._protocol == "elmue":
            flags |= ELM_DevFlagProtocolElmue

        if self._listen_only:
            flags |= GS_DevFlagListenOnly

        if loopback:
            flags |= GS_DevFlagLoopback

        if one_shot:
            flags |= GS_DevFlagOneShot

        if disable_echo:
            flags |= ELM_DevFlagDisableTxEcho

        if self._fd_mode:
            flags |= GS_DevFlagCAN_FD

        payload = struct.pack('<II', GS_ModeStart, flags)
        self._ctrl_out_checked(GS_ReqSetDeviceMode, data=payload)

        self._has_timestamp = bool(flags & GS_DevFlagTimestamp)
        if self._parser and isinstance(self._parser, _ElmueProtocol):
            self._parser.set_timestamp_mode(self._has_timestamp)

        self._running = True
        self._loopback, self._disable_echo, self._one_shot = loopback, disable_echo, one_shot
        self._needs_reconfigure = False
        self._last_error_info = None
        if self._bus_load_interval:
            self.set_bus_load_report(self._bus_load_interval)
        time.sleep(0.05)  # allow transceiver/isolator to power up
        logger.info("CAN started (protocol=%s, FD=%s, loopback=%s, flags=0x%X, bitrate=%s, data_bitrate=%s)",
                    self._protocol, self._fd_mode, bool(flags & GS_DevFlagLoopback),
                    flags, self._bitrate, self._data_bitrate)

    def stop(self):
        with self._lifecycle():
            self.stop_listening()
            with self._lock:
                if self.dev is None:
                    self._running = False
                    self._clear_receive_buffers()
                    return
                self._stop_controller()

    def _protocol_flag(self):
        return ELM_DevFlagProtocolElmue if self._protocol == "elmue" else 0

    def _stop_controller(self):
        try:
            self._ctrl_out_checked(GS_ReqSetDeviceMode,
                                   data=struct.pack('<II', 0, self._protocol_flag()))
        finally:
            # On a transport failure the device state is uncertain. Do not
            # permit more TX until configuration/start has succeeded again.
            self._running = False
            self._session_id += 1
            self._nominal_configured = self._data_configured = False
            self._needs_reconfigure = True
            self._clear_receive_buffers(drain=True)
        logger.info("CAN stopped")

    def recover(self):
        with self._lifecycle():
            listening = self._is_listening()
            self.stop()
            self.start()
            self._tx_blocked_until = time.monotonic() + 0.3
            self._resume_listener(listening)
            logger.info("CAN recovered")

    def _clear_receive_buffers(self, drain=False):
        with self._receive_lock:
            if self._parser is not None:
                self._parser.clear()
            if drain and self.ep_in is not None:
                # A stopped controller cannot generate new CAN data. Drain its
                # queued USB messages before accepting frames in a new session.
                for _ in range(256):
                    try:
                        self.ep_in.read(256, timeout=1)
                    except usb.core.USBError:
                        break

    def _load_timing_limits(self, raw, fd=False):
        if len(raw) < (72 if fd else 40):
            return
        clock = struct.unpack_from('<I', raw, 4)[0]
        nominal = TimingLimits(*struct.unpack_from('<8I', raw, 8))
        data = TimingLimits(*struct.unpack_from('<8I', raw, 40)) if fd else None
        for limits in (nominal, data):
            if limits is not None and not (1 <= limits.seg1_min <= limits.seg1_max <= 256
                    and 1 <= limits.seg2_min <= limits.seg2_max <= 128
                    and 1 <= limits.brp_min <= limits.brp_max <= 1024
                    and 1 <= limits.brp_inc <= limits.brp_max
                    and 1 <= limits.sjw_max <= 128):
                raise RuntimeError("device returned invalid bit timing limits")
        if clock <= 0:
            raise RuntimeError("device returned invalid CAN clock")
        self._can_clock = clock
        self._nominal_limits = nominal
        if data is not None:
            self._data_limits = data

    # ================================================================
    #  Bit timing configuration
    # ================================================================
    def set_bitrate(self, bitrate: int, sample_point: float | None = None):
        with self._lock:
            if self._running:
                raise RuntimeError("stop CAN before changing bitrate")
            brp, seg1, seg2, sjw = self._select_timing(bitrate, sample_point, False)
            payload = struct.pack('<IIIII', 0, seg1, seg2, sjw, brp)
            self._ctrl_out_checked(GS_ReqSetBitTiming, data=payload)
            self._bitrate = bitrate
            self._sample_point = sample_point
            self._nominal_configured = True
        sample_pct = (1 + seg1) / (1 + seg1 + seg2) * 100
        logger.info("nominal bitrate set: %d bps (brp=%d seg1=%d seg2=%d sjw=%d sample=%.1f%%)",
                    bitrate, brp, seg1, seg2, sjw, sample_pct)

    def set_data_bitrate(self, data_bitrate: int, sample_point: float | None = None):
        with self._lock:
            if self._running:
                raise RuntimeError("stop CAN before changing data bitrate")
            if not self._capabilities_fd and self._capabilities & GS_DevFlagCAN_FD:
                self.check_fd_support()
            brp, seg1, seg2, sjw = self._select_timing(data_bitrate, sample_point, True)
            payload = struct.pack('<IIIII', 0, seg1, seg2, sjw, brp)
            self._ctrl_out_checked(GS_ReqSetBitTimingFD, data=payload)
            self._data_bitrate = data_bitrate
            self._data_sample_point = 0.5 if data_bitrate == 8_000_000 else sample_point
            self._data_configured = True
        sample_pct = (1 + seg1) / (1 + seg1 + seg2) * 100
        logger.info("data bitrate set: %d bps (brp=%d seg1=%d seg2=%d sjw=%d sample=%.1f%%)",
                    data_bitrate, brp, seg1, seg2, sjw, sample_pct)

    def _calc_bitrate_params(self, bitrate: int, data_phase: bool = False,
                             sample_point: float | None = None):
        if not isinstance(bitrate, int) or isinstance(bitrate, bool) or bitrate <= 0:
            raise ValueError("bitrate must be a positive integer")
        if sample_point is None:
            sample_point = 0.75 if data_phase else 0.875
        if not math.isfinite(sample_point) or not 0 < sample_point < 1:
            raise ValueError("sample point must be between 0 and 1")
        limits = self._data_limits if data_phase else self._nominal_limits
        return calculate_timing(bitrate, self._can_clock, limits, sample_point)

    def _select_timing(self, bitrate, sample_point, data_phase):
        # Validate even when a precomputed timing will be used.
        if sample_point is not None and (not math.isfinite(sample_point)
                                        or not 0 < sample_point < 1):
            raise ValueError("sample point must be between 0 and 1")
        effective_sample = 0.5 if data_phase and bitrate == 8_000_000 else sample_point
        timing = self._calc_bitrate_params(bitrate, data_phase, effective_sample)
        table = DATA_BITTIMING if data_phase else NOMINAL_BITTIMING
        limits = self._data_limits if data_phase else self._nominal_limits
        if (sample_point is None or (data_phase and bitrate == 8_000_000)):
            preset = table.get(bitrate)
            if self._can_clock == 160_000_000 and preset and limits.accepts(preset):
                return preset
        return timing

    # ================================================================
    #  Send / Receive
    # ================================================================
    def send(self, frame: CANFrame, timeout: int = 1000):
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("send timeout must be a positive number of milliseconds")
        short_write = False
        try:
            with self._lock:
                if not self._running:
                    raise RuntimeError("CAN not started")
                if time.monotonic() < self._tx_blocked_until:
                    raise RuntimeError("CAN recovering, please wait")
                if frame.fd and not self._fd_mode:
                    raise ValueError("CAN FD is not enabled on this controller")
                snapshot = replace(frame, data=frame.tx_payload())
                if self._protocol == "elmue":
                    marker = 0 if self._disable_echo else self._parser.reserve_tx_frame(snapshot)
                    raw = snapshot.to_elmue_bytes(marker=marker)
                else:
                    raw = snapshot.to_legacy_bytes()
                written = self.ep_out.write(raw, timeout=timeout)
                if written != len(raw):
                    short_write = True
                    raise usb.core.USBError(f"short USB write: {written}/{len(raw)} bytes", errno=5)
                if len(raw) > 0 and len(raw) % MAX_PACKET_SIZE == 0:
                    self.ep_out.write(b'', timeout=timeout)
        except usb.core.USBError as e:
            pipe_error = getattr(e, 'errno', None) in (32, 232) or 'pipe' in str(e).lower()
            if pipe_error or short_write:
                logger.warning("USB TX failed; recovering controller: %s", e)
                try:
                    if pipe_error:
                        self.ep_out.clear_halt()
                    self.recover()
                    self._tx_blocked_until = time.monotonic() + 0.5
                except Exception:
                    self._running = False
                    logger.exception("USB TX recovery failed")
                    raise
            # Never retransmit automatically: the device may have accepted it.
            raise

    def send_periodic(self, frame: CANFrame, interval_s: float = 0.01, count: int = 0):
        if not math.isfinite(interval_s) or interval_s <= 0:
            raise ValueError("interval_s must be positive")
        if not isinstance(count, int) or count < 0:
            raise ValueError("count must be a nonnegative integer")
        sent = 0
        deadline = time.monotonic()
        while count == 0 or sent < count:
            self.send(frame)
            sent += 1
            if count == 0 or sent < count:
                deadline += interval_s
                now = time.monotonic()
                if deadline < now:
                    deadline = now
                time.sleep(max(0.0, deadline - now))

    def receive(self, timeout: float = 1.0) -> Optional[CANFrame]:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("receive timeout must be finite and nonnegative")
        if not self._running:
            raise RuntimeError("CAN not started")
        if self._is_listening() and threading.current_thread() is not self._recv_thr:
            raise RuntimeError("background listener owns CAN receive")
        if not self._reader_lock.acquire(blocking=False):
            raise RuntimeError("another thread owns CAN receive")
        try:
            return self._receive_until(timeout)
        finally:
            self._reader_lock.release()

    def _receive_until(self, timeout):
        deadline = time.monotonic() + timeout
        session_id = self._session_id
        first = True
        # Only hold the RX state lock during a bounded read/parse. Callbacks
        # run outside it so they can safely stop or recover the controller.
        while (self._running and session_id == self._session_id
               and (first or time.monotonic() < deadline)):
            if threading.current_thread() is self._recv_thr and self._listen_stop.is_set():
                break
            first = False
            remaining = max(0.0, min(0.1, deadline - time.monotonic()))
            with self._receive_lock:
                if not self._running or session_id != self._session_id:
                    break
                self._rx_overflow = False
                frame = (self._recv_elmue(remaining) if self._protocol == "elmue"
                         else self._recv_legacy(remaining))
            if not self._running or session_id != self._session_id:
                break
            if self._rx_overflow:
                self._notify_overflow()
            if frame is not None:
                if frame.is_error:
                    self._last_error_info = frame._error_info
                return frame
        return None

    def _recv_elmue(self, timeout: float = 1.0) -> Optional[CANFrame]:
        if self._parser is not None:
            frame = self._parser.pop_pending()
            if frame is not None:
                return frame

        try:
            data = self.ep_in.read(256, timeout=max(1, math.ceil(timeout * 1000)))
        except usb.core.USBError as e:
            errno = getattr(e, "errno", None)
            if errno in (110, 10060) or "timeout" in str(e).lower():
                return None
            if errno in (75, 121) or "overflow" in str(e).lower():
                self._parser.reset_rx()
                self._rx_overflow = True
                return None
            raise

        if not data:
            return None

        raw = bytes(data)
        frames = self._parser.feed(raw)

        return self._take_first_frame(frames)

    def _take_first_frame(self, frames: list) -> Optional[CANFrame]:
        """Return first frame, push the rest to pending buffer."""
        if not frames:
            return None
        if len(frames) > 1:
            self._parser.push_pending(frames[1:])
        return frames[0]

    def _recv_legacy(self, timeout: float = 1.0) -> Optional[CANFrame]:
        try:
            # Round to an endpoint packet multiple to avoid libusb overflow
            # when a transfer contains the 64-byte first packet of an FD frame.
            data = self.ep_in.read(128, timeout=max(1, math.ceil(timeout * 1000)))
        except usb.core.USBError as e:
            errno = getattr(e, "errno", None)
            if errno in (110, 10060) or "timeout" in str(e).lower():
                return None
            if errno in (75, 121) or "overflow" in str(e).lower():
                self._rx_overflow = True
                return None
            raise

        if not data:
            return None

        return CANFrame.from_legacy_bytes(bytes(data), has_timestamp=self._has_timestamp,
                                          fd_mode=self._fd_mode)

    def _notify_overflow(self):
        if self._overflow_cb:
            try:
                self._overflow_cb()
            except Exception:
                logger.exception("overflow callback failed")

    # ================================================================
    #  Feature queries & settings
    # ================================================================
    def check_fd_support(self) -> bool:
        try:
            caps_fd = self._ctrl_in(GS_ReqGetCapabilitiesFD, length=72)
            if caps_fd and len(caps_fd) >= 4:
                self._capabilities_fd = struct.unpack_from('<I', bytes(caps_fd), 0)[0]
                self._load_timing_limits(bytes(caps_fd), fd=True)
        except usb.core.USBError:
            pass

        fd_supported = bool((self._capabilities | self._capabilities_fd) & GS_DevFlagCAN_FD)
        fd_timing = bool((self._capabilities | self._capabilities_fd) & GS_DevFlagBitTimingFD)
        supported = fd_supported and fd_timing
        logger.info("FD support: %s (caps=0x%X, caps_fd=0x%X)",
                    supported, self._capabilities, self._capabilities_fd)
        return supported

    def get_version(self) -> Optional[str]:
        """Return firmware version as human-readable string (e.g. '25.10.23')."""
        try:
            ver = self._ctrl_in(GS_ReqGetDeviceVersion, length=16)
            if ver and len(ver) >= 12:
                sw = struct.unpack_from('<I', bytes(ver), 4)[0]
                hw = struct.unpack_from('<I', bytes(ver), 8)[0]
                # BCD format: 0x251023 → "25.10.23"
                def bcd(value):
                    return (value >> 4) * 10 + (value & 0x0F)
                major = bcd((sw >> 16) & 0xFF)
                minor = bcd((sw >> 8) & 0xFF)
                patch = bcd(sw & 0xFF)
                return f"{major}.{minor:02d}.{patch:02d} (fw=0x{sw:08X}, hw=0x{hw:08X})"
        except usb.core.USBError:
            pass
        return None

    def read_error_register(self) -> Optional[str]:
        return self._last_error_info

    def identify(self, duration_ms: int = 1000):
        try:
            self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 1))
            time.sleep(duration_ms / 1000.0)
            self._ctrl_out(GS_ReqIdentify, data=struct.pack('<I', 0))
            time.sleep(0.02)
        except usb.core.USBError:
            pass

    def set_silent(self, enable: bool) -> bool:
        with self._lifecycle():
            if self._listen_only == bool(enable):
                return True
            was_running = self._running
            listening = self._is_listening()
            if was_running:
                self.stop()
            self._listen_only = bool(enable)
            if was_running:
                self.start()
                self._resume_listener(listening)
        return True

    # ================================================================
    #  Extended features
    # ================================================================
    def set_filter(self, operation: int = 0, can_id: int = 0, mask: int = 0):
        """Set hardware acceptance filter.

        Args:
            operation: FIL_ClearAll (0), FIL_AcceptMask11bit (1), or FIL_AcceptMask29bit (2).
            can_id: Filter value (e.g. 0x7E0). Ignored for FIL_ClearAll.
            mask: Mask value (e.g. 0x7FF). Ignored for FIL_ClearAll.
        """
        with self._lock:
            payload = struct.pack('<BIIII', operation, can_id, mask, 0, 0)
            self._ctrl_out_checked(ELM_ReqSetFilter, data=payload)
            if operation == FIL_ClearAll:
                self._filters.clear()
            else:
                self._filters.append((operation, can_id, mask))
        logger.info("filter set: op=%d id=0x%X mask=0x%X", operation, can_id, mask)

    def clear_filters(self):
        """Remove all hardware acceptance filters."""
        self.set_filter(FIL_ClearAll)

    def get_termination(self) -> Optional[bool]:
        try:
            result = self._ctrl_in(GS_ReqGetTermination, length=4)
            if result and len(result) >= 4:
                return bool(struct.unpack_from('<I', bytes(result), 0)[0])
        except usb.core.USBError:
            pass
        return None

    def set_termination(self, enabled: bool):
        payload = struct.pack('<I', 1 if enabled else 0)
        self._ctrl_out_checked(GS_ReqSetTermination, data=payload)
        logger.info("termination: %s", "ON" if enabled else "OFF")

    def set_bus_load_report(self, interval: int = 0):
        """Enable periodic bus load report.

        Args:
            interval: 0=off, 1..100 in units of 100 ms.
        """
        if not isinstance(interval, int) or not 0 <= interval <= 100:
            raise ValueError("bus load interval must be in 0..100 (100 ms units)")
        with self._lock:
            payload = struct.pack('<B', interval)
            self._ctrl_out_checked(ELM_ReqSetBusLoadReport, data=payload)
            self._bus_load_interval = interval

    def get_board_info(self) -> Optional[dict]:
        """Return board information (MCU name, board name, device ID)."""
        try:
            result = self._ctrl_in(ELM_ReqGetBoardInfo, length=55)
            if result and len(result) >= 52:
                raw = bytes(result)
                mcu_id = struct.unpack_from('<H', raw, 0)[0]
                # Two 25-char null-terminated strings at offset 2 and 27
                mcu_name = raw[2:27].split(b'\x00', 1)[0].decode('ascii', errors='replace')
                board_name = raw[27:52].split(b'\x00', 1)[0].decode('ascii', errors='replace')
                return {
                    "mcu_device_id": f"0x{mcu_id:03X}",
                    "mcu_name": mcu_name,
                    "board_name": board_name,
                }
        except usb.core.USBError:
            pass
        return None

    def get_timestamp(self) -> Optional[int]:
        """Return firmware 1μs precision timestamp (rolls over after ~1 hour)."""
        try:
            result = self._ctrl_in(GS_ReqGetTimestamp, length=4)
            if result and len(result) >= 4:
                return struct.unpack_from('<I', bytes(result), 0)[0]
        except usb.core.USBError:
            pass
        return None

    def set_pin_status(self, pin_id: int, operation: int):
        """Control a processor pin.

        Args:
            pin_id: ePinID constant (e.g. PINID_BOOT0=1).
            operation: ePinOperation constant (PINOP_Reset/Set/Tristate/etc.).
        """
        payload = struct.pack('<HHII', operation, pin_id, 0, 0)
        self._ctrl_out_checked(ELM_ReqSetPinStatus, data=payload)
        logger.info("pin %d: operation=%d", pin_id, operation)

    def get_pin_status(self, pin_id: int) -> Optional[int]:
        """Read a processor pin status.

        Args:
            pin_id: ePinID constant (e.g. PINID_BOOT0=1).

        Returns:
            Bit flags: PINST_High (0x01), PINST_Enabled (0x02), or None on error.
        """
        try:
            result = self._ctrl_in(ELM_ReqGetPinStatus, value=pin_id, length=2)
            if result and len(result) >= 2:
                return struct.unpack_from('<H', bytes(result), 0)[0]
        except usb.core.USBError:
            pass
        return None

    # ================================================================
    #  Callbacks & listening
    # ================================================================
    def on_receive(self, callback: Callable[[CANFrame], None]):
        self._callbacks.append(callback)

    def on_overflow(self, callback: Callable[[], None]):
        self._overflow_cb = callback

    def start_listening(self):
        with self._lifecycle(), self._listener_lock:
            if not self._running:
                raise RuntimeError("start CAN before starting the listener")
            if self._recv_thr is not None and self._recv_thr.is_alive():
                if self._listen_stop.is_set():
                    raise RuntimeError("previous receive thread is still stopping")
                return
            if self._reader_lock.locked():
                raise RuntimeError("another thread owns CAN receive")
            self._listen_stop = threading.Event()
            self._recv_thr = threading.Thread(target=self._listen_loop,
                                              args=(self._listen_stop,), daemon=True)
            self._recv_thr.start()

    def stop_listening(self):
        """Stop callback delivery and wait for the receive thread to exit."""
        with self._listener_lock:
            thread = self._recv_thr
            self._listen_stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError("receive callback has not exited; USB device remains open")

    def _is_listening(self):
        return (self._recv_thr is not None and self._recv_thr.is_alive()
                and not self._listen_stop.is_set())

    def _resume_listener(self, was_listening):
        if was_listening:
            if threading.current_thread() is self._recv_thr:
                self._listen_stop.clear()
            else:
                self.start_listening()

    def _listen_loop(self, stop_event):
        while self._running and not stop_event.is_set():
            try:
                frame = self.receive(timeout=0.1)
                if frame is not None:
                    for cb in tuple(self._callbacks):
                        if stop_event.is_set():
                            break
                        try:
                            cb(frame)
                        except Exception:
                            logger.exception("receive callback failed")
            except Exception as e:
                if self._running and not stop_event.is_set():
                    logger.warning("receive error: %s", e)
                stop_event.wait(0.01)
