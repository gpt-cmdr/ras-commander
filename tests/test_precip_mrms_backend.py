"""Backend selection, the missing wheel and shadow comparison for ``PrecipMrms.to_dss``.

No test here starts a JVM or runs HEC-Vortex: the Java route is replaced where it is called.
Selection and missing-wheel tests need no wheel. Argument mapping uses a stand-in engine. The
comparison tests write real DSS grids and skip when ``ras_commander_fast_dss`` is not installed.

``RAS_COMMANDER_MRMS_SAMPLE_DIR`` may name a folder of public MRMS GRIB2 samples for the tests on
real files; they copy each sample before reading it.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time
import types

import numpy as np
import pytest

from ras_commander.precip import PrecipMrms, _native_vortex as nv
from ras_commander.precip.VortexCli import VortexCli

HOURLY_NAME = "MRMS_MultiSensor_QPE_01H_Pass2_00.00_20240926-220000.grib2"
DAILY_NAME = "MRMS_MultiSensor_QPE_24H_Pass2_00.00_20240926-220000.grib2"
PATHNAME = "/SHG/MRMS_QPE/PRECIPITATION/26SEP2024:2100/26SEP2024:2200/GAUGECORR_QPE_01H/"


def hourly_record(pathname: str = PATHNAME, data_type: str = "PER-CUM") -> dict:
    return {"pathname": pathname, "data_type": data_type, "units": "MM"}


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv(nv.ENV_VAR, raising=False)
    monkeypatch.setattr(PrecipMrms, "backend", "java")
    nv.reset_fallback_warning()
    nv.reset_shadow_stats()
    yield
    nv.reset_fallback_warning()
    nv.reset_shadow_stats()


@pytest.fixture
def no_wheel(monkeypatch):
    """An environment where the engine is not installed."""
    for name in (
        "ras_commander_fast_dss",
        "ras_commander_fast_dss.gridded",
        "ras_commander_fast_dss.exceptions",
    ):
        monkeypatch.setitem(sys.modules, name, None)


@pytest.fixture
def java_calls(monkeypatch):
    """Replace HEC-Vortex with a stand-in that writes a placeholder file."""
    calls = []

    def fake_import_gridded(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_dss"])
        output.write_bytes(b"DSS")
        return output

    monkeypatch.setattr(VortexCli, "import_gridded", staticmethod(fake_import_gridded))
    return calls


@pytest.fixture
def engine(monkeypatch):
    """A stand-in engine recording what the adapter passes. ``engine.records`` is what it returns."""

    class DssError(RuntimeError):
        pass

    class DssUnsupportedRecordError(DssError):
        pass

    state = types.SimpleNamespace(
        calls=[],
        records=[hourly_record()],
        error=None,
        fail_after=0,
        variables=["MultiSensor_QPE_01H_Pass2_altitude_above_msl"],
    )

    def import_gridded(inputs, output, **kwargs):
        state.calls.append(dict(inputs=inputs, output=output, **kwargs))
        if state.error is not None and len(state.calls) > state.fail_after:
            raise state.error
        if kwargs.get("progress"):
            kwargs["progress"]({"done": 1, "total": 1})
        return types.SimpleNamespace(records=list(state.records), output=output)

    gridded = types.ModuleType("ras_commander_fast_dss.gridded")
    gridded.import_gridded = import_gridded
    gridded.list_variables = lambda path: list(state.variables)
    exceptions = types.ModuleType("ras_commander_fast_dss.exceptions")
    exceptions.DssError = DssError
    exceptions.DssUnsupportedRecordError = DssUnsupportedRecordError
    package = types.ModuleType("ras_commander_fast_dss")
    package.gridded = gridded
    package.exceptions = exceptions
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss", package)
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss.gridded", gridded)
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss.exceptions", exceptions)
    state.exceptions = exceptions
    return state


@pytest.fixture
def grib(tmp_path) -> Path:
    path = tmp_path / HOURLY_NAME
    path.write_bytes(b"GRIB")
    return path


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_default_stays_java_and_never_loads_the_engine(no_wheel, java_calls, grib, tmp_path):
    output = tmp_path / "out.dss"
    assert PrecipMrms.backend == "java"
    assert PrecipMrms.to_dss(grib, output) == output
    assert len(java_calls) == 1


def test_java_arguments_are_unchanged_by_the_backend_argument(java_calls, grib, tmp_path):
    PrecipMrms.to_dss(grib, tmp_path / "a.dss", backend="java")
    PrecipMrms.to_dss(grib, tmp_path / "b.dss")
    first, second = java_calls
    assert {k: v for k, v in first.items() if k != "output_dss"} == {
        k: v for k, v in second.items() if k != "output_dss"
    }


def test_argument_wins_then_environment_then_attribute(monkeypatch):
    monkeypatch.setattr(PrecipMrms, "backend", "shadow")
    assert nv.requested_backend(None, PrecipMrms.backend) == "shadow"
    monkeypatch.setenv(nv.ENV_VAR, " NATIVE ")
    assert nv.requested_backend(None, PrecipMrms.backend) == "native"
    assert nv.requested_backend("Java", PrecipMrms.backend) == "java"


@pytest.mark.parametrize("bad", ["rust", "vortex", ""])
def test_invalid_backend_argument_is_refused(bad, java_calls, grib, tmp_path):
    with pytest.raises(ValueError, match="Invalid MRMS backend"):
        PrecipMrms.to_dss(grib, tmp_path / "out.dss", backend=bad)
    assert java_calls == []


def test_invalid_environment_value_names_the_variable(monkeypatch):
    monkeypatch.setenv(nv.ENV_VAR, "rust")
    with pytest.raises(ValueError, match=nv.ENV_VAR):
        nv.requested_backend(None, "java")


def test_rasdss_environment_variable_does_not_select_this_backend(monkeypatch, java_calls, grib, tmp_path):
    monkeypatch.setenv("RAS_COMMANDER_DSS_BACKEND", "native")
    PrecipMrms.to_dss(grib, tmp_path / "out.dss")
    assert len(java_calls) == 1


# ---------------------------------------------------------------------------
# Missing wheel
# ---------------------------------------------------------------------------


def test_native_without_wheel_raises_import_error_and_writes_nothing(no_wheel, java_calls, grib, tmp_path):
    output = tmp_path / "out.dss"
    with pytest.raises(ImportError, match="ras-commander-fast-dss"):
        PrecipMrms.to_dss(grib, output, backend="native")
    assert not output.exists()
    assert java_calls == []


def test_shadow_without_wheel_runs_java_and_warns_once(no_wheel, java_calls, grib, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        first = PrecipMrms.to_dss(grib, tmp_path / "a.dss", backend="shadow")
        PrecipMrms.to_dss(grib, tmp_path / "b.dss", backend="shadow")
    assert first == tmp_path / "a.dss"
    assert len(java_calls) == 2
    assert sum("not available" in r.getMessage() for r in caplog.records) == 1


def test_broken_wheel_counts_as_absent(monkeypatch, java_calls, grib, tmp_path):
    def broken(name, *args, **kwargs):
        if name.startswith("ras_commander_fast_dss"):
            raise OSError("DLL load failed")
        return __import__(name)

    monkeypatch.setattr(nv.importlib, "import_module", broken)
    assert not nv.native_available()
    with pytest.raises(ImportError, match="failed to load") as info:
        PrecipMrms.to_dss(grib, tmp_path / "out.dss", backend="native")
    assert isinstance(info.value.__cause__, OSError)
    assert PrecipMrms.to_dss(grib, tmp_path / "out.dss", backend="shadow") == tmp_path / "out.dss"
    assert len(java_calls) == 1


def test_wheel_without_the_importer_is_reported(monkeypatch, grib, tmp_path):
    bare = types.ModuleType("ras_commander_fast_dss.gridded")
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss", types.ModuleType("ras_commander_fast_dss"))
    monkeypatch.setitem(sys.modules, "ras_commander_fast_dss.gridded", bare)
    with pytest.raises(ImportError, match="no gridded importer"):
        PrecipMrms.to_dss(grib, tmp_path / "out.dss", backend="native")


@pytest.mark.parametrize("blocked", [True, False])
def test_import_ras_commander_does_not_need_or_load_the_engine(blocked):
    block = "sys.modules['ras_commander_fast_dss'] = None" if blocked else ""
    code = textwrap.dedent(
        f"""
        import sys
        {block}
        import ras_commander
        from ras_commander.precip import PrecipMrms, _native_vortex
        assert PrecipMrms.backend == "java"
        assert sys.modules.get("ras_commander_fast_dss") is None
        assert "ras_commander_fast_dss.gridded" not in sys.modules
        """
    )
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root)}
    done = subprocess.run([sys.executable, "-c", code], cwd=str(root), env=env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]


# ---------------------------------------------------------------------------
# Native arguments
# ---------------------------------------------------------------------------


def test_native_maps_arguments_and_does_not_run_java(engine, java_calls, grib, tmp_path):
    clip = tmp_path / "clip.shp"
    clip.write_text("placeholder")
    output = tmp_path / "out.dss"
    result = PrecipMrms.to_dss(
        [grib],
        output,
        clip_shp=clip,
        product="MultiSensor_QPE_01H_Pass2_00.00",
        target_wkt="shg",
        target_cell_size=1000,
        resampling_method="Nearest Neighbor",
        dss_parts={"b": "WNC", "F": "P47"},
        backend="native",
    )
    assert java_calls == []
    assert result == output.resolve()
    call = engine.calls[0]
    assert call["inputs"] == [str(grib.resolve())]
    assert call["output"] == str(output)
    assert call["product"] == "mrms_qpe"
    assert "variable" not in call
    assert "data_type" not in call and "window_rule" not in call
    assert call["shapefile"] == str(clip.resolve())
    assert call["target_crs"] == "SHG"
    assert call["cell_size"] == 1000.0
    assert call["method"] == "near"
    assert call["align"] == "refuse"
    assert call["parts"]["A"] == "SHG"
    assert call["parts"]["B"] == "WNC"
    assert call["parts"]["F"] == "P47"
    assert "b" not in call["parts"]


@pytest.mark.parametrize(
    "spelling,method",
    [("Bilinear", "bilinear"), ("near", "near"), ("NearestNeighbor", "near"), ("AVERAGE", "average")],
)
def test_resampling_spellings(spelling, method, engine, grib, tmp_path):
    PrecipMrms.to_dss(grib, tmp_path / "o.dss", resampling_method=spelling, backend="native")
    assert engine.calls[0]["method"] == method


def test_unknown_resampling_is_refused(engine, grib, tmp_path):
    with pytest.raises(ValueError, match="resampling_method"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", resampling_method="cubic", backend="native")
    assert engine.calls == []


def test_each_stated_variable_is_imported(engine, grib, tmp_path):
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    other = PATHNAME.replace("/GAUGECORR_QPE_01H/", "/OTHER/")
    pathnames = iter([PATHNAME, other, PATHNAME, other])  # The rehearsal, then the import.
    real_import = sys.modules["ras_commander_fast_dss.gridded"].import_gridded

    def distinct(inputs, output, **kwargs):
        result = real_import(inputs, output, **kwargs)
        result.records = [hourly_record(next(pathnames))]
        return result

    sys.modules["ras_commander_fast_dss.gridded"].import_gridded = distinct
    PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=names, backend="native")
    assert [call["variable"] for call in engine.calls] == names * 2


def test_a_later_stated_variable_that_is_absent_is_refused_before_any_write(engine, grib, tmp_path):
    held = "MultiSensor_QPE_01H_Pass2_altitude_above_msl"
    output = tmp_path / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="UnknownQPE"):
        PrecipMrms.to_dss(grib, output, variables=[held, "UnknownQPE"], backend="native")
    assert engine.calls == []
    assert not output.exists()


def test_a_variable_absent_from_one_input_of_several_is_refused(engine, monkeypatch, grib, tmp_path):
    second = tmp_path / HOURLY_NAME.replace("220000", "230000")
    second.write_bytes(b"GRIB")
    held = "MultiSensor_QPE_01H_Pass2_altitude_above_msl"
    gridded = sys.modules["ras_commander_fast_dss.gridded"]
    monkeypatch.setattr(gridded, "list_variables", lambda path: [held] if path == str(grib.resolve()) else [])
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="230000"):
        PrecipMrms.to_dss([grib, second], tmp_path / "o.dss", variables=[held], backend="native")
    assert engine.calls == []


def test_a_variable_stated_twice_is_refused(engine, grib, tmp_path):
    held = "MultiSensor_QPE_01H_Pass2_altitude_above_msl"
    with pytest.raises(ValueError, match="more than once"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=[held, held], backend="native")
    assert engine.calls == []


def distinct_pathnames(engine):
    """Give the stand-in importer's two selections their own pathnames, in the rehearsal and the import."""
    other = PATHNAME.replace("/GAUGECORR_QPE_01H/", "/OTHER/")
    pathnames = iter([PATHNAME, other, PATHNAME, other])
    module = sys.modules["ras_commander_fast_dss.gridded"]
    real_import = module.import_gridded

    def distinct(inputs, output, **kwargs):
        result = real_import(inputs, output, **kwargs)
        result.records = [hourly_record(next(pathnames))]
        return result

    module.import_gridded = distinct


