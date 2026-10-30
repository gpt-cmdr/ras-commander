"""Floodway helpers read encroachments, boundaries and lateral weirs where HEC-RAS stores them.

- ``_get_encroachment_parameters``: plan ``.p##`` ``Encroach`` records (``RasFloodway``).
- ``_check_floodway_boundary_conditions``: steady ``.f##`` boundaries (``RasSteady``).
- ``_check_floodway_lateral_weirs``: ``Geometry/Structures`` (Type Lateral) and
  ``.../Steady Profiles/Lateral Structures/<name>/Structure Variables``.

Expected values come from an independent read in this module (a direct line parse of
the text, or plain h5py), never from the code under test. Text fixtures are unmodified
USACE example files (``tests/fixtures/floodway_example6/README.md``). Real computed
plan HDFs come from the ``RAS_ROUTE2_FIXTURES`` manifest; those tests skip when unset.
"""
import json
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf
from ras_commander.check.check_floodways import CheckFloodways
from ras_commander.check.thresholds import get_default_thresholds

TEXT = Path(__file__).parent / "fixtures" / "floodway_example6"
STEADY = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"


# ----------------------------------------------------------------- independent readers
def _plan_encroachments(plan, profile_number):
    """Methods and Method 4/5 targets for one profile, from 8-character node fields."""
    lines = (TEXT / plan).read_text().splitlines()
    methods, targets = set(), set()
    for i, line in enumerate(lines):
        if not line.startswith("Encroach Node="):
            continue
        fields = [lines[i + 1][k:k + 8].strip() for k in range(0, len(lines[i + 1]), 8)]
        slot = (profile_number - 2) * 3
        if slot < len(fields) and fields[slot]:
            method = int(float(fields[slot]))
            methods.add(method)
            if method in (4, 5):
                targets.add(float(fields[slot + 1]))
    return sorted(methods), targets


def _flow_downstream(flow):
    """``{(river, reach, profile): (type, known_ws, slope)}`` and profile names."""
    lines = (TEXT / flow).read_text().splitlines()
    names = next(l for l in lines if l.startswith("Profile Names=")).split("=", 1)[1].split(",")
    out, key = {}, None
    for line in lines:
        if line.startswith("Boundary for River Rch & Prof#="):
            river, reach, prof = [p.strip() for p in line.split("=", 1)[1].split(",")]
            key = (river, reach, int(prof))
            out[key] = [0, None, None]
        elif key and line.startswith("Dn Type="):
            out[key][0] = int(line.split("=")[1])
        elif key and line.startswith("Dn Known WS="):
            out[key][1] = float(line.split("=")[1])
        elif key and line.startswith("Dn Slope="):
            out[key][2] = float(line.split("=")[1])
    return out, [n.strip() for n in names]


def _expected_bc(flow, base, floodway):
    bcs, names = _flow_downstream(flow)
    b, f = names.index(base) + 1, names.index(floodway) + 1
    expected = []
    for (river, reach, prof), (kind, ws, slope) in bcs.items():
        if prof != f:
            continue
        bkind, bws, bslope = bcs.get((river, reach, b), (0, None, None))
        if kind == 1:
            if bkind == 1 and bws != ws:
                expected.append(("FW_BC_01", river, reach, ws - bws))
            expected.append(("FW_BC_03", river, reach, ws))
        elif kind == 3 and bkind == 3 and bslope == slope:
            expected.append(("FW_BC_02", river, reach, slope))
    return expected


def _h5py_lateral(plan_hdf, floodway):
    """(river, reach, rs, pct) for every lateral structure with a result group, plain h5py."""
    with h5py.File(plan_hdf, "r") as hdf:
        rows = hdf["Geometry/Structures/Attributes"][()]
        names = [n.decode().strip() for n in hdf[f"{STEADY}/Profile Names"][()]]
        idx = names.index(floodway)
        out = []
        for r in rows:
            if r["Type"].decode().strip() != "Lateral":
                continue
            ident = [r[k].decode().strip() for k in ("River", "Reach", "RS")]
            ds = hdf[f"{STEADY}/Lateral Structures/{' '.join(ident)}/Structure Variables"]
            cols = [c[0].decode() for c in ds.attrs["Variable_Unit"]]
            row = ds[()][idx]
            total, upstream = float(row[cols.index("Total Flow")]), float(row[cols.index("Flow HW US")])
            out.append((*ident, abs(total) / upstream * 100))
    return out


