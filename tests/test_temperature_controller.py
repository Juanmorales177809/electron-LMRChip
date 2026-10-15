import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

try:
    import serial  # noqa: F401
except ModuleNotFoundError:
    fake_serial = ModuleType("serial")
    fake_serial.Serial = object
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

from lmrchip.temperature.controller import PR59Controller


class ScriptedController(PR59Controller):
    def __init__(self, responses=None):
        super().__init__()
        self.responses = responses or {}
        self.commands = []
        self.stream_events = []
        self.ser = SimpleNamespace(is_open=True, close=lambda: None)

    def send_command(self, command, timeout=None):
        self.commands.append((command, timeout))
        response = self.responses.get(command, "OK")
        if isinstance(response, Exception):
            raise response
        return response

    def start_stream(self):
        self.stream_events.append("start")
        self.streaming = True

    def stop_stream(self):
        self.stream_events.append("stop")
        self.streaming = False


class TemperatureControllerTests(unittest.TestCase):
    def test_start_preserves_all_register_values_and_order(self):
        controller = ScriptedController({"$W": "RUN"})

        controller.start_control(37.0)

        expected_settings = ((0, 37.0), *controller.FIXED_SETTINGS)
        expected_commands = [
            (f"$R{register}={value:.9g}", 3.0)
            for register, value in expected_settings
        ]
        expected_commands.append(("$W", 3.0))
        self.assertEqual(controller.commands, expected_commands)
        self.assertEqual(controller.stream_events, ["start"])
        self.assertTrue(controller.running)
        self.assertEqual(controller.control_state, "running")

    def test_failed_write_stops_control_and_restores_previous_stream(self):
        controller = ScriptedController({"$R2=0.2": "", "$Q": "STOP"})
        controller.streaming = True

        with self.assertRaisesRegex(RuntimeError, "Empty response while writing R2"):
            controller.start_control(37.0)

        self.assertEqual(controller.stream_events, ["stop", "start"])
        self.assertEqual(controller.commands[-1], ("$Q", 3.0))
        self.assertFalse(controller.running)
        self.assertEqual(controller.control_state, "stopped")
        self.assertTrue(controller.streaming)

    def test_failed_write_does_not_start_stream_when_it_was_previously_off(self):
        controller = ScriptedController({"$R1=8": "error", "$Q": "STOP"})

        with self.assertRaisesRegex(RuntimeError, "Failed to write R1"):
            controller.start_control(37.0)

        self.assertEqual(controller.stream_events, [])
        self.assertFalse(controller.streaming)
        self.assertEqual(controller.control_state, "stopped")

    def test_failed_recovery_marks_control_state_unknown_and_reports_both_errors(self):
        controller = ScriptedController(
            {"$R1=8": "", "$Q": TimeoutError("controller silent")}
        )

        with self.assertRaisesRegex(
            RuntimeError, "Empty response.*could not confirm stop.*controller silent"
        ):
            controller.start_control(37.0)

        self.assertTrue(controller.running)
        self.assertEqual(controller.control_state, "unknown")
        self.assertFalse(controller.streaming)

    def test_lost_communication_while_stopping_marks_state_unknown(self):
        controller = ScriptedController({"$Q": TimeoutError("controller silent")})
        controller.running = True
        controller.control_state = "running"
        controller.streaming = True

        with self.assertRaisesRegex(TimeoutError, "controller silent"):
            controller.stop_control()

        self.assertEqual(controller.stream_events, ["stop"])
        self.assertTrue(controller.running)
        self.assertEqual(controller.control_state, "unknown")

    def test_empty_register_response_is_never_accepted(self):
        with self.assertRaisesRegex(RuntimeError, "Empty response"):
            PR59Controller._require_successful_register_write(3, 14.0, "  ")

    def test_setpoint_limits_are_preserved(self):
        controller = PR59Controller()

        controller._validate_setpoint(10.0)
        controller._validate_setpoint(80.0)
        for invalid in (9.99, 80.01, float("nan"), float("inf")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                controller._validate_setpoint(invalid)

    def test_a3_parsing_mapping_is_preserved(self):
        sample = PR59Controller._parse_a3_sample(
            "[3 0 6 25.5 36.8 -999.9 37.0 36.8 1.0 2.0 3.0 4.0 5.0]"
        )

        self.assertEqual(sample["output"], 25.5)
        self.assertEqual(sample["temp_sensor_1"], 36.8)
        self.assertIsNone(sample["temp_sensor_2"])
        self.assertEqual(sample["setpoint"], 37.0)
        self.assertEqual(sample["active_temp"], 36.8)


if __name__ == "__main__":
    unittest.main()
