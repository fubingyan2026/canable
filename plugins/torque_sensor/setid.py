"""扭矩传感器站号扫描 / 设置 ID 状态机 — 在宿主 CAN worker 线程独占模式运行。

依据 G0_Torque_SetID（protocol.h / main.c）：
- 请求 = 0x500 + 站号×0x10，响应 = 0x400 + 站号×0x10，仅标准帧
- 扫描站号 1..47：每站发 8 字节查询 ``04 00 00 00 00 00 00 00``，
  等待 50ms 统计匹配应答；仅当恰好一个站号应答且无多回复时才允许改号
- 改号：向当前站号发 DLC=7 ``10 00 90 <目标站号大端 float32>``，
  等待最多 1s；旧地址或新地址返回 ``10 00 90 3F 80 00 00`` 视为成功

``SetIdTask`` 是 plain object（worker 线程调用 ``run(bus)``）；
``SetIdSignals`` 是主线程 QObject，跨线程 emit 安全。
日志与结果以 i18n key + 参数发出，由 widget 翻译，避免硬编码文本。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from PySide6.QtCore import QObject, Signal

from canable_sdk import ZDTCanable

from . import protocol as P


class _Cancelled(Exception):
    """用户取消。"""


class SetIdSignals(QObject):
    """扫描/改号过程信号（主线程 QObject，供 widget 连接）。"""

    progress = Signal(int, int)     # 已扫描站号, 总数
    found = Signal(int, int)        # 站号, 匹配回复数
    log = Signal(str, str, object)  # level, i18n key, 参数 dict
    finished = Signal(bool, str)    # ok, 结果码


@dataclass
class SetIdResult:
    found_stations: List[int] = field(default_factory=list)
    ambiguous: bool = False
    current: Optional[int] = None
    target: Optional[int] = None
    wrote: bool = False


class SetIdTask:
    """扫描并在必要时改号；在 worker 线程上同步执行。"""

    def __init__(self, signals: SetIdSignals, target: Optional[int] = None,
                 stop_stations: Sequence[int] = ()):
        self._sig = signals
        self._target = target
        self._stop_stations = tuple(stop_stations)
        self.cancel_requested = False
        self.result = SetIdResult()
        self._bus: Optional[ZDTCanable] = None
        self._done = False

    # ── 主线程 ──
    def cancel(self) -> None:
        self.cancel_requested = True

    # ── worker 线程 ──
    def run(self, bus: ZDTCanable) -> None:
        self._bus = bus
        try:
            if self._stop_stations:
                for station in self._stop_stations:
                    self._bus.send(P.build_stop_report_station(station))
                time.sleep(0.02)
                self._drain()
            current = self._scan()
            if current is None:
                self._finish(False, "scan_failed")
                return
            self.result.current = current
            if self._target is None:
                self._finish(True, "scan_only")
                return
            if not P.station_valid(self._target):
                self._finish(False, "bad_target")
                return
            self._write_id(current, int(self._target))
        except _Cancelled:
            self._finish(False, "cancelled")
        except Exception as exc:  # noqa: BLE001 - 汇报给 UI，不让 worker 崩溃
            self._log("error", "Torque.SetId.Log.Error", {"msg": str(exc)})
            self._finish(False, "error")

    # ── 内部 ──
    def _finish(self, ok: bool, code: str) -> None:
        if not self._done:
            self._done = True
            self._sig.finished.emit(ok, code)

    def _log(self, level: str, key: str, params=None) -> None:
        self._sig.log.emit(level, key, params or {})

    def _drain(self) -> None:
        """清空接收缓冲，避免上一站/主动上报残留影响下一窗口。"""
        for _ in range(200):
            if self._bus.receive(timeout=0.001) is None:
                break

    def _scan(self) -> Optional[int]:
        self._log("info", "Torque.SetId.Log.ScanStart", {"max": P.MAX_SENSOR_ID})
        found: List[int] = []
        ambiguous = False
        for station in range(1, P.MAX_SENSOR_ID + 1):
            if self.cancel_requested:
                raise _Cancelled()
            self._sig.progress.emit(station, P.MAX_SENSOR_ID)
            self._drain()
            self._bus.send(P.build_scan_query(station))
            deadline = time.monotonic() + P.SCAN_QUERY_WINDOW_S
            replies = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                if self.cancel_requested:
                    raise _Cancelled()
                frame = self._bus.receive(
                    timeout=max(0.001, min(remaining, 0.005)))
                if frame is None or getattr(frame, "is_tx", False) or frame.is_error:
                    continue
                if P.match_scan_reply(station, frame.can_id, frame.data,
                                      frame.extended):
                    replies += 1
            self._drain()
            if replies:
                found.append(station)
                self._sig.found.emit(station, replies)
                if replies > 1:
                    ambiguous = True
        self.result.found_stations = found
        self.result.ambiguous = ambiguous
        if len(found) != 1 or ambiguous:
            self._log("warn", "Torque.SetId.Log.ScanReject",
                      {"count": len(found), "multi": ambiguous})
            return None
        self._log("info", "Torque.SetId.Log.ScanFound", {"station": found[0]})
        return found[0]

    def _write_id(self, current: int, target: int) -> None:
        if self.cancel_requested:
            raise _Cancelled()
        self.result.target = target
        self._drain()
        self._log("info", "Torque.SetId.Log.Writing",
                  {"current": current, "target": target})
        self._bus.send(P.build_set_id(current, target))
        # 命令已发出后不再响应取消：必须等到应答才能判断地址是否已改变
        deadline = time.monotonic() + P.SET_ID_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            frame = self._bus.receive(timeout=max(0.001, min(remaining, 0.01)))
            if frame is None or getattr(frame, "is_tx", False) or frame.is_error:
                continue
            verdict = P.match_set_id_ack(current, target, frame.can_id,
                                         frame.data, frame.extended)
            if verdict is None:
                continue
            if verdict:
                self.result.wrote = True
                self._log("info", "Torque.SetId.Log.WriteOk", {"target": target})
                self._finish(True, "write_ok")
            else:
                self._finish(False, "write_error")
            return
        self._finish(False, "write_timeout")
