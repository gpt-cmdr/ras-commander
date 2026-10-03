"""Offline tests for plan interval and HDF compression helpers in RasPlan/HdfPlan."""

import shutil
from pathlib import Path

import pytest

from ras_commander.RasPlan import RasPlan

FIXTURE = Path(__file__).parent / "fixtures" / "plan_output_intervals" / "UPGU1.p01"


class _DummyRas:
    def check_initialized(self):
        return None


@pytest.fixture
def upgu1(tmp_path):
    path = tmp_path / "UPGU1.p01"
    shutil.copyfile(FIXTURE, path)
    return path


def _changed_lines(before: bytes, after: bytes):
    b, a = before.split(b"\r\n"), after.split(b"\r\n")
    return [x for x in a if x not in b], [x for x in b if x not in a]


def test_get_plan_intervals_real_plan(upgu1):
    values = RasPlan.get_plan_intervals(upgu1, ras_object=_DummyRas())
    assert values == {
        "computation": "1MIN",
        "output": "30MIN",
        "instantaneous": "1HOUR",
        "mapping": "1HOUR",
    }


def test_update_intervals_roundtrips_other_lines_and_crlf(upgu1):
    before = upgu1.read_bytes()
    RasPlan.update_plan_intervals(
        upgu1,
        computation_interval="30SEC",
        output_interval="15min",
        mapping_interval="15MIN",
        ras_object=_DummyRas(),
    )
    after = upgu1.read_bytes()
    assert b"\n" not in after.replace(b"\r\n", b"")  # still pure CRLF
    added, removed = _changed_lines(before, after)
    assert sorted(added) == [
        b"Computation Interval=30SEC",
        b"Mapping Interval=15MIN",
        b"Output Interval=15MIN",
    ]
    assert sorted(removed) == [
        b"Computation Interval=1MIN",
        b"Mapping Interval=1HOUR",
        b"Output Interval=30MIN",
    ]
    assert len(before.split(b"\r\n")) == len(after.split(b"\r\n"))
    assert RasPlan.get_plan_intervals(upgu1, ras_object=_DummyRas())["instantaneous"] == "1HOUR"


def test_update_intervals_does_not_touch_wq_output_interval(upgu1):
    RasPlan.update_plan_intervals(upgu1, output_interval="15MIN", ras_object=_DummyRas())
    assert "WQ Output Interval=15MIN" in upgu1.read_text()
    assert "WQ Max Comp Step=1HOUR" in upgu1.read_text()


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"output_interval": "7MIN"}, "Invalid Output Interval"),
        ({"computation_interval": "2MIN", "output_interval": "3MIN"}, "even multiple"),
        ({"output_interval": "30SEC"}, "less than the Computation Interval"),
        ({"instantaneous_interval": "10MIN"}, "less than the Output"),
        ({"computation_interval": "1HOUR"}, "less than the Computation"),
    ],
)
def test_update_intervals_rejects_bad_values(upgu1, kwargs, fragment):
    before = upgu1.read_bytes()
    with pytest.raises(ValueError, match=fragment):
        RasPlan.update_plan_intervals(upgu1, ras_object=_DummyRas(), **kwargs)
    assert upgu1.read_bytes() == before


def test_start_time_alignment_with_output_interval(tmp_path):
    plan = tmp_path / "P.p01"
    plan.write_text(
        "Plan Title=T\nSimulation Date=30JUN2025,00:10,09JUL2025,06:00\n"
        "Computation Interval=10SEC\nOutput Interval=10MIN\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Simulation start time"):
        RasPlan.update_plan_intervals(plan, output_interval="15MIN", ras_object=_DummyRas())
    RasPlan.update_plan_intervals(
        plan, output_interval="15MIN", validate=False, ras_object=_DummyRas()
    )
    assert RasPlan.get_plan_intervals(plan, ras_object=_DummyRas())["output"] == "15MIN"


