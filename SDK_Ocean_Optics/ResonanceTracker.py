"""Compatibility imports for the legacy spectrometer GUI."""

import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "python"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from lmrchip.spectroscopy.resonance import ResonanceResult, ResonanceTracker

__all__ = ["ResonanceResult", "ResonanceTracker"]
