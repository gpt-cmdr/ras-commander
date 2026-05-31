from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from ras_commander.hdf.HdfChannelCapacity import HdfChannelCapacity, LEVEL_TO_CATEGORY


def _xs_attrs(count: int = 3) -> np.ndarray:
    dtype = np.dtype([
        ("River", "S16"),
        ("Reach", "S16"),
        ("Station", "S16"),
    ])
    return np.array(
        [(b"River A", b"Reach 1", f"{1000 - i * 100}".encode()) for i in range(count)],
        dtype=dtype,
    )


def _write_dataset(hdf: h5py.File, path: str, data: np.ndarray) -> None:
    group_path, name = path.rsplit("/", 1)
    group = hdf.require_group(group_path)
    group.create_dataset(name, data=data)


def test_extract_max_wse_ras6_summary(tmp_path: Path) -> None:
    hdf_path = tmp_path / "summary.p01.hdf"
    summary_base = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Summary Output/Cross Sections"
    )

    with h5py.File(hdf_path, "w") as hdf:
        _write_dataset(
            hdf,
            f"{summary_base}/Maximum Water Surface",
            np.array([[11.0, 12.5, 13.25]]),
        )
        _write_dataset(hdf, f"{summary_base}/Cross Section Attributes", _xs_attrs())

    result = HdfChannelCapacity.extract_max_wse(hdf_path, profile_names=["50P"])

    assert list(result.columns) == ["River", "Reach", "RS", "50P"]
    assert result["50P"].tolist() == [11.0, 12.5, 13.25]
    assert result["RS"].tolist() == ["1000", "900", "800"]


def test_extract_max_wse_unsteady_timeseries_fallback(tmp_path: Path) -> None:
    hdf_path = tmp_path / "timeseries.p01.hdf"
    time_base = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        "Unsteady Time Series/Cross Sections"
    )

    with h5py.File(hdf_path, "w") as hdf:
        _write_dataset(
            hdf,
            f"{time_base}/Water Surface",
            np.array([
                [7.0, 8.0, 9.0],
                [8.5, 9.5, 10.5],
                [8.0, 11.0, 10.0],
            ]),
        )
        _write_dataset(hdf, f"{time_base}/Cross Section Attributes", _xs_attrs())

    result = HdfChannelCapacity.extract_max_wse(hdf_path, profile_names=["20P"])

    assert result["20P"].tolist() == [8.5, 11.0, 10.5]


def test_extract_max_wse_steady_profile_selection_with_geometry_attrs(tmp_path: Path) -> None:
    hdf_path = tmp_path / "steady.p01.hdf"
    steady_base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"

    with h5py.File(hdf_path, "w") as hdf:
        _write_dataset(
            hdf,
            f"{steady_base}/Cross Sections/Water Surface",
            np.array([
                [20.0, 21.0, 22.0],
                [30.0, 31.0, 32.0],
            ]),
        )
        _write_dataset(hdf, f"{steady_base}/Profile Names", np.array([b"10yr", b"100yr"]))
        _write_dataset(
            hdf,
            "Results/Steady/Output/Geometry Info/Cross Section Attributes",
            _xs_attrs(),
        )

    result = HdfChannelCapacity.extract_max_wse(
        hdf_path,
        profile_names=["1P"],
        steady_profile_names=["100yr"],
    )

    assert result["1P"].tolist() == [30.0, 31.0, 32.0]
    assert result["River"].tolist() == ["River A", "River A", "River A"]


def test_determine_capacity_uses_storm_levels_and_breaks_on_first_overtop() -> None:
    bank_df = pd.DataFrame({
        "River": ["R"] * 4,
        "Reach": ["A"] * 4,
        "RS": ["400", "300", "200", "100"],
        "controlling_bank_elev": [10.0, 10.0, 10.0, 10.0],
        "Len Channel": [100.0, 100.0, 100.0, 100.0],
    })
    wse_df = pd.DataFrame({
        "River": ["R"] * 4,
        "Reach": ["A"] * 4,
        "RS": ["400", "300", "200", "100"],
        "50P": [11.0, 9.0, 9.0, 9.0],
        "20P": [12.0, 11.0, 9.0, 9.0],
        "10P": [8.0, 8.0, 9.0, 9.0],
        "4P": [8.0, 8.0, 9.0, 9.0],
        "2P": [8.0, 8.0, 9.0, 9.0],
        "1P": [8.0, 8.0, 9.0, 9.0],
        "0.2P": [8.0, 8.0, 11.0, 9.0],
    })

    result = HdfChannelCapacity.determine_capacity(bank_df, wse_df, storm_order=[
        "50P", "20P", "10P", "4P", "2P", "1P", "0.2P"
    ])

    assert result["capacity_level"].tolist() == [1, 1, 6, 7]
    assert result["last_contained_storm"].tolist() == ["None", "50P", "1P", "0.2P"]
    assert result["capacity_category"].tolist()[-1] == LEVEL_TO_CATEGORY[7]


