"""Federal model source integrations."""

import warnings

from .ebfe_models import RasEbfeModels


def __getattr__(name):
    if name == "CoastalBoundary":
        warnings.warn(
            "Importing CoastalBoundary from ras_commander.sources.federal is "
            "deprecated. Use ras_commander.boundaries instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from ras_commander.boundaries import CoastalBoundary

        return CoastalBoundary
    raise AttributeError(f"module 'ras_commander.sources.federal' has no attribute {name!r}")


__all__ = ['RasEbfeModels']
