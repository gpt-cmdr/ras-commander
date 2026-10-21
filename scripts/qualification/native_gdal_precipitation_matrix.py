"""Compare configured-only, vendor GDAL, and Python/HDF precipitation routes.

Start with a real project already configured for cumulative NetCDF precipitation.
Each route uses a new copy and discards only that copy's selected unsteady HDF.
Do not use a project whose other meteorology depends on imported HDF-only data.
All model execution goes through the portable ras-commander request API.
"""

from __future__ import annotations

import argparse
import ast
import json
import hashlib
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys

from ras_commander import (
    RasPlan,
    RasPrj,
    RasPrecipHdf,
    RasPreprocess,
    RasUnsteady,
    init_ras_project,
)
from ras_commander.remote import RasExecutionRequest

PRECIP = "Event Conditions/Meteorology/Precipitation"


_GEOMETRY_AUDIT_DATES = {
    "Data Date",
    "Property Tables Last Computed",
    "Terrain File Date",
    "Land Cover File Date",
    "Land Cover Date Last Modified",
    "Infiltration File Date",
    "Infiltration Date Last Modified",
    "Percent Impervious File Date",
    "Percent Impervious Date Last Modified",
    "Sediment Bed Material File Date",
}


def _matches_compound_schema(record, names, formats):
    """Normalize only a recognized fixed-width vendor table schema."""
    try:
        fields = ast.literal_eval(record["dtype"])
        return len(fields) == len(names) and all(
            len(field) == 2
            and field[0] == name
            and isinstance(field[1], str)
            and re.fullmatch(fmt, field[1])
            for field, name, fmt in zip(fields, names, formats)
        )
    except (ValueError, TypeError, KeyError, IndexError, SyntaxError):
        return False


def _is_geometry_process_audit(path, record):
    """Recognize only the vendor's execution-history table, not physical inputs."""
    return path == "/Geometry/Compute Processes" and _matches_compound_schema(
        record,
        [
            "Process",
            "Filename",
            "File Date",
            "File Size",
            "File Version",
            "Arguments",
            "Compute Time",
            "Compute Time (ms)",
        ],
        [r"S[1-9][0-9]*"] * 3 + [r"[<>=|]?i4"] + [r"S[1-9][0-9]*"] * 3 + [r"[<>=|]?i4"],
    )


def _is_mannings_mapping(record):
    return _matches_compound_schema(
        record, ["Region ID", "Cell Index"], [r"[<>=|]?i4", r"[<>=|]?i4"]
    )


_MANNING_MAPPING = "/Geometry/Land Cover (Manning's n)/Internal Cells"


