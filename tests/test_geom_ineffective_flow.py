"""Native Lower Colorado normal L/R and multiple-block record regressions."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ras_commander.geom.GeomCrossSection import GeomCrossSection

FIXTURES = Path(__file__).parent / "fixtures" / "ineffective_flow"
STATIONS = {
    "normal_both": "758717",
    "normal_left_only": "760438",
    "normal_right_only": "727241",
    "multiple_blocks": "753090",
    "normal_left_zero_placeholder": "633500",
    "normal_right_zero_placeholder": "54210",
}


def _copy_fixture(tmp_path, name, newline=b"\r\n"):
    path = tmp_path / "model.g01"
    path.write_bytes((FIXTURES / f"{name}.g01").read_bytes().replace(b"\r\n", newline))
    return path


def _get(path, station):
    return GeomCrossSection.get_ineffective_flow(
        path, "COLORADO RIVER", "Reach-1", station
    )


def _set(path, station, frame, flag, permanent):
    GeomCrossSection.set_ineffective_flow(
        path, "COLORADO RIVER", "Reach-1", station, frame, flag, permanent
    )


@pytest.mark.parametrize("name", STATIONS)
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_native_no_edit_roundtrip_is_byte_exact(tmp_path, name, newline):
    path = _copy_fixture(tmp_path, name, newline)
    # Include legacy encoding bytes, mixed newlines and no terminal newline.
    path.write_bytes(path.read_bytes() + b"Description=legacy \xe9\r\nlast record")
    before = path.read_bytes()
    frame, flag, permanent = _get(str(path), STATIONS[name])
    _set(path, STATIONS[name], frame.copy(), flag, permanent.copy())
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak*"))


@pytest.mark.parametrize(
    ("name", "expected", "flag", "permanent"),
    [
        (
            "normal_both",
            [[np.nan, 4112.36, 412.39], [6161.66, np.nan, 414.32]],
            0,
            [False, False],
        ),
        (
            "normal_left_only",
            [[np.nan, 3022.47, 417.29], [np.nan, np.nan, np.nan]],
            0,
            [False, False],
        ),
        (
            "normal_right_only",
            [[np.nan, np.nan, np.nan], [8284.97, np.nan, 409.38]],
            0,
            [False, False],
        ),
        (
            "multiple_blocks",
            [[9025.91, 11699.48, 412.28], [5585.49, 7533.68, 394.92]],
            -1,
            [False, True],
        ),
    ],
)
def test_native_slots_and_flags(tmp_path, name, expected, flag, permanent):
    path = _copy_fixture(tmp_path, name)
    frame, actual_flag, actual_permanent = _get(path, STATIONS[name])
    assert list(frame.columns) == ["left_station", "right_station", "elevation"]
    np.testing.assert_equal(frame.to_numpy(), expected)
    assert (actual_flag, actual_permanent) == (flag, permanent)


def test_permanent_only_edit_preserves_native_numeric_record(tmp_path):
    path = _copy_fixture(tmp_path, "normal_both")
    before = path.read_bytes()
    frame, flag, permanent = _get(path, "758717")
    permanent[1] = True
    _set(path, "758717", frame, flag, permanent)
    assert path.read_bytes() == before.replace(b"       F       F", b"       F       T")
    assert list(tmp_path.glob("*.bak*"))
    assert _get(path, "758717")[2] == [False, True]


@pytest.mark.parametrize(
    "name", ["normal_both", "normal_left_only", "normal_right_only"]
)
def test_normal_station_elevation_edits_retain_blank_slots(tmp_path, name):
    path = _copy_fixture(tmp_path, name)
    frame, flag, permanent = _get(path, STATIONS[name])
    before_blanks = frame.isna()
    defined = frame.elevation.notna()
    frame.loc[defined, "elevation"] += 1.25
    _set(path, STATIONS[name], frame, None, permanent)
    result, actual_flag, actual_permanent = _get(path, STATIONS[name])
    pd.testing.assert_frame_equal(result, frame)
    pd.testing.assert_frame_equal(result.isna(), before_blanks)
    assert (actual_flag, actual_permanent) == (flag, permanent)
    assert b"nan" not in path.read_bytes().lower()


@pytest.mark.parametrize(
    "name", ["normal_left_zero_placeholder", "normal_right_zero_placeholder"]
)
def test_normal_zero_placeholders_are_retained_on_edits(tmp_path, name):
    path = _copy_fixture(tmp_path, name)
    frame, flag, permanent = _get(path, STATIONS[name])
    assert frame.loc[0, "left_station"] == 0
    assert frame.loc[1, "right_station"] == 0
    defined = frame.elevation.notna()
    frame.loc[defined, "elevation"] += 1
    _set(path, STATIONS[name], frame, flag, permanent)
    result, _, _ = _get(path, STATIONS[name])
    pd.testing.assert_frame_equal(result, frame)
    assert result.loc[0, "left_station"] == result.loc[1, "right_station"] == 0


@pytest.mark.parametrize(
    "name", ["normal_left_zero_placeholder", "normal_right_zero_placeholder"]
)
def test_zero_placeholder_partial_activation_pair_rejected(tmp_path, name):
    path = _copy_fixture(tmp_path, name)
    before = path.read_bytes()
    frame, flag, permanent = _get(path, STATIONS[name])
    frame.loc[frame.elevation.notna(), "elevation"] = np.nan
    with pytest.raises(ValueError):
        _set(path, STATIONS[name], frame, flag, permanent)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak*"))


@pytest.mark.parametrize("new_count", [0, 1, 4, 8])
def test_multiple_block_resize_preserves_following_records(tmp_path, new_count):
    path = _copy_fixture(tmp_path, "multiple_blocks")
    frame = pd.DataFrame(
        [[n * 10, n * 10 + 5, 400 + n] for n in range(new_count)],
        columns=["left_station", "right_station", "elevation"],
        dtype=float,
    )
    flags = [bool(n % 2) for n in range(new_count)]
    _set(path, "753090", frame, -1, flags)
    result, flag, permanent = _get(path, "753090")
    pd.testing.assert_frame_equal(result, frame)
    assert (flag, permanent) == (-1, flags)
    assert path.read_bytes().endswith(b"Bank Sta=1,2\r\n")
    assert path.read_bytes().count(b"Permanent Ineff=") == 1


@pytest.mark.parametrize(
    "invalid",
    ["partial", "flags_short", "flags_type", "format", "infinity", "overflow"],
)
def test_invalid_edits_leave_geometry_and_backup_untouched(tmp_path, invalid):
    path = _copy_fixture(tmp_path, "normal_both")
    before = path.read_bytes()
    frame, flag, permanent = _get(path, "758717")
    if invalid == "partial":
        frame.loc[0, "elevation"] = np.nan
    elif invalid == "flags_short":
        permanent = [False]
    elif invalid == "flags_type":
        permanent = ["F", "T"]
    elif invalid == "format":
        flag = -1
    elif invalid == "infinity":
        frame.loc[0, "elevation"] = np.inf
    else:
        frame.loc[0, "elevation"] = 123456789
    with pytest.raises(ValueError):
        _set(path, "758717", frame, flag, permanent)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.bak*"))


@pytest.mark.parametrize("invalid", ["partial", "flags", "truncated_block"])
def test_malformed_native_records_fail_without_mutation(tmp_path, invalid):
    name = "multiple_blocks" if invalid == "truncated_block" else "normal_both"
    path = _copy_fixture(tmp_path, name)
    raw = path.read_bytes()
    if invalid == "partial":
        raw = raw.replace(b"  412.39", b"        ")
    elif invalid == "flags":
        raw = raw.replace(b"       F       F", b"       F       X")
    else:
        raw = raw.replace(
            b" 9025.9111699.48  412.28 5585.49 7533.68  394.92", b" 9025.9111699.48"
        )
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        _get(path, STATIONS[name])
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob("*.bak*"))


@pytest.mark.parametrize(
    "token", [b"  BAD123", b"12.3-4.5", b"garbage!", b"     nan", b"     inf"]
)
def test_malformed_scalar_slot_is_never_salvaged(tmp_path, token):
    path = _copy_fixture(tmp_path, "normal_both")
    raw = path.read_bytes().replace(b"  412.39", token)
    path.write_bytes(raw)
    with pytest.raises(ValueError):
        _get(path, "758717")
    with pytest.raises(ValueError):
        _set(
            path,
            "758717",
            pd.DataFrame(
                [[np.nan, 4112.36, 412.39], [6161.66, np.nan, 414.32]],
                columns=["left_station", "right_station", "elevation"],
            ),
            0,
            [False, False],
        )
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob("*.bak*"))
