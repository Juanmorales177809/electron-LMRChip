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


class ProtocolServiceTests(unittest.TestCase):
    def test_protocol_commands_round_trip_over_jsonl_handler(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LMRCHIP_PROTOCOL_DIR": directory}):
            service = LMRChipService()
            try:
                created = service.handle_line(request("new", "protocol.new", {"name": "Integration protocol"}))
                protocol = created["data"]
                protocol["samples"] = [{"id": "s1", "name": "Sample", "concentration": "", "notes": ""}]
                protocol["positions"][0] = {"sample_id": "s1", "color": "teal"}
                protocol["steps"][0] = {"sample_id": "s1", "flow_rate": 5, "duration_seconds": 10}
                saved = service.handle_line(request("save", "protocol.save", {"protocol": protocol}))
                loaded = service.handle_line(request("load", "protocol.load", {"protocol_id": protocol["id"]}))
                validated = service.handle_line(request("validate", "protocol.validate", {"protocol": loaded["data"]}))
                listed = service.handle_line(request("list", "protocol.list"))
                self.assertTrue(saved["ok"])
                self.assertTrue(validated["ok"])
                self.assertEqual(loaded["data"], saved["data"])
                self.assertEqual(listed["data"]["protocols"][0]["id"], protocol["id"])
            finally:
                service.close()

    def test_saved_protocol_survives_service_restart(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"LMRCHIP_PROTOCOL_DIR": directory}):
            first = LMRChipService()
            try:
                protocol = first.handle_line(request("new", "protocol.new", {"name": "Restart protocol"}))["data"]
                saved = first.handle_line(request("save", "protocol.save", {"protocol": protocol}))
                self.assertTrue(saved["ok"])
            finally:
                first.close()

            second = LMRChipService()
            try:
                loaded = second.handle_line(request("load", "protocol.load", {"protocol_id": protocol["id"]}))
                self.assertTrue(loaded["ok"])
                self.assertEqual(loaded["data"]["name"], "Restart protocol")
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
