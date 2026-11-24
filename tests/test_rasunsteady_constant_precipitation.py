"""Tests for RasUnsteady.set_constant_precipitation().

Constant precipitation is a testing/commissioning helper (rain-on-grid mesh
shakedown, numerical sensitivity, CI fixtures), not an engineering-deliverable
forcing. These tests cover the .u## text write, the .u##.hdf sidecar update,
round-trip through get_met_precipitation_config(), insertion into a minimal
file, and input validation. They require only h5py + numpy (no HEC-RAS/pyjnius).
"""

import logging
from pathlib import Path

import pytest

h5py = pytest.importorskip("h5py")
np = pytest.importorskip("numpy")


def _write_unsteady(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _decode(value):
    if isinstance(value, bytes):
        return value.decode("utf-8").rstrip("\x00")
    if isinstance(value, np.bytes_):
        return bytes(value).decode("utf-8").rstrip("\x00")
    if isinstance(value, np.generic):
        return value.item()
    return value


@pytest.fixture
def davis_style_unsteady(tmp_path):
    body = (
        "Flow Title=Full System Rain w/ Pump\n"
        "Program Version=6.60\n"
        "Use Restart= 0 \n"
        "Precipitation Mode=Disable\n"
        "Wind Mode=Disable\n"
        "Met BC=Precipitation|Mode=Hyetograph\n"
        "Met BC=Evapotranspiration|Mode=Disable\n"
        "Met BC=Precipitation|Expanded View=-1\n"
        "Met BC=Precipitation|Constant Value=1\n"
        "Met BC=Precipitation|Constant Units=in/hr\n"
        "Met BC=Precipitation|Gridded Source=DSS\n"
        "Boundary Location=                ,                ,        ,        ,                ,DavisSystem     ,                ,Rainfall                        ,                                \n"
        "Interval=1HOUR\n"
        "Precipitation Hydrograph= 2 \n"
        "    0.00    0.00\n"
    )
    unsteady_path = _write_unsteady(tmp_path / "DavisStormSystem.u01", body)
    with h5py.File(str(unsteady_path) + ".hdf", "w") as hdf:
        precip = hdf.require_group("Event Conditions/Meteorology/Precipitation")
        precip.attrs["Enabled"] = np.uint8(0)
        precip.attrs["Mode"] = np.bytes_("Hyetograph")
    return unsteady_path


def test_set_constant_precipitation_updates_text_and_hdf(
    davis_style_unsteady, caplog
):
    from ras_commander import RasUnsteady

    with caplog.at_level(logging.INFO, logger="ras_commander.RasUnsteady"):
        RasUnsteady.set_constant_precipitation(
            davis_style_unsteady, value=0.25, units="mm/hr"
        )

    lines = davis_style_unsteady.read_text(encoding="utf-8").splitlines()
    assert "Precipitation Mode=Enable" in lines
    assert "Met BC=Precipitation|Mode=Constant" in lines
    assert "Met BC=Precipitation|Constant Value=0.25" in lines
    assert "Met BC=Precipitation|Constant Units=mm/hr" in lines

    with h5py.File(str(davis_style_unsteady) + ".hdf", "r") as hdf:
        precip = hdf["Event Conditions/Meteorology/Precipitation"]
        assert _decode(precip.attrs["Enabled"]) == 1
        assert _decode(precip.attrs["Mode"]) == "Constant"
        assert _decode(precip.attrs["Constant Value"]) == pytest.approx(0.25)
        assert _decode(precip.attrs["Constant Units"]) == "mm/hr"
        # The shared HDF writer also registers the Meteorology attributes index.
        attrs = hdf["Event Conditions/Meteorology/Attributes"][()]
        assert _decode(attrs[0]["Variable"]) == "Precipitation"

    info_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "ras_commander.RasUnsteady"
        and record.levelno == logging.INFO
    ]
    assert any("DavisStormSystem.u01" in message for message in info_messages)
    assert any("DavisStormSystem.u01.hdf" in message for message in info_messages)
    assert all(
        str(davis_style_unsteady.parent) not in message
        for message in info_messages
    )