def _messages(func, backend, *args):
    with fast_hdf.backend_scope(backend):
        return [asdict(m) for m in func(*args)]


def _plan_hdf(folder, hdf_name, plan_name, flow_name, texts, info=True):
    folder.mkdir(parents=True, exist_ok=True)
    for name in texts:
        shutil.copy(TEXT / name, folder / name)
    path = folder / hdf_name
    with h5py.File(path, "w") as hdf:
        group = hdf.require_group("Plan Data/Plan Information")
        if info:
            group.attrs["Plan Filename"] = np.bytes_(plan_name)
            group.attrs["Flow Filename"] = np.bytes_(flow_name)
    return path


# ----------------------------------------------------------------- committed text fixtures
@pytest.mark.parametrize("plan, flow, plan_name, flow_name, floodway, number", [
    ("FLODENCR.p04", "FLODENCR.F01", "FLODENCR.p04", "FLODENCR.f01", "PF#2", 2),
    ("FLODENCR.P02", "FLODENCR.F02", "FLODENCR.p02", "FLODENCR.f02", "PF#4", 4),
    ("FLODENCR.P02", "FLODENCR.F02", "FLODENCR.p02", "FLODENCR.f02", "PF#2", 2),
    ("flodencr.p01", "FLODENCR.F01", "FLODENCR.p01", "FLODENCR.f01", "PF#2", 2),
])
@pytest.mark.parametrize("backend", ["h5py", "native"])
def test_encroachment_parameters_from_plan_file(tmp_path, backend, plan, flow, plan_name, flow_name,
                                                floodway, number):
    path = _plan_hdf(tmp_path, f"{plan_name}.hdf", plan_name, flow_name, [plan, flow])
    with fast_hdf.backend_scope(backend):
        params = CheckFloodways._get_encroachment_parameters(path, floodway)
    methods, targets = _plan_encroachments(plan, number)
    assert params["profile_number"] == number
    assert params["methods"] == methods
    assert params["plan_file"].lower() == plan_name.lower()
    if len(targets) == 1:
        assert params["target_surcharge"] == targets.pop()
    else:
        assert "target_surcharge" not in params
    assert "max_iterations" not in params and "tolerance" not in params
    assert params["targets_complete"] is True and params["nodes_missing_target"] == []


def test_encroachment_parameters_without_plan_information(tmp_path):
    # Plan file from the HDF name, flow file from the plan's "Flow File=f01".
    path = _plan_hdf(tmp_path, "FLODENCR.p04.hdf", "", "", ["FLODENCR.p04", "FLODENCR.F01"], info=False)
    params = CheckFloodways._get_encroachment_parameters(path, "PF#2")
    assert params["methods"] == [4]


@pytest.mark.parametrize("texts, profile", [
    ([], "PF#2"),                                  # no text files next to the HDF
    (["FLODENCR.p04"], "PF#2"),                    # flow file missing
    (["FLODENCR.p04", "FLODENCR.F01"], "Nope"),    # profile not in the flow file
    (["FLODENCR.p04", "FLODENCR.F01"], "PF#1"),    # no encroachment slot for profile 1
])
def test_encroachment_parameters_refuse_without_inputs(tmp_path, texts, profile):
    path = _plan_hdf(tmp_path, "FLODENCR.p04.hdf", "FLODENCR.p04", "FLODENCR.f01", texts)
    assert CheckFloodways._get_encroachment_parameters(path, profile) is None


@pytest.mark.parametrize("flow, flow_name, base, floodway", [
    ("FLODENCR.F01", "FLODENCR.f01", "PF#1", "PF#2"),
    ("FLODENCR.F02", "FLODENCR.f02", "PF#1", "PF#4"),
    ("FLODENCR.F02", "FLODENCR.f02", "PF#3", "PF#4"),
    ("Baxter.f01", "Baxter.f01", "Big", "Biggest"),
])
@pytest.mark.parametrize("backend", ["h5py", "native"])
def test_boundary_conditions_from_flow_file(tmp_path, backend, flow, flow_name, base, floodway):
    path = _plan_hdf(tmp_path, "plan.p01.hdf", "plan.p01", flow_name, [flow])
    got = _messages(CheckFloodways._check_floodway_boundary_conditions, backend,
                    path, base, floodway, get_default_thresholds())
    assert [(m["message_id"], m["river"], m["reach"], m["value"]) for m in got] == \
        _expected_bc(flow, base, floodway)
    assert all(m["severity"].value == "INFO" for m in got)


