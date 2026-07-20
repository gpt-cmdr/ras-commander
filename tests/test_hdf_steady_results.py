"""Regression coverage for legacy steady-flow plan HDF layouts."""

from pathlib import Path

import h5py
import numpy as np

from ras_commander.hdf import HdfResultsPlan


STEADY_BASE_PATH = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"


def _write_legacy_steady_plan_hdf(path: Path) -> None:
    """Write a HEC-RAS 6.x-like steady HDF without output-side XS attributes."""
    attributes_dtype = np.dtype(
        [
            ("River", "S32"),
            ("Reach", "S32"),
            ("RS", "S32"),
        ]
    )
    with h5py.File(path, "w") as hdf:
        hdf.create_dataset(
            "Geometry/Cross Sections/Attributes",
            data=np.array(
                [
                    (b"River A", b"Reach A", b"1000"),
                    (b"River A", b"Reach A", b"900"),
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
