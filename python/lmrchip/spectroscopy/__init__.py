"""Spectrometer acquisition and LMR resonance tracking."""

from importlib import import_module


__all__ = ["ResonanceResult", "ResonanceTracker", "Spectrometer"]


def __getattr__(name):
    if name in ("ResonanceResult", "ResonanceTracker"):
        return getattr(import_module(".resonance", __name__), name)
    if name == "Spectrometer":
        return getattr(import_module(".spectrometer", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
