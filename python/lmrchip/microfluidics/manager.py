"""Safe asynchronous lifecycle manager for the GRBL microfluidic machine."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from typing import Any

from lmrchip.errors import CommandError


EventSink = Callable[[str, dict[str, Any]], None]


class MicrofluidicsManager:
    def __init__(self, event_sink: EventSink | None = None) -> None:
        self._event_sink = event_sink or (lambda _event, _data: None)
        self._lock = threading.Lock()
        self._grbl: Any | None = None
        self._machine: Any | None = None
        self._connection_state = "disconnected"
        self._operation_state = "idle"
        self._needle_state = "unknown"
        self._last_grbl_status: str | None = None
        self._worker: threading.Thread | None = None

    @property
    def simulation_enabled(self) -> bool:
        return os.environ.get("LMRCHIP_SIMULATE_MICROFLUIDICS") == "1"

    def list_ports(self) -> list[str]:
        if self.simulation_enabled:
            return ["SIMULATED"]
        try:
            from serial.tools import list_ports
        except ImportError as error:
            raise CommandError("MICROFLUIDICS_STATE_UNKNOWN", "pyserial is not installed.") from error
        return [port.device for port in list_ports.comports()]

    def connect(self, port: str) -> dict[str, Any]:
        with self._lock:
            if self._grbl is not None:
                raise CommandError("ALREADY_CONNECTED", "GRBL is already connected.")
            if port not in self.list_ports():
                raise CommandError("PORT_UNAVAILABLE", f"Port {port!r} is not available.")
            try:
                controller_class, machine_class = self._classes()
                grbl = controller_class(port=port)
                grbl.connect()
                machine = machine_class(grbl)
                if self.simulation_enabled:
                    machine.NEEDLE_LOWERING_DELAY = 0.02
            except CommandError:
                raise
            except Exception as error:
                raise CommandError("MICROFLUIDICS_STATE_UNKNOWN", f"Could not connect GRBL: {error}") from error
            self._grbl, self._machine = grbl, machine
            self._connection_state = "connected"
            self._operation_state = "idle"
            self._needle_state = "unknown"
        self._emit_state()
        return self.snapshot()

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            self._require_connected()
            if self._is_busy():
                raise CommandError("BUSY", "Wait for the active movement before disconnecting.")
            try:
                self._grbl.close()
            except Exception as error:
                self._connection_state = "unknown"
                raise CommandError("MICROFLUIDICS_STATE_UNKNOWN", f"Could not close GRBL: {error}") from error
            self._grbl = None
            self._machine = None
            self._connection_state = "disconnected"
            self._operation_state = "idle"
            self._needle_state = "unknown"
            self._last_grbl_status = None
        self._emit_state()
        return self.snapshot()

    def unlock(self): return self._start_operation("unlocking", self._grbl_unlock)
    def calibrate(self): return self._start_operation("calibrating", self._machine_calibrate)
    def select_tube(self, tube_number):
        if isinstance(tube_number, bool) or not isinstance(tube_number, int) or not 1 <= tube_number <= 12:
            raise CommandError("INVALID_TUBE", "Tube number must be an integer from 1 to 12.")
        return self._start_operation("moving_carousel", lambda: self._machine.run_tube(tube_number))
    def raise_needle(self): return self._start_operation("raising_needle", self._machine_raise)
    def lower_needle(self): return self._start_operation("lowering_needle", self._machine_lower)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            machine = self._machine
            return {
                "connection_state": self._connection_state,
                "operation_state": self._operation_state,
                "busy": self._is_busy(),
                "calibrated": bool(machine and machine.is_calibrated),
                "current_tube": machine.current_tube if machine and machine.is_calibrated else None,
                "needle_state": self._needle_state,
                "last_grbl_status": self._last_grbl_status,
                "simulation": self.simulation_enabled,
            }

    def shutdown(self) -> None:
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=130.0)
        if self._grbl is not None:
            try: self.disconnect()
            except CommandError: pass

    def _start_operation(self, state, operation):
        with self._lock:
            self._require_connected()
            if self._is_busy():
                raise CommandError("BUSY", "Another physical operation is active.")
            self._operation_state = state
            worker = threading.Thread(target=self._run_operation, args=(state, operation), daemon=True, name=f"microfluidics-{state}")
            self._worker = worker
            worker.start()
        snapshot = self.snapshot()
        self._emit("microfluidics.operation_started", snapshot)
        self._emit_state()
        return snapshot

    def _run_operation(self, name, operation):
        try:
            operation()
            with self._lock:
                self._last_grbl_status = self._grbl.get_status()
                self._operation_state = "idle"
                if self._machine.is_calibrated:
                    self._needle_state = "lowered" if self._machine.needle_is_lowered else "raised"
            self._emit("microfluidics.operation_completed", {"operation": name, "state": self.snapshot()})
        except Exception as error:
            with self._lock:
                self._operation_state = "unknown"
                self._needle_state = "unknown"
                if self._machine is not None:
                    self._machine.is_calibrated = False
                    self._machine.current_tube = None
            code = "MOVEMENT_TIMEOUT" if isinstance(error, TimeoutError) else "GRBL_ALARM" if "ALARM" in str(error).upper() else "MICROFLUIDICS_STATE_UNKNOWN"
            self._emit("microfluidics.error", {"code": code, "message": str(error)})
        finally:
            self._emit_state()

    def _grbl_unlock(self): self._grbl.unlock()
    def _machine_calibrate(self): self._machine.calibrate()
    def _machine_raise(self): self._machine.raise_needle()
    def _machine_lower(self): self._machine.lower_needle()

    def _classes(self):
        from .machine import MicrofluidicMachine
        if self.simulation_enabled:
            from .simulator import SimulatedGrblController
            return SimulatedGrblController, MicrofluidicMachine
        try:
            from .controller import GrblController
        except ImportError as error:
            raise CommandError("MICROFLUIDICS_STATE_UNKNOWN", "GRBL dependencies are not installed.") from error
        return GrblController, MicrofluidicMachine

    def _require_connected(self):
        if self._grbl is None or self._machine is None:
            raise CommandError("NOT_CONNECTED", "GRBL is not connected.")

    def _is_busy(self): return self._worker is not None and self._worker.is_alive()
    def _emit(self, event, data): self._event_sink(event, data)
    def _emit_state(self): self._emit("microfluidics.state", self.snapshot())
