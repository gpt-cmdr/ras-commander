"""Unit gates for native RASMapper land-cover contracts."""

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest

import ras_commander._land_classification_polygon_native as polygon_native
import ras_commander._landcover_native as landcover_native
from ras_commander._land_classification_polygon_native import (
    _normalize_single_polygon,
    _normalize_variable_values,
    _prepare_class,
    _require_landcover_sidecar,
    add_land_classification_polygon,
)
from ras_commander._landcover_native import (
    _native_extent,
    _validate_property_tables_postcondition,
    validate_native_landcover,
)
from ras_commander.geom import GeomLandCover, GeomPreprocessor
from ras_commander.hdf import HdfLandCover


class _Extent:
    def __init__(self, *values):
        self.values = values


def test_native_extent_uses_rasmapper_constructor_order():
    extent = _native_extent(
        (1.0, 2.0, 11.0, 22.0),
        buffer_distance=3.0,
        extent_cls=_Extent,
    )

    assert extent.values == (14.0, -2.0, 25.0, -1.0)


def test_single_member_hole_free_multipolygon_normalizes():
    shapely = pytest.importorskip("shapely")
    polygon = shapely.box(0, 0, 10, 10)

    result = _normalize_single_polygon(shapely.MultiPolygon([polygon]))

    assert result.geom_type == "Polygon"
    assert len(result.interiors) == 0
    assert result.equals(polygon)


def test_classification_polygon_interior_ring_is_rejected():
    shapely = pytest.importorskip("shapely")
    polygon = shapely.Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
        holes=[[(2, 2), (2, 4), (4, 4), (4, 2), (2, 2)]],
    )

    with pytest.raises(NotImplementedError, match="interior rings"):
        _normalize_single_polygon(polygon)


def test_add_and_update_reject_holes_before_backup_or_native_load(
    tmp_path: Path,
    monkeypatch,
):
    shapely = pytest.importorskip("shapely")
    sidecar = tmp_path / "LandCover.hdf"
    with h5py.File(sidecar, "w") as hdf:
        hdf.attrs["LC Type"] = "LandCover"
    original_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()
    polygon = shapely.Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)],
        holes=[[(2, 2), (2, 4), (4, 4), (4, 2), (2, 2)]],
    )

    def fail_if_loaded(*_args, **_kwargs):
        raise AssertionError("native layer must not load for unsupported holes")

    monkeypatch.setattr(polygon_native, "_load_native_layer", fail_if_loaded)
    for operation in (
        lambda: polygon_native.add_land_classification_polygon(
            sidecar,
            polygon,
            "Open Water",
            hecras_version="7.0",
        ),
        lambda: polygon_native.update_land_classification_polygon(
            sidecar,
            0,
            polygon=polygon,
            hecras_version="7.0",
        ),
    ):
        with pytest.raises(NotImplementedError, match="interior rings"):
            operation()

    assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == original_hash
    assert not list(
        tmp_path.glob("LandCover.classification_polygon.*.backup.hdf")
    )


def test_true_multipart_classification_polygon_is_rejected():
    shapely = pytest.importorskip("shapely")
    multipart = shapely.MultiPolygon(
        [
            shapely.box(0, 0, 1, 1),
            shapely.box(2, 2, 3, 3),
        ]
    )

    with pytest.raises(ValueError, match="True multipart"):
        _normalize_single_polygon(multipart)


def test_invalid_classification_polygon_is_rejected():
    shapely = pytest.importorskip("shapely")
    bowtie = shapely.Polygon([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])

    with pytest.raises(ValueError, match="not valid"):
        _normalize_single_polygon(bowtie)


def test_geodataframe_crs_must_match_sidecar(tmp_path: Path):
    geopandas = pytest.importorskip("geopandas")
    shapely = pytest.importorskip("shapely")
    sidecar = tmp_path / "LandCover.hdf"
    with h5py.File(sidecar, "w") as hdf:
        hdf.attrs["Projection"] = "EPSG:2271"
    polygon = geopandas.GeoDataFrame(
        geometry=[shapely.box(-77, 40, -76, 41)],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="does not match"):
        _normalize_single_polygon(polygon, layer_hdf_path=sidecar)


def test_raw_shapely_polygon_is_explicitly_assumed_to_use_sidecar_crs(
    tmp_path: Path,
):
    shapely = pytest.importorskip("shapely")
    sidecar = tmp_path / "LandCover.hdf"
    with h5py.File(sidecar, "w") as hdf:
        hdf.attrs["Projection"] = "EPSG:2271"
    polygon = shapely.box(2_000_000, 300_000, 2_001_000, 301_000)

    result = _normalize_single_polygon(polygon, layer_hdf_path=sidecar)

    assert result.equals(polygon)


