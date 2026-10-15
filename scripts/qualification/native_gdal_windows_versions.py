"""Qualify installed HEC-RAS GDAL imports/solves from a verified healthy share.

Run under the authorized Windows owner context. All staged inputs, intermediate
files and reports stay under --root; installed vendor binaries stay in place.
"""

from __future__ import annotations
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback


def _windows_volume_guid(root: Path) -> str:
    """Query only volume metadata in the actual executing logon context."""
    import ctypes
    from ctypes import wintypes
    from pathlib import PureWindowsPath

    anchor = PureWindowsPath(str(root)).anchor
    if not anchor:
        raise ValueError("Expected an absolute Windows task root")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetVolumeNameForVolumeMountPointW
    query.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    query.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(1024)
    if not query(anchor, buffer, len(buffer)):
        raise OSError(ctypes.get_last_error(), "Cannot establish task volume identity")
    return buffer.value


def _verify_root_volume(root: Path, expected: str | None) -> dict | None:
    """Fail before directory creation when an expected task disk is aliased."""
    if expected is None:
        return None
    actual = _windows_volume_guid(root)
    if actual.casefold() != expected.casefold():
        raise RuntimeError(
            f"Task root volume mismatch: expected {expected!r}, got {actual!r}"
        )
    return {"expected": expected, "actual": actual, "verified": True}


def _provision_tcu(executable, *, operator_acceptance=False, acceptance_export=None):
    """Inspect by default; seed only with explicit assent or a trusted export."""
    from ras_commander import RasTcu

    action = RasTcu.accept if operator_acceptance else RasTcu.status
    result = {"tcu": dataclasses.asdict(action(ras_version=str(executable)))}
    if result["tcu"]["accepted"] is not True and acceptance_export:
        payload = acceptance_export.read_bytes()
        result["tcu_export_sha256"] = hashlib.sha256(payload).hexdigest()
        result["tcu"] = dataclasses.asdict(
            RasTcu.import_acceptance(json.loads(payload), ras_version=str(executable))
        )
    return result


