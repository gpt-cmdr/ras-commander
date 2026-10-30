"""``HdfPlan.get_starting_wse_method`` reads boundary conditions where HEC-RAS stores them.

Unsteady plans: ``Event Conditions/Unsteady/Boundary Conditions`` in the plan HDF.
Steady plans: the ``.f##`` file named by ``Plan Information/Flow Filename`` (and the
plan file's flow-regime line). Expected values come from an independent read in this
module (plain h5py, or a direct line parse of the text), never from the code under test.

The committed text fixtures are unmodified USACE example files (see
``tests/fixtures/starting_wse/README.md``). Real computed plan HDFs come from the
``RAS_ROUTE2_FIXTURES`` manifest (``{"fixtures": [{"name", "path"}]}``); those tests
skip when it is unset.
"""
import json
import os
import re
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf.HdfPlan import HdfPlan

TEXT = Path(__file__).parent / "fixtures" / "starting_wse"
BC = "Event Conditions/Unsteady/Boundary Conditions"
WS_GROUPS = {"Normal Depths": "Normal Depth", "Rating Curves": "Rating Curve",
             "Stage Hydrographs": "Stage Hydrograph"}
STEADY_TYPES = {1: "Known WS", 2: "Critical Depth", 3: "Normal Depth", 4: "Rating Curve"}


# ----------------------------------------------------------------- independent readers
def _text_boundaries(flow_file, sides):
    """Line parse of ``Boundary for River Rch & Prof#=`` blocks (profile-specific format)."""
    lines = Path(flow_file).read_text(encoding="utf-8", errors="replace").splitlines()
    names = []
    out, block = [], None
    for line in lines:
        if line.startswith("Profile Names="):
            names = [n.strip() for n in line.split("=", 1)[1].split(",")]
        elif line.startswith("Boundary for River Rch & Prof#="):
            river, reach, prof = [p.strip() for p in line.split("=", 1)[1].split(",")]
            block = {"river": river, "reach": reach, "profile": int(prof)}
            block["sides"] = {}
        elif block is not None and re.match(r"(Up|Dn) ", line) and "=" in line:
            side = "upstream" if line.startswith("Up") else "downstream"
            key, value = line[3:].split("=", 1)
            spec = block["sides"].setdefault(side, {})
            if key == "Type":
                spec["type"] = int(value)
                if side == "downstream":
                    out.append(block)
            elif key == "Known WS":
                spec["wse"] = float(value)
            elif key == "Slope":
                spec["slope"] = float(value)
    expected = []
    for block in out:
        for side in sides:
            spec = block["sides"].get(side, {})
            if spec.get("type", 0) == 0:
                continue
            entry = {"type": STEADY_TYPES[spec["type"]], "side": side, "river": block["river"],
                     "reach": block["reach"], "profile": block["profile"],
                     "profile_name": names[block["profile"] - 1]}
            entry.update({k: spec[k] for k in ("wse", "slope") if k in spec})
            expected.append(entry)
    return expected


def _h5py_unsteady(path):
    """Water-surface boundary conditions read with plain h5py."""
    with h5py.File(path, "r") as hdf:
        group = hdf[BC]
        out = []
        for group_name, method in WS_GROUPS.items():
            if group_name not in group:
                continue
            for location, dataset in group[group_name].items():
                entry = {"type": method, "location": location}
                if group_name == "Normal Depths":
                    entry["slope"] = float(dataset[()][0])
                if group_name == "Rating Curves":
                    entry["points"] = dataset.shape[0]
                out.append(entry)
        ic = hdf.get("Event Conditions/Unsteady/Initial Conditions")
        mode = ic.attrs["Startup Mode"].decode() if ic is not None and "Startup Mode" in ic.attrs else None
        restart = (ic.attrs["Restart Filename"].decode()
                   if ic is not None and "Restart Filename" in ic.attrs else None)
    return out, mode, restart


def _call(path, backend):
    with fast_hdf.backend_scope(backend):
        return HdfPlan.get_starting_wse_method(path)


# ----------------------------------------------------------------- minimal plan HDFs
def _steady_plan(folder, hdf_name, flow_name, plan_name, texts):
    folder.mkdir(parents=True, exist_ok=True)
    for name in texts:
        shutil.copy(TEXT / name, folder / name)
    path = folder / hdf_name
    with h5py.File(path, "w") as hdf:
        info = hdf.require_group("Plan Data/Plan Information")
        info.attrs["Flow Filename"] = np.bytes_(flow_name)
        info.attrs["Plan Filename"] = np.bytes_(plan_name)
        hdf.require_group("Event Conditions/Steady")
    return path


@pytest.mark.parametrize("backend", ["h5py", "native"])
def test_steady_known_ws_per_profile_from_flow_file(tmp_path, backend):
    path = _steady_plan(tmp_path, "FLODENCR.p04.hdf", "FLODENCR.f01", "FLODENCR.p04",
                        ["FLODENCR.F01", "FLODENCR.p04"])
    result = _call(path, backend)
    expected = _text_boundaries(TEXT / "FLODENCR.F01", ("downstream",))
    assert [e["wse"] for e in expected] == [211.8, 212.8]
    assert result["boundaries"] == expected
    assert result["method"] == "Known WS"
    assert result["regime"] == "Subcritical"
    assert result["source"].lower() == "flodencr.f01"
    assert "wse" not in result and "differ" in result["note"]