def test_polygon_variable_aliases_and_ranges_are_validated():
    assert _normalize_variable_values(
        {"mannings_n": 0.045, "percent_impervious": 25}
    ) == {"ManningsN": 0.045, "Percent Impervious": 25.0}

    with pytest.raises(ValueError, match="ManningsN must be positive"):
        _normalize_variable_values({"mannings_n": 0})
    with pytest.raises(ValueError, match="between 0 and 100"):
        _normalize_variable_values({"percent_impervious": 101})


def test_polygon_sidecar_edit_fails_clearly_for_ras5(tmp_path: Path):
    with pytest.raises(NotImplementedError, match="set_mannings_region_polygons"):
        add_land_classification_polygon(
            tmp_path / "LandCover.hdf",
            object(),
            "Channel",
            hecras_version="5.0.7",
        )


@pytest.mark.parametrize("version", ["6.0", "6.6", "7.0", "7.0.1"])
def test_polygon_version_gate_accepts_only_qualified_families(version: str):
    polygon_native._require_modern_rasmapper(version)


@pytest.mark.parametrize("version", ["7.1", "8.0", "10.0"])
def test_polygon_version_gate_rejects_future_unqualified_families(version: str):
    with pytest.raises(RuntimeError, match="qualified only"):
        polygon_native._require_modern_rasmapper(version)


@pytest.mark.parametrize("layer_type", ["Soils", "InfiltrationSCSCurveNumber", None])
def test_polygon_mutation_is_narrowed_to_qualified_landcover_sidecars(
    tmp_path: Path,
    layer_type: str | None,
):
    sidecar = tmp_path / "Classification.hdf"
    with h5py.File(sidecar, "w") as hdf:
        if layer_type is not None:
            hdf.attrs["LC Type"] = layer_type

    with pytest.raises(NotImplementedError, match="LC Type='LandCover'"):
        _require_landcover_sidecar(sidecar)


def test_qualified_landcover_sidecar_type_is_accepted(tmp_path: Path):
    sidecar = tmp_path / "LandCover.hdf"
    with h5py.File(sidecar, "w") as hdf:
        hdf.attrs["LC Type"] = "LandCover"

    _require_landcover_sidecar(sidecar)


def test_polygon_crud_rejects_undefined_classification():
    class _Column:
        def __init__(self, name):
            self.ColumnName = name

    class _Table:
        Columns = [_Column("ID"), _Column("Name"), _Column("ManningsN")]
        Rows = []

    class _LandCoverLayer:
        @staticmethod
        def IsValidClassificationName(_name):
            return True

        @staticmethod
        def GetClassificationVariablesAsDataTable(_classification, _parameters):
            return _Table()

    class _Layer:
        Classification = object()
        Parameters = object()

    with pytest.raises(ValueError, match="existing classes only"):
        _prepare_class(
            _LandCoverLayer,
            _Layer(),
            class_name="Undefined",
            class_id=None,
            variable_values={"mannings_n": 0.04},
        )


def test_polygon_crud_validates_existing_class_id():
    class _Column:
        def __init__(self, name):
            self.ColumnName = name

    class _Table:
        Columns = [_Column("ID"), _Column("Name")]
        Rows = [{"ID": 11, "Name": "Open Water"}]

    class _LandCoverLayer:
        @staticmethod
        def IsValidClassificationName(_name):
            return True

        @staticmethod
        def GetClassificationVariablesAsDataTable(_classification, _parameters):
            return _Table()

    class _Layer:
        Classification = object()
        Parameters = object()

    with pytest.raises(ValueError, match="does not match HEC-RAS class"):
        _prepare_class(
            _LandCoverLayer,
            _Layer(),
            class_name="Open Water",
            class_id=12,
            variable_values=None,
        )


