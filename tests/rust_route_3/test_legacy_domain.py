"""PY-ROUTE-3 item 5: engine-typed 2D mesh series domains versus PR #565's h5py rule.

Engine API 9 types the HEC-RAS 5.0.7 Base Output 2D series that carry no stored
``Location`` (for example the public FEMA eBFE AustinOyster.p03 ``Depth``,
``Water Surface``, ``Face Velocity``, ``Face Shear Stress``) with
``domain_rule == "legacy_exact_name"``.
``fast_hdf.mesh_series_domain`` exposes that typed domain on the native path.

The h5py rule lives in ras-commander PR #565 (``HdfResultsMesh._mesh_series_id_dim``),
which this branch's base does not contain. Two tests compare the pathways:

- ``test_native_domain_matches_pr565_rule`` runs now. ``pr565_id_dim`` below is
  transcribed from ``gh pr diff 565 -R gpt-cmdr/ras-commander`` (head afdc3ee):
  present ``Location`` is authoritative (``Cells``/``Cell``/``Faces``; anything else
  refuses); absent ``Location`` permits only the six exact stable-core names at
  the canonical path; numeric rank-two data, canonical Base Output ``Time`` rows,
  stored geometry counts (ghosts included) and the physical Cell Count bound are
  required on both paths; rank-one series are time-only.
- ``test_native_domain_matches_h5py_reader`` is marked ``requires_pr565``. Since
  R2.4 (#565 merged) it runs: the library's own rule, evaluated in python mode so
  it never consults the engine, is compared with the native domain.
- ``test_library_domain_identical_across_modes`` (R2.4) calls the library's
  ``HdfResultsMesh._mesh_series_id_dim``, which takes the native domain when the
  engine qualifies one, in auto and required mode, and asserts the python-mode
  outcome (``id_dim`` or the exact ``ValueError`` text). Required mode may only
  differ by raising ``FastHdfError`` (an engine refusal); those are counted.

Agreement means: a qualified h5py domain equals the engine ``id_dim`` with the
matching ``domain_rule`` (``stored_location`` when ``Location`` is present, else
``legacy_exact_name``); a time-only series is engine ``domain == "other"``; an h5py
``ValueError`` is an engine refusal (``id_dim is None``).

Inputs: ``RAS_ROUTE2_FIXTURES`` (real fixtures, AustinOyster.p03 included) and
optionally ``RAS_ROUTE3_LEGACY_EXCERPTS``, a directory holding the engine's
legacy-location excerpts (valid, wrong_count, invalid_location, rows_mismatch,
physical_count, physical_count_ok), read only. In a checkout of
https://github.com/gpt-cmdr/ras-commander-fast-hdf (0.2 and later) they are
``tests/fixtures/legacy_location/*.h5``.
``RAS_ROUTE3_RESULTS`` (optional) receives one JSON line per compared series.
"""
import json
import os
from pathlib import Path
from types import MappingProxyType

import h5py
import numpy as np
import pytest

MANIFEST = os.environ.get("RAS_ROUTE2_FIXTURES")
FIXTURES = json.loads(Path(MANIFEST).read_text())["fixtures"] if MANIFEST else []
EXCERPTS = os.environ.get("RAS_ROUTE3_LEGACY_EXCERPTS")
EXCERPT_FILES = sorted(str(p) for p in Path(EXCERPTS).glob("*.h5")) if EXCERPTS else []
RESULTS = os.environ.get("RAS_ROUTE3_RESULTS")
if RESULTS and os.environ.get("PYTEST_XDIST_WORKER"):
    RESULTS = f"{RESULTS}.{os.environ['PYTEST_XDIST_WORKER']}"

BASE = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
AREAS = f"{BASE}/2D Flow Areas"

# --------------------------------------------------------------------------- PR #565 rule
# Transcribed from PR #565 (ras_commander/hdf/HdfResultsMesh.py, head afdc3ee).
_LEGACY_MESH_SERIES_DOMAINS = MappingProxyType({
    "Depth": "cell_id",
    "Water Surface": "cell_id",
    "Face Velocity": "face_id",
    "Face Shear Stress": "face_id",
    "Face Area": "face_id",
    "Face Manning's n": "face_id",
})


def _get_mesh_timeseries_output_path(mesh_name, var_name):
    return f"{AREAS}/{mesh_name}/{var_name}"


def _physical_cell_counts(hdf_file):
    # PR #565 calls HdfResultsMesh._physical_cell_counts, which delegates to this base helper.
    from ras_commander.hdf.HdfMesh import HdfMesh
    return HdfMesh._physical_cell_counts(hdf_file)


