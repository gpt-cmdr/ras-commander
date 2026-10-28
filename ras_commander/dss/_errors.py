"""Typed DSS exceptions shared by every ``RasDss`` backend (decision D32).

The four base classes are the ``dss_commander`` exceptions once that optional
package has been imported (the native and shadow backends import it before they
read), so the native backend raises them unchanged. Otherwise they are local
classes with the same names and bases. This module never imports
``dss_commander`` itself: the Java backend does not load the native engine, and a
missing or broken native wheel cannot affect it.

``RasDss`` adds subclasses where an existing method, or the condition itself,
already maps to a builtin. Each keeps that builtin as a base, so existing handlers
keep working:

=============================  ================================================  =====================
Class                          Bases                                             Raised when
=============================  ================================================  =====================
``DssError``                   ``RuntimeError``                                  Any other DSS failure
``DssFormatError``             ``DssError``                                      Damaged or non-DSS file
``DssUnsupportedRecordError``  ``DssError``                                      Record kind/encoding not read
``DssPathnameNotFoundError``   ``DssError``, ``ValueError``                      No record / no data
``DssRecordTypeError``         ``DssUnsupportedRecordError``, ``TypeError``      Record exists but is another kind
``DssInvalidFileError``        ``DssFormatError``, ``ValueError``                File is not DSS6/DSS7
``DssReadError``               ``DssFormatError``                                Record exists but could not be read
``DssCapabilityError``         ``DssError``, ``NotImplementedError``             Backend does not (yet) support it
=============================  ================================================  =====================

Resolution happens on each use. Within a process the classes change at most once:
from the local set to the ``dss_commander`` set when the native engine is first
imported. A process that uses only one backend always sees one set. Catch the
builtin bases (``ValueError``, ``TypeError``, ``RuntimeError``) when code must work
across a backend switch.
"""

from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace
from typing import Dict, Optional

__all__ = ["ERROR_NAMES", "classes", "get"]

#: Public exception names, in documentation order.
ERROR_NAMES = (
    "DssError",
    "DssFormatError",
    "DssUnsupportedRecordError",
    "DssPathnameNotFoundError",
    "DssRecordTypeError",
    "DssInvalidFileError",
    "DssReadError",
    "DssCapabilityError",
)

_BASE_NAMES = ERROR_NAMES[:4]

_lock = threading.Lock()
#: Built class sets: key "local" or "native".
_cache: Dict[str, SimpleNamespace] = {}


def _local_bases() -> SimpleNamespace:
    """Base classes used when ``dss_commander`` has not been imported."""

    class DssError(RuntimeError):
        """Base class for every DSS error raised by ``RasDss``."""

    class DssFormatError(DssError):
        """The file is not a DSS6/DSS7 file, or a structure in it is damaged."""

    class DssUnsupportedRecordError(DssError):
        """The record exists but its kind or encoding is not read by this call."""

    class DssPathnameNotFoundError(DssError, ValueError):
        """No record, or no data, for the requested pathname."""

    base = SimpleNamespace(
        DssError=DssError,
        DssFormatError=DssFormatError,
        DssUnsupportedRecordError=DssUnsupportedRecordError,
        DssPathnameNotFoundError=DssPathnameNotFoundError,
    )
    for name in _BASE_NAMES:
        cls = getattr(base, name)
        cls.__module__ = "ras_commander.dss"
        cls.__qualname__ = name
    return base


def _native_bases(dc: Optional[ModuleType]) -> Optional[SimpleNamespace]:
    """The four base classes of an imported ``dss_commander``, or None if unusable."""
    if dc is None:
        return None
    try:
        base = SimpleNamespace(**{name: getattr(dc, name) for name in _BASE_NAMES})
    except Exception:  # a broken or partial native package must not break RasDss
        return None
    if not all(isinstance(getattr(base, n), type) and issubclass(getattr(base, n), Exception)
               for n in _BASE_NAMES):
        return None
    return base


def _build(dc: Optional[ModuleType]) -> SimpleNamespace:
    """All classes on the ``dss_commander`` bases (when usable) or local bases."""
    base = _native_bases(dc) or _local_bases()

    class DssRecordTypeError(base.DssUnsupportedRecordError, TypeError):
        """The record exists but is not the kind this call reads (for example a time
        series passed to ``read_grid``). Also a ``TypeError``, which ``read_grid``
        raised for this condition before typed errors existed."""

    class DssInvalidFileError(base.DssFormatError, ValueError):
        """The file is not a DSS6 or DSS7 database. Also a ``ValueError``, which
        ``get_file_version`` raised for this condition before typed errors existed."""

    class DssReadError(base.DssFormatError):
        """The record exists but the backend failed to read it (the cause is
        chained)."""

    class DssCapabilityError(base.DssError, NotImplementedError):
        """The selected backend does not support, or has not qualified, this
        operation. Never answered by silently using another backend."""

    for cls in (DssRecordTypeError, DssInvalidFileError, DssReadError, DssCapabilityError):
        cls.__module__ = "ras_commander.dss"
        cls.__qualname__ = cls.__name__
        setattr(base, cls.__name__, cls)
    return base


def classes() -> SimpleNamespace:
    """All exception classes for the current process state (never imports)."""
    dc = sys.modules.get("dss_commander")
    key = "native" if _native_bases(dc) is not None else "local"
    built = _cache.get(key)
    if built is None:
        with _lock:
            built = _cache.get(key)
            if built is None:
                built = _build(dc if key == "native" else None)
                _cache[key] = built
    return built


def get(name: str) -> type:
    """One exception class by name."""
    if name not in ERROR_NAMES:
        raise AttributeError(name)
    return getattr(classes(), name)
