"""Tests for HdfSlim: lossless slim copies of 2D plan result HDF files.

The synthetic files reproduce the HEC-RAS Base Output layout (series root, mesh groups,
boundary-condition subgroups, summary output, time table) so the exact-byte, layout and
failure contracts can be checked without a solver. ``test_real_example_*`` exercises a
real HEC-RAS 2D result when the example project is available.
"""

import json
import os

import h5py
import numpy as np
import pytest

from ras_commander import HdfSlim, HdfSlimError, HdfSlimPolicy
from ras_commander.hdf import _hdf_slim_engine as engine
from ras_commander.hdf._hdf_slim_engine import SERIES_ROOT, sha256_file

T, C, F = 37, 1000, 2500
SMALL = {"time_chunk_steps": 8, "space_chunk_size": 300}
PLUVIAL = ("Cell Cumulative Precipitation Depth", "Cell Cumulative Excess Depth")


def _make(path, *, face_flow=True, pluvial=True, face_velocity=True, depth=False, meshes=("Mesh A",)):
    rng = np.random.default_rng(0)
    with h5py.File(path, "w") as h:
        h.attrs["File Type"] = np.bytes_("HEC-RAS Results")
        h.attrs["File Version"] = np.float32(6.6)
        g = h.create_group("Geometry/2D Flow Areas")
        attrs = np.array([(m.encode(), C) for m in meshes], dtype=[("Name", "S16"), ("Cell Count", "<i4")])
        g.create_dataset("Attributes", data=attrs)
        for mesh in meshes:
            g.create_dataset(f"{mesh}/Cells Minimum Elevation", data=rng.random(C).astype("f4"))
            s = h.create_group(f"{SERIES_ROOT}/{mesh}")
            s.attrs["Units"] = np.bytes_("ft")
            ws = (100 + rng.random((T, C))).astype("f4")
            ws[3, 7] = np.nan
            for name, shape in (
                ("Water Surface", (T, C)),
                ("Face Flow", (T, F)),
                ("Face Velocity", (T, F)),
                ("Cell Courant", (T, C)),
                ("Face Water Surface", (T, F)),
                ("Face Cumulative Volume", (T, F)),
                *((n, (T, C)) for n in PLUVIAL),
            ):
                if (name == "Face Flow" and not face_flow) or (name == "Face Velocity" and not face_velocity):
                    continue
                if name in PLUVIAL and not pluvial:
                    continue
                data = ws if name == "Water Surface" else rng.normal(size=shape).astype("f4")
                d = s.create_dataset(name, data=data, chunks=(1, shape[1]), compression="gzip",
                                     compression_opts=4)
                d.attrs["Units"] = np.bytes_("ft" if "Water" in name else "cfs")
                d.attrs["Scale"] = np.float32(1.0)
            if depth:
                s.create_dataset("Depth", data=rng.random((T, C)).astype("f4"))
            s.create_dataset("Small Table", data=np.arange(5, dtype="i4"))  # not a series: kept
            bc = s.create_group("Boundary Conditions")
            bc.create_dataset("BC_1 - Flow per Face", data=rng.random((T, 12)).astype("f4"))
            h.create_dataset(
                "Results/Unsteady/Output/Output Blocks/Base Output/Summary Output/2D Flow Areas"
                f"/{mesh}/Maximum Water Surface",
                data=rng.random((2, C)).astype("f4"),
            )
        h.create_dataset(
            "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time",
            data=np.arange(T, dtype="f8") / 1440,
        )


def _names(rows):
    return {r["path"].rsplit("/", 1)[1] for r in rows}


@pytest.fixture
def src(tmp_path):
    path = tmp_path / "plan.p01.hdf"
    _make(path)
    return path


# ---- slim: exactness, layout, manifest -------------------------------------------------


def test_slim_keeps_layout_and_exact_values(src, tmp_path):
    out = tmp_path / "slim.hdf"
    m = HdfSlim.slim(src, out, HdfSlim.get_policy(**SMALL), workers=2)
    assert m["schema"] == "ras-commander-hdf-slim/v1"
    assert m["status"] == "completed" and m["reason_code"] == "HDF_SLIM_VERIFIED"
    assert m["verification"] == {
        "method": "every kept object: shape, dtype, attributes, exact bytes",
        "objects_checked": m["verification"]["objects_checked"],
        "problem_count": 0,
        "problems": [],
    } and m["verification"]["objects_checked"] > 10
    assert _names(m["dropped"]) == {"Face Velocity", "Cell Courant", "Face Water Surface",
                                    "Face Cumulative Volume"}
    assert _names(m["rechunked"]) == {"Water Surface", "Face Flow", *PLUVIAL}
    assert m["source"] == {"name": "plan.p01.hdf", "bytes": src.stat().st_size,
                           "sha256": sha256_file(src), "sha256_verified": True}
    assert m["output"] == {"name": "slim.hdf", "bytes": out.stat().st_size, "sha256": sha256_file(out)}
    assert m["fallbacks_applied"] == {} and m["meshes"] == ["Mesh A"]
    with h5py.File(src) as a, h5py.File(out) as b:
        for k in ("Water Surface", "Face Flow"):
            x, y = a[f"{SERIES_ROOT}/Mesh A/{k}"], b[f"{SERIES_ROOT}/Mesh A/{k}"]
            assert y.chunks == (8, 300) and y.shuffle and y.compression == "gzip"
            assert x[...].tobytes() == y[...].tobytes()
            assert y.attrs["Units"] == x.attrs["Units"]
        assert np.isnan(b[f"{SERIES_ROOT}/Mesh A/Water Surface"][3, 7])
        assert "Face Velocity" not in b[f"{SERIES_ROOT}/Mesh A"]
        assert b[f"{SERIES_ROOT}/Mesh A/Small Table"][...].tolist() == [0, 1, 2, 3, 4]
        assert f"{SERIES_ROOT}/Mesh A/Boundary Conditions/BC_1 - Flow per Face" in b
        assert b.attrs["File Type"] == a.attrs["File Type"]
        assert b["Geometry/2D Flow Areas/Attributes"][0]["Name"] == b"Mesh A"
    assert not (tmp_path / "slim.hdf.partial").exists()


