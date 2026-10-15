import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.errors import CommandError
from lmrchip.service import LMRChipService


def request(request_id, command, payload=None):
    return json.dumps({"version": 1, "id": request_id, "command": command, "payload": payload or {}})


class ExperimentManagerTests(unittest.TestCase):
    def setUp(self):
        self.previous = {name: os.environ.get(name) for name in (
            "LMRCHIP_SIMULATE_TEMPERATURE", "LMRCHIP_SIMULATE_SPECTROMETER", "LMRCHIP_SIMULATE_MICROFLUIDICS"
        )}
        for name in self.previous:
            os.environ[name] = "1"
        self.events = []
        self.service = LMRChipService(lambda event, data: self.events.append((event, data)))
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.service.close()
        self.tempdir.cleanup()
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def prepare_modules(self):
        self.service.temperature.connect("SIMULATED")
        self.service.temperature.start_control(37.0)
        self.service.spectrometer.connect("SIMULATED")
        self.service.spectrometer.configure({"scans_to_average": 1, "delay": 0, "boxcar_width": 0, "tracking_interval_ms": 20})
        self.service.spectrometer.capture("background")
        self.service.spectrometer.capture("reference")
        self.service.microfluidics.connect("SIMULATED")
        self.service.microfluidics.calibrate()
        self.wait_until(lambda: not self.service.microfluidics.snapshot()["busy"])

    def test_requires_all_three_ready_modules(self):
        with self.assertRaises(CommandError) as raised:
            self.service.experiment.validate({"results_root": self.tempdir.name})
        self.assertEqual(raised.exception.code, "PREREQUISITES_NOT_MET")

    def test_complete_simulated_experiment_persists_results(self):
        self.prepare_modules()
        started = self.service.experiment.start({
            "results_root": self.tempdir.name,
            "tubes": [2, 1],
            "setpoint": 37,
            "temperature_tolerance": 1,
            "stable_seconds": 0.1,
            "stabilization_timeout_seconds": 3,
            "tracking_seconds": 0.15,
        })
        self.wait_until(lambda: self.service.experiment.snapshot()["state"] in {"completed", "failed"}, timeout=8)
        result = self.service.experiment.snapshot()
        result_dir = Path(started["result_directory"])

        self.assertEqual(result["state"], "completed", result.get("error"))
        self.assertEqual(result["completed_tubes"], [2, 1])
        self.assertEqual(self.service.microfluidics.snapshot()["needle_state"], "raised")
        self.assertEqual(self.service.temperature.snapshot()["control_state"], "running")
        self.assertTrue((result_dir / "metadata.json").is_file())
        self.assertTrue((result_dir / "temperature.csv").stat().st_size > 80)
        self.assertTrue((result_dir / "resonance.csv").stat().st_size > 100)
        self.assertTrue(any((result_dir / "spectra").glob("tube_02_*.npz")))
        metadata = json.loads((result_dir / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "completed")

    def test_pause_reaches_safe_state_and_resume_restarts_tube(self):
        self.prepare_modules()
        self.service.experiment.start({
            "results_root": self.tempdir.name, "tubes": [3], "setpoint": 37,
            "temperature_tolerance": 1, "stable_seconds": 0.1,
            "stabilization_timeout_seconds": 3, "tracking_seconds": 1,
        })
        self.wait_until(lambda: self.service.experiment.snapshot()["phase"] == "tracking", timeout=5)
        self.service.experiment.pause()
        self.wait_until(lambda: self.service.experiment.snapshot()["state"] == "paused", timeout=5)
        self.assertEqual(self.service.microfluidics.snapshot()["needle_state"], "raised")
        self.assertFalse(self.service.spectrometer.snapshot()["tracking"])
        self.assertEqual(self.service.temperature.snapshot()["control_state"], "running")
        self.service.experiment.resume()
        self.wait_until(lambda: self.service.experiment.snapshot()["state"] == "completed", timeout=8)
        self.assertEqual(self.service.experiment.snapshot()["completed_tubes"], [3])

    def test_manual_module_commands_are_blocked_during_experiment(self):
        self.prepare_modules()
        self.service.experiment.start({
            "results_root": self.tempdir.name, "tubes": [1], "setpoint": 37,
            "temperature_tolerance": 1, "stable_seconds": 0.1,
            "stabilization_timeout_seconds": 3, "tracking_seconds": 2,
        })
        blocked = self.service.handle_line(request("1", "microfluidics.disconnect"))
        status = self.service.handle_line(request("2", "microfluidics.status"))
        self.assertEqual(blocked["error"]["code"], "EXPERIMENT_ACTIVE")
        self.assertTrue(status["ok"])
        self.service.experiment.cancel()
        self.wait_until(lambda: self.service.experiment.snapshot()["state"] == "cancelled", timeout=5)

    @staticmethod
    def wait_until(predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        raise AssertionError("Timed out waiting for condition")


if __name__ == "__main__":
    unittest.main()
