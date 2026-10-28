"""Columnar PMTiles properties: capability detection, forms and byte identity.

ras-commander-fast-hdf engines with columnar ``write_pmtiles`` properties take
NumPy arrays, ``(values, valid)`` pairs and ``{"codes", "categories"}`` dicts
without a Python object per value. Older engines take only lists. Every form
must give the same archive bytes as the list form, on either engine.
"""
import numpy as np
import pytest

from ras_commander import fast_hdf


@pytest.fixture
def native():
    return pytest.importorskip("ras_commander_fast_hdf")


@pytest.fixture
def columnar(native):
    if not fast_hdf._supports_columnar_properties(native):
        pytest.skip("installed ras-commander-fast-hdf has no columnar PMTiles properties")
    return native


@pytest.fixture
def list_only(monkeypatch):
    """Force the list fallback, as on an engine without columnar properties."""
    monkeypatch.setattr(fast_hdf, "_supports_columnar_properties", lambda module: False)


def squares(count, size=0.01):
    """Packed, closed unit squares in EPSG:4326 along a row."""
    coords, offsets = [], [0]
    for index in range(count):
        x = -77.0 + index * size * 1.5
        ring = [(x, 40.0), (x + size, 40.0), (x + size, 40.0 + size), (x, 40.0 + size), (x, 40.0)]
        coords.extend(ring)
        offsets.append(len(coords))
    return np.asarray(coords, dtype=np.float64), np.asarray(offsets, dtype=np.int64)


def write(path, properties, count):
    coords, offsets = squares(count)
    layer = {"coordinates": coords, "offsets": offsets,
             "cell_ids": np.arange(count, dtype=np.int64), "properties": properties}
    fast_hdf.export_pmtiles(path, {"cells": layer}, min_zoom=0, max_zoom=12, backend="rust", threads=1)
    return path.read_bytes()


def typed_and_list_columns():
    count = 7
    f8 = np.array([1.5, np.nan, -2.25, np.inf, 0.0, 3.0, 1e-300])
    f4 = np.array([0.1, 0.2, np.nan, 4.5, -1.0, 7.25, 3.3], dtype=np.float32)
    i1 = np.array([-3, 0, 5, 127, -128, 1, 2], dtype=np.int8)
    u4 = np.array([0, 1, 2, 2**32 - 1, 7, 8, 9], dtype=np.uint32)
    i8_be = np.array([2**53 + 1, -(2**62), 0, 1, 2, 3, 4], dtype=">i8")
    flags = np.array([True, False, True, True, False, False, True])
    names = np.array(["b", "a", "b", "", "c", "a", "b"])
    valid = np.array([True, False, True, True, False, True, True])
    codes = np.array([1, -1, 0, 0, 2, 1, -1], dtype=np.int64)
    categories = ["Upper 2D Area", "BaldEagleCr", "x"]
    typed = {"f8": f8, "f4": f4, "i1": i1, "u4": u4, "i8_be": i8_be, "flags": flags, "names": names,
             "masked": (f8, valid), "category": {"codes": codes, "categories": categories},
             "listed": [1, "a", None, 2.5, True, float("nan"), -4]}
    lists = {"f8": fast_hdf._property_values(f8, count, "f8"),
             "f4": fast_hdf._property_values(f4, count, "f4"),
             "i1": i1.tolist(), "u4": u4.tolist(), "i8_be": i8_be.tolist(),
             "flags": flags.tolist(), "names": names.tolist(),
             "masked": [v if ok else None for v, ok in zip(fast_hdf._property_values(f8, count, "m"), valid)],
             "category": [None if c < 0 else categories[c] for c in codes],
             "listed": [1, "a", None, 2.5, True, None, -4]}
    return count, typed, lists