def test_round_trips_through_get_met_precipitation_config(davis_style_unsteady):
    from ras_commander import RasUnsteady

    RasUnsteady.set_constant_precipitation(davis_style_unsteady)  # defaults: 1.0 in/hr

    config = RasUnsteady.get_met_precipitation_config(davis_style_unsteady)
    assert config["enabled"] is True
    assert config["precipitation_mode"] == "Enable"
    assert config["mode"] == "Constant"
    assert config["constant_value"] == pytest.approx(1.0)
    assert config["constant_units"] == "in/hr"
    assert config["raw"]["Constant Value"] == "1"
    assert config["hdf_attributes"]["Enabled"] == 1
    assert config["hdf_attributes"]["Mode"] == "Constant"
    assert config["hdf_attributes"]["Constant Value"] == pytest.approx(1.0)
    assert config["hdf_attributes"]["Constant Units"] == "in/hr"


@pytest.mark.parametrize("ratio", [1.0, 0.5, None])
def test_explicit_constant_ratio_updates_both_representations_or_preserves_default(
    davis_style_unsteady, ratio
):
    from ras_commander import RasUnsteady

    path = davis_style_unsteady
    path.write_text(
        path.read_text().replace(
            "Boundary Location=",
            "Met BC=Precipitation|Ratio=0.8768\nBoundary Location=",
            1,
        )
    )
    sidecar = Path(str(path) + ".hdf")
    with h5py.File(sidecar, "r+") as h:
        h["Event Conditions/Meteorology/Precipitation"].attrs["Ratio"] = np.float32(
            0.8768
        )
    boundary = path.read_text().split("Boundary Location=", 1)[1]
    kwargs = {} if ratio is None else {"ratio": ratio}
    RasUnsteady.set_constant_precipitation(path, value=0.01, units="in/hr", **kwargs)
    expected = 0.8768 if ratio is None else ratio
    config = RasUnsteady.get_met_precipitation_config(path)
    assert float(config["raw"]["Ratio"]) == pytest.approx(expected)
    assert config["hdf_attributes"]["Ratio"] == pytest.approx(expected)
    assert config["constant_value"] == pytest.approx(0.01)
    assert boundary in path.read_text().split("Boundary Location=", 1)[1]
    with h5py.File(sidecar) as h:
        assert h["Event Conditions/Meteorology/Precipitation"].attrs[
            "Ratio"
        ].dtype == np.dtype("float32")


@pytest.mark.parametrize(
    "ratio", [0, -1, float("nan"), float("inf"), True, "1", 1e100, 1e-100, 10**1000]
)
def test_invalid_constant_ratio_leaves_text_and_sidecar_unchanged(
    davis_style_unsteady, ratio
):
    from ras_commander import RasUnsteady

    path = davis_style_unsteady
    sidecar = Path(str(path) + ".hdf")
    before = (path.read_bytes(), sidecar.read_bytes())
    with pytest.raises(ValueError, match="ratio"):
        RasUnsteady.set_constant_precipitation(path, ratio=ratio)
    assert (path.read_bytes(), sidecar.read_bytes()) == before


@pytest.mark.parametrize(
    "ratio",
    [1e-9, np.finfo(np.float32).max, np.nextafter(np.float32(0), np.float32(1))],
)
def test_constant_ratio_text_roundtrips_native_single(davis_style_unsteady, ratio):
    from ras_commander import RasUnsteady

    path = davis_style_unsteady
    RasUnsteady.set_constant_precipitation(path, ratio=ratio)
    config = RasUnsteady.get_met_precipitation_config(path)
    text_ratio = float(config["raw"]["Ratio"])
    assert np.isfinite(text_ratio) and text_ratio > 0
    assert np.float32(text_ratio) == np.float32(ratio)
    assert config["hdf_attributes"]["Ratio"] == float(np.float32(ratio))


