"""Tests for opt-in in-job result HDF slimming in RasApptainer.render_job.

Render-time tests (spec validation, request hashing, staging, receipt validation) run on
every platform. The execution tests run the rendered job.sh with bash, the fake 5.0.7
``rasUnsteady64`` from test_apptainer_507 (extended here to write 2D series), a fake
``apptainer`` that maps binds to host paths, and the real staged slim engine. They qualify
the job script's ordering, fallback and receipt contract, not HEC-RAS.
"""

import copy
import hashlib
import importlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from ras_commander import HdfSlim, RasApptainer

importlib.import_module("ras_commander.RasApptainer")
RA = sys.modules["ras_commander.RasApptainer"]  # the package re-exports the class by this name

from test_apptainer_507 import (  # fixtures and fake solver
    C_BYTES,
    _fake_engine_dir,
    _write_executable,
    posix_site_profile,
    profile507,
    project507,
)

BASH = shutil.which("bash")
# sha256 of JOB_SCRIPT_TEMPLATE as released before in-job slimming (slim placeholders empty).
UNSLIMMED_TEMPLATE_SHA256 = "4e2ec21e704f52bc406b24f0b66f8e35951181804fc76ca303ee46a2af97a46d"
SERIES = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/2D Flow Areas"
PLUVIAL = ("Cell Cumulative Precipitation Depth", "Cell Cumulative Excess Depth")

__all__ = ["profile507", "project507"]  # re-exported pytest fixtures


def test_job_script_template_unchanged_when_slim_is_off():
    off = RA.JOB_SCRIPT_TEMPLATE
    for key, value in RA._slim_values(None).items():
        assert value == ""
        off = off.replace(f"@{key}@", value)
    assert hashlib.sha256(off.encode("utf-8")).hexdigest() == UNSLIMMED_TEMPLATE_SHA256


# ---- spec validation and rendering --------------------------------------------------


def test_slim_spec_defaults_to_preset_and_solver_image():
    spec = RA._slim_spec({})
    assert spec["policy"] == HdfSlim.list_presets()["inundation-mapping"]
    assert spec["image"] is None and spec["image_sha256"] is None
    assert spec["engine_sha256"] == HdfSlim.implementation_sha256()
    assert spec["policy_sha256"] == hashlib.sha256(RA._slim_policy_bytes(spec["policy"])).hexdigest()
    assert RA._slim_spec(None) is None


def test_slim_spec_resolves_custom_policy_and_extra_series():
    spec = RA._slim_spec({"policy": {"required": ["Water Surface"], "keep_if_present": ["Depth"]},
                          "extra_series": ["Face Flow"], "image": "/opt/slim.sif",
                          "image_sha256": "a" * 64})
    assert spec["policy"]["keep"] == ["Water Surface", "Face Flow", "Depth"]
    assert spec["image"] == "/opt/slim.sif" and spec["image_sha256"] == "a" * 64


@pytest.mark.parametrize("bad, fragment", [
    ({"image": "relative.sif", "image_sha256": "a" * 64}, "absolute path"),
    ({"image": "/opt/slim.sif", "image_sha256": "ABC"}, "64 lowercase hex"),
    ({"image": "/opt/slim.sif"}, "64 lowercase hex"),
    ({"image_sha256": "a" * 64}, "needs hdf_slim.image"),
    ({"args": ["--no-source-hash"]}, "unknown keys"),
    ({"policy": "no-such-preset"}, "unknown preset"),
    ({"policy": {"required": []}}, "hdf_slim.policy"),
    ({"extra_series": "Depth"}, "list of names"),
    ({"policy": {"required": ["Water Surface"], "time_chunk_steps": 0}}, "positive"),
])
def test_slim_spec_validation(bad, fragment):
    with pytest.raises(ValueError, match=fragment):
        RA._slim_spec(bad)


