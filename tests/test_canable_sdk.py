"""SDK regression tests using the repository firmware's control semantics.

Run with: python -B -m unittest discover -s tests -v
"""

import queue
import random
import runpy
import struct
import threading
import unittest
from unittest.mock import patch

import usb.core

from canable_sdk import CANFrame, CANableCommandError, ZDTCanable
from canable_sdk.bitrate import TimingLimits
from canable_sdk.constants import (
    ECHO_RxData, ELM_DevFlagProtocolElmue,
    ELM_ReqGetLastError, ELM_ReqSetBusLoadReport, ELM_ReqSetFilter,
    ERID_Bus_is_off, FIL_AcceptMask11bit, FIL_ClearAll, FRM_FDF,
    GS_DevFlagCAN_FD, GS_DevFlagBitTimingFD, GS_DevFlagListenOnly,
    GS_DevFlagLoopback, GS_DevFlagOneShot, GS_ReqGetCapabilities,
    GS_ReqGetCapabilitiesFD, GS_ReqGetDeviceVersion, GS_ReqSetBitTiming,
    GS_ReqSetBitTimingFD, GS_ReqSetDeviceMode, MSG_Busload, MSG_Error,
    MSG_RxFrame, MSG_TxEcho,
)
from canable_sdk.protocol import _ElmueProtocol


def rx_message(can_id=0x123, data=b'12345678', fd=False, timestamp=None):
    body = struct.pack('<BI', FRM_FDF if fd else 0, can_id)
    if timestamp is not None:
        body += struct.pack('<I', timestamp)
    body += data
    return bytes([len(body) + 2, MSG_RxFrame]) + body


def error_message(err_id=0, byte1=0):
    return struct.pack('<BBI', 14, MSG_Error, err_id) + bytes([0, byte1, 0, 0, 0, 0, 129, 129])


class FakeIn:
    def __init__(self):
        self.messages = queue.Queue()
        self.timeouts = []
        self.reading = threading.Event()

    def read(self, size, timeout):
        self.timeouts.append(timeout)
        self.reading.set()
        try:
            message = self.messages.get(timeout=timeout / 1000)
        except queue.Empty:
            raise usb.core.USBTimeoutError('timeout', errno=110)
        if isinstance(message, Exception):
            raise message
        return message


class FakeOut:
    def __init__(self):
        self.writes = []
        self.failure = None
        self.short = False
        self.cleared = 0

    def write(self, raw, timeout):
        self.writes.append(bytes(raw))
        if self.failure is not None:
            failure, self.failure = self.failure, None
            raise failure
        return 3 if self.short else len(raw)

    def clear_halt(self):
        self.cleared += 1