def test_default_layout_and_descriptors(src, tmp_path):
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    for row in m["rechunked"]:
        assert row["chunks"] == [min(16, row["shape"][0]), min(16384, row["shape"][1])]
        assert row["filters"] == ["shuffle", "deflate:4"]
        assert row["path"].startswith(f"/{SERIES_ROOT}/Mesh A/") and row["dtype"] == "float32"
        assert set(row) == {"path", "shape", "dtype", "source_chunks", "source_filters",
                            "source_stored_bytes", "chunks", "filters", "stored_bytes"}
    assert m["policy"] == {
        "name": "inundation-mapping",
        "keep": ["Water Surface", "Face Flow", *PLUVIAL, "Depth"],
        "required": ["Water Surface", "Face Flow"],
        "keep_if_present": [*PLUVIAL, "Depth"],
        "fallbacks": {"Face Flow": "Face Velocity"},
        "extra_series": [],
        "time_chunk_steps": 16,
        "space_chunk_size": 16384,
        "deflate_level": 4,
        "series_root": SERIES_ROOT,
    }
    assert set(m["software"]) == {"python", "h5py", "hdf5", "numpy", "implementation_sha256"}
    assert m["software"]["implementation_sha256"] == HdfSlim.implementation_sha256()


def test_manifest_has_no_paths(src, tmp_path):
    man = tmp_path / "m.json"
    HdfSlim.slim(src, tmp_path / "s.hdf", manifest_path=man)
    text = man.read_text(encoding="utf-8")
    assert str(tmp_path) not in text and str(tmp_path).replace("\\", "/") not in text
    assert b"\r\n" not in man.read_bytes()


def test_extra_series_is_additive_and_ordered(src, tmp_path):
    m = HdfSlim.slim(src, tmp_path / "s.hdf", extra_series=["Face Cumulative Volume"], hash_source=False)
    assert _names(m["rechunked"]) == {"Water Surface", "Face Flow", "Face Cumulative Volume", *PLUVIAL}
    assert m["policy"]["keep"] == ["Water Surface", "Face Flow", "Face Cumulative Volume", *PLUVIAL, "Depth"]
    assert m["policy"]["required"] == ["Water Surface", "Face Flow", "Face Cumulative Volume"]
    assert m["source"]["sha256"] is None and m["source"]["sha256_verified"] is False


def test_extra_series_must_exist(src, tmp_path):
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf", extra_series=["Cell Velocity"])
    assert e.value.reason_code == "HDF_SLIM_REQUIRED_DATASET_MISSING"


def test_missing_face_flow_and_velocity_fails_without_output(tmp_path):
    src, out = tmp_path / "p.hdf", tmp_path / "s.hdf"
    _make(src, face_flow=False, face_velocity=False)
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, out)
    assert e.value.reason_code == "HDF_SLIM_REQUIRED_DATASET_MISSING"
    assert not out.exists() and not (tmp_path / "s.hdf.partial").exists()


def test_face_velocity_kept_when_face_flow_absent(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, face_flow=False, meshes=("Mesh A", "Mesh B"))
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert "Face Velocity" in _names(m["rechunked"])
    assert m["fallbacks_applied"] == {"Mesh A": {"Face Flow": "Face Velocity"},
                                      "Mesh B": {"Face Flow": "Face Velocity"}}


