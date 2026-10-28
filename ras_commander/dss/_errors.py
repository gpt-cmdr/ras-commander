"""Typed DSS exceptions shared by every ``RasDss`` backend (decision D32).

The four base classes are the ``dss_commander`` exceptions when that optional package
is installed, so the native backend raises them unchanged. Without ``dss_commander``
they are local classes with the same names and bases. Either way, the Java and native
backends of the methods that use them raise the same classes.

``RasDss`` adds three subclasses where an existing method, or the condition itself,
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
``DssCapabilityError``         ``DssError``, ``NotImplementedError``             Backend does not (yet) support it
=============================  ================================================  =====================

The classes are resolved once per process, on first use; install or remove
``dss_commander`` before the first DSS call, not during a session.
"""

from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace
from typing import Optional

__all__ = ["ERROR_NAMES", "classes", "get"]

#: Public exception names, in documentation order.
ERROR_NAMES = (
    "DssError",
    "DssFormatError",
    "DssUnsupportedRecordError",
    "DssPathnameNotFoundError",
    "DssRecordTypeError",
    "DssInvalidFileError",
    "DssCapabilityError",
)

_lock = threading.Lock()
_classes: Optional[SimpleNamespace] = None


def _local_bases() -> SimpleNamespace:
    """Fallback base classes, used only when ``dss_commander`` is not installed."""

    class DssError(RuntimeError):
        """Base class for every DSS error raised by ``RasDss``."""

    class DssFormatError(DssError):
        """The file is not a DSS6/DSS7 file, or a structure in it is damaged."""

    class DssUnsupportedRecordError(DssError):
        """The record exists but its kind or encoding is not read by this call."""

    class DssPathnameNotFoundError(DssError, ValueError):
        """No record, or no data, for the requested pathname."""

    for cls in (DssError, DssFormatError, DssUnsupportedRecordError, DssPathnameNotFoundError):
        cls.__module__ = "ras_commander.dss"
        cls.__qualname__ = cls.__name__
    return SimpleNamespace(
        DssError=DssError,
        DssFormatError=DssFormatError,
        DssUnsupportedRecordError=DssUnsupportedRecordError,
        DssPathnameNotFoundError=DssPathnameNotFoundError,
    )


def _build() -> SimpleNamespace:
    try:
        dc = importlib.import_module("dss_commander")
        base = SimpleNamespace(
            DssError=dc.DssError,
            DssFormatError=dc.DssFormatError,
            DssUnsupportedRecordError=dc.DssUnsupportedRecordError,
            DssPathnameNotFoundError=dc.DssPathnameNotFoundError,
        )
    except (ImportError, AttributeError):
        base = _local_bases()

    class DssRecordTypeError(base.DssUnsupportedRecordError, TypeError):
        """The record exists but is not the kind this call reads (for example a time
        series passed to ``read_grid``). Also a ``TypeError``, which ``read_grid``
        raised for this condition before typed errors existed."""

    class DssInvalidFileError(base.DssFormatError, ValueError):
        """The file is not a DSS6 or DSS7 database. Also a ``ValueError``, which
        ``get_file_version`` raised for this condition before typed errors existed."""

    class DssCapabilityError(base.DssError, NotImplementedError):
        """The selected backend does not support, or has not qualified, this
        operation. Never answered by silently using another backend."""

    for cls in (DssRecordTypeError, DssInvalidFileError, DssCapabilityError):
        cls.__module__ = "ras_commander.dss"
        cls.__qualname__ = cls.__name__
    base.DssRecordTypeError = DssRecordTypeError
    base.DssInvalidFileError = DssInvalidFileError
    base.DssCapabilityError = DssCapabilityError
    return base


def classes() -> SimpleNamespace:
    """All exception classes (resolved once per process)."""
    global _classes
    if _classes is None:
        with _lock:
            if _classes is None:
                _classes = _build()
    return _classes


def get(name: str) -> type:
    """One exception class by name."""
    if name not in ERROR_NAMES:
        raise AttributeError(name)
    return getattr(classes(), name)