def test_inserts_missing_keys_into_minimal_file(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_path = _write_unsteady(
        tmp_path / "Minimal.u01",
        (
            "Flow Title=Minimal\n"
            "Program Version=6.60\n"
            "Boundary Location=                ,                ,        ,        ,                ,Area            ,                ,Rain                            ,                                \n"
        ),
    )

    RasUnsteady.set_constant_precipitation(unsteady_path)

    lines = unsteady_path.read_text(encoding="utf-8").splitlines()
    assert "Precipitation Mode=Enable" in lines
    assert "Met BC=Precipitation|Mode=Constant" in lines
    assert "Met BC=Precipitation|Constant Value=1" in lines
    assert "Met BC=Precipitation|Constant Units=in/hr" in lines
    # Keys are inserted after the Flow Title line.
    assert lines.index("Precipitation Mode=Enable") > lines.index("Flow Title=Minimal")


_BASELINE_MODES = (
    "Met BC=Evapotranspiration|Mode=None",
    "Met BC=Air Density|Mode=Constant",
    "Met BC=Air Pressure|Mode=Constant",
)

# Header of BaldEagleCrkMulti2D BaldEagleDamBrk.u13: a 5.00 file with no
# meteorology records. HEC-RAS 7.0.1 rejected the pre-fix constant write
# with "Error processing event conditions".
_NO_MET_BODY = (
    "Flow Title=Single 2D Area\n"
    "Program Version=5.00\n"
    "Use Restart= 0 \n"
    "Boundary Location=                ,                ,        ,        ,                ,BaldEagleCr     ,                ,DSNormalDepth   \n"
    "Friction Slope=0.0003\n"
)


def test_completes_baseline_met_modes_for_file_without_meteorology(tmp_path):
    """Regression: constant rain on a file without met records must run in 7.0."""
    from ras_commander import RasUnsteady

    unsteady_path = _write_unsteady(tmp_path / "NoMet.u13", _NO_MET_BODY)

    RasUnsteady.set_constant_precipitation(unsteady_path, value=1.0, units="in/hr")

    lines = unsteady_path.read_text(encoding="utf-8").splitlines()
    for record in _BASELINE_MODES:
        assert lines.count(record) == 1, record
    met_indices = [i for i, line in enumerate(lines) if line.startswith("Met BC=")]
    # Met BC records stay contiguous and follow the Precipitation Mode header.
    assert met_indices == list(range(met_indices[0], met_indices[-1] + 1))
    assert lines.index("Precipitation Mode=Enable") < met_indices[0]
    assert met_indices[-1] < next(
        i for i, line in enumerate(lines) if line.startswith("Boundary Location=")
    )
    # Non-meteorology content is unchanged.
    non_met = [
        line for line in lines
        if not line.startswith(("Met BC=", "Precipitation Mode="))
    ]
    assert non_met == _NO_MET_BODY.splitlines()


def test_preserves_explicit_baseline_met_modes(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_path = _write_unsteady(
        tmp_path / "Explicit.u01",
        _NO_MET_BODY
        + "Met BC=Evapotranspiration|Mode=Constant\n"
        + "Met BC=Air Density|Mode=Point\n"
        + "Met BC=Air Pressure|Mode=\n",
    )

    RasUnsteady.set_constant_precipitation(unsteady_path)

    lines = unsteady_path.read_text(encoding="utf-8").splitlines()
    assert lines.count("Met BC=Evapotranspiration|Mode=Constant") == 1
    assert lines.count("Met BC=Air Density|Mode=Point") == 1
    assert "Met BC=Evapotranspiration|Mode=None" not in lines
    assert "Met BC=Air Density|Mode=Constant" not in lines
    # A blank mode is completed with the HEC-RAS default.
    assert lines.count("Met BC=Air Pressure|Mode=Constant") == 1
    assert "Met BC=Air Pressure|Mode=" not in lines


def test_set_met_precipitation_mode_constant_completes_baseline_modes(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_path = _write_unsteady(tmp_path / "Mode.u01", _NO_MET_BODY)

    RasUnsteady.set_met_precipitation_mode(unsteady_path, "Constant")

    lines = unsteady_path.read_text(encoding="utf-8").splitlines()
    assert "Met BC=Precipitation|Mode=Constant" in lines
    for record in _BASELINE_MODES:
        assert lines.count(record) == 1, record


def test_constant_write_is_idempotent(tmp_path):
    from ras_commander import RasUnsteady

    unsteady_path = _write_unsteady(tmp_path / "Twice.u01", _NO_MET_BODY)
    RasUnsteady.set_constant_precipitation(unsteady_path, value=0.5)
    first = unsteady_path.read_text(encoding="utf-8")
    RasUnsteady.set_constant_precipitation(unsteady_path, value=0.5)
    assert unsteady_path.read_text(encoding="utf-8") == first


def test_validates_inputs(davis_style_unsteady):
    from ras_commander import RasUnsteady

    with pytest.raises(ValueError, match="units must be"):
        RasUnsteady.set_constant_precipitation(davis_style_unsteady, units="ft/day")

    with pytest.raises(ValueError, match=">= 0"):
        RasUnsteady.set_constant_precipitation(davis_style_unsteady, value=-0.1)

    with pytest.raises(ValueError, match="finite"):
        RasUnsteady.set_constant_precipitation(
            davis_style_unsteady, value=float("nan")
        )