def test_fallback_layout_is_validated(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, face_flow=False, face_velocity=False)
    with h5py.File(src, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A"].create_dataset("Face Velocity", data=np.ones((T + 1, 4), "f4"))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"


def test_depth_kept_when_present(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, depth=True)
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert "Depth" in _names(m["rechunked"]) and "Face Velocity" not in _names(m["rechunked"])


def test_pluvial_series_are_optional(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, pluvial=False)
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert _names(m["rechunked"]) == {"Water Surface", "Face Flow"}


def test_multiple_meshes(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, meshes=("Upper", "Lower"))
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["meshes"] == ["Lower", "Upper"] or m["meshes"] == ["Upper", "Lower"]
    for mesh in m["meshes"]:
        kept = [r for r in m["rechunked"] if r["path"].startswith(f"/{SERIES_ROOT}/{mesh}/")]
        assert _names(kept) == {"Water Surface", "Face Flow", *PLUVIAL}


def test_output_exists_and_stale_partial(src, tmp_path):
    out = tmp_path / "s.hdf"
    out.write_bytes(b"x")
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, out)
    assert e.value.reason_code == "HDF_SLIM_OUTPUT_EXISTS"
    out.unlink()
    (tmp_path / "s.hdf.partial").write_bytes(b"x")
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, out)
    assert e.value.reason_code == "HDF_SLIM_OUTPUT_EXISTS"


def test_not_a_2d_result(tmp_path):
    src = tmp_path / "p.hdf"
    with h5py.File(src, "w") as h:
        h.create_dataset("Geometry/x", data=[1])
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_NO_2D_SERIES"


def test_unreadable_source_is_bad_input(tmp_path):
    src = tmp_path / "p.hdf"
    src.write_bytes(b"not an hdf5 file")
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_INPUT_INVALID"


def test_insufficient_space_is_checked_before_writing(src, tmp_path, monkeypatch):
    usage = type(engine.shutil.disk_usage(tmp_path))
    monkeypatch.setattr(engine.shutil, "disk_usage", lambda p: usage(10, 9, 1))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_INSUFFICIENT_SPACE"
    assert not list(tmp_path.glob("s.hdf*"))


def test_verify_failure_leaves_no_output(src, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "verify", lambda *a: {"objects_checked": 1, "problems": ["/x: data differ"],
                                                        "problem_count": 1})
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_VERIFY_FAILED"
    assert not list(tmp_path.glob("s.hdf*"))