@pytest.mark.parametrize("backend", ["h5py", "native"])
def test_steady_mixed_regime_reports_both_sides(tmp_path, backend):
    path = _steady_plan(tmp_path, "MIXED.p01.hdf", "MIXED.f01", "MIXED.p01", ["MIXED.f01", "MIXED.P01"])
    result = _call(path, backend)
    expected = _text_boundaries(TEXT / "MIXED.f01", ("upstream", "downstream"))
    assert result["regime"] == "Mixed"
    assert sorted(result["boundaries"], key=repr) == sorted(expected, key=repr)
    assert result["method"] == "Normal Depth"
    assert "slope" not in result  # 0.01 upstream, 0.000586 downstream


def test_steady_subcritical_selects_downstream_slope(tmp_path):
    path = _steady_plan(tmp_path, "MIXED.p01.hdf", "MIXED.f01", "MIXED.p01", ["MIXED.f01"])
    (tmp_path / "MIXED.p01").write_text("Plan Title=x\nSubcritical Flow\n")
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Normal Depth"
    assert result["slope"] == 0.000586
    assert {b["side"] for b in result["boundaries"]} == {"downstream"}


def test_steady_rating_curve(tmp_path):
    path = _steady_plan(tmp_path, "NIT.p01.hdf", "NIT.f01", "NIT.p01", ["NIT.f01", "NIT.p01"])
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Rating Curve"
    lines = (TEXT / "NIT.f01").read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("Dn Rating Curve # Pts="))
    count = int(lines[start].split("=")[1])
    numbers = []
    for line in lines[start + 1:]:
        if len(numbers) >= 2 * count:
            break
        numbers += [float(line[i:i + 8]) for i in range(0, len(line.rstrip()), 8)]
    assert result["boundaries"][0]["rating_curve"] == list(zip(numbers[0::2], numbers[1::2]))
    assert count == 20


def test_steady_without_flow_file_is_unknown(tmp_path):
    path = _steady_plan(tmp_path, "FLODENCR.p04.hdf", "FLODENCR.f01", "FLODENCR.p04", [])
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Unknown"
    assert "FLODENCR.f01 not found" in result["note"]
    assert "boundaries" not in result


def test_unsteady_boundaries_from_event_conditions(tmp_path):
    path = tmp_path / "plan.p01.hdf"
    with h5py.File(path, "w") as hdf:
        nd = hdf.create_dataset(f"{BC}/Normal Depths/River: R  Reach: A  RS: 1.0",
                                data=np.array([0.0005], dtype="f4"))
        for name, value in (("River", b"R"), ("Reach", b"A"), ("RS", b"1.0")):
            nd.attrs[name] = np.bytes_(value)
        hdf.create_dataset(f"{BC}/Flow Hydrographs/River: R  Reach: A  RS: 9.0",
                           data=np.zeros((3, 2), dtype="f4"))
        hdf.require_group("Event Conditions/Unsteady/Initial Conditions").attrs["Startup Mode"] = \
            np.bytes_(b"Computed")
    result = HdfPlan.get_starting_wse_method(path)
    assert result["method"] == "Computed"  # initialization, not the outlet boundary
    assert "slope" not in result
    assert result["startup_mode"] == "Computed"
    assert result["boundaries"] == [{"type": "Normal Depth", "location": "River: R  Reach: A  RS: 1.0",
                                     "river": "R", "reach": "A", "rs": "1.0",
                                     "slope": float(np.float32(0.0005))}]


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


@_needs_manifest
@pytest.mark.parametrize("fixture", _PLANS, ids=[f["name"] for f in _PLANS])
def test_real_unsteady_plans_match_h5py_and_native(fixture):
    path = Path(fixture["path"])
    with h5py.File(path, "r") as hdf:
        if BC not in hdf:
            pytest.skip("not a computed unsteady plan")
    expected, mode, restart = _h5py_unsteady(path)
    with fast_hdf.trace_reads() as trace:
        native = _call(path, "native")
    reference = _call(path, "h5py")
    assert native == reference
    got = [{k: v for k, v in b.items() if k in {"type", "location", "slope", "points"}}
           for b in reference["boundaries"]]
    assert got == expected
    assert reference.get("startup_mode") == mode
    if any(b["type"] == "Normal Depth" for b in expected):
        assert any(r["backend"].startswith("native") for r in trace)
    assert reference["method"] == (mode or "Unknown")
    assert reference.get("restart_file") == restart
    assert "slope" not in reference and "wse" not in reference


def _flow_name(path):
    with h5py.File(path, "r") as hdf:
        info = hdf.get("Plan Data/Plan Information")
        if info is None or "Flow Filename" not in info.attrs:
            return None, None
        return info.attrs["Flow Filename"].decode(), info.attrs["Plan Filename"].decode()


@_needs_manifest
@pytest.mark.parametrize("fixture", _PLANS, ids=[f["name"] for f in _PLANS])
def test_real_steady_plans_with_committed_flow_files(fixture, tmp_path):
    path = Path(fixture["path"])
    flow, plan = _flow_name(path)
    texts = {p.name.lower(): p for p in TEXT.iterdir()}
    if not flow or flow.lower() not in texts or not flow.lower().startswith("flodencr"):
        pytest.skip("no committed flow file for this plan")
    shutil.copy(path, tmp_path / path.name)
    for name in (flow, plan):
        shutil.copy(texts[name.lower()], tmp_path / texts[name.lower()].name)
    native = _call(tmp_path / path.name, "native")
    assert native == _call(tmp_path / path.name, "h5py")
    assert native["boundaries"] == _text_boundaries(texts[flow.lower()], ("downstream",))
    assert native["method"] == "Known WS" and native["regime"] == "Subcritical"