def test_render_job_stages_engine_and_policy_only_when_enabled(project507, profile507, tmp_path):
    off = RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "off")
    on = RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "on",
                                 hdf_slim={"extra_series": ["Face Cumulative Volume"]})
    off_req = json.loads((off.job_directory / "job.json").read_text(encoding="utf-8"))["request"]
    on_req = json.loads((on.job_directory / "job.json").read_text(encoding="utf-8"))["request"]
    assert "hdf_slim" not in off_req and not (off.job_directory / "hdf_slim").exists()
    spec = on_req["hdf_slim"]
    assert spec["policy"]["extra_series"] == ["Face Cumulative Volume"]
    assert off.request_sha256 != on.request_sha256
    staged = on.job_directory / "hdf_slim"
    assert sorted(p.name for p in staged.iterdir()) == ["hdf_slim_engine.py", "hdf_slim_policy.json"]
    assert hashlib.sha256((staged / "hdf_slim_engine.py").read_bytes()).hexdigest() == spec["engine_sha256"]
    assert json.loads((staged / "hdf_slim_policy.json").read_text(encoding="utf-8")) == spec["policy"]
    off_script = off.script_path.read_text(encoding="utf-8")
    on_script = on.script_path.read_text(encoding="utf-8")
    assert "slim_results" not in off_script and "hdf_slim" not in off_script
    assert "slim_results" in on_script and "copy_back || { slim_restore_full && copy_back; }" in on_script
    assert 'SLIM_IMAGE="$IMAGE"' in on_script and spec["engine_sha256"] in on_script
    assert "--no-source-hash" not in on_script


def test_render_job_rejects_bad_spec_before_staging(project507, profile507, tmp_path):
    with pytest.raises(ValueError):
        RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "bad",
                                hdf_slim={"policy": "nope"})
    assert not (tmp_path / "bad").exists() or not any((tmp_path / "bad").iterdir())


def test_load_request_detects_tampered_slim_files(project507, profile507, tmp_path):
    job = RasApptainer.render_job(project507, "TEST", 8, profile507, tmp_path / "on", hdf_slim={})
    RA._load_request(job)
    policy = job.job_directory / "hdf_slim" / "hdf_slim_policy.json"
    policy.write_text(policy.read_text(encoding="utf-8").replace('"deflate_level": 4', '"deflate_level": 5'),
                      encoding="utf-8", newline="\n")
    with pytest.raises(RuntimeError, match="hdf_slim"):
        RA._load_request(job)


# ---- receipt validation -------------------------------------------------------------


def _base_receipt(outputs):
    return {
        "schema": RA.RECEIPT_SCHEMA, "request_sha256": "1" * 64, "job_name": "x",
        "slurm_job_id": "4242", "node": "n1", "container_identity": "sif:sha256:" + "2" * 64,
        "apptainer_image_sha256": "2" * 64, "status": "succeeded", "reason_code": "COMPLETED",
        "exit_code": 0, "started_at": "2026-11-18T00:00:00+00:00",
        "finished_at": "2026-11-18T00:01:00+00:00", "elapsed_seconds": 60, "num_cores": 4,
        "input_hashes": {}, "outputs": outputs, "copy_verified": True,
        "dss_output_rewrite": None, "detail": "",
    }


def _completed_receipt():
    slim = {"sha256": "3" * 64, "size_bytes": 10}
    man = {"sha256": "4" * 64, "size_bytes": 5}
    r = _base_receipt({"project/TEST.p08.hdf": slim, "project/TEST.p08.hdf_slim.json": man})
    r["full_hdf"] = {"name": "TEST.p08.hdf", "bytes": 99, "sha256": "5" * 64}
    r["hdf_slim"] = {
        "output_path": "project/TEST.p08.hdf", "status": "completed",
        "reason_code": "HDF_SLIM_VERIFIED", "copy_back_sha256_verified": True,
        "manifest": {"path": "project/TEST.p08.hdf_slim.json", "bytes": 5, "sha256": "4" * 64},
        "bytes": 10, "sha256": "3" * 64, "policy": {"keep": ["Water Surface"]},
        "applied_keep": {"Area1": []}, "implementation_sha256": "6" * 64, "image_sha256": "2" * 64,
    }
    return r


def test_validate_receipt_accepts_slim_blocks():
    RA.validate_receipt(_completed_receipt())
    r = _base_receipt({"project/TEST.p08.hdf": {"sha256": "5" * 64, "size_bytes": 99}})
    r["full_hdf"] = {"name": "TEST.p08.hdf", "bytes": 99, "sha256": "5" * 64}
    r["hdf_slim"] = {"output_path": "project/TEST.p08.hdf", "status": "failed",
                     "reason_code": "HDF_SLIM_RUNTIME_UNAVAILABLE",
                     "copy_back_sha256_verified": False, "image_sha256": "2" * 64}
    RA.validate_receipt(r)
    RA.validate_receipt(_base_receipt({"project/TEST.p08.hdf": {"sha256": "5" * 64, "size_bytes": 1}}))


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop("full_hdf"),
    lambda r: r.pop("hdf_slim"),
    lambda r: r["hdf_slim"].update(copy_back_sha256_verified="true"),
    lambda r: r["hdf_slim"].update(sha256="7" * 64),
    lambda r: r["hdf_slim"]["manifest"].update(path="project/TEST.p08.hdf.hdf_slim.json"),
    lambda r: r["hdf_slim"].update(status="verified"),
    lambda r: r["hdf_slim"].update(kept_series=[]),
    lambda r: r["hdf_slim"].update(output_path="project/OTHER.p08.hdf"),
    lambda r: r["outputs"].pop("project/TEST.p08.hdf_slim.json"),
    lambda r: r["full_hdf"].update(bytes=0),
    lambda r: r["hdf_slim"].update(status="failed", reason_code="HDF_SLIM_VERIFY_FAILED",
                                   copy_back_sha256_verified=False),
])
def test_validate_receipt_rejects_inconsistent_slim_blocks(mutate):
    r = _completed_receipt()
    mutate(r)
    with pytest.raises(ValueError):
        RA.validate_receipt(r)


