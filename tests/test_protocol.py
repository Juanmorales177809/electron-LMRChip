import json
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.protocol import ProtocolError, encode_message, event_message, parse_request


class ProtocolTests(unittest.TestCase):
    def test_valid_request(self):
        request = parse_request(
            '{"version":1,"id":"req-1","command":"system.ping","payload":{}}'
        )

        self.assertEqual(request.request_id, "req-1")
        self.assertEqual(request.command, "system.ping")
        self.assertEqual(request.payload, {})

    def test_invalid_json_has_stable_error_code(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_request("not-json")

        self.assertEqual(caught.exception.code, "INVALID_JSON")
        self.assertIsNone(caught.exception.request_id)

    def test_unsupported_version_preserves_request_id(self):
        with self.assertRaises(ProtocolError) as caught:
            parse_request(
                '{"version":2,"id":"req-2","command":"system.ping","payload":{}}'
            )

        self.assertEqual(caught.exception.code, "UNSUPPORTED_VERSION")
        self.assertEqual(caught.exception.request_id, "req-2")

    def test_required_fields_are_validated(self):
        invalid_messages = (
            {},
            {"version": True, "id": "x", "command": "system.ping", "payload": {}},
            {"version": 1, "id": "", "command": "system.ping", "payload": {}},
            {"version": 1, "id": "x", "command": "", "payload": {}},
            {"version": 1, "id": "x", "command": "system.ping", "payload": []},
        )

        for message in invalid_messages:
            with self.subTest(message=message), self.assertRaises(ProtocolError) as caught:
                parse_request(json.dumps(message))
            self.assertEqual(caught.exception.code, "INVALID_MESSAGE")

    def test_encoder_produces_one_compact_json_value(self):
        encoded = encode_message({"message": "temperatura á", "ok": True})

        self.assertNotIn("\n", encoded)
        self.assertEqual(json.loads(encoded), {"message": "temperatura á", "ok": True})

    def test_event_has_no_request_id(self):
        event = event_message("temperature.sample", {"block_temp": 36.8})

        self.assertEqual(event["type"], "event")
        self.assertEqual(event["event"], "temperature.sample")
        self.assertNotIn("id", event)


if __name__ == "__main__":
    unittest.main()
