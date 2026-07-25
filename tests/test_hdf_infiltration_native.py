"""Native infiltration sidecar editing and compatibility routing tests."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander.hdf.HdfInfiltration import HdfInfiltration


def test_canonical_sidecar_signatures_use_semantic_hdf_names():
    setter = list(
        inspect.signature(
            HdfInfiltration.set_infiltration_sidecar_parameters
        ).parameters
    )
    sidecar_scaler = list(
        inspect.signature(
            HdfInfiltration.scale_infiltration_sidecar_parameters
        ).parameters
    )
    base_scaler = list(
        inspect.signature(
            HdfInfiltration.scale_infiltration_base_overrides
        ).parameters
    )
    region_scaler_signature = inspect.signature(
        HdfInfiltration.scale_infiltration_region_overrides
    )

    assert setter[:3] == [
        "infiltration_hdf_path",
        "infiltration_df",
        "geometry_hdf_path",
    ]
    assert sidecar_scaler[:4] == [
        "infiltration_hdf_path",
        "infiltration_df",
        "scale_factors",
        "geometry_hdf_path",
    ]
    assert base_scaler[:3] == [
        "geometry_hdf_path",
        "infiltration_df",
        "scale_factors",
    ]
    assert list(region_scaler_signature.parameters) == [
        "geometry_hdf_path",
        "infiltration_df",
        "scale_factors",
        "region_name",
        "region_id",
        "hecras_version",
        "ras_object",
    ]
    assert (
        region_scaler_signature.parameters["region_name"].kind
        is inspect.Parameter.KEYWORD_ONLY
    )


def _write_sidecar(path, lc_type="InfiltrationSCSCurveNumber"):
    dtype = np.dtype(
        [
            ("Name", "S16"),
            ("Curve Number", "f4"),
        ]
    )
    rows = np.array([(b"Class A", 70.0)], dtype=dtype)
    with h5py.File(path, "w") as hdf_file:
        hdf_file.attrs["LC Type"] = np.bytes_(lc_type)
        hdf_file.create_dataset("Variables", data=rows)
    return path


@pytest.mark.parametrize(
    ("lc_type", "expected"),
    [
        ("InfiltrationSCSCurveNumber", "infiltration_scs"),
        ("InfiltrationDeficitConstantLoss", "infiltration_deficit_constant"),
        ("InfiltrationGreenAmpt", "infiltration_green_ampt"),
    ],
)
def test_native_infiltration_layer_type(tmp_path, lc_type, expected):
    sidecar = _write_sidecar(tmp_path / "infiltration.hdf", lc_type)
    assert HdfInfiltration._native_infiltration_layer_type(sidecar) == expected


def test_set_sidecar_routes_through_native_table_editor(
    tmp_path,
    monkeypatch,
):
    sidecar = _write_sidecar(tmp_path / "infiltration.hdf")
    requested = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [77.0]}
    )
    captured = {}

    def fake_set(*, layer_hdf_path, parameter_table, **kwargs):
        captured["path"] = layer_hdf_path
        captured["table"] = parameter_table.copy()
        captured.update(kwargs)
        return parameter_table.copy()

    monkeypatch.setattr(
        "ras_commander._landcover_native.set_classification_parameters",
        fake_set,
    )
    result = HdfInfiltration.set_infiltration_sidecar_parameters(
        sidecar,
        requested,
        ras_object=SimpleNamespace(ras_version="6.6"),
    )

    assert captured["path"] == sidecar
    assert captured["layer_type"] == "infiltration_scs"
    assert captured["hecras_version"] == "6.6"
    pd.testing.assert_frame_equal(result, requested)


def test_set_sidecar_requires_explicit_or_project_version(tmp_path):
    sidecar = _write_sidecar(tmp_path / "infiltration.hdf")
    requested = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [77.0]}
    )
    with pytest.raises(ValueError, match="hecras_version is required"):
        HdfInfiltration.set_infiltration_sidecar_parameters(
            sidecar,
            requested,
            ras_object=SimpleNamespace(ras_version=None),
        )


def test_scale_sidecar_scales_then_uses_native_setter(
    tmp_path,
    monkeypatch,
):
    sidecar = _write_sidecar(tmp_path / "infiltration.hdf")
    requested = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [70.0]}
    )
    captured = {}

    def fake_set(*, infiltration_hdf_path, infiltration_df, **kwargs):
        captured["path"] = infiltration_hdf_path
        captured["table"] = infiltration_df.copy()
        captured.update(kwargs)
        return infiltration_df.copy()

    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_sidecar_parameters",
        staticmethod(fake_set),
    )
    result = HdfInfiltration.scale_infiltration_sidecar_parameters(
        sidecar,
        requested,
        {"Curve Number": 1.1},
        hecras_version="7.0",
    )

    assert captured["hecras_version"] == "7.0"
    assert captured["table"].at[0, "Curve Number"] == pytest.approx(77.0)
    assert result.at[0, "Curve Number"] == pytest.approx(77.0)


def test_scale_region_preserves_sentinel_and_uses_region_setter(monkeypatch):
    requested = pd.DataFrame(
        {
            "Land Cover Name": ["NoData", "Forest"],
            "Curve Number": [-9999.0, 70.0],
        }
    )
    captured = {}

    def fake_set(path, table, **kwargs):
        captured.update(path=path, table=table.copy(), kwargs=kwargs)
        return table

    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_region_overrides",
        staticmethod(fake_set),
    )

    result = HdfInfiltration.scale_infiltration_region_overrides(
        "project.g01.hdf",
        requested,
        {"Curve Number": 1.1},
        region_id=0,
        hecras_version="7.0",
    )

    assert result.at[0, "Curve Number"] == -9999.0
    assert result.at[1, "Curve Number"] == pytest.approx(77.0)
    assert captured["path"] == "project.g01.hdf"
    assert captured["kwargs"] == {
        "region_name": None,
        "region_id": 0,
        "hecras_version": "7.0",
        "ras_object": None,
    }


def test_legacy_sidecar_setter_delegates_with_old_keywords(monkeypatch):
    requested = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [77.0]}
    )
    captured = {}

    def fake_set(**kwargs):
        captured.update(kwargs)
        return requested

    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_sidecar_parameters",
        staticmethod(fake_set),
    )

    with pytest.deprecated_call(match="set_infiltration_layer_data"):
        result = HdfInfiltration.set_infiltration_layer_data(
            "infiltration.hdf",
            requested,
            geom_hdf_path="project.g01.hdf",
            hecras_version="6.6",
        )

    assert result is requested
    assert captured["infiltration_hdf_path"] == "infiltration.hdf"
    assert captured["geometry_hdf_path"] == "project.g01.hdf"
    assert captured["infiltration_df"] is requested


def test_legacy_base_scaler_delegates_with_old_keywords(monkeypatch):
    requested = pd.DataFrame(
        {"Land Cover Name": ["Class A"], "Curve Number": [77.0]}
    )
    captured = {}

    def fake_scale(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return requested

    monkeypatch.setattr(
        HdfInfiltration,
        "scale_infiltration_base_overrides",
        staticmethod(fake_scale),
    )

    with pytest.deprecated_call(match="scale_infiltration_base_overrides"):
        result = HdfInfiltration.scale_infiltration_baseoverrides(
            "project.g01.hdf",
            requested,
            {"Curve Number": 1.1},
            hecras_version="7.0",
        )

    assert result is requested
    assert captured["args"] == (
        "project.g01.hdf",
        requested,
        {"Curve Number": 1.1},
    )
    assert captured["kwargs"]["hecras_version"] == "7.0"


def test_legacy_scale_fails_with_explicit_migration_guidance(tmp_path):
    sidecar = _write_sidecar(tmp_path / "infiltration.hdf")
    requested = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [70.0]}
    )
    with pytest.deprecated_call(
        match="scale_infiltration_region_overrides"
    ):
        with pytest.raises(
            RuntimeError,
            match="Choose the explicit replacement",
        ):
            HdfInfiltration.scale_infiltration_data(
                sidecar,
                requested,
                {"Curve Number": 1.1},
                hecras_version="7.0",
            )
