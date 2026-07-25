"""Scoped native editing for geometry infiltration override regions.

HEC-RAS owns the compound HDF schema used by ``/Geometry/Infiltration``.
This module therefore mutates the loaded ``InterpretationOverrideLayer`` and
asks that layer to serialize itself.  It never authors those datasets with
``h5py``.

The base-override ``ParameterSet`` is an internal HEC member in every
qualified release (6.0, 6.6, and 7.0).  Access is intentionally guarded by an
exact runtime type/field fingerprint.  Any HEC change fails closed before the
geometry is modified.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence, Union

import h5py
import pandas as pd

from .LoggingConfig import get_logger
from .RasUtils import RasUtils
from .dotnet.clr_bootstrap import find_hecras_install, load_clr

logger = get_logger(__name__)

_LOCK = threading.RLock()
_LAYER_TYPE = "RasMapperLib.InterpretationOverrideLayer"
_PARAMETER_SET_TYPE = "Geospatial.Rasters.Classifications.ParameterSet"
_BASE_FIELD = "_baseVariableOverrides"
_SENTINEL = -9999.0


def resolve_hecras_version(
    hecras_version: Optional[str],
    ras_object: Any,
) -> str:
    """Resolve explicit -> supplied project -> global project -> error."""
    if hecras_version:
        return str(hecras_version)
    if ras_object is not None and getattr(ras_object, "ras_version", None):
        return str(ras_object.ras_version)

    from .RasPrj import ras

    if getattr(ras, "ras_version", None):
        return str(ras.ras_version)
    raise ValueError(
        "hecras_version is required when neither ras_object nor the global "
        "RAS project provides ras_version."
    )


def _qualified_version(version: str) -> tuple[int, int]:
    """Accept the reflected 6.x through 7.0 runtime family only."""
    match = re.search(r"(?<!\d)(\d+)\.(\d+)", str(version))
    if match is None:
        raise ValueError(f"Could not parse HEC-RAS version from {version!r}.")
    parsed = (int(match.group(1)), int(match.group(2)))
    if not ((6, 0) <= parsed < (7, 1)):
        raise RuntimeError(
            "Native geometry infiltration override editing is qualified only "
            "for HEC-RAS 6.x and 7.0.x. "
            f"Received {version!r}; refusing to guess at HEC's private ABI."
        )
    return parsed


def _geometry_path(path: Union[str, Path]) -> Path:
    resolved = RasUtils.safe_resolve(Path(path))
    if not resolved.exists():
        raise FileNotFoundError(f"Geometry HDF not found: {resolved}")
    if (
        not resolved.is_file()
        or re.fullmatch(r".+\.g\d{2}\.hdf", resolved.name, re.IGNORECASE)
        is None
    ):
        raise ValueError(
            "Expected an exact compiled geometry-HDF filename (*.g##.hdf), "
            f"not {resolved}."
        )
    try:
        with h5py.File(resolved, "r") as hdf_file:
            raw_file_type = hdf_file.attrs.get("File Type")
            root_groups = set(hdf_file.keys())
    except OSError as exc:
        raise ValueError(f"Could not open geometry HDF read-only: {resolved}") from exc
    if isinstance(raw_file_type, bytes):
        file_type = raw_file_type.decode("utf-8", errors="replace")
    elif hasattr(raw_file_type, "item"):
        item = raw_file_type.item()
        file_type = (
            item.decode("utf-8", errors="replace")
            if isinstance(item, bytes)
            else str(item)
        )
    else:
        file_type = str(raw_file_type or "")
    file_type = file_type.rstrip("\x00").strip()
    is_geometry_artifact = (
        file_type == "HEC-RAS Geometry"
        or (
            # HEC-RAS 7.0's geometry preprocessor has been observed changing
            # the root File Type to "HEC-RAS Results" while retaining a
            # geometry-only root. The exact .g##.hdf name plus the absence of
            # every plan/result root distinguishes that native artifact from
            # a renamed plan HDF.
            file_type == "HEC-RAS Results"
            and root_groups == {"Geometry"}
        )
    )
    if not is_geometry_artifact:
        raise ValueError(
            "Expected a geometry-only HDF in "
            f"{resolved}; observed File Type={file_type!r} and root groups "
            f"{sorted(root_groups)}. Refusing to mutate a plan, result, "
            "temporary, or unknown HDF artifact."
        )
    return resolved


def _backup_path(geometry_hdf_path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return geometry_hdf_path.with_name(
        f"{geometry_hdf_path.stem}.infiltration_override."
        f"{timestamp}.backup{geometry_hdf_path.suffix}"
    )


@contextmanager
def _geometry_transaction(geometry_hdf_path: Path) -> Iterator[Path]:
    """Keep a durable pre-edit backup and restore it on any failed gate."""
    backup_path = _backup_path(geometry_hdf_path)
    shutil.copy2(geometry_hdf_path, backup_path)

    snapshot_file = tempfile.NamedTemporaryFile(
        prefix=f".{geometry_hdf_path.stem}.infiltration_override.",
        suffix=geometry_hdf_path.suffix,
        dir=geometry_hdf_path.parent,
        delete=False,
    )
    snapshot_path = Path(snapshot_file.name)
    snapshot_file.close()
    shutil.copy2(geometry_hdf_path, snapshot_path)
    try:
        yield backup_path
    except BaseException:
        try:
            shutil.copy2(snapshot_path, geometry_hdf_path)
        except Exception as restore_error:
            raise RuntimeError(
                "Native infiltration edit failed and automatic rollback also "
                f"failed. Restore {geometry_hdf_path} from {backup_path}: "
                f"{restore_error}"
            ) from restore_error
        raise
    finally:
        snapshot_path.unlink(missing_ok=True)


def _release_geometry(geometry: Any) -> None:
    if geometry is not None:
        for method_name in ("Dispose", "Close"):
            try:
                getattr(geometry, method_name)()
            except Exception:
                pass
    try:
        from System import GC  # type: ignore

        GC.Collect()
        GC.WaitForPendingFinalizers()
        GC.Collect()
    except Exception:
        import gc

        gc.collect()


def _load_geometry(
    geometry_hdf_path: Path,
    *,
    hecras_version: str,
) -> Any:
    _qualified_version(hecras_version)
    install = Path(find_hecras_install(hecras_version))
    load_clr(install)

    from RasMapperLib import RASGeometry  # type: ignore

    geometry = RASGeometry(str(geometry_hdf_path))
    actual_dll = Path(str(geometry.GetType().Assembly.Location))
    expected_dll = install / "RasMapperLib.dll"
    if os.path.normcase(str(actual_dll.resolve())) != os.path.normcase(
        str(expected_dll.resolve())
    ):
        _release_geometry(geometry)
        raise RuntimeError(
            "The current Python process already loaded a different "
            "RasMapperLib runtime. Start a fresh process for HEC-RAS "
            f"{hecras_version}. Requested {expected_dll}, loaded {actual_dll}."
        )
    return geometry


def _qualified_layer(geometry: Any) -> Any:
    layer = getattr(geometry, "InfiltrationOverrideRegions", None)
    if layer is None or str(layer.GetType().FullName) != _LAYER_TYPE:
        observed = (
            "<missing>" if layer is None else str(layer.GetType().FullName)
        )
        raise RuntimeError(
            "HEC-RAS did not expose the qualified infiltration override "
            f"layer. Expected {_LAYER_TYPE}, observed {observed}."
        )

    # Force HEC's lazy HDF load before inspecting the internal ParameterSet.
    layer.FeatureCount()
    classification_layer = getattr(layer, "ClassificationLayer", None)
    classification = (
        getattr(classification_layer, "Classification", None)
        if classification_layer is not None
        else None
    )
    classes = (
        [str(value) for value in classification.Classes]
        if classification is not None
        else []
    )
    source_filename = (
        str(getattr(classification_layer, "SourceFilename", "") or "")
        if classification_layer is not None
        else ""
    )
    if (
        classification_layer is None
        or classification is None
        or not classes
        or not source_filename
        or not Path(source_filename).exists()
    ):
        raise RuntimeError(
            "HEC-RAS could not load the geometry's associated infiltration "
            "classification layer and class map. Repair the geometry "
            "'Infiltration Filename' association before editing overrides; "
            "saving without it would delete or truncate Base Overrides."
        )
    return layer


def _base_field(layer: Any) -> Any:
    from System.Reflection import BindingFlags  # type: ignore

    field = layer.GetType().GetField(
        _BASE_FIELD,
        BindingFlags.Instance | BindingFlags.NonPublic,
    )
    fingerprint_ok = (
        field is not None
        and str(field.DeclaringType.FullName) == _LAYER_TYPE
        and str(field.FieldType.FullName) == _PARAMETER_SET_TYPE
        and bool(field.IsAssembly)
        and not bool(field.IsStatic)
        and not bool(field.IsInitOnly)
    )
    if not fingerprint_ok:
        observed = "<missing>"
        if field is not None:
            observed = (
                f"declaring={field.DeclaringType.FullName}, "
                f"type={field.FieldType.FullName}, "
                f"assembly={field.IsAssembly}, static={field.IsStatic}, "
                f"initonly={field.IsInitOnly}"
            )
        raise RuntimeError(
            "HEC-RAS private infiltration base-override ABI does not match "
            f"the qualified fingerprint ({observed}). Refusing to modify "
            "the geometry."
        )
    return field


def _class_names(layer: Any) -> list[str]:
    return [
        str(value)
        for value in layer.ClassificationLayer.Classification.Classes
    ]


def _parameter_values(parameter: Any) -> dict[str, float]:
    return {
        str(item.Key): float(item.Value)
        for item in parameter.Values
        if float(item.Value) != _SENTINEL
    }


def _base_dataframe(layer: Any) -> pd.DataFrame:
    """Read the in-memory HEC ParameterSet after forcing native HDF load."""
    layer.FeatureCount()
    parameters = _base_field(layer).GetValue(layer)
    class_names = _class_names(layer)
    data: dict[str, list[Any]] = {"Land Cover Name": class_names}
    for parameter in parameters:
        values = _parameter_values(parameter)
        data[str(parameter.VariableName)] = [
            values.get(class_name, _SENTINEL) for class_name in class_names
        ]
    return pd.DataFrame(data)


def _parameter_set_dataframe(layer: Any, parameters: Any) -> pd.DataFrame:
    """Return one public region ``ParameterSet`` as a complete class table."""
    class_names = _class_names(layer)
    parameter_names = [
        str(parameter.VariableName)
        for parameter in layer.BaseInterpretationMergedWithLC
    ]
    values_by_parameter = {
        str(parameter.VariableName): _parameter_values(parameter)
        for parameter in parameters
    }
    data: dict[str, list[Any]] = {"Land Cover Name": class_names}
    for parameter_name in parameter_names:
        values = values_by_parameter.get(parameter_name, {})
        data[parameter_name] = [
            values.get(class_name, _SENTINEL) for class_name in class_names
        ]
    return pd.DataFrame(data)


def _normalize_input_table(
    infiltration_df: pd.DataFrame,
    *,
    layer: Any,
) -> tuple[pd.DataFrame, list[str]]:
    if not isinstance(infiltration_df, pd.DataFrame):
        raise TypeError("infiltration_df must be a pandas DataFrame.")
    table = infiltration_df.copy()
    if "Name" in table.columns and "Land Cover Name" not in table.columns:
        table = table.rename(columns={"Name": "Land Cover Name"})
    if "Land Cover Name" not in table.columns:
        raise ValueError(
            "infiltration_df must include 'Land Cover Name' (or legacy 'Name')."
        )

    table["Land Cover Name"] = table["Land Cover Name"].astype(str)
    if table["Land Cover Name"].duplicated().any():
        duplicates = sorted(
            table.loc[
                table["Land Cover Name"].duplicated(keep=False),
                "Land Cover Name",
            ].unique()
        )
        raise ValueError(
            "Land Cover Name values must be unique; duplicates: "
            + ", ".join(duplicates)
        )

    current = _base_field(layer).GetValue(layer)
    parameter_names = [str(item.VariableName) for item in current]
    if not parameter_names:
        raise RuntimeError(
            "The native infiltration override layer has no base parameter "
            "schema. Create a native override region first."
        )
    unknown = [
        str(column)
        for column in table.columns
        if column != "Land Cover Name" and str(column) not in parameter_names
    ]
    if unknown:
        raise ValueError(
            "Unsupported infiltration Base Overrides columns: "
            + ", ".join(unknown)
        )
    supplied_parameters = [
        name for name in parameter_names if name in table.columns
    ]
    if not supplied_parameters:
        raise ValueError(
            "infiltration_df must include at least one native infiltration "
            f"parameter column: {parameter_names}"
        )

    expected_names = _class_names(layer)
    observed_names = table["Land Cover Name"].tolist()
    missing = sorted(set(expected_names) - set(observed_names))
    extra = sorted(set(observed_names) - set(expected_names))
    if missing or extra or len(observed_names) != len(expected_names):
        details = []
        if missing:
            details.append(f"missing={missing[:8]}")
        if extra:
            details.append(f"extra={extra[:8]}")
        raise ValueError(
            "infiltration_df must contain exactly the classes exposed by the "
            "associated native infiltration layer (" + "; ".join(details) + ")."
        )
    return table.set_index("Land Cover Name").loc[expected_names], parameter_names


def _normalize_region_input_table(
    infiltration_df: pd.DataFrame,
    *,
    layer: Any,
) -> tuple[pd.DataFrame, list[str]]:
    """Validate a complete class table for one polygon-specific override."""
    if not isinstance(infiltration_df, pd.DataFrame):
        raise TypeError("infiltration_df must be a pandas DataFrame.")
    table = infiltration_df.copy()
    if "Name" in table.columns and "Land Cover Name" not in table.columns:
        table = table.rename(columns={"Name": "Land Cover Name"})
    if "Land Cover Name" not in table.columns:
        raise ValueError(
            "infiltration_df must include 'Land Cover Name' (or legacy 'Name')."
        )

    table["Land Cover Name"] = table["Land Cover Name"].astype(str)
    if table["Land Cover Name"].duplicated().any():
        duplicates = sorted(
            table.loc[
                table["Land Cover Name"].duplicated(keep=False),
                "Land Cover Name",
            ].unique()
        )
        raise ValueError(
            "Land Cover Name values must be unique; duplicates: "
            + ", ".join(duplicates)
        )

    parameter_names = [
        str(parameter.VariableName)
        for parameter in layer.BaseInterpretationMergedWithLC
    ]
    if not parameter_names:
        raise RuntimeError(
            "The native infiltration layer has no parameter schema."
        )
    unknown = [
        str(column)
        for column in table.columns
        if column != "Land Cover Name" and str(column) not in parameter_names
    ]
    if unknown:
        raise ValueError(
            "Unsupported infiltration region-override columns: "
            + ", ".join(unknown)
        )
    supplied_parameters = [
        name for name in parameter_names if name in table.columns
    ]
    if not supplied_parameters:
        raise ValueError(
            "infiltration_df must include at least one native infiltration "
            f"parameter column: {parameter_names}"
        )

    expected_names = _class_names(layer)
    observed_names = table["Land Cover Name"].tolist()
    missing = sorted(set(expected_names) - set(observed_names))
    extra = sorted(set(observed_names) - set(expected_names))
    if missing or extra or len(observed_names) != len(expected_names):
        details = []
        if missing:
            details.append(f"missing={missing[:8]}")
        if extra:
            details.append(f"extra={extra[:8]}")
        raise ValueError(
            "infiltration_df must contain exactly the classes exposed by the "
            "associated native infiltration layer (" + "; ".join(details) + ")."
        )
    return table.set_index("Land Cover Name").loc[expected_names], parameter_names


def _validate_parameter_value(parameter_name: str, value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{parameter_name!r} values must be numeric; received {value!r}."
        ) from exc
    if not math.isfinite(numeric):
        raise ValueError(
            f"{parameter_name!r} values must be finite or {_SENTINEL}."
        )
    if numeric == _SENTINEL:
        return numeric
    if parameter_name == "Curve Number" and not 0.0 <= numeric <= 100.0:
        raise ValueError("Curve Number must be between 0 and 100.")
    if parameter_name == "Abstraction Ratio" and not 0.0 <= numeric <= 1.0:
        raise ValueError("Abstraction Ratio must be between 0 and 1.")
    if parameter_name == "Minimum Infiltration Rate" and numeric < 0.0:
        raise ValueError("Minimum Infiltration Rate cannot be negative.")
    return numeric


def _replacement_parameter_set(
    layer: Any,
    infiltration_df: pd.DataFrame,
) -> tuple[Any, pd.DataFrame]:
    from Geospatial.Rasters.Classifications import (  # type: ignore
        Parameter,
        ParameterSet,
    )

    table, parameter_names = _normalize_input_table(
        infiltration_df,
        layer=layer,
    )
    current = _base_field(layer).GetValue(layer)
    current_by_name = {
        str(parameter.VariableName): _parameter_values(parameter)
        for parameter in current
    }

    replacement = ParameterSet()
    expected = pd.DataFrame({"Land Cover Name": _class_names(layer)})
    for parameter_name in parameter_names:
        values = dict(current_by_name.get(parameter_name, {}))
        if parameter_name in table.columns:
            values = {}
            for class_name in table.index:
                value = _validate_parameter_value(
                    parameter_name,
                    table.at[class_name, parameter_name],
                )
                if value != _SENTINEL:
                    values[class_name] = value

        parameter = Parameter(parameter_name)
        for class_name, value in values.items():
            parameter.AddOverride(str(class_name), float(value))
        replacement.Add(parameter)
        expected[parameter_name] = [
            values.get(class_name, _SENTINEL)
            for class_name in expected["Land Cover Name"]
        ]
    return replacement, expected


def _replacement_region_parameter_set(
    layer: Any,
    region_id: int,
    infiltration_df: pd.DataFrame,
) -> tuple[Any, pd.DataFrame]:
    """Build a replacement for exactly one public region parameter table."""
    from Geospatial.Rasters.Classifications import (  # type: ignore
        Parameter,
        ParameterSet,
    )

    table, parameter_names = _normalize_region_input_table(
        infiltration_df,
        layer=layer,
    )
    current = layer.GetParameterTable(region_id)
    current_by_name = {
        str(parameter.VariableName): _parameter_values(parameter)
        for parameter in current
    }

    replacement = ParameterSet()
    expected = pd.DataFrame({"Land Cover Name": _class_names(layer)})
    for parameter_name in parameter_names:
        values = dict(current_by_name.get(parameter_name, {}))
        if parameter_name in table.columns:
            values = {}
            for class_name in table.index:
                value = _validate_parameter_value(
                    parameter_name,
                    table.at[class_name, parameter_name],
                )
                if value != _SENTINEL:
                    values[class_name] = value

        parameter = Parameter(parameter_name)
        for class_name, value in values.items():
            parameter.AddOverride(str(class_name), float(value))
        replacement.Add(parameter)
        expected[parameter_name] = [
            values.get(class_name, _SENTINEL)
            for class_name in expected["Land Cover Name"]
        ]
    return replacement, expected


def _region_names(layer: Any) -> list[str]:
    return [
        str(layer.GetFeatureName(index))
        for index in range(int(layer.FeatureCount()))
    ]


def _resolve_region_id(
    layer: Any,
    *,
    region_name: Optional[str],
    region_id: Optional[int],
) -> int:
    """Resolve exactly one existing region before any backup or mutation."""
    if (region_name is None) == (region_id is None):
        raise ValueError(
            "Specify exactly one of region_name or region_id."
        )

    names = _region_names(layer)
    if region_name is not None:
        name = str(region_name).strip()
        if not name:
            raise ValueError("region_name cannot be blank.")
        matches = [index for index, value in enumerate(names) if value == name]
        if not matches:
            raise ValueError(
                f"Infiltration region {name!r} was not found."
            )
        if len(matches) > 1:
            raise ValueError(
                f"Infiltration region name {name!r} is ambiguous; "
                f"matched region IDs {matches}."
            )
        return matches[0]

    if isinstance(region_id, bool) or not isinstance(region_id, int):
        raise TypeError("region_id must be an integer.")
    if region_id < 0 or region_id >= len(names):
        raise ValueError(
            f"region_id must be between 0 and {len(names) - 1}; "
            f"received {region_id}."
        )
    return region_id


def _polygon_signatures(layer: Any) -> tuple[Any, ...]:
    """Capture every polygon part and vertex for non-mutation validation."""
    polygons = []
    for feature_id in range(int(layer.FeatureCount())):
        polygon = layer.Polygon(feature_id)
        parts = []
        for part_id in range(int(polygon.PartsCount())):
            points = polygon.PartPoints(part_id)
            parts.append(
                (
                    bool(polygon.PartIsInterior(part_id)),
                    tuple(
                        (float(points[index].X), float(points[index].Y))
                        for index in range(int(points.Count))
                    ),
                )
            )
        polygons.append(tuple(parts))
    return tuple(polygons)


def _reject_region_interior_rings(layer: Any, region_id: int) -> None:
    polygon = layer.Polygon(region_id)
    interiors = [
        part_id
        for part_id in range(int(polygon.PartsCount()))
        if bool(polygon.PartIsInterior(part_id))
    ]
    if interiors:
        raise NotImplementedError(
            "HEC-RAS native infiltration-region resampling discards polygon "
            "interior-ring topology. Replace the selected region with a "
            "hole-free polygon before setting region overrides."
        )


def _assert_table_equal(
    observed: pd.DataFrame,
    expected: pd.DataFrame,
    *,
    table_label: str = "Native infiltration Base Overrides",
) -> None:
    if list(observed.columns) != list(expected.columns):
        raise RuntimeError(
            f"{table_label} reloaded with a different "
            f"schema. Expected {list(expected.columns)}, observed "
            f"{list(observed.columns)}."
        )
    if observed["Land Cover Name"].tolist() != expected["Land Cover Name"].tolist():
        raise RuntimeError(
            f"{table_label} class names changed on reload."
        )
    for column in observed.columns[1:]:
        observed_values = observed[column].astype(float).tolist()
        expected_values = expected[column].astype(float).tolist()
        for index, (actual, wanted) in enumerate(
            zip(observed_values, expected_values)
        ):
            if not math.isclose(actual, wanted, rel_tol=1e-6, abs_tol=1e-5):
                class_name = observed.at[index, "Land Cover Name"]
                raise RuntimeError(
                    f"{table_label} failed reload "
                    f"validation for {class_name!r}/{column!r}: expected "
                    f"{wanted}, observed {actual}."
                )


def _scoped_save(layer: Any) -> None:
    # Do not call RASGeometry.Save(): decompilation shows it serializes every
    # IGeometryLayer. The inherited layer Save() is HEC's scoped transaction:
    # it opens H5Writer and calls InterpretationOverrideLayer.HDFSaveFeatureTable.
    if not bool(layer.Save()):
        raise RuntimeError(
            "HEC-RAS InterpretationOverrideLayer.Save() returned False."
        )


def create_infiltration_override_regions_native(
    geometry_hdf_path: Union[str, Path],
    region_names: Optional[Sequence[str]],
    *,
    hecras_version: str,
) -> pd.DataFrame:
    """Copy native Manning-region polygons into native infiltration regions."""
    path = _geometry_path(geometry_hdf_path)
    with _LOCK, _geometry_transaction(path) as backup_path:
        geometry = None
        layer = None
        expected_names: list[str] = []
        expected_table: Optional[pd.DataFrame] = None
        try:
            geometry = _load_geometry(path, hecras_version=hecras_version)
            layer = _qualified_layer(geometry)
            if int(layer.FeatureCount()) != 0:
                raise ValueError(
                    f"Native infiltration override regions already exist in {path}. "
                    "Edit their parameter tables instead of recreating them."
                )

            source = getattr(geometry, "LandCoverRegions", None)
            source_count = int(source.FeatureCount()) if source is not None else 0
            if source_count <= 0:
                raise RuntimeError(
                    "The geometry has no native Land Cover (Manning's n) "
                    "regions to copy into the infiltration override layer."
                )

            if region_names is None:
                expected_names = [
                    str(source.GetFeatureName(index))
                    for index in range(source_count)
                ]
            else:
                expected_names = [str(value).strip() for value in region_names]
                if len(expected_names) != source_count:
                    raise ValueError(
                        "region_names must have one name per native Land Cover "
                        f"region ({source_count}); received {len(expected_names)}."
                    )
            if any(not name for name in expected_names):
                raise ValueError("Infiltration region names cannot be blank.")
            if len(set(expected_names)) != len(expected_names):
                raise ValueError("Infiltration region names must be unique.")

            for index, name in enumerate(expected_names):
                layer.AddFeature(source.Polygon(index))
                layer.SetFeatureName(index, name)
                layer.SetIsDefaultName(index, False)

            expected_table = _base_dataframe(layer)
            _scoped_save(layer)
        finally:
            layer = None
            _release_geometry(geometry)
            geometry = None

        reloaded = None
        try:
            reloaded = _load_geometry(path, hecras_version=hecras_version)
            reloaded_layer = _qualified_layer(reloaded)
            observed_names = _region_names(reloaded_layer)
            if observed_names != expected_names:
                raise RuntimeError(
                    "Native infiltration region names changed on reload. "
                    f"Expected {expected_names}, observed {observed_names}."
                )
            observed_table = _base_dataframe(reloaded_layer)
            assert expected_table is not None
            _assert_table_equal(observed_table, expected_table)
        finally:
            _release_geometry(reloaded)

        logger.info(
            "Created %d native infiltration override region(s) in %s; "
            "pre-edit backup: %s",
            len(expected_names),
            path,
            backup_path,
        )
        observed_table.attrs.update(
            {
                "geometry_hdf_path": str(path),
                "backup_path": str(backup_path),
                "recompute_required": True,
            }
        )
        return observed_table


def set_infiltration_base_overrides_native(
    geometry_hdf_path: Union[str, Path],
    infiltration_df: pd.DataFrame,
    *,
    hecras_version: str,
) -> pd.DataFrame:
    """Replace base overrides through HEC's guarded ParameterSet + Save path."""
    path = _geometry_path(geometry_hdf_path)
    with _LOCK, _geometry_transaction(path) as backup_path:
        geometry = None
        layer = None
        expected: Optional[pd.DataFrame] = None
        expected_regions: list[str] = []
        try:
            geometry = _load_geometry(path, hecras_version=hecras_version)
            layer = _qualified_layer(geometry)
            if int(layer.FeatureCount()) <= 0:
                raise RuntimeError(
                    "The geometry has no native infiltration override region. "
                    "Call create_infiltration_override_regions() first."
                )
            expected_regions = _region_names(layer)
            replacement, expected = _replacement_parameter_set(
                layer,
                infiltration_df,
            )
            _base_field(layer).SetValue(layer, replacement)
            _scoped_save(layer)
        finally:
            layer = None
            _release_geometry(geometry)
            geometry = None

        reloaded = None
        try:
            reloaded = _load_geometry(path, hecras_version=hecras_version)
            reloaded_layer = _qualified_layer(reloaded)
            if _region_names(reloaded_layer) != expected_regions:
                raise RuntimeError(
                    "Native infiltration override regions changed while "
                    "saving Base Overrides."
                )
            observed = _base_dataframe(reloaded_layer)
            assert expected is not None
            _assert_table_equal(observed, expected)
        finally:
            _release_geometry(reloaded)

        logger.info(
            "Saved %d native infiltration Base Overrides rows in %s; "
            "pre-edit backup: %s",
            len(observed),
            path,
            backup_path,
        )
        observed.attrs.update(
            {
                "geometry_hdf_path": str(path),
                "backup_path": str(backup_path),
                "recompute_required": True,
            }
        )
        return observed


