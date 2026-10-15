"""Thread-safe lifecycle and streaming manager for the PR-59 controller."""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from typing import Any

from lmrchip.errors import CommandError

from .simulator import SimulatedPR59Controller


EventSink = Callable[[str, dict[str, Any]], None]


class TemperatureManager:
    SAMPLE_EVENT_INTERVAL = 0.2
    MONITOR_INTERVAL = 2.0
    READ_INTERVAL = 0.1

    def __init__(self, event_sink: EventSink | None = None) -> None:
        self._event_sink = event_sink or (lambda _event, _data: None)
        self._controller: Any | None = None
        self._serial_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._connection_state = "disconnected"
        self._control_state = "stopped"
        self._port: str | None = None
        self._version: str | None = None
        self._latest_sample: dict[str, Any] | None = None
        self._latest_monitoring: dict[str, Any] | None = None

    @property
    def simulation_enabled(self) -> bool:
        return os.environ.get("LMRCHIP_SIMULATE_TEMPERATURE") == "1"

    def list_ports(self) -> list[str]:
        if self.simulation_enabled:
            return ["SIMULATED"]
        try:
            from serial.tools import list_ports
        except ImportError as error:
            raise CommandError("COMMUNICATION_ERROR", "pyserial is not installed.") from error
        return [port.device for port in list_ports.comports()]

    def connect(self, port: str) -> dict[str, Any]:
        if not isinstance(port, str) or not port.strip():
            raise CommandError("PORT_UNAVAILABLE", "A serial port must be selected.")
        with self._state_lock:
            if self._controller is not None:
                raise CommandError("ALREADY_CONNECTED", "Temperature controller is already connected.")

        available = self.list_ports()
        if port not in available:
            raise CommandError("PORT_UNAVAILABLE", f"Port {port} is not available.")

        controller = self._create_controller()
        try:
            version = controller.connect(port=port, timeout=5.0)
            if not self.simulation_enabled:
                controller.ser.timeout = 0.3
            controller.start_stream()
        except Exception as error:
            try:
                controller.disconnect()
            except Exception:
                pass
            raise CommandError("COMMUNICATION_ERROR", f"Could not connect to {port}: {error}") from error

        with self._state_lock:
            self._controller = controller
            self._port = port
            self._version = version
            self._connection_state = "connected"
            self._control_state = "stopped"
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(target=self._reader_loop, name="temperature-reader", daemon=True)
        self._reader_thread.start()
        self._emit("temperature.state", self.snapshot())
        return self.snapshot()

    def disconnect(self) -> dict[str, Any]:
        controller = self._require_controller()
        self._reader_stop.set()
        reader = self._reader_thread
        if reader and reader is not threading.current_thread():
            reader.join(timeout=5.0)
        try:
            with self._serial_lock:
                controller.disconnect()
        except Exception as error:
            with self._state_lock:
                self._connection_state = "unknown"
                self._control_state = "unknown"
            self._emit_error("TEMPERATURE_STATE_UNKNOWN", str(error))
            raise CommandError(
                "TEMPERATURE_STATE_UNKNOWN",
                f"Could not confirm temperature controller shutdown: {error}",
            ) from error

        with self._state_lock:
            self._controller = None
            self._reader_thread = None
            self._connection_state = "disconnected"
            self._control_state = "stopped"
            self._port = None
            self._version = None
        self._emit("temperature.state", self.snapshot())
        return self.snapshot()

    def start_control(self, setpoint: float) -> dict[str, Any]:
        controller = self._require_controller()
        if isinstance(setpoint, bool) or not isinstance(setpoint, (int, float)) or not 10 <= setpoint <= 80:
            raise CommandError("INVALID_SETPOINT", "Setpoint must be between 10 and 80 °C.")
        try:
            with self._serial_lock:
                controller.start_control(float(setpoint))
        except ValueError as error:
            raise CommandError("INVALID_SETPOINT", str(error)) from error
        except Exception as error:
            self._mark_unknown(error)
            raise CommandError("COMMUNICATION_ERROR", f"Could not start temperature control: {error}") from error
        with self._state_lock:
            self._control_state = controller.control_state
        self._emit("temperature.state", self.snapshot())
        return self.snapshot()

    def stop_control(self) -> dict[str, Any]:
        controller = self._require_controller()
        try:
            with self._serial_lock:
                controller.stop_control()
                controller.start_stream()
        except Exception as error:
            self._mark_unknown(error)
            raise CommandError(
                "TEMPERATURE_STATE_UNKNOWN",
                f"Could not confirm temperature control stop: {error}",
            ) from error
        with self._state_lock:
            self._control_state = "stopped"
        self._emit("temperature.state", self.snapshot())
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "connection_state": self._connection_state,
                "control_state": self._control_state,
                "port": self._port,
                "version": self._version,
                "simulation": self.simulation_enabled,
                "latest_sample": self._latest_sample,
                "latest_monitoring": self._latest_monitoring,
            }

    def shutdown(self) -> None:
        if self._controller is None:
            return
        try:
            self.disconnect()
        except CommandError:
            pass

    def _reader_loop(self) -> None:
        next_sample_event = 0.0
        next_monitor = 0.0
        while not self._reader_stop.is_set():
            try:
                with self._serial_lock:
                    controller = self._require_controller()
                    sample = controller.read_sample()
                    now = time.monotonic()
                    monitoring = controller.read_monitoring_values() if now >= next_monitor else None
                if sample:
                    with self._state_lock:
                        self._latest_sample = sample
                    if now >= next_sample_event:
                        self._emit("temperature.sample", sample)
                        next_sample_event = now + self.SAMPLE_EVENT_INTERVAL
                if monitoring is not None:
                    with self._state_lock:
                        self._latest_monitoring = monitoring
                    self._emit("temperature.monitoring", monitoring)
                    next_monitor = now + self.MONITOR_INTERVAL
            except CommandError:
                break
            except Exception as error:
                if self._reader_stop.is_set():
                    break
                self._mark_unknown(error)
                time.sleep(1.0)
            self._reader_stop.wait(self.READ_INTERVAL)

    def _create_controller(self) -> Any:
        if self.simulation_enabled:
            return SimulatedPR59Controller()
        try:
            from .controller import PR59Controller
        except ImportError as error:
            raise CommandError("COMMUNICATION_ERROR", "Temperature dependencies are not installed.") from error
        return PR59Controller()

    def _require_controller(self) -> Any:
        with self._state_lock:
            controller = self._controller
        if controller is None:
            raise CommandError("NOT_CONNECTED", "Temperature controller is not connected.")
        return controller

    def _mark_unknown(self, error: Exception) -> None:
        with self._state_lock:
            self._connection_state = "unknown"
            self._control_state = "unknown"
        self._emit_error("COMMUNICATION_ERROR", str(error))
        self._emit("temperature.state", self.snapshot())

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self._event_sink(event, data)

    def _emit_error(self, code: str, message: str) -> None:
        self._emit("temperature.error", {"code": code, "message": message})