def test_segment_channel_floor_and_system_summary() -> None:
    capacity_df = pd.DataFrame({
        "River": ["R"] * 3,
        "Reach": ["A"] * 3,
        "RS": ["300", "200", "100"],
        "Len Channel": [700.0, 700.0, 700.0],
        "capacity_level": [4, 5, 7],
        "capacity_category": [LEVEL_TO_CATEGORY[4], LEVEL_TO_CATEGORY[5], LEVEL_TO_CATEGORY[7]],
    })

    segments = HdfChannelCapacity.segment_channel(capacity_df, segment_length=1320.0)
    summary = HdfChannelCapacity.system_capacity_summary(segments)

    assert segments.loc[0, "weighted_capacity"] == 4.5
    assert segments.loc[0, "capacity_level"] == 4
    assert segments.loc[0, "system_capacity"] == LEVEL_TO_CATEGORY[4]
    assert round(summary["percent_of_total"].sum(), 1) == 100.0
    assert set(summary["capacity_level"]) == set(range(1, 8))


def test_extract_max_wse_steady_unnamed_profile_uses_envelope_max(tmp_path: Path) -> None:
    # Multi-profile steady data with NO profile selected -> per-XS envelope max
    # across profiles (not first-profile). Pins the documented unnamed-profile rule.
    hdf_path = tmp_path / "steady_envelope.p01.hdf"
    steady_base = "Results/Steady/Output/Output Blocks/Base Output/Steady Profiles"

    with h5py.File(hdf_path, "w") as hdf:
        _write_dataset(
            hdf,
            f"{steady_base}/Cross Sections/Water Surface",
            np.array([
                [20.0, 31.0, 22.0],
                [30.0, 21.0, 32.0],
            ]),
        )
        _write_dataset(hdf, f"{steady_base}/Profile Names", np.array([b"10yr", b"100yr"]))
        _write_dataset(
            hdf,
            "Results/Steady/Output/Geometry Info/Cross Section Attributes",
            _xs_attrs(),
        )

    # No steady_profile_names -> envelope (column-wise) max across both profiles.
    result = HdfChannelCapacity.extract_max_wse(hdf_path, profile_names=["BLE"])

    assert result["BLE"].tolist() == [30.0, 31.0, 32.0]


def test_segment_channel_uses_length_weighting_not_count_mean() -> None:
    # Three XS in a single 0.25-mi segment with UNEQUAL channel lengths.
    #   count-mean of [4, 4, 7]            = 5.0  -> floor 5
    #   length-weighted by [100, 100, 1000] = 6.5 -> floor 6
    # Equal-length fixtures cannot distinguish these; this one does.
    capacity_df = pd.DataFrame({
        "River": ["R"] * 3,
        "Reach": ["A"] * 3,
        "RS": ["300", "200", "100"],
        "Len Channel": [100.0, 100.0, 1000.0],
        "capacity_level": [4, 4, 7],
        "capacity_category": [LEVEL_TO_CATEGORY[4], LEVEL_TO_CATEGORY[4], LEVEL_TO_CATEGORY[7]],
    })

    segments = HdfChannelCapacity.segment_channel(capacity_df, segment_length=1320.0)

    assert len(segments) == 1
    assert segments.loc[0, "weighted_capacity"] == 6.5
    assert segments.loc[0, "capacity_level"] == 6  # length-weighted floor, not count-mean floor (5)


def test_compare_conditions_marks_missing_segments_incomplete() -> None:
    # Segment present in only one condition cannot be classified Improved/Degraded/
    # No Change -> it is marked Incomplete (outer join, NaN level change).
    existing = {
        "segments": pd.DataFrame({
            "River": ["R", "R"],
            "Reach": ["A", "A"],
            "segment_id": [1, 2],
            "capacity_level": [3, 4],
            "capacity_category": [LEVEL_TO_CATEGORY[3], LEVEL_TO_CATEGORY[4]],
        })
    }
    proposed = {
        "segments": pd.DataFrame({
            "River": ["R", "R"],
            "Reach": ["A", "A"],
            "segment_id": [1, 3],
            "capacity_level": [5, 4],
            "capacity_category": [LEVEL_TO_CATEGORY[5], LEVEL_TO_CATEGORY[4]],
        })
    }

    comparison = HdfChannelCapacity.compare_conditions(existing, proposed)
    by_seg = comparison.set_index("segment_id")["classification"].to_dict()

    assert by_seg[1] == "Improved"      # 5 - 3 = +2
    assert by_seg[2] == "Incomplete"    # existing only
    assert by_seg[3] == "Incomplete"    # proposed only


def test_compare_conditions_segment_classification() -> None:
    existing = {
        "segments": pd.DataFrame({
            "River": ["R", "R", "R"],
            "Reach": ["A", "A", "A"],
            "segment_id": [1, 2, 3],
            "capacity_level": [2, 4, 5],
            "capacity_category": [LEVEL_TO_CATEGORY[2], LEVEL_TO_CATEGORY[4], LEVEL_TO_CATEGORY[5]],
        })
    }
    proposed = {
        "segments": pd.DataFrame({
            "River": ["R", "R", "R"],
            "Reach": ["A", "A", "A"],
            "segment_id": [1, 2, 3],
            "capacity_level": [3, 4, 2],
            "capacity_category": [LEVEL_TO_CATEGORY[3], LEVEL_TO_CATEGORY[4], LEVEL_TO_CATEGORY[2]],
        })
    }

    comparison = HdfChannelCapacity.compare_conditions(existing, proposed)

    assert comparison["level_change"].tolist() == [1, 0, -3]
    assert comparison["classification"].tolist() == ["Improved", "No Change", "Degraded"]