def _request(spec):
    return {"project": "TEST", "plan": "08", "hdf_slim": spec,
            "profile": {"apptainer_image_sha256": "2" * 64}}


def test_collect_binds_slim_blocks_to_request():
    spec = RA._slim_spec({})
    receipt = _completed_receipt()
    receipt["hdf_slim"].update(implementation_sha256=spec["engine_sha256"], policy=spec["policy"])
    assert RA._slim_collect_problems(receipt, _request(spec)) == []
    assert RA._slim_collect_problems(receipt, _request(None)) == [
        "receipt has hdf_slim blocks but the request did not enable slimming"]
    plain = _base_receipt({})
    assert RA._slim_collect_problems(plain, _request(None)) == []
    assert RA._slim_collect_problems(plain, _request(spec)) == [
        "request enabled hdf_slim but the receipt has no hdf_slim blocks"]
    for change in ({"implementation_sha256": "9" * 64}, {"policy": {"keep": []}}, {"image_sha256": "8" * 64}):
        bad = copy.deepcopy(receipt)
        bad["hdf_slim"].update(change)
        assert RA._slim_collect_problems(bad, _request(spec))
    other = copy.deepcopy(receipt)
    other["full_hdf"]["name"] = "TEST.p09.hdf"
    assert RA._slim_collect_problems(other, _request(spec))
    separate = dict(spec, image="/opt/slim.sif", image_sha256="7" * 64)
    assert RA._slim_collect_problems(receipt, _request(separate))  # receipt used the solver image


# ---- execution (fake solver, fake apptainer, real staged slim engine) -------------------

_SOLVER_2D_PY = r'''
import os, sys, h5py, numpy as np
assert sys.argv[1:] == ["TEST.c02", "b08"], sys.argv
with open("TEST.c02", "rb") as fh:
    assert fh.read() == bytes.fromhex("@CHEX@")
with h5py.File("TEST.p08.tmp.hdf", "r+") as hdf:
    base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
    hdf.create_dataset(base + "/Time Date Stamp",
                       data=np.array([b"02JAN1900 00:00:00", b"03JAN1900 00:00:00"]))
    area = base + "/2D Flow Areas/Area1/"
    t = 2
    hdf.create_dataset(area + "Water Surface", data=np.linspace(0, 1, t * 300, dtype="f4").reshape(t, 300))
    if os.environ.get("FAKE_SOLVER") != "no-flow":
        hdf.create_dataset(area + "Face Flow", data=np.linspace(0, 5, t * 500, dtype="f4").reshape(t, 500))
        hdf.create_dataset(area + "Face Velocity", data=np.ones((t, 500), dtype="f4"))
    hdf.create_dataset(area + "Cell Courant", data=np.ones((t, 300), dtype="f4"))
    for name in ("Cell Cumulative Precipitation Depth", "Cell Cumulative Excess Depth"):
        hdf.create_dataset(area + name, data=np.cumsum(np.ones((t, 300), dtype="f4"), axis=0))
print("Finished Unsteady Flow Simulation")
'''

# Stand-in for the image's python3: runs scripts with the host interpreter. FAKE_SLIM_MODE
# "noruntime" fails the h5py/numpy probe; "badsource" corrupts the manifest the engine wrote.
_FAKE_PYTHON = r'''import json, os, runpy, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_SLIM_MODE", "ok")
if args[:1] == ["-c"]:
    sys.exit(1 if mode == "noruntime" else 0)
sys.argv = args
code = 0
try:
    runpy.run_path(args[0], run_name="__main__")
except SystemExit as exc:
    code = exc.code or 0
if args[0].endswith("hdf_slim_engine.py") and mode == "badsource":
    man = args[args.index("--manifest") + 1]
    with open(man, encoding="utf-8") as f:
        m = json.load(f)
    m["source"]["sha256"] = "0" * 64
    with open(man, "w", encoding="utf-8") as f:
        json.dump(m, f)
sys.exit(code)
'''

