"""H4 text, compound field-dimension and malformed-encoding boundaries on synthetic h5py files.

h5py is the oracle. For every case ``fast_hdf.read_typed`` / ``read_attr`` is run in
python (``RAS_COMMANDER_FAST_HDF=0``), auto and required mode:

- valid fixed-length text (NULLTERM with bytes after the terminator, NULLPAD with an
  embedded NUL, SPACEPAD with trailing spaces and NUL fill, UTF-8, a high byte in an
  ASCII-declared string, scalar and 2-D shapes, selections) is h5py-exact in every
  mode and served natively (``fixed_strings``) in auto and required mode;
- reserved string padding/charset flags never produce a value in any mode: python and
  auto raise h5py's own error, required raises ``FastHdfError`` (or h5py's own dtype
  error when h5py cannot even describe the dtype);
- variable-length text and text-only compounds stay on h5py in every mode
  (``h5py-metadata``); a corrupt global-heap reference (missing object, or an index
  above 65535 that a u16 narrowing would alias to object 1) raises h5py's error in
  every mode, never a native empty/aliased string;
- numeric compounds with array (field-dimension) members, outside or inside a typed
  stored family, are h5py-exact in auto (fallback) and refused in required mode;
  a stored-family compound with a big-endian member is served natively and exactly;
- compound, array-member and vlen attributes are h5py-exact in auto and refused in
  required mode; a corrupt vlen attribute raises in every mode.

The last test exercises the engine's generic dataset string decoder directly
(``classification_catalogue`` legacy ``Names``): it requires the engine change that
proves text encoding before decoding and is a strict xfail on engine 3c2d479.
"""
import struct

import h5py
import numpy as np
import pytest
from h5py import h5d, h5s, h5t

UNPATCHED_ENGINES = {"3c2d4799ffdad01452682b82ca64305279ecc679"}
try:
    import ras_commander_fast_hdf as _engine
    _ENGINE_COMMIT = getattr(_engine, "ENGINE_COMMIT", None)
except ImportError:
    _ENGINE_COMMIT = None
MODES = ("0", "auto", "required")


@pytest.fixture
def native():
    module = pytest.importorskip("ras_commander_fast_hdf")
    assert module.API_VERSION == 11
    return module


def _fixed(width, pad, cset=h5t.CSET_ASCII):
    tid = h5t.C_S1.copy()
    tid.set_size(width)
    tid.set_strpad(pad)
    tid.set_cset(cset)
    return tid


def _put(f, name, tid, data):
    data = np.require(data, requirements="C")
    space = h5s.create_simple(data.shape) if data.shape else h5s.create(h5s.SCALAR)
    h5d.create(f.id, name.encode(), tid, space).write(h5s.ALL, h5s.ALL, data, mtype=tid)


def _patch_string_flags(path, width, flags):
    """Rewrite the flag byte of the one version-1 class-3 datatype of ``width`` bytes."""
    data = bytearray(path.read_bytes())
    hits = [i for i in range(len(data) - 8) if data[i] == 0x13 and data[i + 2:i + 4] == b"\0\0"
            and data[i + 4:i + 8] == struct.pack("<I", width)]
    assert len(hits) == 1, hits
    data[hits[0] + 1] = flags
    path.write_bytes(bytes(data))


def _patch_vlen_index(path, old, new):
    """Rewrite every vlen reference to global-heap object ``old`` (any collection) to ``new``."""
    data = bytearray(path.read_bytes())
    collections = [i for i in range(len(data) - 4) if data[i:i + 4] == b"GCOL"]
    assert collections
    patched = 0
    for gcol in collections:
        ref = struct.pack("<Q", gcol) + struct.pack("<I", old)
        at = data.find(ref)
        while at >= 0:
            data[at + 8:at + 12] = struct.pack("<I", new)
            patched += 1
            at = data.find(ref, at + 1)
    assert patched
    path.write_bytes(bytes(data))