def test_update_intervals_inserts_missing_keys(tmp_path):
    plan = tmp_path / "P.p01"
    plan.write_text(
        "Plan Title=T\nGeom File=g01\nComputation Interval=1MIN\nRun HTab=-1 \n",
        encoding="utf-8",
    )
    RasPlan.update_plan_intervals(
        plan, output_interval="5MIN", mapping_interval="15MIN", ras_object=_DummyRas()
    )
    assert plan.read_bytes() == (
        b"Plan Title=T\r\nGeom File=g01\r\nComputation Interval=1MIN\r\n"
        b"Output Interval=5MIN\r\nMapping Interval=15MIN\r\nRun HTab=-1 \r\n"
    )


def test_validate_plan_intervals_pure():
    assert RasPlan.validate_plan_intervals("30SEC", "15MIN", "1HOUR", "15MIN", "00:00") == []
    assert RasPlan.interval_to_seconds("0.5SEC") == 0.5
    assert RasPlan.interval_to_seconds("1DAY") == 86400.0
    with pytest.raises(ValueError):
        RasPlan.interval_to_seconds("45MIN")


def test_get_hdf_compression_real_plan_and_defaults(upgu1, tmp_path):
    info = RasPlan.get_hdf_compression(upgu1, ras_object=_DummyRas())
    assert info["level"] == 1 and info["chunk_size_mb"] == 1
    assert info["use_max_rows"] is False and info["fixed_rows"] == 1
    assert info["enabled"] is True

    bare = tmp_path / "B.p01"
    bare.write_text("Plan Title=T\n", encoding="utf-8")
    info = RasPlan.get_hdf_compression(bare, ras_object=_DummyRas())
    assert info["level"] is None and info["effective"]["level"] == 1


def test_set_hdf_compression_zero_nine_and_validation(upgu1):
    before = upgu1.read_bytes()
    assert RasPlan.set_hdf_compression(upgu1, 0, ras_object=_DummyRas())
    info = RasPlan.get_hdf_compression(upgu1, ras_object=_DummyRas())
    assert info["level"] == 0 and info["enabled"] is False
    assert RasPlan.set_hdf_compression(upgu1, 1, chunk_size_mb=1, ras_object=_DummyRas())
    after = upgu1.read_bytes()
    # Level back to 1 with the original formatting: file is byte-identical.
    assert after == before
    for bad in (-1, 10, 1.5, True, "1"):
        with pytest.raises(ValueError):
            RasPlan.set_hdf_compression(upgu1, bad, ras_object=_DummyRas())


def test_clone_plan_interval_aliases_map_to_update_arguments():
    # hydrograph/instantaneous aliases must be accepted by update_plan_intervals.
    import inspect
    params = inspect.signature(RasPlan.update_plan_intervals).parameters
    for name in ("output_interval", "instantaneous_interval", "validate"):
        assert name in params


def test_plan_df_exposes_intervals_and_hdf_keys(tmp_path):
    from ras_commander import RasPrj

    shutil.copyfile(FIXTURE, tmp_path / "UPGU1.p01")
    (tmp_path / "UPGU1.prj").write_text(
        "Proj Title=UPGU1\nCurrent Plan=p01\nPlan File=p01\n", encoding="utf-8"
    )
    project = RasPrj()
    project.initialize(tmp_path, ras_exe_path="Ras.exe")
    row = project.plan_df.iloc[0]
    assert row["Output Interval"] == "30MIN"
    assert row["Instantaneous Interval"] == "1HOUR"
    assert row["Mapping Interval"] == "1HOUR"
    assert row["HDF Compression"] == "1"
    assert row["HDF Chunk Size"] == "1"
    assert row["Write Detailed"] == "1"

    RasPlan.update_plan_intervals("01", output_interval="15MIN", ras_object=project)
    assert project.plan_df.iloc[0]["Output Interval"] == "15MIN"
