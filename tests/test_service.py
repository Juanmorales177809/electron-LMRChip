import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.service import LMRChipService, run_service


def request(request_id, command, payload=None, version=1):
    return json.dumps(
        {
            "version": version,
            "id": request_id,
            "command": command,
            "payload": {} if payload is None else payload,
        }
    )


class ServiceTests(unittest.TestCase):
    def test_ping_status_and_shutdown(self):
        service = LMRChipService()

        ping = service.handle_line(request("1", "system.ping"))
        status = service.handle_line(request("2", "system.status"))
        shutdown = service.handle_line(request("3", "system.shutdown"))

        self.assertEqual(ping["data"], {"status": "ok"})
        self.assertEqual(status["data"]["state"], "running")
        self.assertEqual(status["data"]["protocol_version"], 1)
        self.assertEqual(shutdown["data"], {"status": "shutdown-accepted"})
        self.assertTrue(service.shutting_down)

    def test_invalid_message_does_not_stop_service(self):
        input_stream = io.StringIO("invalid\n" + request("2", "system.ping") + "\n")
        output_stream = io.StringIO()

        exit_code = run_service(input_stream, output_stream)
        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]

        self.assertEqual(exit_code, 0)
        self.assertEqual(responses[0]["error"]["code"], "INVALID_JSON")
        self.assertTrue(responses[1]["ok"])

    def test_unknown_command_is_recoverable(self):
        service = LMRChipService()

        unknown = service.handle_line(request("1", "missing.command"))
        ping = service.handle_line(request("2", "system.ping"))

        self.assertEqual(unknown["error"]["code"], "UNKNOWN_COMMAND")
        self.assertTrue(ping["ok"])

    def test_commands_are_rejected_after_shutdown_is_accepted(self):
        service = LMRChipService()
        service.handle_line(request("1", "system.shutdown"))

        response = service.handle_line(request("2", "system.ping"))

        self.assertEqual(response["error"]["code"], "SHUTTING_DOWN")

    def test_end_of_input_is_a_clean_shutdown(self):
        output_stream = io.StringIO()

        exit_code = run_service(io.StringIO(""), output_stream)

        self.assertEqual(exit_code, 0)
        self.assertEqual(output_stream.getvalue(), "")

    def test_unexpected_handler_failure_is_recoverable(self):
        service = LMRChipService()

        def fail(payload):
            raise RuntimeError("private diagnostic")

        service._commands["test.fail"] = fail
        failed = service.handle_line(request("1", "test.fail"))
        ping = service.handle_line(request("2", "system.ping"))

        self.assertEqual(failed["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("private diagnostic", failed["error"]["message"])
        self.assertTrue(ping["ok"])

    def test_real_process_uses_stdout_only_for_json_and_exits_cleanly(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(PACKAGE_ROOT)
        process = subprocess.Popen(
            [sys.executable, "-m", "lmrchip.service"],
            cwd=PROJECT_ROOT,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

        stdout, stderr = process.communicate(
            request("1", "system.ping")
            + "\n"
            + request("2", "system.status")
            + "\n"
            + request("3", "system.shutdown")
            + "\n",
            timeout=5,
        )
        messages = [json.loads(line) for line in stdout.splitlines()]

        self.assertEqual(process.returncode, 0)
        self.assertEqual([message["id"] for message in messages], ["1", "2", "3"])
        self.assertTrue(all(message["type"] == "response" for message in messages))
        self.assertIn("service started", stderr)
        self.assertIn("service stopped", stderr)


if __name__ == "__main__":
    unittest.main()
