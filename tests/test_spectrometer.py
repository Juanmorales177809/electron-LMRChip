import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def _uniform_filter_nearest(values, size, mode):
    if mode != "nearest":
        raise AssertionError("The production code changed its boxcar boundary mode.")
    half_width = size // 2
    padded = np.pad(values, half_width, mode="edge")
    return np.convolve(padded, np.ones(size) / size, mode="valid")


fake_seabreeze = ModuleType("seabreeze")
fake_seabreeze.use = lambda backend: None
fake_spectrometers = ModuleType("seabreeze.spectrometers")
fake_spectrometers.list_devices = lambda: []
fake_seabreeze.spectrometers = fake_spectrometers
fake_scipy = ModuleType("scipy")
fake_ndimage = ModuleType("scipy.ndimage")
fake_ndimage.uniform_filter1d = _uniform_filter_nearest

sys.modules.setdefault("seabreeze", fake_seabreeze)
sys.modules.setdefault("seabreeze.spectrometers", fake_spectrometers)
sys.modules.setdefault("scipy", fake_scipy)
sys.modules.setdefault("scipy.ndimage", fake_ndimage)

from lmrchip.spectroscopy.spectrometer import Spectrometer


class FakeDevice:
    def __init__(self, spectra):
        self.spectra = iter(spectra)
        self.read_count = 0

    def intensities(self):
        self.read_count += 1
        return next(self.spectra)


class SpectrometerTests(unittest.TestCase):
    def test_defaults_are_preserved(self):
        optical = Spectrometer()

        self.assertEqual(optical.integration_time, 100)
        self.assertEqual(optical.scans_to_average, 1)
        self.assertEqual(optical.delay, 0.0)
        self.assertEqual(optical.boxcar_width, 0)

    def test_acquisition_preserves_average_and_number_of_reads(self):
        optical = Spectrometer(scans_to_average=2, delay=0.25)
        optical.spec = FakeDevice([[1.0, 3.0, 5.0], [3.0, 5.0, 7.0]])

        with patch("lmrchip.spectroscopy.spectrometer.time.sleep") as sleep:
            result = optical.acquire_spectrum()

        np.testing.assert_allclose(result, [2.0, 4.0, 6.0], rtol=0, atol=1e-10)
        self.assertEqual(optical.spec.read_count, 2)
        self.assertEqual(sleep.call_count, 2)
        sleep.assert_called_with(0.25)

    def test_boxcar_preserves_existing_nearest_edge_behavior(self):
        optical = Spectrometer(boxcar_width=1)
        optical.spec = FakeDevice([[0.0, 3.0, 6.0]])

        with patch("lmrchip.spectroscopy.spectrometer.time.sleep"):
            result = optical.acquire_spectrum()

        np.testing.assert_allclose(result, [1.0, 3.0, 5.0], rtol=0, atol=1e-10)

    def test_transmission_formula_and_clipping_are_preserved(self):
        optical = Spectrometer()
        optical.background = np.array([10.0, 10.0, 10.0, 10.0])
        optical.reference = np.array([110.0, 110.0, 10.1, 110.0])
        optical.sample = np.array([60.0, 130.0, 10.05, 0.0])

        result = optical.calculate_transmission()

        np.testing.assert_allclose(
            result[[0, 1, 3]], [50.0, 100.0, 0.0], rtol=0, atol=1e-10
        )
        self.assertTrue(np.isnan(result[2]))
        self.assertEqual(optical.transmission_diagnostics["clipped_points"], 2)

    def test_rejects_invalid_settings_at_construction(self):
        invalid_settings = (
            {"integration_time": 0},
            {"integration_time": np.nan},
            {"scans_to_average": 0},
            {"scans_to_average": 1.5},
            {"delay": -0.1},
            {"delay": np.inf},
            {"boxcar_width": -1},
            {"boxcar_width": 1.5},
        )

        for settings in invalid_settings:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                Spectrometer(**settings)

    def test_revalidates_settings_changed_after_construction(self):
        optical = Spectrometer()
        optical.spec = FakeDevice([[1.0]])
        optical.scans_to_average = 0

        with self.assertRaisesRegex(ValueError, "scans_to_average"):
            optical.acquire_spectrum()

        self.assertEqual(optical.spec.read_count, 0)

    def test_rejects_empty_multidimensional_and_all_nonfinite_spectra(self):
        invalid_spectra = (
            np.array([]),
            np.array([[1.0, 2.0]]),
            np.array([np.nan, np.inf]),
        )

        for spectrum in invalid_spectra:
            with self.subTest(spectrum=spectrum):
                optical = Spectrometer()
                optical.spec = FakeDevice([spectrum])
                with self.assertRaises(ValueError):
                    optical.acquire_spectrum()

    def test_allows_isolated_nonfinite_points(self):
        optical = Spectrometer()
        optical.spec = FakeDevice([[1.0, np.nan, 3.0]])

        with patch("lmrchip.spectroscopy.spectrometer.time.sleep"):
            result = optical.acquire_spectrum()

        self.assertEqual(result[0], 1.0)
        self.assertTrue(np.isnan(result[1]))
        self.assertEqual(result[2], 3.0)

    def test_different_scan_shapes_fail_without_retry(self):
        optical = Spectrometer(scans_to_average=2)
        optical.spec = FakeDevice([[1.0, 2.0], [1.0, 2.0, 3.0]])

        with patch("lmrchip.spectroscopy.spectrometer.time.sleep"), self.assertRaisesRegex(
            ValueError, "same shape"
        ):
            optical.acquire_spectrum()

        self.assertEqual(optical.spec.read_count, 2)


if __name__ == "__main__":
    unittest.main()
