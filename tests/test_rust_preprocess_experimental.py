"""Fast tests for the experimental Rust preprocessing harness (no engine, no HEC-RAS).

The comparator, report and guarded write-back run on the real Chippewa_2D g01
geometry HDF from ``RasExamples``. Perturbations are made on temporary copies.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import (
    ExperimentalWarning,
    GeomPreprocessor,
    RustEquivalenceReport,
    RustPreprocessError,
    RustPreprocessNotFoundError,
    RustPreprocessRefusedError,
)
from ras_commander.RasExamples import RasExamples
from ras_commander.geom import _rust_preprocess as rp
from ras_commander.schemas import DATAFRAME_SCHEMAS

AREA = "Perimeter 1"
GROUP = f"Geometry/2D Flow Areas/{AREA}"


@pytest.fixture(scope="module")
def geom_hdf(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("rust_pre_chippewa")
    project = RasExamples.extract_project("Chippewa_2D", output_path=root)
    g = project / "Chippewa_2D.g01.hdf"
    assert g.is_file()
    return g


@pytest.fixture
def pair(geom_hdf, tmp_path):
    a, b = tmp_path / "native.g02.hdf", tmp_path / "rust.g02.hdf"
    shutil.copy2(geom_hdf, a)
    shutil.copy2(geom_hdf, b)
    return a, b


def _by_name(comparisons):
    return {c.dataset: c for c in comparisons}


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_identical_files_are_bitwise(pair):
    comparisons, attrs = rp.compare_geometry_hdfs(*pair)
    assert comparisons and all(c.status == "bitwise" and c.passed for c in comparisons)
    assert attrs == {}
    cats = {c.category for c in comparisons}
    assert cats == {"product", "input"}
    assert _by_name(comparisons)["Faces Cell Indexes"].category == "input"
    assert _by_name(comparisons)["Cells Minimum Elevation"].category == "product"


def test_one_ulp_cell_difference_is_located(pair):
    native, rust = pair
    with h5py.File(rust, "r+") as f:
        d = f[f"{GROUP}/Cells Minimum Elevation"]
        v = d[()]
        cell = int(np.flatnonzero(np.isfinite(v))[100])
        v[cell] = np.nextafter(v[cell], np.float32(np.inf), dtype=np.float32)
        d[...] = v
    c = _by_name(rp.compare_geometry_hdfs(native, rust)[0])["Cells Minimum Elevation"]
    assert c.status == "different" and not c.passed
    assert (c.n_different, c.max_ulp, c.id_kind, c.n_ids_different, c.ids_different) == (1, 1, "cell", 1, [cell])
    # A 0.01 bar accepts it; the same bar on an exact file is still "bitwise".
    tol = _by_name(rp.compare_geometry_hdfs(native, rust, tolerance=0.01)[0])
    assert tol["Cells Minimum Elevation"].status == "within_tolerance"
    assert tol["Cells Minimum Elevation"].passed
    assert tol["Faces Minimum Elevation"].status == "bitwise"
    # Per-dataset tolerance mapping: only the named dataset is relaxed.
    m = _by_name(rp.compare_geometry_hdfs(native, rust, tolerance={"Faces Minimum Elevation": 1.0})[0])
    assert m["Cells Minimum Elevation"].status == "different"


def test_packed_table_difference_maps_to_face(pair):
    native, rust = pair
    with h5py.File(rust, "r+") as f:
        info = f[f"{GROUP}/Faces Area Elevation Info"][()]
        d = f[f"{GROUP}/Faces Area Elevation Values"]
        v = d[()]
        face = 777  # of 814
        start, count = info[face]
        v[start + count - 1, 1] += np.float32(0.5)  # area of the top row
        d[...] = v
    c = _by_name(rp.compare_geometry_hdfs(native, rust)[0])["Faces Area Elevation Values"]
    assert c.id_kind == "face" and c.ids_different == [face] and c.n_different == 1
    assert c.max_abs_diff == pytest.approx(0.5, rel=1e-3)


def test_row_count_change_is_structural_even_with_tolerance(pair):
    native, rust = pair
    with h5py.File(rust, "r+") as f:
        gi = f[f"{GROUP}/Faces Area Elevation Info"]
        info = gi[()]
        face = 10
        # Move one row from face 10 to face 11: same total rows, different owners.
        assert info[face, 1] > 1
        info[face, 1] -= 1
        info[face + 1, 0] -= 1
        info[face + 1, 1] += 1
        gi[...] = info
    by = _by_name(rp.compare_geometry_hdfs(native, rust, tolerance=1e9)[0])
    vals = by["Faces Area Elevation Values"]
    assert vals.status == "different" and set(vals.ids_different) == {face, face + 1}
    # Integer datasets are always exact.
    assert by["Faces Area Elevation Info"].status == "different"


def test_missing_dataset_is_reported(pair):
    native, rust = pair
    with h5py.File(rust, "r+") as f:
        del f[f"{GROUP}/Cells Surface Area"]
    c = _by_name(rp.compare_geometry_hdfs(native, rust)[0])["Cells Surface Area"]
    assert c.status == "missing_rust" and not c.passed


def test_report_outputs(pair, tmp_path):
    native, rust = pair
    comparisons, _ = rp.compare_geometry_hdfs(native, rust)
    report = RustEquivalenceReport(
        verdict="equivalent", project_folder=tmp_path, geometry="Chippewa_2D.g01.hdf",
        hecras_version="7.0.1", engine=None, options={"mode": "native"}, tolerance=None,
        comparisons=comparisons, native_runs=1, labels={"D-4": rp.KNOWN_NATIVE_BEHAVIOURS["D-4"]},
    )
    j, md = report.write(tmp_path / "out")
    data = json.loads(j.read_text())
    assert data["verdict"] == "equivalent" and data["experimental"] is True
    assert data["summary"]["datasets"] == len(comparisons)
    text = md.read_text()
    assert "Experimental" in text and "**equivalent**" in text and "D-4" in text
    df = report.to_dataframe()
    schema = [c["name"] for c in DATAFRAME_SCHEMAS["rust_preprocess_equivalence"]["columns"]]
    assert list(df.columns) == schema
    assert len(df) == len(comparisons)


def _bundle_from(g: Path, out: Path, mutate=None) -> Path:
    """Write a bundle in the engine layout from a geometry HDF's own products."""
    out.mkdir()
    entries = []
    with h5py.File(g, "r") as f:
        grp = f[GROUP]
        attrs = {k: (int(grp.attrs[k]) if np.asarray(grp.attrs[k]).dtype.kind in "iu" else float(np.asarray(grp.attrs[k]).ravel()[0]))
                 for k in ("Manning's n", "Cell Volume Tolerance", "Face Area Elevation Tolerance") if k in grp.attrs}
        for name in ("Cells Center Manning's n", "Cells Minimum Elevation", "Cells Surface Area",
                     "Cells Volume Elevation Info", "Cells Volume Elevation Values",
                     "Faces Area Elevation Info", "Faces Area Elevation Values",
                     "Faces Low Elevation Centroid", "Faces Minimum Elevation"):
            a = grp[name][()]
            if mutate:
                a = mutate(name, a)
            file = name.replace(" ", "_").replace("'", "_") + ".bin"
            a.astype(a.dtype.newbyteorder("<")).tofile(out / file)
            entries.append({"area": AREA, "dataset": name, "stage": 0, "dtype": a.dtype.newbyteorder("<").str,
                            "shape": list(a.shape), "file": file})
    (out / "manifest.json").write_text(json.dumps({
        "mode": "native", "areas": [{"area": AREA, "attributes": attrs}], "datasets": entries}))
    return out


