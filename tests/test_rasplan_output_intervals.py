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
    # Fixture has WQ Output Interval=15MIN; use a different value so a clobbered
    # WQ line would be detected.
    RasPlan.update_plan_intervals(upgu1, output_interval="5MIN", ras_object=_DummyRas())
    text = upgu1.read_text()
    assert "WQ Output Interval=15MIN" in text
    assert "WQ Output Interval=5MIN" not in text
    assert "\nOutput Interval=5MIN" in text
    assert "WQ Max Comp Step=1HOUR" in text


@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"output_interval": "7MIN"}, "Invalid Output Interval"),
        ({"computation_interval": "2MIN", "output_interval": "3MIN"}, "even multiple"),
        ({"output_interval": "30SEC"}, "less than the Computation Interval"),
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


def _make_project(tmp_path):
    from ras_commander import RasPrj

    shutil.copyfile(FIXTURE, tmp_path / "UPGU1.p01")
    (tmp_path / "UPGU1.prj").write_text(
        "Proj Title=UPGU1\nCurrent Plan=p01\nPlan File=p01\n", encoding="utf-8"
    )
    project = RasPrj()
    project.initialize(tmp_path, ras_exe_path="Ras.exe")
    return project


def test_clone_plan_interval_aliases_forwarded(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    captured = {}

    def fake_update(plan, **kwargs):
        captured["plan"] = plan
        captured["kwargs"] = kwargs

    monkeypatch.setattr(RasPlan, "update_plan_intervals", staticmethod(fake_update))
    RasPlan.clone_plan(
        "01",
        intervals={"hydrograph": "15MIN", "detailed": "1HOUR", "mapping": "15MIN"},
        ras_object=project,
    )
    kwargs = captured["kwargs"]
    assert kwargs["output_interval"] == "15MIN"
    assert kwargs["instantaneous_interval"] == "1HOUR"
    assert kwargs["mapping_interval"] == "15MIN"
    assert "hydrograph_output_interval" not in kwargs
    assert kwargs["ras_object"] is project


def test_update_intervals_positional_compat_with_base(upgu1):
    # Base signature: (plan, computation, output, instantaneous, mapping, ras_object)
    dummy = _DummyRas()
    RasPlan.update_plan_intervals(str(upgu1), None, "15MIN", None, None, dummy)
    assert RasPlan.get_plan_intervals(upgu1, ras_object=dummy)["output"] == "15MIN"
    with pytest.raises(TypeError):
        RasPlan.update_plan_intervals(str(upgu1), None, "15MIN", None, None, dummy, False)


DESC_PLAN = (
    "Plan Title=T\n"
    "Simulation Date=30JUN2025,00:00,09JUL2025,06:00\n"
    "Begin DESCRIPTION:\n"
    "Output Interval=30MIN\n"
    "HDF Compression=9\n"
    "Mapping Interval=2HOUR\n"
    "END DESCRIPTION:\n"
    "Computation Interval=1MIN\n"
    "Output Interval=1HOUR\n"
    "Mapping Interval=1HOUR\n"
    "HDF Compression= 1 \n"
    "  Output Interval=45MIN\n"
)


def test_keys_match_only_at_line_start_outside_description(tmp_path):
    plan = tmp_path / "P.p01"
    plan.write_text(DESC_PLAN, encoding="utf-8")
    dummy = _DummyRas()
    assert RasPlan.get_plan_intervals(plan, ras_object=dummy) == {
        "computation": "1MIN", "output": "1HOUR", "instantaneous": None, "mapping": "1HOUR",
    }
    assert RasPlan.get_plan_value(plan, "Output Interval", ras_object=dummy) == "1HOUR"
    assert RasPlan.get_plan_value(plan, "Mapping Interval", ras_object=dummy) == "1HOUR"
    assert RasPlan.get_hdf_compression(plan, ras_object=dummy)["level"] == 1

    RasPlan.update_plan_intervals(plan, output_interval="15MIN", ras_object=dummy)
    RasPlan.set_hdf_compression(plan, 0, ras_object=dummy)
    text = plan.read_text()
    assert "Begin DESCRIPTION:\nOutput Interval=30MIN\nHDF Compression=9\nMapping Interval=2HOUR\nEND DESCRIPTION:" in text
    assert "\nOutput Interval=15MIN\n" in text
    assert "  Output Interval=45MIN" in text
    assert RasPlan.get_plan_intervals(plan, ras_object=dummy)["output"] == "15MIN"
    assert RasPlan.get_hdf_compression(plan, ras_object=dummy)["level"] == 0


def test_missing_keys_are_inserted_outside_description(tmp_path):
    plan = tmp_path / "P.p01"
    description = (
        "Begin DESCRIPTION:\n"
        "Calibration Method=example\n"
        "Output Interval=30MIN\n"
        "HDF Compression=9\n"
        "HDF Additional Output Variable=Face Flow\n"
        "END DESCRIPTION:\n"
    )
    plan.write_text("Plan Title=T\n" + description + "Flow File=u01\n", encoding="utf-8")
    dummy = _DummyRas()

    RasPlan.update_plan_intervals(plan, output_interval="15MIN", ras_object=dummy)
    assert RasPlan.set_hdf_compression(plan, 0, ras_object=dummy)
    assert RasPlan.add_hdf_output_variable(plan, "Face Flow", ras_object=dummy)

    text = plan.read_text(encoding="utf-8")
    assert description in text
    assert text.index("Output Interval=15MIN") > text.index("END DESCRIPTION:")
    assert text.index("HDF Compression= 0 ") > text.index("END DESCRIPTION:")
    assert text.index("HDF Additional Output Variable=Face Flow", text.index("END DESCRIPTION:")) > 0
    assert RasPlan.get_plan_intervals(plan, ras_object=dummy)["output"] == "15MIN"
    assert RasPlan.get_hdf_compression(plan, ras_object=dummy)["effective"]["level"] == 0
    assert RasPlan.get_hdf_output_variables(plan, ras_object=dummy) == ["Face Flow"]


def test_insertion_after_unterminated_final_line(tmp_path):
    plan = tmp_path / "P.p01"
    plan.write_text("Plan Title=T\nFlow File=u01\nHDF Compression= 1 ", encoding="utf-8")
    dummy = _DummyRas()

    assert RasPlan.set_hdf_write_parameters(plan, chunk_size_mb=2, ras_object=dummy)
    assert RasPlan.add_hdf_output_variable(plan, "Face Flow", ras_object=dummy)

    text = plan.read_text(encoding="utf-8")
    assert "HDF Compression= 1 HDF" not in text
    assert RasPlan.get_hdf_compression(plan, ras_object=dummy)["effective"]["level"] == 1
    assert RasPlan.get_hdf_write_parameters(plan, ras_object=dummy)["chunk_size_mb"] == 2
    assert RasPlan.get_hdf_output_variables(plan, ras_object=dummy) == ["Face Flow"]


def test_duplicate_interval_and_hdf_keys_use_first_value_and_update_all(tmp_path):
    plan = tmp_path / "P.p01"
    plan.write_text(
        "Plan Title=T\n"
        "Computation Interval=1MIN\n"
        "Output Interval=30MIN\n"
        "Output Interval=1HOUR\n"
        "HDF Compression= 1 \n"
        "HDF Compression= 5 \n",
        encoding="utf-8",
    )
    dummy = _DummyRas()

    assert RasPlan.get_plan_intervals(plan, ras_object=dummy)["output"] == "30MIN"
    assert RasPlan.get_hdf_write_parameters(plan, ras_object=dummy)["compression"] == 1
    assert RasPlan.get_hdf_compression(plan, ras_object=dummy)["level"] == 1

    RasPlan.update_plan_intervals(plan, output_interval="15MIN", ras_object=dummy)
    assert RasPlan.set_hdf_compression(plan, 0, ras_object=dummy)

    text = plan.read_text(encoding="utf-8")
    assert text.count("Output Interval=15MIN") == 2
    assert text.count("HDF Compression= 0 ") == 2
    assert RasPlan.get_plan_intervals(plan, ras_object=dummy)["output"] == "15MIN"
    assert RasPlan.get_hdf_write_parameters(plan, ras_object=dummy)["compression"] == 0


def test_set_hdf_compression_refreshes_plan_df(tmp_path):
    project = _make_project(tmp_path)
    assert project.plan_df.iloc[0]["HDF Compression"] == "1"
    assert RasPlan.set_hdf_compression("01", 0, ras_object=project)
    assert project.plan_df.iloc[0]["HDF Compression"] == "0"
    assert RasPlan.set_hdf_write_parameters("01", chunk_size_mb=2, ras_object=project)
    assert project.plan_df.iloc[0]["HDF Chunk Size"] == "2"


@pytest.mark.parametrize(
    "getter",
    [
        RasPlan.get_plan_intervals,
        RasPlan.get_hdf_write_parameters,
        RasPlan.get_hdf_compression,
    ],
)
def test_output_getters_raise_for_nonexistent_plan(tmp_path, getter):
    project = _make_project(tmp_path)
    with pytest.raises(ValueError, match="Plan file not found"):
        getter("99", ras_object=project)


@pytest.mark.parametrize("token", ["1WEEK", "1MON", "1YEAR"])
def test_long_interval_tokens_accepted(upgu1, token):
    assert token in RasPlan.VALID_PLAN_INTERVALS
    RasPlan.update_plan_intervals(upgu1, output_interval=token, validate=False, ras_object=_DummyRas())
    assert RasPlan.get_plan_intervals(upgu1, ras_object=_DummyRas())["output"] == token
    assert RasPlan.validate_plan_intervals("1MIN", token) == []


def test_detailed_smaller_than_hydrograph_is_not_an_error(upgu1):
    # Ras.exe has a message for this but it was not confirmed to block a compute.
    assert RasPlan.validate_plan_intervals("1MIN", "30MIN", "10MIN") == []
    RasPlan.update_plan_intervals(upgu1, instantaneous_interval="10MIN", ras_object=_DummyRas())
    assert RasPlan.get_plan_intervals(upgu1, ras_object=_DummyRas())["instantaneous"] == "10MIN"


def test_get_hdf_output_settings_small_h5py_fixture(tmp_path):
    import h5py
    import pandas as pd
    import numpy as np
    from ras_commander import HdfPlan

    path = tmp_path / "UPGU1.p01.hdf"
    with h5py.File(path, "w") as f:
        params = f.create_group("Plan Data/Plan Parameters")
        params.attrs["HDF Compression"] = np.int32(1)
        params.attrs["HDF Chunk Size"] = np.float32(1.0)
        params.attrs["Other"] = "ignored"
        ts = f.create_group("Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series")
        ts.create_dataset("Time Date Stamp", data=np.array([b"t"] * 5, dtype="S20"))
        ts.create_dataset(
            "Area/Water Surface", data=np.zeros((5, 100), dtype="f4"), chunks=(1, 100),
            compression="gzip", compression_opts=1,
        )
        ts.create_dataset("Area/Plain", data=np.ones((5, 10), dtype="f4"))
    out = HdfPlan.get_hdf_output_settings(path)
    assert out["write_parameters"]["HDF Compression"] == 1
    assert "Other" not in out["write_parameters"]
    assert out["n_timesteps"] == 5
    df = out["time_series"].set_index("name")
    assert df.loc["Area/Water Surface", "compression"] == "gzip"
    assert tuple(df.loc["Area/Water Surface", "chunks"]) == (1, 100)
    assert pd.isna(df.loc["Area/Plain", "compression"])
    assert pd.isna(df.loc["Area/Plain", "chunks"])
    assert out["file_size_mb"] > 0


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