def test_a_later_failure_reports_the_total_written_across_calls(engine, grib, tmp_path):
    """A refusal only the importer can know: the earlier call's records remain, and the error says so."""
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    failure = engine.exceptions.DssUnsupportedRecordError("0 record(s) already written remain")
    failure.completed = [hourly_record("/SHG/B/PRECIPITATION/26SEP2024:2200/26SEP2024:2300/F/")]
    engine.error, engine.fail_after = failure, 3  # Past the two rehearsal calls and the first import.
    distinct_pathnames(engine)
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match=r"wrote 2 record\(s\)") as info:
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=names, backend="native")
    assert info.value is failure
    assert len(info.value.completed) == 2


def test_a_later_os_error_still_states_the_total(engine, grib, tmp_path):
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    engine.error, engine.fail_after = OSError(28, "No space left"), 3
    distinct_pathnames(engine)
    with pytest.raises(engine.exceptions.DssError, match=r"wrote 1 record\(s\)") as info:
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=names, backend="native")
    assert isinstance(info.value.__context__, OSError)


def recording_destinations(engine):
    """Note every file the stand-in importer is asked to write."""
    module = sys.modules["ras_commander_fast_dss.gridded"]
    real_import, destinations = module.import_gridded, []

    def recording(inputs, output, **kwargs):
        destinations.append(Path(output))
        return real_import(inputs, output, **kwargs)

    module.import_gridded = recording
    return destinations


def test_two_selections_writing_one_pathname_are_refused_before_the_callers_file(engine, grib, tmp_path):
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    destinations = recording_destinations(engine)
    out = tmp_path / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="Nothing was written") as info:
        PrecipMrms.to_dss(grib, out, variables=names, backend="native")
    assert "one pathname" in str(info.value)
    assert len(destinations) == 2 and out not in destinations
    assert not list(tmp_path.glob("mrms_rehearsal_*"))


def test_a_later_selection_refused_in_rehearsal_leaves_the_callers_file_alone(engine, grib, tmp_path):
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    engine.error, engine.fail_after = engine.exceptions.DssUnsupportedRecordError("refused while planning"), 1
    destinations = recording_destinations(engine)
    out = tmp_path / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="refused while planning"):
        PrecipMrms.to_dss(grib, out, variables=names, backend="native")
    assert out not in destinations
    assert not list(tmp_path.glob("mrms_rehearsal_*"))


def test_one_selection_is_not_rehearsed(engine, grib, tmp_path):
    destinations = recording_destinations(engine)
    out = tmp_path / "o.dss"
    PrecipMrms.to_dss(grib, out, backend="native")
    assert destinations == [out]


def test_a_source_that_changes_after_the_rehearsal_is_still_caught(engine, grib, tmp_path):
    names = ["MultiSensor_QPE_01H_Pass1_altitude_above_msl", "MultiSensor_QPE_01H_Pass2_altitude_above_msl"]
    engine.variables = names
    other = PATHNAME.replace("/GAUGECORR_QPE_01H/", "/OTHER/")
    pathnames = iter([PATHNAME, other, PATHNAME, PATHNAME])
    module = sys.modules["ras_commander_fast_dss.gridded"]
    real_import = module.import_gridded

    def changing(inputs, output, **kwargs):
        result = real_import(inputs, output, **kwargs)
        result.records = [hourly_record(next(pathnames))]
        return result

    module.import_gridded = changing
    with pytest.raises(engine.exceptions.DssError, match="the last stays"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=names, backend="native")


def test_a_scratch_folder_that_cannot_be_removed_is_reported(monkeypatch, tmp_path, caplog):
    def refuse(path):
        raise PermissionError(32, "in use", str(path))

    monkeypatch.setattr(nv.shutil, "rmtree", refuse)
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        nv._remove_scratch(tmp_path / "scratch", pause=0.0)
    assert any("remains" in r.getMessage() and "scratch" in r.getMessage() for r in caplog.records)


