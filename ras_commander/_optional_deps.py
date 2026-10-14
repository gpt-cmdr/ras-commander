"""Deferred imports for optional dependencies.

The core ``ras-commander`` install has only h5py, numpy, and pandas, and the
``compute`` extra adds only process-supervision packages. Modules that also
offer xarray- or GeoDataFrame-returning functions bind the optional package to
a module-level proxy from :func:`optional_module`. The module then imports
without the package, and the first attribute access on the proxy raises an
``ImportError`` that names the exact install command.

Modules that use a proxy must also use ``from __future__ import annotations``
so that return annotations such as ``xr.DataArray`` are not evaluated when the
module is imported.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, Optional

FULL_EXTRA_HINT = 'pip install "ras-commander[full]"'

_PIP_NAMES = {
    "geopandas": "geopandas",
    "shapely": "shapely",
    "xarray": "xarray",
}


class OptionalDependencyError(ImportError):
    """An optional package needed by the requested API is not installed."""


def missing_dependency_message(module_name: str, purpose: str) -> str:
    """Return the installation guidance for a missing optional package."""
    package = module_name.split(".", 1)[0]
    pip_name = _PIP_NAMES.get(package, package)
    return (
        f"{purpose} requires the '{package}' package, which the core and "
        "'compute' ras-commander installs do not include. "
        f"Install it with: {FULL_EXTRA_HINT} (or: pip install {pip_name})"
    )


def require_module(module_name: str, purpose: str) -> ModuleType:
    """Import ``module_name`` or raise an actionable ``ImportError``."""
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise OptionalDependencyError(
            missing_dependency_message(module_name, purpose)
        ) from exc


class _OptionalModule:
    """Module proxy that imports its target on first attribute access."""

    __slots__ = ("_module_name", "_purpose", "_module")

    def __init__(self, module_name: str, purpose: str) -> None:
        object.__setattr__(self, "_module_name", module_name)
        object.__setattr__(self, "_purpose", purpose)
        object.__setattr__(self, "_module", None)

    def _load(self) -> ModuleType:
        module: Optional[ModuleType] = object.__getattribute__(self, "_module")
        if module is None:
            module = require_module(
                object.__getattribute__(self, "_module_name"),
                object.__getattribute__(self, "_purpose"),
            )
            object.__setattr__(self, "_module", module)
        return module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __repr__(self) -> str:
        name = object.__getattribute__(self, "_module_name")
        return f"<optional module {name!r}>"


def optional_module(module_name: str, purpose: str) -> Any:
    """Return a proxy that imports ``module_name`` when first used."""
    return _OptionalModule(module_name, purpose)
