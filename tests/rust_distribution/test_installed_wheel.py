"""Release gate for an installed ras-commander-fast-hdf wheel.

Install the built wheel non-editably into the environment under test, then run
this module from a directory outside the source checkout:

* ``RAS_DIST_WHEEL`` (required): path to the built ``.whl`` that was installed
  (or a directory holding exactly one ``.whl``). Without it every test skips.
* ``RAS_DIST_FIXTURES`` (optional): ``os.pathsep``-separated list of computed
  HEC-RAS HDF files and/or directories containing them. Files named in
  ``CASES`` are hash-checked; real-fixture tests skip when none is found.

The gate pins bridge ``API_VERSION`` 11 and accepts the engine commits of
``tests/native_engine_provenance.py`` (set ``RAS_EXPECTED_ENGINE_COMMIT`` to
require one specific build);
checks that the extension is imported from site-packages and that its binary
is byte-identical to the one inside the wheel; checks the abi3 tag and the
licence files; and runs required-native reads and mesh polygons against
h5py/Python oracles, counting calls into the extension.
"""

import functools
import hashlib
import importlib.metadata as metadata
import json
import os
import sys
import sysconfig
import zipfile
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_engine_provenance import accepted_engine_commits  # noqa: E402

API_VERSION = 11
DIST = "ras-commander-fast-hdf"
LICENCE_HOLDER = "CLB Engineering Corporation"
SOURCE_ROOT = Path(__file__).resolve().parents[2]
BINARY_SUFFIXES = {".pyd", ".so", ".dylib"}

# Stored "File Version" prefix, polygon count, SHA256 of the immutable copy.
CASES = {
    "JUL2020_D100RAS.p04.hdf": ("HEC-RAS 5.0.7", 340246,
                                "37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683"),
    "BaldEagleDamBrk.p07.hdf": ("HEC-RAS 6.6", 87039,
                                "07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984"),
    "BaldEagleDamBrk.p18.hdf": ("HEC-RAS 7.0", 4425,
                                "1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b"),
}

WHEEL_ENV = os.environ.get("RAS_DIST_WHEEL")
pytestmark = pytest.mark.skipif(
    not WHEEL_ENV,
    reason="RAS_DIST_WHEEL not set: point it at the built ras-commander-fast-hdf .whl "
           "installed in this environment to run the release wheel gate")