def _as_701(g: Path) -> None:
    with h5py.File(g, "r+") as f:
        f.attrs["File Version"] = np.bytes_(rp.SUPPORTED_FILE_VERSIONS[0])


def test_write_bundle_refuses_other_file_versions(pair, tmp_path):
    native, rust = pair
    bundle = _bundle_from(native, tmp_path / "b")
    before = _sha(rust)
    with pytest.raises(RustPreprocessError, match="File Version"):
        rp.write_bundle(rust, bundle)
    assert _sha(rust) == before


def test_write_bundle_writes_only_bundle_datasets(pair, tmp_path):
    native, rust = pair
    _as_701(rust)

    def bump(name, a):
        if name == "Cells Surface Area":
            a = a.copy()
            a[5] = a[5] * np.float32(1.5)
        return a

    bundle = _bundle_from(rust, tmp_path / "b", bump)
    receipt = rp.write_bundle(rust, bundle)
    assert receipt["datasets_changed"] == [f"{GROUP}/Cells Surface Area"]
    assert "cell tables" in receipt["areas"][AREA]["validation"]
    c = _by_name(rp.compare_geometry_hdfs(native, rust)[0])["Cells Surface Area"]
    assert c.ids_different == [5]


def test_write_bundle_rejects_invalid_products_and_restores(pair, tmp_path):
    native, rust = pair
    _as_701(rust)

    def bad(name, a):
        if name == "Cells Center Manning's n":
            a = a.copy()
            a[0] = np.nan
        return a

    bundle = _bundle_from(rust, tmp_path / "b", bad)
    before = _sha(rust)
    with pytest.raises(RustPreprocessError, match="Manning's n"):
        rp.write_bundle(rust, bundle)
    assert _sha(rust) == before
    assert not rust.with_name(rust.name + ".pre-rust.bak").exists()


