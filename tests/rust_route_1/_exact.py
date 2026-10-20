"""Exact, type-strict equality for public HDF reader results (no tolerance).

Used by the PY-ROUTE-1 equivalence suite. Floats compare by IEEE bits (NaN
payloads and signed zero included), arrays by dtype/shape/bytes, geometries by
WKB, CRS by WKT, frames by columns/index/dtypes/attrs and cell-by-cell values.
"""
import struct

import numpy as np
import pandas as pd


def _float_bits(value):
    return struct.pack("<d", float(value))


def assert_identical(a, b, where="result"):
    import shapely
    import xarray as xr
    from geopandas import GeoDataFrame, GeoSeries

    assert type(a) is type(b), f"{where}: type {type(a)} != {type(b)}"
    if isinstance(a, xr.Dataset) or isinstance(a, xr.DataArray):
        xr.testing.assert_identical(a, b)
        items = list(a.variables.items()) if isinstance(a, xr.Dataset) else [("data", a.variable)] + list(a.coords.variables.items())
        other = dict(b.variables.items()) if isinstance(b, xr.Dataset) else dict([("data", b.variable)] + list(b.coords.variables.items()))
        for name, var in items:
            assert_identical(np.asarray(var.values), np.asarray(other[name].values), f"{where}.{name}")
            assert_identical(dict(var.attrs), dict(other[name].attrs), f"{where}.{name}.attrs")
        assert_identical(dict(a.attrs), dict(b.attrs), f"{where}.attrs")
        return
    if isinstance(a, (pd.DataFrame,)):
        assert list(a.columns) == list(b.columns), f"{where}: columns"
        assert_identical(a.index, b.index, f"{where}.index")
        assert [str(t) for t in a.dtypes] == [str(t) for t in b.dtypes], f"{where}: dtypes"
        if isinstance(a, GeoDataFrame):
            def crs(frame):
                try:
                    return frame.crs
                except AttributeError:  # no active geometry column
                    return None
            ca, cb = crs(a), crs(b)
            assert (ca is None) == (cb is None), f"{where}: crs presence"
            if ca is not None:
                assert ca.to_wkt() == cb.to_wkt(), f"{where}: crs WKT"
            assert a._geometry_column_name == b._geometry_column_name, f"{where}: geometry column"
        assert_identical(dict(a.attrs), dict(b.attrs), f"{where}.attrs")
        for i, col in enumerate(a.columns):
            assert_identical(a.iloc[:, i], b.iloc[:, i], f"{where}[{col!r}]")
        return
    if isinstance(a, (pd.Series,)):
        assert str(a.dtype) == str(b.dtype), f"{where}: dtype {a.dtype} != {b.dtype}"
        assert a.name == b.name, f"{where}: name"
        assert_identical(a.index, b.index, f"{where}.index")
        if isinstance(a, GeoSeries) or str(a.dtype) == "geometry":
            wa = shapely.to_wkb(np.asarray(a.values, dtype=object), hex=False)
            wb = shapely.to_wkb(np.asarray(b.values, dtype=object), hex=False)
            assert list(wa) == list(wb), f"{where}: geometry WKB"
            if isinstance(a, GeoSeries):
                assert (a.crs is None) == (b.crs is None)
                if a.crs is not None:
                    assert a.crs.to_wkt() == b.crs.to_wkt(), f"{where}: crs"
            return
        if a.dtype == object:
            va, vb = a.tolist(), b.tolist()
            assert len(va) == len(vb)
            for j, (x, y) in enumerate(zip(va, vb)):
                assert_identical(x, y, f"{where}[{j}]")
            return
        assert_identical(np.asarray(a.array), np.asarray(b.array), f"{where}.values")
        return
    if isinstance(a, pd.Index):
        assert type(a) is type(b) and str(a.dtype) == str(b.dtype) and a.names == b.names, f"{where}: index type"
        if a.dtype == object:
            for j, (x, y) in enumerate(zip(a.tolist(), b.tolist())):
                assert_identical(x, y, f"{where}[{j}]")
        else:
            assert_identical(np.asarray(a), np.asarray(b), f"{where}.values")
        return
    if isinstance(a, np.ndarray):
        assert a.dtype == b.dtype and a.shape == b.shape, f"{where}: {a.dtype}{a.shape} != {b.dtype}{b.shape}"
        if a.dtype == object:
            for j, (x, y) in enumerate(zip(a.ravel().tolist(), b.ravel().tolist())):
                assert_identical(x, y, f"{where}[{j}]")
        else:
            assert a.tobytes() == b.tobytes(), f"{where}: bytes differ"
        return
    if isinstance(a, dict):
        assert list(a.keys()) == list(b.keys()), f"{where}: keys"
        for k in a:
            assert_identical(a[k], b[k], f"{where}[{k!r}]")
        return
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{where}: length"
        for j, (x, y) in enumerate(zip(a, b)):
            assert_identical(x, y, f"{where}[{j}]")
        return
    if isinstance(a, shapely.Geometry):
        assert shapely.to_wkb(a) == shapely.to_wkb(b), f"{where}: geometry WKB"
        return
    if isinstance(a, (float, np.floating)):
        assert np.asarray(a).tobytes() == np.asarray(b).tobytes(), f"{where}: float bits {a!r} != {b!r}"
        return
    if isinstance(a, np.generic):
        assert a.dtype == b.dtype and a.tobytes() == b.tobytes(), f"{where}: scalar {a!r} != {b!r}"
        return
    if a is pd.NaT or a is None:
        assert b is a, f"{where}: {a!r} != {b!r}"
        return
    assert a == b, f"{where}: {a!r} != {b!r}"