def test_boundary_conditions_without_flow_file_or_profile(tmp_path):
    path = _plan_hdf(tmp_path, "plan.p01.hdf", "plan.p01", "FLODENCR.f01", [])
    thresholds = get_default_thresholds()
    assert CheckFloodways._check_floodway_boundary_conditions(path, "PF#1", "PF#2", thresholds) == []
    shutil.copy(TEXT / "FLODENCR.F01", tmp_path / "FLODENCR.F01")
    assert CheckFloodways._check_floodway_boundary_conditions(path, "PF#1", "Nope", thresholds) == []


def _synthetic_lateral(path, total, upstream, *, rs=b"10.", group_rs="10."):
    rows = np.array([(b"Bridge", b"R", b"A", b"20."), (b"Lateral", b"R", b"A", rs)],
                    dtype=[("Type", "S16"), ("River", "S16"), ("Reach", "S16"), ("RS", "S8")])
    with h5py.File(path, "w") as hdf:
        hdf["Geometry/Structures/Attributes"] = rows
        hdf[f"{STEADY}/Profile Names"] = np.array([b"Base", b"Floodway"])
        values = np.zeros((2, 3), dtype="f4")
        values[1, 0], values[1, 2] = total, upstream
        ds = hdf.create_dataset(f"{STEADY}/Lateral Structures/R A {group_rs}/Structure Variables", data=values)
        ds.attrs["Variable_Unit"] = np.array([[b"Total Flow", b"cfs"], [b"Weir Flow", b"cfs"],
                                              [b"Flow HW US", b"cfs"]])


@pytest.mark.parametrize("total, upstream, flagged", [(60.0, 1000.0, True), (50.0, 1000.0, False),
                                                      (-80.0, 1000.0, True), (60.0, 0.0, False)])
@pytest.mark.parametrize("backend", ["h5py", "native"])
def test_lateral_weirs_synthetic(tmp_path, backend, total, upstream, flagged):
    path = tmp_path / "plan.p01.hdf"
    _synthetic_lateral(path, total, upstream)
    got = _messages(CheckFloodways._check_floodway_lateral_weirs, backend,
                    path, path, "Floodway", get_default_thresholds())
    assert [m["message_id"] for m in got] == ["FW_LW_01"] + (["FW_LW_02"] if flagged else [])
    assert got[0]["station"] == "10."
    if flagged:
        assert got[1]["value"] == pytest.approx(abs(total) / upstream * 100)
        assert (got[1]["river"], got[1]["reach"], got[1]["station"]) == ("R", "A", "10.")


def test_lateral_weirs_missing_results_or_profile(tmp_path):
    path = tmp_path / "plan.p01.hdf"
    _synthetic_lateral(path, 60.0, 100.0, group_rs="11.")
    ids = [m.message_id for m in CheckFloodways._check_floodway_lateral_weirs(
        path, path, "Floodway", get_default_thresholds())]
    assert ids == ["FW_LW_01"]
    _synthetic_lateral(path, 60.0, 100.0)
    assert [m.message_id for m in CheckFloodways._check_floodway_lateral_weirs(
        path, path, "Other", get_default_thresholds())] == ["FW_LW_01"]


# ----------------------------------------------------------------- real computed plans
def _manifest_plans():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    fixtures = json.loads(Path(manifest).read_text())["fixtures"]
    return [f for f in fixtures if re.search(r"\.p\d\d(\.[^.]+)*\.hdf$", f["path"], re.I)
            and Path(f["path"]).is_file()]


_PLANS = _manifest_plans()
_needs_manifest = pytest.mark.skipif(
    not _PLANS, reason="Set RAS_ROUTE2_FIXTURES to a real-fixture JSON manifest")
# Flow file -> (plan text, base profile, floodway profile) for the computed corpus plans.
_PROJECTS = {
    "flodencr.f01": ("FLODENCR.p04", "PF#1", "PF#2"),
    "flodencr.f02": ("FLODENCR.P02", "PF#1", "PF#4"),
    "baxter.f01": (None, "Big", "Biggest"),
}