def test_poison_and_unrecomputed_detection(pair):
    native, rust = pair
    masks = rp._nan_masks(rust)
    poisoned = rp._poison_products(rust)
    assert f"{AREA}/Cells Minimum Elevation" in poisoned
    assert all(not item.endswith("Info") for item in poisoned)  # integers are left alone
    stale = rp._unrecomputed(rust, poisoned, masks)
    assert stale and all("values" in s for s in stale)
    # Restoring one dataset clears it from the list; ghost-cell NaN does not count.
    with h5py.File(native, "r") as fn, h5py.File(rust, "r+") as fr:
        name = f"{GROUP}/Cells Minimum Elevation"
        fr[name][...] = fn[name][()]
    assert not any(s.startswith(f"{AREA}/Cells Minimum Elevation ") for s in rp._unrecomputed(rust, poisoned, masks))


def test_engine_not_found(monkeypatch, tmp_path):
    monkeypatch.delenv(rp.ENGINE_ENV_VAR, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(RustPreprocessNotFoundError, match=rp.ENGINE_ENV_VAR):
        rp.resolve_engine()
    monkeypatch.setenv(rp.ENGINE_ENV_VAR, str(tmp_path / "missing.exe"))
    with pytest.raises(RustPreprocessNotFoundError, match=rp.ENGINE_ENV_VAR):
        rp.resolve_engine()
    with pytest.raises(RustPreprocessNotFoundError, match="engine_exe"):
        rp.resolve_engine(tmp_path / "nope.exe")


@pytest.mark.parametrize("message, refused", [
    ("opening terrain T.hdf: /Modifications holds 1 layer(s); the terrain is refused because ...", True),
    ("terrain modification: rotated ellipse not supported", True),
    ("T.hdf: terrain TIFF is not tiled", True),
    ("Perimeter 1: stage 2: Land Cover Filename resolves to X.hdf, which does not exist; "
     "the Rust preprocessor does not resolve layers through the .rasmap", True),
    ("stage 3: Face Area Elevation Tolerance", False),
    ("opening g.hdf: No such file or directory", False),
])
def test_refusal_classification(message, refused):
    assert rp._is_refusal(message) is refused


def test_refused_error_names_what_was_refused(tmp_path):
    err = RustPreprocessRefusedError("Basin (Type=\"Circle\": rotated ellipse)", tmp_path / "g.hdf")
    assert "Basin" in str(err) and err.refusal.startswith("Basin")
    assert isinstance(err, RustPreprocessError)


def test_compute_guards_and_warning(geom_hdf, tmp_path):
    with pytest.warns(ExperimentalWarning):
        with pytest.raises(ValueError, match="out_path is required"):
            GeomPreprocessor.compute_rust_experimental(geom_hdf)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ExperimentalWarning)
        with pytest.raises(ValueError, match="in_place"):
            GeomPreprocessor.compute_rust_experimental(geom_hdf, out_path=geom_hdf)
        # The shipped Chippewa HDF is HEC-RAS 6.4: refused before the engine is even located.
        with pytest.raises(RustPreprocessError, match="File Version"):
            GeomPreprocessor.compute_rust_experimental(geom_hdf, out_path=tmp_path / "o.g02.hdf")
        with pytest.raises(ValueError, match="sort"):
            rp._engine_options(True, "quick", None, None)


# ---------------------------------------------------------------------------
# Currency restamp (restamp_currency)
# ---------------------------------------------------------------------------

LC = rp.LAST_COMPUTED_ATTR


def _stamp_type(path: Path):
    with h5py.File(path, "r") as f:
        aid = f[GROUP].attrs.get_id(LC)
        t = aid.get_type()
        return str(aid.dtype), aid.shape, t.get_size(), t.get_strpad(), t.get_cset()