def test_missing_input_and_clip_raise_as_java_does(engine, grib, tmp_path):
    with pytest.raises(FileNotFoundError, match="Input file"):
        PrecipMrms.to_dss(tmp_path / HOURLY_NAME.replace("220000", "230000"), tmp_path / "o.dss", backend="native")
    with pytest.raises(FileNotFoundError, match="Clip shapefile"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", clip_shp=tmp_path / "no.shp", backend="native")
    assert engine.calls == []


def test_engine_error_carries_through_unchanged(engine, grib, tmp_path):
    engine.error = engine.exceptions.DssUnsupportedRecordError("refused while planning")
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="refused while planning") as info:
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend="native")
    assert info.value is engine.error
    assert isinstance(info.value, RuntimeError)


def test_timeout_is_a_timeout_error(engine, grib, tmp_path):
    with pytest.raises(TimeoutError, match="timed out"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", timeout=-1, backend="native")


# ---------------------------------------------------------------------------
# Periods: never a precipitation grid that could read as no rain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "file_name,product,variables,stated",
    [
        (DAILY_NAME, "GaugeCorr_QPE_01H", None, "1440 minutes"),
        ("MRMS_RadarOnly_QPE_15M_00.00_20250115-060000.grib2", "GaugeCorr_QPE_01H", None, "15 minutes"),
        (HOURLY_NAME, "GaugeCorr_QPE_24H", None, "1440 minutes"),
        (HOURLY_NAME, "GaugeCorr_QPE_01H", ["MultiSensor_QPE_72H_Pass2_altitude_above_msl"], "4320 minutes"),
        (HOURLY_NAME, "GaugeCorr_QPE_01H", ["GaugeCorrQPE03H_altitude_above_msl"], "180 minutes"),
    ],
)
def test_other_durations_are_refused_before_the_importer_runs(
    file_name, product, variables, stated, engine, java_calls, tmp_path
):
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    output = tmp_path / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match=stated) as info:
        PrecipMrms.to_dss(path, output, product=product, variables=variables, backend="native")
    assert "no rain" in str(info.value)
    assert engine.calls == []
    assert java_calls == []
    assert not output.exists()


def test_a_file_whose_variable_states_another_duration_is_refused(engine, grib, tmp_path):
    """The file name says 01H, and the file's own variable says 24H."""
    engine.variables = ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"]
    output = tmp_path / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="1440 minutes"):
        PrecipMrms.to_dss(grib, output, backend="native")
    assert engine.calls == []
    assert not output.exists()


def test_a_variable_that_is_not_qpe_is_refused(engine, grib, tmp_path):
    with pytest.raises(ValueError, match="not an MRMS QPE"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", variables=["VAR209-6-250_FROM_161-0--1_altitude_above_msl"], backend="native")
    assert engine.calls == []


@pytest.mark.parametrize(
    "record,why",
    [
        (hourly_record(data_type="INST-VAL"), "INST-VAL"),
        (hourly_record("/SHG/B/PRECIPITATION/26SEP2024:2200//F/"), "no period"),
        (hourly_record("/SHG/B/PRECIPITATION/26SEP2024:2000/26SEP2024:2200/F/"), "7200 seconds"),
        (hourly_record("/SHG/B/PRECIPITATION/26SEP2024:2200/26SEP2024:2200/F/"), "0 seconds"),
        (hourly_record("/SHG/B/PRECIPITATION/F/"), "six-part"),
    ],
)
def test_a_written_record_without_a_one_hour_period_raises(record, why, engine, grib, tmp_path):
    engine.records = [record]
    with pytest.raises(engine.exceptions.DssError, match=why):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend="native")


def test_a_period_across_midnight_is_one_hour():
    midnight = "/SHG/B/PRECIPITATION/26SEP2024:2300/26SEP2024:2400/F/"
    assert nv.record_period_problem(hourly_record(midnight)) is None


def test_no_records_is_an_error(engine, grib, tmp_path):
    engine.records = []
    with pytest.raises(engine.exceptions.DssError, match="no records"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend="native")


RADAR_15M = "MRMS_RadarOnly_QPE_15M_00.00_20250115-060000.grib2"


