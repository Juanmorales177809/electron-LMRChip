import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.service import LMRChipService


def request(request_id, command, payload=None):
    return json.dumps({"version": 1, "id": request_id, "command": command, "payload": payload or {}})


class SpectrometerServiceTests(unittest.TestCase):
    def test_detect_resonance_jsonl_command(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LMRCHIP_SIMULATE_SPECTROMETER": "1"}):
            service = LMRChipService()
            try:
                service.handle_line(request("connect", "spectrometer.connect", {"device_id": "SIMULATED"}))
                service.handle_line(request("background", "spectrometer.capture_background"))
                service.handle_line(request("reference", "spectrometer.capture_reference"))
                service.handle_line(request("sample", "spectrometer.capture_sample"))
                response = service.handle_line(request("detect", "spectrometer.detect_resonance"))
                self.assertTrue(response["ok"])
                self.assertIn("timestamp", response["data"])
                self.assertIn("result", response["data"])
                self.assertFalse(response["data"].get("tracking", False))
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
