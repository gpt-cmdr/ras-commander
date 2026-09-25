"""Deterministic tests for the gridded-precipitation qualification harness."""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np

from scripts.qualification.gridded_precipitation_matrix import (
    COMPUTE_MESSAGES,
    CUMULATIVE_PRECIPITATION,
    PRECIPITATION_GROUP,
    WATER_SURFACE,
    _inspect_hdf,
    _qualification_wmic_shim,
)


def test_inspect_hdf_records_precipitation_hydraulics_and_messages(
    tmp_path: Path,
) -> None:
    hdf_path = tmp_path / "qualified.p01.hdf"
    area = "Asymmetric Area"

    with h5py.File(hdf_path, "w") as hdf:
        precipitation = hdf.create_group(PRECIPITATION_GROUP)
        precipitation.attrs["Source"] = "DSS"
        precipitation.attrs["Units"] = "in"
        precipitation.create_dataset(
            "Timestamp",
            data=np.asarray(
                [b"01Jan2000 00:00:00.000", b"01Jan2000 00:15:00.000"]
            ),
        )
        precipitation.create_dataset(
            "Values",
            data=np.asarray([[0.0, 1.0], [2.0, np.nan]], dtype=np.float32),
        )

        hdf.create_dataset(
            CUMULATIVE_PRECIPITATION.format(area=area),
            data=np.asarray([[0.0, 0.1], [0.2, 0.3]], dtype=np.float32),
        )
        hdf.create_dataset(
            WATER_SURFACE.format(area=area),
            data=np.asarray([[10.0, 11.0], [12.0, 13.0]], dtype=np.float32),
        )
        hdf.create_dataset(
            COMPUTE_MESSAGES,
            data=np.asarray(
                [
                    b"Processing Precipitation data...\n"
                    b"Finished Processing Precipitation data\n"
                    b"Performing Unsteady Flow Simulation\n"
                    b"Finished Unsteady Flow Simulation\n"
                    b"Complete Process"
                ]
            ),
        )

    evidence = _inspect_hdf(hdf_path)

    assert evidence["exists"] is True
    assert len(evidence["sha256"]) == 64
    assert evidence["precipitation"]["attributes"] == {
        "Source": "DSS",
        "Units": "in",
    }
    assert evidence["precipitation"]["timestamps"]["shape"] == [2]
    assert evidence["precipitation"]["values"] == {
        "shape": [2, 2],
        "dtype": "float32",
        "minimum": 0.0,
        "maximum": 2.0,
        "nonzero": 2,
    }
    assert evidence["2d_flow_areas"][area]["cumulative_precipitation"][
        "maximum"
    ] == np.float32(0.3)
    assert evidence["2d_flow_areas"][area]["water_surface"]["nonzero"] == 4
    assert evidence["compute_messages"]["complete_process"] is True
    assert evidence["compute_messages"]["finished_unsteady"] is True
    assert evidence["compute_messages"]["fatal"] is False


def test_qualification_wmic_shim_is_process_local() -> None:
    original_path = os.environ.get("PATH", "")

    with _qualification_wmic_shim(True) as shim:
        assert shim is not None
        assert (shim / "wmic.cmd").is_file()
        assert (shim / "wmic.ps1").is_file()
        assert os.environ["PATH"].split(os.pathsep)[0] == str(shim)

    assert os.environ.get("PATH", "") == original_path


def test_disabled_wmic_shim_does_not_change_path() -> None:
    original_path = os.environ.get("PATH", "")

    with _qualification_wmic_shim(False) as shim:
        assert shim is None
        assert os.environ.get("PATH", "") == original_path

    assert os.environ.get("PATH", "") == original_path
