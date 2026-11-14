"""Opt-in, real-Docker transport check; this does not execute HEC-RAS.

Set RAS_COMMANDER_NETWORK_CANARY_IMAGE to a locally built image with this
Dockerfile (the test supplies the entrypoint script through its job mount)::

    FROM python:3.12-slim
    ENTRYPOINT ["python", "/job/network_canary.py"]
    CMD []
"""

import os
import textwrap

import pytest

from ras_commander import RasDocker


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("RAS_COMMANDER_NETWORK_CANARY_IMAGE"),
    reason="set RAS_COMMANDER_NETWORK_CANARY_IMAGE to a Python image with the canary entrypoint",
)
def test_preprocessing_container_has_only_loopback_network(tmp_path):
    """Observe the namespace inside the launched container, not its CLI flags."""
    project = tmp_path / "model.prj"
    project.write_text("Proj Title=Network transport canary\n", encoding="utf-8")
    (tmp_path / "network_canary.py").write_text(textwrap.dedent('''
        import argparse
        import hashlib
        import json
        from pathlib import Path

        parser = argparse.ArgumentParser()
        parser.add_argument("stage")
        parser.add_argument("--project", type=Path)
        parser.add_argument("--plan")
        parser.add_argument("--timeout")
        parser.add_argument("--run-id")
        parser.add_argument("--num-cores", type=int)
        args = parser.parse_args()
        interfaces = sorted(path.name for path in Path("/sys/class/net").iterdir())
        offline = interfaces == ["lo"]
        artifacts = []
        if offline:
            for suffix in (f".p{args.plan}.tmp.hdf", f".b{args.plan}", f".x{args.plan}"):
                path = args.project.with_suffix(suffix)
                data = b"Network-namespace canary; not a hydraulic result."
                path.write_bytes(data)
                artifacts.append({"path": path.name, "size_bytes": len(data),
                                  "sha256": hashlib.sha256(data).hexdigest()})
        receipt = {
            "schema": "ras-commander-job/v1", "run_id": args.run_id,
            "command": args.stage, "project": args.project.name,
            "plan": args.plan, "geometry": args.plan,
            "status": "succeeded" if offline else "failed",
            "arguments": {"num_cores": args.num_cores},
            "runtime": {"kind": "wine", "hec_ras_version": "6.6"},
            "result": {"timed_out": False, "full_result_copied": False},
            "artifacts": artifacts, "network_interfaces": interfaces,
        }
        if not offline:
            receipt["error"] = {"message": "preparation unexpectedly has a network interface"}
        path = args.project.parent / ".ras-commander/runs" / args.run_id / "prepare.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(receipt))
    '''), encoding="utf-8")
    result = RasDocker.preprocess_plan(
        project, "01", version="6.6", pull="never", timeout=30,
        image=os.environ["RAS_COMMANDER_NETWORK_CANARY_IMAGE"], run_id="offline-canary",
    )
    assert result.success, (result.error, result.receipt)
    assert result.receipt["network_interfaces"] == ["lo"]
