"""Windows Python worker launched by the Linux controller through Wine."""

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import tempfile
from pathlib import Path

# HEC-RAS compute-message line for a failed child program such as
# RasProcess.exe. Ras.exe still exits with code 0 after writing it.
CHILD_PROGRAM_ERROR = re.compile(r"^\s*Error with program:", re.IGNORECASE)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_ras_commander(wheel_path, expected_sha256):
    """Verify the retained wheel and the package imported by Windows Python."""
    actual_sha256 = sha256_file(wheel_path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError("retained ras-commander wheel SHA-256 does not match")
    distribution = importlib.metadata.distribution("ras-commander")
    direct_url_text = distribution.read_text("direct_url.json")
    if not direct_url_text:
        raise RuntimeError("ras-commander installation has no wheel provenance")
    archive = json.loads(direct_url_text).get("archive_info")
    if not isinstance(archive, dict):
        raise RuntimeError("ras-commander was not installed from a wheel archive")
    hashes = archive.get("hashes")
    installed_sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
    if installed_sha256 is None:
        legacy_hash = archive.get("hash")
        if isinstance(legacy_hash, str) and legacy_hash.startswith("sha256="):
            installed_sha256 = legacy_hash.split("=", 1)[1]
    if installed_sha256 != expected_sha256:
        raise RuntimeError("installed ras-commander does not match the retained wheel")
    return {
        "ras_commander_wheel_sha256": actual_sha256,
        "ras_commander_distribution_version": distribution.version,
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_state(path):
    """Return (size, mtime_ns) for an existing file, otherwise None."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns)


def child_program_errors(plan_hdf, state_before):
    """Return HEC-RAS child-program failures from a plan HDF written by this run.

    Ras.exe writes a small final plan HDF when a child program fails, for
    example ``Error with program: RasProcess.exe  Process Count = 1  Exit Code
    = -1073741819``, and exits with code 0. An HDF that is missing, unchanged
    since before the run, or unreadable yields an empty list.
    """
    state_after = file_state(plan_hdf)
    if state_after is None or state_after == state_before:
        return []
    try:
        from ras_commander import HdfResultsPlan

        text = HdfResultsPlan.get_compute_messages_hdf_only(Path(plan_hdf)) or ""
    except Exception:
        return []
    lines = [line.strip() for line in text.splitlines()]
    errors = [line for line in lines if CHILD_PROGRAM_ERROR.match(line)]
    if errors:
        errors.extend([line for line in lines if line.startswith("Unhandled Exception:")][:1])
    return errors


def run_worker(project, plan, ras_executable, ras_commander_wheel,
               expected_ras_commander_wheel_sha256, timeout, replace_generated,
               num_cores=2):
    """Prepare one plan with the public ras-commander preprocessing API."""
    if isinstance(num_cores, bool) or not isinstance(num_cores, int) or not 1 <= num_cores <= 8:
        raise ValueError("num_cores must be an integer from 1 to 8")
    from model_checks import preflight, normalize_inputs, validate_outputs

    provenance = verify_ras_commander(
        Path(ras_commander_wheel), expected_ras_commander_wheel_sha256
    )
    inputs, geometry_hdf, baseline, dependencies = preflight(project, plan)
    normalized = normalize_inputs(inputs)
    from ras_commander import (
        GeomPreprocessor,
        RasPlan,
        RasPreprocess,
        RasPrj,
        init_ras_project,
    )

    ras_object = RasPrj()
    init_ras_project(
        project,
        ras_version=ras_executable,
        ras_object=ras_object,
        load_results_summary=False,
        load_hdf_metadata=False,
        hide_intro=True,
        accept_tcu=True,
    )
    plan_path = RasPlan.get_plan_path(plan, ras_object=ras_object)
    if plan_path is None:
        raise RuntimeError("Selected plan " + plan + " could not be resolved")
    RasPlan.set_num_cores(
        plan_path, num_cores, ras_object=ras_object, refresh_dataframes=False
    )
    # set_num_cores updates existing keys; the typed 2D API also inserts a
    # missing key in each named mesh and the existing default settings block.
    RasPlan.set_2d_flow_options(
        plan_path, cores=num_cores, include_default=True, ras_object=ras_object
    )
    if RasPlan.get_plan_value(plan_path, "UNET D2 Cores", ras_object=ras_object) != num_cores:
        raise RuntimeError("Selected 2D plan has no effective UNET D2 Cores setting")
    GeomPreprocessor.clear_geompre_files(plan_path, ras_object=ras_object)
    RasPlan.update_run_flags(
        plan_path, geometry_preprocessor=True, ras_object=ras_object
    )
    plan_hdf = Path(project).with_suffix(".p" + plan + ".hdf")
    plan_hdf_before = file_state(plan_hdf)
    result = RasPreprocess.preprocess_plan(
        plan,
        ras_object=ras_object,
        max_wait=timeout,
        clear_existing=replace_generated,
        fix_line_endings=True,
    )
    # ras-commander releases before the child-program check report this case
    # as a successful natural completion with half-written artifacts.
    if getattr(result, "signal_source", None) == "natural_completion":
        child_errors = child_program_errors(plan_hdf, plan_hdf_before)
        if child_errors:
            raise RuntimeError(
                "HEC-RAS reported a failed child program before a readiness signal: "
                + "; ".join(child_errors)
            )
    if not result:
        raise RuntimeError(result.error or "HEC-RAS preprocessing failed")
    validation = validate_outputs(geometry_hdf, result.tmp_hdf_path, baseline)
    return {
        "success": bool(result),
        "plan": result.plan_number,
        "geometry": result.geometry_number,
        "num_cores": num_cores,
        "tmp_hdf_path": str(result.tmp_hdf_path) if result.tmp_hdf_path else None,
        "b_file_path": str(result.b_file_path) if result.b_file_path else None,
        "x_file_path": str(result.x_file_path) if result.x_file_path else None,
        "elapsed_seconds": result.elapsed_seconds,
        "signal_source": result.signal_source,
        "full_result_copied": result.full_result_copied,
        "timed_out": result.timed_out,
        "error": result.error,
        "input_preparation": {
            "line_endings": "CRLF",
            "normalized_files": normalized,
            "dependencies": dependencies,
        },
        "hdf_validation": validation,
        **provenance,
    }


def build_parser():
    parser = argparse.ArgumentParser(description="ras-commander Wine worker")
    parser.add_argument("--project", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--ras-executable", required=True)
    parser.add_argument("--ras-commander-wheel", required=True)
    parser.add_argument("--expected-ras-commander-wheel-sha256", required=True)
    parser.add_argument("--timeout", required=True, type=int)
    parser.add_argument("--num-cores", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--replace-generated", action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        payload = run_worker(
            args.project,
            args.plan,
            args.ras_executable,
            args.ras_commander_wheel,
            args.expected_ras_commander_wheel_sha256,
            args.timeout,
            args.replace_generated,
            num_cores=args.num_cores,
        )
    except Exception as exc:
        payload = {
            "success": False,
            "plan": args.plan,
            "geometry": None,
            "num_cores": args.num_cores,
            "tmp_hdf_path": None,
            "b_file_path": None,
            "x_file_path": None,
            "elapsed_seconds": 0.0,
            "signal_source": None,
            "full_result_copied": False,
            "timed_out": False,
            "error": type(exc).__name__ + ": " + str(exc),
            "ras_commander_wheel_sha256": None,
            "ras_commander_distribution_version": None,
        }
    write_json(args.result, payload)
    return 0 if payload["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
