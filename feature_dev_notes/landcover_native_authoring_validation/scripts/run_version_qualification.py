"""End-to-end native land-cover qualification for one HEC-RAS version.

Run each HEC-RAS version in a fresh Python process.  Pythonnet cannot safely
unload one RasMapperLib generation and bind another in the same process.

The harness performs three linked tests on disposable copies of the real
Muncie project:

1. native layer authoring, association, property-table generation, and solve;
2. a plain-text geometry base-Manning edit followed by native regeneration;
3. a native sidecar Manning edit (or 5.0.7 native rebuild) followed by native
   regeneration.

Large projects and result HDFs remain outside git.  The emitted JSON records
paths, hashes, native schema, raster counts, final-array deltas, and all gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
import rasterio

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ras_commander import (  # noqa: E402
    GeomLandCover,
    HdfLandCover,
    RasCmdr,
    RasMap,
    init_ras_project,
)
from ras_commander.hdf.HdfResultsPlan import HdfResultsPlan  # noqa: E402
from ras_commander.results.ResultsParser import ResultsParser  # noqa: E402

DEFAULT_SOURCE_PROJECT = Path(
    r"G:\RasProcess Testing\wine_compare\Muncie_simple_test\Muncie.prj"
)
DEFAULT_PROBE_RASTER = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "muncie_landcover_probe.tif"
)
DEFAULT_PROBE_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "muncie_landcover_probe.json"
)
DEFAULT_RUN_ROOT = Path(r"C:\CLB\landcover-version-matrix")

PLAN_NUMBER = "04"
GEOMETRY_NUMBER = "04"
MESH_NAME = "2D Interior Area"
MATERIAL_TOLERANCE = 1.0e-4
DELTA_TOLERANCE = 1.0e-5

CLASSIFICATION_ROWS = [
    {
        "source_value": 1,
        "class_id": 1,
        "class_name": "Building",
        "mannings_n": 10.0,
        "percent_impervious": 100.0,
    },
    {
        "source_value": 2,
        "class_id": 2,
        "class_name": "Medium Density Residential",
        "mannings_n": 0.08,
        "percent_impervious": 70.0,
    },
    {
        "source_value": 3,
        "class_id": 3,
        "class_name": "Open Space",
        "mannings_n": 0.04,
        "percent_impervious": 20.0,
    },
    {
        "source_value": 4,
        "class_id": 4,
        "class_name": "Park",
        "mannings_n": 0.06,
        "percent_impervious": 10.0,
    },
    {
        "source_value": 5,
        "class_id": 5,
        "class_name": "Trees",
        "mannings_n": 0.12,
        "percent_impervious": 5.0,
    },
    {
        "source_value": 6,
        "class_id": 6,
        "class_name": "Urban",
        "mannings_n": 0.10,
        "percent_impervious": 80.0,
    },
    {
        "source_value": 7,
        "class_id": 7,
        "class_name": "Qualification Probe",
        "mannings_n": 0.07,
        "percent_impervious": 0.0,
    },
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_version(version: str) -> str:
    return (
        str(version)
        .strip()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
    )


def _major_version(version: str) -> int:
    return int(str(version).strip().split(".", 1)[0])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").strip("\x00")
    if isinstance(value, np.ndarray):
        return value.tolist()
    if pd.isna(value):
        return None
    return value


def _material_values(values: np.ndarray) -> list[float]:
    finite = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return []
    ordered = np.sort(finite)
    distinct = [float(ordered[0])]
    for value in ordered[1:]:
        if abs(float(value) - distinct[-1]) > MATERIAL_TOLERANCE:
            distinct.append(float(value))
    return distinct


def _value_count(values: np.ndarray, target: float) -> int:
    array = np.asarray(values, dtype=np.float64).reshape(-1)
    return int(np.count_nonzero(np.isfinite(array) & (np.abs(array - target) <= DELTA_TOLERANCE)))


def _array_delta(before: np.ndarray, after: np.ndarray) -> dict[str, Any]:
    before = np.asarray(before, dtype=np.float64)
    after = np.asarray(after, dtype=np.float64)
    if before.shape != after.shape:
        return {
            "same_shape": False,
            "before_shape": list(before.shape),
            "after_shape": list(after.shape),
            "changed_count": None,
            "max_abs_delta": None,
        }
    finite = np.isfinite(before) & np.isfinite(after)
    delta = np.abs(after - before)
    changed = finite & (delta > DELTA_TOLERANCE)
    return {
        "same_shape": True,
        "before_shape": list(before.shape),
        "after_shape": list(after.shape),
        "changed_count": int(np.count_nonzero(changed)),
        "max_abs_delta": float(np.max(delta[finite])) if np.any(finite) else None,
    }


def _read_solver_arrays(plan_hdf_path: Path) -> dict[str, np.ndarray]:
    base = f"Geometry/2D Flow Areas/{MESH_NAME}"
    with h5py.File(plan_hdf_path, "r") as hdf:
        face = np.asarray(hdf[f"{base}/Faces Area Elevation Values"][()])
        cell_path = f"{base}/Cells Center Manning's n"
        cells = (
            np.asarray(hdf[cell_path][()])
            if cell_path in hdf
            else np.array([], dtype=np.float64)
        )
    return {
        "cells": cells.reshape(-1),
        "face_mannings": face[:, 3].reshape(-1),
        "face_non_mannings": face[:, :3],
    }


def _summarize_arrays(arrays: dict[str, np.ndarray]) -> dict[str, Any]:
    return {
        "cell_count": int(arrays["cells"].size),
        "cell_material_values": _material_values(arrays["cells"]),
        "face_profile_row_count": int(arrays["face_mannings"].size),
        "face_material_values": _material_values(arrays["face_mannings"]),
    }


def _read_hdf_attributes(path: Path, object_path: str = "/") -> dict[str, Any]:
    with h5py.File(path, "r") as hdf:
        obj = hdf if object_path == "/" else hdf[object_path]
        return {str(key): _json_value(value) for key, value in obj.attrs.items()}


def _read_raster(path: Path) -> dict[str, Any]:
    with rasterio.open(path) as src:
        values = src.read(1)
        counts = Counter(values.reshape(-1).tolist())
        return {
            "width": int(src.width),
            "height": int(src.height),
            "dtype": str(src.dtypes[0]),
            "nodata": _json_value(src.nodata),
            "tiled": bool(src.profile.get("tiled")),
            "compression": str(src.profile.get("compress", "")).lower(),
            "overviews": src.overviews(1),
            "class_counts": {
                str(int(value)): int(count)
                for value, count in sorted(counts.items())
            },
            "sha256": _sha256(path),
        }


def _read_sidecar(path: Path, legacy: bool) -> dict[str, Any]:
    with h5py.File(path, "r") as hdf:
        keys = sorted(hdf.keys())
        if legacy:
            ids = [int(value) for value in hdf["IDs"][()]]
            names = [_json_value(value) for value in hdf["Names"][()]]
            values = [float(value) for value in hdf["ManningsN"][()]]
        else:
            raster_map = hdf["Raster Map"][()]
            variables = hdf["Variables"][()]
            ids = [int(row["ID"]) for row in raster_map]
            names = [_json_value(row["Name"]) for row in raster_map]
            variable_names = [_json_value(row["Name"]) for row in variables]
            variable_values = {
                name: float(row["ManningsN"])
                for name, row in zip(variable_names, variables)
            }
            values = [variable_values.get(name, float("nan")) for name in names]
        root_attributes = {
            str(key): _json_value(value) for key, value in hdf.attrs.items()
        }
    return {
        "keys": keys,
        "ids": ids,
        "names": names,
        "mannings_n": values,
        "root_attributes": root_attributes,
        "sha256": _sha256(path),
    }


def _region_block_hash(geometry_path: Path) -> str:
    lines = geometry_path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("LCMann Region Name=")
        ),
        None,
    )
    if start is None:
        return hashlib.sha256(b"").hexdigest()
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].startswith(
                ("Chan Stop", "Geom Raster", "GIS ", "Use User", "User Specified")
            )
        ),
        len(lines),
    )
    payload = "\n".join(lines[start:end]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _project_paths(project_file: Path) -> dict[str, Path]:
    folder = project_file.parent
    project_name = project_file.stem
    return {
        "project": project_file,
        "geometry_text": folder / f"{project_name}.g{GEOMETRY_NUMBER}",
        "geometry_hdf": folder / f"{project_name}.g{GEOMETRY_NUMBER}.hdf",
        "plan_hdf": folder / f"{project_name}.p{PLAN_NUMBER}.hdf",
        "terrain_hdf": folder / "Terrain" / "Terrain.hdf",
        "landcover_hdf": folder / "LandCover" / "LandCover.hdf",
        "landcover_tif": folder / "LandCover" / "LandCover.tif",
    }


def _copy_project(source_project: Path, destination: Path) -> Path:
    if destination.exists():
        raise FileExistsError(destination)
    shutil.copytree(source_project.parent, destination)
    project = destination / source_project.name
    if not project.exists():
        raise FileNotFoundError(project)
    return project


def _classification_table(probe_mannings_n: float = 0.07) -> pd.DataFrame:
    rows = [dict(row) for row in CLASSIFICATION_ROWS]
    rows[-1]["mannings_n"] = float(probe_mannings_n)
    return pd.DataFrame(rows)


def _required_hdf_datasets(project_name: str, major: int) -> dict[str, list[str]]:
    base = f"Geometry/2D Flow Areas/{MESH_NAME}"
    required = [f"{base}/Faces Area Elevation Values"]
    if major >= 6:
        required.append(f"{base}/Cells Center Manning's n")
    return {f"{project_name}.p{PLAN_NUMBER}.hdf": required}


def _compute(
    *,
    ras_object: Any,
    project_paths: dict[str, Path],
    version: str,
) -> dict[str, Any]:
    result = RasCmdr.compute_plan(
        PLAN_NUMBER,
        ras_object=ras_object,
        force_rerun=True,
        # Some completed legacy releases emit non-fatal lines containing
        # "ERROR" (for example the 6.0 River Edge Lines attribute warning).
        # Qualify completion and requested solver arrays independently below,
        # while retaining the parser result as evidence.
        verify=False,
        required_hdf_datasets=_required_hdf_datasets(
            project_paths["project"].stem,
            _major_version(version),
        ),
    )
    compute_messages = (
        HdfResultsPlan.get_compute_messages_hdf_only(project_paths["plan_hdf"])
        if project_paths["plan_hdf"].exists()
        else ""
    )
    parsed_messages = ResultsParser.parse_compute_messages(compute_messages)
    completion_verified = bool(
        project_paths["plan_hdf"].exists()
        and "Complete Process" in compute_messages
        and RasCmdr._verify_completion(
            project_paths["plan_hdf"],
            check_errors=False,
        )
    )
    payload = {
        "success": bool(result.success),
        "completion_verified": completion_verified,
        "compute_message_parse": _json_value(parsed_messages),
        "artifact_verification_passed": _json_value(
            getattr(result, "artifact_verification_passed", None)
        ),
        "verification_failures": [
            str(item) for item in getattr(result, "verification_failures", [])
        ],
    }
    if not payload["success"]:
        raise RuntimeError(f"HEC-RAS compute failed: {payload}")
    if not payload["completion_verified"]:
        raise RuntimeError(f"HEC-RAS completion was not verified: {payload}")
    if not project_paths["plan_hdf"].exists():
        raise RuntimeError(
            f"Expected plan HDF was not created: {project_paths['plan_hdf']}"
        )
    return payload


def _author_associate_compute(
    *,
    project_file: Path,
    probe_raster: Path,
    probe_manifest: dict[str, Any],
    version: str,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    major = _major_version(version)
    paths = _project_paths(project_file)
    ras_object = init_ras_project(
        project_file,
        ras_version=version,
        load_results_summary=False,
        hide_intro=True,
        accept_tcu=True,
    )
    authored = RasMap.add_landcover_layer(
        project_file,
        probe_raster,
        _classification_table(),
        cell_size=5.0,
        output_hdf_path=paths["landcover_hdf"],
        hecras_version=version,
        ras_object=ras_object,
    )
    if Path(authored).resolve() != paths["landcover_hdf"].resolve():
        raise RuntimeError(
            f"Native authoring returned {authored}, "
            f"expected {paths['landcover_hdf']}."
        )

    RasMap.associate_geometry_layers(
        project_file,
        paths["geometry_hdf"],
        landcover_hdf_path=paths["landcover_hdf"],
        terrain_hdf_path=paths["terrain_hdf"],
        hecras_version=version,
        ras_object=ras_object,
    )
    RasMap.recompute_property_tables(
        project_file,
        paths["geometry_hdf"],
        hecras_version=version,
        ras_object=ras_object,
    )
    compute = _compute(
        ras_object=ras_object,
        project_paths=paths,
        version=version,
    )
    audit = HdfLandCover.audit_final_mannings_n(
        paths["plan_hdf"],
        mesh_name=MESH_NAME,
        tolerance=MATERIAL_TOLERANCE,
        minimum_distinct_values=2,
    )
    arrays = _read_solver_arrays(paths["plan_hdf"])
    raster = _read_raster(paths["landcover_tif"])
    if raster["class_counts"] != probe_manifest["class_counts"]:
        raise RuntimeError(
            f"Native output class counts are {raster['class_counts']}, "
            f"expected {probe_manifest['class_counts']}."
        )
    if raster["nodata"] is not None:
        raise RuntimeError("Native output declares GDAL NoData.")
    if not raster["tiled"] or raster["compression"] != "deflate":
        raise RuntimeError(f"Native output TIFF layout is not qualified: {raster}")
    if raster["overviews"] != [2, 4, 8]:
        raise RuntimeError(
            f"Native output overviews are {raster['overviews']}, "
            "expected [2, 4, 8]."
        )

    sidecar = _read_sidecar(paths["landcover_hdf"], legacy=major <= 5)
    expected_ids = list(range(8))
    if sidecar["ids"] != expected_ids:
        raise RuntimeError(
            f"Native sidecar IDs are {sidecar['ids']}, expected {expected_ids}."
        )
    association = RasMap.get_hdf_geometry_association(paths["plan_hdf"])
    baseline = {
        "project": str(project_file),
        "paths": {key: str(value) for key, value in paths.items()},
        "compute": compute,
        "audit": audit.to_dict(orient="records"),
        "arrays": _summarize_arrays(arrays),
        "raster": raster,
        "sidecar": sidecar,
        "association": association,
        "geometry_root_attributes": _read_hdf_attributes(
            paths["geometry_hdf"],
            "Geometry",
        ),
        "plan_root_attributes": _read_hdf_attributes(paths["plan_hdf"]),
        "plan_geometry_attributes": _read_hdf_attributes(
            paths["plan_hdf"],
            "Geometry",
        ),
        "hashes": {
            "geometry_text": _sha256(paths["geometry_text"]),
            "geometry_hdf": _sha256(paths["geometry_hdf"]),
            "plan_hdf": _sha256(paths["plan_hdf"]),
            "landcover_hdf": _sha256(paths["landcover_hdf"]),
            "landcover_tif": _sha256(paths["landcover_tif"]),
            "region_block": _region_block_hash(paths["geometry_text"]),
        },
    }
    return baseline, arrays


def _run_geometry_base_edit(
    *,
    baseline_project: Path,
    destination: Path,
    baseline_arrays: dict[str, np.ndarray],
    baseline: dict[str, Any],
    version: str,
) -> dict[str, Any]:
    project_file = _copy_project(baseline_project, destination)
    paths = _project_paths(project_file)
    ras_object = init_ras_project(
        project_file,
        ras_version=version,
        load_results_summary=False,
        hide_intro=True,
        accept_tcu=True,
    )
    table = GeomLandCover.get_base_mannings_n(paths["geometry_text"])
    urban = table["Land Cover Name"].str.casefold() == "urban"
    if int(urban.sum()) != 1:
        raise RuntimeError(
            f"Expected one Urban base row; found {int(urban.sum())}."
        )
    table.loc[urban, "Base Mannings n Value"] = 0.11
    GeomLandCover.replace_base_mannings_n(
        paths["geometry_text"],
        table,
        backup=True,
    )

    authored_table = GeomLandCover.get_base_mannings_n(paths["geometry_text"])
    if len(authored_table) != 6:
        raise RuntimeError(
            f"Geometry base table has {len(authored_table)} rows, expected 6."
        )
    if set(authored_table["Table Number"].astype(str)) != {"6"}:
        raise RuntimeError(
            "Geometry base table did not preserve LCMann Table=6 row count."
        )
    if _region_block_hash(paths["geometry_text"]) != baseline["hashes"]["region_block"]:
        raise RuntimeError("Geometry base edit changed the regional override block.")
    if _sha256(paths["landcover_hdf"]) != baseline["hashes"]["landcover_hdf"]:
        raise RuntimeError("Geometry base edit changed the land-cover HDF.")
    if _sha256(paths["landcover_tif"]) != baseline["hashes"]["landcover_tif"]:
        raise RuntimeError("Geometry base edit changed the land-cover TIFF.")

    RasMap.recompute_property_tables(
        project_file,
        paths["geometry_hdf"],
        hecras_version=version,
        ras_object=ras_object,
    )
    compute = _compute(
        ras_object=ras_object,
        project_paths=paths,
        version=version,
    )
    arrays = _read_solver_arrays(paths["plan_hdf"])
    cell_delta = _array_delta(baseline_arrays["cells"], arrays["cells"])
    face_delta = _array_delta(
        baseline_arrays["face_mannings"],
        arrays["face_mannings"],
    )
    face_non_n_delta = _array_delta(
        baseline_arrays["face_non_mannings"],
        arrays["face_non_mannings"],
    )
    if face_delta["changed_count"] in {None, 0}:
        raise RuntimeError("Geometry base edit did not change final face Manning values.")
    if face_non_n_delta["changed_count"] != 0:
        raise RuntimeError(
            "Geometry base edit changed non-Manning face property-table columns."
        )
    if _major_version(version) >= 6 and cell_delta["changed_count"] in {None, 0}:
        raise RuntimeError("Geometry base edit did not change final cell Manning values.")
    return {
        "project": str(project_file),
        "compute": compute,
        "arrays": _summarize_arrays(arrays),
        "delta": {
            "cells": cell_delta,
            "face_mannings": face_delta,
            "face_non_mannings": face_non_n_delta,
        },
        "target_counts": {
            "before_cell_urban_0.10": _value_count(
                baseline_arrays["cells"],
                0.10,
            ),
            "after_cell_urban_0.11": _value_count(arrays["cells"], 0.11),
            "after_cell_region_urban_0.09": _value_count(arrays["cells"], 0.09),
            "before_face_urban_0.10": _value_count(
                baseline_arrays["face_mannings"],
                0.10,
            ),
            "after_face_urban_0.11": _value_count(
                arrays["face_mannings"],
                0.11,
            ),
            "after_face_region_urban_0.09": _value_count(
                arrays["face_mannings"],
                0.09,
            ),
        },
        "hashes": {
            "geometry_text": _sha256(paths["geometry_text"]),
            "geometry_hdf": _sha256(paths["geometry_hdf"]),
            "plan_hdf": _sha256(paths["plan_hdf"]),
            "landcover_hdf": _sha256(paths["landcover_hdf"]),
            "landcover_tif": _sha256(paths["landcover_tif"]),
            "region_block": _region_block_hash(paths["geometry_text"]),
        },
    }


def _run_sidecar_edit(
    *,
    baseline_project: Path,
    destination: Path,
    baseline_arrays: dict[str, np.ndarray],
    baseline: dict[str, Any],
    probe_raster: Path,
    version: str,
) -> dict[str, Any]:
    major = _major_version(version)
    project_file = _copy_project(baseline_project, destination)
    paths = _project_paths(project_file)
    ras_object = init_ras_project(
        project_file,
        ras_version=version,
        load_results_summary=False,
        hide_intro=True,
        accept_tcu=True,
    )
    geometry_text_before = _sha256(paths["geometry_text"])
    raster_before = _sha256(paths["landcover_tif"])

    if major <= 5:
        expected_failure = None
        try:
            HdfLandCover.set_landcover_raster_map(
                paths["landcover_hdf"],
                {"Qualification Probe": 0.077},
                ras_object=ras_object,
                hecras_version=version,
            )
        except NotImplementedError as exc:
            expected_failure = str(exc)
        if expected_failure is None:
            raise RuntimeError(
                "HEC-RAS 5.x native sidecar setter did not fail closed."
            )
        RasMap.add_landcover_layer(
            project_file,
            probe_raster,
            _classification_table(probe_mannings_n=0.077),
            cell_size=5.0,
            output_hdf_path=paths["landcover_hdf"],
            hecras_version=version,
            ras_object=ras_object,
        )
        RasMap.associate_geometry_layers(
            project_file,
            paths["geometry_hdf"],
            landcover_hdf_path=paths["landcover_hdf"],
            terrain_hdf_path=paths["terrain_hdf"],
            hecras_version=version,
            ras_object=ras_object,
        )
        edit = {
            "mode": "native-rebuild",
            "expected_setter_failure": expected_failure,
        }
    else:
        edit = HdfLandCover.set_landcover_raster_map(
            paths["landcover_hdf"],
            {"Qualification Probe": 0.077},
            ras_object=ras_object,
            hecras_version=version,
        )
        edit["mode"] = "native-parameter-table"

    if _sha256(paths["geometry_text"]) != geometry_text_before:
        raise RuntimeError("Native sidecar edit changed the geometry text file.")
    if major >= 6 and _sha256(paths["landcover_tif"]) != raster_before:
        raise RuntimeError("Modern native sidecar edit changed the classification TIFF.")

    RasMap.recompute_property_tables(
        project_file,
        paths["geometry_hdf"],
        hecras_version=version,
        ras_object=ras_object,
    )
    compute = _compute(
        ras_object=ras_object,
        project_paths=paths,
        version=version,
    )
    arrays = _read_solver_arrays(paths["plan_hdf"])
    cell_delta = _array_delta(baseline_arrays["cells"], arrays["cells"])
    face_delta = _array_delta(
        baseline_arrays["face_mannings"],
        arrays["face_mannings"],
    )
    face_non_n_delta = _array_delta(
        baseline_arrays["face_non_mannings"],
        arrays["face_non_mannings"],
    )
    if face_delta["changed_count"] in {None, 0}:
        raise RuntimeError("Sidecar edit did not change final face Manning values.")
    if face_non_n_delta["changed_count"] != 0:
        raise RuntimeError(
            "Sidecar edit changed non-Manning face property-table columns."
        )
    if major >= 6 and cell_delta["changed_count"] in {None, 0}:
        raise RuntimeError("Sidecar edit did not change final cell Manning values.")

    sidecar = _read_sidecar(paths["landcover_hdf"], legacy=major <= 5)
    probe_index = next(
        (
            index
            for index, name in enumerate(sidecar["names"])
            if str(name).casefold() == "qualification probe"
        ),
        None,
    )
    if probe_index is None or not np.isclose(
        sidecar["mannings_n"][probe_index],
        0.077,
        atol=1.0e-6,
        rtol=1.0e-6,
    ):
        raise RuntimeError(
            "Native sidecar did not persist Qualification Probe n=0.077."
        )
    return {
        "project": str(project_file),
        "edit": edit,
        "compute": compute,
        "arrays": _summarize_arrays(arrays),
        "delta": {
            "cells": cell_delta,
            "face_mannings": face_delta,
            "face_non_mannings": face_non_n_delta,
        },
        "target_counts": {
            "before_cell_probe_0.070": _value_count(
                baseline_arrays["cells"],
                0.070,
            ),
            "after_cell_probe_0.077": _value_count(arrays["cells"], 0.077),
            "before_face_probe_0.070": _value_count(
                baseline_arrays["face_mannings"],
                0.070,
            ),
            "after_face_probe_0.077": _value_count(
                arrays["face_mannings"],
                0.077,
            ),
        },
        "sidecar": sidecar,
        "hashes": {
            "geometry_text": _sha256(paths["geometry_text"]),
            "geometry_hdf": _sha256(paths["geometry_hdf"]),
            "plan_hdf": _sha256(paths["plan_hdf"]),
            "landcover_hdf": _sha256(paths["landcover_hdf"]),
            "landcover_tif": _sha256(paths["landcover_tif"]),
            "region_block": _region_block_hash(paths["geometry_text"]),
        },
        "baseline_hashes": baseline["hashes"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--source-project",
        type=Path,
        default=DEFAULT_SOURCE_PROJECT,
    )
    parser.add_argument(
        "--probe-raster",
        type=Path,
        default=DEFAULT_PROBE_RASTER,
    )
    parser.add_argument(
        "--probe-manifest",
        type=Path,
        default=DEFAULT_PROBE_MANIFEST,
    )
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    version = str(args.version)
    source_project = args.source_project.resolve()
    probe_raster = args.probe_raster.resolve()
    probe_manifest_path = args.probe_manifest.resolve()
    if not source_project.exists():
        raise FileNotFoundError(source_project)
    if not probe_raster.exists():
        raise FileNotFoundError(probe_raster)
    if not probe_manifest_path.exists():
        raise FileNotFoundError(probe_manifest_path)
    probe_manifest = json.loads(probe_manifest_path.read_text(encoding="utf-8"))

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    version_root = (
        args.run_root.resolve()
        / f"{_safe_version(version)}-{timestamp}"
    )
    version_root.mkdir(parents=True, exist_ok=False)
    output_json = (
        args.output_json.resolve()
        if args.output_json is not None
        else version_root / "qualification.json"
    )
    output_json.parent.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": 1,
        "hecras_version": version,
        "started_at_utc": _utc_now(),
        "source_project": str(source_project),
        "probe_raster": str(probe_raster),
        "probe_manifest": str(probe_manifest_path),
        "run_root": str(version_root),
        "passed": False,
    }
    try:
        baseline_project = _copy_project(
            source_project,
            version_root / "baseline",
        )
        baseline, baseline_arrays = _author_associate_compute(
            project_file=baseline_project,
            probe_raster=probe_raster,
            probe_manifest=probe_manifest,
            version=version,
        )
        geometry_edit = _run_geometry_base_edit(
            baseline_project=baseline_project,
            destination=version_root / "geometry-base-edit",
            baseline_arrays=baseline_arrays,
            baseline=baseline,
            version=version,
        )
        sidecar_edit = _run_sidecar_edit(
            baseline_project=baseline_project,
            destination=version_root / "sidecar-edit",
            baseline_arrays=baseline_arrays,
            baseline=baseline,
            probe_raster=probe_raster,
            version=version,
        )
        report.update(
            {
                "baseline": baseline,
                "geometry_base_edit": geometry_edit,
                "sidecar_edit": sidecar_edit,
                "passed": True,
            }
        )
    except Exception as exc:
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        report["finished_at_utc"] = _utc_now()
        output_json.write_text(
            json.dumps(report, indent=2, default=_json_value) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(report, indent=2, default=_json_value))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
