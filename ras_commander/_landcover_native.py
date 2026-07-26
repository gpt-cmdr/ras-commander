"""Version-aware native RASMapper land-cover authoring.

HEC-RAS owns both the classification raster layout and the companion HDF
schema.  This module deliberately delegates those artifacts to
``LandCoverComputable`` instead of attempting to reproduce them with rasterio
and h5py.
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Union
from uuid import uuid4

import h5py
import numpy as np
import pandas as pd

from .dotnet.clr_bootstrap import find_hecras_install, load_clr
from .LoggingConfig import get_logger
from .RasUtils import RasUtils
from ._spatial_extent import _normalize_extent_bounds

logger = get_logger(__name__)

_RAS5_SCRIPT = Path(__file__).resolve().parent / "native" / "InvokeRas5LandCover.ps1"
_RAS5_GEOMETRY_SCRIPT = (
    Path(__file__).resolve().parent / "native" / "InvokeRas5GeometryLandCover.ps1"
)
_NODATA_NAME = "NoData"
_NODATA_ID = 0
_NODATA_MANNINGS = float(np.finfo(np.float32).max)
_SIDECAR_EDIT_LOCK = threading.RLock()


@contextmanager
def _sidecar_transaction(sidecar_hdf_path: Path):
    """Back up and restore one RAS-owned sidecar around a native edit."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    unique_suffix = uuid4().hex[:8]
    durable_backup_path = sidecar_hdf_path.with_name(
        f"{sidecar_hdf_path.stem}.native_parameters."
        f"{timestamp}_{unique_suffix}.backup{sidecar_hdf_path.suffix}"
    )
    native_backup_path = sidecar_hdf_path.with_name(
        f"{sidecar_hdf_path.stem}.backup.hdf"
    )

    with _SIDECAR_EDIT_LOCK:
        shutil.copy2(sidecar_hdf_path, durable_backup_path)
        with tempfile.NamedTemporaryFile(
            prefix=f".{sidecar_hdf_path.stem}.native_parameters.",
            suffix=sidecar_hdf_path.suffix,
            dir=sidecar_hdf_path.parent,
            delete=False,
        ) as snapshot_file:
            snapshot_path = Path(snapshot_file.name)
        shutil.copy2(sidecar_hdf_path, snapshot_path)

        native_backup_snapshot: Optional[Path] = None
        if native_backup_path.exists():
            with tempfile.NamedTemporaryFile(
                prefix=f".{sidecar_hdf_path.stem}.native_backup.",
                suffix=sidecar_hdf_path.suffix,
                dir=sidecar_hdf_path.parent,
                delete=False,
            ) as native_snapshot_file:
                native_backup_snapshot = Path(native_snapshot_file.name)
            shutil.copy2(native_backup_path, native_backup_snapshot)

        try:
            yield durable_backup_path
        except BaseException:
            try:
                shutil.copy2(snapshot_path, sidecar_hdf_path)
                if native_backup_snapshot is not None:
                    shutil.copy2(native_backup_snapshot, native_backup_path)
                elif native_backup_path.exists():
                    native_backup_path.unlink()
            except Exception as restore_error:
                raise RuntimeError(
                    "Native sidecar edit failed and automatic rollback also "
                    f"failed. Restore {sidecar_hdf_path} from "
                    f"{durable_backup_path}: {restore_error}"
                ) from restore_error
            raise
        finally:
            snapshot_path.unlink(missing_ok=True)
            if native_backup_snapshot is not None:
                native_backup_snapshot.unlink(missing_ok=True)


