"""Native RASMapper classification-polygon editing for HEC-RAS 6.x and 7.0.x.

The classification-polygon datasets are owned by HEC-RAS.  This module uses
``LandCoverLayer`` and its nested ``PolygonFeatureLayer`` so that RasMapperLib,
not ras-commander, defines and serializes the HDF schema.
"""

from __future__ import annotations

import math
import re
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Union
from uuid import uuid4

import h5py

from .dotnet.clr_bootstrap import find_hecras_install, load_clr
from .RasUtils import RasUtils

_VARIABLE_VALUE_ALIASES = {
    "mannings_n": "ManningsN",
    "manning_n": "ManningsN",
    "manningsn": "ManningsN",
    "percent_impervious": "Percent Impervious",
    "curve_number": "Curve Number",
    "abstraction_ratio": "Abstraction Ratio",
    "minimum_infiltration_rate": "Minimum Infiltration Rate",
    "maximum_deficit": "Maximum Deficit",
    "initial_deficit": "Initial Deficit",
    "potential_percolation_rate": "Potential Percolation Rate",
    "wetting_front_suction": "Wetting Front Suction",
    "saturated_hydraulic_conductivity": "Saturated Hydraulic Conductivity",
    "initial_soil_water_content": "Initial Soil Water Content",
    "saturated_soil_water_content": "Saturated Soil Water Content",
}


def _require_modern_rasmapper(hecras_version: str) -> None:
    match = re.search(r"(?<!\d)(\d+)\.(\d+)", str(hecras_version))
    if match is None:
        raise ValueError(f"Invalid HEC-RAS version: {hecras_version!r}")
    parsed = (int(match.group(1)), int(match.group(2)))
    if parsed[0] <= 5:
        raise NotImplementedError(
            "Sidecar classification-polygon mutation requires HEC-RAS 6.0 or "
            "newer within the qualified 6.x/7.0.x range. For HEC-RAS 5.x "
            "geometry overrides, use "
            "GeomLandCover.set_mannings_region_polygons() and "
            "GeomLandCover.set_region_mannings_n()."
        )
    if not ((6, 0) <= parsed < (7, 1)):
        raise RuntimeError(
            "Native classification-polygon mutation is qualified only for "
            "HEC-RAS 6.x and 7.0.x. Refusing to guess at a future "
            f"RasMapperLib contract for {hecras_version!r}."
        )


def _decode_hdf_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00").strip()
    if hasattr(value, "item"):
        try:
            return _decode_hdf_text(value.item())
        except (TypeError, ValueError):
            pass
    return str(value).rstrip("\x00").strip()


def _sidecar_projection(layer_hdf_path: Path) -> Optional[str]:
    with h5py.File(layer_hdf_path, "r") as hdf_file:
        return _decode_hdf_text(hdf_file.attrs.get("Projection"))


def _require_landcover_sidecar(layer_hdf_path: Path) -> None:
    with h5py.File(layer_hdf_path, "r") as hdf_file:
        layer_type = _decode_hdf_text(hdf_file.attrs.get("LC Type"))
    if layer_type != "LandCover":
        raise NotImplementedError(
            "Native classification-polygon mutation is qualified only for "
            "modern sidecars with LC Type='LandCover'. Soils, infiltration, "
            "sediment, and other classification sidecars remain read-only "
            "until independently qualified."
        )


