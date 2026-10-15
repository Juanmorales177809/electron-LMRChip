"""Explicit Ocean Optics simulator used for development and automated tests."""

from __future__ import annotations

import math
import time

import numpy as np


class SimulatedSpectrometer:
    def __init__(self, **settings) -> None:
        self.integration_time = settings["integration_time"]
        self.scans_to_average = settings["scans_to_average"]
        self.delay = settings["delay"]
        self.boxcar_width = settings["boxcar_width"]
        self.connected = False
        self.started_at = time.monotonic()
        self.wavelengths = np.linspace(400.0, 800.0, 1201)
        self.spec = None
        self.background = None
        self.reference = None
        self.sample = None
        self.transmission_diagnostics = {}

    def connect(self, device=None):
        self.connected = True
        self.spec = self

    def close(self):
        self.connected = False
        self.spec = None

    def integration_time_micros(self, value):
        return None

    def intensities(self):
        if not self.connected:
            raise RuntimeError("Simulated spectrometer is not connected.")
        elapsed = time.monotonic() - self.started_at
        center = 700.0 + 1.8 * math.sin(elapsed / 8.0)
        reference = 48_000.0 + 500.0 * np.sin(self.wavelengths / 35.0)
        dip = 0.62 - 0.42 * np.exp(-0.5 * ((self.wavelengths - center) / 4.5) ** 2)
        return 350.0 + reference * dip

    def acquire_spectrum(self):
        self._validate_acquisition_settings()
        spectra = []
        for _ in range(self.scans_to_average):
            spectra.append(self.intensities())
            time.sleep(self.delay)
        spectrum = np.mean(spectra, axis=0)
        if self.boxcar_width > 0:
            size = 2 * self.boxcar_width + 1
            padded = np.pad(spectrum, self.boxcar_width, mode="edge")
            spectrum = np.convolve(padded, np.ones(size) / size, mode="valid")
        return spectrum

    def measure(self, measurement_type):
        reference = 350.0 + 48_000.0 + 500.0 * np.sin(self.wavelengths / 35.0)
        if measurement_type == "background":
            spectrum = np.full_like(self.wavelengths, 350.0)
        elif measurement_type == "reference":
            spectrum = reference
        elif measurement_type == "sample":
            spectrum = self.acquire_spectrum()
        else:
            raise ValueError("measurement_type must be 'background', 'reference', or 'sample'.")
        setattr(self, measurement_type, spectrum)
        return spectrum

    def check_saturation(self, intensities, saturation_limit=65535, warning_limit=60000):
        maximum = float(np.nanmax(intensities))
        return {
            "max_counts": maximum,
            "is_saturated": maximum >= saturation_limit,
            "is_near_saturation": warning_limit < maximum < saturation_limit,
        }

    def calculate_transmission(self, sample=None):
        if self.background is None or self.reference is None:
            raise RuntimeError("Background and reference are required.")
        if sample is not None:
            self.sample = np.asarray(sample, dtype=float)
        if self.sample is None:
            raise RuntimeError("Sample is required.")
        denominator = self.reference - self.background
        threshold = max(1.0, 0.01 * float(np.nanmax(np.abs(denominator))))
        valid = np.isfinite(denominator) & np.isfinite(self.sample) & (np.abs(denominator) >= threshold)
        transmission = np.full(self.sample.shape, np.nan)
        raw = ((self.sample[valid] - self.background[valid]) / denominator[valid]) * 100
        clipped = np.count_nonzero((raw < 0) | (raw > 100))
        transmission[valid] = np.clip(raw, 0, 100)
        self.transmission_diagnostics = {
            "reference_threshold": threshold,
            "valid_points": int(np.count_nonzero(valid)),
            "total_points": int(transmission.size),
            "clipped_points": int(clipped),
        }
        return transmission

    def acquire_transmission(self):
        return self.calculate_transmission(sample=self.acquire_spectrum())

    def _validate_acquisition_settings(self):
        if self.integration_time <= 0 or self.scans_to_average < 1 or self.delay < 0 or self.boxcar_width < 0:
            raise ValueError("Invalid simulated acquisition settings.")
