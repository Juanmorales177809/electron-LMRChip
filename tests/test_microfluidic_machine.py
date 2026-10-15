import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

try:
    import serial  # noqa: F401
except ModuleNotFoundError:
    from types import SimpleNamespace

    sys.modules["serial"] = SimpleNamespace(Serial=None)

from lmrchip.microfluidics.machine import MicrofluidicMachine


class RecordingGrbl:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args):
            self.calls.append((name, *args))

        return record


class MicrofluidicMachineTests(unittest.TestCase):
    def setUp(self):
        self.grbl = RecordingGrbl()
        self.machine = MicrofluidicMachine(self.grbl)

    def test_calibration_preserves_command_sequence(self):
        self.machine.calibrate()

        self.assertEqual(
            self.grbl.calls,
            [
                ("unlock",),
                ("home",),
                ("wait_until_idle",),
                ("move_x", 4.0),
                ("wait_until_idle",),
            ],
        )
        self.assertTrue(self.machine.is_calibrated)
        self.assertEqual(self.machine.current_tube, 1)

    @patch("lmrchip.microfluidics.machine.time.sleep")
    def test_tube_change_preserves_distance_and_needle_sequence(self, sleep):
        self.machine.is_calibrated = True
        self.machine.current_tube = 1

        self.machine.run_tube(3)

        self.assertEqual(
            self.grbl.calls,
            [
                ("move_x", -60.0),
                ("wait_until_idle",),
                ("move_y", -37.0),
                ("wait_until_idle",),
            ],
        )
        sleep.assert_called_once_with(1.0)
        self.assertEqual(self.machine.current_tube, 3)
        self.assertTrue(self.machine.needle_is_lowered)

    @patch("lmrchip.microfluidics.machine.time.sleep")
    def test_carousel_never_rotates_before_raising_lowered_needle(self, sleep):
        self.machine.is_calibrated = True
        self.machine.current_tube = 3
        self.machine.needle_is_lowered = True

        self.machine.run_tube(2)

        self.assertEqual(
            self.grbl.calls,
            [
                ("move_y", 37.0),
                ("wait_until_idle",),
                ("move_x", 30.0),
                ("wait_until_idle",),
                ("move_y", -37.0),
                ("wait_until_idle",),
            ],
        )
        sleep.assert_called_once_with(1.0)


if __name__ == "__main__":
    unittest.main()
