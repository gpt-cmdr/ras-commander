"""Deferred imports for optional dependencies.

The core ``ras-commander`` install has only h5py, numpy, and pandas, and the
``compute`` extra adds only process-supervision packages (psutil, and pywin32
on Windows). The package's lazy exports import their modules through
:func:`import_feature_module`, so a missing optional package surfaces as an
``ImportError`` that names the extra to install. Modules that also
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
COMPUTE_EXTRA_HINT = 'pip install "ras-commander[compute]"'

# Import name -> pip distribution name, where the two differ.
_PIP_NAMES = {
    "win32api": "pywin32",
    "win32com": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32process": "pywin32",
    "win32ui": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "yaml": "pyyaml",
    "PIL": "Pillow",
}

# Packages supplied by the ``compute`` extra. Every other optional package is
# in ``full``.
_COMPUTE_PACKAGES = {"psutil", "pywin32"}


class OptionalDependencyError(ImportError):
    """An optional package needed by the requested API is not installed."""


def missing_dependency_message(module_name: str, purpose: str) -> str:
    """Return the installation guidance for a missing optional package."""
    package = module_name.split(".", 1)[0]
    pip_name = _PIP_NAMES.get(package, package)
    if pip_name in _COMPUTE_PACKAGES:
        return (
            f"{purpose} requires the '{package}' package, which the core "
            "ras-commander install does not include. "
            f"Install it with: {COMPUTE_EXTRA_HINT} (or: pip install {pip_name})"
        )
    return (
        f"{purpose} requires the '{package}' package, which the core and "
        "'compute' ras-commander installs do not include. "
        f"Install it with: {FULL_EXTRA_HINT} (or: pip install {pip_name})"
    )


def _missing_top_level_name(exc: ModuleNotFoundError) -> Optional[str]:
    """Return the top-level package an import failed to find, if known."""
    name = exc.name
    if not name:
        # Some import hooks raise without setting ``name``; fall back to the
        # standard "No module named 'x'" message.
        text = str(exc)
        if "No module named " in text:
            name = text.split("No module named ", 1)[1].strip().strip("'\"")
    return name.split(".", 1)[0] if name else None


def import_feature_module(module_name: str, package: Optional[str], purpose: str) -> ModuleType:
    """Import a ras-commander module, translating a missing optional package.

    A missing third-party package raises :class:`OptionalDependencyError` that
    names the extra to install. A missing ``ras_commander`` module is a
    packaging defect and is re-raised unchanged.
    """
    try:
        return importlib.import_module(module_name, package)
    except OptionalDependencyError:
        raise
    except ModuleNotFoundError as exc:
        missing = _missing_top_level_name(exc)
        if missing is None or missing == "ras_commander":
            raise
        raise OptionalDependencyError(
            missing_dependency_message(missing, purpose)
        ) from exc


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