# Stand-in for ``apptainer exec``: maps --bind container paths to host paths. engine.sh runs
# as in test_apptainer_507; python3 commands run through _FAKE_PYTHON.
_FAKE_APPTAINER = r'''#!/bin/bash
binds=()
while [ $# -gt 0 ]; do
  case "$1" in
    exec|--cleanenv) shift ;;
    --pwd) shift 2 ;;
    --bind) binds+=("$2"); shift 2 ;;
    *) break ;;
  esac
done
shift  # image
map() {
  local a=$1 b host cont
  for b in "${binds[@]}"; do
    host=${b%%:*}; cont=${b#*:}; cont=${cont%:ro}
    case "$a" in "$cont"|"$cont"/*) printf '%s' "$host${a#"$cont"}"; return ;; esac
  done
  printf '%s' "$a"
}
if [ "$1 $2" = "bash /control/engine.sh" ]; then
  work=$(map /job); control=$(map /control)
  sed "s#^cd /job #cd \"$work\" #" "$control/engine.sh" > "$control/../engine.local.sh"
  exec bash "$control/../engine.local.sh"
fi
args=(); for a in "$@"; do args+=("$(map "$a")"); done
[ "${args[0]}" = python3 ] || { echo "unexpected exec: $*" >&2; exit 97; }
exec @PY@ @FAKEPY@ "${args[@]:1}"
'''


def _site(project507, profile507, tmp_path, *, spec=None, slim_image_digest=None):
    root = tmp_path / "site"
    root.mkdir()
    engine_dir = _fake_engine_dir(root)
    (engine_dir / "fake_solver.py").write_text(_SOLVER_2D_PY.replace("@CHEX@", C_BYTES.hex()),
                                               encoding="utf-8")
    image = root / "image.sif"
    image.write_bytes(b"fake 5.0.7 native image")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    fake_py = root / "fake_python.py"
    fake_py.write_text(_FAKE_PYTHON, encoding="utf-8")
    apptainer = root / "apptainer"
    _write_executable(apptainer, _FAKE_APPTAINER.replace("@PY@", shlex.quote(sys.executable))
                      .replace("@FAKEPY@", shlex.quote(str(fake_py))))
    prof = replace(
        profile507, scratch_root=str(root / "remote"), node_scratch_root=str(root / "node"),
        image=str(image), apptainer_image_sha256=digest, container_identity=f"sif:sha256:{digest}",
        apptainer_executable=str(apptainer), hecras_dir=str(engine_dir),
        ld_library_path=(str(engine_dir),), stack_unlimited=False,
    )
    if spec == "separate-image":
        slim_image = root / "slim.sif"
        slim_image.write_bytes(b"fake slim image")
        spec = {"image": str(slim_image),
                "image_sha256": slim_image_digest or hashlib.sha256(slim_image.read_bytes()).hexdigest()}
    job = RasApptainer.render_job(project507, "TEST", 8, prof, tmp_path / "job", hdf_slim=spec or {})
    remote = Path(job.remote_directory)
    remote.mkdir(parents=True)
    shutil.copytree(job.job_directory, remote, dirs_exist_ok=True)
    return root, remote


def _run(remote, **env):
    done = subprocess.run([BASH, str(remote / "job.sh")],
                          env={**os.environ, "SLURM_JOB_ID": "4242", **env},
                          capture_output=True, text=True, check=False)
    out = remote / "out" / "4242"
    receipt = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    return done, out, receipt


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_NATIVE_KEYS = {  # ras-commander-apptainer-receipt/v1 fields; slimming adds only two blocks
    "schema", "request_sha256", "job_name", "slurm_job_id", "node", "container_identity",
    "apptainer_image_sha256", "status", "reason_code", "exit_code", "started_at", "finished_at",
    "elapsed_seconds", "num_cores", "input_hashes", "outputs", "copy_verified",
    "dss_output_rewrite", "detail",
}
posix_job = pytest.mark.skipif(BASH is None, reason="bash is unavailable")


