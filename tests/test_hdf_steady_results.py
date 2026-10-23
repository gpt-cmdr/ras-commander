"""Regression coverage for legacy steady-flow plan HDF layouts."""

from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander.hdf import HdfResultsPlan


STEADY_BASE_PATH = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"


def _write_legacy_steady_plan_hdf(path: Path) -> None:
    """Write a HEC-RAS 6.x-like steady HDF without output-side XS attributes."""
    attributes_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S32"),
            ("Len Channel", "f4"),
        ]
    )
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/Cross Sections/Attributes",
            data=np.array(
                [
                    (b"River A", b"Reach A", b"1000", 125.0),
                    (b"River A", b"Reach A", b"900", 1.0e30),
                ],
                dtype=attributes_dtype,
            ),
        )
        hdf.create_dataset(
            f"{STEADY_BASE_PATH}/Profile Names",
            data=np.array([b"10-percent AEP", b"1-percent AEP"]),
        )
        hdf.create_dataset(
            f"{STEADY_BASE_PATH}/Cross Sections/Water Surface",
            data=np.array([[101.0, 100.5], [102.0, 101.5]]),
        )
        hdf.create_dataset(
            f"{STEADY_BASE_PATH}/Cross Sections/Flow",
            data=np.array([[1000.0, 1000.0], [1500.0, 1500.0]]),
        )
        hdf.create_dataset(
            f"{STEADY_BASE_PATH}/Cross Sections/Additional Variables/Maximum Depth Total",
            data=np.array([[5.0, 4.0], [6.0, 5.0]]),
        )
        hdf.create_dataset(
            f"{STEADY_BASE_PATH}/Cross Sections/Additional Variables/Hydraulic Depth Channel",
            data=np.array([[2.0, 1.0], [3.0, 2.0]]),
        )


def test_steady_results_uses_geometry_cross_section_attributes_when_needed(tmp_path):
    hdf_path = tmp_path / "legacy_steady.p01.hdf"
    _write_legacy_steady_plan_hdf(hdf_path)

    wse = HdfResultsPlan.get_steady_wse(hdf_path)
    results = HdfResultsPlan.get_steady_results(hdf_path)

    assert wse.to_dict("records") == [
        {
            "River": "River A",
            "Reach": "Reach A",
            "Station": "1000",
            "Profile": "10-percent AEP",
            "WSE": 101.0,
        },
        {
            "River": "River A",
            "Reach": "Reach A",
            "Station": "900",
            "Profile": "10-percent AEP",
            "WSE": 100.5,
        },
        {
            "River": "River A",
            "Reach": "Reach A",
            "Station": "1000",
            "Profile": "1-percent AEP",
            "WSE": 102.0,
        },
        {
            "River": "River A",
            "Reach": "Reach A",
            "Station": "900",
            "Profile": "1-percent AEP",
            "WSE": 101.5,
        },
    ]
    assert results[["river", "reach", "node_id", "profile", "wsel", "flow"]].to_dict("records") == [
        {
            "river": "River A",
            "reach": "Reach A",
            "node_id": "1000",
            "profile": "10-percent AEP",
            "wsel": 101.0,
            "flow": 1000.0,
        },
        {
            "river": "River A",
            "reach": "Reach A",
            "node_id": "900",
            "profile": "10-percent AEP",
            "wsel": 100.5,
            "flow": 1000.0,
        },
        {
            "river": "River A",
            "reach": "Reach A",
            "node_id": "1000",
            "profile": "1-percent AEP",
            "wsel": 102.0,
            "flow": 1500.0,
        },
        {
            "river": "River A",
            "reach": "Reach A",
            "node_id": "900",
            "profile": "1-percent AEP",
            "wsel": 101.5,
            "flow": 1500.0,
        },
    ]
    assert results[["max_depth", "hydraulic_depth", "channel_length"]].to_dict("records") == [
        {"max_depth": 5.0, "hydraulic_depth": 2.0, "channel_length": 125.0},
        {"max_depth": 4.0, "hydraulic_depth": 1.0, "channel_length": 0.0},
        {"max_depth": 6.0, "hydraulic_depth": 3.0, "channel_length": 125.0},
        {"max_depth": 5.0, "hydraulic_depth": 2.0, "channel_length": 0.0},
    ]
    assert results.attrs["max_depth_source"] == "Maximum Depth Total"
    assert results.attrs["channel_length_source"].endswith("Len Channel")


def test_steady_results_records_legacy_hydraulic_depth_fallback(tmp_path):
    hdf_path = tmp_path / "legacy_depth_fallback.p01.hdf"
    _write_legacy_steady_plan_hdf(hdf_path)
    maximum_depth_path = (
        f"{STEADY_BASE_PATH}/Cross Sections/Additional Variables/"
        "Maximum Depth Total"
    )
    with h5py.File(hdf_path, "a") as hdf:
        del hdf[maximum_depth_path]

    results = HdfResultsPlan.get_steady_results(hdf_path)

    assert results["max_depth"].tolist() == results["hydraulic_depth"].tolist()
    assert results.attrs["max_depth_source"] == (
        "Hydraulic Depth Channel (legacy fallback)"
    )


