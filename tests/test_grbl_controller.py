import sys
import unittest
from pathlib import Path
from types import ModuleType


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

try:
    import serial  # noqa: F401
except ModuleNotFoundError:
    fake_serial = ModuleType("serial")
    fake_serial.Serial = None
    fake_serial.EIGHTBITS = 8
    fake_serial.STOPBITS_ONE = 1
    fake_serial.PARITY_NONE = "N"
    fake_tools = ModuleType("serial.tools")
    fake_list_ports = ModuleType("serial.tools.list_ports")
    fake_list_ports.comports = lambda: []
    fake_tools.list_ports = fake_list_ports
    fake_serial.tools = fake_tools
    sys.modules["serial"] = fake_serial
    sys.modules["serial.tools"] = fake_tools
    sys.modules["serial.tools.list_ports"] = fake_list_ports

from lmrchip.microfluidics.controller import GrblController


class FakeSerial:
    def __init__(self, responses=()):
        self.is_open = True
        self.responses = iter(responses)
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def readline(self):
        return next(self.responses, b"")


class GrblControllerTests(unittest.TestCase):
    def controller_with(self, responses):
        controller = GrblController(command_timeout=0.01)
        controller.serial_connection = FakeSerial(responses)
        return controller

    def test_command_keeps_existing_wire_format_and_returns_all_lines(self):
        controller = self.controller_with([b"[MSG:Ready]\r\n", b"ok\r\n"])

        result = controller.send_command("$X")

        self.assertEqual(controller.serial_connection.writes, [b"$X\n"])
        self.assertEqual(result, ["[MSG:Ready]", "ok"])

    def test_error_response_is_reported_without_retry(self):
        controller = self.controller_with([b"error:9\r\n"])

        with self.assertRaisesRegex(RuntimeError, "error:9"):
            controller.send_command("$H")

        self.assertEqual(controller.serial_connection.writes, [b"$H\n"])

    def test_alarm_response_is_reported_without_retry(self):
        controller = self.controller_with([b"ALARM:1\r\n"])

        with self.assertRaisesRegex(RuntimeError, "ALARM:1"):
            controller.send_command("$H")

        self.assertEqual(controller.serial_connection.writes, [b"$H\n"])

    def test_silent_device_times_out_without_retry_or_reset(self):
        controller = self.controller_with([])

        with self.assertRaisesRegex(TimeoutError, "no confirmo"):
            controller.send_command("G0X1")

        self.assertEqual(controller.serial_connection.writes, [b"G0X1\n"])

    def test_default_command_timeout_is_five_seconds(self):
        self.assertEqual(GrblController().command_timeout, 5.0)

    def test_motion_commands_preserve_distances_and_feed_rates(self):
        controller = self.controller_with([b"ok\n", b"ok\n", b"ok\n", b"ok\n"])

        controller.move_x(4.0)
        controller.move_y(-37.0)
        controller.move_z(2.0)
        controller.move_a(-3.0)

        self.assertEqual(
            controller.serial_connection.writes,
            [
                b"$J=G21G91X4.0F2000\n",
                b"$J=G21G91Y-37.0F800\n",
                b"$J=G21G91Z2.0F800\n",
                b"$J=G21G91A-3.0F800\n",
            ],
        )


if __name__ == "__main__":
    unittest.main()
