import sys
import unittest
from pathlib import Path

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.spectroscopy.resonance import ResonanceTracker


class ResonanceTrackerTests(unittest.TestCase):
    def test_parabolic_resonance_result_is_numerically_stable(self):
        wavelengths = np.linspace(650.0, 750.0, 2001)
        transmission = 20.0 + 0.2 * (wavelengths - 702.35) ** 2
        tracker = ResonanceTracker(
            680.0,
            720.0,
            fit_half_window_nm=2.0,
            smoothing_window=1,
        )

        result = tracker.update(wavelengths, transmission)

        self.assertTrue(result.valid, result.reason)
        self.assertAlmostEqual(result.wavelength, 702.35, delta=1e-10)
        self.assertAlmostEqual(result.transmission, 20.0, delta=1e-10)

    def test_invalid_frame_keeps_last_valid_tracking_position(self):
        wavelengths = np.linspace(650.0, 750.0, 2001)
        transmission = 20.0 + 0.2 * (wavelengths - 702.35) ** 2
        tracker = ResonanceTracker(
            680.0,
            720.0,
            fit_half_window_nm=2.0,
            smoothing_window=1,
        )
        valid = tracker.update(wavelengths, transmission)
        previous = tracker.previous_wavelength

        invalid = tracker.update(wavelengths, np.full_like(wavelengths, np.nan))

        self.assertTrue(valid.valid)
        self.assertFalse(invalid.valid)
        self.assertEqual(tracker.previous_wavelength, previous)

    def test_isolated_nan_does_not_prevent_tracking(self):
        wavelengths = np.linspace(650.0, 750.0, 2001)
        transmission = 20.0 + 0.2 * (wavelengths - 702.35) ** 2
        transmission[100] = np.nan
        tracker = ResonanceTracker(
            680.0,
            720.0,
            fit_half_window_nm=2.0,
            smoothing_window=1,
        )

        result = tracker.update(wavelengths, transmission)

        self.assertTrue(result.valid, result.reason)
        self.assertAlmostEqual(result.wavelength, 702.35, delta=1e-10)


if __name__ == "__main__":
    unittest.main()