@posix_site_profile
@posix_job
@pytest.mark.parametrize("spec", [None, "separate-image"])
def test_in_job_slim_replaces_payload_and_records_full_identity(project507, profile507, tmp_path, spec):
    root, remote = _site(project507, profile507, tmp_path, spec=spec)
    done, out, receipt = _run(remote)
    assert done.returncode == 0, (receipt, done.stderr)
    assert receipt["status"] == "succeeded" and receipt["copy_verified"] is True
    assert set(receipt) == _NATIVE_KEYS | {"full_hdf", "hdf_slim"}
    RA.validate_receipt(receipt)
    full, slim = receipt["full_hdf"], receipt["hdf_slim"]
    payload = out / "project" / "TEST.p08.hdf"
    manifest = out / "project" / "TEST.p08.hdf_slim.json"
    assert set(full) == {"name", "bytes", "sha256"} and full["name"] == "TEST.p08.hdf"
    assert slim["status"] == "completed" and slim["reason_code"] == "HDF_SLIM_VERIFIED"
    assert slim["copy_back_sha256_verified"] is True
    outputs = receipt["outputs"]
    assert outputs["project/TEST.p08.hdf"] == {"sha256": slim["sha256"], "size_bytes": slim["bytes"]}
    assert slim["sha256"] == _sha(payload) != full["sha256"]
    record = json.loads(manifest.read_text(encoding="utf-8"))
    assert record["schema"] == "ras-commander-hdf-slim/v1"
    assert record["source"] == {"name": "TEST.p08.hdf", "bytes": full["bytes"],
                                "sha256": full["sha256"], "sha256_verified": True}
    assert slim["manifest"] == {"path": "project/TEST.p08.hdf_slim.json",
                                "bytes": manifest.stat().st_size, "sha256": _sha(manifest)}
    assert outputs["project/TEST.p08.hdf_slim.json"]["sha256"] == _sha(manifest)
    assert slim["applied_keep"] == {"Area1": sorted(
        f"/{SERIES}/Area1/{n}" for n in ("Water Surface", "Face Flow", *PLUVIAL))}
    assert slim["policy"] == record["policy"] == HdfSlim.list_presets()["inundation-mapping"]
    assert slim["implementation_sha256"] == HdfSlim.implementation_sha256()
    assert not (root / "node" / "4242" / "ras").exists()  # scratch removed only after success


@posix_site_profile
@posix_job
@pytest.mark.parametrize("env, code", [
    ({"FAKE_SOLVER": "no-flow"}, "HDF_SLIM_REQUIRED_DATASET_MISSING"),  # no Face Flow or Velocity
    ({"FAKE_SLIM_MODE": "badsource"}, "HDF_SLIM_RECEIPT_CHECK_FAILED"),
    ({"FAKE_SLIM_MODE": "noruntime"}, "HDF_SLIM_RUNTIME_UNAVAILABLE"),
])
def test_slim_failure_copies_full_file(project507, profile507, tmp_path, env, code):
    _, remote = _site(project507, profile507, tmp_path)
    done, out, receipt = _run(remote, **env)
    assert done.returncode == 0, (receipt, done.stderr)
    assert receipt["status"] == "succeeded"
    RA.validate_receipt(receipt)
    full, slim = receipt["full_hdf"], receipt["hdf_slim"]
    assert slim["status"] == "failed" and slim["reason_code"] == code
    assert slim["output_path"] == "project/TEST.p08.hdf" and slim["copy_back_sha256_verified"] is False
    payload = out / "project" / "TEST.p08.hdf"
    assert receipt["outputs"]["project/TEST.p08.hdf"]["sha256"] == full["sha256"] == _sha(payload)
    assert not (out / "project" / "TEST.p08.hdf_slim.json").exists()


@posix_site_profile
@posix_job
def test_slim_image_mismatch_copies_full_file(project507, profile507, tmp_path):
    _, remote = _site(project507, profile507, tmp_path, spec="separate-image",
                         slim_image_digest="c" * 64)
    done, out, receipt = _run(remote)
    assert done.returncode == 0, (receipt, done.stderr)
    RA.validate_receipt(receipt)
    assert receipt["hdf_slim"]["status"] == "failed"
    assert receipt["hdf_slim"]["reason_code"] == "HDF_SLIM_IMAGE_MISMATCH"
    assert receipt["full_hdf"]["sha256"] == _sha(out / "project" / "TEST.p08.hdf")


@posix_site_profile
@posix_job
def test_tampered_staged_engine_copies_full_file(project507, profile507, tmp_path):
    _, remote = _site(project507, profile507, tmp_path)
    engine = remote / "hdf_slim" / "hdf_slim_engine.py"
    engine.write_bytes(engine.read_bytes() + b"\n# changed\n")
    done, out, receipt = _run(remote)
    assert done.returncode == 0, (receipt, done.stderr)
    RA.validate_receipt(receipt)
    assert receipt["hdf_slim"]["reason_code"] == "HDF_SLIM_ENGINE_MISMATCH"
    assert receipt["full_hdf"]["sha256"] == _sha(out / "project" / "TEST.p08.hdf")
