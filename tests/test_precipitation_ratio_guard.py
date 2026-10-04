"""Offline regression coverage for retained gridded-precipitation ARFs."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

from ras_commander import RasPrecipHdf, RasUnsteady


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "precipitation"
    / "gdal_netcdf_davis"
    / "DavisStormSystem.gui_imported.u01"
)
PRECIP_PATH = "Event Conditions/Meteorology/Precipitation"
RATIO = 0.8768


def _sha256(path: Path) -> str | None:
    """Return a whole-file fingerprint, including a missing-file sentinel."""
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cloned_davis(tmp_path: Path, retained_in: str) -> tuple[Path, SimpleNamespace]:
    """Copy the offline Davis fixture and inject its cloned design-plan ARF."""
    unsteady = tmp_path / "DavisStormSystem.u01"
    text = FIXTURE.read_text(encoding="utf-8")
    text = "\n".join(
        line
        for line in text.splitlines()
        if not line.startswith("Met BC=Precipitation|Ratio=")
    ) + "\n"
    if retained_in in {"text", "both"}:
        text += f"Met BC=Precipitation|Ratio={RATIO}\n"
    unsteady.write_text(text, encoding="utf-8")

    if retained_in in {"hdf", "both"}:
        with h5py.File(Path(f"{unsteady}.hdf"), "w") as hdf:
            hdf.require_group(PRECIP_PATH).attrs["Ratio"] = np.float32(RATIO)

    return unsteady, SimpleNamespace(
        project_folder=tmp_path,
        project_name="DavisStormSystem",
        check_initialized=lambda: None,
    )


def _call_generic(writer: str, unsteady: Path, ras_object: SimpleNamespace) -> None:
    if writer == "netcdf":
        RasUnsteady.set_gridded_precipitation(
            unsteady, "missing.nc", ras_object=ras_object
        )
    elif writer in {"geotiff", "grib"}:
        getattr(RasUnsteady, f"set_gridded_precipitation_{writer}")(
            unsteady,
            f"missing.{writer}",
            timestamps=["2024-01-01 01:00"],
            units="mm",
            value_type="amount",
            first_timestep_hours=1.0,
            ras_object=ras_object,
        )
    elif writer == "dss":
        RasUnsteady.configure_gridded_dss_precipitation(
            unsteady, "rain.dss", "/A/B/PRECIP///F/", ras_object=ras_object
        )
    else:
        RasPrecipHdf.write_gridded_precip_raster(
            Path(f"{unsteady}.hdf"),
            np.zeros((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
        )


@pytest.mark.parametrize("writer", ["netcdf", "geotiff", "grib", "dss", "hdf"])
@pytest.mark.parametrize("retained_in", ["text", "hdf", "both"])
def test_generic_gridded_precipitation_rejects_retained_arf(
    tmp_path, writer, retained_in
):
    unsteady, ras_object = _cloned_davis(tmp_path, retained_in)
    text_before = unsteady.read_bytes()
    hdf_path = Path(f"{unsteady}.hdf")
    hdf_before = hdf_path.read_bytes() if hdf_path.exists() else None

    with pytest.raises(ValueError, match=r"historic=True \(or ratio=1.0\)") as exc:
        _call_generic(writer, unsteady, ras_object)

    assert "0.8768" in str(exc.value)
    assert unsteady.read_bytes() == text_before
    assert (hdf_path.read_bytes() if hdf_path.exists() else None) == hdf_before


def test_direct_hdf_historic_write_replaces_hdf_ratio_when_text_is_unit(tmp_path, caplog):
    unsteady, _ = _cloned_davis(tmp_path, "hdf")
    hdf_path = Path(f"{unsteady}.hdf")
    with unsteady.open("a", encoding="utf-8", newline="") as text:
        text.write("Met BC=Precipitation|Ratio=1\n")

    with caplog.at_level("WARNING"):
        RasPrecipHdf.write_gridded_precip_raster(
            hdf_path,
            np.zeros((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
            historic=True,
        )

    with h5py.File(hdf_path, "r") as hdf:
        assert hdf[PRECIP_PATH].attrs["Ratio"] == pytest.approx(1.0)
    assert "0.8768" in caplog.text


@pytest.mark.parametrize("retained_in", ["text", "hdf", "both"])
def test_direct_hdf_historic_ratio_mismatch_raises_without_mutating_either_file(
    tmp_path, retained_in
):
    """The payload writer cannot safely repair its plaintext counterpart."""
    unsteady, _ = _cloned_davis(tmp_path, retained_in)
    hdf_path = Path(f"{unsteady}.hdf")
    text_before, hdf_before = _sha256(unsteady), _sha256(hdf_path)

    with pytest.raises(ValueError, match="RasUnsteady"):
        RasPrecipHdf.write_gridded_precip_raster(
            hdf_path,
            np.zeros((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
            historic=True,
        )

    assert _sha256(unsteady) == text_before
    assert _sha256(hdf_path) == hdf_before


def test_direct_hdf_explicit_design_ratio_mismatch_raises_without_mutating_either_file(
    tmp_path,
):
    unsteady, _ = _cloned_davis(tmp_path, "both")
    hdf_path = Path(f"{unsteady}.hdf")
    text_before, hdf_before = _sha256(unsteady), _sha256(hdf_path)

    with pytest.raises(ValueError, match="RasUnsteady"):
        RasPrecipHdf.write_gridded_precip_raster(
            hdf_path,
            np.zeros((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
            ratio=0.9,
        )

    assert _sha256(unsteady) == text_before
    assert _sha256(hdf_path) == hdf_before


def test_direct_hdf_skipped_payload_repairs_ratio_without_rewriting_payload(tmp_path):
    unsteady, _ = _cloned_davis(tmp_path, "hdf")
    hdf_path = Path(f"{unsteady}.hdf")
    with unsteady.open("a", encoding="utf-8", newline="") as text:
        text.write("Met BC=Precipitation|Ratio=1\n")

    RasPrecipHdf.write_gridded_precip_raster(
        hdf_path,
        np.zeros((1, 1, 1), dtype=np.float32),
        [pd.Timestamp("2024-01-01")],
        0.0,
        1.0,
        1.0,
        None,
        "mm",
        require_met_bc_block=False,
        historic=True,
    )
    with h5py.File(hdf_path, "a") as hdf:
        hdf[PRECIP_PATH].attrs["Ratio"] = np.float32(RATIO)
    with h5py.File(hdf_path, "r") as hdf:
        payload_before = hashlib.sha256(
            hdf[f"{PRECIP_PATH}/Imported Raster Data/Values"][...].tobytes()
        ).hexdigest()

    result = RasPrecipHdf.write_gridded_precip_raster(
        hdf_path,
        np.ones((1, 1, 1), dtype=np.float32),
        [pd.Timestamp("2024-01-01")],
        0.0,
        1.0,
        1.0,
        None,
        "mm",
        require_met_bc_block=False,
        historic=True,
    )

    assert result.skipped
    with h5py.File(hdf_path, "r") as hdf:
        assert hdf[PRECIP_PATH].attrs["Ratio"] == pytest.approx(1.0)
        payload_after = hashlib.sha256(
            hdf[f"{PRECIP_PATH}/Imported Raster Data/Values"][...].tobytes()
        ).hexdigest()
    assert payload_after == payload_before


def test_direct_hdf_skipped_payload_ratio_mismatch_raises_without_mutation(tmp_path):
    unsteady, _ = _cloned_davis(tmp_path, "hdf")
    hdf_path = Path(f"{unsteady}.hdf")
    with unsteady.open("a", encoding="utf-8", newline="") as text:
        text.write("Met BC=Precipitation|Ratio=1\n")
    RasPrecipHdf.write_gridded_precip_raster(
        hdf_path,
        np.zeros((1, 1, 1), dtype=np.float32),
        [pd.Timestamp("2024-01-01")],
        0.0,
        1.0,
        1.0,
        None,
        "mm",
        require_met_bc_block=False,
        historic=True,
    )
    unsteady.write_text(
        unsteady.read_text(encoding="utf-8").replace("Ratio=1\n", f"Ratio={RATIO}\n"),
        encoding="utf-8",
    )
    text_before, hdf_before = _sha256(unsteady), _sha256(hdf_path)

    with pytest.raises(ValueError, match="RasUnsteady"):
        RasPrecipHdf.write_gridded_precip_raster(
            hdf_path,
            np.ones((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
            historic=True,
        )

    assert _sha256(unsteady) == text_before
    assert _sha256(hdf_path) == hdf_before


def test_explicit_design_ratio_is_honored_and_logged(tmp_path, caplog):
    unsteady, ras_object = _cloned_davis(tmp_path, "both")

    with caplog.at_level("INFO"):
        RasUnsteady.configure_gridded_dss_precipitation(
            unsteady,
            "rain.dss",
            "/A/B/PRECIP///F/",
            ratio=RATIO,
            ras_object=ras_object,
        )

    assert f"Met BC=Precipitation|Ratio={RATIO}" in unsteady.read_text(encoding="utf-8")
    with h5py.File(Path(f"{unsteady}.hdf"), "r") as hdf:
        assert hdf[PRECIP_PATH].attrs["Ratio"] == pytest.approx(RATIO)
    assert "explicit precipitation Ratio=0.8768" in caplog.text


def test_direct_hdf_historic_rejects_nonunit_ratio(tmp_path):
    unsteady, _ = _cloned_davis(tmp_path, "both")

    with pytest.raises(ValueError, match="historic=True requires ratio=1.0"):
        RasPrecipHdf.write_gridded_precip_raster(
            Path(f"{unsteady}.hdf"),
            np.zeros((1, 1, 1), dtype=np.float32),
            [pd.Timestamp("2024-01-01")],
            0.0,
            1.0,
            1.0,
            None,
            "mm",
            require_met_bc_block=False,
            historic=True,
            ratio=0.9,
        )