def pr565_id_dim(hdf_file, mesh_name, dataset):
    """``HdfResultsMesh._mesh_series_id_dim`` from PR #565, unchanged in logic."""
    if not isinstance(dataset, h5py.Dataset) or dataset.ndim not in (1, 2) or dataset.dtype.kind not in "iuf":
        raise ValueError(f"Unsupported numeric time/element schema: {dataset.name}")
    time = hdf_file.get(f"{BASE}/Time")
    if (not isinstance(time, h5py.Dataset) or time.ndim != 1
            or time.dtype.kind not in "iuf" or dataset.shape[0] != len(time)):
        raise ValueError(f"Series rows differ from Base Output Time axis: {dataset.name}")
    if "Location" in dataset.attrs:
        location = np.asarray(dataset.attrs["Location"])
        if location.shape not in ((), (1,)):
            raise ValueError(f"Location requires one stored text value: {dataset.name}")
        location = location.reshape(-1)[0]
        if isinstance(location, bytes):
            try:
                location = location.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"Invalid stored Location text: {dataset.name}") from exc
        if not isinstance(location, str) or location not in {"Cells", "Cell", "Faces"}:
            raise ValueError(f"Invalid or unqualified stored Location: {dataset.name}")
        if dataset.ndim != 2:
            raise ValueError(f"Stored Location contradicts time-only schema: {dataset.name}")
        id_dim = "cell_id" if location in {"Cells", "Cell"} else "face_id"
    elif dataset.ndim == 1:
        return "time"
    else:
        name = dataset.name.rsplit("/", 1)[-1]
        canonical_path = "/" + _get_mesh_timeseries_output_path(mesh_name, name)
        id_dim = _LEGACY_MESH_SERIES_DOMAINS.get(name)
        if dataset.name != canonical_path or id_dim is None:
            raise ValueError(f"Missing Location and no qualified legacy schema: {dataset.name}")
    is_cell = id_dim == "cell_id"
    geometry_name = "Cells Center Coordinate" if is_cell else "Faces FacePoint Indexes"
    geometry = hdf_file.get(f"Geometry/2D Flow Areas/{mesh_name}/{geometry_name}")
    if geometry is None or not isinstance(geometry, h5py.Dataset) or geometry.ndim < 1:
        raise ValueError(f"Geometry count for qualified series domain absent: {dataset.name}")
    if dataset.shape[1] != len(geometry):
        raise ValueError(f"Qualified series domain contradicts geometry count: {dataset.name}")
    if is_cell:
        physical_count = _physical_cell_counts(hdf_file).get(mesh_name)
        if physical_count is not None and not 0 <= physical_count <= len(geometry):
            raise ValueError(f"Physical Cell Count contradicts stored geometry: {dataset.name}")
    return "cell_id" if is_cell else "face_id"


# --------------------------------------------------------------------------- comparison
def _series(path):
    """``(mesh, name)`` of every numeric dataset directly under a 2D area's Base Output series."""
    with h5py.File(path, "r") as f:
        group = f.get(AREAS)
        if not isinstance(group, h5py.Group):
            return []
        out = []
        for mesh, area in group.items():
            if not isinstance(area, h5py.Group):
                continue
            for name, ds in area.items():
                # PR #565's discovery enumerates numeric datasets only.
                if isinstance(ds, h5py.Dataset) and ds.dtype.kind in "iuf":
                    out.append((mesh, name))
        return out


