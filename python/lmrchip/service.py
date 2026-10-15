"""Persistent JSON Lines service used by the Electron main process."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
from collections.abc import Callable
from typing import Any, TextIO

from . import __version__
from .errors import CommandError
from .protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    Request,
    encode_message,
    error_response,
    parse_request,
    success_response,
    event_message,
)
from .temperature.manager import TemperatureManager
from .spectroscopy.manager import SpectrometerManager
from .microfluidics.manager import MicrofluidicsManager
from .experiment.manager import ExperimentManager


LOGGER = logging.getLogger("lmrchip.service")
CommandHandler = Callable[[dict[str, Any]], dict[str, Any]]


class LMRChipService:
    """Dispatch protocol commands without exposing hardware implementation details."""

    def __init__(self, event_sink: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.shutting_down = False
        self._external_event_sink = event_sink or (lambda _event, _data: None)
        self.experiment: ExperimentManager | None = None
        self.temperature = TemperatureManager(self._route_event)
        self.spectrometer = SpectrometerManager(self._route_event)
        self.microfluidics = MicrofluidicsManager(self._route_event)
        self.experiment = ExperimentManager(
            self.temperature, self.spectrometer, self.microfluidics, self._external_event_sink
        )
        self._commands: dict[str, CommandHandler] = {
            "system.ping": self._ping,
            "system.status": self._status,
            "system.shutdown": self._shutdown,
            "temperature.list_ports": self._temperature_list_ports,
            "temperature.connect": self._temperature_connect,
            "temperature.disconnect": self._temperature_disconnect,
            "temperature.start": self._temperature_start,
            "temperature.stop": self._temperature_stop,
            "temperature.status": self._temperature_status,
            "spectrometer.list_devices": self._spectrometer_list_devices,
            "spectrometer.connect": self._spectrometer_connect,
            "spectrometer.disconnect": self._spectrometer_disconnect,
            "spectrometer.configure": self._spectrometer_configure,
            "spectrometer.capture_background": lambda payload: self.spectrometer.capture("background"),
            "spectrometer.capture_reference": lambda payload: self.spectrometer.capture("reference"),
            "spectrometer.capture_sample": lambda payload: self.spectrometer.capture("sample"),
            "spectrometer.calculate_transmission": lambda payload: self.spectrometer.calculate_transmission(),
            "spectrometer.start_tracking": lambda payload: self.spectrometer.start_tracking(),
            "spectrometer.stop_tracking": lambda payload: self.spectrometer.stop_tracking(),
            "spectrometer.status": lambda payload: self.spectrometer.snapshot(),
            "spectrometer.clear_calibration": lambda payload: self.spectrometer.clear_calibration(),
            "microfluidics.list_ports": lambda payload: {"ports": self.microfluidics.list_ports(), "simulation": self.microfluidics.simulation_enabled},
            "microfluidics.connect": lambda payload: self.microfluidics.connect(payload.get("port")),
            "microfluidics.disconnect": lambda payload: self.microfluidics.disconnect(),
            "microfluidics.unlock": lambda payload: self.microfluidics.unlock(),
            "microfluidics.calibrate": lambda payload: self.microfluidics.calibrate(),
            "microfluidics.select_tube": lambda payload: self.microfluidics.select_tube(payload.get("tube_number")),
            "microfluidics.raise_needle": lambda payload: self.microfluidics.raise_needle(),
            "microfluidics.lower_needle": lambda payload: self.microfluidics.lower_needle(),
            "microfluidics.status": lambda payload: self.microfluidics.snapshot(),
            "experiment.validate": lambda payload: self.experiment.validate(payload),
            "experiment.start": lambda payload: self.experiment.start(payload),
            "experiment.pause": lambda payload: self.experiment.pause(),
            "experiment.resume": lambda payload: self.experiment.resume(),
            "experiment.cancel": lambda payload: self.experiment.cancel(),
            "experiment.status": lambda payload: self.experiment.snapshot(),
        }

    def _route_event(self, event: str, data: dict[str, Any]) -> None:
        if self.experiment is not None:
            self.experiment.handle_module_event(event, data)
        self._external_event_sink(event, data)

    def handle_line(self, line: str) -> dict[str, Any]:
        try:
            request = parse_request(line)
        except ProtocolError as error:
            return error_response(error.request_id, error.code, error.message)

        if self.shutting_down:
            return error_response(
                request.request_id,
                "SHUTTING_DOWN",
                "The service is shutting down.",
            )

        handler = self._commands.get(request.command)
        if handler is None:
            return error_response(
                request.request_id,
                "UNKNOWN_COMMAND",
                f"Unknown command: {request.command}.",
            )

        if self._manual_command_blocked(request.command):
            return error_response(
                request.request_id,
                "EXPERIMENT_ACTIVE",
                "Manual module commands are disabled while an experiment is active.",
            )

        try:
            data = handler(request.payload)
        except CommandError as error:
            return error_response(request.request_id, error.code, error.message)
        except Exception:
            LOGGER.exception("Command %s failed", request.command)
            return error_response(
                request.request_id,
                "INTERNAL_ERROR",
                "The command failed unexpectedly.",
            )

        return success_response(request.request_id, data)

    def _manual_command_blocked(self, command: str) -> bool:
        if self.experiment.snapshot()["state"] not in {"running", "paused"}:
            return False
        if not command.startswith(("temperature.", "spectrometer.", "microfluidics.")):
            return False
        return command not in {
            "temperature.status", "spectrometer.status", "microfluidics.status"
        }

    @staticmethod
    def _ping(payload: dict[str, Any]) -> dict[str, Any]:
        return {"status": "ok"}

    def _status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": "shutting_down" if self.shutting_down else "running",
            "service_version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "python_version": sys.version.split()[0],
            "process_id": os.getpid(),
            "temperature": self.temperature.snapshot(),
            "spectrometer": self.spectrometer.snapshot(),
            "microfluidics": self.microfluidics.snapshot(),
            "experiment": self.experiment.snapshot(),
        }

    def _shutdown(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.experiment.shutdown()
        self.temperature.shutdown()
        self.spectrometer.shutdown()
        self.microfluidics.shutdown()
        self.shutting_down = True
        return {"status": "shutdown-accepted"}

    def close(self) -> None:
        self.experiment.shutdown()
        self.temperature.shutdown()
        self.spectrometer.shutdown()
        self.microfluidics.shutdown()

    def _temperature_list_ports(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"ports": self.temperature.list_ports(), "simulation": self.temperature.simulation_enabled}

    def _temperature_connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.temperature.connect(payload.get("port"))

    def _temperature_disconnect(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.temperature.disconnect()

    def _temperature_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.temperature.start_control(payload.get("setpoint"))

    def _temperature_stop(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.temperature.stop_control()

    def _temperature_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.temperature.snapshot()

    def _spectrometer_list_devices(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"devices": self.spectrometer.list_devices(), "simulation": self.spectrometer.simulation_enabled}

    def _spectrometer_connect(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.spectrometer.connect(payload.get("device_id"))

    def _spectrometer_disconnect(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.spectrometer.disconnect()

    def _spectrometer_configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.spectrometer.configure(payload)


class JsonLineWriter:
    def __init__(self, output_stream: TextIO) -> None:
        self.output_stream = output_stream
        self._lock = threading.Lock()

    def write(self, message: dict[str, Any]) -> None:
        with self._lock:
            self.output_stream.write(encode_message(message) + "\n")
            self.output_stream.flush()

    def event(self, event: str, data: dict[str, Any]) -> None:
        self.write(event_message(event, data))


def run_service(
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    """Process requests sequentially until stdin closes or shutdown is accepted."""
    writer = JsonLineWriter(output_stream)
    service = LMRChipService(writer.event)
    LOGGER.info("LMRChip service started")

    for line in input_stream:
        response = service.handle_line(line)
        writer.write(response)
        if service.shutting_down:
            break

    service.close()
    LOGGER.info("LMRChip service stopped")
    return 0


def main() -> int:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    log_directory = os.environ.get("LMRCHIP_LOG_DIR")
    if log_directory:
        try:
            os.makedirs(log_directory, exist_ok=True)
            handlers.append(RotatingFileHandler(
                os.path.join(log_directory, "python.log"), maxBytes=5 * 1024 * 1024,
                backupCount=5, encoding="utf-8",
            ))
        except OSError:
            pass
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    try:
        return run_service()
    except Exception:
        LOGGER.exception("Fatal service error")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