def _container_geometry_and_crs(polygon: Any) -> tuple[Any, Any, bool]:
    """Extract one geometry and its CRS from a GeoSeries/GeoDataFrame-like input."""
    if not hasattr(polygon, "crs"):
        return polygon, None, False

    crs = getattr(polygon, "crs", None)
    if crs is None:
        raise ValueError("Geospatial polygon input must declare a CRS.")

    if hasattr(polygon, "geometry"):
        geometries = polygon.geometry
        if hasattr(geometries, "iloc"):
            values = [
                geometry
                for geometry in geometries
                if geometry is not None and not geometry.is_empty
            ]
        else:
            values = [
                geometry
                for geometry in list(geometries)
                if geometry is not None and not geometry.is_empty
            ]
    elif hasattr(polygon, "iloc"):
        values = [
            geometry
            for geometry in polygon
            if geometry is not None and not geometry.is_empty
        ]
    else:
        return polygon, crs, True

    if len(values) != 1:
        raise ValueError(
            "Classification polygon input must contain exactly one non-empty "
            f"feature; found {len(values)}."
        )
    return values[0], crs, True


def _validate_input_crs(
    *,
    input_crs: Any,
    has_declared_crs: bool,
    layer_hdf_path: Path,
) -> None:
    if not has_declared_crs:
        return
    try:
        from pyproj import CRS
    except ImportError as exc:  # pragma: no cover - package dependency
        raise ImportError("pyproj is required to validate polygon CRS.") from exc

    sidecar_projection = _sidecar_projection(layer_hdf_path)
    if not sidecar_projection:
        raise ValueError(
            f"{layer_hdf_path} does not declare a Projection attribute, so "
            "the polygon CRS cannot be validated."
        )
    try:
        source = CRS.from_user_input(input_crs)
        target = CRS.from_user_input(sidecar_projection)
    except Exception as exc:
        raise ValueError("Could not parse the polygon or sidecar CRS.") from exc
    if not source.equals(target):
        raise ValueError(
            "Polygon CRS does not match the land-classification sidecar CRS: "
            f"{source.to_string()} != {target.to_string()}."
        )


def _normalize_single_polygon(
    polygon: Any,
    *,
    layer_hdf_path: Optional[Union[str, Path]] = None,
) -> Any:
    """Return one valid, hole-free Shapely Polygon.

    HEC-RAS 6.0 through 7.0.1 can persist interior rings in its native
    ``RasMapperLib.Polygon``.  Its land-cover classification resampler then
    converts that object to a single-ring ``Geospatial.Vectors.Polygon`` and
    fills every hole.  Reject interiors before backup or native mutation so a
    durable sidecar cannot imply unsupported hydraulic behavior.
    """
    try:
        from shapely.geometry import MultiPolygon, Polygon, shape
    except ImportError as exc:  # pragma: no cover - package dependency
        raise ImportError(
            "shapely is required for classification polygon authoring."
        ) from exc

    candidate, input_crs, has_declared_crs = _container_geometry_and_crs(polygon)
    if isinstance(candidate, Polygon):
        geometry = candidate
    elif isinstance(candidate, MultiPolygon):
        parts = [part for part in candidate.geoms if not part.is_empty]
        if len(parts) != 1:
            raise ValueError(
                "Classification polygon input must be one polygon. True "
                f"multipart input has {len(parts)} non-empty polygons."
            )
        geometry = parts[0]
    elif isinstance(candidate, dict):
        geometry = shape(candidate)
    elif hasattr(candidate, "__geo_interface__"):
        geometry = shape(candidate.__geo_interface__)
    elif isinstance(candidate, (list, tuple)):
        geometry = Polygon(candidate)
    else:
        raise TypeError(
            "polygon must be a Shapely Polygon, a one-member MultiPolygon, "
            "a one-feature GeoSeries/GeoDataFrame, a GeoJSON-like mapping, "
            "or a coordinate sequence."
        )

    if geometry.is_empty:
        raise ValueError("Classification polygon geometry cannot be empty.")
    if geometry.geom_type == "MultiPolygon":
        parts = [part for part in geometry.geoms if not part.is_empty]
        if len(parts) != 1:
            raise ValueError(
                "Classification polygon input must be one polygon. True "
                f"multipart input has {len(parts)} non-empty polygons."
            )
        geometry = parts[0]
    if geometry.geom_type != "Polygon":
        raise ValueError("Classification polygon geometry must be a Polygon.")
    if not geometry.is_valid:
        raise ValueError("Classification polygon geometry is not valid.")
    if geometry.area <= 0:
        raise ValueError("Classification polygon geometry must have positive area.")
    if geometry.interiors:
        raise NotImplementedError(
            "HEC-RAS 6.0 through 7.0.1 land-cover classification resampling "
            "does not honor polygon interior rings. Provide one hole-free "
            "Polygon. If an excluded area is required, split the intended "
            "coverage into explicit, non-overlapping hole-free polygons."
        )
    for ring in (geometry.exterior, *geometry.interiors):
        if len(ring.coords) < 4:
            raise ValueError(
                "Each classification polygon ring must contain at least "
                "three vertices plus its closing vertex."
            )
        if any(
            not math.isfinite(float(coordinate))
            for point in ring.coords
            for coordinate in point[:2]
        ):
            raise ValueError(
                "Classification polygon coordinates must be finite numbers."
            )

    if layer_hdf_path is not None:
        _validate_input_crs(
            input_crs=input_crs,
            has_declared_crs=has_declared_crs,
            layer_hdf_path=Path(layer_hdf_path),
        )
    return geometry