def test_steady_results_rejects_misaligned_variable_shape(tmp_path):
    hdf_path = tmp_path / "misaligned_steady.p01.hdf"
    _write_legacy_steady_plan_hdf(hdf_path)
    maximum_depth_path = (
        f"{STEADY_BASE_PATH}/Cross Sections/Additional Variables/"
        "Maximum Depth Total"
    )
    with h5py.File(hdf_path, "a") as hdf:
        del hdf[maximum_depth_path]
        hdf.create_dataset(maximum_depth_path, data=np.array([[5.0, 4.0]]))

    with pytest.raises(ValueError, match="Maximum Depth Total.*shape"):
        HdfResultsPlan.get_steady_results(hdf_path)


@pytest.mark.parametrize("layout", ["primary", "additional", "both"])
def test_steady_energy_uses_stored_values_and_prefers_primary(tmp_path, layout):
    path = tmp_path / "energy.p02.hdf"
    _write_legacy_steady_plan_hdf(path)
    xs = f"{STEADY_BASE_PATH}/Cross Sections"
    primary = np.array([[103.25, 102.75], [104.5, 103.5]])
    alternate = primary + 10
    with h5py.File(path, "a") as hdf:
        if layout in ("primary", "both"):
            hdf.create_dataset(f"{xs}/Energy Grade", data=primary)
        if layout in ("additional", "both"):
            hdf.create_dataset(f"{xs}/Additional Variables/Energy Grade", data=alternate)

    result = HdfResultsPlan.get_steady_results(path)

    expected = alternate if layout == "additional" else primary
    np.testing.assert_array_equal(result["energy"], expected.reshape(-1))
    suffix = "Additional Variables/Energy Grade" if layout == "additional" else "Energy Grade"
    assert result.attrs["column_sources"]["energy"] == f"{xs}/{suffix}"
    assert "energy" not in result.attrs["unavailable_columns"]


def test_steady_results_reports_absent_optional_outputs_once(tmp_path, monkeypatch):
    import importlib

    module = importlib.import_module("ras_commander.hdf.HdfResultsPlan")
    warnings = []
    monkeypatch.setattr(module.logger, "warning", lambda *args: warnings.append(args))
    path = tmp_path / "unavailable.p02.hdf"
    _write_legacy_steady_plan_hdf(path)

    result = HdfResultsPlan.get_steady_results(path)

    for column in ("energy", "froude", "min_ch_el"):
        assert result[column].isna().all()
        assert column in result.attrs["unavailable_columns"]
        assert result.attrs["column_sources"][column] is None
    assert len(warnings) == 1
    message = warnings[0][0] % warnings[0][1:]
    assert "Energy Grade" in message
    assert "Froude # Channel" in message
    assert "Min Ch El" in message
    assert result.attrs["max_depth_source"] == "Maximum Depth Total"
    assert list(result.columns) == [
        "river", "reach", "node_id", "profile", "wsel", "velocity", "flow",
        "froude", "energy", "max_depth", "hydraulic_depth", "channel_length",
        "min_ch_el", "top_width", "area", "eg_slope", "friction_slope",
    ]


def test_present_nan_energy_does_not_fall_back_or_report_source_absent(tmp_path):
    path = tmp_path / "present_nan.p02.hdf"
    _write_legacy_steady_plan_hdf(path)
    xs = f"{STEADY_BASE_PATH}/Cross Sections"
    with h5py.File(path, "a") as hdf:
        hdf.create_dataset(f"{xs}/Energy Grade", data=np.full((2, 2), np.nan))
        hdf.create_dataset(f"{xs}/Additional Variables/Energy Grade", data=np.ones((2, 2)))
        hdf.create_dataset(f"{xs}/Additional Variables/Froude # Channel", data=np.full((2, 2), np.nan))
        hdf.create_dataset(f"{xs}/Additional Variables/Min Ch El", data=np.full((2, 2), np.nan))

    result = HdfResultsPlan.get_steady_results(path)

    assert result["energy"].isna().all()
    for column in ("energy", "froude", "min_ch_el"):
        assert column not in result.attrs["unavailable_columns"]
        assert result.attrs["column_sources"][column] is not None


@pytest.mark.parametrize("shape", [(1, 2), (4,), (2, 1)])
def test_malformed_primary_energy_raises_even_with_valid_fallback(tmp_path, shape):
    path = tmp_path / "bad_energy.p02.hdf"
    _write_legacy_steady_plan_hdf(path)
    xs = f"{STEADY_BASE_PATH}/Cross Sections"
    with h5py.File(path, "a") as hdf:
        hdf.create_dataset(f"{xs}/Energy Grade", data=np.ones(shape))
        hdf.create_dataset(f"{xs}/Additional Variables/Energy Grade", data=np.ones((2, 2)))

    with pytest.raises(ValueError, match="Energy Grade.*shape"):
        HdfResultsPlan.get_steady_results(path)


@pytest.mark.parametrize("keep_hydraulic_depth", [True, False])
def test_depth_fallback_availability_tracks_actual_source(tmp_path, keep_hydraulic_depth):
    path = tmp_path / "depth_source.p02.hdf"
    _write_legacy_steady_plan_hdf(path)
    add = f"{STEADY_BASE_PATH}/Cross Sections/Additional Variables"
    with h5py.File(path, "a") as hdf:
        del hdf[f"{add}/Maximum Depth Total"]
        if not keep_hydraulic_depth:
            del hdf[f"{add}/Hydraulic Depth Channel"]

    result = HdfResultsPlan.get_steady_results(path)

    assert ("max_depth" in result.attrs["unavailable_columns"]) is not keep_hydraulic_depth
    assert result.attrs["column_sources"]["max_depth"] == (
        f"{add}/Hydraulic Depth Channel" if keep_hydraulic_depth else None
    )