@pytest.mark.parametrize("backend", ["java", "shadow"])
@pytest.mark.parametrize(
    "file_name,product,variables,stated",
    [
        (DAILY_NAME, "GaugeCorr_QPE_01H", None, "1440 minutes"),
        (RADAR_15M, "GaugeCorr_QPE_01H", None, "15 minutes"),
        (DAILY_NAME, "GaugeCorr_QPE_01H", ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"], "1440 minutes"),
        ("storm.grib2", "GaugeCorr_QPE_24H", None, "1440 minutes"),
        ("storm.grib2", "GaugeCorr_QPE_01H", None, "gives no one-hour period"),
        ("storm_01H.grib2", "GaugeCorr_QPE_01H", ["RadarOnly_QPE_01H_altitude_above_msl"], "gives no one-hour period"),
    ],
)
def test_java_and_shadow_refuse_with_nothing_written(
    backend, file_name, product, variables, stated, no_wheel, java_calls, tmp_path
):
    """The names alone must be enough: this runs with no wheel, so no listing is available."""
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    output = tmp_path / "new_folder" / "o.dss"
    with pytest.raises(ValueError, match=stated) as info:
        PrecipMrms.to_dss(path, output, product=product, variables=variables, backend=backend)
    message = str(info.value)
    assert file_name in message
    assert "no rain" in message
    assert "allow_instantaneous_precip=True" in message
    assert java_calls == []
    assert not output.parent.exists()


@pytest.mark.parametrize(
    "name,expected",
    [
        ("24H_RadarOnly_QPE_01H_legitimate.grib2", [3600]),
        ("MRMS_MultiSensor_QPE_24H_Pass2_00.00_20240920-120000.grib2", [86400]),
        ("RadarOnly_QPE_15M_altitude_above_msl", [900]),
        ("GaugeCorrQPE03H_altitude_above_msl", [10800]),
        ("GaugeCorr-QPE-06H", [21600]),
        ("radaronly_qpe_12h", [43200]),
        ("QPE_24H_RadarOnly_QPE_01H.grib2", [3600]),
        ("QPE_72H_label.grib2", [259200]),
        ("hrrr_24H.t12z.wrfsfcf01.grib2", []),
        ("FLASH_QPE_ARI01H_00.00.grib2", []),
    ],
)
def test_accumulation_is_tied_to_the_qpe_stem(name, expected):
    assert nv._stem_seconds(name) == expected


@pytest.mark.parametrize("backend", ["java", "shadow"])
@pytest.mark.parametrize("variables", [None, ["RadarOnly_QPE_01H_altitude_above_msl"]])
def test_an_incidental_duration_label_does_not_refuse_a_one_hour_product(
    backend, variables, no_wheel, java_calls, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        VortexCli, "get_grib2_variables",
        staticmethod(lambda p, **kwargs: ["RadarOnly_QPE_01H_altitude_above_msl"]),
    )
    path = tmp_path / "24H_RadarOnly_QPE_01H_legitimate.grib2"
    path.write_bytes(b"GRIB")
    PrecipMrms.to_dss(path, tmp_path / "o.dss", variables=variables, backend=backend)
    assert len(java_calls) == 1


@pytest.mark.parametrize(
    "file_name,variables",
    [
        ("hrrr.t12z.wrfsfcf01.grib2", ["Total_precipitation_surface_1_Hour_Accumulation"]),
        ("hrrr_24H_label.grib2", ["Total_precipitation_surface_1_Hour_Accumulation"]),
        ("anything.grb2", ["Total_precipitation_surface_24_Hour_Accumulation"]),
        ("MRMS_PrecipFlag_00.00_20250115-060000.grib2", ["PrecipFlag_altitude_above_msl"]),
    ],
)
def test_a_non_mrms_grib_with_its_variable_goes_to_vortex_as_before(
    file_name, variables, no_wheel, java_calls, tmp_path, caplog
):
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(path, tmp_path / "o.dss", variables=variables)
    assert java_calls[0]["variables"] == variables
    assert "allow_instantaneous_precip" not in caplog.text


def test_a_non_mrms_grib_listed_by_the_engine_goes_to_vortex_as_before(engine, java_calls, tmp_path):
    path = tmp_path / "hrrr.t12z.wrfsfcf01.grib2"
    path.write_bytes(b"GRIB")
    engine.variables = ["Total_precipitation_surface_1_Hour_Accumulation"]
    PrecipMrms.to_dss(path, tmp_path / "o.dss")
    assert len(java_calls) == 1


def test_an_unlistable_grib_with_no_variable_counts_as_the_default_mrms_selection(
    no_wheel, java_calls, tmp_path
):
    """The narrow case: nothing can say it is not MRMS, and the selection is an MRMS variable."""
    path = tmp_path / "hrrr.t12z.wrfsfcf01.grib2"
    path.write_bytes(b"GRIB")
    with pytest.raises(ValueError, match="If this file is not MRMS, state its variable"):
        PrecipMrms.to_dss(path, tmp_path / "o.dss")
    assert java_calls == []


def test_an_explicit_mrms_product_makes_the_rule_apply(no_wheel, java_calls, tmp_path):
    path = tmp_path / "hrrr.t12z.wrfsfcf01.grib2"
    path.write_bytes(b"GRIB")
    with pytest.raises(ValueError, match="gives no one-hour period"):
        PrecipMrms.to_dss(
            path, tmp_path / "o.dss", product="RadarOnly_QPE_01H",
            variables=["Total_precipitation_surface_1_Hour_Accumulation"],
        )
    assert java_calls == []


@pytest.mark.parametrize(
    "file_name",
    [
        "x_gaugecorr_y_qpe_z_01h_w.grib2",
        "x_radaronly_y_qpe_z_01h_w.grib2",
        "x_multisensor_y_qpe_z_01h_w.grib2",
        "RadarOnly_QPE_01H_00.00_20190520-120000.GRIB2",
        "GaugeCorr QPE 01H odd name.grib2",
    ],
)
def test_each_vortex_one_hour_rule_accepts(file_name, no_wheel, java_calls, tmp_path):
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    PrecipMrms.to_dss(path, tmp_path / "o.dss", variables=["RadarOnly_QPE_01H_altitude_above_msl"])
    assert len(java_calls) == 1


@pytest.mark.parametrize(
    "file_name",
    [
        "GaugeCorr_QPE_01H.grib2.backup",
        "RadarOnly_QPE_01H.grib2.backup",
        "MultiSensor_QPE_01H_Pass2.grib2.backup",
        "RadarOnly_QPE_01H.grib",
        "RadarOnly_QPE_01H.grb2",
        "QPE_01H_x.grib2",
        "qpe_radaronly_01h.grib2",
        "RadarOnly_01H_QPE.grib2",
    ],
)
def test_names_outside_the_vortex_rules_are_refused(file_name, no_wheel, java_calls, tmp_path):
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    with pytest.raises(ValueError, match="gives no one-hour period"):
        PrecipMrms.to_dss(path, tmp_path / "o.dss", variables=["RadarOnly_QPE_01H_altitude_above_msl"])
    assert java_calls == []


@pytest.mark.parametrize("backend", ["java", "shadow"])
@pytest.mark.parametrize("override", [False, True])
@pytest.mark.parametrize(
    "file_name,product,variables,stated",
    [
        (HOURLY_NAME, "GaugeCorr_QPE_01H", ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"], "1440 minutes"),
        (HOURLY_NAME, "GaugeCorr_QPE_01H", ["MultiSensor_QPE_72H_Pass2_altitude_above_msl"], "4320 minutes"),
        (HOURLY_NAME, "GaugeCorr_QPE_01H", ["RadarOnly_QPE_15M_altitude_above_msl"], "15 minutes"),
        (HOURLY_NAME, "RadarOnly_QPE_03H", None, "180 minutes"),
        ("MultiSensor_QPE_24H_then_01H.grib2", "GaugeCorr_QPE_01H", None, "1440 minutes"),
    ],
)
def test_a_detected_conflict_is_refused_even_with_the_override(
    backend, override, file_name, product, variables, stated, no_wheel, java_calls, tmp_path
):
    """Detectable with no wheel: only names are read here."""
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    output = tmp_path / "new_folder" / "o.dss"
    with pytest.raises(ValueError, match=stated) as info:
        PrecipMrms.to_dss(
            path, output, product=product, variables=variables, backend=backend,
            allow_instantaneous_precip=override,
        )
    message = str(info.value)
    assert "one-hour period (60 minutes)" in message
    assert file_name in message
    assert "does not allow" in message
    assert java_calls == []
    assert not output.parent.exists()


@pytest.mark.parametrize("backend", ["java", "shadow"])
def test_a_conflict_the_engine_lists_is_refused_even_with_the_override(
    backend, engine, java_calls, grib, tmp_path
):
    engine.variables = ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"]
    with pytest.raises(ValueError, match="1440 minutes"):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend=backend, allow_instantaneous_precip=True)
    assert java_calls == []


def test_a_conflict_the_vortex_listing_finds_is_refused_even_with_the_override(
    no_wheel, java_calls, monkeypatch, tmp_path
):
    path = tmp_path / "MRMS_RadarOnly_QPE_01H_00.00_20250115-060000.grib2"
    path.write_bytes(b"GRIB")
    monkeypatch.setattr(
        VortexCli, "get_grib2_variables",
        staticmethod(lambda p, **kwargs: ["RadarOnly_QPE_24H_altitude_above_msl"]),
    )
    with pytest.raises(ValueError, match="1440 minutes"):
        PrecipMrms.to_dss(path, tmp_path / "o.dss", allow_instantaneous_precip=True)
    assert java_calls == []


def test_the_override_warning_does_not_claim_there_is_no_period(no_wheel, java_calls, tmp_path, caplog):
    path = tmp_path / DAILY_NAME
    path.write_bytes(b"GRIB")
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(path, tmp_path / "o.dss", allow_instantaneous_precip=True)
    assert "with no period" not in caplog.text


def test_refusal_on_many_files_stays_readable(no_wheel, java_calls, tmp_path):
    paths = []
    for hour in range(12):
        paths.append(tmp_path / f"MRMS_MultiSensor_QPE_24H_Pass2_00.00_20240926-{hour:02d}0000.grib2")
        paths[-1].write_bytes(b"GRIB")
    with pytest.raises(ValueError, match="and 7 more") as info:
        PrecipMrms.to_dss(paths, tmp_path / "o.dss")
    assert paths[0].name in str(info.value)
    assert len(str(info.value)) < 2000


@pytest.mark.parametrize("backend", ["java", "shadow"])
def test_java_and_shadow_refuse_a_file_whose_variable_states_another_duration(
    backend, engine, java_calls, grib, tmp_path
):
    """The same detection as native: the file name says 01H, and the file's own variable says 24H."""
    engine.variables = ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"]
    output = tmp_path / "o.dss"
    with pytest.raises(ValueError, match="1440 minutes") as info:
        PrecipMrms.to_dss(grib, output, backend=backend)
    assert grib.name in str(info.value)
    assert java_calls == []
    assert engine.calls == []
    assert not output.exists()


def test_without_the_wheel_a_renamed_file_passes_the_check(no_wheel, java_calls, grib, tmp_path):
    """The stated limit. No listing exists here, and the file's name says 01H."""
    PrecipMrms.to_dss(grib, tmp_path / "o.dss")
    assert len(java_calls) == 1


def test_without_the_wheel_a_renamed_radaronly_file_is_refused_by_the_vortex_listing(
    no_wheel, java_calls, monkeypatch, tmp_path
):
    path = tmp_path / "MRMS_RadarOnly_QPE_01H_00.00_20250115-060000.grib2"
    path.write_bytes(b"GRIB")
    monkeypatch.setattr(
        VortexCli, "get_grib2_variables",
        staticmethod(lambda p, **kwargs: ["RadarOnly_QPE_24H_altitude_above_msl"]),
    )
    with pytest.raises(ValueError, match="1440 minutes"):
        PrecipMrms.to_dss(path, tmp_path / "o.dss")
    assert java_calls == []


def test_a_file_the_engine_cannot_list_falls_back_to_its_name(engine, java_calls, grib, tmp_path, caplog):
    def unreadable(path):
        raise engine.exceptions.DssError("not a GRIB2 file")

    sys.modules["ras_commander_fast_dss.gridded"].list_variables = unreadable
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss")
    assert len(java_calls) == 1
    assert "checking its name only" in caplog.text


def test_radaronly_spelling_comes_from_the_engine_if_vortex_cannot_list(
    engine, java_calls, monkeypatch, tmp_path
):
    def no_listing(path, **kwargs):
        raise RuntimeError("no Vortex")

    monkeypatch.setattr(VortexCli, "get_grib2_variables", staticmethod(no_listing))
    path = tmp_path / "MRMS_RadarOnly_QPE_01H_00.00_20250115-060000.grib2"
    path.write_bytes(b"GRIB")
    engine.variables = ["RadarOnly_QPE_01H_altitude_above_msl"]
    PrecipMrms.to_dss(path, tmp_path / "o.dss")
    assert java_calls[0]["variables"] == ["RadarOnly_QPE_01H_altitude_above_msl"]


def test_vortex_listing_takes_the_spelling_over_the_engine(engine, java_calls, monkeypatch, tmp_path):
    """The reader that imports decides: an older table spells this name differently."""
    old = "RadarOnlyQPE01H_altitude_above_msl"
    monkeypatch.setattr(VortexCli, "get_grib2_variables", staticmethod(lambda p, **kwargs: [old]))
    path = tmp_path / "MRMS_RadarOnly_QPE_01H_00.00_20250115-060000.grib2"
    path.write_bytes(b"GRIB")
    engine.variables = ["RadarOnly_QPE_01H_altitude_above_msl"]
    PrecipMrms.to_dss(path, tmp_path / "o.dss")
    assert java_calls[0]["variables"] == [old]


@pytest.mark.parametrize("file_name", [DAILY_NAME, "storm.grib2"])
def test_override_runs_java_and_warns_about_no_rain(file_name, no_wheel, java_calls, tmp_path, caplog):
    path = tmp_path / file_name
    path.write_bytes(b"GRIB")
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(path, tmp_path / "o.dss", allow_instantaneous_precip=True)
    assert len(java_calls) == 1
    warned = [r.getMessage() for r in caplog.records if "allow_instantaneous_precip" in r.getMessage()]
    assert len(warned) == 1
    assert "no rain" in warned[0]
    assert "INST-VAL" in warned[0]


def test_override_on_one_hour_changes_nothing(no_wheel, java_calls, grib, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", allow_instantaneous_precip=True)
    assert len(java_calls) == 1
    assert "no rain" not in caplog.text


def test_native_refuses_despite_the_override(engine, java_calls, tmp_path):
    path = tmp_path / DAILY_NAME
    path.write_bytes(b"GRIB")
    output = tmp_path / "new_folder" / "o.dss"
    with pytest.raises(engine.exceptions.DssUnsupportedRecordError, match="Java route only"):
        PrecipMrms.to_dss(path, output, backend="native", allow_instantaneous_precip=True)
    assert engine.calls == []
    assert java_calls == []
    assert not output.parent.exists()


def test_java_does_not_warn_on_one_hour(java_calls, grib, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(grib, tmp_path / "o.dss")
    assert not any("no rain" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Shadow control flow
# ---------------------------------------------------------------------------


def test_shadow_raises_java_failure_itself_and_does_not_run_native(engine, monkeypatch, grib, tmp_path):
    failure = RuntimeError("HEC-Vortex import failed (exit code 1)")

    def failing(**kwargs):
        raise failure

    monkeypatch.setattr(VortexCli, "import_gridded", staticmethod(failing))
    with pytest.raises(RuntimeError) as info:
        PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend="shadow")
    assert info.value is failure
    assert engine.calls == []
    assert nv.SHADOW_STATS[("unexpected", "java_failed")] == 1
    assert "exit code 1" in nv.SHADOW_RECORDS[-1]["java_error"]


def _java_writes(monkeypatch, write):
    def fake_import_gridded(**kwargs):
        output = Path(kwargs["output_dss"])
        write(output)
        return output

    monkeypatch.setattr(VortexCli, "import_gridded", staticmethod(fake_import_gridded))


# ---------------------------------------------------------------------------
# Comparison, on real DSS grids
# ---------------------------------------------------------------------------


@pytest.fixture
def real():
    return pytest.importorskip("ras_commander_fast_dss")


CELLS = np.array([[0.0, 1.5, 2.25], [3.0, 4.125, 5.5]], dtype=np.float32)


def write(path: Path, real, pathname: str = PATHNAME, cells=CELLS, version: int = 7, **overrides) -> None:
    from ras_commander_fast_dss._write import create
    from ras_commander_fast_dss._write_grid import write_grid

    if not path.exists():
        create(path, version=version)
    arguments = dict(
        grid_type="shg",
        cell_size=2000.0,
        units="MM",
        data_type="PER-CUM",
        lower_left_cell=(-200, 800),
        version=version,
    )
    arguments.update(overrides)
    write_grid(path, pathname, cells, **arguments)


def compare(tmp_path, real, java_kwargs=None, native_kwargs=None):
    java_file, native_file = tmp_path / "java.dss", tmp_path / "native.dss"
    write(java_file, real, **(java_kwargs or {}))
    write(native_file, real, **(native_kwargs or {}))
    return nv.compare_outputs(java_file, native_file)


def test_identical_files_compare_identical(real, tmp_path):
    summary = compare(tmp_path, real)
    assert summary["records"] == 1
    assert summary["differences"] == {}


def changed(cells, row, col, value):
    out = cells.copy()
    out[row, col] = value
    return out


@pytest.mark.parametrize(
    "native,fragment",
    [
        pytest.param({"cells": changed(CELLS, 1, 2, 5.5000005)}, "cells: 1 of 6 differ", id="one-ulp-cell"),
        pytest.param({"cells": changed(CELLS, 0, 0, np.nan)}, "1 in mask", id="mask"),
        pytest.param({"units": "IN"}, "data_units", id="units"),
        pytest.param({"data_type": "PER-AVER"}, "data_type", id="data-type"),
        pytest.param({"lower_left_cell": (-199, 800)}, "lower_left_cell_x", id="placement"),
        pytest.param({"cell_size": 1000.0}, "cell_size", id="cell-size"),
    ],
)
def test_a_real_difference_on_one_pathname_is_reported(real, tmp_path, native, fragment):
    """Negative controls. Each changes one thing, and the report must name it."""
    summary = compare(tmp_path, real, native_kwargs=native)
    assert summary["records"] == 1
    assert PATHNAME in summary["differences"]
    assert any(fragment in item for item in summary["differences"][PATHNAME])


def test_cells_differing_report_values_and_position(real, tmp_path):
    summary = compare(tmp_path, real, native_kwargs={"cells": changed(CELLS, 1, 2, 9.0)})
    text = " ".join(summary["differences"][PATHNAME])
    assert "[1,2]" in text and "max abs 3.5" in text


@pytest.mark.parametrize(
    "native_path,expect",
    [
        # A stamp moved an hour: the period is another pathname, so each side holds one alone.
        ("/SHG/MRMS_QPE/PRECIPITATION/26SEP2024:2200/26SEP2024:2300/GAUGECORR_QPE_01H/", "stamp"),
        # Precipitation at an instant, the record that has read as no rain.
        ("/SHG/MRMS_QPE/PRECIPITATION/26SEP2024:2200//GAUGECORR_QPE_01H/", "instant"),
        ("/SHG/MRMS_QPE/PRECIP/26SEP2024:2100/26SEP2024:2200/GAUGECORR_QPE_01H/", "c-part"),
        ("/SHG/MRMS_QPE/PRECIPITATION/26SEP2024:2100/26SEP2024:2200/OTHER/", "f-part"),
    ],
)
def test_pathnames_on_one_side_are_reported(real, tmp_path, native_path, expect):
    kwargs = {"pathname": native_path}
    if expect == "instant":
        kwargs["data_type"] = "INST-VAL"
    summary = compare(tmp_path, real, native_kwargs=kwargs)
    assert summary["records"] == 0
    assert summary["differences"][PATHNAME] == ["pathname: written by java only"]
    assert summary["differences"][native_path] == ["pathname: written by native only"]


OTHER = "/SHG/MRMS_QPE/PRECIPITATION/01JAN2020:0000/01JAN2020:0100/OLD/"


def _from_baseline(tmp_path, real, version=7):
    """A baseline holding OTHER, and two equal starting copies."""
    baseline = tmp_path / "baseline.dss"
    write(baseline, real, pathname=OTHER, version=version)
    java_file, native_file = tmp_path / "java.dss", tmp_path / "native.dss"
    shutil.copy2(baseline, java_file)
    shutil.copy2(baseline, native_file)
    return baseline, java_file, native_file


def test_an_existing_record_neither_writer_touched_counts_as_unchanged(real, tmp_path):
    baseline, java_file, native_file = _from_baseline(tmp_path, real)
    write(java_file, real)
    write(native_file, real)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline, written=[PATHNAME])
    assert summary["differences"] == {}
    assert summary["records"] == 1
    assert summary["unchanged"] == 1


@pytest.mark.parametrize("version", [6, 7])
def test_an_existing_record_java_rewrote_and_native_omitted_is_a_difference(real, tmp_path, version):
    """The reviewer's case. A pathname-only snapshot called this identical."""
    baseline, java_file, native_file = _from_baseline(tmp_path, real, version)
    write(java_file, real, version=version)
    write(java_file, real, pathname=OTHER, cells=CELLS * 2, version=version)
    write(native_file, real, version=version)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline, written=[PATHNAME])
    assert any(key.upper() == OTHER.upper() for key in summary["differences"])
    found = next(v for k, v in summary["differences"].items() if k.upper() == OTHER.upper())
    assert found[0] == "rewritten by java, omitted by native"
    assert any("cells:" in item for item in found)


def test_an_existing_record_native_rewrote_and_java_kept_is_a_difference(real, tmp_path):
    baseline, java_file, native_file = _from_baseline(tmp_path, real)
    write(java_file, real)
    write(native_file, real)
    write(native_file, real, pathname=OTHER, cells=CELLS * 2)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline, written=[PATHNAME, OTHER])
    assert summary["differences"][OTHER][0] == "rewritten by native, not by java"


