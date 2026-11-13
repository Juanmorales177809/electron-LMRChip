import os
import sys
import threading
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.errors import CommandError
from lmrchip.spectroscopy.manager import SpectrometerManager


class SpectrometerManagerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"LMRCHIP_SIMULATE_SPECTROMETER": "1"})
        self.environment.start()
        self.events = []
        self.manager = SpectrometerManager(lambda event, data: self.events.append((event, data)))

    def tearDown(self):
        self.manager.shutdown()
        self.environment.stop()

    def connect_fast(self):
        self.manager.connect("SIMULATED")
        self.manager.configure({"scans_to_average": 1, "delay": 0.0, "boxcar_width": 0})

    def test_explicit_simulator_device_and_connection(self):
        self.assertEqual(self.manager.list_devices()[0]["id"], "SIMULATED")

        state = self.manager.connect("SIMULATED")

        self.assertEqual(state["connection_state"], "connected")
        self.assertTrue(state["simulation"])

    def test_calibration_transmission_and_tracking_flow(self):
        self.connect_fast()
        self.manager.capture("background")
        self.manager.capture("reference")
        self.manager.capture("sample")
        transmission = self.manager.calculate_transmission()
        tracking_event = threading.Event()

        def receive(event, data):
            self.events.append((event, data))
            if event == "spectrometer.tracking":
                tracking_event.set()

        self.manager._event_sink = receive
        tracking = self.manager.start_tracking()
        self.assertTrue(tracking["tracking"])
        self.assertTrue(tracking_event.wait(3.0))
        stopped = self.manager.stop_tracking()

        self.assertEqual(len(transmission["wavelengths"]), 1201)
        self.assertEqual(len(transmission["values"]), 1201)
        self.assertFalse(stopped["tracking"])
        result = next(data["result"] for event, data in self.events if event == "spectrometer.tracking")
        self.assertTrue(result["valid"], result["reason"])

    def test_tracking_requires_background_and_reference(self):
        self.connect_fast()

        with self.assertRaises(CommandError) as caught:
            self.manager.start_tracking()

        self.assertEqual(caught.exception.code, "CALIBRATION_REQUIRED")

    def test_one_shot_resonance_returns_transmission_and_timestamp_without_tracking(self):
        self.connect_fast()
        self.manager.capture("background")
        self.manager.capture("reference")
        self.manager.capture("sample")

        payload = self.manager.detect_resonance_once()

        self.assertIsInstance(payload["timestamp"], float)
        self.assertEqual(len(payload["wavelengths"]), 1201)
        self.assertEqual(len(payload["values"]), 1201)
        self.assertIn("result", payload)
        self.assertTrue(payload["result"]["valid"], payload["result"]["reason"])
        self.assertFalse(self.manager.snapshot()["tracking"])
        self.assertFalse(any(event == "spectrometer.tracking" for event, _ in self.events))

    def test_one_shot_invalid_resonance_has_no_numeric_result(self):
        self.connect_fast()
        self.manager.capture("background")
        self.manager.capture("reference")
        self.manager.capture("sample")
        self.manager._optical.calculate_transmission = lambda: np.ones(1201)
        self.manager._optical.transmission_diagnostics = {}

        payload = self.manager.detect_resonance_once()

        self.assertFalse(payload["result"]["valid"])
        self.assertIsNone(payload["result"]["wavelength"])
        self.assertIsNone(payload["result"]["transmission"])
        self.assertTrue(payload["result"]["reason"])

    def test_one_shot_requires_calibration(self):
        self.connect_fast()
        with self.assertRaises(CommandError) as caught:
            self.manager.detect_resonance_once()
        self.assertEqual(caught.exception.code, "CALIBRATION_REQUIRED")

    def test_invalid_configuration_does_not_replace_previous_settings(self):
        self.connect_fast()
        previous = self.manager.snapshot()["settings"]

        with self.assertRaises(CommandError) as caught:
            self.manager.configure({"scans_to_average": 0})

        self.assertEqual(caught.exception.code, "INVALID_CONFIGURATION")
        self.assertEqual(self.manager.snapshot()["settings"], previous)


if __name__ == "__main__":
    unittest.main()
