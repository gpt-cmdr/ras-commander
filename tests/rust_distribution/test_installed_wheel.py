"""Clean-install qualification of a locally built ras-commander-fast-hdf wheel.

Run from a directory outside the source checkout, in an environment where
ras-commander and the wheel were installed non-editably:

* ``RAS_DIST_RECEIPT``: build-receipt.json written by build_wheel.py.
* ``RAS_DIST_FIXTURES``: directory with local copies of computed HEC-RAS HDF
  fixtures (optional; real-fixture tests are skipped as unavailable without it).

Native tests run with ``backend="rust"``, count calls into the extension and
compare against independent h5py/NumPy and Python-backend oracles.
"""

import hashlib
import functools
import importlib.metadata as metadata
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

RECEIPT_PATH = os.environ.get("RAS_DIST_RECEIPT")
FIXTURES = Path(os.environ["RAS_DIST_FIXTURES"]) if os.environ.get("RAS_DIST_FIXTURES") else None
pytestmark = pytest.mark.skipif(not RECEIPT_PATH, reason="RAS_DIST_RECEIPT not provided")

# Stored "File Version" prefix, polygon count, SHA256 of the immutable copy.
CASES = {
    "JUL2020_D100RAS.p04.hdf": ("HEC-RAS 5.0.7", 340246,
                                "37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683"),
    "BaldEagleDamBrk.p07.hdf": ("HEC-RAS 6.6", 87039,
                                "07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984"),
    "BaldEagleDamBrk.p18.hdf": ("HEC-RAS 7.0", 4425,
                                "1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b"),
}


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def receipt():
    return json.loads(Path(RECEIPT_PATH).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def native():
    import ras_commander_fast_hdf
    return ras_commander_fast_hdf


@pytest.fixture
def counted(native, monkeypatch):
    """Count every call into the extension's callable entry points."""
    counts = {}
    for name in dir(native):
        value = getattr(native, name)
        if name.startswith("_") or isinstance(value, type) or not callable(value):
            continue

        @functools.wraps(value)
        def wrapper(*args, __name=name, __value=value, **kwargs):
            counts[__name] = counts.get(__name, 0) + 1
            return __value(*args, **kwargs)
        monkeypatch.setattr(native, name, wrapper)
    return counts


def _fixture(name):
    if FIXTURES is None:
        pytest.skip("RAS_DIST_FIXTURES not provided; real-fixture coverage unavailable")
    path = FIXTURES / name
    if not path.is_file():
        pytest.skip(f"fixture {name} unavailable")
    return path


def _source_root(receipt):
    return Path(receipt["source"]["root"]).resolve()


def test_import_locations_are_installed_not_source(receipt, native):
    import ras_commander
    source = _source_root(receipt)
    package = Path(ras_commander.__file__).resolve()
    module = Path(native.__file__).resolve()
    for path in (package, module):
        assert "site-packages" in path.parts, path
        assert source not in path.parents, f"{path} imported from source checkout"
        assert Path.cwd().resolve() not in path.parents
    assert Path(sys.prefix).resolve() in package.parents


def test_inner_binary_matches_built_wheel(receipt, native):
    assert native.API_VERSION == 1
    module_dir = Path(native.__file__).resolve().parent
    binaries = [p for p in module_dir.iterdir() if p.suffix in {".pyd", ".so", ".dylib"}]
    assert len(binaries) == 1, binaries
    assert binaries[0].name == Path(receipt["wheel"]["native_member"]).name
    assert _sha256(binaries[0]) == receipt["wheel"]["native_sha256"]
    inner = getattr(native, "ras_commander_fast_hdf", native)
    assert Path(inner.__file__).resolve() == binaries[0].resolve(), (
        "the hashed binary must be the loaded extension module")


def test_versions_and_abi(receipt):
    dist = metadata.distribution("ras-commander-fast-hdf")
    assert dist.version == "0.1.0"
    tags = [line.split(": ", 1)[1] for line in dist.read_text("WHEEL").splitlines()
            if line.startswith("Tag: ")]
    assert tags and all(tag.startswith("cp310-abi3-") for tag in tags), tags
    assert sys.version_info >= (3, 10)
    assert int(np.__version__.split(".")[0]) >= 1
    assert dist.read_text("direct_url.json") is None or "editable" not in dist.read_text("direct_url.json")
    rc = metadata.distribution("ras-commander")
    direct = json.loads(rc.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable", False)


def test_fast_hdf_available_and_required_mode(monkeypatch):
    from ras_commander import fast_hdf
    assert fast_hdf.available()
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    assert fast_hdf._native(fast_hdf._mode("auto")) is not None


@pytest.mark.parametrize("name", list(CASES))
def test_stored_version_and_numeric_reads(name, counted):
    import h5py
    from ras_commander import fast_hdf
    path = _fixture(name)
    version, _, sha = CASES[name]
    assert _sha256(path) == sha
    with h5py.File(path, "r") as hdf:
        stored = hdf.attrs["File Version"].decode()
        assert stored.startswith(version), stored
        names = []
        hdf.visititems(lambda key, obj: names.append(key) if isinstance(obj, h5py.Dataset)
                       and obj.dtype.kind in "iuf" and obj.dtype.fields is None
                       and 0 < obj.size <= 5_000_000 and "2D Flow Areas" in key else None)
        names = ["/" + key for key in names]
        names = sorted(names)[:40]  # deterministic, bounded selection
        assert names, "fixture has numeric 2D datasets"
        oracle = {key: hdf[key][()] for key in names}
    values = fast_hdf.read_datasets(path, names, backend="rust")
    assert counted.get("read_numeric_batch", 0) + counted.get("read_numeric", 0) >= 1
    for key in names:
        got = values[key]
        assert got.dtype == oracle[key].dtype and got.shape == oracle[key].shape, key
        assert np.array_equal(got, oracle[key], equal_nan=oracle[key].dtype.kind == "f"), key
    assert _sha256(path) == sha


@pytest.mark.parametrize("name", list(CASES))
def test_mesh_polygons_native_matches_python(name, counted):
    import shapely
    from ras_commander import fast_hdf
    path = _fixture(name)
    _, polygons, sha = CASES[name]
    rust = fast_hdf.mesh_polygons(path, backend="rust")
    assert counted.get("assemble_cells", 0) >= 1
    calls = dict(counted)
    python = fast_hdf.mesh_polygons(path, backend="python")
    assert dict(counted) == calls, "python backend must not call the extension"
    assert len(rust) == len(python) == polygons
    assert rust.crs == python.crs and rust.crs is not None
    key = ["mesh_name", "cell_id"]
    rust = rust.sort_values(key).reset_index(drop=True)
    python = python.sort_values(key).reset_index(drop=True)
    assert (rust[key].to_numpy() == python[key].to_numpy()).all()
    assert shapely.equals(rust.geometry.values, python.geometry.values).all()
    assert _sha256(path) == sha


def test_arrow_first_tier_and_pmtiles_smoke(tmp_path, counted):
    import geopandas as gpd
    import pyarrow as pa
    import shapely
    from ras_commander import fast_hdf
    path = _fixture("BaldEagleDamBrk.p18.hdf")
    mesh = fast_hdf.mesh_polygons(path, backend="rust")
    schema = pa.schema([
        pa.field("mesh_name", pa.string(), nullable=False),
        pa.field("cell_id", pa.int64(), nullable=False),
        pa.field("geometry", pa.binary(), nullable=False),
        pa.field("area", pa.float64()),
    ])
    table = pa.table({
        "mesh_name": pa.array(mesh["mesh_name"].astype(str), pa.string()),
        "cell_id": pa.array(mesh["cell_id"].astype("int64"), pa.int64()),
        "geometry": pa.array(shapely.to_wkb(mesh.geometry.values), pa.binary()),
        "area": pa.array(mesh.geometry.area.to_numpy(), pa.float64()),
    }, schema=schema)
    crs = mesh.crs.to_wkt()
    for fmt, suffix in (("parquet", ".parquet"), ("fgb", ".fgb"),
                        ("geojson", ".geojson"), ("gpkg", ".gpkg")):
        out = tmp_path / f"mesh{suffix}"
        fast_hdf.export_arrow(out, table, source_crs=crs, format=fmt)
        frame = gpd.read_parquet(out) if fmt == "parquet" else gpd.read_file(out)
        assert len(frame) == len(mesh), fmt
        assert sorted(frame["cell_id"].astype("int64")) == sorted(table["cell_id"].to_pylist()), fmt
        assert frame.crs is not None, fmt
    bundle = tmp_path / "bundle"
    fast_hdf.export_arrow_pmtiles(bundle, table, source_crs=crs, max_zoom=10)
    assert (bundle / "tiles.pmtiles").stat().st_size > 0
    with pa.ipc.open_file(bundle / "identities.arrow") as reader:
        assert reader.read_all().num_rows == len(mesh)
    assert counted, "exports must execute native writers"
