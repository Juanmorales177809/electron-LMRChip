"""Coordinate the three hardware modules and persist experiment results."""

from __future__ import annotations

import csv
import json
import math
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from lmrchip.errors import CommandError
from lmrchip.protocols import ProtocolStore, validate_protocol


EventSink = Callable[[str, dict[str, Any]], None]
TERMINAL_STATES = {"completed", "cancelled", "failed"}
DEFAULT_CONFIG = {
    "tubes": list(range(1, 13)),
    "setpoint": 37.0,
    "temperature_tolerance": 0.2,
    "stable_seconds": 60.0,
    "stabilization_timeout_seconds": 1800.0,
    "tracking_seconds": 60.0,
}


class ExperimentManager:
    """Run one experiment at a time without bypassing module safety rules."""

    def __init__(self, temperature, spectrometer, microfluidics, event_sink: EventSink | None = None, protocol_store: ProtocolStore | None = None) -> None:
        self.temperature = temperature
        self.spectrometer = spectrometer
        self.microfluidics = microfluidics
        self._event_sink = event_sink or (lambda _event, _data: None)
        self._protocol_store = protocol_store or ProtocolStore()
        self._lock = threading.RLock()
        self._pause_requested = threading.Event()
        self._resume_requested = threading.Event()
        self._cancel_requested = threading.Event()
        self._worker: threading.Thread | None = None
        self._state = "idle"
        self._phase = "idle"
        self._config: dict[str, Any] | None = None
        self._result_dir: Path | None = None
        self._current_tube: int | None = None
        self._completed_tubes: list[int] = []
        self._error: dict[str, str] | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._protocol: dict[str, Any] | None = None
        self._current_step: int | None = None
        self._completed_steps: list[int] = []
        self._spectrum_index = 0
        self._file_lock = threading.Lock()

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        protocol = self._load_protocol(payload)
        if protocol is not None:
            self._validate_protocol_execution(protocol)
        config, root = self._validated_config(payload, protocol)
        self._validate_prerequisites(config)
        return {"valid": True, "config": config, "results_root": str(root)}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise CommandError("BUSY", "An experiment is already active.")
        protocol = self._load_protocol(payload)
        if protocol is not None:
            self._validate_protocol_execution(protocol)
        config, root = self._validated_config(payload, protocol)
        self._validate_prerequisites(config)
        result_dir = self._create_result_dir(root)
        with self._lock:
            self._config = config
            self._result_dir = result_dir
            self._state = "running"
            self._phase = "starting"
            self._current_tube = None
            self._completed_tubes = []
            self._error = None
            self._started_at = _utc_now()
            self._finished_at = None
            self._protocol = protocol
            self._current_step = None
            self._completed_steps = []
            self._spectrum_index = 0
            self._pause_requested.clear()
            self._resume_requested.clear()
            self._cancel_requested.clear()
            self._initialize_files()
            self._write_metadata()
            self._worker = threading.Thread(target=self._run, name="experiment-orchestrator", daemon=True)
            self._worker.start()
        self._emit_state()
        return self.snapshot()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "running":
                raise CommandError("INVALID_STATE", "Only a running experiment can be paused.")
            self._pause_requested.set()
            self._phase = "pause_requested"
        self._emit_state()
        return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if self._state != "paused":
                raise CommandError("INVALID_STATE", "Only a paused experiment can be resumed.")
            self._resume_requested.set()
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        with self._lock:
            if self._state not in {"running", "paused"}:
                raise CommandError("INVALID_STATE", "There is no active experiment to cancel.")
            self._cancel_requested.set()
            self._resume_requested.set()
            self._phase = "cancelling"
        self._emit_state()
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            config = dict(self._config) if self._config else None
            return {
                "state": self._state,
                "phase": self._phase,
                "config": config,
                "result_directory": str(self._result_dir) if self._result_dir else None,
                "current_tube": self._current_tube,
                "completed_tubes": list(self._completed_tubes),
                "total_tubes": len(config["tubes"]) if config else 0,
                "pause_requested": self._pause_requested.is_set(),
                "error": dict(self._error) if self._error else None,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "protocol_id": self._protocol["id"] if self._protocol else None,
                "protocol_name": self._protocol["name"] if self._protocol else None,
                "protocol": self._protocol,
                "current_step": self._current_step,
                "completed_steps": list(self._completed_steps),
                "total_steps": len(self._protocol["steps"]) if self._protocol else 0,
                "progress_percent": self._progress_percent(),
            }

    def handle_module_event(self, event: str, data: dict[str, Any]) -> None:
        with self._lock:
            active = self._state in {"running", "paused"} and self._result_dir is not None
            tube = self._current_tube
            phase = self._phase
        if not active:
            return
        if event == "temperature.sample":
            self._append_csv("temperature.csv", [
                time.time(), tube, phase, data.get("block_temp"), data.get("active_temp"),
                data.get("setpoint"), data.get("output"),
            ])
        elif event == "spectrometer.tracking" and phase == "tracking":
            result = data.get("result") or {}
            self._append_csv("resonance.csv", [
                data.get("timestamp", time.time()), tube, result.get("valid"),
                result.get("wavelength"), result.get("transmission"), result.get("r_squared"),
                result.get("prominence"), result.get("reason"),
            ])
            self._save_spectrum(tube, data)
        elif event.endswith(".error"):
            self._append_event(event, data)

    def shutdown(self) -> None:
        self._cancel_requested.set()
        self._resume_requested.set()
        worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=140.0)

    def _run(self) -> None:
        try:
            assert self._config is not None
            sequence = self._protocol_sequence()
            for sequence_index, tube in enumerate(sequence):
                with self._lock:
                    self._current_step = sequence_index if self._protocol else None
                self._emit_state()
                if self._cancel_requested.is_set():
                    break
                completed = self._run_tube(tube)
                if not completed:
                    if self._cancel_requested.is_set():
                        break
                    self._wait_while_paused()
                    if self._cancel_requested.is_set():
                        break
                    completed = self._run_tube(tube)
                    while not completed and not self._cancel_requested.is_set():
                        self._wait_while_paused()
                        if not self._cancel_requested.is_set():
                            completed = self._run_tube(tube)
                if completed:
                    with self._lock:
                        if tube not in self._completed_tubes:
                            self._completed_tubes.append(tube)
                        if self._protocol:
                            self._completed_steps.append(sequence_index)
                    self._write_metadata()
                    self._emit_progress()
            if self._cancel_requested.is_set():
                self._finish("cancelled", "cancelled")
            else:
                self._finish("completed", "completed")
        except Exception as error:
            self._safe_stop_tracking()
            self._safe_raise_needle()
            code = error.code if isinstance(error, CommandError) else "EXPERIMENT_FAILED"
            with self._lock:
                self._error = {"code": code, "message": str(error)}
            self._append_event("experiment.error", self._error)
            self._finish("failed", "failed")

    def _run_tube(self, tube: int) -> bool:
        with self._lock:
            self._current_tube = tube
        self._set_phase("selecting_tube")
        self.microfluidics.select_tube(tube)
        self._wait_for_microfluidics()
        if self._interruption_requested():
            self._safe_raise_needle()
            return False
        self._set_phase("stabilizing")
        if not self._wait_for_stable_temperature():
            self._safe_raise_needle()
            return False
        self._set_phase("tracking")
        self.spectrometer.start_tracking()
        deadline = time.monotonic() + self._config["tracking_seconds"]
        while time.monotonic() < deadline and not self._interruption_requested():
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))
        self._safe_stop_tracking()
        self._safe_raise_needle()
        return not self._interruption_requested()

    def _protocol_sequence(self) -> list[int]:
        if not self._protocol:
            return list(self._config["tubes"]) if self._config else []
        return [step["tube"] for step in self._protocol["steps"] if step.get("sample_id") is not None]

    def _load_protocol(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if "protocol_id" not in payload and "protocol" not in payload:
            return None
        protocol = self._protocol_store.load(payload["protocol_id"]) if "protocol_id" in payload else validate_protocol(payload.get("protocol"))
        sample_tubes = {position["sample_id"]: index for index, position in enumerate(protocol["positions"], start=1) if position["sample_id"] is not None}
        for step in protocol["steps"]:
            if step["sample_id"] is not None:
                step["tube"] = sample_tubes.get(step["sample_id"])
        return protocol

    @staticmethod
    def _validate_protocol_execution(protocol: dict[str, Any]) -> None:
        configured = [step for step in protocol["steps"] if step["sample_id"] is not None]
        if not configured:
            raise CommandError("INVALID_PROTOCOL", "Protocol must contain at least one configured step.")
        positions: dict[str, int] = {}
        for index, position in enumerate(protocol["positions"], start=1):
            sample_id = position["sample_id"]
            if sample_id is not None and sample_id not in positions:
                positions[sample_id] = index
        for step in configured:
            if step["sample_id"] not in positions:
                raise CommandError("INVALID_PROTOCOL", "Every configured step must resolve to a carousel position.")
            if step["flow_rate"] is not None:
                raise CommandError(
                    "FLOW_CONTROL_UNAVAILABLE",
                    "This installation has no connected flow controller; protocol steps with flow_rate cannot run yet.",
                )

    def _progress_percent(self) -> int:
        total = len(self._protocol["steps"]) if self._protocol else len(self._config["tubes"]) if self._config else 0
        completed = len(self._completed_steps) if self._protocol else len(self._completed_tubes)
        return round(completed / total * 100) if total else 0

    def _wait_for_stable_temperature(self) -> bool:
        assert self._config is not None
        deadline = time.monotonic() + self._config["stabilization_timeout_seconds"]
        stable_since: float | None = None
        while time.monotonic() < deadline:
            if self._interruption_requested():
                return False
            sample = self.temperature.snapshot().get("latest_sample") or {}
            value = sample.get("active_temp")
            if _finite_number(value) and abs(float(value) - self._config["setpoint"]) <= self._config["temperature_tolerance"]:
                stable_since = stable_since or time.monotonic()
                elapsed = time.monotonic() - stable_since
                self._emit("experiment.temperature", {"value": value, "stable_seconds": elapsed})
                if elapsed >= self._config["stable_seconds"]:
                    return True
            else:
                stable_since = None
            time.sleep(0.1)
        raise CommandError("STABILIZATION_TIMEOUT", "Temperature did not stabilize before the configured timeout.")

    def _wait_while_paused(self) -> None:
        with self._lock:
            self._state = "paused"
            self._phase = "paused"
            self._pause_requested.clear()
        self._write_metadata()
        self._emit_state()
        while not self._cancel_requested.is_set():
            if self._resume_requested.wait(0.2):
                self._resume_requested.clear()
                with self._lock:
                    self._state = "running"
                    self._phase = "resuming"
                self._emit_state()
                return

    def _wait_for_microfluidics(self) -> None:
        deadline = time.monotonic() + 130.0
        while time.monotonic() < deadline:
            state = self.microfluidics.snapshot()
            if not state["busy"]:
                if state["operation_state"] != "idle":
                    raise CommandError("MICROFLUIDICS_STATE_UNKNOWN", "Microfluidic movement did not finish safely.")
                return
            time.sleep(0.05)
        raise CommandError("MOVEMENT_TIMEOUT", "Microfluidic movement exceeded 130 seconds.")

    def _safe_stop_tracking(self) -> None:
        try:
            if self.spectrometer.snapshot()["tracking"]:
                self.spectrometer.stop_tracking()
        except Exception as error:
            self._append_event("experiment.cleanup_error", {"action": "stop_tracking", "message": str(error)})

    def _safe_raise_needle(self) -> None:
        try:
            state = self.microfluidics.snapshot()
            if state["connection_state"] == "connected" and state["needle_state"] == "lowered" and not state["busy"]:
                self._set_phase("raising_needle")
                self.microfluidics.raise_needle()
                self._wait_for_microfluidics()
        except Exception as error:
            self._append_event("experiment.cleanup_error", {"action": "raise_needle", "message": str(error)})

    def _validate_prerequisites(self, config: dict[str, Any]) -> None:
        temperature = self.temperature.snapshot()
        spectrometer = self.spectrometer.snapshot()
        microfluidics = self.microfluidics.snapshot()
        problems = []
        if temperature["connection_state"] != "connected" or temperature["control_state"] != "running":
            problems.append("temperature control must be connected and running")
        sample = temperature.get("latest_sample") or {}
        if _finite_number(sample.get("setpoint")) and abs(float(sample["setpoint"]) - config["setpoint"]) > 0.01:
            problems.append("temperature setpoint does not match the experiment")
        if spectrometer["connection_state"] != "connected" or not spectrometer["has_background"] or not spectrometer["has_reference"]:
            problems.append("spectrometer must be connected with background and reference")
        if spectrometer["tracking"]:
            problems.append("spectrometer tracking must be stopped")
        if microfluidics["connection_state"] != "connected" or not microfluidics["calibrated"] or microfluidics["busy"]:
            problems.append("microfluidics must be connected, calibrated, and idle")
        if microfluidics["needle_state"] != "raised":
            problems.append("needle must be in the known raised position")
        if problems:
            raise CommandError("PREREQUISITES_NOT_MET", "; ".join(problems) + ".")

    def _validated_config(self, payload: dict[str, Any], protocol: dict[str, Any] | None = None) -> tuple[dict[str, Any], Path]:
        root_value = payload.get("results_root")
        if not isinstance(root_value, str) or not root_value.strip():
            raise CommandError("INVALID_RESULTS_PATH", "A results folder must be selected.")
        root = Path(root_value).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise CommandError("INVALID_RESULTS_PATH", "Results folder must be an existing absolute directory.")
        config = dict(DEFAULT_CONFIG)
        config.update({key: payload[key] for key in DEFAULT_CONFIG if key in payload})
        if protocol is not None:
            tubes = [step["tube"] for step in protocol["steps"] if step.get("sample_id") is not None and step.get("tube") is not None]
            config["tubes"] = tubes or config["tubes"]
        tubes = config["tubes"]
        if not isinstance(tubes, list) or not tubes or any(isinstance(t, bool) or not isinstance(t, int) or not 1 <= t <= 12 for t in tubes) or len(set(tubes)) != len(tubes):
            raise CommandError("INVALID_CONFIGURATION", "Tubes must be a non-empty, unique list containing values from 1 to 12.")
        for key in ("setpoint", "temperature_tolerance", "stable_seconds", "stabilization_timeout_seconds", "tracking_seconds"):
            value = config[key]
            if not _finite_number(value) or float(value) <= 0:
                raise CommandError("INVALID_CONFIGURATION", f"{key} must be a positive finite number.")
            config[key] = float(value)
        if not 10 <= config["setpoint"] <= 80 or config["stable_seconds"] > config["stabilization_timeout_seconds"]:
            raise CommandError("INVALID_CONFIGURATION", "Invalid temperature range or stabilization timing.")
        config["tubes"] = list(tubes)
        return config, root.resolve()

    @staticmethod
    def _create_result_dir(root: Path) -> Path:
        base = datetime.now().strftime("experimento_%Y%m%d_%H%M%S")
        candidate = root / base
        suffix = 1
        while candidate.exists():
            candidate = root / f"{base}_{suffix:02d}"
            suffix += 1
        candidate.mkdir(parents=False)
        (candidate / "spectra").mkdir()
        return candidate

    def _initialize_files(self) -> None:
        assert self._result_dir is not None
        headers = {
            "temperature.csv": ["timestamp", "tube", "phase", "block_temp", "active_temp", "setpoint", "output"],
            "resonance.csv": ["timestamp", "tube", "valid", "wavelength_nm", "transmission", "r_squared", "prominence", "reason"],
        }
        for filename, header in headers.items():
            with (self._result_dir / filename).open("w", newline="", encoding="utf-8") as stream:
                csv.writer(stream).writerow(header)
        (self._result_dir / "events.jsonl").touch()

    def _append_csv(self, filename: str, row: list[Any]) -> None:
        result_dir = self._result_dir
        if result_dir is None:
            return
        with self._file_lock, (result_dir / filename).open("a", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerow(row)

    def _append_event(self, event: str, data: dict[str, Any]) -> None:
        result_dir = self._result_dir
        if result_dir is None:
            return
        record = {"timestamp": time.time(), "event": event, "data": data}
        with self._file_lock, (result_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _save_spectrum(self, tube: int | None, data: dict[str, Any]) -> None:
        result_dir = self._result_dir
        if result_dir is None or tube is None:
            return
        with self._file_lock:
            self._spectrum_index += 1
            target = result_dir / "spectra" / f"tube_{tube:02d}_{self._spectrum_index:06d}.npz"
            np.savez_compressed(
                target,
                wavelengths=np.asarray(data.get("wavelengths", []), dtype=float),
                transmission=np.asarray(data.get("values", []), dtype=float),
                timestamp=float(data.get("timestamp", time.time())),
            )

    def _write_metadata(self) -> None:
        result_dir = self._result_dir
        if result_dir is None:
            return
        target = result_dir / "metadata.json"
        temporary = result_dir / "metadata.json.tmp"
        with self._file_lock:
            temporary.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, target)

    def _set_phase(self, phase: str) -> None:
        with self._lock:
            self._phase = phase
        self._write_metadata()
        self._emit_state()

    def _finish(self, state: str, phase: str) -> None:
        with self._lock:
            self._state = state
            self._phase = phase
            self._current_tube = None
            self._finished_at = _utc_now()
        self._write_metadata()
        self._emit_state()
        self._emit(f"experiment.{state}", self.snapshot())

    def _emit_progress(self) -> None:
        snapshot = self.snapshot()
        self._emit("experiment.progress", snapshot)

    def _emit_state(self) -> None:
        snapshot = self.snapshot()
        self._append_event("experiment.state", snapshot)
        self._event_sink("experiment.state", snapshot)

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        self._append_event(event, data)
        self._event_sink(event, data)

    def _interruption_requested(self) -> bool:
        return self._pause_requested.is_set() or self._cancel_requested.is_set()


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
