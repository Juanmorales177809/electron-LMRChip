import time
from numbers import Integral, Real

import numpy as np
import seabreeze
from scipy.ndimage import uniform_filter1d

seabreeze.use("cseabreeze")
import seabreeze.spectrometers as spectrometers


class Spectrometer:
    def __init__(self,
                integration_time=100,
                scans_to_average=1,
                delay=0.0,
                boxcar_width=0):

        self.integration_time = integration_time
        self.scans_to_average = scans_to_average
        self.delay            = delay   # delay es el tiempo de espera entre una captura y la siguiente cuando haces promediado.
        self.boxcar_width     = boxcar_width

        self.spec       = None
        self.wavelengths = None
        self.background = None
        self.reference  = None
        self.sample     = None
        self.transmission_diagnostics = {}

        self._validate_acquisition_settings()

    def connect(self, device=None):
        self._validate_acquisition_settings()
        print("Searching spectrometers...")
        devices = spectrometers.list_devices()
        print(f"Devices found: {devices}")

        if not devices:
            raise RuntimeError("No spectrometer detected.")

        selected_device = devices[0] if device is None else device
        if selected_device not in devices:
            raise RuntimeError("Selected spectrometer is not available.")
        self.spec = spectrometers.Spectrometer(selected_device)
        self.spec.integration_time_micros(int(self.integration_time * 1000))
        self.wavelengths = self.spec.wavelengths()

    def close(self):
        if self.spec is not None:
            self.spec.close()
            self.spec = None

    def check_saturation(self, intensities, saturation_limit=65535, warning_limit=60000):
        if not np.any(np.isfinite(intensities)):
            raise ValueError("Spectrum does not contain finite values.")
        max_counts = float(np.nanmax(intensities))
    
        return {"max_counts": max_counts,
                "is_saturated": max_counts >= saturation_limit,
                "is_near_saturation": warning_limit < max_counts < saturation_limit}
    

    def acquire_spectrum(self):
        if self.spec is None:
            raise RuntimeError("Spectrometer is not connected.")

        self._validate_acquisition_settings()

        spectra = []

        for _ in range(self.scans_to_average):
            spectrum = np.asarray(self.spec.intensities(), dtype=float)
            self._validate_spectrum(spectrum)
            if spectra and spectrum.shape != spectra[0].shape:
                raise ValueError("Acquired spectra must have the same shape.")
            spectra.append(spectrum)
            time.sleep(self.delay)

        intensities = np.mean(spectra, axis=0)

        if self.boxcar_width > 0:
            intensities = uniform_filter1d(intensities, size=2 * self.boxcar_width + 1, mode="nearest")

        return intensities

    def _validate_acquisition_settings(self):
        if (
            isinstance(self.integration_time, bool)
            or not isinstance(self.integration_time, Real)
            or not np.isfinite(self.integration_time)
            or self.integration_time <= 0
        ):
            raise ValueError("integration_time must be a finite number greater than zero.")

        if (
            isinstance(self.scans_to_average, bool)
            or not isinstance(self.scans_to_average, Integral)
            or self.scans_to_average < 1
        ):
            raise ValueError("scans_to_average must be an integer greater than or equal to one.")

        if (
            isinstance(self.delay, bool)
            or not isinstance(self.delay, Real)
            or not np.isfinite(self.delay)
            or self.delay < 0
        ):
            raise ValueError("delay must be a finite number greater than or equal to zero.")

        if (
            isinstance(self.boxcar_width, bool)
            or not isinstance(self.boxcar_width, Integral)
            or self.boxcar_width < 0
        ):
            raise ValueError("boxcar_width must be an integer greater than or equal to zero.")

    @staticmethod
    def _validate_spectrum(spectrum):
        if spectrum.ndim != 1:
            raise ValueError("Acquired spectrum must be a one-dimensional array.")
        if spectrum.size == 0:
            raise ValueError("Acquired spectrum is empty.")
        if not np.any(np.isfinite(spectrum)):
            raise ValueError("Acquired spectrum does not contain finite values.")


    def measure(self, measurement_type):
        spectrum = self.acquire_spectrum()

        if measurement_type == "background":
            self.background = spectrum
        elif measurement_type == "reference":
            self.reference = spectrum
        elif measurement_type == "sample":
            self.sample = spectrum
        else:
            raise ValueError("measurement_type must be 'background', 'reference', or 'sample'.")

        return spectrum

    def calculate_transmission(
        self,
        sample=None,
        minimum_reference_signal=1.0,
        minimum_reference_fraction=0.01,
        clip_range=(0.0, 100.0),
    ):
        if self.background is None:
            raise RuntimeError("Background has not been measured.")

        if self.reference is None:
            raise RuntimeError("Reference has not been measured.")

        if sample is not None:
            self.sample = np.asarray(sample, dtype=float)

        if self.sample is None:
            raise RuntimeError("Sample has not been measured.")

        if not (
            self.sample.shape == self.background.shape == self.reference.shape
        ):
            raise ValueError("Background, reference and sample must have the same shape.")

        with np.errstate(divide="ignore", invalid="ignore"):
            denominator = self.reference - self.background
            transmission = np.full(self.sample.shape, np.nan, dtype=float)
            finite_signal = np.isfinite(denominator)
            if not np.any(finite_signal):
                raise RuntimeError("Reference minus background has no finite values.")

            strongest_reference = float(np.nanmax(np.abs(denominator[finite_signal])))
            reference_threshold = max(
                float(minimum_reference_signal),
                float(minimum_reference_fraction) * strongest_reference,
            )
            valid = (
                finite_signal
                & np.isfinite(self.sample)
                & np.isfinite(self.background)
                & (np.abs(denominator) >= reference_threshold)
            )
            raw_transmission = (
                (self.sample[valid] - self.background[valid]) / denominator[valid]
            ) * 100
            out_of_range = np.count_nonzero(
                (raw_transmission < clip_range[0]) | (raw_transmission > clip_range[1])
            ) if clip_range is not None else 0

            if clip_range is not None:
                raw_transmission = np.clip(raw_transmission, *clip_range)
            transmission[valid] = raw_transmission

        self.transmission_diagnostics = {
            "reference_threshold": reference_threshold,
            "valid_points": int(np.count_nonzero(valid)),
            "total_points": int(transmission.size),
            "clipped_points": int(out_of_range),
        }

        return transmission

    def acquire_transmission(self):
        """Acquire a fresh sample and calculate transmission using saved calibration."""
        sample = self.acquire_spectrum()
        return self.calculate_transmission(sample=sample)
