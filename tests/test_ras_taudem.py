"""Tests for RasTauDem: discovery and argument checks always; delineation when TauDEM is installed."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")
pytest.importorskip("geopandas")

from ras_commander.terrain import RasTauDem, TauDemDelineation, TauDemNotFoundError  # noqa: E402

CRS_FT = "EPSG:2277"  # NAD83 / Texas Central (ftUS)


def _write_dem(path: Path, z: np.ndarray, cell: float, crs: str = CRS_FT, north_up: bool = True) -> Path:
    from rasterio.transform import Affine

    e = -cell if north_up else cell
    transform = Affine(cell, 0.0, 2_000_000.0, 0.0, e, 13_000_000.0)
    with rasterio.open(path, "w", driver="GTiff", height=z.shape[0], width=z.shape[1], count=1,
                       dtype="float32", crs=crs, transform=transform, nodata=-9999.0) as sink:
        sink.write(z.astype("float32"), 1)
    return path


def _two_valley_dem(n: int = 120) -> np.ndarray:
    """Main valley draining south, joined by a side valley from the east."""
    rows, cols = np.mgrid[0:n, 0:n].astype(float)
    centre = n / 2.0
    main = 100.0 + 0.5 * (n - rows) + 2.0 * np.abs(cols - centre)
    side = 100.0 + 0.5 * (n - n * 0.4) + 0.5 * (cols - centre) + 2.0 * np.abs(rows - n * 0.4)
    side = np.where(cols > centre, side, np.inf)
    return np.minimum(main, side)


def _taudem_available() -> bool:
    try:
        RasTauDem.get_taudem_info()
        return True
    except TauDemNotFoundError:
        return False


def test_terrain_import_does_not_load_taudem_or_geopandas():
    import subprocess
    import sys

    script = "\n".join([
        "import sys",
        "import ras_commander.terrain as t",
        "assert 'ras_commander.terrain.RasTauDem' not in sys.modules",
        "assert 'geopandas' not in sys.modules",
        "assert t.RasTauDem.__name__ == 'RasTauDem'",
        "assert 'RasTauDem' in t.__all__",
    ])
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_named_folder_raises(tmp_path):
    with pytest.raises(TauDemNotFoundError, match="TauDEM folder not found"):
        RasTauDem.get_taudem_info(taudem_dir=tmp_path / "absent")


def test_folder_without_tools_raises(tmp_path):
    with pytest.raises(TauDemNotFoundError, match="PitRemove"):
        RasTauDem.get_taudem_info(taudem_dir=tmp_path)


def test_env_var_names_the_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_TAUDEM_DIR", str(tmp_path))
    with pytest.raises(TauDemNotFoundError, match="RAS_COMMANDER_TAUDEM_DIR"):
        RasTauDem.get_taudem_info()


def test_named_missing_mpiexec_raises(tmp_path):
    for tool in ("PitRemove", "D8FlowDir", "AreaD8", "Threshold", "StreamNet"):
        (tmp_path / f"{tool}.exe").write_bytes(b"")
    info = RasTauDem.get_taudem_info(taudem_dir=tmp_path, mpiexec_path=None)
    assert set(info["executables"]) == {"PitRemove", "D8FlowDir", "AreaD8", "Threshold", "StreamNet"}
    with pytest.raises(TauDemNotFoundError, match="mpiexec_path"):
        RasTauDem.get_taudem_info(taudem_dir=tmp_path, mpiexec_path=tmp_path / "mpiexec.exe")


@pytest.mark.parametrize("kwargs, message", [
    ({"stream_area_sqmi": 0}, "stream_area_sqmi"),
    ({"stream_area_sqmi": float("nan")}, "stream_area_sqmi"),
    ({"cell_size": -1.0}, "cell_size"),
    ({"num_processes": 0}, "num_processes"),
])
def test_argument_checks(tmp_path, kwargs, message):
    dem = _write_dem(tmp_path / "dem.tif", _two_valley_dem(20), 10.0)
    with pytest.raises(ValueError, match=message):
        RasTauDem.delineate(dem, tmp_path / "out", **kwargs)


def test_refuses_nonempty_dest(tmp_path):
    dem = _write_dem(tmp_path / "dem.tif", _two_valley_dem(20), 10.0)
    out = tmp_path / "out"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        RasTauDem.delineate(dem, out)


@pytest.mark.skipif(not _taudem_available(), reason="TauDEM is not installed")
def test_refuses_geographic_dem(tmp_path):
    dem = _write_dem(tmp_path / "dem.tif", _two_valley_dem(20), 0.001, crs="EPSG:4269")
    with pytest.raises(ValueError, match="projected"):
        RasTauDem.delineate(dem, tmp_path / "out")


@pytest.mark.skipif(not _taudem_available(), reason="TauDEM is not installed")
@pytest.mark.parametrize("num_processes", [1, 2])
def test_delineates_two_valleys(tmp_path, num_processes):
    cell = 50.0  # ft
    z = _two_valley_dem(120)
    dem = _write_dem(tmp_path / "dem.tif", z, cell)
    before = dem.read_bytes()
    result = RasTauDem.delineate(dem, tmp_path / "taudem", stream_area_sqmi=0.05,
                                 num_processes=num_processes)
    assert isinstance(result, TauDemDelineation)
    assert dem.read_bytes() == before
    streams, catchments = result.streams, result.catchments
    assert {"LINKNO", "DSLINKNO", "USLINKNO1", "USLINKNO2", "strmOrder", "Length", "Slope",
            "DSContArea", "contributing_area_sqmi"}.issubset(streams.columns)
    assert len(streams) >= 3  # main stem above and below the confluence, plus the side valley
    assert streams["LINKNO"].is_unique
    outlets = streams[streams["DSLINKNO"] < 0]
    assert len(outlets) == 1
    # The outlet link carries the largest contributing area and starts at the DEM's low edge.
    assert outlets["DSContArea"].iloc[0] == streams["DSContArea"].max()
    x0, y0 = outlets.geometry.iloc[0].coords[0]
    assert y0 < 13_000_000.0 - 0.8 * 120 * cell
    # Catchments: one per link, together covering (nearly) the whole DEM.
    assert set(catchments["LINKNO"]) == set(streams["LINKNO"])
    dem_area_sqmi = (120 * cell) ** 2 * (1200 / 3937) ** 2 / 0.3048 ** 2 / 5280.0 ** 2
    assert math.isclose(catchments["area_sqmi"].sum(), dem_area_sqmi, rel_tol=0.1)
    summary = result.to_dict()
    assert summary["stream_count"] == len(streams)
    assert len(summary["commands"]) == 5
    assert (tmp_path / "taudem" / "taudem.log").is_file()


@pytest.mark.skipif(not _taudem_available(), reason="TauDEM is not installed")
def test_cell_size_resamples(tmp_path):
    dem = _write_dem(tmp_path / "dem.tif", _two_valley_dem(120), 25.0)
    result = RasTauDem.delineate(dem, tmp_path / "taudem", stream_area_sqmi=0.05, cell_size=50.0)
    assert result.cell_size == pytest.approx(50.0)
    with rasterio.open(result.raster_paths["dem"]) as src:
        assert src.shape == (60, 60)