def test_capability_probe_detects_engine_and_writes_nothing(columnar, tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    fast_hdf._COLUMNAR_SUPPORT.clear()
    assert fast_hdf._supports_columnar_properties(columnar) is True
    assert list(tmp_path.iterdir()) == []


def test_capability_probe_rejects_list_only_engine():
    class ListOnly:
        @staticmethod
        def write_pmtiles(layers, output, min_zoom, max_zoom, threads=None):
            for layer in layers:
                for values in layer["properties"].values():
                    if not isinstance(values, list):
                        raise TypeError("'ndarray' object cannot be converted to 'PyList'")
            raise ValueError("at least one nonempty layer is required")

    class Missing:
        pass

    assert fast_hdf._supports_columnar_properties(ListOnly) is False
    assert fast_hdf._supports_columnar_properties(Missing) is False


def test_columnar_forms_are_byte_identical_to_lists(columnar, tmp_path):
    count, typed, lists = typed_and_list_columns()
    reference = write(tmp_path / "lists.pmtiles", lists, count)
    assert write(tmp_path / "columnar.pmtiles", typed, count) == reference


def test_list_fallback_is_byte_identical(columnar, tmp_path, monkeypatch):
    count, typed, lists = typed_and_list_columns()
    reference = write(tmp_path / "lists.pmtiles", lists, count)
    monkeypatch.setattr(fast_hdf, "_supports_columnar_properties", lambda module: False)
    assert write(tmp_path / "fallback.pmtiles", typed, count) == reference


def test_engine_receives_arrays_not_lists(columnar, tmp_path, monkeypatch):
    count, typed, _ = typed_and_list_columns()
    seen = {}
    original = columnar.write_pmtiles

    def record(layers, *args, **kwargs):
        seen.update(layers[0]["properties"])
        return original(layers, *args, **kwargs)

    fast_hdf._supports_columnar_properties(columnar)  # cache the probe for the real binding
    fast_hdf._COLUMNAR_SUPPORT[record] = True
    monkeypatch.setattr(columnar, "write_pmtiles", record)
    write(tmp_path / "recorded.pmtiles", typed, count)
    assert seen["i1"].dtype == np.int32 and seen["f4"].dtype == np.float32
    assert seen["i8_be"].dtype == np.dtype("<i8") and seen["i8_be"].flags.c_contiguous
    assert set(seen["names"]) == {"codes", "categories"}
    assert isinstance(seen["masked"], tuple) and seen["masked"][1].dtype == np.bool_
    assert isinstance(seen["listed"], list)
    fast_hdf._COLUMNAR_SUPPORT.pop(record, None)


@pytest.mark.parametrize("value, message", [
    ((np.zeros(3),), "pair"),
    ((np.zeros(3, dtype=object), np.ones(3, dtype=bool)), "typed"),
    ((np.zeros(3), np.ones(3, dtype=np.int8)), "bool array"),
    ((np.zeros(3), np.ones(2, dtype=bool)), "bool array"),
    ((np.zeros(2), np.ones(2, dtype=bool)), "one value per feature"),
    ({"codes": np.array([0, 1, 3]), "categories": ["a", "b"]}, "out of range"),
    ({"codes": np.array([0, -2, 1]), "categories": ["a", "b"]}, "out of range"),
    ({"codes": np.array([0.0, 1.0, 1.0]), "categories": ["a", "b"]}, "integer"),
    ({"codes": np.array([0, 1, 1])}, "exactly"),
    (np.zeros(2), "one value per feature"),
])
@pytest.mark.parametrize("engine", ["columnar", "list"])
def test_invalid_columns_refused_on_both_paths(native, tmp_path, monkeypatch, value, message, engine):
    if engine == "list":
        monkeypatch.setattr(fast_hdf, "_supports_columnar_properties", lambda module: False)
    elif not fast_hdf._supports_columnar_properties(native):
        pytest.skip("installed engine has no columnar properties")
    with pytest.raises((ValueError, TypeError), match=message):
        write(tmp_path / "bad.pmtiles", {"bad": value}, 3)
    assert not (tmp_path / "bad.pmtiles").exists()


def test_mesh_property_column_forms():
    a = np.array([1.0, 2.0], dtype=np.float32)
    b = np.array([3.0], dtype=np.float32)
    whole = fast_hdf._mesh_property_column([a, b], [2, 1], "x")
    assert isinstance(whole, np.ndarray) and whole.dtype == np.float32
    values, valid = fast_hdf._mesh_property_column([a, None], [2, 3], "x")
    assert values.dtype == np.float32 and valid.tolist() == [True, True, False, False, False]
    # Different dtypes across meshes keep each value's own scalar type.
    mixed = fast_hdf._mesh_property_column([np.array([1, 2]), np.array([0.5])], [2, 1], "x")
    assert mixed == [1, 2, 0.5] and type(mixed[0]) is int
    objects = fast_hdf._mesh_property_column([np.array([1, "a"], dtype=object), None], [2, 1], "x")
    assert objects == [1, "a", None]


def _fake_meshes(monkeypatch):
    coords_a, offsets_a = squares(4)
    coords_b, offsets_b = squares(3)
    coords_b = coords_b + [0.0, 0.05]
    meshes = {"Upper 2D Area": {"coordinates": coords_a, "offsets": offsets_a,
                                "cell_ids": np.array([0, 2, 3, 5], dtype=np.int64)},
              "BaldEagleCr": {"coordinates": coords_b, "offsets": offsets_b,
                              "cell_ids": np.array([1, 0, 4], dtype=np.int64)},
              "Empty": {"coordinates": np.zeros((0, 2)), "offsets": np.zeros(1, dtype=np.int64),
                        "cell_ids": np.zeros(0, dtype=np.int64)}}
    monkeypatch.setattr(fast_hdf, "packed_meshes", lambda *args, **kwargs: meshes)
    return meshes


def _reference_mesh_layer(meshes, properties):
    """The list-form layer exactly as export_mesh_pmtiles built it before columns."""
    names = list(dict.fromkeys(key for columns in properties.values() for key in columns))
    columns = {key: [] for key in ["mesh_name", "cell_id", *names]}
    coordinates, offsets, cursor = [], [0], 0
    for name, packed in meshes.items():
        ids = np.asarray(packed["cell_ids"])
        if not len(ids):
            continue
        coordinates.append(packed["coordinates"])
        offsets.extend((np.asarray(packed["offsets"])[1:] + cursor).tolist())
        cursor += len(packed["coordinates"])
        columns["mesh_name"].extend([name] * len(ids))
        columns["cell_id"].extend(ids.tolist())
        for key in names:
            if key not in properties.get(name, {}):
                columns[key].extend([None] * len(ids))
                continue
            values = np.asarray(properties[name][key], dtype=object)
            columns[key].extend(fast_hdf._property_values(values[ids], len(ids), key))
    count = len(columns["cell_id"])
    return {"coordinates": np.concatenate(coordinates), "offsets": np.asarray(offsets, dtype=np.int64),
            "cell_ids": np.arange(count, dtype=np.int64), "properties": columns}


@pytest.mark.parametrize("engine", ["columnar", "list"])
def test_export_mesh_pmtiles_byte_identical_to_list_layer(native, tmp_path, monkeypatch, engine):
    if engine == "columnar" and not fast_hdf._supports_columnar_properties(native):
        pytest.skip("installed engine has no columnar properties")
    meshes = _fake_meshes(monkeypatch)
    source = tmp_path / "source.hdf"
    source.write_bytes(b"")
    properties = {
        # Ghost rows beyond the constructed cells, NaN, a column one mesh lacks,
        # a column whose dtype differs between meshes and an object column.
        "Upper 2D Area": {"depth": np.array([0.5, 9.0, np.nan, 1.25, 7.0, 2.0, 99.0], dtype=np.float32),
                          "wet": np.array([True, False, True, True, False, True]),
                          "mixed": np.array([1, 2, 3, 4, 5, 6]),
                          "note": ["a", 1, None, 2.5, "b", "c"]},
        "BaldEagleCr": {"depth": np.array([3.5, 4.5, 0.0, 0.0, -1.0], dtype=np.float32),
                        "mixed": np.array([0.5, 1.5, 2.5, 3.5, 4.5])},
    }
    reference = tmp_path / "reference.pmtiles"
    fast_hdf.export_pmtiles(reference, {"mesh_cells": _reference_mesh_layer(meshes, properties)},
                            source_crs="EPSG:4326", min_zoom=0, max_zoom=12, backend="rust", threads=1)
    if engine == "list":
        monkeypatch.setattr(fast_hdf, "_supports_columnar_properties", lambda module: False)
    output = tmp_path / "mesh.pmtiles"
    fast_hdf.export_mesh_pmtiles(source, output, properties=properties, source_crs="EPSG:4326",
                                 min_zoom=0, max_zoom=12, backend="rust", threads=1)
    assert output.read_bytes() == reference.read_bytes()