def _info(path, key):
    with h5py.File(path, "r") as hdf:
        info = hdf.get("Plan Data/Plan Information")
        return info.attrs[key].decode() if info is not None and key in info.attrs else None


@_needs_manifest
@pytest.mark.parametrize("fixture", _PLANS, ids=[f["name"] for f in _PLANS])
def test_real_plans_with_committed_text(fixture, tmp_path):
    path = Path(fixture["path"])
    flow = (_info(path, "Flow Filename") or "").lower()
    if flow not in _PROJECTS:
        pytest.skip("no committed text files for this plan")
    plan, base, floodway = _PROJECTS[flow]
    texts = {p.name.lower(): p.name for p in TEXT.iterdir()}
    shutil.copy(path, tmp_path / path.name)
    shutil.copy(TEXT / texts[flow], tmp_path / texts[flow])
    if plan:
        assert _info(path, "Plan Filename").lower() == plan.lower()
        shutil.copy(TEXT / plan, tmp_path / plan)
    copied = tmp_path / path.name
    thresholds = get_default_thresholds()
    for backend in ("h5py", "native"):
        got = _messages(CheckFloodways._check_floodway_boundary_conditions, backend,
                        copied, base, floodway, thresholds)
        assert [(m["message_id"], m["river"], m["reach"], m["value"]) for m in got] == \
            _expected_bc(texts[flow], base, floodway)
        with fast_hdf.backend_scope(backend):
            params = CheckFloodways._get_encroachment_parameters(copied, floodway)
        if plan:
            assert params["methods"] == _plan_encroachments(plan, params["profile_number"])[0]
        else:
            assert params is None  # Baxter.p01 text is not committed


@_needs_manifest
@pytest.mark.parametrize("fixture", _PLANS, ids=[f["name"] for f in _PLANS])
def test_real_steady_lateral_weirs(fixture):
    path = Path(fixture["path"])
    with h5py.File(path, "r") as hdf:
        if f"{STEADY}/Lateral Structures" not in hdf:
            pytest.skip("no steady lateral-structure results")
        floodway = hdf[f"{STEADY}/Profile Names"][()][-1].decode().strip()
    expected = _h5py_lateral(path, floodway)
    thresholds = get_default_thresholds()
    with fast_hdf.trace_reads() as trace:
        native = _messages(CheckFloodways._check_floodway_lateral_weirs, "native",
                           path, path, floodway, thresholds)
    assert native == _messages(CheckFloodways._check_floodway_lateral_weirs, "h5py",
                               path, path, floodway, thresholds)
    assert any(r["route"] == "structure_series" and "/Lateral Structures/" in r["path"]
               for r in trace if r["backend"] == "native-typed")
    assert [(m["river"], m["reach"], m["station"]) for m in native if m["message_id"] == "FW_LW_01"] == \
        [e[:3] for e in expected]
    assert [(m["river"], m["reach"], m["station"], m["value"]) for m in native
            if m["message_id"] == "FW_LW_02"] == [e for e in expected if e[3] > 5.0]


def test_encroachment_target_missing_at_one_node_is_incomplete(tmp_path):
    """A blank Method 4 target must not be dropped in favour of the other nodes' target."""
    (tmp_path / "proj.p01").write_text(
        "Plan Title=t\nFlow File=f01\nEncroach Param=-1 ,10,10, 2 \n"
        "Encroach River=R\nEncroach Reach=A\n"
        "Encroach Node=2.0\n       4       1        \n"
        "Encroach Node=1.0\n       4                \n")
    (tmp_path / "proj.f01").write_text(
        "Flow Title=t\nNumber of Profiles= 2 \nProfile Names=Base,Floodway\n"
        "River Rch & RM=R,A,2.0\n     100     100\n")
    path = _plan_hdf(tmp_path, "proj.p01.hdf", "proj.p01", "proj.f01", [])
    params = CheckFloodways._get_encroachment_parameters(path, "Floodway")
    assert params["methods"] == [4]
    assert params.get("target_surcharge") is None
    assert params["targets_complete"] is False
    assert params["nodes_missing_target"] == [
        {"river": "R", "reach": "A", "node": "1.0", "method": 4}]