def get_infiltration_region_overrides_native(
    geometry_hdf_path: Union[str, Path],
    *,
    region_name: Optional[str] = None,
    region_id: Optional[int] = None,
    hecras_version: str,
) -> pd.DataFrame:
    """Read one public region ``ParameterSet`` in native class order."""
    path = _geometry_path(geometry_hdf_path)
    with _LOCK:
        geometry = None
        try:
            geometry = _load_geometry(path, hecras_version=hecras_version)
            layer = _qualified_layer(geometry)
            selected_id = _resolve_region_id(
                layer,
                region_name=region_name,
                region_id=region_id,
            )
            names = _region_names(layer)
            observed = _parameter_set_dataframe(
                layer,
                layer.GetParameterTable(selected_id),
            )
        finally:
            _release_geometry(geometry)

    observed.attrs.update(
        {
            "geometry_hdf_path": str(path),
            "region_name": names[selected_id],
            "region_id": selected_id,
        }
    )
    return observed


def set_infiltration_region_overrides_native(
    geometry_hdf_path: Union[str, Path],
    infiltration_df: pd.DataFrame,
    *,
    region_name: Optional[str] = None,
    region_id: Optional[int] = None,
    hecras_version: str,
) -> pd.DataFrame:
    """Replace one polygon-specific infiltration table through public APIs."""
    path = _geometry_path(geometry_hdf_path)
    with _LOCK:
        geometry = None
        layer = None
        try:
            geometry = _load_geometry(path, hecras_version=hecras_version)
            layer = _qualified_layer(geometry)
            selected_id = _resolve_region_id(
                layer,
                region_name=region_name,
                region_id=region_id,
            )
            _reject_region_interior_rings(layer, selected_id)

            original_names = _region_names(layer)
            original_polygons = _polygon_signatures(layer)
            original_base = _base_dataframe(layer)
            original_tables = [
                _parameter_set_dataframe(
                    layer,
                    layer.GetParameterTable(feature_id),
                )
                for feature_id in range(int(layer.FeatureCount()))
            ]
            replacement, expected = _replacement_region_parameter_set(
                layer,
                selected_id,
                infiltration_df,
            )

            with _geometry_transaction(path) as backup_path:
                try:
                    layer.SetParameterTable(selected_id, replacement)
                    _scoped_save(layer)
                finally:
                    layer = None
                    _release_geometry(geometry)
                    geometry = None

                reloaded = None
                try:
                    reloaded = _load_geometry(
                        path,
                        hecras_version=hecras_version,
                    )
                    reloaded_layer = _qualified_layer(reloaded)

                    observed_names = _region_names(reloaded_layer)
                    if observed_names != original_names:
                        raise RuntimeError(
                            "Infiltration region names changed while saving "
                            "one region parameter table."
                        )
                    if _polygon_signatures(reloaded_layer) != original_polygons:
                        raise RuntimeError(
                            "Infiltration region polygons changed while saving "
                            "one region parameter table."
                        )

                    observed_base = _base_dataframe(reloaded_layer)
                    _assert_table_equal(
                        observed_base,
                        original_base,
                        table_label="Native infiltration Base Overrides",
                    )

                    observed_tables = [
                        _parameter_set_dataframe(
                            reloaded_layer,
                            reloaded_layer.GetParameterTable(feature_id),
                        )
                        for feature_id in range(
                            int(reloaded_layer.FeatureCount())
                        )
                    ]
                    if len(observed_tables) != len(original_tables):
                        raise RuntimeError(
                            "The infiltration region-table count changed "
                            "during a scoped region update."
                        )
                    for feature_id, observed_table in enumerate(observed_tables):
                        comparison = (
                            expected
                            if feature_id == selected_id
                            else original_tables[feature_id]
                        )
                        _assert_table_equal(
                            observed_table,
                            comparison,
                            table_label=(
                                "Native infiltration region "
                                f"{original_names[feature_id]!r}"
                            ),
                        )
                    observed = observed_tables[selected_id]
                finally:
                    _release_geometry(reloaded)
        finally:
            _release_geometry(geometry)

        logger.info(
            "Saved native infiltration region overrides for %s (ID=%d) in "
            "%s; pre-edit backup: %s",
            original_names[selected_id],
            selected_id,
            path,
            backup_path,
        )
        observed.attrs.update(
            {
                "geometry_hdf_path": str(path),
                "backup_path": str(backup_path),
                "region_name": original_names[selected_id],
                "region_id": selected_id,
                "recompute_required": True,
            }
        )
        return observed
