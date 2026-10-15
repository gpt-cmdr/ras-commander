"""Configuration coverage; these tests do not qualify vendor GDAL ingestion."""
from pathlib import Path
import shutil

import h5py
import pytest

from ras_commander import RasPrj, RasUnsteady
from ras_commander.precip import PrecipCapabilities

FIXTURES = Path(__file__).parent / "fixtures/precipitation/gdal_netcdf_davis"
PRECIP = "Event Conditions/Meteorology/Precipitation"


@pytest.fixture
def project(tmp_path):
    # Use the real native-import fixture's text and NetCDF. Omit its imported
    # sidecar deliberately: a clean stage is needed to exercise vendor ingestion.
    unsteady = tmp_path / "Davis.u01"
    shutil.copyfile(FIXTURES / "DavisStormSystem.gui_imported.u01", unsteady)
    source = tmp_path / "Precipitation/rain.nc"
    source.parent.mkdir()
    shutil.copyfile(FIXTURES / "clb704_precip_5step.nc", source)
    return unsteady, source


def test_native_configuration_leaves_source_unchanged_and_authors_no_values(project):
    unsteady, source = project
    source_before = source.read_bytes()
    RasUnsteady.configure_gridded_gdal_precipitation(
        unsteady, r"Precipitation\rain.nc", "APCP_surface", historic=True
    )
    config = RasUnsteady.get_met_precipitation_config(unsteady)
    assert config["gdal_filename"] == r".\Precipitation\rain.nc"
    assert config["gdal_group"] == "APCP_surface"
    assert config["source"] == "GDAL Raster File(s)"
    with h5py.File(str(unsteady) + ".hdf", "r") as hdf:
        assert len(hdf[PRECIP]) == 0
        assert hdf[PRECIP].attrs["GDAL Datasetname"] == b"APCP_surface"
        assert hdf[PRECIP].attrs["Ratio"] == 1.0
        assert "Attributes" in hdf["Event Conditions/Meteorology"]
    assert source.read_bytes() == source_before
    assert PrecipCapabilities.for_version("6.6").qualification_for(
        "netcdf", route="native"
    ) == "qualified_windows_and_wine"


def test_number_resolution_and_idempotency(project):
    unsteady, source = project
    prj = unsteady.with_suffix(".prj")
    prj.write_text("Proj Title=Davis\nUnsteady File=u01\n")
    obj = RasPrj()
    obj.initialize(unsteady.parent, "6.6", load_results_summary=False,
                   load_hdf_metadata=False)
    # Native file paths use the common project resolver.
    RasUnsteady.configure_gridded_gdal_precipitation(
        "01", source, "APCP_surface", ras_object=obj, ratio=1.0
    )
    first = unsteady.read_bytes()
    RasUnsteady.configure_gridded_gdal_precipitation(
        unsteady, source, "APCP_surface", ratio=1.0
    )
    assert unsteady.read_bytes() == first


@pytest.mark.parametrize("child", ["Imported Raster Data/Values", "Values"])
def test_rejects_cached_precipitation_without_mutation(project, child):
    unsteady, source = project
    hdf_path = Path(str(unsteady) + ".hdf")
    with h5py.File(hdf_path, "w") as hdf:
        hdf.create_dataset(f"{PRECIP}/{child}", data=[[25.4]])
    before = unsteady.read_bytes(), hdf_path.read_bytes()
    with pytest.raises(ValueError, match="mask native GDAL"):
        RasUnsteady.configure_gridded_gdal_precipitation(
            unsteady, source, "APCP_surface", historic=True
        )
    assert (unsteady.read_bytes(), hdf_path.read_bytes()) == before


@pytest.mark.parametrize("selector", ["", None, "precip\nPrecipitation Mode=Disable"])
def test_invalid_selector_does_not_modify_project(project, selector):
    unsteady, source = project
    before = unsteady.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.configure_gridded_gdal_precipitation(unsteady, source, selector)
    assert unsteady.read_bytes() == before
    assert not Path(str(unsteady) + ".hdf").exists()


@pytest.mark.parametrize("case", ["missing", "geotiff", "5.x", "ratio"])
def test_preflight_failures_leave_text_unchanged(project, case):
    unsteady, source = project
    if case == "missing":
        source = source.with_name("missing.nc")
    elif case == "geotiff":
        source = source.with_suffix(".tif")
    elif case == "5.x":
        unsteady.write_text("Flow Title=Rain\nProgram Version=5.07\n")
    before = unsteady.read_bytes()
    with pytest.raises((ValueError, FileNotFoundError)):
        RasUnsteady.configure_gridded_gdal_precipitation(
            unsteady, source, "APCP_surface", ratio=-1 if case == "ratio" else 1.0
        )
    assert unsteady.read_bytes() == before
    assert not Path(str(unsteady) + ".hdf").exists()


def test_native_import_rejects_existing_payload_without_changing_it(project):
    unsteady, source = project
    RasUnsteady.configure_gridded_gdal_precipitation(
        unsteady, source, "APCP_surface", historic=True
    )
    sidecar = Path(str(unsteady) + ".hdf")
    with h5py.File(sidecar, "a") as hdf:
        hdf.create_dataset(PRECIP + "/Imported Raster Data/Values", data=[[1.0]])
    before = sidecar.read_bytes(), unsteady.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        RasUnsteady.import_gridded_gdal_precipitation(
            unsteady, units="mm", hecras_dir=unsteady.parent
        )
    assert (sidecar.read_bytes(), unsteady.read_bytes()) == before


@pytest.mark.parametrize("data_type,units", [("unknown", "mm"), ("inst-val", "mm/hr"), ("per-cum", "mm"), ("per-avg", "mm"),
                                            ("cumulative", "mm/hr")])
def test_native_import_rejects_unimplemented_or_invalid_semantics(project, data_type, units):
    unsteady, source = project
    before = unsteady.read_bytes()
    with pytest.raises(ValueError):
        RasUnsteady.import_gridded_gdal_precipitation(
            unsteady, units=units, data_type=data_type, hecras_dir=unsteady.parent
        )
    assert unsteady.read_bytes() == before
    assert not Path(str(unsteady) + ".hdf").exists()


def test_inspection_reads_retained_native_fixture():
    from ras_commander import RasPrecipHdf

    receipt = RasPrecipHdf.inspect_gridded_precipitation(
        FIXTURES / "DavisStormSystem.gui_imported.p02.precipitation.hdf"
    )
    rows = receipt["datasets"]
    horizontal = rows[PRECIP + "/Imported Raster Data/Values"]
    vertical = rows[PRECIP + "/Imported Raster Data/Values (Vertical)"]
    assert horizontal["shape"] == [5, 6]
    assert horizontal["sha256"] == vertical["sha256"]
    assert horizontal["maximum"] == 11.25
    assert horizontal["final_nonzero"] == 6


def test_inspection_reports_missing_hdf(tmp_path):
    from ras_commander import RasPrecipHdf

    receipt = RasPrecipHdf.inspect_gridded_precipitation(tmp_path / "absent.hdf")
    assert receipt["exists"] is False
    assert receipt["datasets"] == {}