def _canonical_mapping_record(raw, rows):
    """Hash the exact multiset of region/cell pairs; retain duplicates."""
    if raw.get("shape") != [len(rows)] or any(
        len(row) != 2 or any(isinstance(x, bool) or not isinstance(x, int) for x in row)
        for row in rows
    ):
        raise ValueError("Invalid region/cell mapping receipt")
    payload = json.dumps(sorted(rows), separators=(",", ":")).encode()
    return {
        "method": "sorted-region-cell-pairs-v1",
        "rows": len(rows),
        "raw_sha256": raw["sha256"],
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _inspect_model_inputs(hdf_path):
    """Retain raw hashes and a canonical digest for the keyed cell mapping."""
    from ras_commander import HdfBase, HdfLandCover

    receipt = HdfBase.fingerprint_model_inputs(
        hdf_path, groups=("Geometry",), block_bytes=4 * 1024 * 1024
    )
    raw = receipt["datasets"].get(_MANNING_MAPPING)
    if raw and _is_mannings_mapping(raw):
        if len(raw["shape"]) != 1 or raw["shape"][0] > 1_000_000:
            raise ValueError(
                "Region/cell mapping exceeds qualification inspection limit"
            )
        mapping = HdfLandCover.get_mannings_region_cell_mapping(hdf_path)
        if mapping is None:
            raise RuntimeError("Existing region/cell mapping could not be inspected")
        receipt["canonical_tables"] = {
            _MANNING_MAPPING: _canonical_mapping_record(raw, mapping.values.tolist())
        }
    return receipt


def _geometry_layer_associations(receipt):
    """Read root layer bindings from an existing public-API fingerprint."""
    if not isinstance(receipt, dict):
        return None
    attributes = receipt.get("groups", {}).get("/Geometry", {}).get("attributes")
    if not isinstance(attributes, dict):
        return None
    return {
        key: value
        for key, value in attributes.items()
        if isinstance(key, str) and key.endswith((" Filename", " Layername"))
    }


def _geometry_comparison_record(receipt):
    """Compare physical inputs with named audit and keyed-row normalization."""
    if (
        not receipt
        or "/Geometry" not in receipt.get("groups", {})
        or not receipt.get("datasets")
    ):
        return None
    result = {"aliases": receipt.get("aliases", {}), "datasets": {}, "groups": {}}
    for section in ("datasets", "groups"):
        for path, record in receipt[section].items():
            if section == "datasets" and _is_geometry_process_audit(path, record):
                continue
            record = dict(record)
            canonical = receipt.get("canonical_tables", {}).get(path)
            if section == "datasets" and path == _MANNING_MAPPING and canonical:
                if (
                    not _is_mannings_mapping(record)
                    or canonical.get("method") != "sorted-region-cell-pairs-v1"
                    or canonical.get("raw_sha256") != record.get("sha256")
                    or record.get("shape") != [canonical.get("rows")]
                ):
                    return None
                record["sha256"] = canonical["sha256"]
            result[section][path] = dict(
                record,
                attributes={
                    key: value
                    for key, value in record.get("attributes", {}).items()
                    if key not in _GEOMETRY_AUDIT_DATES
                },
            )
    return result if result["datasets"] else None


def assess(report: dict) -> dict:
    """Require independent native import, failed empty control, and exact parity."""
    routes = report.get("routes", {})
    checks = {}
    empty = routes.get("configured_only", {})
    empty_error = str(
        ((empty.get("execution_receipt") or {}).get("compute_diagnostics") or {}).get(
            "first_error_line", ""
        )
    )
    checks["empty_control_fails"] = bool(
        empty.get("execution_returncode") not in (None, 0)
        and "event conditions" in empty_error.casefold()
        and PRECIP + "/Values" not in empty.get("final", {}).get("datasets", {})
    )
    native, control = routes.get("vendor_gdal", {}), routes.get("python_hdf", {})
    for name, row in (("vendor", native), ("python", control)):
        receipt = row.get("execution_receipt") or {}
        checks[name + "_compute_verified"] = bool(
            row.get("execution_returncode") == 0
            and receipt.get("success")
            and receipt.get("solver_verified")
        )
    for name, row in (("vendor", native), ("python", control)):
        checks[name + "_preprocess_verified"] = bool(
            row.get("preprocess_returncode") == 0
            and (row.get("preprocess") or {}).get("success")
            and row.get("temporary", {}).get("event_completed")
        )
    checks["native_import_recorded"] = (native.get("native_import") or {}).get(
        "success"
    ) is True
    checks["native_started_without_payload"] = (
        PRECIP + "/Imported Raster Data/Values"
        not in native.get("before_import", {}).get("datasets", {})
        and native.get("before_import", {}).get("exists") is True
    )
    for phase in ("after_import", "temporary", "final"):
        left = native.get(phase, {}).get("datasets", {})
        right = control.get(phase, {}).get("datasets", {})
        selected = [
            key
            for key in left
            if (
                key.endswith("/Values")
                or key.endswith("/Values (Vertical)")
                or key.endswith("/Timestamp")
                or key.endswith("/Cell Cumulative Precipitation Depth")
                or key.endswith("/Water Surface")
                or key.endswith("/Cell Hydraulic Depth")
            )
        ]
        required = (
            [
                PRECIP + "/Imported Raster Data/Values",
                PRECIP + "/Imported Raster Data/Values (Vertical)",
            ]
            if phase == "after_import"
            else [PRECIP + "/Values", PRECIP + "/Timestamp"]
        )
        complete = all(key in left and key in right for key in required)
        if phase == "final":
            complete = complete and all(
                any(key.endswith("/" + name) for key in left)
                for name in (
                    "Cell Cumulative Precipitation Depth",
                    "Water Surface",
                    "Cell Hydraulic Depth",
                )
            )
        checks[phase + "_exact_parity"] = (
            complete
            and bool(selected)
            and all(
                key in right
                and all(
                    left[key].get(field) == right[key].get(field)
                    for field in ("shape", "dtype", "sha256", "times", "semantics")
                )
                for key in selected
            )
        )
    final = native.get("final", {}).get("datasets", {})
    checks["positive_cell_rainfall"] = any(
        key.endswith("/Cell Cumulative Precipitation Depth")
        and row.get("final_nonzero", 0) > 0
        and (row.get("final_maximum") or 0) > 0
        for key, row in final.items()
    )
    checks["nonempty_hydraulics"] = any(
        key.endswith("/Cell Hydraulic Depth")
        and (row.get("maximum") or 0) > 0
        and row.get("finite_count", 0) > 0
        for key, row in final.items()
    )
    if report.get("qualification_protocol") == "native-gdal-v2-model-inputs":
        left = _geometry_comparison_record(native.get("model_inputs"))
        right = _geometry_comparison_record(control.get("model_inputs"))
        checks["compiled_geometry_exact_parity"] = left is not None and left == right
        if "source_geometry_associations" in report:
            expected = report["source_geometry_associations"]
            checks["compiled_geometry_exact_parity"] = (
                checks["compiled_geometry_exact_parity"]
                and isinstance(expected, dict)
                and bool(expected)
                and all(
                    isinstance(key, str)
                    and key.endswith((" Filename", " Layername"))
                    for key in expected
                )
                and all(
                    _geometry_layer_associations(route.get("model_inputs"))
                    == expected
                    for route in (native, control)
                )
            )
    return {"passed": all(checks.values()), "checks": checks}


def run(args) -> dict:
    source = args.source_project.absolute()
    if args.workspace.exists() and any(args.workspace.iterdir()):
        raise FileExistsError("Use an absent or empty workspace")
    args.workspace.mkdir(parents=True, exist_ok=True)
    args.report_directory.mkdir(parents=True, exist_ok=True)
    report = {
        "qualification_protocol": "native-gdal-v2-model-inputs",
        "source_project": str(source),
        "container_identity": args.container_identity,
        "routes": {},
    }
    for route in ("configured_only", "vendor_gdal", "python_hdf"):
        bundle = args.workspace / route
        project = bundle / "input"
        shutil.copytree(source.parent, project)
        ras = init_ras_project(
            project / source.name,
            ras_object=RasPrj(),
            load_results_summary=False,
            load_hdf_metadata=False,
            hide_intro=True,
        )
        row = ras.plan_df.loc[ras.plan_df["plan_number"] == args.plan].iloc[0]
        unsteady = RasPlan.get_unsteady_path(row["unsteady_number"], ras_object=ras)
        config = RasUnsteady.get_met_precipitation_config(unsteady)
        netcdf = project / Path(config["gdal_filename"].replace("\\", "/"))
        Path(str(unsteady) + ".hdf").unlink(missing_ok=True)
        RasUnsteady.configure_gridded_gdal_precipitation(
            unsteady, netcdf, config["gdal_group"], historic=True
        )
        evidence = {
            "before_import": RasPrecipHdf.inspect_gridded_precipitation(
                Path(str(unsteady) + ".hdf")
            )
        }
        report["routes"][route] = evidence
        if route == "vendor_gdal":
            evidence["native_import"] = RasUnsteady.import_gridded_gdal_precipitation(
                unsteady,
                units=args.units,
                data_type=args.data_type,
                hecras_dir=args.hecras_dir,
            )
        elif route == "python_hdf":
            RasUnsteady.set_gridded_precipitation(
                unsteady,
                netcdf,
                dataset_name=config["gdal_group"],
                units=args.units.removesuffix("/hr"),
                value_type="cumulative" if args.data_type == "cumulative" else "rate",
                historic=True,
                ras_object=ras,
            )
        evidence["after_import"] = RasPrecipHdf.inspect_gridded_precipitation(
            Path(str(unsteady) + ".hdf")
        )
        if route != "configured_only":
            if os.name == "nt":
                import dataclasses

                ras.ras_exe_path = Path(args.ras_executable)
                prep = RasPreprocess.preprocess_plan(
                    args.plan,
                    ras_object=ras,
                    max_wait=args.timeout,
                    require_linux_solver_ready=False,
                )
                evidence["preprocess"] = dataclasses.asdict(prep)
                evidence["preprocess_returncode"] = 0 if prep else 1
            else:
                if not args.windows_python:
                    raise ValueError(
                        "Linux/Wine qualification requires --windows-python"
                    )
                prefix = Path(os.environ.get("WINEPREFIX", ""))
                if (
                    not prefix.is_absolute()
                    or not (prefix / "dosdevices/z:").is_symlink()
                    or (prefix / "dosdevices/z:").resolve() != Path("/")
                ):
                    raise ValueError(
                        "Qualification requires a private Wine prefix with verified Z: root mapping"
                    )

                def windows(path):
                    return "Z:\\" + str(Path(path).absolute()).lstrip("/").replace(
                        "/", "\\"
                    )

                prep_response = bundle / "preprocess-response.json"
                prep_request = bundle / "preprocess-request.json"
                prep_request.write_text(
                    json.dumps(
                        {
                            "project": windows(project / source.name),
                            "executable": args.ras_executable,
                            "plan": args.plan,
                            "response": windows(prep_response),
                        }
                    )
                )
                worker = Path(__file__).with_name("native_gdal_preprocess_worker.py")
                with (args.report_directory / (route + "-preprocess.log")).open(
                    "w"
                ) as log:
                    prep = subprocess.run(
                        [
                            args.wine_executable,
                            args.windows_python,
                            windows(worker),
                            windows(prep_request),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=args.timeout + 300,
                    )
                evidence["preprocess_returncode"] = prep.returncode
                evidence["preprocess"] = (
                    json.loads(prep_response.read_text())
                    if prep_response.exists()
                    else None
                )
            if (
                not evidence.get("preprocess")
                or evidence["preprocess"].get("success") is not True
            ):
                evidence["error"] = (
                    "Preprocessing failed; no temporary HDF inspection or compute is permitted"
                )
                continue
            temporary = project / (source.stem + ".p" + args.plan + ".tmp.hdf")
            evidence["temporary"] = RasPrecipHdf.inspect_gridded_precipitation(
                temporary
            )
        request = RasExecutionRequest.create(
            execution_id="gdal-" + route,
            request_directory=bundle,
            source_project_path="input/" + source.name,
            plan_number=args.plan,
            output_directory="results",
            ras_executable=args.ras_executable,
            container_identity=args.container_identity,
            timeout_seconds=args.timeout,
        )
        request_path = request.write(bundle / "request.json")
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        with (args.report_directory / (route + "-engine.log")).open("w") as log:
            completed = subprocess.run(
                [
                    args.engine_python,
                    "-m",
                    "ras_commander.remote.execute_request",
                    "execute-request",
                    str(request_path),
                ],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=args.timeout + 300,
            )
        evidence["execution_returncode"] = completed.returncode
        receipt = bundle / "results/execution_receipt.json"
        evidence["execution_receipt"] = (
            json.loads(receipt.read_text()) if receipt.exists() else None
        )
        result = (
            bundle
            / "results/runtime_project"
            / (source.stem + ".p" + args.plan + ".hdf")
        )
        if (evidence["execution_receipt"] or {}).get("solver_verified") is True:
            evidence["final_temporary"] = RasPrecipHdf.inspect_gridded_precipitation(
                result.with_suffix(".tmp.hdf")
            )
            evidence["final"] = RasPrecipHdf.inspect_gridded_precipitation(result)
            evidence["model_inputs"] = _inspect_model_inputs(result)
        else:
            evidence["final_inspection_skipped"] = (
                "No verified terminal solver receipt; result files were not opened"
            )
        (args.report_directory / "report.json").write_text(
            json.dumps(report, indent=2, default=str)
        )
    report["assessment"] = assess(report)
    (args.report_directory / "report.json").write_text(
        json.dumps(report, indent=2, default=str)
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--plan", default="06")
    parser.add_argument("--hecras-dir", type=Path, required=True)
    parser.add_argument("--ras-executable", required=True)
    parser.add_argument("--container-identity", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--report-directory", type=Path, required=True)
    parser.add_argument("--units", choices=["mm", "in", "mm/hr", "in/hr"], default="mm")
    parser.add_argument(
        "--data-type", choices=["cumulative", "per-avg"], default="cumulative"
    )
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--engine-python", default=sys.executable)
    parser.add_argument("--windows-python")
    parser.add_argument("--wine-executable", default="wine")
    args = parser.parse_args()
    args.plan = args.plan.zfill(2)
    return 0 if run(args)["assessment"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
