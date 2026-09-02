from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import HdfBase


def _write_result_hdf(
    path: Path,
    *,
    si_units=None,
    unit_system=None,
    include_results: bool = True,
) -> Path:
    with h5py.File(path, "w") as hdf_file:
        if include_results:
            hdf_file.require_group("Results/Steady")
        geometry = hdf_file.require_group("Geometry")
        if si_units is not None:
            geometry.attrs["SI Units"] = si_units
        if unit_system is not None:
            hdf_file.attrs["Units System"] = unit_system
    return path


@pytest.mark.parametrize(
    ("si_units", "unit_system", "expected"),
    [
        (False, np.bytes_("US Customary"), ("US Customary", "ft", "ft3/s")),
        (1, np.bytes_("SI Units"), ("SI", "m", "m3/s")),
    ],
)
def test_result_unit_metadata_resolves_agreeing_evidence(
    tmp_path,
    si_units,
    unit_system,
    expected,
):
    hdf_path = _write_result_hdf(
        tmp_path / "Model.p01.hdf",
        si_units=si_units,
        unit_system=unit_system,
    )

    metadata = HdfBase.get_result_unit_metadata(hdf_path)

    expected_system, expected_length, expected_flow = expected
    assert metadata["status"] == "resolved"
    assert metadata["unit_system"] == expected_system
    assert metadata["length_units"] == expected_length
    assert metadata["depth_units"] == expected_length
    assert metadata["velocity_units"] == f"{expected_length}/s"
    assert metadata["flow_units"] == expected_flow
    assert metadata["source"] == "plan_hdf"
    assert metadata["source_file"] == str(hdf_path.resolve())
    assert metadata["contradictions"] == []
    assert [item["attribute"] for item in metadata["evidence"]] == [
        "/Geometry/@SI Units",
        "/@Units System",
    ]


def test_result_unit_metadata_reports_missing_without_english_default(tmp_path):
    hdf_path = _write_result_hdf(tmp_path / "missing.p01.hdf")

    with pytest.raises(ValueError, match="no recognized embedded"):
        HdfBase.get_result_unit_metadata(hdf_path)

    metadata = HdfBase.get_result_unit_metadata(hdf_path, strict=False)
    assert metadata["status"] == "missing"
    assert metadata["unit_system"] is None
    assert metadata["length_units"] is None
    assert metadata["flow_units"] is None
    assert metadata["evidence"] == []


def test_result_unit_metadata_reports_unrecognized_value(tmp_path):
    hdf_path = _write_result_hdf(
        tmp_path / "unrecognized.p01.hdf",
        unit_system=np.bytes_("Martian"),
    )

    with pytest.raises(ValueError, match="Unrecognized /@Units System"):
        HdfBase.get_result_unit_metadata(hdf_path)

    metadata = HdfBase.get_result_unit_metadata(hdf_path, strict=False)
    assert metadata["status"] == "unrecognized"
    assert metadata["evidence"] == [
        {
            "attribute": "/@Units System",
            "raw_value": "Martian",
            "unit_system": None,
        }
    ]
    assert metadata["contradictions"]


def test_result_unit_metadata_reports_contradictory_evidence(tmp_path):
    hdf_path = _write_result_hdf(
        tmp_path / "contradictory.p01.hdf",
        si_units=True,
        unit_system=np.bytes_("US Customary"),
    )

    with pytest.raises(ValueError, match="unit-system metadata is contradictory"):
        HdfBase.get_result_unit_metadata(hdf_path)

    metadata = HdfBase.get_result_unit_metadata(hdf_path, strict=False)
    assert metadata["status"] == "contradictory"
    assert metadata["unit_system"] is None
    assert {item["unit_system"] for item in metadata["evidence"]} == {
        "SI",
        "US Customary",
    }


def test_result_unit_metadata_rejects_geometry_only_hdf(tmp_path):
    hdf_path = _write_result_hdf(
        tmp_path / "Model.g01.hdf",
        si_units=False,
        unit_system=np.bytes_("US Customary"),
        include_results=False,
    )

    with pytest.raises(ValueError, match="does not contain a /Results group"):
        HdfBase.get_result_unit_metadata(hdf_path)

    metadata = HdfBase.get_result_unit_metadata(hdf_path, strict=False)
    assert metadata["status"] == "unrecognized"
    assert metadata["length_units"] is None