def _major_version(version: str) -> int:
    try:
        return int(str(version).strip().split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid HEC-RAS version: {version!r}") from exc


def _decode_hdf_attribute(value: Any) -> str:
    """Return a normalized text representation of an HDF attribute."""
    if value is None:
        return ""
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace").strip("\x00").strip()
    return str(value).strip("\x00").strip()


def _attribute_is_true(value: Any) -> bool:
    """Interpret the scalar encodings HEC-RAS uses for boolean attributes."""
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return _decode_hdf_attribute(value).lower() in {"1", "true", "yes"}


def _validate_property_tables_postcondition(
    geometry_hdf_path: Union[str, Path],
) -> None:
    """Require complete, structurally paired native property-table outputs."""
    geometry_hdf_path = RasUtils.safe_resolve(Path(geometry_hdf_path))
    with h5py.File(geometry_hdf_path, "r") as hdf:
        geometry = hdf.get("Geometry")
        if not isinstance(geometry, h5py.Group):
            raise RuntimeError(
                "Native property-table computation did not leave a /Geometry group."
            )
        if not _attribute_is_true(geometry.attrs.get("Complete Geometry")):
            raise RuntimeError(
                "Native property-table computation did not mark geometry complete."
            )

        flow_areas = geometry.get("2D Flow Areas")
        if flow_areas is None:
            return
        if not isinstance(flow_areas, h5py.Group):
            raise RuntimeError(
                "Native property-table computation left /Geometry/2D Flow Areas "
                "as a non-group object."
            )

        incomplete: list[str] = []
        checked_areas = 0
        required_pairs = (
            ("Cells Volume Elevation Info", "Cells Volume Elevation Values"),
            ("Faces Area Elevation Info", "Faces Area Elevation Values"),
        )
        for area_name, area in flow_areas.items():
            if not isinstance(area, h5py.Group):
                continue
            checked_areas += 1
            for info_name, values_name in required_pairs:
                info = area.get(info_name)
                values = area.get(values_name)
                base = f"Geometry/2D Flow Areas/{area_name}"
                if not isinstance(info, h5py.Dataset):
                    incomplete.append(f"{base}/{info_name}")
                if not isinstance(values, h5py.Dataset):
                    incomplete.append(f"{base}/{values_name}")
                if (
                    isinstance(info, h5py.Dataset)
                    and isinstance(values, h5py.Dataset)
                    and (info.size == 0 or values.size == 0)
                ):
                    incomplete.append(f"{base}/{info_name}|{values_name} (empty)")

        if checked_areas and incomplete:
            raise RuntimeError(
                "Native property-table computation returned without required "
                "2D hydraulic arrays: "
                + ", ".join(incomplete)
            )


def _native_extent(
    restrict_to_extent: Any,
    *,
    buffer_distance: float,
    extent_cls: Any,
) -> Any:
    if restrict_to_extent is None:
        if float(buffer_distance) != 0.0:
            raise ValueError(
                "buffer_distance requires restrict_to_extent; there is no "
                "authoritative polygon to buffer."
            )
        return None

    left, bottom, right, top = _normalize_extent_bounds(
        restrict_to_extent,
        buffer_distance=buffer_distance,
        parameter_name="restrict_to_extent",
    )
    # RasMapperLib.Extent uses the non-GIS constructor order
    # (maxX, minX, maxY, minY).
    return extent_cls(right, left, top, bottom)


def _native_rows(classification_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = [
        {
            "source_value": 0,
            "class_id": _NODATA_ID,
            "class_name": _NODATA_NAME,
            "mannings_n": _NODATA_MANNINGS,
            "percent_impervious": 0.0,
        }
    ]
    for row in classification_df.itertuples(index=False):
        source_value = row.source_value
        if isinstance(source_value, np.generic):
            source_value = source_value.item()
        rows.append(
            {
                "source_value": source_value,
                "class_id": int(row.class_id),
                "class_name": str(row.class_name),
                "mannings_n": float(row.mannings_n),
                "percent_impervious": float(row.percent_impervious),
            }
        )
    return rows


def _initialize_shared_projection(rasmap_path: Path) -> None:
    from RasMapperLib import RASMapperCom, SharedData  # type: ignore
    from System.Xml import XmlDocument  # type: ignore

    document = XmlDocument()
    document.Load(str(rasmap_path))
    srs_filename = RASMapperCom.GetSRSFromRasmapDoc(document, str(rasmap_path))
    if not srs_filename or not Path(str(srs_filename)).exists():
        raise RuntimeError(
            f"RASMapper could not resolve the project projection from {rasmap_path}"
        )
    SharedData.SRSFilename = str(srs_filename)
    if SharedData.SRSProjection is None:
        raise RuntimeError(f"RASMapper could not load project projection {srs_filename}")


def _populate_modern_input_mapping(
    landcover_file: Any,
    rows: list[dict[str, Any]],
    *,
    source_field: Optional[str],
) -> tuple[Any, Any]:
    from System import Array, Int32, String  # type: ignore

    if source_field:
        landcover_file.SelectedIdentifierColumn = str(source_field)

    landcover_file.ValueToOutput.Rows.Clear()
    mapped_source_values = {
        str(row["source_value"]) for row in rows if row["class_id"] != _NODATA_ID
    }

    # RASMapper treats zero (or the reported raster NoData value) as its
    # explicit NoData classification even when the source TIFF has no GDAL
    # NoData metadata.
    if bool(landcover_file.IsRaster):
        nodata_source = str(int(landcover_file.NoDataValue))
        if nodata_source not in mapped_source_values:
            data_row = landcover_file.ValueToOutput.NewRow()
            data_row["Name Field"] = nodata_source
            data_row["Classification"] = _NODATA_NAME
            landcover_file.ValueToOutput.Rows.Add(data_row)

    for row in rows:
        if row["class_id"] == _NODATA_ID:
            continue
        data_row = landcover_file.ValueToOutput.NewRow()
        data_row["Name Field"] = str(row["source_value"])
        data_row["Classification"] = row["class_name"]
        landcover_file.ValueToOutput.Rows.Add(data_row)

    names = Array[String]([row["class_name"] for row in rows])
    ids = Array[Int32]([row["class_id"] for row in rows])
    landcover_file.SetNameIDMap(names, ids)
    return names, ids


def _create_modern_landcover(
    *,
    rasmap_path: Path,
    source_path: Path,
    classification_df: pd.DataFrame,
    cell_size: float,
    source_field: Optional[str],
    output_hdf_path: Path,
    restrict_to_extent: Any,
    buffer_distance: float,
    hecras_version: str,
) -> Path:
    install = find_hecras_install(hecras_version)
    load_clr(install)

    from RasMapperLib import (  # type: ignore
        Extent,
        LandCoverComputable,
        LandCoverFile,
        LandCoverLayer,
        LandCoverLayerHelper,
        SharedData,
    )
    from RasMapperLib.Progress import ConsoleDisplayProgress  # type: ignore
    from System import Array, Int32, Single  # type: ignore
    from System.Collections.Generic import List  # type: ignore
    from Utility.Progress import ProgressReporter  # type: ignore

    _initialize_shared_projection(rasmap_path)
    extent = _native_extent(
        restrict_to_extent,
        buffer_distance=buffer_distance,
        extent_cls=Extent,
    )
    rows = _native_rows(classification_df)

    source = LandCoverFile(str(source_path), extent, SharedData.SRSProjection)
    names, ids = _populate_modern_input_mapping(
        source,
        rows,
        source_field=source_field,
    )

    inputs = List[LandCoverFile]()
    inputs.Add(source)
    extras = List[Array[Single]]()
    extras.Add(Array[Single]([row["mannings_n"] for row in rows]))
    extras.Add(Array[Single]([row["percent_impervious"] for row in rows]))
    payload_columns = List[Int32]()
    payload_columns.Add(0)
    payload_columns.Add(1)

    computable = LandCoverComputable(
        str(output_hdf_path),
        float(cell_size),
        extent,
        inputs,
        names,
        ids,
        LandCoverLayerHelper.ManningsN(),
        extras,
        payload_columns,
    )

    # ConsoleDisplayProgress.Run is a stub in HEC-RAS 6.6/7.0.  Its display
    # methods are implemented, so drive the computable synchronously using the
    # same Initialize -> Run -> Complete lifecycle as ComputeWindow.
    display = ConsoleDisplayProgress()
    computable.Initialize(display)
    computable.Run(getattr(ProgressReporter, "None")())
    computable.Complete()
    if not bool(computable.Success()):
        raise RuntimeError("RASMapper LandCoverComputable reported failure.")

    loaded, layer, error = LandCoverLayer.TryLoadLayer(
        str(output_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.LandCover,
    )
    if not loaded or layer is None:
        raise RuntimeError(
            "RASMapper could not load its generated land-cover layer: "
            f"{error or '<no diagnostic>'}"
        )
    if (
        layer.Classification is None
        or layer.Parameters is None
        or layer.Resampler is None
    ):
        raise RuntimeError(
            "RASMapper generated an incomplete land-cover layer "
            "(classification, parameters, or resampler is missing)."
        )

    # Native UI code performs this save after LandCoverComputable. It converts
    # the V1 interchange arrays into the V2 compound Raster Map/Variables
    # layout and writes the attributes RASMapper later consumes.
    layer.Save()
    return RasUtils.safe_resolve(output_hdf_path)


def create_soils(
    *,
    rasmap_path: Union[str, Path],
    source_raster_path: Union[str, Path],
    raster_map_rows: list[tuple[int, str]],
    cell_size: float,
    output_hdf_path: Union[str, Path],
    hecras_version: str,
) -> Path:
    """Author a hydrologic-soils sidecar through the target RasMapperLib.

    The input raster may be prepared with normal GIS tooling, but HEC-RAS owns
    creation and serialization of the output TIFF/HDF pair.
    """
    if _major_version(hecras_version) <= 5:
        raise NotImplementedError(
            "HEC-RAS 5.x has no hydrologic soils sidecar system. "
            "Use HEC-RAS 6.0 or newer for soils/infiltration authoring."
        )

    rasmap_path = RasUtils.safe_resolve(Path(rasmap_path))
    source_raster_path = RasUtils.safe_resolve(Path(source_raster_path))
    output_hdf_path = RasUtils.safe_resolve(Path(output_hdf_path))
    if not rasmap_path.exists():
        raise FileNotFoundError(rasmap_path)
    if not source_raster_path.exists():
        raise FileNotFoundError(source_raster_path)
    if not math.isfinite(float(cell_size)) or float(cell_size) <= 0:
        raise ValueError("cell_size must be positive and finite.")

    normalized_rows: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for class_id, class_name in raster_map_rows:
        class_id = int(class_id)
        class_name = str(class_name).strip()
        if class_id < 0:
            raise ValueError("Soils class IDs cannot be negative.")
        if not class_name:
            raise ValueError("Soils class names cannot be empty.")
        if class_id in seen_ids:
            raise ValueError(f"Duplicate soils class ID: {class_id}")
        if class_name in seen_names:
            raise ValueError(f"Duplicate soils class name: {class_name!r}")
        seen_ids.add(class_id)
        seen_names.add(class_name)
        normalized_rows.append(
            {
                "source_value": class_id,
                "class_id": class_id,
                "class_name": class_name,
            }
        )
    if not normalized_rows or 0 not in seen_ids:
        raise ValueError("Soils classes must include ID 0 for NoData.")

    install = find_hecras_install(hecras_version)
    load_clr(install)
    from RasMapperLib import (  # type: ignore
        LandCoverComputable,
        LandCoverFile,
        LandCoverLayer,
        LandCoverLayerHelper,
        SharedData,
    )
    from RasMapperLib.Progress import ConsoleDisplayProgress  # type: ignore
    from System import Array, Int32, Single  # type: ignore
    from System.Collections.Generic import List  # type: ignore
    from Utility.Progress import ProgressReporter  # type: ignore

    _initialize_shared_projection(rasmap_path)
    source = LandCoverFile(
        str(source_raster_path),
        None,
        SharedData.SRSProjection,
    )
    names, ids = _populate_modern_input_mapping(
        source,
        normalized_rows,
        source_field=None,
    )
    inputs = List[LandCoverFile]()
    inputs.Add(source)
    extras = List[Array[Single]]()
    payload_columns = List[Int32]()
    computable = LandCoverComputable(
        str(output_hdf_path),
        float(cell_size),
        None,
        inputs,
        names,
        ids,
        LandCoverLayerHelper.DefaultSoils(),
        extras,
        payload_columns,
    )
    display = ConsoleDisplayProgress()
    computable.Initialize(display)
    computable.Run(getattr(ProgressReporter, "None")())
    computable.Complete()
    if not bool(computable.Success()):
        raise RuntimeError("RASMapper soils LandCoverComputable reported failure.")

    loaded, layer, error = LandCoverLayer.TryLoadLayer(
        str(output_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.Soils,
    )
    if not loaded or layer is None:
        raise RuntimeError(
            "RASMapper could not load its generated soils layer: "
            f"{error or '<no diagnostic>'}"
        )
    if layer.Classification is None or layer.Resampler is None:
        raise RuntimeError(
            "RASMapper generated an incomplete soils layer "
            "(classification or resampler is missing)."
        )
    layer.Save()

    loaded, saved_layer, error = LandCoverLayer.TryLoadLayer(
        str(output_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.Soils,
    )
    if not loaded or saved_layer is None:
        raise RuntimeError(
            "RASMapper could not reload its saved soils layer: "
            f"{error or '<no diagnostic>'}"
        )
    saved = {
        int(class_id): str(class_name)
        for class_id, class_name in zip(
            saved_layer.GetIDs(),
            saved_layer.GetNames(),
            strict=False,
        )
    }
    expected = {
        int(row["class_id"]): str(row["class_name"])
        for row in normalized_rows
    }
    if saved != expected:
        raise RuntimeError(
            "RASMapper soils classification did not round-trip exactly: "
            f"expected {expected!r}, got {saved!r}"
        )
    return output_hdf_path


def _create_junction(junction: Path, target: Path) -> None:
    escaped_junction = str(junction).replace("'", "''")
    escaped_target = str(target).replace("'", "''")
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "New-Item -ItemType Junction "
                f"-Path '{escaped_junction}' "
                f"-Target '{escaped_target}' -Force | Out-Null"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not create the HEC-RAS 5.x GDAL junction: {result.stderr.strip()}"
        )


@contextmanager
def _ras5_host(install: Path):
    system_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    powershell_source = (
        system_root / "SysWOW64" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    if not powershell_source.exists():
        raise FileNotFoundError(
            "32-bit Windows PowerShell is required for HEC-RAS 5.x RasMapperLib."
        )

    with tempfile.TemporaryDirectory(prefix="ras_commander_ras5_") as temp_dir:
        temp_path = Path(temp_dir)
        host_dir = temp_path / "host"
        host_dir.mkdir()
        powershell_host = host_dir / "powershell.exe"
        shutil.copy2(powershell_source, powershell_host)
        config_source = powershell_source.with_suffix(".exe.config")
        if config_source.exists():
            shutil.copy2(config_source, host_dir / config_source.name)
        _create_junction(host_dir / "GDAL", install / "GDAL")
        yield temp_path, powershell_host


def _run_ras5_helper(
    *,
    install: Path,
    script_path: Path,
    config: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    if not script_path.exists():
        raise FileNotFoundError(f"Missing packaged RAS 5.x helper: {script_path}")
    with _ras5_host(install) as (temp_path, powershell_host):
        config_path = temp_path / "config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return subprocess.run(
            [
                str(powershell_host),
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ConfigPath",
                str(config_path),
            ],
            cwd=install,
            capture_output=True,
            text=True,
            timeout=1800,
        )


def _create_legacy_landcover(
    *,
    rasmap_path: Path,
    source_path: Path,
    classification_df: pd.DataFrame,
    cell_size: float,
    source_field: Optional[str],
    output_hdf_path: Path,
    restrict_to_extent: Any,
    buffer_distance: float,
    hecras_version: str,
) -> Path:
    if platform.system() != "Windows":
        raise RuntimeError("HEC-RAS 5.x native land-cover authoring is Windows-only.")
    if int(classification_df["class_id"].max()) > 255:
        raise ValueError("HEC-RAS 5.x land-cover class IDs must fit in one byte.")

    install = find_hecras_install(hecras_version)
    rows = _native_rows(classification_df)
    bounds = (
        _normalize_extent_bounds(
            restrict_to_extent,
            buffer_distance=buffer_distance,
            parameter_name="restrict_to_extent",
        )
        if restrict_to_extent is not None
        else None
    )
    if bounds is None:
        try:
            import rasterio
            from rasterio.errors import RasterioIOError
        except ImportError as exc:
            raise ImportError(
                "rasterio is required to derive the source extent for HEC-RAS 5.x."
            ) from exc
        try:
            with rasterio.open(source_path) as source:
                bounds = tuple(float(value) for value in source.bounds)
        except RasterioIOError:
            try:
                import geopandas as gpd
            except ImportError as exc:
                raise ImportError(
                    "geopandas is required to derive a vector source extent "
                    "for HEC-RAS 5.x."
                ) from exc
            source_frame = gpd.read_file(source_path)
            bounds = tuple(float(value) for value in source_frame.total_bounds)

    left, bottom, right, top = bounds
    config = {
        "install": str(install),
        "rasmap": str(rasmap_path),
        "source": str(source_path),
        "source_field": str(source_field or ""),
        "output_hdf": str(output_hdf_path),
        "cell_size": float(cell_size),
        "extent": {
            "min_x": left,
            "min_y": bottom,
            "max_x": right,
            "max_y": top,
        },
        "classes": rows,
    }

    result = _run_ras5_helper(
        install=install,
        script_path=_RAS5_SCRIPT,
        config=config,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "HEC-RAS 5.x native land-cover authoring failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return RasUtils.safe_resolve(output_hdf_path)


def validate_native_landcover(
    output_hdf_path: Union[str, Path],
    *,
    expected_class_ids: set[int],
    legacy: bool,
) -> dict[str, Any]:
    """Validate that RASMapper authored a usable, spatially classified layer."""
    output_hdf_path = RasUtils.safe_resolve(Path(output_hdf_path))
    output_tif_path = output_hdf_path.with_suffix(".tif")
    if not output_hdf_path.exists() or not output_tif_path.exists():
        raise RuntimeError("RASMapper did not create both land-cover HDF and TIFF files.")

    with h5py.File(output_hdf_path, "r") as hdf:
        if legacy:
            required = {"IDs", "Names", "ManningsN"}
            actual_ids = {int(value) for value in hdf["IDs"][()]} if "IDs" in hdf else set()
        else:
            required = {"Raster Map", "Variables"}
            actual_ids = (
                {int(row["ID"]) for row in hdf["Raster Map"][()]}
                if "Raster Map" in hdf
                else set()
            )
        missing = sorted(required.difference(hdf.keys()))
        if missing:
            raise RuntimeError(
                "RASMapper land-cover HDF is incomplete; missing: "
                + ", ".join(missing)
            )

    if not expected_class_ids.issubset(actual_ids):
        raise RuntimeError(
            "RASMapper land-cover HDF is missing requested class IDs: "
            + ", ".join(str(value) for value in sorted(expected_class_ids - actual_ids))
        )

    try:
        import rasterio
    except ImportError as exc:
        raise ImportError("rasterio is required to validate native land cover.") from exc

    with rasterio.open(output_tif_path) as raster:
        raster_ids = {int(value) for value in np.unique(raster.read(1))}
        if raster.nodata is not None:
            raise RuntimeError(
                "Native HEC land-cover TIFF unexpectedly declares GDAL NoData; "
                "RASMapper expects class 0 without NoData metadata."
            )
        if not bool(raster.profile.get("tiled")):
            raise RuntimeError("Native HEC land-cover TIFF is not tiled.")
        compression = str(raster.profile.get("compress", "")).lower()
        if compression != "deflate":
            raise RuntimeError(
                f"Native HEC land-cover TIFF compression is {compression!r}, not DEFLATE."
            )

    positive_ids = raster_ids.intersection(expected_class_ids)
    if not positive_ids:
        raise RuntimeError(
            "RASMapper land-cover TIFF collapsed to class 0; none of the "
            "requested classifications are present."
        )
    unexpected_ids = raster_ids.difference(expected_class_ids).difference({_NODATA_ID})
    if unexpected_ids:
        raise RuntimeError(
            "RASMapper land-cover TIFF contains unexpected class IDs: "
            + ", ".join(str(value) for value in sorted(unexpected_ids))
        )

    return {
        "hdf_path": output_hdf_path,
        "tif_path": output_tif_path,
        "hdf_class_ids": sorted(actual_ids),
        "raster_class_ids": sorted(raster_ids),
        "legacy_schema": legacy,
    }


def _set_landcover_parameters_native(
    landcover_hdf_path: Union[str, Path],
    class_mapping: Mapping[str, float],
    *,
    hecras_version: str,
) -> dict[str, Any]:
    """Update a modern sidecar through RASMapper's native table editor API.

    HEC-RAS 5.x exposes no supported equivalent.  Callers targeting 5.x must
    put geometry-specific Manning overrides in the text geometry calibration
    table instead of editing solver-owned HDF datasets.
    """
    landcover_hdf_path = RasUtils.safe_resolve(Path(landcover_hdf_path))
    if not landcover_hdf_path.exists():
        raise FileNotFoundError(landcover_hdf_path)
    if _major_version(hecras_version) <= 5:
        raise NotImplementedError(
            "HEC-RAS 5.x has no native land-cover parameter-table writer. "
            "Use GeomLandCover.set_base_mannings_n() for geometry-specific "
            "Manning overrides, or rebuild the layer with "
            "RasMap.add_landcover_layer()."
        )

    normalized_mapping = {
        str(class_name).strip(): float(mannings_n)
        for class_name, mannings_n in class_mapping.items()
    }
    for class_name, mannings_n in normalized_mapping.items():
        if not class_name:
            raise ValueError("Land-cover class names cannot be empty.")
        if not math.isfinite(mannings_n) or mannings_n <= 0:
            raise ValueError(
                f"Manning's n for {class_name!r} must be positive and finite."
            )

    install = find_hecras_install(hecras_version)
    load_clr(install)
    from RasMapperLib import LandCoverLayer  # type: ignore

    loaded, layer, error = LandCoverLayer.TryLoadLayer(
        str(landcover_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.LandCover,
    )
    if not loaded or layer is None:
        raise RuntimeError(
            "RASMapper could not load the land-cover layer for editing: "
            f"{error or '<no diagnostic>'}"
        )

    table = LandCoverLayer.GetClassificationVariablesAsDataTable(
        layer.Classification,
        layer.Parameters,
    )
    rows_by_name = {}
    for row in table.Rows:
        name = str(row["Name"]).strip()
        if name in rows_by_name:
            raise RuntimeError(
                f"RASMapper returned duplicate land-cover class {name!r}."
            )
        rows_by_name[name] = row

    missing = sorted(set(normalized_mapping).difference(rows_by_name))
    if missing:
        raise ValueError(
            "Class names not found in native land-cover table: "
            + ", ".join(missing)
        )

    details = []
    for name, row in rows_by_name.items():
        old_value = (
            float(row["ManningsN"])
            if str(row["ManningsN"]).strip()
            else float("nan")
        )
        new_value = normalized_mapping.get(name, old_value)
        changed = name in normalized_mapping and not np.isclose(
            old_value,
            new_value,
        )
        if name in normalized_mapping:
            row["ManningsN"] = new_value
        details.append(
            {
                "class_name": name,
                "old_mannings_n": old_value,
                "new_mannings_n": new_value,
                "requested": name in normalized_mapping,
                "value_changed": bool(changed),
            }
        )

    # The public method name is misspelled in RasMapperLib itself.
    if normalized_mapping and not bool(
        layer.TryAssigningNewParamtersUsingTable(table, True)
    ):
        raise RuntimeError(
            "RASMapper rejected the updated land-cover parameter table."
        )

    loaded, saved_layer, error = LandCoverLayer.TryLoadLayer(
        str(landcover_hdf_path),
        None,
        "",
        LandCoverLayer.LandCoverType.LandCover,
    )
    if not loaded or saved_layer is None:
        raise RuntimeError(
            "RASMapper could not reload its saved land-cover layer: "
            f"{error or '<no diagnostic>'}"
        )
    saved_table = LandCoverLayer.GetClassificationVariablesAsDataTable(
        saved_layer.Classification,
        saved_layer.Parameters,
    )
    saved_values = {
        str(row["Name"]).strip(): float(row["ManningsN"])
        for row in saved_table.Rows
        if str(row["ManningsN"]).strip()
    }
    mismatches = [
        name
        for name, expected in normalized_mapping.items()
        if name not in saved_values
        or not np.isclose(saved_values[name], expected, rtol=1.0e-6, atol=1.0e-7)
    ]
    if mismatches:
        raise RuntimeError(
            "RASMapper did not persist Manning values for: "
            + ", ".join(sorted(mismatches))
        )

    changed_count = sum(detail["value_changed"] for detail in details)
    requested_unchanged_count = sum(
        detail["requested"] and not detail["value_changed"]
        for detail in details
    )
    not_requested_count = sum(
        not detail["requested"]
        for detail in details
    )
    return {
        "changed": changed_count,
        "requested_unchanged": requested_unchanged_count,
        "not_requested": not_requested_count,
        "unchanged": len(details) - changed_count,
        "format": "native-v6+",
        "class_details": details,
    }


def set_landcover_parameters(
    landcover_hdf_path: Union[str, Path],
    class_mapping: Mapping[str, float],
    *,
    hecras_version: str,
) -> dict[str, Any]:
    """Transactionally update a native land-cover parameter table."""
    path = RasUtils.safe_resolve(Path(landcover_hdf_path))
    if not path.exists():
        raise FileNotFoundError(path)
    if _major_version(hecras_version) <= 5:
        raise NotImplementedError(
            "HEC-RAS 5.x has no native land-cover parameter-table writer. "
            "Use GeomLandCover.set_base_mannings_n() for geometry-specific "
            "Manning overrides, or rebuild the layer with "
            "RasMap.add_landcover_layer()."
        )

    with _sidecar_transaction(path) as backup_path:
        report = _set_landcover_parameters_native(
            path,
            class_mapping,
            hecras_version=hecras_version,
        )
    report.update(
        {
            "landcover_hdf_path": path,
            "backup_path": backup_path,
            "recompute_required": True,
        }
    )
    return report


def _set_classification_parameters_native(
    layer_hdf_path: Union[str, Path],
    parameter_table: pd.DataFrame,
    *,
    layer_type: str,
    hecras_version: str,
    properties: Optional[Mapping[str, float]] = None,
) -> pd.DataFrame:
    """Update a modern classification sidecar through RASMapper's table API.

    ``layer_type`` identifies the native layer schema and must be one of
    ``soils``, ``infiltration_scs``, ``infiltration_deficit_constant``, or
    ``infiltration_green_ampt``. The supplied rows update existing native
    classes by ``Name``; classification IDs and row membership are preserved.
    """
    if _major_version(hecras_version) <= 5:
        raise NotImplementedError(
            "HEC-RAS 5.x has no native soils/infiltration sidecar editor."
        )
    if not isinstance(parameter_table, pd.DataFrame):
        raise TypeError("parameter_table must be a pandas DataFrame.")
    if "Name" not in parameter_table.columns:
        raise ValueError("parameter_table must contain a Name column.")

    layer_hdf_path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not layer_hdf_path.exists():
        raise FileNotFoundError(layer_hdf_path)

    normalized_type = str(layer_type).strip().lower()
    type_names = {
        "soils": "Soils",
        "infiltration_scs": "InfiltrationSCSCurveNumber",
        "infiltration_scs_curve_number": "InfiltrationSCSCurveNumber",
        "scs_curve_number": "InfiltrationSCSCurveNumber",
        "infiltration_deficit_constant": "InfiltrationDeficitConstantLoss",
        "deficit_constant": "InfiltrationDeficitConstantLoss",
        "infiltration_green_ampt": "InfiltrationGreenAmpt",
        "green_ampt": "InfiltrationGreenAmpt",
    }
    if normalized_type not in type_names:
        raise ValueError(
            "layer_type must be soils, infiltration_scs, "
            "infiltration_deficit_constant, or infiltration_green_ampt."
        )

    updates = parameter_table.copy()
    updates["Name"] = updates["Name"].astype(str).str.strip()
    if (updates["Name"] == "").any():
        raise ValueError("Classification names cannot be empty.")
    if updates["Name"].duplicated().any():
        duplicates = sorted(
            updates.loc[updates["Name"].duplicated(keep=False), "Name"].unique()
        )
        raise ValueError(
            "parameter_table contains duplicate class names: "
            + ", ".join(duplicates)
        )
    parameter_columns = [
        str(column)
        for column in updates.columns
        if str(column) not in {"Name", "ID"}
    ]
    if not parameter_columns and not properties:
        raise ValueError("No classification parameters or properties were supplied.")
    for column in parameter_columns:
        numeric = pd.to_numeric(updates[column], errors="raise").astype(float)
        if not np.isfinite(numeric.to_numpy()).all():
            raise ValueError(f"{column} values must be finite.")
        updates[column] = numeric
    normalized_properties = {
        str(name).strip(): float(value)
        for name, value in (properties or {}).items()
    }
    for name, value in normalized_properties.items():
        if not name:
            raise ValueError("Property names cannot be empty.")
        if not math.isfinite(value):
            raise ValueError(f"Property {name!r} must be finite.")

    install = find_hecras_install(hecras_version)
    load_clr(install)
    from RasMapperLib import LandCoverLayer  # type: ignore

    native_type = getattr(
        LandCoverLayer.LandCoverType,
        type_names[normalized_type],
    )
    loaded, layer, error = LandCoverLayer.TryLoadLayer(
        str(layer_hdf_path),
        None,
        "",
        native_type,
    )
    if not loaded or layer is None:
        raise RuntimeError(
            "RASMapper could not load the classification layer for editing: "
            f"{error or '<no diagnostic>'}"
        )
    table = LandCoverLayer.GetClassificationVariablesAsDataTable(
        layer.Classification,
        layer.Parameters,
    )
    native_columns = {
        str(table.Columns[index].ColumnName)
        for index in range(table.Columns.Count)
    }
    unknown_columns = sorted(set(parameter_columns).difference(native_columns))
    if unknown_columns:
        raise ValueError(
            "Parameters are not present in the native layer schema: "
            + ", ".join(unknown_columns)
        )

    native_rows = {
        str(row["Name"]).strip(): row
        for row in table.Rows
    }
    missing_names = sorted(set(updates["Name"]).difference(native_rows))
    if missing_names:
        raise ValueError(
            "Class names not found in the native classification table: "
            + ", ".join(missing_names)
        )
    for update in updates.to_dict(orient="records"):
        native_row = native_rows[update["Name"]]
        for column in parameter_columns:
            native_row[column] = float(update[column])

    if parameter_columns and not bool(
        layer.TryAssigningNewParamtersUsingTable(table, True)
    ):
        raise RuntimeError(
            "RASMapper rejected the updated classification parameter table."
        )
    for name, value in normalized_properties.items():
        if not bool(layer.TrySetPropertyValue(name, value)):
            raise ValueError(
                f"Native layer does not expose property {name!r}."
            )
    if normalized_properties:
        save_result = layer.Save()
        if save_result is not None and not bool(save_result):
            raise RuntimeError(
                "RASMapper rejected the classification-layer save."
            )

    loaded, saved_layer, error = LandCoverLayer.TryLoadLayer(
        str(layer_hdf_path),
        None,
        "",
        native_type,
    )
    if not loaded or saved_layer is None:
        raise RuntimeError(
            "RASMapper could not reload its saved classification layer: "
            f"{error or '<no diagnostic>'}"
        )
    saved_table = LandCoverLayer.GetClassificationVariablesAsDataTable(
        saved_layer.Classification,
        saved_layer.Parameters,
    )
    saved_rows = {
        str(row["Name"]).strip(): row
        for row in saved_table.Rows
    }
    mismatches: list[str] = []
    for update in updates.to_dict(orient="records"):
        saved_row = saved_rows.get(update["Name"])
        if saved_row is None:
            mismatches.append(update["Name"])
            continue
        for column in parameter_columns:
            if not np.isclose(
                float(saved_row[column]),
                float(update[column]),
                rtol=1.0e-6,
                atol=1.0e-7,
            ):
                mismatches.append(f"{update['Name']}:{column}")
    if mismatches:
        raise RuntimeError(
            "RASMapper did not persist classification parameters for: "
            + ", ".join(mismatches)
        )
    property_mismatches: list[str] = []
    for name, expected in normalized_properties.items():
        try:
            property_loaded, observed = saved_layer.TryGetPropertyValue(
                name,
                0.0,
            )
        except Exception as exc:
            raise RuntimeError(
                f"RASMapper could not reload property {name!r}."
            ) from exc
        if not bool(property_loaded) or not np.isclose(
            float(observed),
            expected,
            rtol=1.0e-6,
            atol=1.0e-7,
        ):
            property_mismatches.append(name)
    if property_mismatches:
        raise RuntimeError(
            "RASMapper did not persist classification properties for: "
            + ", ".join(property_mismatches)
        )

    records: list[dict[str, Any]] = []
    for row in saved_table.Rows:
        record = {
            str(saved_table.Columns[index].ColumnName): row[index]
            for index in range(saved_table.Columns.Count)
        }
        records.append(record)
    return pd.DataFrame.from_records(records)


def set_classification_parameters(
    layer_hdf_path: Union[str, Path],
    parameter_table: pd.DataFrame,
    *,
    layer_type: str,
    hecras_version: str,
    properties: Optional[Mapping[str, float]] = None,
) -> pd.DataFrame:
    """Transactionally update a native soils or infiltration sidecar."""
    path = RasUtils.safe_resolve(Path(layer_hdf_path))
    if not path.exists():
        raise FileNotFoundError(path)
    if _major_version(hecras_version) <= 5:
        raise NotImplementedError(
            "HEC-RAS 5.x has no native soils/infiltration sidecar editor."
        )

    with _sidecar_transaction(path) as backup_path:
        result = _set_classification_parameters_native(
            path,
            parameter_table,
            layer_type=layer_type,
            hecras_version=hecras_version,
            properties=properties,
        )
    result.attrs.update(
        {
            "classification_hdf_path": str(path),
            "backup_path": str(backup_path),
            "recompute_required": True,
        }
    )
    return result


def recompute_property_tables(
    *,
    rasmap_path: Union[str, Path],
    geometry_hdf_path: Union[str, Path],
    hecras_version: str,
) -> Path:
    """Run the selected HEC-RAS generation's native property-table command."""
    rasmap_path = RasUtils.safe_resolve(Path(rasmap_path))
    geometry_hdf_path = RasUtils.safe_resolve(Path(geometry_hdf_path))
    if not rasmap_path.exists():
        raise FileNotFoundError(rasmap_path)
    if not geometry_hdf_path.exists():
        raise FileNotFoundError(geometry_hdf_path)

    install = find_hecras_install(hecras_version)
    if _major_version(hecras_version) <= 5:
        result = _run_ras5_helper(
            install=install,
            script_path=_RAS5_GEOMETRY_SCRIPT,
            config={
                "install": str(install),
                "rasmap": str(rasmap_path),
                "geometry_hdf": str(geometry_hdf_path),
                "landcover_tif": "",
                "layer_name": "",
                "terrain_hdf": "",
                "compute_property_tables": True,
            },
        )
        if result.returncode != 0:
            raise RuntimeError(
                "HEC-RAS 5.x native property-table computation failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
    else:
        load_clr(install)
        from RasMapperLib.Scripting import ComputePropertyTablesCommand  # type: ignore

        command = ComputePropertyTablesCommand(str(geometry_hdf_path))
        command.Execute(None)
    _validate_property_tables_postcondition(geometry_hdf_path)
    return geometry_hdf_path


def associate_landcover_to_geometry(
    *,
    rasmap_path: Union[str, Path],
    geometry_hdf_path: Union[str, Path],
    landcover_hdf_path: Union[str, Path],
    terrain_hdf_path: Optional[Union[str, Path]] = None,
    hecras_version: str,
    compute_property_tables: bool = False,
) -> Path:
    """Associate native land cover using the selected RASMapper generation."""
    rasmap_path = RasUtils.safe_resolve(Path(rasmap_path))
    geometry_hdf_path = RasUtils.safe_resolve(Path(geometry_hdf_path))
    landcover_hdf_path = RasUtils.safe_resolve(Path(landcover_hdf_path))
    terrain_hdf_path = (
        RasUtils.safe_resolve(Path(terrain_hdf_path))
        if terrain_hdf_path is not None
        else None
    )
    for path in (
        rasmap_path,
        geometry_hdf_path,
        landcover_hdf_path,
        terrain_hdf_path,
    ):
        if path is None:
            continue
        if not path.exists():
            raise FileNotFoundError(path)

    major = _major_version(hecras_version)
    install = find_hecras_install(hecras_version)
    if major <= 5:
        landcover_tif = landcover_hdf_path.with_suffix(".tif")
        if not landcover_tif.exists():
            raise FileNotFoundError(landcover_tif)
        result = _run_ras5_helper(
            install=install,
            script_path=_RAS5_GEOMETRY_SCRIPT,
            config={
                "install": str(install),
                "rasmap": str(rasmap_path),
                "geometry_hdf": str(geometry_hdf_path),
                "landcover_tif": str(landcover_tif),
                "layer_name": landcover_tif.stem,
                "terrain_hdf": str(terrain_hdf_path or ""),
                "compute_property_tables": bool(compute_property_tables),
            },
        )
        if result.returncode != 0:
            raise RuntimeError(
                "HEC-RAS 5.x native land-cover association failed: "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        expected_path = landcover_tif
    else:
        from .geom.GeomMesh import GeomMesh

        GeomMesh.set_geometry_association(
            geometry_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
            landcover_hdf_path=landcover_hdf_path,
            hecras_dir=install,
            validate=True,
        )
        if compute_property_tables:
            from RasMapperLib.Scripting import ComputePropertyTablesCommand  # type: ignore

            command = ComputePropertyTablesCommand(str(geometry_hdf_path))
            command.Execute(None)
        expected_path = landcover_hdf_path

    if compute_property_tables:
        _validate_property_tables_postcondition(geometry_hdf_path)

    with h5py.File(geometry_hdf_path, "r") as hdf:
        if "Geometry" not in hdf:
            raise RuntimeError("Geometry HDF has no /Geometry group after association.")
        attributes = hdf["Geometry"].attrs
        raw_filename = attributes.get("Land Cover Filename")
        raw_layer = attributes.get("Land Cover Layername")
        filename = (
            raw_filename.decode("utf-8", errors="replace")
            if isinstance(raw_filename, (bytes, np.bytes_))
            else str(raw_filename or "")
        )
        layer_name = (
            raw_layer.decode("utf-8", errors="replace")
            if isinstance(raw_layer, (bytes, np.bytes_))
            else str(raw_layer or "")
        )
    if not filename:
        raise RuntimeError("HEC-RAS did not persist Land Cover Filename.")
    if Path(filename.replace("\\", os.sep)).name.lower() != expected_path.name.lower():
        raise RuntimeError(
            "HEC-RAS persisted the wrong land-cover association: "
            f"{filename!r}, expected {expected_path.name!r}."
        )
    if layer_name.lower() != expected_path.stem.lower():
        raise RuntimeError(
            "HEC-RAS persisted the wrong land-cover layer name: "
            f"{layer_name!r}, expected {expected_path.stem!r}."
        )
    return geometry_hdf_path


def create_landcover(
    *,
    rasmap_path: Union[str, Path],
    source_path: Union[str, Path],
    classification_df: pd.DataFrame,
    cell_size: float,
    source_field: Optional[str],
    output_hdf_path: Union[str, Path],
    restrict_to_extent: Any,
    buffer_distance: float,
    hecras_version: str,
) -> dict[str, Any]:
    """Author and validate a land-cover layer using the selected HEC-RAS."""
    if not math.isfinite(float(cell_size)) or float(cell_size) <= 0:
        raise ValueError("cell_size must be a positive finite number.")

    rasmap_path = RasUtils.safe_resolve(Path(rasmap_path))
    source_path = RasUtils.safe_resolve(Path(source_path))
    output_hdf_path = RasUtils.safe_resolve(Path(output_hdf_path))
    output_hdf_path.parent.mkdir(parents=True, exist_ok=True)
    output_hdf_path.unlink(missing_ok=True)
    output_hdf_path.with_suffix(".tif").unlink(missing_ok=True)

    major = _major_version(hecras_version)
    kwargs = {
        "rasmap_path": rasmap_path,
        "source_path": source_path,
        "classification_df": classification_df,
        "cell_size": float(cell_size),
        "source_field": source_field,
        "output_hdf_path": output_hdf_path,
        "restrict_to_extent": restrict_to_extent,
        "buffer_distance": float(buffer_distance),
        "hecras_version": str(hecras_version),
    }
    if major <= 5:
        _create_legacy_landcover(**kwargs)
    else:
        _create_modern_landcover(**kwargs)

    validation = validate_native_landcover(
        output_hdf_path,
        expected_class_ids={
            int(value) for value in classification_df["class_id"].tolist()
        },
        legacy=major <= 5,
    )
    logger.info(
        "RASMapper %s authored land cover with raster classes %s",
        hecras_version,
        validation["raster_class_ids"],
    )
    return validation
