from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import (
    CalibrationPoint,
    extract_modeled,
    extract_steady_profile_modeled,
    extract_steady_profile_observations,
    make_steady_profile_calibration_points,
)


def _write_steady_hdf(path: Path) -> Path:
    base_path = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"
    xs_path = f"{base_path}/Cross Sections"
    geom_info_path = "Results/Steady/Output/Geometry Info"

    with h5py.File(path, "w") as hdf:
        profile_group = hdf.require_group(base_path)
        profile_group.create_dataset(
            "Profile Names",
            data=np.array([b"PF 1", b"PF 2"]),
        )

        xs_group = hdf.require_group(xs_path)
        xs_group.create_dataset(
            "Water Surface",
            data=np.array(
                [
                    [101.1, 102.2, 103.3],
                    [201.1, 202.2, 203.3],
                ],
                dtype=float,
            ),
        )

        attrs_dtype = np.dtype(
            [
                ("River", "S32"),
                ("Reach", "S32"),
                ("Station", "S16"),
            ]
        )
        attrs = np.array(
            [
                (b"River A", b"Reach 1", b"100"),
                (b"River A", b"Reach 1", b"200"),
                (b"River A", b"Reach 1", b"300.05"),
            ],
            dtype=attrs_dtype,
        )
        hdf.require_group(geom_info_path).create_dataset(
            "Cross Section Attributes",
            data=attrs,
        )

    return path


@pytest.fixture()
def steady_hdf(tmp_path: Path) -> Path:
    return _write_steady_hdf(tmp_path / "steady.p01.hdf")


def test_extract_steady_profile_modeled_exact_station(steady_hdf: Path) -> None:
    point = CalibrationPoint(
        name="PF1 RS200",
        variable="wse",
        extraction_method="steady_profile",
        observed=102.0,
        river="River A",
        reach="Reach 1",
        station="200",
        profile_name="PF 1",
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(102.2)
    assert extract_modeled(point, steady_hdf) == pytest.approx(102.2)


def test_extract_steady_profile_modeled_numeric_station_match(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="PF2 RS200 numeric",
        variable="wse",
        extraction_method="steady_profile",
        observed=202.0,
        river="River A",
        reach="Reach 1",
        station="200.0",
        profile_name="PF 2",
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(202.2)


def test_extract_steady_profile_modeled_station_tolerance(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="PF1 RS300 tolerance",
        variable="wse",
        extraction_method="steady_profile",
        observed=103.0,
        river="River A",
        reach="Reach 1",
        station="300.0",
        profile_name="PF 1",
        station_tolerance=0.1,
    )

    assert extract_steady_profile_modeled(point, steady_hdf) == pytest.approx(103.3)


def test_extract_steady_profile_modeled_station_mismatch_is_clear(
    steady_hdf: Path,
) -> None:
    point = CalibrationPoint(
        name="missing station",
        variable="wse",
        extraction_method="steady_profile",
        observed=99.0,
        river="River A",
        reach="Reach 1",
        station="999",
        profile_name="PF 1",
    )

    with pytest.raises(ValueError, match="No steady-profile row matched station"):
        extract_steady_profile_modeled(point, steady_hdf)


def test_extract_observations_profile_filter_and_make_points(
    steady_hdf: Path,
) -> None:
    all_observations = extract_steady_profile_observations(steady_hdf)
    all_points = make_steady_profile_calibration_points(all_observations)

    assert len(all_points) == 6
    assert {point.profile_name for point in all_points} == {"PF 1", "PF 2"}

    observations = extract_steady_profile_observations(
        steady_hdf,
        profiles=["PF 2"],
    )

    assert observations["profile"].unique().tolist() == ["PF 2"]
    assert observations["observed"].tolist() == pytest.approx(
        [201.1, 202.2, 203.3]
    )

    points = make_steady_profile_calibration_points(
        observations,
        station_tolerance=0.05,
    )

    assert len(points) == 3
    assert {point.extraction_method for point in points} == {"steady_profile"}
    assert {point.profile_name for point in points} == {"PF 2"}
    assert points[1].observed == pytest.approx(202.2)