def test_native_polygon_save_failure_restores_hdf_and_native_backup(
    tmp_path: Path,
    monkeypatch,
):
    shapely = pytest.importorskip("shapely")
    sidecar = tmp_path / "LandCover.hdf"
    with h5py.File(sidecar, "w") as hdf:
        hdf.attrs["LC Type"] = "LandCover"
        hdf.create_dataset("Original", data=np.asarray([1, 2, 3]))
    native_backup = tmp_path / "LandCover.backup.hdf"
    native_backup.write_bytes(b"pre-existing native backup")
    original_hash = hashlib.sha256(sidecar.read_bytes()).hexdigest()

    class _Column:
        def __init__(self, name):
            self.ColumnName = name

    class _Table:
        Columns = [_Column("ID"), _Column("Name")]
        Rows = [{"ID": 11, "Name": "Open Water"}]

    class _LandCoverLayer:
        @staticmethod
        def IsValidClassificationName(_name):
            return True

        @staticmethod
        def GetClassificationVariablesAsDataTable(_classification, _parameters):
            return _Table()

    class _Layer:
        Classification = object()
        Parameters = object()

    class _FailingPolygonLayer:
        @staticmethod
        def FeatureCount():
            return 0

        @staticmethod
        def AddFeature(_polygon):
            return None

        @staticmethod
        def SetFeatureName(_index, _name):
            return None

        @staticmethod
        def SaveFeatureTable():
            with h5py.File(sidecar, "a") as hdf:
                hdf.create_dataset("Partial Native Save", data=np.asarray([99]))
            native_backup.write_bytes(b"overwritten by failed save")
            return False

    monkeypatch.setattr(
        polygon_native,
        "_load_native_layer",
        lambda *_args, **_kwargs: (
            _LandCoverLayer,
            _Layer(),
            _FailingPolygonLayer(),
        ),
    )
    monkeypatch.setattr(
        polygon_native,
        "_to_native_polygon",
        lambda _geometry: object(),
    )

    with pytest.raises(RuntimeError, match="failed to save"):
        polygon_native.add_land_classification_polygon(
            sidecar,
            shapely.box(0, 0, 10, 10),
            "Open Water",
            hecras_version="7.0",
        )

    assert hashlib.sha256(sidecar.read_bytes()).hexdigest() == original_hash
    assert native_backup.read_bytes() == b"pre-existing native backup"
    with h5py.File(sidecar, "r") as hdf:
        assert "Partial Native Save" not in hdf
    durable_backups = list(
        tmp_path.glob("LandCover.classification_polygon.*.backup.hdf")
    )
    assert len(durable_backups) == 1
    assert hashlib.sha256(durable_backups[0].read_bytes()).hexdigest() == original_hash


def test_polygon_transactions_create_distinct_durable_backups(
    tmp_path: Path,
    monkeypatch,
):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.write_bytes(b"original")
    monkeypatch.setattr(
        polygon_native,
        "datetime",
        SimpleNamespace(
            now=lambda: SimpleNamespace(
                strftime=lambda _format: "20260725_155650_676039"
            )
        ),
    )

    with polygon_native._hdf_transaction(sidecar, backup=True):
        pass
    with polygon_native._hdf_transaction(sidecar, backup=True):
        pass

    backups = list(
        tmp_path.glob("LandCover.classification_polygon.*.backup.hdf")
    )
    assert len(backups) == 2
    assert all(path.read_bytes() == b"original" for path in backups)


def test_polygon_transaction_rolls_back_base_exception(tmp_path: Path):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.write_bytes(b"original")

    with pytest.raises(KeyboardInterrupt):
        with polygon_native._hdf_transaction(sidecar, backup=True):
            sidecar.write_bytes(b"partial")
            raise KeyboardInterrupt

    assert sidecar.read_bytes() == b"original"


def test_landcover_parameter_rejection_restores_partial_native_save(
    tmp_path: Path,
    monkeypatch,
):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.write_bytes(b"original sidecar")
    native_backup = tmp_path / "LandCover.backup.hdf"
    native_backup.write_bytes(b"original native backup")

    table = SimpleNamespace(
        Rows=[{"Name": "Open Water", "ManningsN": 0.04}]
    )

    class _Layer:
        Classification = object()
        Parameters = object()

        @staticmethod
        def TryAssigningNewParamtersUsingTable(_table, _apply):
            sidecar.write_bytes(b"partial native save")
            native_backup.write_bytes(b"partial native backup")
            return False

    class _LandCoverLayer:
        LandCoverType = SimpleNamespace(LandCover=object())

        @staticmethod
        def TryLoadLayer(*_args):
            return True, _Layer(), ""

        @staticmethod
        def GetClassificationVariablesAsDataTable(*_args):
            return table

    monkeypatch.setattr(
        landcover_native,
        "find_hecras_install",
        lambda _version: tmp_path,
    )
    monkeypatch.setattr(landcover_native, "load_clr", lambda _install: None)
    monkeypatch.setitem(
        sys.modules,
        "RasMapperLib",
        SimpleNamespace(LandCoverLayer=_LandCoverLayer),
    )

    with pytest.raises(RuntimeError, match="rejected"):
        landcover_native.set_landcover_parameters(
            sidecar,
            {"Open Water": 0.08},
            hecras_version="6.6",
        )

    assert sidecar.read_bytes() == b"original sidecar"
    assert native_backup.read_bytes() == b"original native backup"
    backups = list(
        tmp_path.glob("LandCover.native_parameters.*.backup.hdf")
    )
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original sidecar"


