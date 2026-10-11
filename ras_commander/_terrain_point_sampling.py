"""Strict native sampling of supplied coordinates, without profile interpolation."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path

import numpy as np


def _point_elevation_batches(
    batches: Iterable[np.ndarray],
    evaluate: Callable[[np.ndarray], Sequence[float] | None],
    nodata_values: Sequence[float],
) -> Iterator[np.ndarray]:
    """Validate each bounded input/output batch; never substitute missing values."""
    sentinels = np.asarray(
        [*nodata_values, -np.finfo(np.float32).max, np.finfo(np.float32).max]
    )
    for batch in batches:
        coordinates = np.asarray(batch)
        if (
            coordinates.dtype != np.dtype("float64")
            or coordinates.ndim != 2
            or coordinates.shape[1] != 2
        ):
            raise ValueError("Point batches must be binary64 arrays with shape (n, 2)")
        if not len(coordinates) or not np.isfinite(coordinates).all():
            raise ValueError("Point batches must contain finite coordinates")
        coordinates = coordinates.copy()
        parts = []
        for offset in range(0, len(coordinates), 4096):
            subset = coordinates[offset : offset + 4096]
            parts.append(_checked_native_values(subset, evaluate, sentinels))
        yield np.concatenate(parts)


def _checked_native_values(
    coordinates: np.ndarray,
    evaluate: Callable[[np.ndarray], Sequence[float] | None],
    sentinels: np.ndarray,
) -> np.ndarray:
    """Reject an incomplete or invalid native call before assembling its batch."""
    values = evaluate(coordinates)
    if values is None or len(values) != len(coordinates):
        raise RuntimeError(
            "Native point sampling returned missing or incomplete values"
        )
    elevations = np.asarray(values, dtype=np.float32)
    if elevations.shape != (len(coordinates),):
        raise RuntimeError("Native point sampling changed output cardinality")
    if not np.isfinite(elevations).all() or np.isin(elevations, sentinels).any():
        raise RuntimeError(
            "Native point sampling returned invalid or nodata elevations"
        )
    return elevations


def _load_native_point_reader(
    mapper: Path, terrain_name: str, use_obstructions: bool, cell_size: float
):
    """Load one selected native layer and bind its public point-array overload."""
    from .terrain.RasTerrainMod import RasTerrainMod

    RasTerrainMod._ensure_initialized()
    if RasTerrainMod._ras_path.name != "6.6":
        raise RuntimeError(
            "Explicit native point sampling requires an isolated HEC-RAS 6.6 runtime"
        )
    import clr
    from RasMapperLib import PointM, RASMapperCom, SharedData, TerrainLayer
    from System import Array
    from System.Xml import XmlDocument

    kind = clr.GetClrType(TerrainLayer)
    methods = [m for m in kind.GetMethods() if str(m.Name) == "ComputePointElevations"]
    expected = ["RasMapperLib.PointM[]", "System.Boolean", "System.Double"]
    selected = [
        m
        for m in methods
        if [str(p.ParameterType) for p in m.GetParameters()] == expected
    ]
    if len(selected) != 1 or str(selected[0].ReturnType) != "System.Single[]":
        raise RuntimeError("The qualified native point-array contract changed")
    if [str(p.Name) for p in selected[0].GetParameters()] != [
        "points",
        "useObstructions",
        "cellSize",
    ]:
        raise RuntimeError(
            "The qualified native point-array parameter semantics changed"
        )
    document = XmlDocument()
    document.Load(str(mapper))
    SharedData.RasMapFilename = str(mapper)
    SharedData.SRSFilename = RASMapperCom.GetSRSFromRasmapDoc(document, str(mapper))
    units = document.SelectSingleNode("/RASMapper/Units")
    if units is not None and str(units.InnerText).strip():
        SharedData.SetUnitsSystem(str(units.InnerText).strip())
    layers = [
        node
        for node in document.SelectNodes("/RASMapper/Terrains/Layer")
        if str(node.GetAttribute("Name")) == terrain_name
    ]
    if len(layers) != 1:
        raise ValueError("Exactly one registered terrain must match terrain_name")
    terrain = TerrainLayer(terrain_name)
    terrain.XMLLoad(layers[0])
    terrain.ResampleMethod = "near"

    def evaluate(coordinates: np.ndarray) -> list[float] | None:
        extent = terrain.Extent
        if np.any(
            (coordinates[:, 0] < extent.MinX)
            | (coordinates[:, 0] > extent.MaxX)
            | (coordinates[:, 1] < extent.MinY)
            | (coordinates[:, 1] > extent.MaxY)
        ):
            raise ValueError(
                "Supplied points lie outside the selected native terrain extent"
            )
        points = Array[PointM]([PointM(float(x), float(y)) for x, y in coordinates])
        native_coordinates = np.asarray(
            [[float(p.X), float(p.Y)] for p in points], dtype=np.float64
        )
        if native_coordinates.tobytes() != coordinates.tobytes():
            raise RuntimeError(
                "Native points did not preserve the supplied binary64 coordinates"
            )
        values = terrain.ComputePointElevations(points, use_obstructions, cell_size)
        return None if values is None else [float(value) for value in values]

    return evaluate


def iter_point_elevations(
    mapper: Path,
    terrain_name: str,
    batches: Iterable[np.ndarray],
    cell_size: float,
    use_obstructions: bool,
    nodata_values: Sequence[float],
) -> Iterator[np.ndarray]:
    """Load one native layer; preserve batches with serial native calls of <=4096."""
    if not mapper.is_file():
        raise FileNotFoundError(mapper)
    if not terrain_name or not isinstance(use_obstructions, bool):
        raise ValueError(
            "A registered terrain name and Boolean use_obstructions are required"
        )
    if not np.isfinite(cell_size) or cell_size <= 0:
        raise ValueError(
            "cell_size must be finite and positive in the terrain CRS units"
        )
    evaluate = _load_native_point_reader(
        mapper.resolve(), terrain_name, use_obstructions, float(cell_size)
    )
    yield from _point_elevation_batches(batches, evaluate, nodata_values)
