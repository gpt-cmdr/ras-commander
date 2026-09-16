"""Shared managed-assembly bootstrap for RasMapperLib interop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Union

from .LoggingConfig import get_logger

logger = get_logger(__name__)

# RasMapperLib exposes a large, mutually-referential type graph.  Python.NET's
# lazy reflection can become unstable when RasMapperLib is loaded before its
# local managed dependencies, especially under Wine/.NET Framework.  Keep the
# dependency order explicit and load RasMapperLib last.
RAS_MAPPER_MANAGED_DEPENDENCIES: tuple[str, ...] = (
    "Utility.Core",
    "Geospatial.Core",
    "H5Assist",
    "ZeroFormatter.Interfaces",
    "ZeroFormatter",
    "clipper_library",
    "HDF.PInvoke",
    "Geospatial.GDALAssist",
    "Geospatial.IO",
    "Geospatial.Rendering",
    "Hec.Dss",
    "OxyPlot",
    "OxyPlot.WindowsForms",
    "TiffAssist",
    "System.Data.SQLite",
    "PipeClient",
    "TiffBinaryReader",
    "Newtonsoft.Json",
    "SharpDX",
    "SharpDX.DXGI",
    "SharpDX.Direct2D1",
    "ParticleTracking",
    "RasMapperLib",
)

_REQUIRED_BASE_DEPENDENCIES = frozenset(
    {"Utility.Core", "Geospatial.Core", "H5Assist", "RasMapperLib"}
)


def load_rasmapper_assemblies(
    hecras_dir: Union[str, Path],
    add_reference: Callable[[str], Any],
) -> tuple[Path, ...]:
    """Load available HEC-RAS managed assemblies in a stable order.

    Older supported HEC-RAS installations do not necessarily ship every
    assembly in the 7.0.1 dependency graph, so absent non-core assemblies are
    skipped.  If an assembly is present but cannot be loaded, fail immediately
    rather than allowing a partially bound RasMapperLib type graph to crash or
    hang later during reflection.
    """
    root = Path(hecras_dir)
    loaded: list[Path] = []

    for dependency in RAS_MAPPER_MANAGED_DEPENDENCIES:
        dll_path = root / f"{dependency}.dll"
        if not dll_path.exists():
            if dependency in _REQUIRED_BASE_DEPENDENCIES:
                raise FileNotFoundError(
                    f"Required HEC-RAS assembly not found: {dll_path}"
                )
            logger.debug(
                "HEC-RAS assembly %s is not present in this installation; "
                "skipping it",
                dll_path.name,
            )
            continue

        try:
            add_reference(str(dll_path))
        except Exception as exc:
            raise RuntimeError(f"Cannot load {dll_path}: {exc}") from exc
        loaded.append(dll_path)

    return tuple(loaded)
