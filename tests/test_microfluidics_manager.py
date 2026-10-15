import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path: sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.errors import CommandError
from lmrchip.microfluidics.manager import MicrofluidicsManager


class MicrofluidicsManagerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"LMRCHIP_SIMULATE_MICROFLUIDICS": "1"})
        self.environment.start()
        self.events = []
        self.manager = MicrofluidicsManager(lambda event, data: self.events.append((event, data)))

    def tearDown(self):
        self.manager.shutdown()
        self.environment.stop()

    def wait_idle(self):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = self.manager.snapshot()
            if not state["busy"]: return state
            time.sleep(0.01)
        self.fail("Simulated operation did not finish.")

    def test_calibration_tube_and_needle_lifecycle(self):
        self.assertEqual(self.manager.list_ports(), ["SIMULATED"])
        self.manager.connect("SIMULATED")
        self.manager.calibrate()
        calibrated = self.wait_idle()
        self.assertTrue(calibrated["calibrated"])
        self.assertEqual(calibrated["current_tube"], 1)
        self.assertEqual(calibrated["needle_state"], "raised")

        self.manager.select_tube(3)
        selected = self.wait_idle()
        self.assertEqual(selected["current_tube"], 3)
        self.assertEqual(selected["needle_state"], "lowered")

        self.manager.raise_needle()
        raised = self.wait_idle()
        self.assertEqual(raised["needle_state"], "raised")

    def test_busy_and_invalid_tube_are_rejected(self):
        self.manager.connect("SIMULATED")
        self.manager.calibrate()
        with self.assertRaises(CommandError) as busy:
            self.manager.calibrate()
        self.assertEqual(busy.exception.code, "BUSY")
        self.wait_idle()
        with self.assertRaises(CommandError) as invalid:
            self.manager.select_tube(13)
        self.assertEqual(invalid.exception.code, "INVALID_TUBE")

    def test_disconnect_is_rejected_during_motion(self):
        self.manager.connect("SIMULATED")
        self.manager.calibrate()
        with self.assertRaises(CommandError) as caught:
            self.manager.disconnect()
        self.assertEqual(caught.exception.code, "BUSY")


if __name__ == "__main__": unittest.main()