def test_classification_reload_mismatch_restores_partial_native_save(
    tmp_path: Path,
    monkeypatch,
):
    sidecar = tmp_path / "Infiltration.hdf"
    sidecar.write_bytes(b"original sidecar")

    class _Columns:
        def __init__(self):
            self._items = [
                SimpleNamespace(ColumnName="Name"),
                SimpleNamespace(ColumnName="Curve Number"),
            ]
            self.Count = len(self._items)

        def __getitem__(self, index):
            return self._items[index]

    requested_table = SimpleNamespace(
        Columns=_Columns(),
        Rows=[{"Name": "Class A", "Curve Number": 70.0}],
    )
    mismatched_table = SimpleNamespace(
        Columns=_Columns(),
        Rows=[{"Name": "Class A", "Curve Number": 71.0}],
    )

    class _EditingClassification:
        pass

    class _ReloadedClassification:
        pass

    class _EditingLayer:
        Classification = _EditingClassification()
        Parameters = object()

        @staticmethod
        def TryAssigningNewParamtersUsingTable(_table, _apply):
            sidecar.write_bytes(b"partial native save")
            return True

    class _ReloadedLayer:
        Classification = _ReloadedClassification()
        Parameters = object()

    layers = [_EditingLayer(), _ReloadedLayer()]

    class _LandCoverLayer:
        LandCoverType = SimpleNamespace(
            InfiltrationSCSCurveNumber=object()
        )

        @staticmethod
        def TryLoadLayer(*_args):
            return True, layers.pop(0), ""

        @staticmethod
        def GetClassificationVariablesAsDataTable(
            classification,
            _parameters,
        ):
            return (
                requested_table
                if isinstance(classification, _EditingClassification)
                else mismatched_table
            )

    monkeypatch.setattr(
        landcover_native,
        "find_hecras_install",
        lambda _version: tmp_path,
    )
    monkeypatch.setattr(landcover_native, "load_clr", lambda _install: None)
    monkeypatch.setitem(
        sys.modules,
        "RasMapperLib",
        SimpleNamespace(LandCoverLayer=_LandCoverLayer),
    )

    updates = pd.DataFrame(
        {"Name": ["Class A"], "Curve Number": [77.0]}
    )
    with pytest.raises(RuntimeError, match="did not persist"):
        landcover_native.set_classification_parameters(
            sidecar,
            updates,
            layer_type="infiltration_scs",
            hecras_version="6.6",
        )

    assert sidecar.read_bytes() == b"original sidecar"


def test_native_sidecar_transactions_are_unique_and_restore_base_exception(
    tmp_path: Path,
    monkeypatch,
):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.write_bytes(b"original sidecar")
    native_backup = tmp_path / "LandCover.backup.hdf"
    native_backup.write_bytes(b"original native backup")
    monkeypatch.setattr(
        landcover_native,
        "datetime",
        SimpleNamespace(
            now=lambda: SimpleNamespace(
                strftime=lambda _format: "20260726_140409_423519"
            )
        ),
    )

    with landcover_native._sidecar_transaction(sidecar):
        pass
    with landcover_native._sidecar_transaction(sidecar):
        pass

    backups = list(
        tmp_path.glob("LandCover.native_parameters.*.backup.hdf")
    )
    assert len(backups) == 2

    with pytest.raises(KeyboardInterrupt):
        with landcover_native._sidecar_transaction(sidecar):
            sidecar.write_bytes(b"partial sidecar")
            native_backup.write_bytes(b"partial native backup")
            raise KeyboardInterrupt

    assert sidecar.read_bytes() == b"original sidecar"
    assert native_backup.read_bytes() == b"original native backup"


