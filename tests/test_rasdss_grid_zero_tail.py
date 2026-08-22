"""Coverage for non-destructive DSS grid zero-tail derivatives."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import sys
import textwrap
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from ras_commander import RasDss, RasUtils

FAMILY = "/SHG/TEST/PRECIPITATION///C04-SOURCE/"
RECORDS = [
    "/SHG/TEST/PRECIPITATION/01JAN2020:0000/01JAN2020:0100/C04-SOURCE/",
    "/SHG/TEST/PRECIPITATION/01JAN2020:0100/01JAN2020:0200/C04-SOURCE/",
]


def _fake_grid(
    data: np.ndarray,
    start: str = "01JAN2020:0000",
    end: str = "01JAN2020:0100",
) -> dict:
    frame = np.asarray(data, dtype=np.float32)
    missing = int((~np.isfinite(frame)).sum())
    return {
        "data": frame,
        "shape": frame.shape,
        "units": "MM",
        "data_type": "PER-CUM",
        "grid_type": "albers",
        "crs": "SHG WKT",
        "cell_size": 1000.0,
        "start_time": RasDss._parse_grid_dss_datetime(start),
        "end_time": RasDss._parse_grid_dss_datetime(end),
        "metadata": {
            "grid_class": "hec.heclib.grid.AlbersInfo",
            "grid_type_code": 420,
            "data_type_code": 1,
            "shape": frame.shape,
            "number_of_cells_x": frame.shape[1],
            "number_of_cells_y": frame.shape[0],
            "lower_left_cell": (259, 1024),
            "origin": (259000.0, 1024000.0),
            "number_missing": missing,
            "nodata_value": -3.4028234663852886e38,
            "projection": {
                "x_coord_cell_zero": 0.0,
                "y_coord_cell_zero": 0.0,
                "datum_code": 2,
                "units": "Meter",
                "standard_parallel_1": 29.5,
                "standard_parallel_2": 45.5,
                "central_meridian": -96.0,
                "latitude_of_origin": 23.0,
                "false_easting": 0.0,
                "false_northing": 0.0,
            },
            "compression": {
                "method": 26,
                "base": 0.0,
                "scale_factor": 100.0,
                "element_size": 0,
            },
            "timing": {
                "start": start,
                "end": end,
                "period": "",
            },
        },
    }


def _install_fake_family(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    grids: list[dict],
    catalog: pd.DataFrame | None = None,
) -> None:
    source_catalog = (
        catalog if catalog is not None else pd.DataFrame({"pathname": RECORDS})
    )
    for grid, record_path in zip(grids, source_catalog["pathname"].astype(str)):
        _, parts = RasDss._split_dss_pathname(record_path)
        grid["start_time"] = RasDss._parse_grid_dss_datetime(parts[3])
        grid["end_time"] = RasDss._parse_grid_dss_datetime(parts[4])
        grid["metadata"]["timing"] = {
            "start": parts[3],
            "end": parts[4],
            "period": "",
        }
    by_path = dict(zip(RECORDS, grids))

    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda path: source_catalog),
    )
    monkeypatch.setattr(
        RasDss,
        "read_grid",
        staticmethod(lambda _path, pathname: by_path[pathname]),
    )
    monkeypatch.setattr(RasDss, "get_file_version", staticmethod(lambda _path: 7))
    monkeypatch.setattr(RasDss, "_close_dss_file", staticmethod(lambda _path: None))


def _install_fake_derivative_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    source: Path,
    grids: list[dict] | None = None,
    records: list[str] | None = None,
) -> dict:
    """Install a deterministic streaming writer/readback pipeline."""
    source = RasUtils.safe_resolve(source)
    records = list(records or RECORDS)
    grids = grids or [
        _fake_grid(np.array([[1.0, np.nan], [2.0, 3.0]])),
        _fake_grid(
            np.array([[4.0, np.nan], [5.0, 6.0]]),
            "01JAN2020:0100",
            "01JAN2020:0200",
        ),
    ]
    for grid, record_path in zip(grids, records):
        _, parts = RasDss._split_dss_pathname(record_path)
        grid["start_time"] = RasDss._parse_grid_dss_datetime(parts[3])
        grid["end_time"] = RasDss._parse_grid_dss_datetime(parts[4])
        grid["metadata"]["timing"] = {
            "start": parts[3],
            "end": parts[4],
            "period": "",
        }

    source_grids = dict(zip(records, grids))
    state = {
        "temporary": None,
        "written": [],
        "output_grids": {},
        "write_shapes": [],
        "write_pathnames": [],
        "source_reads": 0,
        "temp_reads": 0,
        "catalog_override": None,
        "writer_return_override": None,
        "readback_mutator": None,
        "source_read_hook": None,
        "source_version": 7,
        "temporary_version": 7,
        "source_grids": source_grids,
        "catalog_paths": [],
        "read_paths": [],
        "create_paths": [],
        "close_paths": [],
    }

    def fake_catalog(path):
        state["catalog_paths"].append(Path(path))
        if Path(path) == source:
            return pd.DataFrame({"pathname": records})
        paths = state["catalog_override"]
        if paths is None:
            paths = state["written"]
        return pd.DataFrame({"pathname": list(paths)})

    def fake_read(path, pathname):
        state["read_paths"].append(Path(path))
        if Path(path) == source:
            state["source_reads"] += 1
            hook = state["source_read_hook"]
            if hook is not None:
                hook(state["source_reads"])
            return deepcopy(source_grids[pathname])
        state["temp_reads"] += 1
        grid = deepcopy(state["output_grids"][pathname])
        mutator = state["readback_mutator"]
        if mutator is not None:
            mutated = mutator(grid, pathname, state["temp_reads"])
            if mutated is not None:
                grid = mutated
        return grid

    def fake_version(path):
        if Path(path) == source:
            return state["source_version"]
        return state["temporary_version"]

    def fake_create(path, _version):
        state["temporary"] = Path(path)
        state["create_paths"].append(Path(path))
        Path(path).write_bytes(b"empty")

    def fake_close(path):
        state["close_paths"].append(Path(path))

    def fake_write(dss_file, pathname, data, times, grid_info, **_kwargs):
        frame_data = np.asarray(data, dtype=np.float32)
        state["write_shapes"].append(frame_data.shape)
        state["write_pathnames"].append(pathname)
        start = pd.Timestamp(times[0])
        end = pd.Timestamp(times[1])
        _, parts = RasDss._split_dss_pathname(pathname)
        parts[3] = RasDss._format_grid_dss_datetime(start)
        parts[4] = RasDss._format_grid_dss_datetime(end)
        returned_path = RasDss._build_dss_pathname("/", parts)
        parts[4] = RasDss._format_native_grid_end_datetime(end)
        catalog_path = RasDss._build_dss_pathname("/", parts)

        output_grid = deepcopy(grids[0])
        output_frame = frame_data[0].copy()
        output_grid["data"] = output_frame
        output_grid["shape"] = output_frame.shape
        output_grid["start_time"] = start
        output_grid["end_time"] = end
        output_grid["metadata"]["shape"] = output_frame.shape
        output_grid["metadata"]["number_of_cells_x"] = output_frame.shape[1]
        output_grid["metadata"]["number_of_cells_y"] = output_frame.shape[0]
        output_grid["metadata"]["number_missing"] = int(
            (~np.isfinite(output_frame)).sum()
        )
        lower_left = (
            int(grid_info["lower_left_cell_x"]),
            int(grid_info["lower_left_cell_y"]),
        )
        output_grid["metadata"]["lower_left_cell"] = lower_left
        projection = output_grid["metadata"]["projection"]
        output_grid["metadata"]["origin"] = (
            projection["x_coord_cell_zero"]
            + lower_left[0] * output_grid["cell_size"],
            projection["y_coord_cell_zero"]
            + lower_left[1] * output_grid["cell_size"],
        )
        output_grid["metadata"]["timing"] = {
            "start": parts[3],
            "end": parts[4],
            "period": "",
        }
        state["written"].append(catalog_path)
        state["output_grids"][catalog_path] = output_grid
        Path(dss_file).write_bytes(b"complete derivative")
        override = state["writer_return_override"]
        return override(returned_path) if override is not None else [returned_path]

    monkeypatch.setattr(RasDss, "get_catalog", staticmethod(fake_catalog))
    monkeypatch.setattr(RasDss, "read_grid", staticmethod(fake_read))
    monkeypatch.setattr(RasDss, "get_file_version", staticmethod(fake_version))
    monkeypatch.setattr(RasDss, "_create_empty_dss", staticmethod(fake_create))
    monkeypatch.setattr(RasDss, "_close_dss_file", staticmethod(fake_close))
    monkeypatch.setattr(
        RasDss,
        "write_grid_timeseries",
        staticmethod(fake_write),
    )
    return state


def test_public_signature_is_additive_and_keyword_scoped() -> None:
    signature = inspect.signature(RasDss.copy_grid_with_zero_tail)

    assert list(signature.parameters) == [
        "source_dss",
        "output_dss",
        "pathname",
        "tail_intervals",
        "time_shift_minutes",
        "output_pathname",
        "x_shift",
        "y_shift",
        "overwrite",
    ]
    for name in (
        "time_shift_minutes",
        "output_pathname",
        "x_shift",
        "y_shift",
        "overwrite",
    ):
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tail_intervals": True}, "positive integer"),
        ({"tail_intervals": 0}, "positive integer"),
        ({"tail_intervals": 1.0}, "positive integer"),
        ({"tail_intervals": 1, "time_shift_minutes": True}, "integer"),
        ({"tail_intervals": 1, "time_shift_minutes": 1.5}, "integer"),
        ({"tail_intervals": 1, "x_shift": float("nan")}, "finite number"),
        ({"tail_intervals": 1, "x_shift": 10**10000}, "finite number"),
        ({"tail_intervals": 1, "y_shift": True}, "finite number"),
        ({"tail_intervals": 1, "overwrite": 1}, "boolean"),
        (
            {"tail_intervals": 1, "output_pathname": ""},
            "start and end",
        ),
    ],
)
def test_scalar_validation_fails_before_catalog_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kwargs: dict,
    message: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda _path: pytest.fail("catalog must not be opened")),
    )

    with pytest.raises(ValueError, match=message):
        RasDss.copy_grid_with_zero_tail(
            source,
            tmp_path / "output.dss",
            FAMILY,
            **kwargs,
        )


def test_source_identity_and_existing_output_are_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source bytes")

    with pytest.raises(ValueError, match="must differ"):
        RasDss.copy_grid_with_zero_tail(source, source, FAMILY, 1)

    output = tmp_path / "existing.dss"
    output.write_bytes(b"old derivative")
    with pytest.raises(FileExistsError, match="already exists"):
        RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)
    assert output.read_bytes() == b"old derivative"


def test_existing_output_directory_fails_before_catalog_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    output.mkdir()
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda _path: pytest.fail("catalog must not be opened")),
    )

    with pytest.raises(IsADirectoryError, match="not a file"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )


@pytest.mark.parametrize(
    ("pathnames", "message"),
    [
        (["/SHG/OTHER/PRECIP/01JAN2020:0000/01JAN2020:0100/X/"], "No grid"),
        (
            [RECORDS[0], RECORDS[0].replace("TEST", "test")],
            "ambiguous",
        ),
        (
            [
                RECORDS[0],
                RECORDS[1].replace("0200", "0230"),
            ],
            "uniform interval",
        ),
        (
            [
                RECORDS[0],
                RECORDS[1].replace("0100/01JAN", "0200/01JAN").replace(
                    "0200/C04", "0300/C04"
                ),
            ],
            "not contiguous",
        ),
        ([RECORDS[0], RECORDS[0]], "ambiguous"),
        (
            [
                RECORDS[0].replace(":0000", ":000030"),
                RECORDS[1].replace(":0100", ":010030").replace(
                    ":0200", ":020030"
                ),
            ],
            "invalid time window",
        ),
    ],
)
def test_family_selection_rejects_zero_ambiguous_and_bad_timing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pathnames: list[str],
    message: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda _path: pd.DataFrame({"pathname": pathnames})),
    )
    monkeypatch.setattr(
        RasDss,
        "read_grid",
        staticmethod(lambda *_args: pytest.fail("bad families must not be read")),
    )
    monkeypatch.setattr(RasDss, "_close_dss_file", staticmethod(lambda _path: None))
    output = tmp_path / "output.dss"

    with pytest.raises(ValueError, match=message):
        RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["metadata", "compression", "nodata"])
def test_family_validation_rejects_metadata_or_nodata_drift_before_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    first = _fake_grid(np.array([[1.0, np.nan], [2.0, 3.0]]))
    second = _fake_grid(np.array([[4.0, np.nan], [5.0, 6.0]]))
    if failure == "metadata":
        second["cell_size"] = 2000.0
    elif failure == "compression":
        second["metadata"]["compression"]["method"] = 99
    else:
        second["data"] = np.array([[np.nan, 4.0], [5.0, 6.0]])
    _install_fake_family(monkeypatch, source, [first, second])
    output = tmp_path / "output.dss"
    output.write_bytes(b"old derivative")

    with pytest.raises(ValueError, match="inconsistent|NoData"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )
    assert output.read_bytes() == b"old derivative"


def test_payload_derived_compression_element_size_may_vary() -> None:
    first = _fake_grid(np.array([[1.0, np.nan], [2.0, 3.0]]))
    second = _fake_grid(
        np.array([[4.0, np.nan], [5.0, 6.0]]),
        "01JAN2020:0100",
        "01JAN2020:0200",
    )
    second["metadata"]["compression"]["element_size"] = 31
    records = [
        (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-01 01:00"), RECORDS[0]),
        (
            pd.Timestamp("2020-01-01 01:00"),
            pd.Timestamp("2020-01-01 02:00"),
            RECORDS[1],
        ),
    ]

    mask = RasDss._validate_grid_family_metadata([first, second], records)

    np.testing.assert_array_equal(
        mask,
        np.array([[False, True], [False, False]]),
    )


def test_non_whole_cell_translation_is_strict_and_creates_no_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    grids = [
        _fake_grid(np.array([[1.0, np.nan], [2.0, 3.0]])),
        _fake_grid(
            np.array([[4.0, np.nan], [5.0, 6.0]]),
            "01JAN2020:0100",
            "01JAN2020:0200",
        ),
    ]
    _install_fake_family(monkeypatch, source, grids)
    output = tmp_path / "output.dss"

    with pytest.raises(ValueError, match="exact whole grid-cell"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            x_shift=1000.000000001,
        )
    assert not output.exists()


def test_writer_failure_cleans_temp_and_preserves_existing_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    grids = [
        _fake_grid(np.array([[1.0, np.nan], [2.0, 3.0]])),
        _fake_grid(
            np.array([[4.0, np.nan], [5.0, 6.0]]),
            "01JAN2020:0100",
            "01JAN2020:0200",
        ),
    ]
    _install_fake_family(monkeypatch, source, grids)
    monkeypatch.setattr(RasDss, "get_file_version", staticmethod(lambda _path: 7))
    monkeypatch.setattr(
        RasDss,
        "_create_empty_dss",
        staticmethod(lambda path, _version: Path(path).write_bytes(b"empty")),
    )
    def injected_temp_close_failure(path):
        if Path(path).name.startswith(".output."):
            raise RuntimeError("injected cleanup close failure")

    monkeypatch.setattr(
        RasDss,
        "_close_dss_file",
        staticmethod(injected_temp_close_failure),
    )

    def fail_after_partial_write(dss_file, **_kwargs):
        Path(dss_file).write_bytes(b"partial derivative")
        raise RuntimeError("injected Java write failure")

    monkeypatch.setattr(
        RasDss,
        "write_grid_timeseries",
        staticmethod(fail_after_partial_write),
    )
    output = tmp_path / "output.dss"
    output.write_bytes(b"old derivative")

    with pytest.raises(RuntimeError, match="injected Java write failure"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )

    assert output.read_bytes() == b"old derivative"
    assert list(tmp_path.glob(".output.*.tmp.dss")) == []
    assert "injected cleanup close failure" in caplog.text


def test_destination_appearing_during_build_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    _install_fake_derivative_pipeline(monkeypatch, source)
    real_link = os.link

    def racing_link(temporary, destination):
        output.write_bytes(b"competing destination")
        return real_link(temporary, destination)

    monkeypatch.setattr(os, "link", racing_link)

    with pytest.raises(FileExistsError, match="appeared while"):
        RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)

    assert output.read_bytes() == b"competing destination"
    assert list(tmp_path.glob(".output.*.tmp.dss")) == []


def test_output_prefix_is_canonicalized_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    state = _install_fake_derivative_pipeline(monkeypatch, source)

    result = RasDss.copy_grid_with_zero_tail(
        source,
        output,
        FAMILY,
        1,
        output_pathname="//SHG/TEST/PRECIPITATION///C04-SOURCE/",
    )

    assert set(state["write_pathnames"]) == {FAMILY}
    assert result["output_pathname"] == FAMILY
    assert result["shifted_pathnames"] == []


def test_output_none_preserves_caller_family_casing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    state = _install_fake_derivative_pipeline(monkeypatch, source)
    selector = "//shg/test/precipitation///c04-source/"

    result = RasDss.copy_grid_with_zero_tail(source, output, selector, 1)

    expected_family = "/shg/test/precipitation///c04-source/"
    assert result["output_pathname"] == expected_family
    assert set(state["write_pathnames"]) == {expected_family}
    assert result["shifted_pathnames"] == result["written_source_pathnames"]


def test_valid_2400_follows_native_record_end_spelling(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    records = [
        "/SHG/TEST/PRECIPITATION/01JAN2020:2300/01JAN2020:2400/C04-SOURCE/",
        "/SHG/TEST/PRECIPITATION/02JAN2020:0000/02JAN2020:0100/C04-SOURCE/",
    ]
    _install_fake_derivative_pipeline(monkeypatch, source, records=records)

    result = RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)

    native_first = (
        "/SHG/TEST/PRECIPITATION/01JAN2020:2300/"
        "01JAN2020:2400/C04-SOURCE/"
    )
    assert result["written_source_pathnames"][0] == native_first
    assert result["shifted_pathnames"] == []


def test_raw_source_timing_mismatch_fails_before_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    state = _install_fake_derivative_pipeline(monkeypatch, source)
    state["source_grids"][RECORDS[1]]["metadata"]["timing"]["start"] = (
        "01JAN1999:0100"
    )

    with pytest.raises(ValueError, match="raw timing metadata disagrees"):
        RasDss.copy_grid_with_zero_tail(source, tmp_path / "output.dss", FAMILY, 1)


def test_fractional_shift_and_java_cell_overflow_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    _install_fake_derivative_pipeline(monkeypatch, source)

    with pytest.raises(ValueError, match="exact whole grid-cell"):
        RasDss.copy_grid_with_zero_tail(
            source,
            tmp_path / "fraction.dss",
            FAMILY,
            1,
            x_shift=Fraction(1, 2),
        )
    with pytest.raises(ValueError, match="Java int32 bounds"):
        RasDss.copy_grid_with_zero_tail(
            source,
            tmp_path / "overflow.dss",
            FAMILY,
            1,
            x_shift=(2**31) * 1000,
        )


def test_time_shift_overflow_is_value_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    _install_fake_derivative_pipeline(monkeypatch, source)

    with pytest.raises(ValueError, match="datetime bounds"):
        RasDss.copy_grid_with_zero_tail(
            source,
            tmp_path / "output.dss",
            FAMILY,
            1,
            time_shift_minutes=2**63,
        )


def test_wrong_self_consistent_writer_and_catalog_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    output.write_bytes(b"old destination")
    state = _install_fake_derivative_pipeline(monkeypatch, source)
    wrong = "/WRONG/FAMILY/GRID/01JAN2020:0000/01JAN2020:0100/X/"
    state["writer_return_override"] = lambda _expected: [wrong]
    state["catalog_override"] = [wrong]

    with pytest.raises(RuntimeError, match="unexpected ordered pathname"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )
    assert output.read_bytes() == b"old destination"


@pytest.mark.parametrize("failure", ["version", "catalog"])
def test_version_and_catalog_mismatch_preserve_destination(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    output.write_bytes(b"old destination")
    state = _install_fake_derivative_pipeline(monkeypatch, source)
    if failure == "version":
        state["temporary_version"] = 6
    else:
        state["catalog_override"] = ["/WRONG/FAMILY/GRID/D/E/F/"]

    with pytest.raises(RuntimeError, match="major version|expected pathnames"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )
    assert output.read_bytes() == b"old destination"


@pytest.mark.parametrize("failure", ["data", "metadata", "timing", "tail"])
def test_corrupt_temporary_readback_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    output.write_bytes(b"old destination")
    state = _install_fake_derivative_pipeline(monkeypatch, source)

    def mutate(grid, _pathname, read_number):
        is_source_record = read_number <= len(RECORDS)
        if failure == "data" and read_number == 1:
            grid["data"][0, 0] += np.float32(1.0)
        elif failure == "metadata" and read_number == 1:
            grid["metadata"]["lower_left_cell"] = (999, 1024)
        elif failure == "timing" and read_number == 1:
            grid["metadata"]["timing"]["start"] = "WRONG"
        elif failure == "tail" and not is_source_record:
            grid["data"][0, 0] = np.float32(1.0)
        return grid

    state["readback_mutator"] = mutate
    with pytest.raises((ValueError, RuntimeError)):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )
    assert output.read_bytes() == b"old destination"


def test_streams_one_frame_per_write_and_returns_source_sha(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "output.dss"
    state = _install_fake_derivative_pipeline(monkeypatch, source)
    monkeypatch.setattr(np, "stack", lambda *_a, **_k: pytest.fail("no stack"))
    monkeypatch.setattr(np, "repeat", lambda *_a, **_k: pytest.fail("no repeat"))
    monkeypatch.setattr(
        np,
        "concatenate",
        lambda *_a, **_k: pytest.fail("no concatenate"),
    )

    result = RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 3)

    assert state["write_shapes"] == [(1, 2, 2)] * 5
    assert state["source_reads"] == 4
    assert state["temp_reads"] == 5
    assert result["source_sha256"] == source_sha


@pytest.mark.parametrize("source_read_number", [2, 4])
def test_source_snapshot_change_aborts_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source_read_number: int,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    state = _install_fake_derivative_pipeline(monkeypatch, source)

    def mutate_source(read_number):
        if read_number == source_read_number:
            source.write_bytes(b"changed source")

    state["source_read_hook"] = mutate_source
    with pytest.raises(RuntimeError, match="Source DSS changed"):
        RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)
    assert not output.exists()
    assert list(tmp_path.glob(".output.*.tmp.dss")) == []


def test_atomic_no_clobber_requires_supported_hardlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "output.dss"
    _install_fake_derivative_pipeline(monkeypatch, source)
    monkeypatch.setattr(
        os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(50, "hard links unsupported")
        ),
    )

    with pytest.raises(OSError, match="requires hard-link support"):
        RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)
    assert not output.exists()
    assert list(tmp_path.glob(".output.*.tmp.dss")) == []


def test_output_symlink_is_rejected_before_catalog_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    target = tmp_path / "target.dss"
    target.write_bytes(b"target")
    output = tmp_path / "output.dss"
    try:
        output.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda _path: pytest.fail("catalog must not be opened")),
    )

    with pytest.raises(ValueError, match="symlink, junction, or reparse"):
        RasDss.copy_grid_with_zero_tail(
            source,
            output,
            FAMILY,
            1,
            overwrite=True,
        )
    assert target.read_bytes() == b"target"


def test_output_safe_resolves_parent_and_publishes_lexical_final_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    output = tmp_path / "lexical-output.dss"
    _install_fake_derivative_pipeline(monkeypatch, source)
    original_safe_resolve = RasUtils.safe_resolve
    safe_resolve_calls = []

    def tracked_safe_resolve(path):
        safe_resolve_calls.append(Path(path))
        return original_safe_resolve(Path(path))

    published = {}
    original_replace = os.replace

    def tracked_replace(temporary, destination):
        published["destination"] = Path(destination)
        return original_replace(temporary, destination)

    monkeypatch.setattr(
        RasUtils,
        "safe_resolve",
        staticmethod(tracked_safe_resolve),
    )
    monkeypatch.setattr(os, "replace", tracked_replace)

    result = RasDss.copy_grid_with_zero_tail(
        source,
        output,
        FAMILY,
        1,
        overwrite=True,
    )

    assert output.parent in safe_resolve_calls
    assert output not in safe_resolve_calls
    assert published["destination"] == output
    assert result["output_dss"] == str(output)


def test_source_phase_close_failure_does_not_mask_primary_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    close_count = 0

    def close_source(_path):
        nonlocal close_count
        close_count += 1
        if close_count == 2:
            raise RuntimeError("injected source close failure")

    monkeypatch.setattr(RasDss, "_close_dss_file", staticmethod(close_source))
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(
            lambda _path: (_ for _ in ()).throw(
                RuntimeError("injected catalog failure")
            )
        ),
    )

    with pytest.raises(RuntimeError, match="injected catalog failure"):
        RasDss.copy_grid_with_zero_tail(source, tmp_path / "output.dss", FAMILY, 1)
    assert close_count == 2
    assert "injected source close failure" in caplog.text


def test_java_long_form_2400_raw_timing_is_narrow() -> None:
    assert RasDss._parse_grid_raw_datetime("1 January 2020, 24:00") == pd.Timestamp(
        "2020-01-02 00:00"
    )
    for minute in (1, 30, 59):
        assert (
            RasDss._parse_grid_raw_datetime(
                f"1 January 2020, 24:{minute:02d}"
            )
            is None
        )


def test_mapped_drive_form_reaches_all_stages_and_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = Path(__file__).absolute().parents[1]
    if os.name != "nt" or not str(repo_root.resolve()).startswith("\\\\"):
        pytest.skip("test requires a mapped Windows repository drive")
    test_dir = repo_root / f".c04-mapped-{uuid4().hex}"
    test_dir.mkdir()
    source = test_dir / "source.dss"
    output = test_dir / "output.dss"
    source.write_bytes(b"source")
    try:
        state = _install_fake_derivative_pipeline(monkeypatch, source)
        result = RasDss.copy_grid_with_zero_tail(source, output, FAMILY, 1)

        assert result["source_dss"] == str(source)
        assert result["output_dss"] == str(output)
        observed = (
            state["catalog_paths"]
            + state["read_paths"]
            + state["create_paths"]
            + state["close_paths"]
        )
        assert observed
        assert all(path.drive == source.drive for path in observed)
        assert all(not str(path).startswith("\\\\") for path in observed)
    finally:
        for child in test_dir.iterdir():
            child.unlink()
        test_dir.rmdir()


@pytest.mark.parametrize(
    "selector",
    [
        "/SHG/TEST/PRECIPITATION/01JAN2020:0000//C04-SOURCE/",
        "/SH*/TEST/PRECIPITATION///C04-SOURCE/",
    ],
)
def test_invalid_family_selector_fails_before_catalog(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selector: str,
) -> None:
    source = tmp_path / "source.dss"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        RasDss,
        "get_catalog",
        staticmethod(lambda _path: pytest.fail("catalog must not be opened")),
    )

    with pytest.raises(ValueError):
        RasDss.copy_grid_with_zero_tail(source, tmp_path / "output.dss", selector, 1)


def _run_bridge_script(script: str, *args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
    )


def _skip_if_bridge_unavailable(completed: subprocess.CompletedProcess[str]) -> None:
    if completed.returncode == 77 and "C04_BRIDGE_UNAVAILABLE:" in completed.stdout:
        pytest.skip(completed.stdout.strip())


def _assert_clean_native_output(completed: subprocess.CompletedProcess[str]) -> None:
    diagnostic = (completed.stdout + completed.stderr).casefold()
    assert "access violation" not in diagnostic
    assert "fatal exception" not in diagnostic


@pytest.mark.integration
@pytest.mark.parametrize("dss_version", [6, 7])
def test_real_grid_derivative_preserves_version_source_and_exact_content(
    tmp_path: Path,
    dss_version: int,
) -> None:
    """Use a deterministic Java grid because no grid DSS fixture is tracked."""
    source = tmp_path / f"source-v{dss_version}.dss"
    output = tmp_path / f"derivative-v{dss_version}.dss"
    linked_output = tmp_path / f"linked-v{dss_version}.dss"
    result_json = tmp_path / f"result-v{dss_version}.json"
    output.write_bytes(b"old destination that must be atomically replaced")

    prepare_script = """
        import sys
        from datetime import datetime
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C04_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        source = Path(sys.argv[1])
        version = int(sys.argv[2])
        RasDss.write_timeseries(
            source,
            "/UNRELATED/GAGE/FLOW//1HOUR/C04/",
            pd.date_range("2020-01-01", periods=2, freq="h"),
            [10.0, 20.0],
            dss_version=version,
        )
        grid_info = {
            "cell_size": 1000,
            "origin": (259000, 1024000),
            "crs": "SHG",
            "units": "MM",
            "data_type": "PER-CUM",
            "compression": "PRECIP_2_BYTE",
        }
        if version == 6:
            # Monolith's V6 setter exposes base/scale in the opposite order.
            grid_info.update(
                compression_base=100.0,
                compression_scale_factor=0.0,
            )
        RasDss.write_grid_timeseries(
            source,
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            np.array(
                [
                    [[1.0, np.nan, 2.0], [3.0, 4.0, 5.0]],
                    [[6.0, np.nan, 7.0], [8.0, 9.0, 10.0]],
                ],
                dtype=np.float32,
            ),
            [
                datetime(2020, 1, 1, 0),
                datetime(2020, 1, 1, 1),
                datetime(2020, 1, 1, 2),
            ],
            grid_info,
        )
        assert RasDss.get_file_version(source) == version
    """
    prepared = _run_bridge_script(prepare_script, source, dss_version)
    _skip_if_bridge_unavailable(prepared)
    _assert_clean_native_output(prepared)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()

    transform_script = """
        import json
        import sys
        from pathlib import Path

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C04_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        overwrite_result = RasDss.copy_grid_with_zero_tail(
            Path(sys.argv[1]),
            Path(sys.argv[2]),
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            2,
            time_shift_minutes=-300,
            output_pathname="/SHG/TEST/PRECIPITATION///C04-DERIVATIVE/",
            x_shift=2000,
            y_shift=3000,
            overwrite=True,
        )
        linked_result = RasDss.copy_grid_with_zero_tail(
            Path(sys.argv[1]),
            Path(sys.argv[3]),
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            2,
            time_shift_minutes=-300,
            output_pathname="/SHG/TEST/PRECIPITATION///C04-DERIVATIVE/",
            x_shift=2000,
            y_shift=3000,
        )
        Path(sys.argv[4]).write_text(
            json.dumps({"overwrite": overwrite_result, "link": linked_result}),
            encoding="utf-8",
        )
    """
    transformed = _run_bridge_script(
        transform_script,
        source,
        output,
        linked_output,
        result_json,
    )
    _skip_if_bridge_unavailable(transformed)
    _assert_clean_native_output(transformed)
    assert transformed.returncode == 0, transformed.stdout + transformed.stderr
    results = json.loads(result_json.read_text(encoding="utf-8"))
    result = results["overwrite"]
    linked_result = results["link"]
    assert result["dss_version"] == dss_version
    assert result["source_record_count"] == 2
    assert result["appended_record_count"] == 2
    assert result["interval_minutes"] == 60
    assert result["output_lower_left_cell"] == [261, 1027]
    assert result["source_start"] == "2020-01-01T00:00:00"
    assert result["source_end"] == "2020-01-01T02:00:00"
    assert result["output_start"] == "2019-12-31T19:00:00"
    assert result["padded_end"] == "2019-12-31T23:00:00"
    assert result["source_sha256"] == source_sha
    assert linked_result["source_sha256"] == source_sha
    assert linked_result["output_dss"] == str(linked_output)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert output.read_bytes() != b"old destination that must be atomically replaced"
    assert linked_output.is_file()
    assert list(tmp_path.glob(f".{output.stem}.*.tmp.dss")) == []
    assert list(tmp_path.glob(f".{linked_output.stem}.*.tmp.dss")) == []

    verify_script = """
        import sys
        from pathlib import Path

        import numpy as np

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C04_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        source = Path(sys.argv[1])
        outputs = [Path(sys.argv[2]), Path(sys.argv[4])]
        version = int(sys.argv[3])
        expected = [
            "/SHG/TEST/PRECIPITATION/31DEC2019:1900/31DEC2019:2000/C04-DERIVATIVE/",
            "/SHG/TEST/PRECIPITATION/31DEC2019:2000/31DEC2019:2100/C04-DERIVATIVE/",
            "/SHG/TEST/PRECIPITATION/31DEC2019:2100/31DEC2019:2200/C04-DERIVATIVE/",
            "/SHG/TEST/PRECIPITATION/31DEC2019:2200/31DEC2019:2300/C04-DERIVATIVE/",
        ]
        source_paths = sorted(
            value
            for value in RasDss.get_catalog(source)["pathname"].tolist()
            if "/PRECIPITATION/" in value
        )
        source_first = RasDss.read_grid(source, source_paths[0])
        for output in outputs:
            assert RasDss.get_file_version(output) == version
            actual = sorted(RasDss.get_catalog(output)["pathname"].tolist())
            assert actual == expected
            assert not any("UNRELATED" in value for value in actual)

            copied_first = RasDss.read_grid(output, expected[0])
            copied_second = RasDss.read_grid(output, expected[1])
            first_tail = RasDss.read_grid(output, expected[2])
            second_tail = RasDss.read_grid(output, expected[3])

            np.testing.assert_array_equal(
                copied_first["data"],
                np.array(
                    [[1.0, np.nan, 2.0], [3.0, 4.0, 5.0]],
                    dtype=np.float32,
                ),
            )
            np.testing.assert_array_equal(
                copied_second["data"],
                np.array(
                    [[6.0, np.nan, 7.0], [8.0, 9.0, 10.0]],
                    dtype=np.float32,
                ),
            )
            expected_tail = np.array(
                [[0.0, np.nan, 0.0], [0.0, 0.0, 0.0]], dtype=np.float32
            )
            np.testing.assert_array_equal(first_tail["data"], expected_tail)
            np.testing.assert_array_equal(second_tail["data"], expected_tail)

            assert copied_first["metadata"]["lower_left_cell"] == (261, 1027)
            assert copied_first["metadata"]["origin"] == (261000.0, 1027000.0)
            for key in ("units", "data_type", "grid_type", "crs", "cell_size"):
                assert copied_first[key] == source_first[key]
            for key in (
                "grid_class",
                "grid_type_code",
                "data_type_code",
                "nodata_value",
                "projection",
                "compression",
            ):
                assert copied_first["metadata"][key] == source_first["metadata"][key]
    """
    verified = _run_bridge_script(
        verify_script,
        source,
        output,
        dss_version,
        linked_output,
    )
    _skip_if_bridge_unavailable(verified)
    _assert_clean_native_output(verified)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha


@pytest.mark.integration
@pytest.mark.parametrize("dss_version", [6, 7])
def test_native_2400_family_uses_role_specific_midnight_spelling(
    tmp_path: Path,
    dss_version: int,
) -> None:
    source = tmp_path / f"source-2400-v{dss_version}.dss"
    output = tmp_path / f"output-2400-v{dss_version}.dss"
    result_json = tmp_path / f"result-2400-v{dss_version}.json"
    script = """
        import hashlib
        import json
        import sys
        from datetime import datetime
        from pathlib import Path

        import numpy as np
        import pandas as pd

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C04_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        source = Path(sys.argv[1])
        output = Path(sys.argv[2])
        version = int(sys.argv[3])
        result_path = Path(sys.argv[4])
        RasDss._create_empty_dss(source, version)
        grid_info = {
            "cell_size": 1000,
            "origin": (259000, 1024000),
            "crs": "SHG",
            "units": "MM",
            "data_type": "PER-CUM",
            "compression": "PRECIP_2_BYTE",
        }
        if version == 6:
            grid_info.update(
                compression_base=100.0,
                compression_scale_factor=0.0,
            )

        original_format_descriptor = RasDss.__dict__["_format_grid_dss_datetime"]
        original_format = original_format_descriptor.__func__

        def format_with_2400(value):
            timestamp = pd.Timestamp(value)
            if timestamp == pd.Timestamp("2020-01-02 00:00"):
                return "01JAN2020:2400"
            return original_format(timestamp)

        RasDss._format_grid_dss_datetime = staticmethod(format_with_2400)
        try:
            written = RasDss.write_grid_timeseries(
                source,
                "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
                np.array(
                    [[[1.0, np.nan], [2.0, 3.0]]],
                    dtype=np.float32,
                ),
                [datetime(2020, 1, 1, 23), datetime(2020, 1, 2, 0)],
                grid_info,
                create_if_missing=False,
            )
        finally:
            RasDss._format_grid_dss_datetime = original_format_descriptor

        source_record = (
            "/SHG/TEST/PRECIPITATION/01JAN2020:2300/"
            "01JAN2020:2400/C04-SOURCE/"
        )
        assert written == [source_record]
        source_grid = RasDss.read_grid(source, source_record)
        assert source_grid["metadata"]["timing"]["end"] == (
            "1 January 2020, 24:00"
        )

        result = RasDss.copy_grid_with_zero_tail(
            source,
            output,
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            1,
        )
        expected_source = (
            "/SHG/TEST/PRECIPITATION/01JAN2020:2300/"
            "01JAN2020:2400/C04-SOURCE/"
        )
        expected_tail = (
            "/SHG/TEST/PRECIPITATION/02JAN2020:0000/"
            "02JAN2020:0100/C04-SOURCE/"
        )
        assert result["written_source_pathnames"] == [expected_source]
        assert result["shifted_pathnames"] == []
        assert result["appended_pathnames"] == [expected_tail]
        assert result["dss_version"] == version
        assert result["source_sha256"] == hashlib.sha256(
            source.read_bytes()
        ).hexdigest()
        assert RasDss.get_file_version(output) == version
        assert sorted(RasDss.get_catalog(output)["pathname"].tolist()) == [
            expected_source,
            expected_tail,
        ]
        copied = RasDss.read_grid(output, expected_source)
        tail = RasDss.read_grid(output, expected_tail)
        np.testing.assert_array_equal(
            copied["data"],
            np.array([[1.0, np.nan], [2.0, 3.0]], dtype=np.float32),
        )
        np.testing.assert_array_equal(
            tail["data"],
            np.array([[0.0, np.nan], [0.0, 0.0]], dtype=np.float32),
        )
        assert copied["metadata"]["timing"]["end"] == "1 January 2020, 24:00"
        assert RasDss._parse_grid_raw_datetime(
            copied["metadata"]["timing"]["end"]
        ) == pd.Timestamp("2020-01-02 00:00")
        result_path.write_text(json.dumps(result), encoding="utf-8")
    """
    completed = _run_bridge_script(
        script,
        source,
        output,
        dss_version,
        result_json,
    )
    _skip_if_bridge_unavailable(completed)
    _assert_clean_native_output(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["dss_version"] == dss_version
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize("dss_version", [6, 7])
def test_same_process_source_handles_close_on_success_and_validation_failure(
    tmp_path: Path,
    dss_version: int,
) -> None:
    source = tmp_path / f"same-process-v{dss_version}.dss"
    output = tmp_path / f"same-process-output-v{dss_version}.dss"
    rejected_output = tmp_path / f"rejected-v{dss_version}.dss"
    result_json = tmp_path / f"same-process-result-v{dss_version}.json"
    script = """
        import hashlib
        import json
        import sys
        from datetime import datetime
        from pathlib import Path

        import numpy as np

        from ras_commander import RasDss

        try:
            RasDss._configure_jvm()
        except Exception as exc:
            print(f"C04_BRIDGE_UNAVAILABLE:{type(exc).__name__}:{exc}")
            raise SystemExit(77)

        source = Path(sys.argv[1])
        output = Path(sys.argv[2])
        rejected_output = Path(sys.argv[3])
        version = int(sys.argv[4])
        result_path = Path(sys.argv[5])
        RasDss._create_empty_dss(source, version)
        grid_info = {
            "cell_size": 1000,
            "origin": (259000, 1024000),
            "crs": "SHG",
            "units": "MM",
            "data_type": "PER-CUM",
            "compression": "PRECIP_2_BYTE",
        }
        if version == 6:
            grid_info.update(
                compression_base=100.0,
                compression_scale_factor=0.0,
            )
        RasDss.write_grid_timeseries(
            source,
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            np.array(
                [[[1.0, np.nan], [2.0, 3.0]]],
                dtype=np.float32,
            ),
            [datetime(2020, 1, 1, 0), datetime(2020, 1, 1, 1)],
            grid_info,
            create_if_missing=False,
        )

        # No manual source close occurs between write and copy.
        result = RasDss.copy_grid_with_zero_tail(
            source,
            output,
            "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
            1,
        )
        accepted_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        assert result["source_sha256"] == accepted_sha

        try:
            RasDss.copy_grid_with_zero_tail(
                source,
                rejected_output,
                "/SHG/TEST/PRECIPITATION///C04-SOURCE/",
                1,
                x_shift=500,
            )
        except ValueError as exc:
            assert "whole grid-cell" in str(exc)
        else:
            raise AssertionError("expected deliberate validation rejection")

        assert hashlib.sha256(source.read_bytes()).hexdigest() == accepted_sha
        moved = source.with_name(f"moved-v{version}.dss")
        source.rename(moved)
        moved.rename(source)
        assert hashlib.sha256(source.read_bytes()).hexdigest() == accepted_sha
        assert not rejected_output.exists()
        assert RasDss.get_file_version(output) == version
        result_path.write_text(json.dumps(result), encoding="utf-8")
    """
    completed = _run_bridge_script(
        script,
        source,
        output,
        rejected_output,
        dss_version,
        result_json,
    )
    _skip_if_bridge_unavailable(completed)
    _assert_clean_native_output(completed)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(result_json.read_text(encoding="utf-8"))
    assert result["dss_version"] == dss_version
    assert result["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
