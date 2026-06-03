"""
Tests for HdfResultsSediment: 2D mobile-bed (sediment) plan-HDF results reader.

These tests build a minimal synthetic plan HDF that mimics the HEC-RAS
``Sediment Bed`` output block plus the embedded geometry datasets the reader
needs, so they run fast and deterministically without HEC-RAS. Real-HEC-RAS
integration coverage lives in examples/230 and examples/232.

Covered:
- unit-system detection (SI vs US Customary) and native-unit volumes
- zero-area perimeter/ghost cells dropping out of volume integrals and extrema
- GeoDataFrame column/attrs contracts
- optional active-layer gradation present vs. missing (clear ValueError)
- timeseries DataArray shape/coords
"""

from __future__ import annotations

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")
pytest.importorskip("geopandas")

from ras_commander.hdf import HdfResultsSediment

_BED = ("Results/Unsteady/Output/Output Blocks/Sediment Bed/"
        "Unsteady Time Series/2D Flow Areas")


def _write_synthetic_plan_hdf(path, *, si_units, area="Perimeter 1",
                              with_d50=True):
    """Create a minimal plan-HDF-like file the reader can parse.

    5 cells; 2 of them (indices 2 and 4) are zero-area ghost cells.
    Final bed change = [-1, +2, +5(ghost), -0.5, +9(ghost)].
    Surface area     = [10, 20,  0,        30,    0].
    """
    surface_area = np.array([10.0, 20.0, 0.0, 30.0, 0.0], dtype="f4")
    centers = np.array([[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]], dtype="f8")
    # two time steps; final row is the one read by default (time_index=-1)
    bed_change = np.array([[0, 0, 0, 0, 0],
                           [-1.0, 2.0, 5.0, -0.5, 9.0]], dtype="f4")
    bed_elev = bed_change + 100.0
    d50 = np.array([[2.0] * 5, [2.5, 3.0, 0.0, 4.0, 0.0]], dtype="f4")

    with h5py.File(path, "w") as f:
        f.attrs["Units System"] = np.bytes_("SI Units" if si_units else "US Customary")
        geom = f.create_group("Geometry")
        geom.attrs["SI Units"] = np.bytes_("True" if si_units else "False")
        ga = geom.create_group(f"2D Flow Areas/{area}")
        ga.create_dataset("Cells Surface Area", data=surface_area)
        ga.create_dataset("Cells Center Coordinate", data=centers)

        base = f.create_group(f"{_BED}/{area}")
        base.create_dataset("Cell Bed Change", data=bed_change)
        base.create_dataset("Cell Bed Elevation", data=bed_elev)
        base.create_dataset("Cell Initial Bed Elevation", data=bed_elev[:1])
        if with_d50:
            base.create_dataset("Cell Active Layer Percentile Diameters - D50", data=d50)
        f.create_dataset(
            "Results/Unsteady/Output/Output Blocks/Sediment Bed/"
            "Unsteady Time Series/Time", data=np.array([0.0, 1.0]))
    return path


@pytest.fixture
def si_hdf(tmp_path):
    return str(_write_synthetic_plan_hdf(tmp_path / "Weise.p01.hdf", si_units=True,
                                         area="2DArea"))


@pytest.fixture
def us_hdf(tmp_path):
    return str(_write_synthetic_plan_hdf(tmp_path / "River.p01.hdf", si_units=False))


@pytest.fixture
def us_hdf_no_d50(tmp_path):
    return str(_write_synthetic_plan_hdf(tmp_path / "River.p02.hdf", si_units=False,
                                         with_d50=False))


class TestDiscovery:
    def test_is_sediment_plan(self, us_hdf):
        assert HdfResultsSediment.is_sediment_plan(us_hdf) is True

    def test_is_sediment_plan_false(self, tmp_path):
        empty = tmp_path / "Empty.p01.hdf"
        with h5py.File(empty, "w") as f:
            f.create_group("Results")
        assert HdfResultsSediment.is_sediment_plan(str(empty)) is False

    def test_get_sediment_mesh_areas(self, si_hdf):
        assert HdfResultsSediment.get_sediment_mesh_areas(si_hdf) == ["2DArea"]


class TestVolumes:
    def test_us_units_and_values(self, us_hdf):
        df = HdfResultsSediment.get_bed_change_volumes(us_hdf)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["length_unit"] == "ft"
        # only the 3 non-zero-area cells count
        assert row["n_cells"] == 3
        # net = -1*10 + 2*20 + -0.5*30 = 15 ; erosion = -25 ; deposition = 40
        assert row["net_bed_volume"] == pytest.approx(15.0)
        assert row["erosion_volume"] == pytest.approx(-25.0)
        assert row["deposition_volume"] == pytest.approx(40.0)
        # ghost cell (+9) must NOT become max_deposition; wet max is +2
        assert row["max_deposition"] == pytest.approx(2.0)
        assert row["max_scour"] == pytest.approx(-1.0)

    def test_si_unit_detection(self, si_hdf):
        df = HdfResultsSediment.get_bed_change_volumes(si_hdf)
        assert df.iloc[0]["length_unit"] == "m"


class TestPerCell:
    def test_cell_bed_change_gdf_contract(self, us_hdf):
        gdf = HdfResultsSediment.get_cell_bed_change(us_hdf)
        assert list(gdf.columns) == ["mesh_name", "cell_id", "bed_change",
                                     "surface_area", "geometry"]
        assert len(gdf) == 5
        assert gdf.attrs["length_unit"] == "ft"
        assert gdf.attrs["units"] == "ft"
        # final-timestep values
        assert gdf["bed_change"].tolist() == [-1.0, 2.0, 5.0, -0.5, 9.0]

    def test_cell_bed_elevation(self, si_hdf):
        gdf = HdfResultsSediment.get_cell_bed_elevation(si_hdf)
        assert "bed_elevation" in gdf.columns
        assert gdf.attrs["length_unit"] == "m"


class TestActiveLayer:
    def test_d50_present(self, us_hdf):
        gdf = HdfResultsSediment.get_active_layer_grain_class(us_hdf, "D50")
        assert "d50_mm" in gdf.columns
        assert gdf.attrs["units"] == "mm"  # grain size always mm

    def test_d50_missing_raises(self, us_hdf_no_d50):
        with pytest.raises(ValueError, match="not found"):
            HdfResultsSediment.get_active_layer_grain_class(us_hdf_no_d50, "D50")

    def test_invalid_percentile(self, us_hdf):
        with pytest.raises(ValueError, match="D10, D50, or D90"):
            HdfResultsSediment.get_active_layer_grain_class(us_hdf, "D55")


class TestTimeseries:
    def test_timeseries_shape(self, us_hdf):
        da = HdfResultsSediment.get_cell_bed_change_timeseries(us_hdf)
        assert da.dims == ("time", "cell_id")
        assert da.shape == (2, 5)
        assert da.attrs["units"] == "ft"
        assert list(da.coords["time"].values) == [0.0, 1.0]
