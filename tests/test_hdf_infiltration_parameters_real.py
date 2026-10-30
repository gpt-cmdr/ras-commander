"""``HdfInfiltration.get_infiltration_parameters`` on real RASMapper infiltration layers.

HEC-RAS stores per-class infiltration parameters in the layer's root
``Variables`` table, keyed by ``Name``. Every expected value here is read
independently with plain h5py; the method under test must return the same row
in h5py and native mode.

Committed fixtures (``tests/fixtures/infiltration_layers``) always run. More
layers are taken from ``RAS_ROUTE2_FIXTURES`` (``{"fixtures": [{"name",
"path"}]}``) when it is set: every listed HDF whose root ``LC Type`` starts
with ``Infiltration`` is checked; the parametrisation is empty otherwise.
"""
import json
import os
from pathlib import Path

import h5py
import pandas as pd
import pytest

from ras_commander import fast_hdf
from ras_commander.hdf import HdfInfiltration

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "infiltration_layers"
COMMITTED = sorted(FIXTURE_DIR.glob("*.hdf"))


def _lc_type(path):
    with h5py.File(path, "r") as hdf:
        value = hdf.attrs.get("LC Type")
    return value.decode() if isinstance(value, bytes) else str(value or "")


def _manifest_layers():
    manifest = os.environ.get("RAS_ROUTE2_FIXTURES")
    if not manifest:
        return []
    layers = []
    for entry in json.loads(Path(manifest).read_text()).get("fixtures", []):
        path = Path(entry["path"])
        if path.suffix.lower() != ".hdf" or not path.exists():
            continue
        try:
            if _lc_type(path).startswith("Infiltration"):
                layers.append(path)
        except OSError:
            continue
    return layers


LAYERS = COMMITTED + _manifest_layers()


def _expected_rows(path):
    """Independent read: {Name: {parameter: float}} from plain h5py."""
    with h5py.File(path, "r") as hdf:
        table = hdf["Variables"][()]
    params = [f for f in table.dtype.names if f != "Name"]
    return {
        row["Name"].decode(): {f: float(row[f]) for f in params}
        for row in table
    }


def _call(backend, path, mukey):
    with fast_hdf.backend_scope(backend):
        return HdfInfiltration.get_infiltration_parameters(path, mukey=mukey)


def _backends():
    try:
        import ras_commander_fast_hdf  # noqa: F401
    except ImportError:
        return ["h5py"]
    return ["h5py", "native"]


def test_committed_fixtures_cover_each_keying_layout():
    assert {p.name for p in COMMITTED} == {
        "deficitconstant_701.hdf",
        "greenampt_701.hdf",
        "scs_701.hdf",
        "deficitconstant_soils_only_rbfs.hdf",
        "greenampt_legacy_homewood.hdf",
    }


@pytest.mark.parametrize("path", LAYERS, ids=[p.name for p in LAYERS])
def test_every_class_row_matches_independent_read(path):
    expected = _expected_rows(path)
    assert expected
    for backend in _backends():
        for name, params in expected.items():
            result = _call(backend, path, name)
            assert result == params, (backend, name)
            assert list(result) == list(params)


@pytest.mark.parametrize("path", LAYERS, ids=[p.name for p in LAYERS])
def test_native_read_is_made_and_identical(path):
    pytest.importorskip("ras_commander_fast_hdf")
    name = next(iter(_expected_rows(path)))
    with fast_hdf.trace_reads() as records:
        native = _call("native", path, name)
    assert any(r["backend"].startswith("native") for r in records)
    assert native == _call("h5py", path, name)


@pytest.mark.parametrize("path", LAYERS, ids=[p.name for p in LAYERS])
def test_unknown_class_returns_none(path):
    for backend in _backends():
        assert _call(backend, path, "__no_such_class__") is None