def test_native_timestamp_format():
    from datetime import datetime

    assert rp._native_timestamp(datetime(2026, 11, 27, 22, 59, 52)) == "27NOV2026 22:59:52"
    assert rp._native_timestamp(datetime(2027, 1, 5, 3, 4, 5)) == "05JAN2027 03:04:05"
    assert len(rp._native_timestamp()) == 18


def test_write_bundle_restamps_last_computed_like_native(pair, tmp_path):
    from datetime import datetime

    _, rust = pair
    _as_701(rust)
    type_before = _stamp_type(rust)
    with h5py.File(rust, "r") as f:
        lc_hash_before = np.asarray(f[GROUP].attrs.get(rp.LC_HASH_ATTR)).tobytes()
    bundle = _bundle_from(rust, tmp_path / "b")
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        receipt = rp.write_bundle(rust, bundle, stamp_time=datetime(2026, 11, 27, 23, 1, 2))
    cur = receipt["currency"]
    assert cur["restamp_currency"] and cur["stamp"] == "27NOV2026 23:01:02"
    assert cur["areas"][AREA][LC]["status"] == "restamped"
    # Only the stamp changed, among every attribute of every object.
    assert cur["attributes_changed"] == [f"{GROUP}@{LC}"]
    with h5py.File(rust, "r") as f:
        assert bytes(f[GROUP].attrs[LC]) == b"27NOV2026 23:01:02"  # all 18 characters
        assert np.asarray(f[GROUP].attrs.get(rp.LC_HASH_ATTR)).tobytes() == lc_hash_before
    assert _stamp_type(rust) == type_before  # same fixed-length type, padding and charset
    # Chippewa carries an LC hash: it is kept, reported and warned about.
    assert rp.LC_HASH_ATTR in cur["not_restamped"][AREA]
    assert any(rp.LC_HASH_ATTR in str(x.message) for x in w)


def test_write_bundle_without_restamp_writes_no_attribute(pair, tmp_path):
    _, rust = pair
    _as_701(rust)
    with h5py.File(rust, "r") as f:
        before = bytes(f[GROUP].attrs[LC])
    receipt = rp.write_bundle(rust, _bundle_from(rust, tmp_path / "b"), restamp_currency=False)
    assert receipt["currency"]["restamp_currency"] is False
    assert receipt["currency"]["attributes_changed"] == []
    with h5py.File(rust, "r") as f:
        assert bytes(f[GROUP].attrs[LC]) == before


def test_write_bundle_never_creates_a_missing_stamp(pair, tmp_path):
    _, rust = pair
    _as_701(rust)
    with h5py.File(rust, "r+") as f:
        del f[GROUP].attrs[LC]
    receipt = rp.write_bundle(rust, _bundle_from(rust, tmp_path / "b"))
    assert receipt["currency"]["areas"][AREA][LC]["status"] == "absent"
    assert receipt["currency"]["attributes_changed"] == []
    with h5py.File(rust, "r") as f:
        assert LC not in f[GROUP].attrs


def test_report_states_stage2_coverage_and_attribute_meaning(pair, tmp_path):
    native, rust = pair
    with h5py.File(native, "r+") as f:
        g = f[GROUP]
        g.create_dataset("Infiltration/Curve Number", data=np.arange(5, dtype=np.float32))
        g.create_dataset("Percent Impervious/Percent Impervious", data=np.zeros(5, np.float32))
    shutil.copy2(native, rust)
    with h5py.File(rust, "r+") as f:
        f[GROUP].attrs.modify(LC, np.bytes_("01JAN2027 00:00:00"))
    comparisons, attrs = rp.compare_geometry_hdfs(native, rust)
    cov = rp._stage2_coverage(comparisons, {AREA: {"Infiltration/Curve Number"}})
    assert cov[AREA]["compared"] == ["Infiltration/Curve Number"]
    assert cov[AREA]["not_compared"] == ["Percent Impervious/Percent Impervious"]
    carried = _by_name(comparisons)["Percent Impervious/Percent Impervious"]
    assert carried.category == "carried" and any("not compared" in x for x in carried.labels)
    rep = RustEquivalenceReport(
        verdict="equivalent", project_folder=tmp_path, geometry="x.g01.hdf", hecras_version="7.0.1",
        engine=None, options={}, tolerance=None, comparisons=comparisons,
        attribute_differences=attrs, stage2_coverage=cov)
    md = rep.to_markdown()
    assert "Stage 2 infiltration and impervious coverage" in md
    assert "workstream P" in md and "**not compared**" in md and "does **not** compare" in md
    assert "(timestamp; expected)" in md
    assert rep.to_dict()["stage2_coverage"] == cov