def _implementation_hashes():
    """Resolve source provenance independently of the chosen output directory."""
    source_root = Path(__file__).resolve().parents[2]
    return {
        str(path.relative_to(source_root).as_posix()): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in [
            Path(__file__).resolve(),
            source_root / "scripts/qualification/native_gdal_precipitation_matrix.py",
            source_root / "ras_commander/hdf/HdfBase.py",
            source_root / "ras_commander/hdf/_fingerprint.py",
            source_root / "ras_commander/_process_inspection.py",
            source_root / "ras_commander/RasCmdr.py",
            source_root / "ras_commander/RasPreprocess.py",
            source_root / "ras_commander/ComputeResults.py",
            source_root / "ras_commander/RasTcu.py",
            source_root / "ras_commander/_tcu_gui.py",
            source_root / "ras_commander/_plan_windows.py",
            source_root / "ras_commander/_native_precip.py",
            source_root / "ras_commander/_native_helper.py",
            source_root / "ras_commander/native/RasMetImportHelper.cs",
        ]
        if path.is_file()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent)
    parser.add_argument("--source-project", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument(
        "--semantics-source",
        type=Path,
        help="Five-frame APCP_surface rate NetCDF; defaults to ROOT/rain.nc",
    )
    parser.add_argument(
        "--semantics-template",
        type=Path,
        help="Clean unsteady text template; defaults to ROOT/Davis.u01",
    )
    parser.add_argument("--phase", choices=["sources", "full"], required=True)
    parser.add_argument("--versions", nargs="+", required=True)
    parser.add_argument("--run-label", default="round1")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--cores", type=int, default=1)
    parser.add_argument(
        "--routes",
        nargs="+",
        choices=["configured_only", "python_hdf", "vendor_gdal", "vendor_rate"],
        default=["configured_only", "python_hdf", "vendor_gdal", "vendor_rate"],
        help="Subset runs are diagnostics and cannot qualify a release",
    )
    parser.add_argument(
        "--operator-accept-tcu",
        action="store_true",
        help="Explicit operator assent: seed release acceptance and accept exact owned TCU dialogs",
    )
    parser.add_argument(
        "--complete-geometry",
        action="store_true",
        help="Also run mapper CompleteGeometry per route; default uses native plan preprocessing and preserves geometry associations",
    )
    parser.add_argument(
        "--disable-omp-affinity",
        action="store_true",
        help="Set process-local KMP_AFFINITY=disabled through RasCmdr",
    )
    parser.add_argument(
        "--capture-windows",
        action="store_true",
        help="Read-only exact-plan Windows dialog sampling during compute",
    )
    parser.add_argument(
        "--execution-platform", choices=["windows", "wine"], default="windows"
    )
    parser.add_argument(
        "--tcu-acceptance",
        type=Path,
        help="Trusted operator export from RasTcu.export_acceptance",
    )
    parser.add_argument(
        "--expected-volume-guid",
        help="Require this Windows volume GUID before any task-root writes; use for private VHD runs",
    )
    args = parser.parse_args()
    root = args.root.absolute()
    out = root / ("windows-" + args.phase + "-" + args.run_label)
    root_volume = _verify_root_volume(root, args.expected_volume_guid)
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(root))
    # A staged package beside the workspace takes precedence when provided;
    # repository/installed imports also support a separate output directory.
    log = (out / "driver.log").open("a", buffering=1)
    sys.stdout = log
    sys.stderr = log
    from ras_commander import (
        RasPrj,
        RasUnsteady,
        RasPrecipHdf,
        RasPreprocess,
        RasCmdr,
        RasTcu,
        RasPlan,
        HdfBase,
        init_ras_project,
    )
    from ras_commander._legal_dialogs import TCU_DIALOG_TITLE
    import numpy as np
    import xarray as xr
    from scripts.qualification.native_gdal_source_semantics import run as source_cases
    from scripts.qualification.native_gdal_precipitation_matrix import (
        assess,
        _inspect_model_inputs,
    )

    report = {
        "disable_omp_affinity": args.disable_omp_affinity,
        "execution_platform": args.execution_platform,
        "cores": args.cores,
        "force_geompre": args.complete_geometry,
        "operator_accept_tcu": args.operator_accept_tcu,
        "diagnostic_scope": set(args.routes)
        != {"configured_only", "python_hdf", "vendor_gdal", "vendor_rate"},
        "phase": args.phase,
        "source_project": str(args.source_project),
        "storage_root": str(root),
        "root_volume": root_volume,
        "versions": {},
    }
    report["implementation_sha256"] = _implementation_hashes()

    def save():
        (out / "report.json").write_text(json.dumps(report, indent=2, default=str))

    for version in args.versions:
        work = out / version.replace(" ", "_")
        work.mkdir(exist_ok=False)
        row = {"version": version, "started": time.time()}
        report["versions"][version] = row
        save()
        install = (
            args.runtime_root or Path("C:/Program Files (x86)/HEC/HEC-RAS")
        ) / version
        try:
            row["runtime_sha256"] = hashlib.sha256(
                (install / "Ras.exe").read_bytes()
            ).hexdigest()
            row.update(
                _provision_tcu(
                    install / "Ras.exe",
                    operator_acceptance=args.operator_accept_tcu,
                    acceptance_export=args.tcu_acceptance,
                )
            )
            save()
            if args.phase == "sources":
                positive, negative = source_cases(
                    work,
                    install,
                    work,
                    args.semantics_source or root / "rain.nc",
                    args.semantics_template or root / "Davis.u01",
                )
                row.update(positive=positive, negative=negative, passed=True)
            else:
                if not args.source_project:
                    raise ValueError("full phase requires --source-project")
                row["qualification_protocol"] = "native-gdal-v2-model-inputs"
                row["routes"] = {}
                for route in args.routes:
                    r = {"route": route}
                    row["routes"][route] = r
                    save()
                    try:
                        project = work / route
                        shutil.copytree(args.source_project.parent, project)
                        # Fail before execution if source text points outside the
                        # verified share. Relative dependencies stay in its copy.
                        import re

                        for path in project.iterdir():
                            if path.is_file() and (
                                path.suffix.lower() in {".prj", ".rasmap"}
                                or re.fullmatch(r"\.[pug]\d\d", path.suffix, re.I)
                            ):
                                text = path.read_text(errors="replace")
                                if re.search(r"(?i)(?<![\w])[a-bd-z]:[\\/]", text):
                                    raise ValueError(
                                        "Absolute drive reference in staged project: "
                                        + str(path)
                                    )
                        ras = init_ras_project(
                            project / args.source_project.name,
                            str(install / "Ras.exe"),
                            ras_object=RasPrj(),
                            load_results_summary=False,
                            load_hdf_metadata=False,
                            hide_intro=True,
                        )
                        RasPlan.set_num_cores("06", args.cores, ras_object=ras)
                        r["plan_core_settings_before_preprocessing"] = {
                            key: RasPlan.get_plan_value("06", key, ras_object=ras)
                            for key in ["UNET D1 Cores", "UNET D2 Cores", "PS Cores"]
                        }
                        if (
                            r["plan_core_settings_before_preprocessing"].get(
                                "UNET D2 Cores"
                            )
                            != args.cores
                        ):
                            raise RuntimeError(
                                "Requested 2D core count was not present before preprocessing"
                            )
                        plan = ras.plan_df.loc[ras.plan_df.plan_number == "06"].iloc[0]
                        u = RasPlan.get_unsteady_path(
                            plan["unsteady_number"], ras_object=ras
                        )
                        config = RasUnsteady.get_met_precipitation_config(u)
                        nc = project / Path(config["gdal_filename"].replace("\\", "/"))
                        if not nc.resolve().is_relative_to(project.resolve()):
                            raise ValueError("Raster escaped staged project")
                        if route == "vendor_rate":
                            with xr.open_dataset(nc) as ds:
                                ds = ds.load()
                            data = ds[config["gdal_group"]].values.astype("float64")
                            hours = np.diff(ds.time.values) / np.timedelta64(1, "h")
                            rates = np.zeros_like(data)
                            rates[1:] = np.diff(data, axis=0) / hours[:, None, None]
                            ds[config["gdal_group"]].values[:] = rates
                            ds[config["gdal_group"]].attrs.update(
                                units="mm/hr",
                                long_name="Period-average precipitation rate",
                                standard_name="precipitation_flux",
                                source_value_type="rate",
                            )
                            nc = project / "native-period-average.nc"
                            ds.to_netcdf(nc)
                        Path(str(u) + ".hdf").unlink(missing_ok=True)
                        RasUnsteady.configure_gridded_gdal_precipitation(
                            u, nc, config["gdal_group"], historic=True, ras_object=ras
                        )
                        r["before_import"] = RasPrecipHdf.inspect_gridded_precipitation(
                            Path(str(u) + ".hdf")
                        )
                        if route.startswith("vendor"):
                            r["native_import"] = (
                                RasUnsteady.import_gridded_gdal_precipitation(
                                    u,
                                    units="mm/hr" if route == "vendor_rate" else "mm",
                                    data_type="per-avg"
                                    if route == "vendor_rate"
                                    else "cumulative",
                                    hecras_dir=install,
                                )
                            )
                        elif route == "python_hdf":
                            RasUnsteady.set_gridded_precipitation(
                                u,
                                nc,
                                dataset_name=config["gdal_group"],
                                units="mm",
                                value_type="cumulative",
                                historic=True,
                                ras_object=ras,
                            )
                        r["after_import"] = RasPrecipHdf.inspect_gridded_precipitation(
                            Path(str(u) + ".hdf")
                        )
                        save()
                        import threading

                        stop_preprocess_windows = threading.Event()
                        preprocess_sampler = None
                        if args.capture_windows:

                            def sample_preprocessing(
                                ras_scope=ras,
                                path_scope=work
                                / (route + "-preprocessing-windows.jsonl"),
                                stop_scope=stop_preprocess_windows,
                            ):
                                with path_scope.open("a", buffering=1) as journal:
                                    while not stop_scope.wait(2):
                                        try:
                                            snapshot = RasCmdr.inspect_plan_windows(
                                                "06",
                                                ras_object=ras_scope,
                                                max_text_chars=16384,
                                            )
                                        except Exception:
                                            snapshot = {"error": traceback.format_exc()}
                                        journal.write(
                                            json.dumps(
                                                {
                                                    "time": time.time(),
                                                    "snapshot": snapshot,
                                                },
                                                default=str,
                                            )
                                            + "\n"
                                        )

                            preprocess_sampler = threading.Thread(
                                target=sample_preprocessing, daemon=True
                            )
                            preprocess_sampler.start()
                        try:
                            prep = RasPreprocess.preprocess_plan(
                                "06",
                                ras_object=ras,
                                max_wait=min(30, args.timeout)
                                if route == "configured_only"
                                and args.execution_platform == "windows"
                                else args.timeout,
                                clear_existing=True,
                                require_linux_solver_ready=False,
                                accept_tcu=args.operator_accept_tcu,
                            )
                        finally:
                            stop_preprocess_windows.set()
                            if preprocess_sampler is not None:
                                preprocess_sampler.join(timeout=30)
                        r["preprocessing_target"] = "native_windows"
                        r["preprocess"] = dataclasses.asdict(prep)
                        r["preprocess_returncode"] = 0 if prep else 1
                        temporary_path = project / "BaldEagleDamBrk.p06.tmp.hdf"
                        if not prep:
                            inventory = RasCmdr.inspect_plan_processes(
                                "06", ras_object=ras
                            )
                            r["failed_preprocess_inventory"] = inventory.to_dict()
                            if not inventory.complete or inventory.matched:
                                raise RuntimeError(
                                    "Temporary HDF inspection refused: failed preprocessing left uncertain/active owned processes"
                                )
                            if not RasPreprocess._wait_stopped_artifacts_quiet(
                                (temporary_path,)
                            ):
                                raise RuntimeError(
                                    "Temporary HDF inspection refused: failed preprocessing artifact is unsettled"
                                )
                        r["temporary"] = RasPrecipHdf.inspect_gridded_precipitation(
                            temporary_path
                        )
                        save()
                        if not prep:
                            r["execution_returncode"] = 1
                            r["execution_receipt"] = {
                                "success": False,
                                "solver_verified": False,
                                "compute_diagnostics": {
                                    "first_error_line": str(r["preprocess"])
                                },
                            }
                            r["final"] = r["temporary"]
                            continue
                        compiled = r["temporary"].get("solver_core_settings", {})
                        if any(
                            any(
                                int(value) != args.cores
                                for value in np.asarray(setting).reshape(-1)
                            )
                            for setting in compiled.values()
                        ):
                            raise RuntimeError(
                                "Compiled preprocessing core settings differ from requested count"
                            )
                        import threading

                        stop_windows = threading.Event()
                        sampler = None
                        if args.capture_windows or args.operator_accept_tcu:

                            def sample_windows(
                                ras_scope=ras,
                                path_scope=work / (route + "-windows.jsonl"),
                                stop_scope=stop_windows,
                            ):
                                accepted = set()
                                with path_scope.open("a", buffering=1) as journal:
                                    while not stop_scope.wait(2):
                                        try:
                                            snapshot = RasCmdr.inspect_plan_windows(
                                                "06",
                                                ras_object=ras_scope,
                                                max_text_chars=16384,
                                            )
                                        except Exception:
                                            snapshot = {"error": traceback.format_exc()}
                                        journal.write(
                                            json.dumps(
                                                {
                                                    "time": time.time(),
                                                    "snapshot": snapshot,
                                                },
                                                default=str,
                                            )
                                            + "\n"
                                        )
                                        if (
                                            args.operator_accept_tcu
                                            and snapshot.get("complete") is True
                                        ):
                                            for window in snapshot.get("windows", []):
                                                if (
                                                    window.get("title", "")
                                                    .strip()
                                                    .casefold()
                                                    != TCU_DIALOG_TITLE.casefold()
                                                ):
                                                    continue
                                                identity = (
                                                    window["pid"],
                                                    window["create_time"],
                                                )
                                                if identity in accepted:
                                                    continue
                                                accepted.add(identity)
                                                try:
                                                    receipt = RasTcu.accept_running_terms(
                                                        identity[0],
                                                        expected_create_time=identity[
                                                            1
                                                        ],
                                                        ras_version=ras_scope.ras_exe_path,
                                                        operator_acceptance=True,
                                                        timeout=30,
                                                    )
                                                    event = {"tcu_acceptance": receipt}
                                                except Exception:
                                                    event = {
                                                        "tcu_acceptance_error": traceback.format_exc()
                                                    }
                                                journal.write(
                                                    json.dumps(
                                                        {"time": time.time(), **event},
                                                        default=str,
                                                    )
                                                    + "\n"
                                                )

                            sampler = threading.Thread(
                                target=sample_windows, daemon=True
                            )
                            sampler.start()
                        try:
                            result = RasCmdr.compute_plan(
                                "06",
                                ras_object=ras,
                                num_cores=args.cores,
                                clear_geompre=True,
                                force_geompre=args.complete_geometry,
                                force_rerun=True,
                                verify=True,
                                max_runtime=args.timeout,
                                disable_omp_affinity=args.disable_omp_affinity,
                            )
                        finally:
                            stop_windows.set()
                            if sampler is not None:
                                sampler.join(timeout=30)

                        r["compute_result"] = {
                            "success": result.success,
                            "completion_verified": result.completion_verified,
                            "execution_details": result.execution_details,
                        }
                        r["execution_returncode"] = 0 if result else 1
                        r["execution_receipt"] = {
                            "success": result.success,
                            "solver_verified": result.completion_verified is True,
                            "compute_diagnostics": result.execution_details,
                        }
                        if (result.execution_details or {}).get(
                            "solver_quiescence_confirmed"
                        ) is not True:
                            raise RuntimeError(
                                "Final HDF inspection refused without confirmed solver quiescence"
                            )
                        r["final"] = RasPrecipHdf.inspect_gridded_precipitation(
                            project / "BaldEagleDamBrk.p06.hdf"
                        )
                        r["model_inputs"] = _inspect_model_inputs(
                            project / "BaldEagleDamBrk.p06.hdf"
                        )
                    except Exception:
                        r["error"] = traceback.format_exc()
                    finally:
                        save()
                row["assessment"] = assess(row)
                alternate = dict(
                    row,
                    routes=dict(
                        row["routes"], vendor_gdal=row["routes"].get("vendor_rate", {})
                    ),
                )
                row["rate_assessment"] = assess(alternate)
                row["passed"] = (
                    not report["diagnostic_scope"]
                    and row["assessment"]["passed"]
                    and row["rate_assessment"]["passed"]
                )
        except Exception:
            row["error"] = traceback.format_exc()
            row["passed"] = False
        finally:
            row["finished"] = time.time()
            save()
    (out / "DONE").write_text("finished")
    return 0 if all(row.get("passed") for row in report["versions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