def test_classification_property_reload_mismatch_restores_native_save(
    tmp_path: Path,
    monkeypatch,
):
    sidecar = tmp_path / "Infiltration.hdf"
    sidecar.write_bytes(b"original sidecar")

    class _Columns:
        def __init__(self):
            self._items = [SimpleNamespace(ColumnName="Name")]
            self.Count = 1

        def __getitem__(self, index):
            return self._items[index]

    table = SimpleNamespace(
        Columns=_Columns(),
        Rows=[{"Name": "Class A"}],
    )

    class _EditingLayer:
        Classification = object()
        Parameters = object()

        @staticmethod
        def TrySetPropertyValue(_name, _value):
            return True

        @staticmethod
        def Save():
            sidecar.write_bytes(b"partial property save")
            return None

    class _ReloadedLayer:
        Classification = object()
        Parameters = object()

        @staticmethod
        def TryGetPropertyValue(_name, _value):
            return True, 2.0

    layers = [_EditingLayer(), _ReloadedLayer()]

    class _LandCoverLayer:
        LandCoverType = SimpleNamespace(
            InfiltrationSCSCurveNumber=object()
        )

        @staticmethod
        def TryLoadLayer(*_args):
            return True, layers.pop(0), ""

        @staticmethod
        def GetClassificationVariablesAsDataTable(*_args):
            return table

    monkeypatch.setattr(
        landcover_native,
        "find_hecras_install",
        lambda _version: tmp_path,
    )
    monkeypatch.setattr(landcover_native, "load_clr", lambda _install: None)
    monkeypatch.setitem(
        sys.modules,
        "RasMapperLib",
        SimpleNamespace(LandCoverLayer=_LandCoverLayer),
    )

    with pytest.raises(RuntimeError, match="properties"):
        landcover_native.set_classification_parameters(
            sidecar,
            pd.DataFrame({"Name": ["Class A"]}),
            layer_type="infiltration_scs",
            hecras_version="6.6",
            properties={"Example Property": 1.0},
        )

    assert sidecar.read_bytes() == b"original sidecar"


@pytest.mark.parametrize("legacy", [True, False])
def test_validate_native_landcover_accepts_native_layout(
    tmp_path: Path,
    legacy: bool,
):
    rasterio = pytest.importorskip("rasterio")
    hdf_path = tmp_path / "LandCover.hdf"
    tif_path = hdf_path.with_suffix(".tif")

    with h5py.File(hdf_path, "w") as hdf:
        if legacy:
            hdf.create_dataset("IDs", data=np.array([0, 1, 2], dtype=np.uint8))
            hdf.create_dataset("Names", data=np.array([b"NoData", b"A", b"B"]))
            hdf.create_dataset(
                "ManningsN",
                data=np.array([np.finfo(np.float32).max, 0.03, 0.08]),
            )
        else:
            dtype = np.dtype([("ID", "<i4"), ("Name", "S16")])
            hdf.create_dataset(
                "Raster Map",
                data=np.array([(0, b"NoData"), (1, b"A"), (2, b"B")], dtype=dtype),
            )
            variables_dtype = np.dtype([("Name", "S16"), ("ManningsN", "<f4")])
            hdf.create_dataset(
                "Variables",
                data=np.array(
                    [(b"NoData", np.finfo(np.float32).max), (b"A", 0.03), (b"B", 0.08)],
                    dtype=variables_dtype,
                ),
            )

    data = np.tile(np.array([0, 1, 2, 1], dtype=np.uint8), (32, 8))
    with rasterio.open(
        tif_path,
        "w",
        driver="GTiff",
        width=32,
        height=32,
        count=1,
        dtype=data.dtype,
        transform=rasterio.transform.from_origin(0, 32, 1, 1),
        tiled=True,
        blockxsize=16,
        blockysize=16,
        compress="deflate",
    ) as raster:
        raster.write(data, 1)

    report = validate_native_landcover(
        hdf_path,
        expected_class_ids={1, 2},
        legacy=legacy,
    )

    assert report["raster_class_ids"] == [0, 1, 2]
    assert report["legacy_schema"] is legacy