def test_both_writers_rewriting_an_existing_record_alike_is_compared(real, tmp_path):
    baseline, java_file, native_file = _from_baseline(tmp_path, real)
    for path in (java_file, native_file):
        write(path, real, pathname=OTHER, cells=CELLS * 2)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline, written=[OTHER])
    assert summary["differences"] == {}
    assert summary["records"] == 1
    assert summary["unchanged"] == 0


def test_a_same_content_rewrite_native_omitted_shows_in_dss7_by_write_time(real, tmp_path):
    baseline, java_file, native_file = _from_baseline(tmp_path, real)
    # The engine's writer skips a write of equal content, as Monolith does not. Two writes stand in.
    time.sleep(0.01)
    write(java_file, real, pathname=OTHER, cells=CELLS * 2)
    write(java_file, real, pathname=OTHER)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline)
    assert summary["differences"][OTHER] == ["rewritten by java with the same content, omitted by native"]


def test_a_same_content_rewrite_native_omitted_cannot_show_in_dss6(real, tmp_path):
    """Pins the stated limit. Both outputs end the same, and DSS6 has no write time to read."""
    baseline, java_file, native_file = _from_baseline(tmp_path, real, version=6)
    write(java_file, real, pathname=OTHER, cells=CELLS * 2, version=6)
    write(java_file, real, pathname=OTHER, version=6)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline)
    assert summary["differences"] == {}
    assert summary["unchanged"] == 1