class FakeDevice:
    """Reset clears timings/filters, as can_close -> can_reset does."""

    def __init__(self, legacy=False):
        self.legacy = legacy
        self.running = False
        self.nominal = None
        self.data = None
        self.flags = 0
        self.filters = []
        self.interval = 0
        self.feedback = 2
        self.reject = {}
        self.requests = []
        self.short_feedback = False
        self.ep_in = FakeIn()
        self.ep_out = FakeOut()

    def ctrl_transfer(self, bm, request, value, index, data, timeout):
        self.requests.append((bm, request, data))
        if bm & 128:
            if request == ELM_ReqGetLastError:
                if self.legacy:
                    raise usb.core.USBError('pipe', errno=32)
                return b'' if self.short_feedback else bytes([self.feedback])
            feature = GS_DevFlagCAN_FD | GS_DevFlagBitTimingFD
            if not self.legacy:
                feature |= ELM_DevFlagProtocolElmue
            nominal = (1, 256, 1, 128, 128, 1, 512, 1)
            if request == GS_ReqGetCapabilities:
                return struct.pack('<10I', feature, 160_000_000, *nominal)
            if request == GS_ReqGetCapabilitiesFD:
                return struct.pack('<18I', feature, 160_000_000, *nominal,
                                   1, 32, 1, 16, 16, 1, 32, 1)
            if request == GS_ReqGetDeviceVersion:
                return struct.pack('<IIII', 0, 0x251023, 0x200, 0)
            return b''
        self.feedback = self.reject.get(request, 2)
        if self.feedback != 2:
            return len(data)
        if request in (GS_ReqSetBitTiming, GS_ReqSetBitTimingFD):
            if self.running:
                self.feedback = 52
            elif request == GS_ReqSetBitTiming:
                self.nominal = bytes(data)
            else:
                self.data = bytes(data)
        elif request == GS_ReqSetDeviceMode:
            mode, flags = struct.unpack('<II', data)
            if mode:
                if self.running:
                    self.feedback = 52
                elif self.nominal is None or (flags & GS_DevFlagCAN_FD and self.data is None):
                    self.feedback = 58
                else:
                    self.running = True
                    self.flags = flags
            else:
                if self.running:
                    self.nominal = self.data = None
                    self.filters.clear()
                    self.interval = 0
                self.running = False
                self.flags = flags
        elif request == ELM_ReqSetFilter:
            operation, can_id, mask, _, _ = struct.unpack('<BIIII', data)
            if operation == FIL_ClearAll:
                self.filters.clear()
            else:
                self.filters.append((operation, can_id, mask))
        elif request == ELM_ReqSetBusLoadReport:
            self.interval = data[0]
        return len(data)


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.pause = patch('canable_sdk.driver.time.sleep')
        self.pause.start()
        self.dispose = patch('canable_sdk.driver.usb.util.dispose_resources')
        self.dispose.start()
        self.bus = ZDTCanable()
        self.device = FakeDevice()
        self.bus.dev = self.device
        self.bus.ep_in = self.device.ep_in
        self.bus.ep_out = self.device.ep_out
        self.bus._init_device()

    def tearDown(self):
        self.bus.close()
        self.dispose.stop()
        self.pause.stop()

    def start(self, fd=False, **options):
        self.bus.fd_mode = fd
        self.bus.set_bitrate(500_000)
        if fd:
            self.bus.set_data_bitrate(2_000_000)
        self.bus.start(**options)

    def test_firmware_rejection_does_not_commit_configuration(self):
        self.device.reject[GS_ReqSetBitTiming] = 50
        with self.assertRaises(CANableCommandError) as caught:
            self.bus.set_bitrate(500_000)
        self.assertEqual(caught.exception.feedback, 50)
        self.assertIsNone(self.bus._bitrate)
        self.assertFalse(self.bus.running)

    def test_rejected_start_does_not_claim_running(self):
        self.bus.set_bitrate(500_000)
        self.device.reject[GS_ReqSetDeviceMode] = 53
        with self.assertRaises(CANableCommandError):
            self.bus.start()
        self.assertFalse(self.bus.running)
        self.assertFalse(self.device.running)

    def test_empty_feedback_is_an_error(self):
        self.device.short_feedback = True
        with self.assertRaisesRegex(RuntimeError, 'feedback'):
            self.bus.set_bitrate(500_000)
        self.assertIsNone(self.bus._bitrate)

    def test_close_resets_a_start_that_succeeded_without_feedback(self):
        self.bus.set_bitrate(500_000)
        self.device.short_feedback = True
        with self.assertRaisesRegex(RuntimeError, 'feedback'):
            self.bus.start()
        self.assertFalse(self.bus.running)
        self.assertTrue(self.device.running)
        self.bus.close()
        self.assertFalse(self.device.running)
        self.assertIsNone(self.bus.dev)

    def test_legacy_does_not_query_elmue_feedback(self):
        self.device.legacy = True
        self.bus._init_device()
        self.device.requests.clear()
        self.bus.set_bitrate(500_000)
        self.bus.start()
        self.assertTrue(self.bus.running)
        self.assertNotIn(ELM_ReqGetLastError, [r[1] for r in self.device.requests])

    def test_running_configuration_changes_are_rejected(self):
        self.start()
        for action in (lambda: self.bus.set_bitrate(250_000),
                       lambda: self.bus.set_data_bitrate(1_000_000),
                       lambda: setattr(self.bus, 'fd_mode', True)):
            with self.assertRaises(RuntimeError):
                action()
        self.assertEqual(self.bus._bitrate, 500_000)

    def test_restart_restores_fd_modes_filters_and_report(self):
        self.bus.fd_mode = True
        self.bus.set_bitrate(500_000, 0.875)
        self.bus.set_data_bitrate(2_000_000, 0.75)
        self.bus.set_filter(FIL_AcceptMask11bit, 0x100, 0x700)
        self.bus.set_bus_load_report(7)
        self.bus.start(loopback=True, one_shot=True, disable_echo=True)
        expected = (self.device.nominal, self.device.data, self.device.flags,
                    list(self.device.filters), self.device.interval)
        self.bus.recover()
        self.assertEqual((self.device.nominal, self.device.data, self.device.flags,
                          self.device.filters, self.device.interval), expected)
        self.bus.set_silent(True)
        self.assertTrue(self.device.running)
        self.assertEqual(self.device.flags, expected[2] | GS_DevFlagListenOnly)
        self.assertEqual(self.device.nominal, expected[0])
        self.assertEqual(self.device.data, expected[1])

    def test_stop_start_discards_old_host_and_usb_frames(self):
        self.start()
        self.bus._parser.feed(rx_message(data=b'1')[:4])
        self.bus._parser.push_pending([CANFrame(1)])
        self.device.ep_in.messages.put(rx_message(2))
        self.bus.stop()
        self.assertIsNone(self.device.nominal)
        self.bus.start()
        self.device.ep_in.messages.put(rx_message(3))
        self.assertEqual(self.bus.receive(0.1).can_id, 3)

    def test_switch_to_classic_after_stopping_fd(self):
        self.start(fd=True)
        self.bus.stop()
        self.bus.fd_mode = False
        self.bus.start()
        self.assertIsNone(self.device.data)
        self.assertFalse(self.device.flags & GS_DevFlagCAN_FD)

    def test_fd_requires_mode_and_data_timing(self):
        self.bus.set_bitrate(500_000)
        self.bus.fd_mode = True
        with self.assertRaisesRegex(RuntimeError, 'data bitrate'):
            self.bus.start()
        self.bus.fd_mode = False
        self.bus.set_data_bitrate(2_000_000)
        with self.assertRaisesRegex(RuntimeError, 'enable FD'):
            self.bus.start()

    def test_stall_is_cleared_before_recovery_without_resending(self):
        self.start(loopback=True, one_shot=True)
        self.device.ep_out.failure = usb.core.USBError('pipe', errno=32)
        with self.assertLogs('canable_sdk', level='WARNING'), self.assertRaises(usb.core.USBError):
            self.bus.send(CANFrame(1, b'1'))
        self.assertEqual(self.device.ep_out.cleared, 1)
        self.assertEqual(len(self.device.ep_out.writes), 1)
        self.assertTrue(self.device.running)
        self.assertTrue(self.device.flags & GS_DevFlagLoopback)
        self.assertTrue(self.device.flags & GS_DevFlagOneShot)
        with self.assertRaisesRegex(RuntimeError, 'recovering'):
            self.bus.send(CANFrame(1))

    def test_short_write_is_reported_and_recovers_without_retry(self):
        self.start()
        self.device.ep_out.short = True
        with self.assertLogs('canable_sdk', level='WARNING'), \
             self.assertRaisesRegex(usb.core.USBError, 'short USB write'):
            self.bus.send(CANFrame(1, b'1234'))
        self.assertEqual(len(self.device.ep_out.writes), 1)
        self.assertTrue(self.device.running)

    def test_failed_recovery_leaves_controller_unavailable(self):
        self.start()
        self.device.ep_out.failure = usb.core.USBError('pipe', errno=32)
        self.device.reject[GS_ReqSetDeviceMode] = 53
        with self.assertLogs('canable_sdk', level='WARNING'), self.assertRaises(CANableCommandError):
            self.bus.send(CANFrame(1))
        self.assertFalse(self.bus.running)

    def test_disabled_echo_does_not_consume_markers(self):
        self.start(disable_echo=True)
        for _ in range(300):
            self.bus.send(CANFrame(1, b'1'))
        self.assertFalse(self.bus._parser._tx_frames)
        self.assertTrue(all(raw[7] == 0 for raw in self.device.ep_out.writes))

    def test_receive_waits_through_non_frame_messages(self):
        self.start()
        self.device.ep_in.messages.put(bytes([3, MSG_Busload, 42]))
        self.device.ep_in.messages.put(rx_message(17))
        self.assertEqual(self.bus.receive(0.1).can_id, 17)
        self.assertEqual(self.bus._parser.bus_load, 42)

    def test_overflow_preserves_next_frame_and_tx_reservation(self):
        self.start()
        self.bus.send(CANFrame(1))
        self.bus._parser.feed(rx_message()[:5])
        called = []
        self.bus.on_overflow(lambda: called.append(True))
        self.device.ep_in.messages.put(usb.core.USBError('overflow', errno=75))
        self.device.ep_in.messages.put(rx_message(99))
        self.assertEqual(self.bus.receive(0.1).can_id, 99)
        self.assertEqual(called, [True])
        self.assertEqual(len(self.bus._parser._tx_frames), 1)

    def test_error_register_and_version(self):
        self.start()
        self.device.ep_in.messages.put(error_message(ERID_Bus_is_off))
        self.assertTrue(self.bus.receive(0.1).is_error)
        self.assertIn('BUS-OFF', self.bus.read_error_register())
        self.assertTrue(self.bus.get_version().startswith('25.10.23 '))

    def test_zero_timeout_does_not_become_infinite_usb_timeout(self):
        self.start()
        self.assertIsNone(self.bus.receive(0))
        self.assertEqual(self.device.ep_in.timeouts[-1], 1)

    def test_listener_is_singleton_and_owns_receive(self):
        self.start()
        received = threading.Event()
        self.bus.on_receive(lambda frame: received.set())
        self.bus.start_listening()
        thread = self.bus._recv_thr
        self.bus.start_listening()
        self.assertIs(thread, self.bus._recv_thr)
        with self.assertRaisesRegex(RuntimeError, 'listener'):
            self.bus.receive(0)
        self.device.ep_in.messages.put(rx_message())
        self.assertTrue(received.wait(1))
        self.bus.stop()
        self.assertFalse(thread.is_alive())

    def test_listener_requires_started_controller(self):
        with self.assertRaises(RuntimeError):
            self.bus.start_listening()
        self.assertFalse(self.bus.running)

    def test_listener_can_be_stopped_and_restarted_without_stopping_can(self):
        self.start()
        self.bus.start_listening()
        first = self.bus._recv_thr
        self.bus.stop_listening()
        self.assertFalse(first.is_alive())
        self.assertTrue(self.bus.running)
        self.bus.start_listening()
        self.assertIsNot(self.bus._recv_thr, first)
        self.assertTrue(self.bus._recv_thr.is_alive())

    def test_recover_resumes_external_listener(self):
        self.start()
        received = threading.Event()
        self.bus.on_receive(lambda frame: received.set())
        self.bus.start_listening()
        first = self.bus._recv_thr
        self.bus.recover()
        self.assertFalse(first.is_alive())
        self.assertTrue(self.bus._recv_thr.is_alive())
        self.device.ep_in.messages.put(rx_message())
        self.assertTrue(received.wait(1))

    def test_callback_recovery_does_not_deadlock_concurrent_stop(self):
        self.start()
        entered = threading.Event()
        proceed = threading.Event()
        callback_errors = []
        stop_errors = []
        def callback(frame):
            entered.set()
            if proceed.wait(1):
                try:
                    self.bus.recover()
                except RuntimeError as error:
                    callback_errors.append(str(error))
        def stop():
            try:
                self.bus.stop()
            except Exception as error:
                stop_errors.append(error)
        self.bus.on_receive(callback)
        self.bus.start_listening()
        self.device.ep_in.messages.put(rx_message())
        self.assertTrue(entered.wait(1))
        stopper = threading.Thread(target=stop)
        stopper.start()
        self.assertTrue(self.bus._listen_stop.wait(1))
        proceed.set()
        stopper.join(1)
        self.assertFalse(stopper.is_alive())
        self.assertFalse(self.bus._recv_thr.is_alive())
        self.assertEqual(stop_errors, [])
        self.assertEqual(callback_errors, ['receive listener is stopping'])

    def test_listener_recovers_and_can_close_from_callback(self):
        self.start()
        done = threading.Event()
        failures = []
        def callback(frame):
            try:
                self.bus.recover()
                self.bus.close()
            except Exception as error:
                failures.append(error)
            finally:
                done.set()
        self.bus.on_receive(callback)
        self.bus.start_listening()
        thread = self.bus._recv_thr
        self.device.ep_in.messages.put(rx_message())
        self.assertTrue(done.wait(1))
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertIsNone(self.bus.dev)

    def test_stop_interrupts_long_direct_receive(self):
        self.start()
        self.device.ep_in.reading.clear()
        received = []
        thread = threading.Thread(target=lambda: received.append(self.bus.receive(30)))
        thread.start()
        self.assertTrue(self.device.ep_in.reading.wait(1))
        self.bus.stop()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(received, [None])

    def test_custom_clock_and_limits_drive_timing(self):
        self.bus._can_clock = 80_000_000
        self.bus.set_bitrate(500_000)
        _, seg1, seg2, sjw, brp = struct.unpack('<5I', self.device.nominal)
        self.assertEqual(80_000_000 / (brp * (1 + seg1 + seg2)), 500_000)
        self.assertLessEqual(sjw, min(seg1, seg2))
        self.bus.check_fd_support()
        self.assertEqual(self.bus._data_limits.seg1_max, 32)
        self.assertEqual(self.bus._data_limits.seg2_max, 16)

    def test_open_failure_disposes_device_and_forwards_selector(self):
        self.bus.close()
        backend = object()
        bus = ZDTCanable(serial='abc', port=(2, 3), backend=backend)
        with patch('canable_sdk.driver.usb.core.find', return_value=self.device) as find, \
             patch('canable_sdk.driver.usb.util.get_string', return_value='abc'), \
             patch.object(bus, '_setup_usb', side_effect=RuntimeError('setup failed')), \
             patch('canable_sdk.driver.usb.util.dispose_resources') as dispose:
            with self.assertRaisesRegex(RuntimeError, 'setup failed'):
                bus.open()
            find.assert_called_once_with(idVendor=bus.vid, idProduct=bus.pid,
                                         bus=2, address=3, serial_number='abc', backend=backend)
            dispose.assert_called_once_with(self.device)
            self.assertIsNone(bus.dev)

    def test_feedback_is_not_cleared_by_another_threads_query(self):
        entered = threading.Event()
        proceed = threading.Event()
        attempted_query = threading.Event()
        errors = []
        original = self.device.ctrl_transfer
        self.device.reject[GS_ReqSetBitTiming] = 50
        def transfer(bm, request, value, index, data, timeout):
            result = original(bm, request, value, index, data, timeout)
            if not bm & 128 and request == GS_ReqSetBitTiming:
                entered.set()
                proceed.wait(1)
            elif bm & 128 and request != ELM_ReqGetLastError:
                self.device.feedback = 2
            return result
        def configure():
            try:
                self.bus.set_bitrate(500_000)
            except CANableCommandError as error:
                errors.append(error.feedback)
        def query():
            attempted_query.set()
            self.bus.get_version()
        with patch.object(self.device, 'ctrl_transfer', side_effect=transfer):
            config_thread = threading.Thread(target=configure)
            config_thread.start()
            self.assertTrue(entered.wait(1))
            query_thread = threading.Thread(target=query)
            query_thread.start()
            self.assertTrue(attempted_query.wait(1))
            proceed.set()
            config_thread.join(1)
            query_thread.join(1)
        self.assertFalse(config_thread.is_alive())
        self.assertFalse(query_thread.is_alive())
        self.assertEqual(errors, [50])