def _write_result_hdf(
    path: Path,
    face_values: list[float],
    *,
    cell_values: list[float] | None = None,
    complete: bool = True,
) -> None:
    with h5py.File(path, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = "True" if complete else "False"
        geometry.attrs["Land Cover Filename"] = r".\LandCover\Native.hdf"
        geometry.attrs["Land Cover Layername"] = "Native"
        area = geometry.create_group("2D Flow Areas").create_group("Mesh")
        faces = np.zeros((len(face_values), 4), dtype=np.float64)
        faces[:, 3] = face_values
        area.create_dataset("Faces Area Elevation Values", data=faces)
        if cell_values is not None:
            area.create_dataset(
                "Cells Center Manning's n",
                data=np.asarray(cell_values, dtype=np.float64),
            )


def test_final_mannings_audit_rejects_floating_noise(tmp_path: Path):
    result = tmp_path / "noise.p01.hdf"
    _write_result_hdf(result, [0.035000, 0.035003])

    with pytest.raises(RuntimeError, match="not materially diverse"):
        HdfLandCover.audit_final_mannings_n(result, tolerance=1.0e-4)


def test_final_mannings_audit_accepts_ras5_face_values(tmp_path: Path):
    result = tmp_path / "legacy.p01.hdf"
    _write_result_hdf(result, [0.03, 0.04, 0.08])

    report = HdfLandCover.audit_final_mannings_n(
        result,
        expected_values=[0.03, 0.08],
    )

    assert bool(report.loc[0, "passed"])
    assert report.loc[0, "cell_value_count"] == 0
    assert report.loc[0, "face_distinct_count"] == 3


def test_final_mannings_audit_accepts_ras6_cell_and_face_values(tmp_path: Path):
    result = tmp_path / "modern.p01.hdf"
    _write_result_hdf(
        result,
        [0.03, 0.04, 0.08],
        cell_values=[0.03, 0.04, 0.08],
    )

    report = HdfLandCover.audit_final_mannings_n(result)

    assert bool(report.loc[0, "passed"])
    assert report.loc[0, "cell_distinct_count"] == 3


def test_final_mannings_audit_requires_complete_geometry(tmp_path: Path):
    result = tmp_path / "incomplete.p01.hdf"
    _write_result_hdf(result, [0.03, 0.08], complete=False)

    with pytest.raises(RuntimeError, match="does not mark geometry complete"):
        HdfLandCover.audit_final_mannings_n(result)


def test_solver_owned_hdf_mutation_apis_fail_closed(tmp_path: Path):
    with pytest.raises(NotImplementedError, match="Direct writes"):
        GeomLandCover.override_2d_mannings_n(
            tmp_path / "model.g01.hdf",
            0.04,
        )
    with pytest.warns(DeprecationWarning, match="deprecated"):
        with pytest.raises(RuntimeError, match="no longer mutates silently"):
            GeomPreprocessor.clear_geompre_hdf(tmp_path / "model.g01.hdf")


def test_native_sidecar_edit_requires_selected_hecras_version(tmp_path: Path):
    sidecar = tmp_path / "LandCover.hdf"
    sidecar.touch()

    with pytest.raises(ValueError, match="hecras_version is required"):
        HdfLandCover.set_landcover_mannings_n(
            sidecar,
            {"Open Water": 0.04},
        )


def test_property_table_postcondition_requires_complete_paired_arrays(
    tmp_path: Path,
):
    geometry_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geometry_hdf, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = np.bool_(True)
        area = geometry.create_group("2D Flow Areas").create_group("Mesh")
        area.create_dataset(
            "Cells Volume Elevation Info",
            data=np.array([[0, 1]], dtype=np.int32),
        )
        area.create_dataset(
            "Cells Volume Elevation Values",
            data=np.array([[10.0, 20.0]], dtype=np.float64),
        )
        area.create_dataset(
            "Faces Area Elevation Info",
            data=np.array([[0, 1]], dtype=np.int32),
        )

    with pytest.raises(RuntimeError, match="Faces Area Elevation Values"):
        _validate_property_tables_postcondition(geometry_hdf)

    with h5py.File(geometry_hdf, "r+") as hdf:
        hdf["Geometry/2D Flow Areas/Mesh"].create_dataset(
            "Faces Area Elevation Values",
            data=np.array([[10.0, 20.0, 1.0, 0.04]], dtype=np.float64),
        )

    _validate_property_tables_postcondition(geometry_hdf)


def test_property_table_postcondition_rejects_incomplete_geometry(
    tmp_path: Path,
):
    geometry_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geometry_hdf, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = "False"

    with pytest.raises(RuntimeError, match="did not mark geometry complete"):
        _validate_property_tables_postcondition(geometry_hdf)


def test_property_table_postcondition_accepts_complete_1d_only_geometry(
    tmp_path: Path,
):
    geometry_hdf = tmp_path / "model.g01.hdf"
    with h5py.File(geometry_hdf, "w") as hdf:
        geometry = hdf.create_group("Geometry")
        geometry.attrs["Complete Geometry"] = np.bool_(True)
        geometry.create_group("Cross Sections")

    _validate_property_tables_postcondition(geometry_hdf)