@pytest.mark.parametrize("side", ["java", "native"])
def test_an_existing_time_series_changed_by_one_writer_is_a_difference(real, tmp_path, side):
    from ras_commander_fast_dss._write import create, write_timeseries

    flow = "//P47/FLOW/01JAN2020/1HOUR/KEEP/"
    arguments = dict(start="2020-01-01T01:00:00", units="CFS", data_type="INST-VAL", version=6)
    baseline = tmp_path / "baseline.dss"
    create(baseline, version=6)
    write_timeseries(str(baseline), flow, np.array([1.0, 2.0, 3.0]), **arguments)
    java_file, native_file = tmp_path / "java.dss", tmp_path / "native.dss"
    shutil.copy2(baseline, java_file)
    shutil.copy2(baseline, native_file)
    untouched = nv.compare_outputs(java_file, native_file, baseline_file=baseline)
    assert untouched["differences"] == {} and untouched["unchanged"] == 1
    changed_file = java_file if side == "java" else native_file
    write_timeseries(str(changed_file), flow, np.array([1.0, 2.0, 4.0]), **arguments)
    summary = nv.compare_outputs(java_file, native_file, baseline_file=baseline)
    assert summary["unchanged"] == 0
    assert any("content: java and native differ" in items for items in summary["differences"].values())


def test_an_existing_record_removed_by_one_writer_is_a_difference(real, tmp_path):
    baseline, java_file, native_file = _from_baseline(tmp_path, real)
    fresh = tmp_path / "fresh.dss"
    write(fresh, real)
    summary = nv.compare_outputs(fresh, native_file, baseline_file=baseline)
    assert summary["differences"][OTHER] == ["pathname: removed by java"]


def _grid(**overrides):
    base = dict(
        dss_version=6, record_type=420, grid_type="albers", nx=2, ny=1, cell_size=2000.0,
        lower_left_cell_x=0, lower_left_cell_y=0, x_coord_of_grid_cell_zero=0.0, y_coord_of_grid_cell_zero=0.0,
        srs_name="", srs_definition_type=0, srs_definition="", data_units="MM", data_type=1,
        start_time=None, end_time=None, min_value=1.0, max_value=2.0, mean_value=1.5,
        range_limit_table=np.array([1.0]), range_counts=np.array([2]), null_value=-1.0,
        data=np.array([[1.0, 2.0]], dtype=np.float32), metadata={},
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


P2B = {"compression_method": 101001, "compression_scale_factor": 100.0, "compression_base": 0.0}
MFM = float(-np.finfo(np.float32).max)
ZLIB = {"compression_method": 26, "compression_scale_factor": MFM, "compression_base": MFM}


def test_dss6_precip_2_byte_is_compared_after_rounding():
    java = _grid(data=np.array([[1.23, 2.0]], dtype=np.float32), metadata=P2B)
    native = _grid(data=np.array([[1.2340001, 2.0]], dtype=np.float32), metadata=ZLIB)
    unexpected, expected = nv.compare_grids(java, native)
    assert unexpected == []
    assert "dss6_precip_2_byte:1" in expected


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_value", -123456.0),
        ("max_value", 999999.0),
        ("mean_value", 123456.0),
        ("range_counts", np.array([999999])),
        ("range_limit_table", np.array([999999.0])),
    ],
)
@pytest.mark.parametrize("corrupted_side", ["java", "native"])
def test_dss6_allowance_does_not_cover_statistics(field, value, corrupted_side):
    """The reviewer's negative controls, under the recognized compression pair."""
    corrupted = {field: value}
    java = _grid(metadata=P2B, **(corrupted if corrupted_side == "java" else {}))
    native = _grid(metadata=ZLIB, **(corrupted if corrupted_side == "native" else {}))
    unexpected, expected = nv.compare_grids(java, native)
    assert any(item.startswith(f"{field}:") for item in unexpected)
    assert "dss6_precip_2_byte:0" in expected


def test_dss6_rounding_does_not_hide_a_real_difference():
    java = _grid(data=np.array([[1.23, 2.0]], dtype=np.float32), metadata=P2B)
    native = _grid(data=np.array([[1.25, 2.0]], dtype=np.float32), metadata=ZLIB)
    unexpected, _ = nv.compare_grids(java, native)
    assert any(item.startswith("cells:") for item in unexpected)


@pytest.mark.parametrize(
    "field,value",
    [("compression_scale_factor", 1234.0), ("compression_base", 5678.0), ("compression_method", 987654)],
)
def test_dss6_allowance_holds_one_shape_only(field, value):
    java = _grid(metadata={**P2B, field: value})
    native = _grid(metadata=ZLIB)
    unexpected, expected = nv.compare_grids(java, native)
    assert any(f"metadata {field}" in item for item in unexpected)
    assert not any(item.startswith("dss6_precip_2_byte") for item in expected)


def test_dss7_does_not_take_the_dss6_allowance():
    java = _grid(dss_version=7, metadata=P2B)
    native = _grid(dss_version=7, metadata=ZLIB)
    unexpected, _ = nv.compare_grids(java, native)
    assert any("compression_method" in item for item in unexpected)


def test_null_value_allowance_is_the_exact_pair():
    good = nv.compare_grids(_grid(dss_version=7, null_value=0.0), _grid(dss_version=7, null_value=MFM))
    assert good[0] == [] and "null_value" in good[1]
    bad = nv.compare_grids(_grid(dss_version=7, null_value=1.0), _grid(dss_version=7, null_value=MFM))
    assert any("null_value" in item for item in bad[0])


# ---------------------------------------------------------------------------
# Shadow, end to end with stand-ins for the two writers
# ---------------------------------------------------------------------------


def _native_writes(monkeypatch, real, **write_kwargs):
    def fake_import_native(paths, output, **kwargs):
        fake_import_native.kwargs = kwargs
        write(Path(output), real, **write_kwargs)
        return [hourly_record()]

    monkeypatch.setattr(nv, "import_native", fake_import_native)
    return fake_import_native


