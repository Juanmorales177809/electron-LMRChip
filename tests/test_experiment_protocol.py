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


class ExperimentProtocolTests(unittest.TestCase):
    def test_protocol_start_is_rejected_explicitly_when_flow_control_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LMRCHIP_PROTOCOL_DIR": directory}):
            service = LMRChipService()
            try:
                protocol = service.handle_line(request("new", "protocol.new"))["data"]
                protocol["samples"] = [{"id": "s1", "name": "Sample", "concentration": "", "notes": ""}]
                protocol["positions"][0] = {"sample_id": "s1", "color": "teal"}
                protocol["steps"][0] = {"sample_id": "s1", "flow_rate": 7, "duration_seconds": 60}
                response = service.handle_line(request("start", "experiment.start", {"protocol": protocol, "results_root": directory}))
                self.assertFalse(response["ok"])
                self.assertEqual(response["error"]["code"], "FLOW_CONTROL_UNAVAILABLE")
            finally:
                service.close()

    def test_legacy_experiment_snapshot_exposes_protocol_fields_without_changing_old_config(self):
        with tempfile.TemporaryDirectory() as directory:
            service = LMRChipService()
            try:
                snapshot = service.experiment.snapshot()
                self.assertIsNone(snapshot["protocol_id"])
                self.assertEqual(snapshot["completed_steps"], [])
                self.assertEqual(snapshot["progress_percent"], 0)
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