class FrameAndProtocolTests(unittest.TestCase):
    def test_fd_payload_is_zero_padded_for_every_length(self):
        for length in range(65):
            frame = CANFrame(0x123, b'\xAA' * length, fd=True)
            raw = frame.to_elmue_bytes(1)
            expected = CANFrame.dlc_to_len(frame.dlc)
            with self.subTest(length=length):
                self.assertEqual(len(raw), 8 + expected)
                self.assertEqual(raw[8:], b'\xAA' * length + bytes(expected - length))
                self.assertEqual(frame.to_legacy_bytes()[12:12 + expected], raw[8:])

    def test_invalid_transmissions_are_rejected(self):
        for frame in (CANFrame(1, bytes(9)), CANFrame(1, bytes(65), fd=True),
                      CANFrame(0x800), CANFrame(-1), CANFrame(0x20000000, extended=True),
                      CANFrame(1, brs=True), CANFrame(1, fd=True, rtr=True)):
            for serialize in (frame.to_elmue_bytes, frame.to_legacy_bytes):
                with self.subTest(frame=repr(frame), serialize=serialize.__name__):
                    with self.assertRaises(ValueError):
                        serialize()

    def test_passive_flags_are_never_bus_off(self):
        for byte1 in (0x10, 0x20, 0x30):
            frame = _ElmueProtocol().feed(error_message(byte1=byte1))[0]
            self.assertIn('ERROR-PASSIVE', frame._error_info)
            self.assertNotIn('BUS-OFF', frame._error_info)
        self.assertIn('BUS-OFF', _ElmueProtocol().feed(error_message(ERID_Bus_is_off))[0]._error_info)

    def test_short_messages_do_not_destroy_following_frames(self):
        for stamp in (False, True):
            parser = _ElmueProtocol()
            parser.set_timestamp_mode(stamp)
            valid = rx_message(timestamp=7 if stamp else None)
            broken = bytes([2, MSG_RxFrame, 2, MSG_TxEcho, 6, MSG_Error, 0, 0, 0, 0])
            frames = parser.feed(broken + valid)
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0].can_id, 0x123)

    def test_normal_stream_with_random_fragmentation(self):
        rng = random.Random(42)
        for stamp in (False, True):
            expected = [bytes([n]) * rng.choice((0, 1, 8, 12, 16, 32, 48, 64)) for n in range(100)]
            stream = b''.join(rx_message(n, data, True, n if stamp else None)
                              for n, data in enumerate(expected))
            for _ in range(20):
                parser = _ElmueProtocol()
                parser.set_timestamp_mode(stamp)
                actual = []
                offset = 0
                while offset < len(stream):
                    count = rng.randint(1, 256)
                    actual.extend(parser.feed(stream[offset:offset + count]))
                    offset += count
                self.assertEqual([(f.can_id, f.data) for f in actual], list(enumerate(expected)))

    def test_large_valid_input_is_parsed_instead_of_discarded(self):
        self.assertEqual(len(_ElmueProtocol().feed(rx_message() * 500)), 500)

    def test_random_invalid_stream_does_not_raise_or_grow_unbounded(self):
        rng = random.Random(7)
        parser = _ElmueProtocol()
        for _ in range(1000):
            parser.feed(bytes(rng.randrange(256) for _ in range(rng.randrange(257))))
            self.assertLess(len(parser._buffer), 128)

    def test_package_cli_entrypoint(self):
        with patch('canable_sdk.cli._cli') as cli:
            runpy.run_module('canable_sdk', run_name='__main__')
        cli.assert_called_once_with()

    def test_markers_are_not_reused_until_echo_and_snapshot_is_immutable(self):
        parser = _ElmueProtocol()
        frame = CANFrame(0, b'123456789', fd=True)
        marker = parser.reserve_tx_frame(frame)
        frame.can_id = 99
        frame.data = b'changed'
        for n in range(1, 255):
            parser.reserve_tx_frame(CANFrame(n))
        with self.assertRaises(RuntimeError):
            parser.reserve_tx_frame(CANFrame(255))
        echo = parser.feed(bytes([3, MSG_TxEcho, marker]))[0]
        self.assertEqual(echo.can_id, 0)
        self.assertEqual(echo.data, b'123456789\x00\x00\x00')
        self.assertEqual(parser.feed(bytes([3, MSG_TxEcho, marker])), [])
        self.assertEqual(parser.reserve_tx_frame(CANFrame(255)), marker)

    def test_legacy_timestamp_is_negotiated_not_inferred_from_padding(self):
        raw = struct.pack('<IIBBBB', ECHO_RxData, 123, 8, 0, 0, 0)
        raw += b'12345678' + bytes([1, 2, 3, 4]) + bytes(52)
        with patch('canable_sdk.frame.time.time', return_value=123456):
            frame = CANFrame.from_legacy_bytes(raw, has_timestamp=False, fd_mode=True)
        self.assertEqual(frame.timestamp, 123456)
        self.assertIsNone(CANFrame.from_legacy_bytes(raw[:64], has_timestamp=False, fd_mode=True))

    def test_zero_hardware_timestamp_stays_zero(self):
        parser = _ElmueProtocol()
        parser.set_timestamp_mode(True)
        self.assertEqual(parser.feed(rx_message(timestamp=0))[0].timestamp, 0)

    def test_custom_timing_and_invalid_inputs(self):
        bus = ZDTCanable()
        for bitrate in (5000, 333333, 1_000_000):
            brp, seg1, seg2, sjw = bus._calc_bitrate_params(bitrate)
            self.assertLess(abs(160_000_000 / (brp * (1 + seg1 + seg2)) - bitrate) / bitrate, 0.01)
            self.assertGreater(1 + seg1 + seg2, 3)
            self.assertLessEqual(sjw, min(seg1, seg2))
        for bitrate, sample in ((0, None), (-1, None), (500000, 0), (500000, 1),
                                (500000, float('nan')), (500000, float('inf'))):
            with self.assertRaises(ValueError):
                bus._calc_bitrate_params(bitrate, sample_point=sample)
        bus._data_limits = TimingLimits(seg1_max=32, seg2_max=16, sjw_max=16, brp_max=32)
        brp, seg1, seg2, _ = bus._calc_bitrate_params(125000, data_phase=True)
        self.assertEqual(160_000_000 / (brp * (1 + seg1 + seg2)), 125000)


if __name__ == '__main__':
    unittest.main()