def _to_native_polygon(geometry: Any) -> Any:
    """Convert one Shapely Polygon, including holes, to RasMapperLib.Polygon."""
    from RasMapperLib import PointMs, Polygon as NativePolygon  # type: ignore
    from System import Array, Int32  # type: ignore
    from shapely.geometry.polygon import orient

    # RasMapperLib reports positive area for clockwise exterior rings. Shapely
    # then orients holes counter-clockwise, preserving native interior parts.
    oriented = orient(geometry, sign=-1.0)
    native_points = PointMs()
    part_starts: list[int] = []
    for ring in (oriented.exterior, *oriented.interiors):
        part_starts.append(int(native_points.Count))
        for x, y, *_ in ring.coords:
            native_points.Add(float(x), float(y))

    if len(part_starts) == 1:
        native_polygon = NativePolygon(native_points)
    else:
        native_polygon = NativePolygon(native_points, Array[Int32](part_starts))
    if not bool(native_polygon.IsValid()):
        raise ValueError("RasMapperLib rejected the converted polygon geometry.")
    if float(native_polygon.Area) <= 0:
        raise ValueError(
            "RasMapperLib did not recognize the exterior/interior ring orientation."
        )
    return native_polygon


def _load_native_layer(
    layer_hdf_path: Path,
    *,
    hecras_version: str,
) -> tuple[Any, Any, Any]:
    install = find_hecras_install(hecras_version)
    load_clr(install)
    from RasMapperLib import LandCoverLayer, PolygonFeatureLayer  # type: ignore

    loaded, layer, error = LandCoverLayer.TryLoadLayer(
        str(layer_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.LandCover,
    )
    if not loaded or layer is None:
        raise RuntimeError(
            "RASMapper could not load the land-classification sidecar: "
            f"{error or '<no diagnostic>'}"
        )

    polygon_layer = None
    for node in layer.Nodes:
        if isinstance(node, PolygonFeatureLayer) and str(
            node.GetType().FullName
        ).endswith("LandCoverClassificationLayer"):
            polygon_layer = node
            break
    if polygon_layer is None:
        # HEC-RAS keeps the property internal in some generations. Reflection
        # is a fallback only; the public child-node path is preferred.
        from System.Reflection import BindingFlags  # type: ignore

        prop = layer.GetType().GetProperty(
            "OverridePolygonLayer",
            BindingFlags.Instance | BindingFlags.NonPublic,
        )
        if prop is not None:
            polygon_layer = prop.GetValue(layer, None)
    if polygon_layer is None:
        raise RuntimeError(
            "RASMapper loaded the sidecar but exposed no native "
            "classification-polygon layer."
        )
    return LandCoverLayer, layer, polygon_layer


def _normalize_variable_values(
    variable_values: Optional[Mapping[str, Any]],
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, value in (variable_values or {}).items():
        lookup_key = str(key).strip()
        if not lookup_key:
            raise ValueError("Classification variable names cannot be blank.")
        canonical_key = _VARIABLE_VALUE_ALIASES.get(
            lookup_key.lower().replace(" ", "_"),
            lookup_key,
        )
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise ValueError(
                f"Classification variable {canonical_key!r} must be finite."
            )
        if canonical_key == "ManningsN" and numeric_value <= 0:
            raise ValueError("ManningsN must be positive.")
        if canonical_key == "Percent Impervious" and not 0 <= numeric_value <= 100:
            raise ValueError("Percent Impervious must be between 0 and 100.")
        normalized[canonical_key] = numeric_value
    return normalized


def _class_rows(landcover_layer_cls: Any, layer: Any) -> tuple[Any, dict[str, Any]]:
    table = landcover_layer_cls.GetClassificationVariablesAsDataTable(
        layer.Classification,
        layer.Parameters,
    )
    rows_by_name: dict[str, Any] = {}
    for row in table.Rows:
        name = str(row["Name"]).strip()
        if name.casefold() in rows_by_name:
            raise RuntimeError(
                f"RASMapper returned duplicate classification name {name!r}."
            )
        rows_by_name[name.casefold()] = row
    return table, rows_by_name


def _prepare_class(
    landcover_layer_cls: Any,
    layer: Any,
    *,
    class_name: str,
    class_id: Optional[int],
    variable_values: Optional[Mapping[str, Any]],
) -> tuple[str, int, dict[str, float]]:
    class_name = str(class_name).strip()
    if not class_name:
        raise ValueError("class_name cannot be blank.")
    if not bool(landcover_layer_cls.IsValidClassificationName(class_name)):
        raise ValueError(f"HEC-RAS rejected classification name {class_name!r}.")
    normalized_variables = _normalize_variable_values(variable_values)
    table, rows_by_name = _class_rows(landcover_layer_cls, layer)
    available_variables = {
        str(column.ColumnName)
        for column in table.Columns
        if str(column.ColumnName) not in {"ID", "Name"}
    }
    unknown_variables = sorted(set(normalized_variables) - available_variables)
    if unknown_variables:
        raise ValueError(
            "Variables are not available for this classification layer: "
            + ", ".join(unknown_variables)
        )

    existing_row = rows_by_name.get(class_name.casefold())
    if existing_row is None:
        raise ValueError(
            f"Classification {class_name!r} is not defined in the native "
            "sidecar. Classification-polygon CRUD can assign existing "
            "classes only; rebuild the land-classification layer to add a "
            "new class safely."
        )

    canonical_name = str(existing_row["Name"]).strip()
    resolved_class_id = int(existing_row["ID"])
    if class_id is not None and int(class_id) != resolved_class_id:
        raise ValueError(
            f"class_id {class_id} does not match HEC-RAS class "
            f"{canonical_name!r} (ID {resolved_class_id}). Rebuild the "
            "classification layer to remap raster class IDs."
        )
    for variable_name, value in normalized_variables.items():
        existing_row[variable_name] = value
    if normalized_variables and not bool(
        layer.TryAssigningNewParamtersUsingTable(table, True)
    ):
        raise RuntimeError(
            "RASMapper rejected the updated classification parameter table."
        )
    return canonical_name, resolved_class_id, normalized_variables


def _validate_class_after_save(
    landcover_layer_cls: Any,
    layer: Any,
    *,
    class_name: str,
    class_id: Optional[int],
    variable_values: dict[str, float],
) -> int:
    table, rows_by_name = _class_rows(landcover_layer_cls, layer)
    del table
    row = rows_by_name.get(class_name.casefold())
    if row is None:
        raise RuntimeError(f"RASMapper did not persist classification {class_name!r}.")
    persisted_id = int(row["ID"])
    if class_id is not None and persisted_id != int(class_id):
        raise RuntimeError(
            f"RASMapper persisted class ID {persisted_id}, not requested "
            f"class_id {class_id}."
        )
    mismatches = [
        variable_name
        for variable_name, expected in variable_values.items()
        if not math.isclose(
            float(row[variable_name]),
            expected,
            rel_tol=1.0e-6,
            abs_tol=1.0e-7,
        )
    ]
    if mismatches:
        raise RuntimeError(
            "RASMapper did not persist classification variables: "
            + ", ".join(sorted(mismatches))
        )
    return persisted_id


@contextmanager
def _hdf_transaction(
    layer_hdf_path: Path,
    *,
    backup: bool,
) -> Iterator[Optional[Path]]:
    """Restore the HDF and RASMapper backup artifact if any edit step fails."""
    with tempfile.NamedTemporaryFile(
        prefix=f".{layer_hdf_path.stem}.",
        suffix=".transaction.hdf",
        dir=layer_hdf_path.parent,
        delete=False,
    ) as snapshot_file:
        snapshot_path = Path(snapshot_file.name)
    shutil.copy2(layer_hdf_path, snapshot_path)

    native_backup_path = layer_hdf_path.with_name(f"{layer_hdf_path.stem}.backup.hdf")
    native_backup_snapshot: Optional[Path] = None
    if native_backup_path.exists():
        with tempfile.NamedTemporaryFile(
            prefix=f".{layer_hdf_path.stem}.backup.",
            suffix=".transaction.hdf",
            dir=layer_hdf_path.parent,
            delete=False,
        ) as native_snapshot_file:
            native_backup_snapshot = Path(native_snapshot_file.name)
        shutil.copy2(native_backup_path, native_backup_snapshot)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_suffix = uuid4().hex[:8]
    user_backup_path = (
        layer_hdf_path.with_name(
            f"{layer_hdf_path.stem}.classification_polygon."
            f"{timestamp}_{unique_suffix}.backup{layer_hdf_path.suffix}"
        )
        if backup
        else None
    )
    if user_backup_path is not None:
        shutil.copy2(layer_hdf_path, user_backup_path)

    try:
        yield user_backup_path
    except BaseException:
        shutil.copy2(snapshot_path, layer_hdf_path)
        if native_backup_snapshot is not None:
            shutil.copy2(native_backup_snapshot, native_backup_path)
        elif native_backup_path.exists():
            native_backup_path.unlink()
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)
        if native_backup_snapshot is not None:
            native_backup_snapshot.unlink(missing_ok=True)


def _result_polygons(
    layer_hdf_path: Path,
    *,
    backup_path: Optional[Path],
    class_update: Optional[dict[str, Any]] = None,
    removed_class_names: Optional[set[str]] = None,
) -> Any:
    from . import _land_classification_helper as _lch

    result = _lch.list_land_classification_polygons(layer_hdf_path)
    result.attrs.update(
        {
            "classification_hdf_path": str(layer_hdf_path),
            "backup_path": str(backup_path) if backup_path is not None else None,
            "recompute_required": True,
        }
    )
    if class_update is not None:
        result.attrs["class_update"] = class_update
    if removed_class_names is not None:
        result.attrs["removed_class_names"] = sorted(removed_class_names)
    return result


def add_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon: Any,
    class_name: str,
    class_id: Optional[int] = None,
    variable_values: Optional[Mapping[str, Any]] = None,
    backup: bool = True,
    *,
    hecras_version: str,
) -> Any:
    """Add one sidecar classification override through native RasMapperLib."""
    _require_modern_rasmapper(hecras_version)
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    _require_landcover_sidecar(layer_hdf_path)
    geometry = _normalize_single_polygon(
        polygon,
        layer_hdf_path=layer_hdf_path,
    )

    with _hdf_transaction(layer_hdf_path, backup=backup) as backup_path:
        landcover_layer_cls, layer, polygon_layer = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        initial_count = int(polygon_layer.FeatureCount())
        (
            canonical_name,
            _resolved_class_id,
            normalized_variables,
        ) = _prepare_class(
            landcover_layer_cls,
            layer,
            class_name=class_name,
            class_id=class_id,
            variable_values=variable_values,
        )
        if normalized_variables:
            landcover_layer_cls, layer, polygon_layer = _load_native_layer(
                layer_hdf_path,
                hecras_version=hecras_version,
            )

        polygon_layer.AddFeature(_to_native_polygon(geometry))
        polygon_layer.SetFeatureName(initial_count, canonical_name)
        if not bool(polygon_layer.SaveFeatureTable()):
            raise RuntimeError(
                "RASMapper failed to save the classification-polygon layer."
            )

        (
            verified_cls,
            verified_layer,
            verified_polygon_layer,
        ) = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        if int(verified_polygon_layer.FeatureCount()) != initial_count + 1:
            raise RuntimeError(
                "RASMapper did not persist the added classification polygon."
            )
        if (
            str(verified_polygon_layer.GetFeatureName(initial_count)).strip()
            != canonical_name
        ):
            raise RuntimeError(
                "RASMapper did not persist the polygon classification name."
            )
        persisted_id = _validate_class_after_save(
            verified_cls,
            verified_layer,
            class_name=canonical_name,
            class_id=class_id,
            variable_values=normalized_variables,
        )

        result = _result_polygons(
            layer_hdf_path,
            backup_path=backup_path,
            class_update={
                "class_name": canonical_name,
                "class_id": persisted_id,
                "created": False,
                "variable_values": normalized_variables,
            },
        )
        persisted = result.loc[result["polygon_index"] == initial_count]
        if len(persisted) != 1 or not persisted.iloc[0].geometry.equals(geometry):
            raise RuntimeError(
                "Native classification-polygon geometry failed readback verification."
            )
        return result


