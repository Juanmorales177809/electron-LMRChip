"""GRBL and microfluidic machine control."""

from importlib import import_module

__all__ = ["GrblController", "MicrofluidicMachine"]


def __getattr__(name):
    if name == "GrblController":
        return getattr(import_module(".controller", __name__), name)
    if name == "MicrofluidicMachine":
        return getattr(import_module(".machine", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
