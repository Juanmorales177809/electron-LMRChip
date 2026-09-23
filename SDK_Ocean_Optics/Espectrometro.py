import time
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

    def connect(self):
        print("Searching spectrometers...")
        devices = spectrometers.list_devices()
        print(f"Devices found: {devices}")

        if not devices:
            raise RuntimeError("No spectrometer detected.")

        self.spec = spectrometers.Spectrometer(devices[0])
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

        spectra = []

        for _ in range(self.scans_to_average):
            spectra.append(self.spec.intensities())
            time.sleep(self.delay)

        intensities = np.mean(spectra, axis=0)

        if self.boxcar_width > 0:
            intensities = uniform_filter1d(intensities, size=2 * self.boxcar_width + 1, mode="nearest")

        return intensities


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