def _same(actual, expected):
    assert type(actual) is type(expected), (type(actual), type(expected))
    if isinstance(expected, (str, bytes)):
        assert actual == expected
        return
    a, e = np.asarray(actual), np.asarray(expected)
    assert a.dtype == e.dtype and a.dtype.str == e.dtype.str and a.shape == e.shape
    if a.dtype.kind == "O":
        assert a.tolist() == e.tolist()
    else:
        assert a.tobytes() == e.tobytes()


def _modes(monkeypatch):
    from ras_commander import fast_hdf
    for mode in MODES:
        monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", mode)
        fast_hdf.close_sessions()
        yield mode


TEXT = {
    "nullterm": (11, h5t.STR_NULLTERM, h5t.CSET_ASCII, np.array([b"ab\0zz", b"abcdefghijk", b""], "S11")),
    "nullpad 2d": (7, h5t.STR_NULLPAD, h5t.CSET_ASCII, np.array([[b"a\0b", b"x"], [b"", b"abcdefg"]], "S7")),
    "spacepad": (9, h5t.STR_SPACEPAD, h5t.CSET_ASCII, np.array([b"ab   ", b"\0\0", b"a b"], "S9")),
    "utf8": (8, h5t.STR_NULLPAD, h5t.CSET_UTF8, np.array(["hé".encode(), b"z"], "S8")),
    "ascii high byte": (6, h5t.STR_NULLPAD, h5t.CSET_ASCII, np.array([b"\xe9t\xe9", b"ok"], "S6")),
    "scalar": (5, h5t.STR_NULLTERM, h5t.CSET_ASCII, np.array(b"abc", "S5")),
}


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "text.h5"
    with h5py.File(path, "w", libver="earliest") as f:
        for name, (width, pad, cset, data) in TEXT.items():
            _put(f, name, _fixed(width, pad, cset), data)
    return path


@pytest.mark.parametrize("name", list(TEXT))
def test_fixed_text_exact_in_every_mode(name, native, text_file, monkeypatch):
    from ras_commander import fast_hdf
    with h5py.File(text_file, "r") as f:
        ds = f[name]
        selections = [None] if ds.shape == () else [None, np.s_[1:], np.s_[0], np.s_[::2]]
        for mode in _modes(monkeypatch):
            for sel in selections:
                expected = ds[() if sel is None else sel]
                with fast_hdf.trace_reads() as trace:
                    actual = fast_hdf.read_typed(ds, sel)
                _same(actual, expected)
                backends = {(r["backend"], r.get("route")) for r in trace}
                assert backends == ({("h5py", None)} if mode == "0" else {("native-typed", "fixed_strings")}), (
                    mode, sel, trace)


@pytest.fixture
def reserved_file(tmp_path):
    path = tmp_path / "reserved.h5"
    with h5py.File(path, "w", libver="earliest") as f:
        f.create_dataset("reserved padding", data=np.array([b"abc"], "S13"))
        f.create_dataset("reserved charset", data=np.array([b"abc"], "S17"))
    _patch_string_flags(path, 13, 0x03)  # padding 3 is reserved
    _patch_string_flags(path, 17, 0x20)  # charset 2 is reserved
    return path


def test_reserved_string_flags_never_produce_a_value(native, reserved_file, monkeypatch):
    from ras_commander import fast_hdf
    with h5py.File(reserved_file, "r") as f:
        with pytest.raises(OSError) as h5py_error:
            f["reserved padding"][()]
        with pytest.raises(TypeError):
            f["reserved charset"].dtype
        for mode in _modes(monkeypatch):
            expected = fast_hdf.FastHdfError if mode == "required" else OSError
            with pytest.raises(expected) as error:
                fast_hdf.read_typed(f["reserved padding"])
            if mode != "required":
                assert str(error.value) == str(h5py_error.value)
            # h5py cannot describe the dtype; the engine is never reached and no mode succeeds.
            with pytest.raises(TypeError):
                fast_hdf.read_typed(f["reserved charset"])
    assert native.raw_fixed_strings(str(reserved_file), "reserved padding", 1 << 20)["capability"]["code"] == "encoding"
    assert native.raw_fixed_strings(str(reserved_file), "reserved charset", 1 << 20)["capability"]["code"] == "encoding"


