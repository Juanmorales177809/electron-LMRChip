"""PR-59 temperature controller integration."""

from importlib import import_module

__all__ = ["PR59Controller"]


def __getattr__(name):
    if name == "PR59Controller":
        return getattr(import_module(".controller", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