def update_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon_index: int,
    polygon: Optional[Any] = None,
    class_name: Optional[str] = None,
    class_id: Optional[int] = None,
    variable_values: Optional[Mapping[str, Any]] = None,
    backup: bool = True,
    *,
    hecras_version: str,
) -> Any:
    """Update one native classification polygon and/or its class parameters."""
    _require_modern_rasmapper(hecras_version)
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    _require_landcover_sidecar(layer_hdf_path)
    polygon_index = int(polygon_index)
    geometry = (
        _normalize_single_polygon(polygon, layer_hdf_path=layer_hdf_path)
        if polygon is not None
        else None
    )

    with _hdf_transaction(layer_hdf_path, backup=backup) as backup_path:
        landcover_layer_cls, layer, polygon_layer = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        feature_count = int(polygon_layer.FeatureCount())
        if polygon_index < 0 or polygon_index >= feature_count:
            raise IndexError(f"polygon_index out of range: {polygon_index}")
        current_name = str(polygon_layer.GetFeatureName(polygon_index)).strip()
        requested_name = current_name if class_name is None else class_name
        (
            canonical_name,
            _resolved_class_id,
            normalized_variables,
        ) = _prepare_class(
            landcover_layer_cls,
            layer,
            class_name=requested_name,
            class_id=class_id,
            variable_values=variable_values,
        )
        if normalized_variables:
            landcover_layer_cls, layer, polygon_layer = _load_native_layer(
                layer_hdf_path,
                hecras_version=hecras_version,
            )

        if geometry is not None:
            polygon_layer.SetFeature(
                polygon_index,
                _to_native_polygon(geometry),
            )
        if canonical_name != current_name:
            polygon_layer.SetFeatureName(polygon_index, canonical_name)
        if not bool(polygon_layer.SaveFeatureTable()):
            raise RuntimeError(
                "RASMapper failed to save the classification-polygon layer."
            )

        (
            verified_cls,
            verified_layer,
            verified_polygon_layer,
        ) = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        if int(verified_polygon_layer.FeatureCount()) != feature_count:
            raise RuntimeError("RASMapper changed the polygon count during an update.")
        if (
            str(verified_polygon_layer.GetFeatureName(polygon_index)).strip()
            != canonical_name
        ):
            raise RuntimeError(
                "RASMapper did not persist the updated polygon classification."
            )
        persisted_id = _validate_class_after_save(
            verified_cls,
            verified_layer,
            class_name=canonical_name,
            class_id=class_id,
            variable_values=normalized_variables,
        )

        result = _result_polygons(
            layer_hdf_path,
            backup_path=backup_path,
            class_update={
                "class_name": canonical_name,
                "class_id": persisted_id,
                "created": False,
                "variable_values": normalized_variables,
            },
        )
        if geometry is not None:
            persisted = result.loc[result["polygon_index"] == polygon_index]
            if len(persisted) != 1 or not persisted.iloc[0].geometry.equals(geometry):
                raise RuntimeError(
                    "Native classification-polygon geometry failed readback "
                    "verification."
                )
        return result