def test_links_are_unsupported(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A/Alias"] = h5py.SoftLink(f"/{SERIES_ROOT}/Mesh A/Water Surface")
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"
    assert not list(tmp_path.glob("s.hdf*"))


def test_bounded_tiles_match_unbounded(src, tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "MAX_PENDING_TILES", 1)
    policy = HdfSlim.get_policy(time_chunk_steps=5, space_chunk_size=128)
    m = HdfSlim.slim(src, tmp_path / "s.hdf", policy)
    assert m["verification"]["problem_count"] == 0


def test_integer_series_and_edge_chunks(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src)
    with h5py.File(src, "r+") as h:
        g = h[f"{SERIES_ROOT}/Mesh A"]
        g.create_dataset("Cell Flags", data=np.arange(T * 7, dtype="i2").reshape(T, 7), fillvalue=-9)
    m = HdfSlim.slim(src, tmp_path / "s.hdf", {"required": ["Water Surface", "Cell Flags"], **SMALL})
    row = next(r for r in m["rechunked"] if r["path"].endswith("Cell Flags"))
    assert row["dtype"] == "int16" and row["chunks"] == [8, 7]


# ---- layout validation (named series, time axis, empty, links, vlen, space) -------------


def test_required_series_on_wrong_time_axis_is_refused(src, tmp_path):
    with h5py.File(src, "r+") as h:
        g = h[f"{SERIES_ROOT}/Mesh A"]
        del g["Face Flow"]
        g.create_dataset("Face Flow", data=np.ones((T - 1, F), "f4"))
    for call in (lambda: HdfSlim.slim(src, tmp_path / "s.hdf"), lambda: HdfSlim.plan(src)):
        with pytest.raises(HdfSlimError) as e:
            call()
        assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"
    assert not list(tmp_path.glob("s.hdf*"))


def test_kept_if_present_series_on_wrong_time_axis_is_refused(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A"].create_dataset("Depth", data=np.ones((T + 2, C), "f4"))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"


def test_water_surface_must_match_time_table(src, tmp_path):
    with h5py.File(src, "r+") as h:
        del h["Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time"]
        h.create_dataset("Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series/Time",
                         data=np.arange(T + 1, dtype="f8"))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"


def test_unnamed_table_off_the_time_axis_is_copied_unchanged(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A"].create_dataset("Lookup", data=np.ones((T - 5, 3), "f4"))
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert "Lookup" not in _names(m["dropped"]) | _names(m["rechunked"])
    with h5py.File(tmp_path / "s.hdf") as b:
        assert b[f"{SERIES_ROOT}/Mesh A/Lookup"].shape == (T - 5, 3)


@pytest.mark.parametrize("shape", [(T, 0)])
def test_empty_kept_series_is_unsupported(src, tmp_path, shape):
    with h5py.File(src, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A"].create_dataset("Depth", shape=shape, dtype="f4")
    for call in (lambda: HdfSlim.slim(src, tmp_path / "s.hdf"), lambda: HdfSlim.plan(src)):
        with pytest.raises(HdfSlimError) as e:
            call()
        assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"


def test_zero_time_steps_is_unsupported(tmp_path):
    src = tmp_path / "p.hdf"
    with h5py.File(src, "w") as h:
        g = h.create_group(f"{SERIES_ROOT}/Mesh A")
        g.create_dataset("Water Surface", shape=(0, 4), dtype="f4", maxshape=(None, 4))
        g.create_dataset("Face Flow", shape=(0, 6), dtype="f4", maxshape=(None, 6))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"


PROPERTY_TABLES = "Geometry/Cross Sections/Property Tables"


def _addr(h, path):
    return h5py.h5o.get_info(h[path].id).addr


BLOCKS = "Results/Unsteady/Output/Output Blocks"
MESH_BC = f"{SERIES_ROOT}/Mesh A/Boundary Conditions"
BLOCK_BC = f"{BLOCKS}/Base Output/Unsteady Time Series/Boundary Conditions"


def _link_property_tables(src):
    """The hard links a real HEC-RAS 2D result carries (UPGU3 canary layout), plus a dataset alias.

    Property tables shared by Cross Sections and GeomPreprocess, one Summary Output group shared
    by three output blocks, and each mesh boundary-condition table shared with the block-level
    Boundary Conditions group.
    """
    with h5py.File(src, "r+") as h:
        g = h.create_group(PROPERTY_TABLES)
        g.attrs["Count"] = np.int32(2)
        g.create_dataset("XS 1", data=np.arange(12, dtype="f4").reshape(3, 4), chunks=(1, 4), compression="gzip")
        g.create_dataset("XS 2", data=np.arange(8, dtype="f8"))
        h["Geometry/GeomPreprocess/Property Tables"] = g
        h["Geometry/Cells Alias"] = h["Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation"]
        summary = h[f"{BLOCKS}/Base Output/Summary Output"]
        h[f"{BLOCKS}/DSS Hydrograph Output/Summary Output"] = summary
        h[f"{BLOCKS}/DSS Adaptive Hydrograph Output/Summary Output"] = summary
        bc = h[MESH_BC]
        bc.create_dataset("BC_1", data=np.arange(T * 2, dtype="f4").reshape(T, 2))
        bc.create_dataset("BC_1 - Stage per Face", data=np.ones((T, 12), "f4"))
        for name in ("BC_1", "BC_1 - Flow per Face", "BC_1 - Stage per Face"):
            h[f"{BLOCK_BC}/{name}"] = bc[name]


def test_hard_links_outside_the_series_are_preserved(src, tmp_path):
    _link_property_tables(src)
    out = tmp_path / "s.hdf"
    planned = HdfSlim.plan(src)
    m = HdfSlim.slim(src, out)
    links = {
        "/Geometry/GeomPreprocess/Property Tables": "/Geometry/Cross Sections/Property Tables",
        "/Geometry/Cells Alias": "/Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation",
        f"/{BLOCKS}/DSS Hydrograph Output/Summary Output": f"/{BLOCKS}/Base Output/Summary Output",
        f"/{BLOCKS}/DSS Adaptive Hydrograph Output/Summary Output": f"/{BLOCKS}/Base Output/Summary Output",
        **{f"/{BLOCK_BC}/{n}": f"/{MESH_BC}/{n}" for n in ("BC_1", "BC_1 - Flow per Face", "BC_1 - Stage per Face")},
    }
    assert {r["path"]: r["target"] for r in m["hard_links"]} == links
    assert planned["hard_links"] == m["hard_links"]
    assert m["verification"]["problem_count"] == 0
    with h5py.File(out, "r") as h:
        for alias, target in links.items():
            assert _addr(h, alias) == _addr(h, target)
        assert h5py.h5o.get_info(h[f"{BLOCKS}/Base Output/Summary Output"].id).rc == 3
        assert h5py.h5o.get_info(h[f"{MESH_BC}/BC_1"].id).rc == 2
        mws = f"{BLOCKS}/DSS Hydrograph Output/Summary Output/2D Flow Areas/Mesh A/Maximum Water Surface"
        assert h[mws].shape == (2, C)
        np.testing.assert_array_equal(h[f"{PROPERTY_TABLES}/XS 1"][()], np.arange(12).reshape(3, 4))
        assert h[f"{PROPERTY_TABLES}/XS 1"].compression == "gzip"


def test_hard_linked_objects_are_copied_once(src, tmp_path):
    plain = HdfSlim.slim(src, tmp_path / "plain.hdf")
    plain_other = HdfSlim.plan(src)["other_stored_bytes"]
    with h5py.File(src, "r+") as h:
        h["Geometry/Cells Alias"] = h["Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation"]
    assert HdfSlim.plan(src)["other_stored_bytes"] == plain_other
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["copied_datasets"] == plain["copied_datasets"]
    assert m["output"]["bytes"] < plain["output"]["bytes"] + 4096


def test_hard_link_cycle_outside_the_series_is_preserved(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h["Geometry/2D Flow Areas/Mesh A/Up"] = h["Geometry/2D Flow Areas"]
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["hard_links"] == [{"path": "/Geometry/2D Flow Areas/Mesh A/Up", "target": "/Geometry/2D Flow Areas"}]
    assert m["verification"]["problem_count"] == 0


@pytest.mark.parametrize(
    ("alias", "target"),
    [
        (f"{SERIES_ROOT}/Mesh A/Alias", f"{SERIES_ROOT}/Mesh A/Water Surface"),  # inside a mesh group
        ("Geometry/WS Alias", f"{SERIES_ROOT}/Mesh A/Water Surface"),  # a kept series, from outside
        ("Geometry/Dropped Alias", f"{SERIES_ROOT}/Mesh A/Face Velocity"),  # a dropped series
        ("Geometry/Mesh Alias", f"{SERIES_ROOT}/Mesh A"),  # a mesh series group
        ("Geometry/Output Alias", "Results/Unsteady/Output"),  # an ancestor of the series root
        ("Geometry/Root Alias", SERIES_ROOT),  # the series root itself
        ("Geometry/File Root", "/"),  # the file root (a cycle)
        (f"{SERIES_ROOT}/Mesh A/Small Alias", f"{SERIES_ROOT}/Mesh A/Small Table"),  # any mesh dataset
        (f"{SERIES_ROOT}/Mesh A/Elevation", "Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation"),
    ],
)
def test_hard_links_touching_the_series_tree_are_refused(src, tmp_path, alias, target):
    with h5py.File(src, "r+") as h:
        h[alias] = h[target]
    for call in (lambda: HdfSlim.plan(src), lambda: HdfSlim.slim(src, tmp_path / "s.hdf")):
        with pytest.raises(HdfSlimError) as e:
            call()
        assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"
        assert "hard link at a policy-controlled 2D series path" in str(e.value)
    assert not list(tmp_path.glob("s.hdf*"))


def _rewrite(src, dst, edit):
    """Copy ``src`` to ``dst`` object by object (h5py copy splits nothing), then apply ``edit``."""
    import shutil

    shutil.copyfile(src, dst)
    with h5py.File(dst, "r+") as h:
        edit(h)


def test_verify_refuses_a_split_hard_link(src, tmp_path):
    _link_property_tables(src)
    out = tmp_path / "s.hdf"
    m = HdfSlim.slim(src, out)
    dropped = [d["path"] for d in m["dropped"]]
    alias = "Geometry/GeomPreprocess/Property Tables"

    def split(h):
        del h[alias]
        h.copy(h[PROPERTY_TABLES], h["Geometry/GeomPreprocess"], name="Property Tables")

    bad = tmp_path / "split.hdf"
    _rewrite(out, bad, split)
    result = engine.verify(src, bad, dropped)
    assert any("hard link to /Geometry/Cross Sections/Property Tables not preserved" in x for x in result["problems"])


def test_verify_refuses_a_hard_link_not_in_source(src, tmp_path):
    out = tmp_path / "s.hdf"
    m = HdfSlim.slim(src, out)
    dropped = [d["path"] for d in m["dropped"]]
    with h5py.File(src, "r+") as h:
        h.copy(h["Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation"], h["Geometry"], name="Copy")

    def link(h):
        h["Geometry/Copy"] = h["Geometry/2D Flow Areas/Mesh A/Cells Minimum Elevation"]

    bad = tmp_path / "linked.hdf"
    _rewrite(out, bad, link)
    result = engine.verify(src, bad, dropped)
    assert result["problems"] == ["/Geometry/Copy: hard link not in source"]


def test_verify_refuses_a_dropped_series_kept_under_an_alias(src, tmp_path):
    out = tmp_path / "s.hdf"
    m = HdfSlim.slim(src, out)
    dropped = [d["path"] for d in m["dropped"]]
    velocity = f"{SERIES_ROOT}/Mesh A/Face Velocity"
    assert f"/{velocity}" in dropped
    with h5py.File(src, "r+") as h:
        h["Geometry/Velocity Alias"] = h[velocity]

    def keep(h):
        with h5py.File(src, "r") as s:
            s.copy(s[velocity], h["Geometry"], name="Velocity Alias")

    rogue = tmp_path / "rogue.hdf"
    _rewrite(out, rogue, keep)
    assert engine.verify(src, rogue, dropped)["problems"] == [
        "/Geometry/Velocity Alias: hard link to a dropped dataset present"
    ]


def test_undefined_object_address_fails_closed(src, tmp_path, monkeypatch):
    class Info:
        addr, rc = (1 << 64) - 1, 1

    monkeypatch.setattr(engine.h5py.h5o, "get_info", lambda _id: Info())
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_UNSUPPORTED_LAYOUT"
    assert not list(tmp_path.glob("s.hdf*"))


def test_link_target_is_the_first_path_in_walk_order(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h["Geometry/Z Original"] = np.arange(3)
        h["Geometry/A Alias"] = h["Geometry/Z Original"]
        h["Geometry/M Alias"] = h["Geometry/Z Original"]
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["hard_links"] == [
        {"path": "/Geometry/M Alias", "target": "/Geometry/A Alias"},
        {"path": "/Geometry/Z Original", "target": "/Geometry/A Alias"},
    ]
    with h5py.File(tmp_path / "s.hdf", "r") as h:
        assert h5py.h5o.get_info(h["Geometry/A Alias"].id).rc == 3


def test_verify_checks_every_link_path(src, tmp_path):
    _link_property_tables(src)
    out = tmp_path / "s.hdf"
    m = HdfSlim.slim(src, out)
    dropped = [d["path"] for d in m["dropped"]]
    with h5py.File(src, "r") as h:
        n_paths = sum(1 for _ in _all_paths(h))
    assert m["verification"]["objects_checked"] == n_paths - len(dropped)

    def drop_alias(h):
        del h["Geometry/Cells Alias"]

    bad = tmp_path / "noalias.hdf"
    _rewrite(out, bad, drop_alias)
    assert engine.verify(src, bad, dropped)["problems"] == ["/Geometry/Cells Alias: missing"]


def _all_paths(h, prefix=""):
    seen = set()

    def walk(g, prefix):
        for k in g:
            obj = g[k]
            yield f"{prefix}/{k}"
            addr = h5py.h5o.get_info(obj.id).addr
            if isinstance(obj, h5py.Group) and addr not in seen:
                seen.add(addr)
                yield from walk(obj, f"{prefix}/{k}")

    yield from walk(h, prefix)


def test_variable_length_numeric_and_compound_datasets_verify(src, tmp_path):
    with h5py.File(src, "r+") as h:
        vl = h.create_dataset("Plan Data/Ragged", shape=(3,), dtype=h5py.vlen_dtype("f8"))
        vl[0], vl[1], vl[2] = np.array([1.0, np.nan]), np.array([]), np.arange(4.0)
        comp = np.dtype([("Name", h5py.string_dtype()), ("Value", "f8")])
        h.create_dataset("Plan Data/Table", data=np.array([("a", 1.5), ("b", np.nan)], dtype=comp))
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["verification"]["problem_count"] == 0
    with h5py.File(tmp_path / "s.hdf", "r+") as b:
        b["Plan Data/Ragged"][2] = np.arange(5.0)
    assert any("Ragged: data differ" in p for p in HdfSlim.verify(src, tmp_path / "s.hdf", m)["problems"])


def test_verify_detects_fill_value_and_maxshape_changes(tmp_path):
    a, b = tmp_path / "a.hdf", tmp_path / "b.hdf"
    with h5py.File(a, "w") as h:
        h.create_dataset("x", data=np.ones((2, 3)), maxshape=(None, 3), fillvalue=0.0)
    with h5py.File(b, "w") as h:
        h.create_dataset("x", data=np.ones((2, 3)), maxshape=(2, 3), fillvalue=99.0)
    result = engine.verify(a, b, [])
    assert result["problems"] == ["/x: fill value or maximum shape differs"]


def test_space_check_counts_copied_datasets(src, tmp_path, monkeypatch):
    report = HdfSlim.plan(src)
    assert report["required_free_bytes"] == (report["kept_series_raw_bytes"]
                                             + report["other_stored_bytes"] + (1 << 30))
    usage = type(engine.shutil.disk_usage(tmp_path))
    just_kept = report["kept_series_raw_bytes"] + (1 << 30)  # enough for kept series only
    monkeypatch.setattr(engine.shutil, "disk_usage", lambda p: usage(10 * just_kept, 0, just_kept))
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf")
    assert e.value.reason_code == "HDF_SLIM_INSUFFICIENT_SPACE"


def test_cli_manifest_write_failure_is_coded(src, tmp_path, capsys):
    man = tmp_path / "folder-missing" / "m.json"
    assert engine.main([str(src), str(tmp_path / "s.hdf"), "--manifest", str(man)]) == 1
    assert "HDF_SLIM_IO_ERROR" in capsys.readouterr().err


# ---- policies --------------------------------------------------------------------------


def test_custom_policy_keeps_exactly_what_it_names(src, tmp_path):
    policy = {"required": ["Water Surface"], "keep_if_present": ["Cell Courant", "Not There"]}
    m = HdfSlim.slim(src, tmp_path / "s.hdf", policy)
    assert _names(m["rechunked"]) == {"Water Surface", "Cell Courant"}
    assert m["policy"]["name"] is None and m["policy"]["fallbacks"] == {}


def test_policy_round_trips_through_manifest(src, tmp_path):
    m = HdfSlim.slim(src, tmp_path / "s.hdf", extra_series=["Face Cumulative Volume"])
    again = HdfSlim.get_policy(m["policy"])
    assert again.to_dict() == m["policy"]
    assert again.extra_series == ("Face Cumulative Volume",)
    second = HdfSlim.slim(src, tmp_path / "t.hdf", m["policy"])
    assert second["policy"] == m["policy"]
    bad = dict(m["policy"], required=["Water Surface", "Face Flow"])  # extras missing
    with pytest.raises(HdfSlimError):
        HdfSlim.get_policy(bad)


def test_presets_round_trip():
    for name, policy in HdfSlim.list_presets().items():
        assert HdfSlim.get_policy(policy).to_dict() == policy == HdfSlim.get_policy(name).to_dict()


@pytest.mark.parametrize(
    "spec",
    [
        {"required": [""]},
        {"required": []},
        {"required": ["A", "A"]},
        {"required": "Water Surface"},
        {"required": ["A"], "keep_if_present": ["A"]},
        {"required": ["A"], "extra_series": ["A"]},
        {"required": ["A"], "fallbacks": {"B": "C"}},
        {"required": ["A"], "fallbacks": {"A": 123}},
        {"required": ["A", "B"], "fallbacks": {"A": "B"}},
        {"required": ["A"], "time_chunk_steps": 0},
        {"required": ["A"], "space_chunk_size": 2.5},
        {"required": ["A"], "deflate_level": 10},
        {"required": ["A"], "unknown": 1},
        {"required": ["A/B"]},
        {"required": ["A"], "keep": ["B"]},
        {"required": ["A"], "series_root": "Other"},
    ],
)
def test_invalid_policy(spec):
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.get_policy(spec)
    assert e.value.reason_code == "HDF_SLIM_INVALID_POLICY"


def test_preset_overrides_and_errors():
    p = HdfSlim.get_policy("inundation-mapping", ["Face Cumulative Volume"], deflate_level=6)
    assert p.deflate_level == 6 and p.extra_series == ("Face Cumulative Volume",)
    assert HdfSlim.get_policy(p) is p
    assert HdfSlim.get_policy(p, ["Cell Courant"]).extra_series == ("Face Cumulative Volume", "Cell Courant")
    for bad in ("no-such-preset",):
        with pytest.raises(HdfSlimError):
            HdfSlim.get_policy(bad)
    with pytest.raises(HdfSlimError):
        HdfSlim.get_policy(extra_series="Depth")
    with pytest.raises(HdfSlimError):
        HdfSlim.get_policy(extra_series=["Face Flow"])  # already required
    with pytest.raises(HdfSlimError):
        HdfSlim.get_policy(workers=3)
    assert list(HdfSlim.list_presets()) == ["inundation-mapping"]
    assert isinstance(p, HdfSlimPolicy)


# ---- plan (dry run) and verify ----------------------------------------------------------


def test_plan_matches_slim_and_writes_nothing(src, tmp_path):
    before = sorted(p.name for p in tmp_path.iterdir())
    report = HdfSlim.plan(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert report["schema"] == "ras-commander-hdf-slim-plan/v1"
    assert {r["path"] for r in report["dropped"]} == {r["path"] for r in m["dropped"]}
    assert {r["path"] for r in report["kept"]} == {r["path"] for r in m["rechunked"]}
    assert report["applied_keep"] == {"Mesh A": sorted(r["path"] for r in m["rechunked"])}
    assert report["policy"] == m["policy"]
    assert report["required_free_bytes"] == (report["kept_series_raw_bytes"]
                                             + report["other_stored_bytes"] + (1 << 30))
    assert report["kept_series_raw_bytes"] == sum(r["raw_bytes"] for r in report["kept"])


def test_plan_reports_missing_required(tmp_path):
    src = tmp_path / "p.hdf"
    _make(src, face_flow=False, face_velocity=False)
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.plan(src)
    assert e.value.reason_code == "HDF_SLIM_REQUIRED_DATASET_MISSING"


def test_verify_passes_and_detects_tampering(src, tmp_path):
    out = tmp_path / "s.hdf"
    man = tmp_path / "s.hdf_slim.json"
    HdfSlim.slim(src, out, manifest_path=man)
    result = HdfSlim.verify(src, out, man)
    assert result["passed"] and result["problem_count"] == 0 and result["objects_checked"] > 10
    with h5py.File(out, "r+") as h:
        h[f"{SERIES_ROOT}/Mesh A/Water Surface"][0, 0] = 1.0
    result = HdfSlim.verify(src, out, man)
    assert not result["passed"]
    assert {"output size differs from manifest", "output sha256 differs from manifest"} & set(
        result["problems"])
    assert any("data differ" in p for p in result["problems"])


# ---- command line -----------------------------------------------------------------------


def test_cli_manifest_and_exit_codes(src, tmp_path, capsys):
    out, man = tmp_path / "s.hdf", tmp_path / "hdf_slim.json"
    argv = [str(src), str(out), "--manifest", str(man), "--time-chunk-steps", "4"]
    assert engine.main(argv) == 0
    first = json.loads(man.read_text(encoding="utf-8"))
    assert first["status"] == "completed" and first["policy"]["time_chunk_steps"] == 4
    assert "host" not in first and first["output"]["name"] == "s.hdf"
    assert engine.main([str(src), str(out), "--manifest", str(man)]) == 2
    failed = json.loads(man.read_text(encoding="utf-8"))
    assert failed["reason_code"] == "HDF_SLIM_OUTPUT_EXISTS" and failed["status"] == "failed"
    assert "error: HDF_SLIM_OUTPUT_EXISTS" in capsys.readouterr().err


def test_cli_failure_exit_one(tmp_path):
    src, man = tmp_path / "p.hdf", tmp_path / "m.json"
    _make(src, face_flow=False, face_velocity=False)
    assert engine.main([str(src), str(tmp_path / "s.hdf"), "--manifest", str(man)]) == 1
    assert json.loads(man.read_text(encoding="utf-8"))["reason_code"] == "HDF_SLIM_REQUIRED_DATASET_MISSING"


def test_cli_policy_json_round_trip(src, tmp_path):
    first = HdfSlim.slim(src, tmp_path / "a.hdf", extra_series=["Face Cumulative Volume"])
    pol = tmp_path / "policy.json"
    pol.write_text(json.dumps(first["policy"]), encoding="utf-8")
    man = tmp_path / "b.json"
    assert engine.main([str(src), str(tmp_path / "b.hdf"), "--manifest", str(man),
                        "--policy-json", str(pol)]) == 0
    assert json.loads(man.read_text(encoding="utf-8"))["policy"] == first["policy"]
    assert engine.main([str(src), str(tmp_path / "c.hdf"), "--manifest", str(man), "--policy-json",
                        str(pol), "--extra-series", "Cell Courant"]) == 2


def test_cli_refuses_manifest_alias(src, tmp_path):
    before = sha256_file(src)
    assert engine.main([str(src), str(tmp_path / "s.hdf"), "--manifest", str(src)]) == 2
    assert sha256_file(src) == before


def test_cli_dry_run(src, tmp_path, capsys):
    assert engine.main([str(src), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == "ras-commander-hdf-slim-plan/v1"
    assert not list(tmp_path.glob("*.partial"))


def test_api_refuses_manifest_alias(src, tmp_path):
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf", manifest_path=src)
    assert e.value.reason_code == "HDF_SLIM_INPUT_INVALID"


def test_api_checks_manifest_folder_before_slimming(src, tmp_path):
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.slim(src, tmp_path / "s.hdf", manifest_path=tmp_path / "missing" / "m.json")
    assert e.value.reason_code == "HDF_SLIM_INPUT_INVALID"
    assert not list(tmp_path.glob("s.hdf*"))


def test_missing_source_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        HdfSlim.slim(tmp_path / "nope.hdf", tmp_path / "s.hdf")


def test_verify_reports_bad_inputs(src, tmp_path):
    out = tmp_path / "s.hdf"
    m = HdfSlim.slim(src, out)
    with pytest.raises(HdfSlimError) as e:
        HdfSlim.verify(src, tmp_path / "missing.hdf", m)
    assert e.value.reason_code == "HDF_SLIM_INPUT_INVALID"
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(HdfSlimError):
        HdfSlim.verify(src, out, tmp_path / "bad.json")
    result = HdfSlim.verify(src, out, dict(m, dropped=[{"no": "path"}]))
    assert not result["passed"] and "manifest dropped list is malformed" in result["problems"]
    junk = tmp_path / "junk.hdf"
    junk.write_bytes(b"not hdf")
    result = HdfSlim.verify(src, junk, m)
    assert not result["passed"] and any("not readable as HDF5" in p for p in result["problems"])


def test_variable_length_strings_verify_by_value(src, tmp_path):
    with h5py.File(src, "r+") as h:
        h.create_dataset("Plan Data/Notes", data=np.array(["alpha", "beta"], dtype=object),
                         dtype=h5py.string_dtype())
    m = HdfSlim.slim(src, tmp_path / "s.hdf")
    assert m["verification"]["problem_count"] == 0


def test_engine_is_self_contained_and_lf():
    text = HdfSlim.engine_path().read_bytes()
    assert b"\r\n" not in text
    imports = [ln for ln in text.decode().splitlines() if ln.startswith(("import ", "from "))]
    assert all("ras_commander" not in ln and not ln.startswith("from .") for ln in imports)
    assert b"@" not in text.replace(b"@dataclass", b"").replace(b"@property", b"").replace(
        b"@classmethod", b"")  # job templates reject leftover @TOKEN@ markers


# ---- real HEC-RAS result ----------------------------------------------------------------


def _real_2d_result():
    root = os.environ.get("RAS_COMMANDER_SLIM_REAL_HDF")
    return root if root and os.path.isfile(root) else None


@pytest.mark.skipif(_real_2d_result() is None, reason="RAS_COMMANDER_SLIM_REAL_HDF not set")
def test_real_example_round_trip(tmp_path):
    src = _real_2d_result()
    m = HdfSlim.slim(src, tmp_path / "s.hdf", manifest_path=tmp_path / "s.json")
    assert m["verification"]["problem_count"] == 0 and m["size_ratio"] < 1
    assert HdfSlim.verify(src, tmp_path / "s.hdf", m, check_source_sha256=False)["passed"]