def _compare(path, label, oracle):
    from ras_commander import fast_hdf
    series = _series(path)
    if not series:
        pytest.skip(f"{label}: no Base Output 2D mesh series")
    rows = []
    with h5py.File(path, "r") as f:
        for mesh, name in series:
            ds = f[_get_mesh_timeseries_output_path(mesh, name)]
            try:
                expected, error = oracle(f, mesh, ds), None
            except ValueError as exc:
                expected, error = None, str(exc)
            auto = fast_hdf.mesh_series_domain(ds, backend="auto")
            try:
                native = fast_hdf.mesh_series_domain(ds, backend="rust")
            except fast_hdf.FastHdfError as exc:
                # The engine refused the whole area inventory (e.g. Corrupt): a refusal.
                assert auto is None
                native = {"id_dim": None, "domain": None, "domain_rule": None,
                          "capability": {"status": "error", "reason": str(exc)[:300]}}
            else:
                assert auto == native
            located = "Location" in ds.attrs
            if expected in {"cell_id", "face_id"}:
                assert native["id_dim"] == expected, (name, native)
                assert native["domain_rule"] == ("stored_location" if located else "legacy_exact_name"), (name, native)
            elif expected == "time":
                assert native["id_dim"] is None and native["domain"] == "other", (name, native)
            else:
                assert native["id_dim"] is None, (name, error, native)
            rows.append({"fixture": label, "mesh": mesh, "series": name, "h5py": expected or "ValueError",
                         "h5py_error": error, "located": located, **native})
    if RESULTS:
        with open(RESULTS, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")
    return rows


@pytest.fixture(autouse=True)
def _native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    assert module.API_VERSION == 11


CASES = [(f["path"], f["name"]) for f in FIXTURES] + [(p, f"excerpt:{Path(p).name}") for p in EXCERPT_FILES]


@pytest.mark.skipif(not CASES, reason="Set RAS_ROUTE2_FIXTURES and/or RAS_ROUTE3_LEGACY_EXCERPTS")
@pytest.mark.parametrize("path,label", CASES, ids=[c[1] for c in CASES])
def test_native_domain_matches_pr565_rule(path, label):
    rows = _compare(path, label, pr565_id_dim)
    if label == "AustinOyster.p03":
        legacy = {r["series"] for r in rows if r["domain_rule"] == "legacy_exact_name"}
        assert legacy == {"Depth", "Water Surface", "Face Velocity", "Face Shear Stress"}


@pytest.mark.requires_pr565
@pytest.mark.skipif(not CASES, reason="Set RAS_ROUTE2_FIXTURES and/or RAS_ROUTE3_LEGACY_EXCERPTS")
@pytest.mark.parametrize("path,label", CASES, ids=[c[1] for c in CASES])
def test_native_domain_matches_h5py_reader(path, label):
    from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
    if not hasattr(HdfResultsMesh, "_mesh_series_id_dim"):
        pytest.skip("requires ras-commander PR #565 (HdfResultsMesh._mesh_series_id_dim); reconcile at R2.4")

    def h5py_rule(hdf_file, mesh, dataset):
        with _env_mode("0"):
            return HdfResultsMesh._mesh_series_id_dim(hdf_file, mesh, dataset)
    _compare(path, label, h5py_rule)


class _env_mode:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.old = os.environ.get("RAS_COMMANDER_FAST_HDF")
        os.environ["RAS_COMMANDER_FAST_HDF"] = self.value

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("RAS_COMMANDER_FAST_HDF", None)
        else:
            os.environ["RAS_COMMANDER_FAST_HDF"] = self.old


def _outcome(call, mode):
    from ras_commander import fast_hdf
    with _env_mode(mode):
        try:
            return ("value", call())
        except fast_hdf.FastHdfError as exc:
            return ("FastHdfError", str(exc)[:200])
        except ValueError as exc:
            return ("ValueError", str(exc))


@pytest.mark.requires_pr565
@pytest.mark.skipif(not CASES, reason="Set RAS_ROUTE2_FIXTURES and/or RAS_ROUTE3_LEGACY_EXCERPTS")
@pytest.mark.parametrize("path,label", CASES, ids=[c[1] for c in CASES])
def test_library_domain_identical_across_modes(path, label):
    from ras_commander.hdf.HdfResultsMesh import HdfResultsMesh
    series = _series(path)
    if not series:
        pytest.skip(f"{label}: no Base Output 2D mesh series")
    rows = []
    with h5py.File(path, "r") as f:
        for mesh, name in series:
            ds = f[_get_mesh_timeseries_output_path(mesh, name)]
            call = lambda: HdfResultsMesh._mesh_series_id_dim(f, mesh, ds)  # noqa: E731
            python = _outcome(call, "0")
            auto = _outcome(call, "auto")
            required = _outcome(call, "rust")
            assert python[0] != "FastHdfError"
            assert auto == python, (name, python, auto)
            assert required == python or required[0] == "FastHdfError", (name, python, required)
            rows.append({"fixture": label, "mesh": mesh, "series": name, "python": python,
                         "required_refused": required[0] == "FastHdfError"})
    if RESULTS:
        with open(f"{RESULTS}.modes", "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")


def test_python_mode_has_no_engine_domain(monkeypatch):
    from ras_commander import fast_hdf
    legacy = [f["path"] for f in FIXTURES if f["name"] == "AustinOyster.p03"]
    if not legacy:
        pytest.skip("AustinOyster.p03 not in RAS_ROUTE2_FIXTURES")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "0")
    with h5py.File(legacy[0], "r") as f:
        mesh = next(iter(f[AREAS]))
        assert fast_hdf.mesh_series_domain(f[f"{AREAS}/{mesh}/Depth"]) is None
        with pytest.raises(ValueError, match="not a Base Output 2D mesh time series"):
            fast_hdf.mesh_series_domain(f[f"{BASE}/Time"])
