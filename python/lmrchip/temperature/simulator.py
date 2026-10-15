"""Explicit temperature-controller simulator for development without hardware."""

from __future__ import annotations

import math
import time


class SimulatedPR59Controller:
    def __init__(self) -> None:
        self.connected = False
        self.running = False
        self.streaming = False
        self.control_state = "stopped"
        self.setpoint = 37.0
        self.started_at = time.monotonic()

    def connect(self, port: str, timeout: float = 5.0) -> str:
        if port != "SIMULATED":
            raise RuntimeError("Simulated controller only accepts the SIMULATED port.")
        self.connected = True
        return "PR-59 SIMULATOR 1.0"

    def disconnect(self) -> None:
        self.running = False
        self.streaming = False
        self.control_state = "stopped"
        self.connected = False

    def start_stream(self) -> None:
        self._require_connected()
        self.streaming = True

    def start_control(self, setpoint: float) -> None:
        self._require_connected()
        self.setpoint = setpoint
        self.running = True
        self.streaming = True
        self.control_state = "running"

    def stop_control(self) -> None:
        self._require_connected()
        self.running = False
        self.streaming = False
        self.control_state = "stopped"

    def read_sample(self) -> dict:
        self._require_connected()
        elapsed = time.monotonic() - self.started_at
        target = self.setpoint if self.running else 24.0
        block_temp = target + 0.18 * math.sin(elapsed / 3.0)
        active_temp = block_temp + 0.04 * math.sin(elapsed)
        output = 18.0 + 2.0 * math.sin(elapsed / 4.0) if self.running else 0.0
        raw_values = [output, block_temp, -999.9, self.setpoint, active_temp, 1, 2, 3, 4, 5]
        return {
            "output": output,
            "setpoint": self.setpoint,
            "raw_values": raw_values,
            "raw_line": "[3 0 6 " + " ".join(f"{value:.3f}" for value in raw_values) + "]",
            "temp_sensor_1": block_temp,
            "temp_sensor_2": None,
            "temp_sensor_3": None,
            "temp_sensor_4": None,
            "block_temp": block_temp,
            "ambient_temp": None,
            "onboard_temp": None,
            "active_temp": active_temp,
        }

    def read_monitoring_values(self) -> dict[str, float]:
        self._require_connected()
        elapsed = time.monotonic() - self.started_at
        return {
            "onboard_temp": 29.0 + 0.1 * math.sin(elapsed / 5.0),
            "input_voltage": 12.0,
            "main_current": 1.2 if self.running else 0.08,
        }

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("Simulated controller is not connected.")
