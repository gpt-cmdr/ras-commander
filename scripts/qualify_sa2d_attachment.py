"""Collect native SA/2D attachment evidence in a new, disposable project copy.

Run under the clone's Python environment (or Wine Python in the qualified fleet
image). This is attachment evidence, not a seam-conveyance qualification.
"""

import argparse
import hashlib
import json
import shutil
import time
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from ras_commander import (
    HdfStruc,
    RasCmdr,
    RasPlan,
    RasPreprocess,
    RasPrj,
    RasTcu,
    RasUtils,
    init_ras_project,
)
from ras_commander.geom import GeomLateral


def _hashes(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not RasUtils.is_windows_reserved_name(path.name)
    }


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--plan-number", required=True)
    parser.add_argument("--ras-exe", type=Path, required=True)
    parser.add_argument("--max-wait", type=int, default=120)
    parser.add_argument(
        "--compute-start",
        type=datetime.fromisoformat,
        help="Optionally collect results connectivity with a five-minute compute; ISO date/time.",
    )
    args = parser.parse_args()
    source = args.project.resolve()
    destination = args.workspace.resolve()
    if destination == source or source in destination.parents:
        parser.error("Workspace must be separate from the immutable source project")
    if destination.exists():
        parser.error("Workspace must not already exist")
    if args.max_wait <= 0:
        parser.error("--max-wait must be positive")
    before = _hashes(source)
    shutil.copytree(source, destination, ignore=RasUtils.ignore_windows_reserved)
    ras_object = RasPrj()
    init_ras_project(
        destination,
        ras_version=str(args.ras_exe),
        ras_object=ras_object,
        hide_intro=True,
        load_results_summary=False,
        load_hdf_metadata=False,
    )
    plan = ras_object.plan_df.loc[
        ras_object.plan_df["plan_number"] == str(args.plan_number).zfill(2)
    ].iloc[0]
    geometry_number = str(plan["geometry_number"]).zfill(2)
    geometry = ras_object.geom_df.loc[
        ras_object.geom_df["geom_number"] == geometry_number
    ].iloc[0]
    geometry_path = Path(geometry["full_path"])
    expected = GeomLateral.get_connection_data(geometry_path)
    geometry_sha256 = hashlib.sha256(geometry_path.read_bytes()).hexdigest()
    tcu_before = RasTcu.status(ras_object=ras_object)
    start = time.monotonic()
    preprocess = RasPreprocess.preprocess_plan(
        args.plan_number,
        ras_object=ras_object,
        max_wait=args.max_wait,
    )
    receipt = {
        "source": str(source),
        "workspace": str(destination),
        "ras_exe": str(args.ras_exe),
        "preprocess": asdict(preprocess),
        "tcu_before": asdict(tcu_before),
        "tcu_after": asdict(RasTcu.status(ras_object=ras_object)),
        "tcu_method": "status only; script does not accept terms",
        "geometry_path": str(geometry_path),
        "geometry_sha256": geometry_sha256,
    }
    hdf_path = preprocess.tmp_hdf_path if preprocess.success else None
    if preprocess.success and args.compute_start is not None:
        RasPlan.update_simulation_date(
            args.plan_number,
            args.compute_start,
            args.compute_start + timedelta(minutes=5),
            ras_object=ras_object,
        )
        computed = RasCmdr.compute_plan(
            args.plan_number,
            ras_object=ras_object,
            force_rerun=True,
            max_runtime=args.max_wait,
            num_cores=1,
            force_geompre=True,
        )
        receipt["compute"] = asdict(computed)
        receipt["compute_start"] = args.compute_start.isoformat()
        receipt["compute_minutes"] = 5
        plan = ras_object.plan_df.loc[
            ras_object.plan_df["plan_number"] == str(args.plan_number).zfill(2)
        ].iloc[0]
        if computed.success:
            value = plan["HDF_Results_Path"]
            if isinstance(value, (str, Path)):
                candidate = Path(value)
                if candidate.is_file():
                    hdf_path = candidate
        else:
            hdf_path = None
    receipt["source_unchanged"] = before == _hashes(source)
    receipt["source_hashes"] = before
    receipt["elapsed_seconds"] = time.monotonic() - start
    attachments = None
    if hdf_path:
        try:
            attachments = HdfStruc.get_connection_attachments(hdf_path, expected)
        except (OSError, ValueError, KeyError) as error:
            receipt["attachment_read_error"] = str(error)
    if hdf_path:
        receipt["native_hdf_sha256"] = hashlib.sha256(
            Path(hdf_path).read_bytes()
        ).hexdigest()
    receipt["attachments"] = (
        attachments.to_dict(orient="records") if attachments is not None else []
    )
    (destination / "sa2d_attachment_receipt.json").write_text(
        json.dumps(receipt, indent=2, default=str),
        encoding="utf-8",
    )
    if not receipt["source_unchanged"]:
        raise RuntimeError("Source project bytes changed during qualification")
    if (
        attachments is None
        or attachments.empty
        or not attachments.attachment_verified.all()
    ):
        raise SystemExit(
            "CONNECTION_ATTACHMENT_UNVERIFIED; review sa2d_attachment_receipt.json"
        )


if __name__ == "__main__":
    _main()
