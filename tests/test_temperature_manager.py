import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.errors import CommandError
from lmrchip.service import LMRChipService
from lmrchip.temperature.manager import TemperatureManager


class TemperatureManagerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"LMRCHIP_SIMULATE_TEMPERATURE": "1"})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()

    def test_simulator_is_explicit_and_lists_only_simulated_port(self):
        manager = TemperatureManager()

        self.assertTrue(manager.simulation_enabled)
        self.assertEqual(manager.list_ports(), ["SIMULATED"])

    def test_connect_stream_control_and_disconnect_lifecycle(self):
        received_sample = threading.Event()
        events = []

        def receive(event, data):
            events.append((event, data))
            if event == "temperature.sample":
                received_sample.set()

        manager = TemperatureManager(receive)
        connected = manager.connect("SIMULATED")
        try:
            self.assertEqual(connected["connection_state"], "connected")
            self.assertTrue(received_sample.wait(2.0))
            running = manager.start_control(37.0)
            self.assertEqual(running["control_state"], "running")
            stopped = manager.stop_control()
            self.assertEqual(stopped["control_state"], "stopped")
        finally:
            disconnected = manager.disconnect()

        self.assertEqual(disconnected["connection_state"], "disconnected")
        self.assertTrue(any(event == "temperature.monitoring" for event, _ in events))

    def test_invalid_operations_have_domain_error_codes(self):
        manager = TemperatureManager()

        with self.assertRaises(CommandError) as not_connected:
            manager.start_control(37.0)
        self.assertEqual(not_connected.exception.code, "NOT_CONNECTED")

        manager.connect("SIMULATED")
        try:
            with self.assertRaises(CommandError) as invalid:
                manager.start_control(81.0)
            self.assertEqual(invalid.exception.code, "INVALID_SETPOINT")
            with self.assertRaises(CommandError) as duplicate:
                manager.connect("SIMULATED")
            self.assertEqual(duplicate.exception.code, "ALREADY_CONNECTED")
        finally:
            manager.disconnect()

    def test_service_exposes_temperature_commands_and_events(self):
        events = []
        service = LMRChipService(lambda event, data: events.append((event, data)))

        ports = service.handle_line(
            '{"version":1,"id":"1","command":"temperature.list_ports","payload":{}}'
        )
        connected = service.handle_line(
            '{"version":1,"id":"2","command":"temperature.connect","payload":{"port":"SIMULATED"}}'
        )
        try:
            status = service.handle_line(
                '{"version":1,"id":"3","command":"temperature.status","payload":{}}'
            )
        finally:
            service.close()

        self.assertEqual(ports["data"]["ports"], ["SIMULATED"])
        self.assertTrue(connected["ok"])
        self.assertEqual(status["data"]["connection_state"], "connected")
        self.assertTrue(any(event == "temperature.state" for event, _ in events))


if __name__ == "__main__":
    unittest.main()