def _vlen_file(path, corrupt=None):
    with h5py.File(path, "w", libver="earliest") as f:
        f.create_dataset("vlen", data=np.array([b"one", b"two"], dtype=object), dtype=h5py.string_dtype("ascii"))
    if corrupt is not None:
        _patch_vlen_index(path, 2, corrupt)
    return path


@pytest.mark.parametrize("corrupt", [None, 9, 0x10001], ids=["valid", "missing object", "index 65537"])
def test_vlen_text_stays_on_h5py_and_corrupt_heap_raises_everywhere(corrupt, native, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    path = _vlen_file(tmp_path / "vlen.h5", corrupt)
    with h5py.File(path, "r") as f:
        ds = f["vlen"]
        if corrupt is None:
            expected = ds[()]
        else:
            with pytest.raises(OSError) as h5py_error:
                ds[()]
        for mode in _modes(monkeypatch):
            with fast_hdf.trace_reads() as trace:
                if corrupt is None:
                    _same(fast_hdf.read_typed(ds), expected)
                else:
                    with pytest.raises(OSError) as error:
                        fast_hdf.read_typed(ds)
                    assert str(error.value) == str(h5py_error.value)
            assert {r["backend"] for r in trace} == ({"h5py"} if mode == "0" else {"h5py-metadata"}), (mode, trace)


COMPOUNDS = {
    "text only": ([("x", "S2"), ("y", "S4")], [(b"a", b"bb")], "metadata"),
    "text array field": ([("s", "S4", (2,))], [((b"a", b"b"),)], "metadata"),
    "mixed": ([("n", "S4"), ("i", "<i4"), ("f", "<f4")], [(b"a", 7, 1.5)], "value"),
    "array fields": ([("s", "S4", (2,)), ("v", "<f4", (3,))], [((b"a", b"b"), [1, 2, 3])], "value"),
    "2d field": ([("m", "<i2", (2, 2))], [([[1, 2], [3, 4]],)], "value"),
}


@pytest.mark.parametrize("name", list(COMPOUNDS))
def test_untyped_compounds_with_field_dimensions(name, native, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    dtype, rows, kind = COMPOUNDS[name]
    path = tmp_path / "compound.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("table", data=np.array(rows, dtype=dtype))
    with h5py.File(path, "r") as f:
        ds = f["table"]
        expected = ds[()]
        for mode in _modes(monkeypatch):
            if kind == "value" and mode == "required":
                with pytest.raises(fast_hdf.FastHdfError, match="numeric compound has no typed engine route"):
                    fast_hdf.read_typed(ds)
                continue
            with fast_hdf.trace_reads() as trace:
                _same(fast_hdf.read_typed(ds), expected)
            backend = {"0": "h5py"}.get(mode, "h5py-metadata" if kind == "metadata" else "h5py-fallback")
            assert {r["backend"] for r in trace} == {backend}, (mode, trace)


def test_stored_family_compound_members(native, tmp_path, monkeypatch):
    """Big-endian member: native and exact. Array member in a stored family: no native value."""
    from ras_commander import fast_hdf
    path = tmp_path / "stored.h5"
    with h5py.File(path, "w") as f:
        f.create_dataset("Event Conditions/Meteorology/Attributes",
                         data=np.array([(b"m", 2.25)], dtype=[("Name", "S16"), ("Value", ">f8")]))
        f.create_dataset("Geometry/Infiltration/Base Overrides",
                         data=np.array([(b"x", [0.5, 1.5], 1)],
                                       dtype=[("Name", "S16"), ("Value", "<f4", (2,)), ("Count", "<i4")]))
    rows = {r["path"]: r for r in native.stored_family_index(str(path))["datasets"]}
    assert rows["Geometry/Infiltration/Base Overrides"]["status"] == "unsupported"
    with h5py.File(path, "r") as f:
        met, arr = f["Event Conditions/Meteorology/Attributes"], f["Geometry/Infiltration/Base Overrides"]
        for mode in _modes(monkeypatch):
            with fast_hdf.trace_reads() as trace:
                _same(fast_hdf.read_typed(met), met[()])
            assert {r["backend"] for r in trace} == ({"h5py"} if mode == "0" else {"native-typed"})
            if mode == "required":
                with pytest.raises(fast_hdf.FastHdfError):
                    fast_hdf.read_typed(arr)
            else:
                _same(fast_hdf.read_typed(arr), arr[()])


@pytest.mark.parametrize("attr", ["compound", "array member", "vlen"])
def test_untyped_attributes_exact_in_auto_and_refused_in_required(attr, native, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    path = tmp_path / "attrs.h5"
    with h5py.File(path, "w") as f:
        g = f.create_group("g")
        g.attrs.create("compound", np.array([(b"a", 3)], dtype=[("n", "S3"), ("i", "<i2")]))
        g.attrs.create("array member", np.array([([1, 2],)], dtype=[("a", "<i4", (2,))]))
        g.attrs.create("vlen", "v", dtype=h5py.string_dtype())
    with h5py.File(path, "r") as f:
        g = f["g"]
        expected = g.attrs[attr]
        for mode in _modes(monkeypatch):
            if mode == "required":
                with pytest.raises(fast_hdf.FastHdfError, match=attr):
                    fast_hdf.read_attr(g, attr)
            else:
                _same(fast_hdf.read_attr(g, attr), expected)


def test_corrupt_vlen_attribute_raises_in_every_mode(native, tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    path = tmp_path / "vlen-attr.h5"
    with h5py.File(path, "w") as f:
        f.create_group("g").attrs.create("vlen", "value", dtype=h5py.string_dtype())
    _patch_vlen_index(path, 1, 9)
    with h5py.File(path, "r") as f:
        g = f["g"]
        with pytest.raises(OSError):
            g.attrs["vlen"]
        for mode in _modes(monkeypatch):
            with pytest.raises(fast_hdf.FastHdfError if mode == "required" else OSError):
                fast_hdf.read_attr(g, "vlen")


def _legacy_landcover(path, names):
    with h5py.File(path, "w", libver="earliest") as f:
        f.create_dataset("IDs", data=np.array([1, 2, 3], dtype="<i4"))
        f.create_dataset("ManningsN", data=np.array([0.03, 0.05, 0.08], dtype="<f4"))
        names(f)


@pytest.mark.xfail(_ENGINE_COMMIT in UNPATCHED_ENGINES, strict=True,
                   reason="engine 3c2d479 decodes unproven text in read_strings (H4 engine patch pending)")
@pytest.mark.parametrize("case", ["missing object", "index 65537", "reserved padding", "reserved charset", "valid vlen"])
def test_engine_generic_string_decoder_refuses_unproven_text(case, native, tmp_path):
    """Engine-level: legacy land-cover ``Names`` are decoded by the generic dataset string reader."""
    path = tmp_path / "lc.h5"
    if case in ("missing object", "index 65537", "valid vlen"):
        _legacy_landcover(path, lambda f: f.create_dataset(
            "Names", data=np.array([b"Grass", b"Forest", b"Urban"], dtype=object), dtype=h5py.string_dtype("ascii")))
        if case != "valid vlen":
            _patch_vlen_index(path, 2, 9 if case == "missing object" else 0x10001)
    else:
        _legacy_landcover(path, lambda f: _put(f, "Names", _fixed(13, h5t.STR_NULLTERM),
                                               np.array([b"Grass", b"Forest", b"Urban"], "S13")))
        _patch_string_flags(path, 13, 0x03 if case == "reserved padding" else 0x20)
    try:
        report = native.classification_catalogue(str(path), "land_cover", 1 << 20)
    except native.UnsupportedError:
        return
    assert report.get("value") is None, report