def test_method_specific_keys():
    keys = {
        "deficitconstant_701.hdf": [
            "Maximum Deficit", "Initial Deficit", "Potential Percolation Rate"],
        "greenampt_701.hdf": [
            "Wetting Front Suction", "Saturated Hydraulic Conductivity",
            "Initial Soil Water Content", "Saturated Soil Water Content",
            "Residual Soil Water Content", "Pore Size Distribution Index"],
        "scs_701.hdf": [
            "Curve Number", "Abstraction Ratio", "Minimum Infiltration Rate"],
    }
    for file_name, expected_keys in keys.items():
        result = _call("h5py", FIXTURE_DIR / file_name, "Mixed Forest : B")
        assert list(result) == expected_keys
        for legacy in ("Initial Loss (in)", "Constant Loss Rate (in/hr)",
                       "Impervious Area (%)"):
            assert legacy not in result


def test_soils_only_layer_is_keyed_by_soil_class():
    path = FIXTURE_DIR / "deficitconstant_soils_only_rbfs.hdf"
    with h5py.File(path, "r") as hdf:
        soil_classes = [v[0].decode() for v in hdf["Dependency Classifications"][()]]
    expected = _expected_rows(path)
    assert set(soil_classes) == set(expected)
    assert _call("h5py", path, "167") == expected["167"]


@pytest.mark.parametrize(
    "file_name", ["deficitconstant_701.hdf", "greenampt_701.hdf", "scs_701.hdf"])
def test_bare_dependency_class_of_combined_layer_is_refused(file_name):
    path = FIXTURE_DIR / file_name
    with h5py.File(path, "r") as hdf:
        deps = hdf["Dependency Classifications"][()]
    soil_column = deps.dtype.names[1]
    soil_class = deps[soil_column][1].decode()
    assert soil_class == "B"
    for backend in _backends():
        with pytest.raises(ValueError, match="combined classes"):
            _call(backend, path, soil_class)


def test_weighted_parameters_use_returned_keys():
    path = FIXTURE_DIR / "deficitconstant_soils_only_rbfs.hdf"
    params = {m: _call("h5py", path, m) for m in ("167", "33")}
    stats = pd.DataFrame({"mukey": ["167", "33"], "Percentage": [75.0, 25.0]})
    weighted = HdfInfiltration.calculate_weighted_parameters(stats, params)
    assert list(weighted) == list(params["167"])
    for key, value in weighted.items():
        assert value == pytest.approx(
            0.75 * params["167"][key] + 0.25 * params["33"][key])


def test_weighted_parameters_skip_unavailable_sentinel():
    """7.0.1 Green-Ampt stores -9999 for two parameters: never average it."""
    path = FIXTURE_DIR / "greenampt_701.hdf"
    classes = ["Mixed Forest : B", "Mixed Forest : A"]
    params = {c: _call("h5py", path, c) for c in classes}
    with h5py.File(path, "r") as hdf:
        table = hdf["Variables"][()]
    rows = {row["Name"].decode(): row for row in table}
    sentinel = [k for k in table.dtype.names
                if k != "Name" and any(float(rows[c][k]) == -9999.0 for c in classes)]
    assert sentinel == ["Residual Soil Water Content", "Pore Size Distribution Index"]
    # get_infiltration_parameters still returns exactly what is stored.
    assert params[classes[0]]["Residual Soil Water Content"] == -9999.0

    stats = pd.DataFrame({"mukey": classes, "Percentage": [60.0, 40.0]})
    weighted = HdfInfiltration.calculate_weighted_parameters(stats, params)

    for key in sentinel:
        assert key not in weighted
    available = [k for k in params[classes[0]] if k not in sentinel]
    assert list(weighted) == available
    for key in available:
        assert weighted[key] == pytest.approx(
            0.6 * float(rows[classes[0]][key]) + 0.4 * float(rows[classes[1]][key]))


@pytest.mark.parametrize("bad", [-9999.0, float("nan"), None])
def test_weighted_parameters_drop_parameter_any_class_lacks(bad):
    params = {
        "a": {"Curve Number": 70.0, "Abstraction Ratio": 0.2},
        "b": {"Curve Number": 80.0, "Abstraction Ratio": 0.2},
    }
    if bad is None:
        del params["b"]["Abstraction Ratio"]
    else:
        params["b"]["Abstraction Ratio"] = bad
    stats = pd.DataFrame({"mukey": ["a", "b"], "Percentage": [50.0, 50.0]})
    weighted = HdfInfiltration.calculate_weighted_parameters(stats, params)
    assert weighted == {"Curve Number": pytest.approx(75.0)}
