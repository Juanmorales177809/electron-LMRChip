"""Deteccion subpixel y seguimiento de una resonancia LMR.

El modulo no depende del espectrometro ni de la interfaz grafica. Recibe dos
arrays (longitud de onda y transmitancia) y devuelve una estimacion validada
del minimo mediante un ajuste parabolico local.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ResonanceResult:
    wavelength: float = np.nan
    transmission: float = np.nan
    raw_min_wavelength: float = np.nan
    raw_min_transmission: float = np.nan
    r_squared: float = np.nan
    curvature: float = np.nan
    prominence: float = np.nan
    points_used: int = 0
    valid: bool = False
    reason: str = ""
    fit_wavelengths: Optional[np.ndarray] = None
    fit_transmission: Optional[np.ndarray] = None


class ResonanceTracker:
    """Localiza el minimo LMR y mantiene continuidad entre espectros."""

    def __init__(
        self,
        search_min_nm,
        search_max_nm,
        fit_half_window_nm=1.5,
        smoothing_window=9,
        smoothing_order=2,
        min_r_squared=0.80,
        min_prominence=0.0,
        tracking_half_window_nm=15.0,
    ):
        if search_min_nm >= search_max_nm:
            raise ValueError("search_min_nm must be smaller than search_max_nm.")
        if fit_half_window_nm <= 0:
            raise ValueError("fit_half_window_nm must be greater than zero.")

        self.search_min_nm = float(search_min_nm)
        self.search_max_nm = float(search_max_nm)
        self.fit_half_window_nm = float(fit_half_window_nm)
        self.smoothing_window = int(smoothing_window)
        self.smoothing_order = int(smoothing_order)
        self.min_r_squared = float(min_r_squared)
        self.min_prominence = float(min_prominence)
        self.tracking_half_window_nm = float(tracking_half_window_nm)
        self.previous_wavelength = None

    def reset(self):
        """Olvida la posicion anterior y fuerza una busqueda global."""
        self.previous_wavelength = None

    def update(self, wavelengths, transmission):
        wavelengths = np.asarray(wavelengths, dtype=float)
        transmission = np.asarray(transmission, dtype=float)

        if wavelengths.ndim != 1 or transmission.ndim != 1:
            return self._invalid("Wavelength and transmission must be 1-D arrays.")
        if wavelengths.size != transmission.size or wavelengths.size < 5:
            return self._invalid("Wavelength and transmission arrays are incompatible.")

        finite = np.isfinite(wavelengths) & np.isfinite(transmission)
        if self.previous_wavelength is None:
            # The configured LMR interval selects the target only on the first
            # spectrum. It does not prevent a successfully locked resonance
            # from moving beyond that initial interval later in the experiment.
            roi = finite & (wavelengths >= self.search_min_nm) & (wavelengths <= self.search_max_nm)
        else:
            roi = finite & (
                np.abs(wavelengths - self.previous_wavelength) <= self.tracking_half_window_nm
            )

        x = wavelengths[roi]
        y = transmission[roi]
        if x.size < 5:
            return self._invalid("Not enough valid points in the search interval.")

        order = np.argsort(x)
        x = x[order]
        y = y[order]
        y_smooth = self._smooth(y)

        minima = np.flatnonzero(
            (y_smooth[1:-1] < y_smooth[:-2])
            & (y_smooth[1:-1] <= y_smooth[2:])
        ) + 1
        if minima.size == 0:
            return self._invalid("No internal local minimum was found in the search interval.")

        prominences = np.asarray(
            [
                min(
                    np.max(y_smooth[: index + 1]) - y_smooth[index],
                    np.max(y_smooth[index:]) - y_smooth[index],
                )
                for index in minima
            ]
        )
        adaptive_prominence = max(
            self.min_prominence,
            0.05 * float(np.max(prominences)),
        )
        prominent = prominences >= adaptive_prominence
        minima = minima[prominent]
        prominences = prominences[prominent]
        if minima.size == 0:
            return self._invalid("No minimum has the required prominence.")

        if self.previous_wavelength is None:
            candidate_position = int(np.argmin(y_smooth[minima]))
        else:
            # Once locked, continuity is more important than absolute depth:
            # this avoids jumping to a second, deeper resonance in the window.
            candidate_position = int(
                np.argmin(np.abs(x[minima] - self.previous_wavelength))
            )

        minimum_index = int(minima[candidate_position])
        prominence = float(prominences[candidate_position])
        center = float(x[minimum_index])
        fit_selection = np.abs(x - center) <= self.fit_half_window_nm
        fit_x = x[fit_selection]
        fit_y = y_smooth[fit_selection]

        if (
            fit_x.size < 5
            or np.count_nonzero(fit_x < center) < 2
            or np.count_nonzero(fit_x > center) < 2
        ):
            return self._invalid(
                "The fit radius contains fewer than two points on each side of the minimum."
            )

        try:
            a, b, c = np.polyfit(fit_x - center, fit_y, 2)
        except (ValueError, np.linalg.LinAlgError) as error:
            return self._invalid(f"Quadratic fit failed: {error}")

        if not np.isfinite(a) or a <= 0:
            return self._invalid("The fitted curve does not have a minimum.")

        vertex_offset = -b / (2.0 * a)
        resonance_wavelength = center + vertex_offset
        resonance_transmission = a * vertex_offset**2 + b * vertex_offset + c

        if not (fit_x[0] <= resonance_wavelength <= fit_x[-1]):
            return self._invalid("The fitted vertex lies outside the local fit window.")

        fitted_at_samples = np.polyval((a, b, c), fit_x - center)
        residual_sum = float(np.sum((fit_y - fitted_at_samples) ** 2))
        total_sum = float(np.sum((fit_y - np.mean(fit_y)) ** 2))
        r_squared = 1.0 - residual_sum / total_sum if total_sum > 0 else 0.0

        if r_squared < self.min_r_squared:
            return self._invalid(
                f"Quadratic fit quality is too low (R2={r_squared:.3f})."
            )

        dense_x = np.linspace(fit_x[0], fit_x[-1], 150)
        dense_y = np.polyval((a, b, c), dense_x - center)
        self.previous_wavelength = float(resonance_wavelength)

        return ResonanceResult(
            wavelength=float(resonance_wavelength),
            transmission=float(resonance_transmission),
            raw_min_wavelength=float(x[minimum_index]),
            raw_min_transmission=float(y[minimum_index]),
            r_squared=float(r_squared),
            curvature=float(a),
            prominence=prominence,
            points_used=int(fit_x.size),
            valid=True,
            reason="OK",
            fit_wavelengths=dense_x,
            fit_transmission=dense_y,
        )

    def _smooth(self, values):
        window = min(self.smoothing_window, values.size)
        if window % 2 == 0:
            window -= 1
        minimum_window = self.smoothing_order + 2
        if minimum_window % 2 == 0:
            minimum_window += 1
        if window < minimum_window or window < 3:
            return values.copy()
        # Savitzky-Golay smoothing coefficients calculated with NumPy.  This
        # keeps the tracking module independent from SciPy and preserves the
        # local position/curvature better than a simple moving average.
        half_window = window // 2
        positions = np.arange(-half_window, half_window + 1, dtype=float)
        design = np.vander(positions, N=self.smoothing_order + 1, increasing=True)
        coefficients = np.linalg.pinv(design)[0]
        padded = np.pad(values, half_window, mode="edge")
        return np.convolve(padded, coefficients[::-1], mode="valid")

    @staticmethod
    def _invalid(reason):
        return ResonanceResult(valid=False, reason=reason)
