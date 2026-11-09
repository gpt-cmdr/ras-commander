"""Exception types for the optional FIM mapping engine (:mod:`ras_commander.fim`)."""

from __future__ import annotations


class FimError(RuntimeError):
    """Base class for FIM mapping errors."""


class FimEngineNotFoundError(FimError, FileNotFoundError):
    """The ``ras2fim-batch`` engine executable could not be found or run.

    RAS Commander never builds, downloads, or installs the engine, and it
    has no Python fallback for the mapping arithmetic.
    """


class FimEngineError(FimError):
    """The engine rejected a request, crashed, or wrote inconsistent output."""


class FimGeometryError(FimEngineError, ValueError):
    """Geometry delivery refused, optionally with retained raw diagnostics.

    Raw artifacts do not represent repaired or qualified vector products.
    ``diagnostic_manifest`` identifies the aborted diagnostic receipt;
    ``artifacts`` lists retained paths and ``validity_reason`` records the
    independent topology-validation refusal.
    """

    def __init__(self, message: str, *, diagnostic_manifest=None, artifacts=None,
                 validity_reason=None):
        super().__init__(message)
        self.diagnostic_manifest = diagnostic_manifest
        self.artifacts = tuple(artifacts or ())
        self.validity_reason = validity_reason


class FimUnsupportedError(FimError):
    """The input is outside the current engine contract."""


class FimAoiError(FimError, ValueError):
    """A bounding-box or polygon area of interest is invalid."""


class FimMappingError(FimError):
    """One or more profiles failed.

    The product manifest is still written. ``manifest`` holds the returned
    product DataFrame, so callers can inspect the profiles that completed.
    """

    def __init__(self, message: str, manifest=None):
        super().__init__(message)
        self.manifest = manifest
