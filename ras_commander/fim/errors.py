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


class FimUnsupportedError(FimError):
    """The input is outside the current engine contract."""


class FimAoiError(FimError, ValueError):
    """A bounding-box or polygon area of interest is invalid."""


class FimMappingError(FimError):
    """One or more profiles failed.

    The product manifest is still written. ``manifest`` holds the returned
    product DataFrame, so callers can inspect the profiles that completed.
    For ``map_depth_groups``, ``manifest`` contains the structured group receipt
    instead of a DataFrame; its status and partial native receipts describe the
    failed catalog.
    """

    def __init__(self, message: str, manifest=None):
        super().__init__(message)
        self.manifest = manifest