def _sha256(path_or_bytes):
    digest = hashlib.sha256()
    if isinstance(path_or_bytes, bytes):
        digest.update(path_or_bytes)
        return digest.hexdigest()
    with open(path_or_bytes, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def _fixture_paths():
    found = {}
    for entry in filter(None, os.environ.get("RAS_DIST_FIXTURES", "").split(os.pathsep)):
        path = Path(entry)
        if path.is_dir():
            for name in CASES:
                if (path / name).is_file():
                    found.setdefault(name, path / name)
        elif path.is_file() and path.name in CASES:
            found.setdefault(path.name, path)
    return found


FIXTURES = _fixture_paths()


def _fixture(name):
    if not os.environ.get("RAS_DIST_FIXTURES"):
        pytest.skip("RAS_DIST_FIXTURES not set; real-fixture coverage unavailable")
    if name not in FIXTURES:
        pytest.skip(f"fixture {name} not found in RAS_DIST_FIXTURES")
    path = FIXTURES[name]
    assert _sha256(path) == CASES[name][2], f"{path} is not the pinned immutable copy"
    return path


@pytest.fixture(scope="module")
def wheel_path():
    path = Path(WHEEL_ENV)
    if path.is_dir():
        wheels = sorted(path.glob("*.whl"))
        assert len(wheels) == 1, f"RAS_DIST_WHEEL directory must hold exactly one wheel: {wheels}"
        path = wheels[0]
    assert path.is_file() and path.suffix == ".whl", f"RAS_DIST_WHEEL is not a wheel: {path}"
    return path


@pytest.fixture(scope="module")
def wheel(wheel_path):
    with zipfile.ZipFile(wheel_path) as archive:
        yield archive


@pytest.fixture(scope="module")
def dist():
    return metadata.distribution(DIST)


@pytest.fixture(scope="module")
def native():
    import ras_commander_fast_hdf
    return ras_commander_fast_hdf


@pytest.fixture
def adapter(monkeypatch):
    from ras_commander import fast_hdf
    monkeypatch.delenv("RAS_COMMANDER_FAST_HDF", raising=False)
    fast_hdf.close_sessions()
    fast_hdf._reset_native()
    yield fast_hdf
    fast_hdf.close_sessions()
    fast_hdf._reset_native()


def _installed_binary(native):
    module_dir = Path(native.__file__).resolve().parent
    binaries = [p for p in module_dir.iterdir() if p.suffix.lower() in BINARY_SUFFIXES]
    assert len(binaries) == 1, binaries
    return binaries[0]


def _wheel_member(wheel, suffix):
    members = [n for n in wheel.namelist() if n.endswith(suffix)]
    assert len(members) == 1, (suffix, members)
    return members[0]


@pytest.fixture
def counted(native, adapter, monkeypatch):
    """Count calls into module-level extension entry points and HdfSession methods."""
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

    session_type = native.HdfSession

    class CountingSession:
        """Delegating proxy; the adapter builds sessions via module.HdfSession."""

        def __init__(self, *args, **kwargs):
            self._inner = session_type(*args, **kwargs)

        def __getattr__(self, name):
            value = getattr(self._inner, name)
            if not callable(value):
                return value

            def call(*args, **kwargs):
                key = f"HdfSession.{name}"
                counts[key] = counts.get(key, 0) + 1
                return value(*args, **kwargs)
            return call

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

    monkeypatch.setattr(native, "HdfSession", CountingSession)
    return counts


@contextmanager
def _python_polygonize_forbidden():
    import shapely.ops
    original = shapely.ops.polygonize

    def forbidden(*args, **kwargs):
        raise AssertionError("required native mesh polygons fell back to Python polygonize")
    shapely.ops.polygonize = forbidden
    try:
        yield
    finally:
        shapely.ops.polygonize = original


# --------------------------------------------------------------------------
# Identity: pins, location, binary, tags, licences
# --------------------------------------------------------------------------

def test_api_version_and_engine_commit_pins(native, adapter):
    assert native.API_VERSION == API_VERSION
    assert native.ENGINE_COMMIT in accepted_engine_commits(), native.ENGINE_COMMIT
    assert adapter.available(), "ras_commander.fast_hdf must accept the installed extension"


def test_extension_imported_from_site_packages(native, dist):
    module = Path(native.__file__).resolve()
    inner = getattr(native, "ras_commander_fast_hdf", None)
    paths = [module] + ([Path(inner.__file__).resolve()] if getattr(inner, "__file__", None) else [])
    site_dirs = {Path(sysconfig.get_paths()[key]).resolve() for key in ("purelib", "platlib")}
    for path in paths:
        assert any(site in path.parents for site in site_dirs), (path, site_dirs)
        assert SOURCE_ROOT not in path.parents, f"{path} imported from the source checkout"
        assert Path.cwd().resolve() not in path.parents, f"{path} imported from the working directory"
    assert Path(sys.prefix).resolve() in module.parents
    installed = {Path(dist.locate_file(f)).resolve() for f in dist.files}
    assert module in installed, "extension module is not a file of the installed distribution"
    direct = json.loads(dist.read_text("direct_url.json") or "{}")
    assert not direct.get("dir_info", {}).get("editable", False), direct


def test_installed_binary_matches_wheel(native, wheel, wheel_path, dist):
    binary = _installed_binary(native)
    member = next(n for n in wheel.namelist() if Path(n).suffix.lower() in BINARY_SUFFIXES)
    assert [n for n in wheel.namelist() if Path(n).suffix.lower() in BINARY_SUFFIXES] == [member]
    assert binary.name == Path(member).name
    assert _sha256(binary) == _sha256(wheel.read(member)), (
        f"installed {binary} differs from {member} in {wheel_path.name}")
    inner = getattr(native, "ras_commander_fast_hdf", native)
    assert Path(inner.__file__).resolve() == binary.resolve(), (
        "the hashed binary must be the loaded extension module")
    # The installed distribution is this wheel's version.
    assert wheel_path.name.split("-")[1] == dist.version


def test_abi3_tag(wheel, wheel_path, dist):
    tags = [line.split(": ", 1)[1] for line in wheel.read(_wheel_member(wheel, ".dist-info/WHEEL"))
            .decode().splitlines() if line.startswith("Tag: ")]
    assert tags and all(tag.startswith("cp310-abi3-") for tag in tags), tags
    assert "-cp310-abi3-" in wheel_path.name
    installed = [line.split(": ", 1)[1] for line in dist.read_text("WHEEL").splitlines()
                 if line.startswith("Tag: ")]
    assert installed == tags
    assert sys.version_info >= (3, 10)


@pytest.mark.parametrize("name", ["THIRD-PARTY-NOTICES.md", "ras-commander-rust-LICENSE.txt",
                                  "ras-commander-LICENSE.txt"])
def test_licence_files_installed_and_match_wheel(wheel, dist, name):
    installed = [f for f in dist.files if ".dist-info/licenses/" in f.as_posix()
                 and f.name == name]
    assert len(installed) == 1, f"{name} missing from installed dist-info licenses"
    member = _wheel_member(wheel, "/" + installed[0].as_posix().split(".dist-info/", 1)[1])
    data = Path(dist.locate_file(installed[0])).read_bytes()
    assert data == wheel.read(member)
    if name == "ras-commander-rust-LICENSE.txt":
        text = data.decode("utf-8")
        assert text.startswith("MIT License") and f"Copyright (c) 2024 {LICENCE_HOLDER}" in text


def test_embedded_notices_name_engine_licence_holder(dist):
    """THIRD-PARTY-NOTICES must carry the engine's own licence text (CLB holder)."""
    import re
    notices = next(f for f in dist.files if f.name == "THIRD-PARTY-NOTICES.md"
                   and ".dist-info/licenses/" in f.as_posix())
    text = Path(dist.locate_file(notices)).read_text(encoding="utf-8")
    row = re.search(r"^\| ras-commander-rust \|.*\(#(licence-[0-9a-f]+)\)", text, re.M)
    assert row, "ras-commander-rust missing from the notices table"
    section = text.split(f"### {row.group(1)}", 1)[1].split("\n### ", 1)[0]
    assert f"Copyright (c) 2024 {LICENCE_HOLDER}" in section, (
        f"engine licence section {row.group(1)} does not name {LICENCE_HOLDER}; "
        "regenerate THIRD-PARTY-NOTICES.md and rebuild the wheel")


# --------------------------------------------------------------------------
# Behaviour: required mode, numeric reads, mesh polygons
# --------------------------------------------------------------------------

def test_required_mode_reads_natively(adapter, counted, monkeypatch, tmp_path):
    import h5py
    path = tmp_path / "numeric.hdf"
    expected = {"/a": np.arange(24, dtype="f8").reshape(4, 6),
                "/g/b": np.arange(10, dtype="i4"),
                "/g/c": np.linspace(0, 1, 37, dtype="f4").reshape(37, 1)}
    with h5py.File(path, "w") as hdf:
        for key, values in expected.items():
            hdf[key] = values
        hdf.create_dataset("/chunked", data=np.arange(5000, dtype="f8"), chunks=(512,),
                           compression="gzip")
    expected["/chunked"] = np.arange(5000, dtype="f8")
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    assert adapter.native_required()
    assert adapter._native(adapter._mode("auto")) is not None
    values = adapter.read_datasets(path, list(expected), backend="auto")
    assert counted.get("HdfSession.read_numeric_batch", 0) >= 1, counted
    for key, oracle in expected.items():
        assert values[key].dtype == oracle.dtype and values[key].shape == oracle.shape, key
        assert np.array_equal(values[key], oracle), key


@pytest.mark.parametrize("name", list(CASES))
def test_stored_version_and_numeric_reads(name, adapter, counted):
    import h5py
    path = _fixture(name)
    version, _, sha = CASES[name]
    with h5py.File(path, "r") as hdf:
        stored = hdf.attrs["File Version"].decode()
        assert stored.startswith(version), stored
        names = []
        hdf.visititems(lambda key, obj: names.append(key) if isinstance(obj, h5py.Dataset)
                       and obj.dtype.kind in "iuf" and obj.dtype.fields is None
                       and 0 < obj.size <= 5_000_000 and "2D Flow Areas" in key else None)
        names = sorted("/" + key for key in names)[:40]  # deterministic, bounded selection
        assert names, "fixture has numeric 2D datasets"
        oracle = {key: hdf[key][()] for key in names}
    values = adapter.read_datasets(path, names, backend="rust")
    assert counted.get("HdfSession.read_numeric_batch", 0) >= 1, counted
    for key in names:
        got = values[key]
        assert got.dtype == oracle[key].dtype and got.shape == oracle[key].shape, key
        assert np.array_equal(got, oracle[key], equal_nan=oracle[key].dtype.kind == "f"), key
    adapter.close_sessions()
    assert _sha256(path) == sha


def _canonical(frame):
    import shapely
    order = np.lexsort((frame.cell_id.to_numpy(), frame.mesh_name.to_numpy()))
    keys = list(zip(frame.mesh_name.to_numpy()[order].tolist(),
                    frame.cell_id.to_numpy()[order].astype("i8").tolist()))
    geometries = shapely.normalize(shapely.remove_repeated_points(frame.geometry.to_numpy()[order], 0))
    return keys, shapely.to_wkb(geometries)


@pytest.mark.parametrize("name", list(CASES))
def test_mesh_polygons_native_matches_python(name, adapter, counted):
    from ras_commander.hdf.HdfMesh import HdfMesh
    path = _fixture(name)
    _, polygons, sha = CASES[name]
    python = HdfMesh.get_mesh_cell_polygons(path, engine="h5py", strict=False, diagnostics=True)
    assert not counted, f"h5py engine must not call the extension: {counted}"
    with _python_polygonize_forbidden():
        rust = HdfMesh.get_mesh_cell_polygons(path, engine="native", strict=False, diagnostics=True)
    assert counted.get("assemble_cells", 0) >= 1, counted
    assert len(rust) == len(python) == polygons
    assert rust.crs == python.crs and rust.crs is not None
    rust_keys, rust_wkb = _canonical(rust)
    python_keys, python_wkb = _canonical(python)
    assert rust_keys == python_keys
    assert (rust_wkb == python_wkb).all()
    assert rust.attrs["cell_polygon_diagnostics"] == python.attrs["cell_polygon_diagnostics"]
    adapter.close_sessions()
    assert _sha256(path) == sha