def test_shadow_identical_returns_java_output_and_leaves_no_sidecar(real, monkeypatch, grib, tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    output = folder / "o.dss"
    _java_writes(monkeypatch, lambda path: write(path, real))
    native = _native_writes(monkeypatch, real)
    result = PrecipMrms.to_dss(grib, output, backend="shadow")
    assert result == output
    assert sorted(p.name for p in folder.iterdir()) == ["o.dss"]
    assert nv.SHADOW_STATS[("identical", "identical")] == 1
    assert native.kwargs["version"] == 7
    assert native.kwargs["align"] == "vortex"


def test_shadow_negative_control_reports_a_difference_and_keeps_java(real, monkeypatch, grib, tmp_path, caplog):
    """The acceptance control: one cell differs, the log names it, and Java's file is what returns."""
    output = tmp_path / "o.dss"
    _java_writes(monkeypatch, lambda path: write(path, real))
    _native_writes(monkeypatch, real, cells=changed(CELLS, 1, 2, 9.0))
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        result = PrecipMrms.to_dss(grib, output, backend="shadow")
    assert result == output
    assert nv.SHADOW_STATS[("unexpected", "records_differ")] == 1
    log = "\n".join(r.getMessage() for r in caplog.records)
    assert "UNEXPECTED" in log and PATHNAME in log and "cells: 1 of 6 differ" in log
    with real.open(str(output)) as handle:
        kept = handle.read_grid(PATHNAME)
    assert np.array_equal(kept.data, CELLS)


def test_shadow_native_failure_is_logged_and_java_returned(real, monkeypatch, grib, tmp_path, caplog):
    output = tmp_path / "o.dss"
    _java_writes(monkeypatch, lambda path: write(path, real))

    def failing(paths, sidecar, **kwargs):
        raise OSError("disk trouble")

    monkeypatch.setattr(nv, "import_native", failing)
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        assert PrecipMrms.to_dss(grib, output, backend="shadow") == output
    assert nv.SHADOW_STATS[("unexpected", "native_failed")] == 1
    assert "disk trouble" in "\n".join(r.getMessage() for r in caplog.records)


def test_shadow_refusal_of_other_durations_is_expected(real, monkeypatch, tmp_path):
    path = tmp_path / DAILY_NAME
    path.write_bytes(b"GRIB")
    output = tmp_path / "o.dss"
    instant = "/SHG/MRMS_QPE/PRECIPITATION/26SEP2024:2200//GAUGECORR_QPE_24H/"
    _java_writes(monkeypatch, lambda p: write(p, real, pathname=instant, data_type="INST-VAL"))
    result = PrecipMrms.to_dss(
        path, output, product="MultiSensor_QPE_24H_Pass2_00.00", backend="shadow", allow_instantaneous_precip=True
    )
    assert result == output
    assert nv.SHADOW_STATS[("expected", "native_refuses_instant_precipitation")] == 1


def test_shadow_refusal_of_a_name_with_no_period_is_expected(real, monkeypatch, tmp_path):
    source = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    renamed = tmp_path / "storm.grib2"
    source.rename(renamed)
    output = tmp_path / "o.dss"
    instant = "/SHG/MRMS_QPE/PRECIPITATION/15JAN2025:0600//GAUGECORR_QPE_01H/"
    _java_writes(monkeypatch, lambda p: write(p, real, pathname=instant, data_type="INST-VAL"))
    PrecipMrms.to_dss(renamed, output, backend="shadow", allow_instantaneous_precip=True, align="vortex")
    assert nv.SHADOW_STATS[("expected", "native_refuses_instant_precipitation")] == 1


def test_shadow_other_refusal_on_one_hour_is_unexpected(real, monkeypatch, grib, tmp_path):
    from ras_commander_fast_dss.exceptions import DssUnsupportedRecordError

    _java_writes(monkeypatch, lambda p: write(p, real))

    def refusing(paths, sidecar, **kwargs):
        raise DssUnsupportedRecordError("refused")

    monkeypatch.setattr(nv, "import_native", refusing)
    PrecipMrms.to_dss(grib, tmp_path / "o.dss", backend="shadow")
    assert nv.SHADOW_STATS[("unexpected", "native_failed")] == 1


def test_shadow_comparison_failure_never_raises(real, monkeypatch, grib, tmp_path):
    output = tmp_path / "o.dss"
    _java_writes(monkeypatch, lambda path: write(path, real))
    _native_writes(monkeypatch, real)

    def broken(*args, **kwargs):
        raise ValueError("comparison broke")

    monkeypatch.setattr(nv, "compare_outputs", broken)
    assert PrecipMrms.to_dss(grib, output, backend="shadow") == output
    assert nv.SHADOW_STATS[("unexpected", "comparison_failed")] == 1


def test_shadow_keeps_records_already_in_the_output(real, monkeypatch, grib, tmp_path):
    output = tmp_path / "o.dss"
    write(output, real, pathname=OTHER)
    _java_writes(monkeypatch, lambda path: write(path, real))
    _native_writes(monkeypatch, real)
    PrecipMrms.to_dss(grib, output, backend="shadow")
    assert nv.SHADOW_STATS[("identical", "identical")] == 1
    assert nv.SHADOW_RECORDS[-1]["unchanged"] == 1
    assert nv.SHADOW_RECORDS[-1]["records"] == 1
    with real.open(str(output)) as handle:
        assert np.array_equal(handle.read_grid(OTHER).data, CELLS)


def test_shadow_reports_an_existing_record_java_rewrote_and_native_omitted(real, monkeypatch, grib, tmp_path, caplog):
    """End to end, the reviewer's reproduction: it logged identical before the fix."""
    folder = tmp_path / "out"
    folder.mkdir()
    output = folder / "o.dss"
    write(output, real, pathname=OTHER)

    def java(path):
        write(path, real)
        write(path, real, pathname=OTHER, cells=CELLS * 2)

    _java_writes(monkeypatch, java)
    _native_writes(monkeypatch, real)
    with caplog.at_level(logging.WARNING, logger=nv.logger.name):
        PrecipMrms.to_dss(grib, output, backend="shadow")
    assert nv.SHADOW_STATS[("unexpected", "records_differ")] == 1
    assert OTHER in nv.SHADOW_RECORDS[-1]["differences"]
    assert "rewritten by java, omitted by native" in "\n".join(r.getMessage() for r in caplog.records)
    assert sorted(p.name for p in folder.iterdir()) == ["o.dss"]


def test_shadow_native_starts_from_a_copy_and_writes_the_output_never(real, monkeypatch, grib, tmp_path):
    output = tmp_path / "o.dss"
    write(output, real, pathname=OTHER)
    _java_writes(monkeypatch, lambda path: write(path, real))
    native = _native_writes(monkeypatch, real)
    seen = {}
    wrapped = nv.import_native

    def spying(paths, sidecar, **kwargs):
        seen["path"] = Path(sidecar)
        with real.open(str(sidecar)) as handle:
            seen["names"] = set(handle.catalog()["pathname"].astype(str))
        return wrapped(paths, sidecar, **kwargs)

    monkeypatch.setattr(nv, "import_native", spying)
    PrecipMrms.to_dss(grib, output, backend="shadow")
    assert seen["path"] != output
    assert seen["names"] == {OTHER}
    assert native.kwargs["version"] == 7


def test_shadow_java_failure_leaves_no_copies_and_is_itself(real, monkeypatch, grib, tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    output = folder / "o.dss"
    write(output, real, pathname=OTHER)
    failure = RuntimeError("HEC-Vortex import failed")

    def failing(**kwargs):
        raise failure

    monkeypatch.setattr(VortexCli, "import_gridded", staticmethod(failing))
    with pytest.raises(RuntimeError) as info:
        PrecipMrms.to_dss(grib, output, backend="shadow")
    assert info.value is failure
    assert sorted(p.name for p in folder.iterdir()) == ["o.dss"]


def test_shadow_runs_java_when_the_existing_output_cannot_be_copied(real, monkeypatch, grib, tmp_path):
    output = tmp_path / "o.dss"
    write(output, real, pathname=OTHER)
    _java_writes(monkeypatch, lambda path: write(path, real))
    native = _native_writes(monkeypatch, real)
    native.kwargs = None

    def no_copy(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(nv.shutil, "copy2", no_copy)
    assert PrecipMrms.to_dss(grib, output, backend="shadow") == output
    assert nv.SHADOW_STATS[("unexpected", "existing_output_not_copied")] == 1
    assert native.kwargs is None
    with real.open(str(output)) as handle:
        assert PATHNAME in set(handle.catalog()["pathname"].astype(str))


# ---------------------------------------------------------------------------
# Real MRMS files
# ---------------------------------------------------------------------------


def _sample(tmp_path: Path, pattern: str) -> Path:
    root = os.environ.get("RAS_COMMANDER_MRMS_SAMPLE_DIR")
    if not root:
        pytest.skip("RAS_COMMANDER_MRMS_SAMPLE_DIR is not set")
    found = sorted(Path(root).glob(pattern))
    if not found:
        pytest.skip(f"no sample matching {pattern}")
    copy = tmp_path / found[0].name
    shutil.copy(found[0], copy)
    return copy


@pytest.mark.parametrize("pattern", ["*MultiSensor_QPE_01H*.grib2", "*RadarOnly_QPE_01H*.grib2"])
def test_real_one_hour_file_gets_a_one_hour_period(real, tmp_path, pattern):
    grib_file = _sample(tmp_path, pattern)
    result = PrecipMrms.to_dss(grib_file, tmp_path / "o.dss", backend="native", align="vortex")
    with real.open(str(result)) as handle:
        names = list(handle.catalog()["pathname"].astype(str))
        assert len(names) == 1
        grid = handle.read_grid(names[0], max_cells=2**28)
    assert grid.data_type == 1
    assert grid.data_units == "MM"
    assert (grid.end_time - grid.start_time) == np.timedelta64(3600, "s")


@pytest.mark.parametrize("pattern", ["*QPE_24H*.grib2", "*QPE_15M*.grib2"])
def test_real_other_durations_are_refused_and_write_nothing(real, tmp_path, pattern):
    from ras_commander_fast_dss.exceptions import DssUnsupportedRecordError

    grib_file = _sample(tmp_path, pattern)
    output = tmp_path / "o.dss"
    with pytest.raises(DssUnsupportedRecordError, match="no rain"):
        PrecipMrms.to_dss(grib_file, output, backend="native", align="vortex")
    assert not output.exists()


def test_real_later_unknown_variable_leaves_nothing(real, tmp_path):
    """The reviewer's reproduction: this used to leave the first variable's record."""
    from ras_commander_fast_dss.exceptions import DssUnsupportedRecordError

    grib_file = _sample(tmp_path, "*MultiSensor_QPE_01H*.grib2")
    from ras_commander_fast_dss import gridded

    held = gridded.list_variables(str(grib_file))[0]
    output = tmp_path / "o.dss"
    with pytest.raises(DssUnsupportedRecordError, match="UnknownQPE"):
        PrecipMrms.to_dss(grib_file, output, variables=[held, "UnknownQPE"], backend="native", align="vortex")
    assert not output.exists()


def test_real_daily_file_renamed_hourly_is_refused(real, tmp_path):
    from ras_commander_fast_dss.exceptions import DssUnsupportedRecordError

    source = _sample(tmp_path, "*MultiSensor_QPE_24H*.grib2")
    renamed = tmp_path / HOURLY_NAME
    source.rename(renamed)
    output = tmp_path / "o.dss"
    with pytest.raises(DssUnsupportedRecordError, match="1440 minutes"):
        PrecipMrms.to_dss(renamed, output, backend="native", align="vortex")
    assert not output.exists()


def test_renamed_one_hour_file_is_refused_by_the_importer(real, tmp_path):
    """The name states no duration, so no window rule applies: an instant, which is refused."""
    from ras_commander_fast_dss.exceptions import DssUnsupportedRecordError

    source = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    renamed = tmp_path / "renamed.grib2"
    source.rename(renamed)
    output = tmp_path / "o.dss"
    with pytest.raises(DssUnsupportedRecordError):
        PrecipMrms.to_dss(renamed, output, backend="native", align="vortex")
    assert not output.exists()


def test_real_daily_file_renamed_hourly_is_refused_on_java(real, java_calls, tmp_path):
    source = _sample(tmp_path, "*MultiSensor_QPE_24H*.grib2")
    renamed = tmp_path / HOURLY_NAME
    source.rename(renamed)
    output = tmp_path / "o.dss"
    with pytest.raises(ValueError, match="1440 minutes"):
        PrecipMrms.to_dss(renamed, output)
    assert java_calls == []
    assert not output.exists()


def test_real_radaronly_spelling_is_read_by_the_engine(real, java_calls, monkeypatch, tmp_path):
    def no_listing(path, **kwargs):
        raise RuntimeError("no Vortex")

    monkeypatch.setattr(VortexCli, "get_grib2_variables", staticmethod(no_listing))
    source = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    PrecipMrms.to_dss(source, tmp_path / "o.dss")
    assert java_calls[0]["variables"] == ["RadarOnly_QPE_01H_altitude_above_msl"]


def test_real_incidental_label_is_not_refused_and_gets_a_period_from_native(real, java_calls, tmp_path):
    source = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    renamed = tmp_path / "24H_RadarOnly_QPE_01H_legitimate.grib2"
    source.rename(renamed)
    PrecipMrms.to_dss(renamed, tmp_path / "j.dss", variables=["RadarOnly_QPE_01H_altitude_above_msl"])
    assert len(java_calls) == 1
    result = PrecipMrms.to_dss(renamed, tmp_path / "n.dss", backend="native", align="vortex")
    with real.open(str(result)) as handle:
        name = list(handle.catalog()["pathname"].astype(str))[0]
        grid = handle.read_grid(name, max_cells=2**28)
    assert (grid.end_time - grid.start_time) == np.timedelta64(3600, "s")


def test_real_hrrr_is_not_held_to_the_mrms_rules(real, java_calls, tmp_path):
    source = _sample(tmp_path, "hrrr*wrfsfcf01*.grib2")
    stated = ["Total_precipitation_surface_1_Hour_Accumulation"]
    PrecipMrms.to_dss(source, tmp_path / "a.dss", variables=stated)
    PrecipMrms.to_dss(source, tmp_path / "b.dss")
    assert [call["variables"][0] for call in java_calls][0] == stated[0]
    assert len(java_calls) == 2


def test_real_mixed_mrms_and_hrrr_list_is_judged_file_by_file(real, java_calls, tmp_path):
    radar = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    hrrr = _sample(tmp_path, "hrrr*wrfsfcf01*.grib2")
    stated = ["RadarOnly_QPE_01H_altitude_above_msl", "Total_precipitation_surface_1_Hour_Accumulation"]
    PrecipMrms.to_dss([radar, hrrr], tmp_path / "ok.dss", variables=stated)
    assert len(java_calls) == 1
    # The MRMS file in the same list is still held to Vortex's name rule.
    backup = tmp_path / "RadarOnly_QPE_01H.grib2.backup"
    radar.rename(backup)
    with pytest.raises(ValueError, match="gives no one-hour period") as info:
        PrecipMrms.to_dss([backup, hrrr], tmp_path / "no.dss", variables=stated)
    assert "hrrr" not in str(info.value).split("refused", 1)[1].split(":", 1)[1].split(". Nothing")[0]
    assert len(java_calls) == 1


def test_a_stated_mrms_variable_still_holds_an_unnamed_file_to_the_rule(java_calls, tmp_path):
    plain = tmp_path / "storm.grib2"
    plain.write_bytes(b"GRIB")
    with pytest.raises(ValueError, match="gives no one-hour period"):
        PrecipMrms.to_dss(plain, tmp_path / "o.dss", variables=["RadarOnly_QPE_01H_altitude_above_msl"], backend="java")
    assert java_calls == []


def test_real_backup_suffix_is_refused(real, java_calls, tmp_path):
    source = _sample(tmp_path, "*RadarOnly_QPE_01H*.grib2")
    renamed = tmp_path / "RadarOnly_QPE_01H.grib2.backup"
    source.rename(renamed)
    with pytest.raises(ValueError, match="gives no one-hour period"):
        PrecipMrms.to_dss(renamed, tmp_path / "o.dss", variables=["RadarOnly_QPE_01H_altitude_above_msl"])
    assert java_calls == []


@pytest.mark.parametrize("stated", [None, ["MultiSensor_QPE_24H_Pass2_altitude_above_msl"]])
def test_real_daily_file_renamed_hourly_is_refused_with_the_override(stated, real, java_calls, tmp_path):
    source = _sample(tmp_path, "*MultiSensor_QPE_24H*.grib2")
    renamed = tmp_path / HOURLY_NAME
    source.rename(renamed)
    with pytest.raises(ValueError, match="1440 minutes"):
        PrecipMrms.to_dss(renamed, tmp_path / "o.dss", variables=stated, allow_instantaneous_precip=True)
    assert java_calls == []
