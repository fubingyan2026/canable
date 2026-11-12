"""§3.1 报文的已知向量、边界和保留字段验证（无需 CAN 硬件）。"""
import unittest

from plugins.juxie_motor.protocol import (
    build_single_control, build_single_control_units, build_mit_single_control,
)


class SingleControlTests(unittest.TestCase):
    def test_confirmed_ce_torque_frames(self):
        for target, payload in ((1.0, "CE 00 0A 00 00 00 00"),
                                (1.5, "CE 00 0F 00 00 00 00"),
                                (-1.0, "CE FF F6 00 00 00 00")):
            for fd in (False, True):
                with self.subTest(target=target, fd=fd):
                    frame = build_single_control_units(1, True, True, False,
                                                       7, target, fd=fd)
                    self.assertEqual(frame.data, bytes.fromhex(payload))
                    self.assertEqual(frame.can_id, 0x101)
                    self.assertEqual(frame.dlc, 7)

    def test_mit_keeps_its_own_mode_code(self):
        data = build_mit_single_control(1, True, True, False, 0, 0, 0, 0, 0)
        self.assertEqual(len(data), 9)
        self.assertEqual(data[0], 0xCC)

    def test_section_3_2_physical_unit_examples(self):
        cases = [
            (1, 0, 2000, 5, "C2 00 00 07 D0 00 05"),
            (1, 90, 1000, 8, "C2 40 00 03 E8 00 08"),
            (1, -90, 1000, 8, "C2 C0 00 03 E8 00 08"),
            (2, 500, 1000, 0, "C4 01 F4 03 E8 00 00"),
            (5, 1000, 0, 0, "CA 03 E8 00 00 00 00"),
            (7, 20, 0, 0, "CE 00 C8 00 00 00 00"),
        ]
        for mode, target, accel, velocity, expected in cases:
            with self.subTest(mode=mode, target=target):
                frame = build_single_control_units(7, True, True, False, mode,
                                                   target, accel, velocity)
                self.assertEqual(frame.can_id, 0x107)
                self.assertEqual(frame.data, bytes.fromhex(expected))

    def test_physical_unit_boundaries_and_negative_torque(self):
        for mode, target, expected in ((1, -180, "80 00"), (1, 180, "7F FF"),
                                       (3, 90, "40 00"), (4, -500, "FE 0C"),
                                       (7, -20, "FF 38"), (7, 0.1, "00 01"),
                                       (7, -3276.8, "80 00"), (7, 3276.7, "7F FF")):
            with self.subTest(mode=mode, target=target):
                frame = build_single_control_units(7, True, True, False, mode, target)
                self.assertEqual(frame.data[1:3], bytes.fromhex(expected))

    def test_invalid_physical_targets_rejected(self):
        for mode, target in ((1, 180.01), (3, -180.01), (7, 3276.8),
                             (7, -3276.9), (2, 32768), (5, -32769),
                             (1, float('nan')), (7, float('inf')), (6, 0)):
            with self.subTest(mode=mode, target=target), self.assertRaises(ValueError):
                build_single_control_units(7, True, True, False, mode, target)

    def test_profile_position_wire_vector(self):
        frame = build_single_control(2, True, True, True, 1, -32768,
                                     20000, 3000)
        self.assertEqual(frame.can_id, 0x102)
        self.assertEqual(frame.data, bytes.fromhex("E2 80 00 4E 20 0B B8"))
        self.assertEqual(frame.dlc, 7)
        self.assertFalse(frame.extended)
        self.assertFalse(frame.fd)
        self.assertFalse(frame.brs)

    def test_modes_and_reserved_fields(self):
        for mode in (1, 2, 3, 4, 5, 7):
            with self.subTest(mode=mode):
                frame = build_single_control(255, False, False, False,
                                             mode, -1, 123, 456, fd=True)
                self.assertEqual(frame.can_id, 0x1FF)
                self.assertEqual(frame.data[:3], bytes([mode << 1, 255, 255]))
                self.assertEqual(frame.data[3:5], b"\x00{" if mode in (1, 2)
                                 else b"\x00\x00")
                self.assertEqual(frame.data[5:], b"\x01\xc8" if mode == 1
                                 else b"\x00\x00")
                self.assertEqual(frame.dlc, 7)
                self.assertTrue(frame.fd and frame.brs)

    def test_signed_targets(self):
        for target, expected in ((-32768, b"\x80\x00"), (-1, b"\xff\xff"),
                                 (0, b"\x00\x00"), (32767, b"\x7f\xff")):
            frame = build_single_control(1, False, False, False, 5, target)
            self.assertEqual(frame.data[1:3], expected)

    def test_profile_velocity_unsigned_boundary(self):
        frame = build_single_control(1, False, False, False, 1, 0, 0, 65535)
        self.assertEqual(frame.data[5:], b"\xff\xff")

    def test_control_bits_are_independent(self):
        for enable in (False, True):
            for brake in (False, True):
                for clear in (False, True):
                    frame = build_single_control(1, enable, brake, clear, 7, 0)
                    self.assertEqual(frame.data[0], (enable << 7) | (brake << 6)
                                     | (clear << 5) | 0x0E)

    def test_invalid_ranges_rejected(self):
        for index, value in ((0, -1), (0, 256), (4, 0), (4, 6), (4, 8),
                             (5, -32769), (5, 32768), (6, -1), (6, 20001),
                             (7, -1), (7, 65536)):
            args = [1, False, False, False, 1, 0, 0, 0]
            args[index] = value
            with self.subTest(index=index, value=value), self.assertRaises(ValueError):
                build_single_control(*args)


if __name__ == "__main__":
    unittest.main()