def delete_land_classification_polygon(
    layer_hdf_path: Union[str, Path],
    polygon_index: Optional[int] = None,
    class_name: Optional[str] = None,
    remove_unused_class: bool = False,
    backup: bool = True,
    *,
    hecras_version: str,
) -> Any:
    """Delete native classification polygons by index or classification name."""
    _require_modern_rasmapper(hecras_version)
    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(f"Land-classification HDF not found: {layer_hdf_path}")
    _require_landcover_sidecar(layer_hdf_path)
    if polygon_index is None and class_name is None:
        raise ValueError("Provide polygon_index or class_name.")
    if polygon_index is not None and class_name is not None:
        raise ValueError("Provide only one of polygon_index or class_name.")
    if remove_unused_class:
        raise NotImplementedError(
            "remove_unused_class is not supported by RasMapperLib's public "
            "classification API. Rebuild the classification layer to remove "
            "an unused class safely."
        )

    with _hdf_transaction(layer_hdf_path, backup=backup) as backup_path:
        _, _, polygon_layer = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        feature_count = int(polygon_layer.FeatureCount())
        removed_class_names: set[str] = set()
        if polygon_index is not None:
            polygon_index = int(polygon_index)
            if polygon_index < 0 or polygon_index >= feature_count:
                raise IndexError(f"polygon_index out of range: {polygon_index}")
            removed_class_names.add(
                str(polygon_layer.GetFeatureName(polygon_index)).strip()
            )
            polygon_layer.DeleteFeature(polygon_index)
            expected_count = feature_count - 1
        else:
            target_name = str(class_name).strip()
            if not target_name:
                raise ValueError("class_name cannot be blank.")
            matching_indexes = [
                index
                for index in range(feature_count)
                if str(polygon_layer.GetFeatureName(index)).strip().casefold()
                == target_name.casefold()
            ]
            if not matching_indexes:
                raise ValueError(
                    f"No classification polygons found for class_name={target_name!r}."
                )
            for index in reversed(matching_indexes):
                removed_class_names.add(
                    str(polygon_layer.GetFeatureName(index)).strip()
                )
                polygon_layer.DeleteFeature(index)
            expected_count = feature_count - len(matching_indexes)

        if not bool(polygon_layer.SaveFeatureTable()):
            raise RuntimeError(
                "RASMapper failed to save the classification-polygon layer."
            )
        _, _, verified_polygon_layer = _load_native_layer(
            layer_hdf_path,
            hecras_version=hecras_version,
        )
        if int(verified_polygon_layer.FeatureCount()) != expected_count:
            raise RuntimeError(
                "RASMapper did not persist the classification-polygon deletion."
            )
        return _result_polygons(
            layer_hdf_path,
            backup_path=backup_path,
            removed_class_names=removed_class_names,
        )
