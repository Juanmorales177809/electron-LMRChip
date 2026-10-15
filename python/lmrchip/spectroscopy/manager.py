"""Lifecycle, calibration, acquisition, and tracking manager for spectroscopy."""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import numpy as np

from lmrchip.errors import CommandError

from .resonance import ResonanceTracker


EventSink = Callable[[str, dict[str, Any]], None]


DEFAULT_SETTINGS = {
    "integration_time": 100.0,
    "scans_to_average": 10,
    "delay": 0.05,
    "boxcar_width": 2,
    "search_min_nm": 650.0,
    "search_max_nm": 750.0,
    "fit_half_window_nm": 1.5,
    "smoothing_window": 9,
    "tracking_half_window_nm": 15.0,
    "tracking_interval_ms": 250,
}


class SpectrometerManager:
    def __init__(self, event_sink: EventSink | None = None) -> None:
        self._event_sink = event_sink or (lambda _event, _data: None)
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._optical: Any | None = None
        self._connection_state = "disconnected"
        self._device_id: str | None = None
        self._settings = dict(DEFAULT_SETTINGS)
        self._tracking = False
        self._tracking_stop = threading.Event()
        self._tracking_thread: threading.Thread | None = None

    @property
    def simulation_enabled(self) -> bool:
        return os.environ.get("LMRCHIP_SIMULATE_SPECTROMETER") == "1"

    def list_devices(self) -> list[dict[str, str]]:
        if self.simulation_enabled:
            return [{"id": "SIMULATED", "model": "USB4000 Simulator", "serial": "SIM-001"}]
        try:
            import seabreeze.spectrometers as spectrometers
        except ImportError as error:
            raise CommandError("ACQUISITION_ERROR", "SeaBreeze is not installed.") from error
        return [
            {
                "id": str(index),
                "model": str(getattr(device, "model", type(device).__name__)),
                "serial": str(getattr(device, "serial_number", "unknown")),
            }
            for index, device in enumerate(spectrometers.list_devices())
        ]

    def connect(self, device_id: str) -> dict[str, Any]:
        with self._state_lock:
            if self._optical is not None:
                raise CommandError("ALREADY_CONNECTED", "A spectrometer is already connected.")
        devices = self.list_devices()
        selected = next((device for device in devices if device["id"] == device_id), None)
        if selected is None:
            raise CommandError("NO_DEVICE", f"Spectrometer {device_id!r} is not available.")
        try:
            optical = self._create_optical()
            if self.simulation_enabled:
                optical.connect()
            else:
                import seabreeze.spectrometers as spectrometers
                hardware = spectrometers.list_devices()[int(device_id)]
                optical.connect(hardware)
        except Exception as error:
            raise CommandError("ACQUISITION_ERROR", f"Could not connect spectrometer: {error}") from error
        with self._state_lock:
            self._optical = optical
            self._connection_state = "connected"
            self._device_id = device_id
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def disconnect(self) -> dict[str, Any]:
        optical = self._require_optical()
        self.stop_tracking()
        try:
            with self._lock:
                optical.close()
        except Exception as error:
            self._mark_unknown(error)
            raise CommandError("SPECTROMETER_STATE_UNKNOWN", f"Could not close spectrometer: {error}") from error
        with self._state_lock:
            self._optical = None
            self._connection_state = "disconnected"
            self._device_id = None
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def configure(self, values: dict[str, Any]) -> dict[str, Any]:
        self._require_optical()
        if self._tracking:
            raise CommandError("BUSY", "Stop tracking before changing configuration.")
        settings = dict(self._settings)
        settings.update(values)
        self._validate_settings(settings)
        optical = self._require_optical()
        with self._lock:
            optical.integration_time = settings["integration_time"]
            optical.scans_to_average = settings["scans_to_average"]
            optical.delay = settings["delay"]
            optical.boxcar_width = settings["boxcar_width"]
            optical._validate_acquisition_settings()
            if optical.spec is not None:
                optical.spec.integration_time_micros(int(optical.integration_time * 1000))
        self._settings = settings
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def capture(self, measurement_type: str) -> dict[str, Any]:
        if self._tracking:
            raise CommandError("BUSY", "Manual acquisition is unavailable during tracking.")
        optical = self._require_optical()
        try:
            with self._lock:
                spectrum = optical.measure(measurement_type)
                saturation = optical.check_saturation(spectrum)
        except Exception as error:
            raise CommandError("ACQUISITION_ERROR", f"Could not acquire {measurement_type}: {error}") from error
        payload = self._spectrum_payload(measurement_type, spectrum)
        self._emit("spectrometer.spectrum", payload)
        self._emit("spectrometer.saturation", saturation)
        self._emit("spectrometer.state", self.snapshot())
        return payload

    def calculate_transmission(self) -> dict[str, Any]:
        optical = self._require_optical()
        self._require_calibration(optical, require_sample=True)
        try:
            with self._lock:
                transmission = optical.calculate_transmission()
        except Exception as error:
            raise CommandError("ACQUISITION_ERROR", f"Could not calculate transmission: {error}") from error
        payload = self._transmission_payload(transmission)
        self._emit("spectrometer.transmission", payload)
        return payload

    def start_tracking(self) -> dict[str, Any]:
        optical = self._require_optical()
        self._require_calibration(optical)
        if self._tracking:
            raise CommandError("BUSY", "LMR tracking is already running.")
        self._tracking = True
        self._tracking_stop.clear()
        self._tracking_thread = threading.Thread(target=self._tracking_loop, name="spectrometer-tracking", daemon=True)
        self._tracking_thread.start()
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def stop_tracking(self) -> dict[str, Any]:
        self._tracking_stop.set()
        thread = self._tracking_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=10.0)
        self._tracking = False
        self._tracking_thread = None
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def clear_calibration(self) -> dict[str, Any]:
        if self._tracking:
            raise CommandError("BUSY", "Stop tracking before clearing calibration.")
        optical = self._require_optical()
        optical.background = None
        optical.reference = None
        optical.sample = None
        self._emit("spectrometer.state", self.snapshot())
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            optical = self._optical
            return {
                "connection_state": self._connection_state,
                "device_id": self._device_id,
                "simulation": self.simulation_enabled,
                "tracking": self._tracking,
                "has_background": optical is not None and optical.background is not None,
                "has_reference": optical is not None and optical.reference is not None,
                "has_sample": optical is not None and optical.sample is not None,
                "settings": dict(self._settings),
            }

    def shutdown(self) -> None:
        if self._optical is None:
            return
        try:
            self.disconnect()
        except CommandError:
            pass

    def _tracking_loop(self) -> None:
        tracker = ResonanceTracker(
            self._settings["search_min_nm"], self._settings["search_max_nm"],
            fit_half_window_nm=self._settings["fit_half_window_nm"],
            smoothing_window=self._settings["smoothing_window"],
            tracking_half_window_nm=self._settings["tracking_half_window_nm"],
        )
        while not self._tracking_stop.is_set():
            started = time.monotonic()
            try:
                optical = self._require_optical()
                with self._lock:
                    transmission = optical.acquire_transmission()
                    result = tracker.update(optical.wavelengths, transmission)
                result_data = asdict(result)
                result_data["fit_wavelengths"] = _array_values(result.fit_wavelengths)
                result_data["fit_transmission"] = _array_values(result.fit_transmission)
                payload = self._transmission_payload(transmission)
                payload["result"] = _json_values(result_data)
                payload["timestamp"] = time.time()
                self._emit("spectrometer.tracking", payload)
            except Exception as error:
                self._tracking = False
                self._emit_error("ACQUISITION_ERROR", str(error))
                self._emit("spectrometer.state", self.snapshot())
                return
            interval = self._settings["tracking_interval_ms"] / 1000.0
            self._tracking_stop.wait(max(0.0, interval - (time.monotonic() - started)))
        self._tracking = False

    def _create_optical(self):
        acquisition = {key: self._settings[key] for key in ("integration_time", "scans_to_average", "delay", "boxcar_width")}
        if self.simulation_enabled:
            from .simulator import SimulatedSpectrometer
            return SimulatedSpectrometer(**acquisition)
        try:
            from .spectrometer import Spectrometer
        except ImportError as error:
            raise CommandError("ACQUISITION_ERROR", "Spectrometer dependencies are not installed.") from error
        return Spectrometer(**acquisition)

    def _require_optical(self):
        with self._state_lock:
            optical = self._optical
        if optical is None:
            raise CommandError("NOT_CONNECTED", "Spectrometer is not connected.")
        return optical

    @staticmethod
    def _require_calibration(optical, require_sample=False):
        missing = []
        if optical.background is None: missing.append("background")
        if optical.reference is None: missing.append("reference")
        if require_sample and optical.sample is None: missing.append("sample")
        if missing:
            raise CommandError("CALIBRATION_REQUIRED", "Missing calibration: " + ", ".join(missing) + ".")

    @staticmethod
    def _validate_settings(settings):
        try:
            if settings["integration_time"] <= 0 or int(settings["scans_to_average"]) != settings["scans_to_average"] or settings["scans_to_average"] < 1:
                raise ValueError
            if settings["delay"] < 0 or int(settings["boxcar_width"]) != settings["boxcar_width"] or settings["boxcar_width"] < 0:
                raise ValueError
            if settings["search_min_nm"] >= settings["search_max_nm"] or settings["fit_half_window_nm"] <= 0:
                raise ValueError
            if int(settings["smoothing_window"]) != settings["smoothing_window"] or settings["smoothing_window"] < 1:
                raise ValueError
            if settings["tracking_half_window_nm"] <= 0 or settings["tracking_interval_ms"] < 0:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise CommandError("INVALID_CONFIGURATION", "Invalid spectrometer configuration.") from error

    def _spectrum_payload(self, kind, spectrum):
        optical = self._require_optical()
        return {"kind": kind, "wavelengths": _array_values(optical.wavelengths), "values": _array_values(spectrum)}

    def _transmission_payload(self, transmission):
        optical = self._require_optical()
        return {
            "wavelengths": _array_values(optical.wavelengths),
            "values": _array_values(transmission),
            "diagnostics": _json_values(optical.transmission_diagnostics),
        }

    def _mark_unknown(self, error):
        with self._state_lock:
            self._connection_state = "unknown"
        self._emit_error("SPECTROMETER_STATE_UNKNOWN", str(error))
        self._emit("spectrometer.state", self.snapshot())

    def _emit(self, event, data): self._event_sink(event, data)
    def _emit_error(self, code, message): self._emit("spectrometer.error", {"code": code, "message": message})


def _array_values(values):
    if values is None:
        return None
    return [float(value) if math.isfinite(float(value)) else None for value in np.asarray(values).flat]


def _json_values(value):
    if isinstance(value, dict): return {key: _json_values(item) for key, item in value.items()}
    if isinstance(value, (np.floating, float)): return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer): return int(value)
    return value
