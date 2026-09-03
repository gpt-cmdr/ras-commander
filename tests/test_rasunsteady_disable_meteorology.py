from pathlib import Path

import h5py
import numpy as np
import pytest

from ras_commander import RasUnsteady


def _write_event_hdf(path: Path, *, include_event_conditions: bool = True) -> Path:
    with h5py.File(path, "w") as hdf:
        if not include_event_conditions:
            hdf.create_group("Geometry")
            return path
        met = hdf.require_group("Event Conditions/Meteorology")
        met.require_group("Evapotranspiration").attrs["Enabled"] = np.uint8(1)
        met.require_group("Precipitation").attrs["Enabled"] = np.uint8(1)
        met.require_group("Wind Speed").attrs["Enabled"] = np.uint8(1)
        met["Evapotranspiration"].create_dataset("Values", data=[1.0, 2.0])
    return path


def test_disable_meteorology_updates_text_sidecar_and_compiled_tmp(tmp_path):
    unsteady = tmp_path / "Model.u01"
    unsteady.write_bytes(
        b"Flow Title=Clone\r\n"
        b"Program Version=6.60\r\n"
        b"Precipitation Mode=Enable\r\n"
        b"Met BC=Precipitation|Mode=Gridded\r\n"
        b"Met BC=Precipitation|Gridded Source=DSS\r\n"
        b"Wind Mode=Enable\r\n"
        b"Met BC=Evapotranspiration|Mode=Point Gage\r\n"
        b"Met BC=Evapotranspiration|Point Time Series=Station A\r\n"
        b"Boundary Location=,,,,,Area,,BC,\r\n"
    )
    sidecar = _write_event_hdf(Path(str(unsteady) + ".hdf"))
    compiled = _write_event_hdf(tmp_path / "Model.p01.tmp.hdf")

    evidence = RasUnsteady.disable_meteorology(
        unsteady,
        compiled_plan_hdf=compiled,
    )

    raw = unsteady.read_bytes()
    assert raw.count(b"Precipitation Mode=Disable\r\n") == 1
    assert raw.count(b"Met BC=Precipitation|Mode=None\r\n") == 1
    assert raw.count(b"Wind Mode=Disable\r\n") == 1
    assert raw.count(b"Met BC=Evapotranspiration|Mode=Disable\r\n") == 1
    assert b"Met BC=Precipitation|Gridded Source=" not in raw
    assert b"Met BC=Evapotranspiration|Point Time Series=Station A\r\n" in raw
    assert raw.endswith(b"\r\n")
    assert len(evidence["hdf_targets"]) == 2

    with h5py.File(sidecar, "r") as hdf:
        met = hdf["Event Conditions/Meteorology"]
        assert all(
            int(item.attrs["Enabled"]) == 0
            for item in met.values()
            if isinstance(item, h5py.Group)
        )
        assert list(met["Evapotranspiration/Values"][()]) == [1.0, 2.0]

    with h5py.File(compiled, "r") as hdf:
        assert "Event Conditions/Meteorology" not in hdf
    compiled_evidence = next(
        item
        for item in evidence["hdf_targets"]
        if item["representation"] == "compiled_plan"
    )
    assert compiled_evidence["meteorology_group_removed"] is True
    assert sorted(compiled_evidence["removed_groups"]) == [
        "Evapotranspiration",
        "Precipitation",
        "Wind Speed",
    ]


def test_disable_meteorology_is_idempotent(tmp_path):
    unsteady = tmp_path / "Model.u01"
    unsteady.write_text(
        "Flow Title=Clone\n"
        "Program Version=6.60\n"
        "Boundary Location=,,,,,Area,,BC,",
        encoding="utf-8",
    )

    RasUnsteady.disable_meteorology(unsteady)
    first = unsteady.read_bytes()
    RasUnsteady.disable_meteorology(unsteady)

    assert unsteady.read_bytes() == first
    lines = unsteady.read_text(encoding="utf-8").splitlines()
    assert lines.count("Precipitation Mode=Disable") == 1
    assert lines.count("Met BC=Precipitation|Mode=None") == 1
    assert lines.count("Wind Mode=Disable") == 1
    assert lines.count("Met BC=Evapotranspiration|Mode=Disable") == 1


def test_disable_meteorology_compiled_target_is_idempotent(tmp_path):
    unsteady = tmp_path / "Model.u01"
    unsteady.write_text(
        "Flow Title=Clone\nProgram Version=6.60\n",
        encoding="utf-8",
    )
    compiled = _write_event_hdf(tmp_path / "Model.p01.tmp.hdf")

    first = RasUnsteady.disable_meteorology(
        unsteady,
        compiled_plan_hdf=compiled,
    )
    second = RasUnsteady.disable_meteorology(
        unsteady,
        compiled_plan_hdf=compiled,
    )

    assert first["hdf_targets"][-1]["meteorology_group_removed"] is True
    assert second["hdf_targets"][-1]["meteorology_group_removed"] is False
    with h5py.File(compiled, "r") as hdf:
        assert "Event Conditions/Meteorology" not in hdf


@pytest.mark.parametrize("filename", ["Model.p01.hdf", "Model.u01.hdf"])
def test_disable_meteorology_rejects_non_tmp_compiled_target_without_mutation(
    tmp_path,
    filename,
):
    unsteady = tmp_path / "Model.u01"
    original = b"Flow Title=Clone\nProgram Version=6.60\n"
    unsteady.write_bytes(original)
    target = _write_event_hdf(tmp_path / filename)

    with pytest.raises(ValueError, match=r"\*\.tmp\.hdf"):
        RasUnsteady.disable_meteorology(
            unsteady,
            compiled_plan_hdf=target,
        )

    assert unsteady.read_bytes() == original


def test_disable_meteorology_rejects_tmp_without_event_conditions(tmp_path):
    unsteady = tmp_path / "Model.u01"
    original = b"Flow Title=Clone\nProgram Version=6.60\n"
    unsteady.write_bytes(original)
    target = _write_event_hdf(
        tmp_path / "Model.p01.tmp.hdf",
        include_event_conditions=False,
    )

    with pytest.raises(ValueError, match="lacks /Event Conditions"):
        RasUnsteady.disable_meteorology(
            unsteady,
            compiled_plan_hdf=target,
        )

    assert unsteady.read_bytes() == original
