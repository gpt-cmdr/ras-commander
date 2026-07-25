"""Public-surface and fail-safe tests for native infiltration overrides."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import h5py
import pandas as pd
import pytest

from ras_commander import _infiltration_override_native as native
from ras_commander.RasPrj import ras as global_ras
from ras_commander.hdf.HdfInfiltration import HdfInfiltration

ras_calibrate_module = importlib.import_module("ras_commander.RasCalibrate")


def test_canonical_public_signatures_keep_ras_object_last():
    create_parameters = list(
        inspect.signature(
            HdfInfiltration.create_infiltration_override_regions
        ).parameters
    )
    set_parameters = list(
        inspect.signature(
            HdfInfiltration.set_infiltration_base_overrides
        ).parameters
    )
    get_region_signature = inspect.signature(
        HdfInfiltration.get_infiltration_region_overrides
    )
    set_region_signature = inspect.signature(
        HdfInfiltration.set_infiltration_region_overrides
    )

    assert create_parameters == [
        "geometry_hdf_path",
        "region_names",
        "hecras_version",
        "ras_object",
    ]
    assert set_parameters == [
        "geometry_hdf_path",
        "infiltration_df",
        "hecras_version",
        "ras_object",
    ]
    assert list(get_region_signature.parameters) == [
        "geometry_hdf_path",
        "region_name",
        "region_id",
        "hecras_version",
        "ras_object",
    ]
    assert list(set_region_signature.parameters) == [
        "geometry_hdf_path",
        "infiltration_df",
        "region_name",
        "region_id",
        "hecras_version",
        "ras_object",
    ]
    for signature in (get_region_signature, set_region_signature):
        assert signature.parameters["region_name"].kind is inspect.Parameter.KEYWORD_ONLY
        assert signature.parameters["region_id"].kind is inspect.Parameter.KEYWORD_ONLY


def test_version_resolution_is_explicit_then_project_then_global(monkeypatch):
    monkeypatch.setattr(global_ras, "ras_version", "6.0", raising=False)
    project = SimpleNamespace(ras_version="6.6")

    assert native.resolve_hecras_version("7.0", project) == "7.0"
    assert native.resolve_hecras_version(None, project) == "6.6"
    assert native.resolve_hecras_version(None, None) == "6.0"


def test_version_resolution_fails_without_any_version(monkeypatch):
    monkeypatch.setattr(global_ras, "ras_version", None, raising=False)

    with pytest.raises(ValueError, match="hecras_version is required"):
        native.resolve_hecras_version(
            None,
            SimpleNamespace(ras_version=None),
        )


def test_canonical_create_routes_to_native_with_resolved_version(monkeypatch):
    captured = {}
    expected = pd.DataFrame(
        {
            "Land Cover Name": ["NoData"],
            "Curve Number": [-9999.0],
        }
    )

    def fake_create(path, names, *, hecras_version):
        captured.update(
            path=path,
            names=names,
            hecras_version=hecras_version,
        )
        return expected

    monkeypatch.setattr(
        native,
        "create_infiltration_override_regions_native",
        fake_create,
    )

    result = HdfInfiltration.create_infiltration_override_regions(
        "project.g01.hdf",
        ["Region 1"],
        ras_object=SimpleNamespace(ras_version="6.6"),
    )

    assert result is expected
    assert captured == {
        "path": "project.g01.hdf",
        "names": ["Region 1"],
        "hecras_version": "6.6",
    }


def test_canonical_set_routes_to_native_with_explicit_version(monkeypatch):
    requested = pd.DataFrame(
        {
            "Land Cover Name": ["NoData"],
            "Curve Number": [77.0],
        }
    )
    captured = {}

    def fake_set(path, table, *, hecras_version):
        captured.update(
            path=path,
            table=table,
            hecras_version=hecras_version,
        )
        return table

    monkeypatch.setattr(
        native,
        "set_infiltration_base_overrides_native",
        fake_set,
    )

    result = HdfInfiltration.set_infiltration_base_overrides(
        "project.g01.hdf",
        requested,
        hecras_version="7.0",
    )

    assert result is requested
    assert captured["path"] == "project.g01.hdf"
    assert captured["table"] is requested
    assert captured["hecras_version"] == "7.0"


def test_canonical_region_get_and_set_route_to_native(monkeypatch):
    requested = pd.DataFrame(
        {
            "Land Cover Name": ["NoData"],
            "Curve Number": [77.0],
        }
    )
    calls = []

    def fake_get(path, **kwargs):
        calls.append(("get", path, kwargs))
        return requested

    def fake_set(path, table, **kwargs):
        calls.append(("set", path, kwargs, table))
        return requested

    monkeypatch.setattr(
        native,
        "get_infiltration_region_overrides_native",
        fake_get,
    )
    monkeypatch.setattr(
        native,
        "set_infiltration_region_overrides_native",
        fake_set,
    )

    result_get = HdfInfiltration.get_infiltration_region_overrides(
        "project.g01.hdf",
        region_id=0,
        ras_object=SimpleNamespace(ras_version="6.6"),
    )
    result_set = HdfInfiltration.set_infiltration_region_overrides(
        "project.g01.hdf",
        requested,
        region_name="Main Channel",
        hecras_version="7.0",
    )

    assert result_get is requested
    assert result_set is requested
    assert calls[0] == (
        "get",
        "project.g01.hdf",
        {
            "region_name": None,
            "region_id": 0,
            "hecras_version": "6.6",
        },
    )
    assert calls[1][:3] == (
        "set",
        "project.g01.hdf",
        {
            "region_name": "Main Channel",
            "region_id": None,
            "hecras_version": "7.0",
        },
    )
    assert calls[1][3] is requested


def test_legacy_writers_are_deprecated_working_native_wrappers(monkeypatch):
    requested = pd.DataFrame(
        {
            "Land Cover Name": ["NoData"],
            "Curve Number": [77.0],
        }
    )
    calls = []

    def fake_create(*args, **kwargs):
        calls.append(("create", args, kwargs))
        return requested

    def fake_set(*args, **kwargs):
        calls.append(("set", args, kwargs))
        return requested

    monkeypatch.setattr(
        HdfInfiltration,
        "create_infiltration_override_regions",
        staticmethod(fake_create),
    )
    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_base_overrides",
        staticmethod(fake_set),
    )

    with pytest.deprecated_call(match="create_infiltration_group"):
        HdfInfiltration.create_infiltration_group(
            "project.g01.hdf",
            ["Region 1"],
            hecras_version="6.6",
        )
    with pytest.deprecated_call(match="set_infiltration_baseoverrides"):
        HdfInfiltration.set_infiltration_baseoverrides(
            "project.g01.hdf",
            requested,
            hecras_version="6.6",
        )

    assert [call[0] for call in calls] == ["create", "set"]
    assert all(call[2]["hecras_version"] == "6.6" for call in calls)


def test_scale_base_overrides_preserves_sentinel_and_uses_native_setter(
    monkeypatch,
):
    requested = pd.DataFrame(
        {
            "Land Cover Name": ["NoData", "Forest"],
            "Curve Number": [-9999.0, 70.0],
        }
    )
    captured = {}

    def fake_set(*, geometry_hdf_path, infiltration_df, **kwargs):
        captured.update(
            path=geometry_hdf_path,
            table=infiltration_df.copy(),
            kwargs=kwargs,
        )
        return infiltration_df

    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_base_overrides",
        staticmethod(fake_set),
    )

    result = HdfInfiltration.scale_infiltration_base_overrides(
        "project.g01.hdf",
        requested,
        {"Curve Number": 1.1},
        hecras_version="7.0",
    )

    assert result.at[0, "Curve Number"] == -9999.0
    assert result.at[1, "Curve Number"] == pytest.approx(77.0)
    assert captured["kwargs"]["hecras_version"] == "7.0"


def test_calibration_apply_fn_uses_canonical_native_setter(monkeypatch):
    geometry_path = Path("project.g01.hdf")
    project = SimpleNamespace(ras_version="7.0")
    current = pd.DataFrame(
        {
            "Land Cover Name": ["Forest", "Urban"],
            "Curve Number": [70.0, 90.0],
            "Abstraction Ratio": [0.2, 0.1],
        }
    )
    captured = {}

    monkeypatch.setattr(
        ras_calibrate_module,
        "_resolve_geom_hdf_path_from_plan",
        lambda _plan_path: geometry_path,
    )
    monkeypatch.setattr(
        HdfInfiltration,
        "get_infiltration_baseoverrides",
        staticmethod(lambda _path: current),
    )

    def fake_set(path, table, **kwargs):
        captured.update(path=path, table=table.copy(), kwargs=kwargs)
        return table

    monkeypatch.setattr(
        HdfInfiltration,
        "set_infiltration_base_overrides",
        staticmethod(fake_set),
    )

    apply_fn = ras_calibrate_module.make_infiltration_apply_fn(
        {"cn": ("Forest", "Curve Number")},
        hecras_version="6.6",
    )
    apply_fn(Path("project.p01"), pd.Series({"cn": 77.0}), project)

    assert captured["path"] == geometry_path
    assert captured["table"].loc[0, "Curve Number"] == 77.0
    assert captured["kwargs"] == {
        "hecras_version": "6.6",
        "ras_object": project,
    }


def test_geometry_transaction_rolls_back_failed_edit(tmp_path):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")

    with pytest.raises(RuntimeError, match="forced failure"):
        with native._geometry_transaction(geometry):
            geometry.write_bytes(b"mutated")
            raise RuntimeError("forced failure")

    assert geometry.read_bytes() == b"original"
    backups = list(
        tmp_path.glob(
            "project.g01.infiltration_override.*.backup.hdf"
        )
    )
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original"


class _FakePoints:
    def __init__(self, coordinates):
        self._points = [
            SimpleNamespace(X=x, Y=y) for x, y in coordinates
        ]
        self.Count = len(self._points)

    def __getitem__(self, index):
        return self._points[index]


class _FakePolygon:
    def __init__(self, *, has_hole=False):
        self._parts = [
            _FakePoints([(0, 0), (10, 0), (10, 10), (0, 0)])
        ]
        if has_hole:
            self._parts.append(
                _FakePoints([(2, 2), (2, 4), (4, 2), (2, 2)])
            )

    def PartsCount(self):
        return len(self._parts)

    def PartIsInterior(self, part_id):
        return part_id > 0

    def PartPoints(self, part_id):
        return self._parts[part_id]


class _FakeRegionLayer:
    def __init__(
        self,
        names,
        tables,
        *,
        has_hole=False,
        base=None,
        polygon_signature=None,
    ):
        self.names = list(names)
        self.tables = list(tables)
        self.polygons = [
            _FakePolygon(has_hole=has_hole and index == 0)
            for index in range(len(names))
        ]
        self.base = base
        self.polygon_signature = (
            polygon_signature
            if polygon_signature is not None
            else tuple((name, index) for index, name in enumerate(names))
        )
        self.set_calls = []

    def FeatureCount(self):
        return len(self.names)

    def GetFeatureName(self, feature_id):
        return self.names[feature_id]

    def Polygon(self, feature_id):
        return self.polygons[feature_id]

    def GetParameterTable(self, feature_id):
        return self.tables[feature_id]

    def SetParameterTable(self, feature_id, value):
        self.set_calls.append((feature_id, value))
        self.tables[feature_id] = value


def _patch_fake_native_runtime(monkeypatch, layers):
    queue = iter(layers)
    monkeypatch.setattr(
        native,
        "_load_geometry",
        lambda *_args, **_kwargs: SimpleNamespace(layer=next(queue)),
    )
    monkeypatch.setattr(
        native,
        "_qualified_layer",
        lambda geometry: geometry.layer,
    )
    monkeypatch.setattr(native, "_release_geometry", lambda _geometry: None)
    monkeypatch.setattr(
        native,
        "_base_dataframe",
        lambda layer: layer.base.copy(deep=True),
    )
    monkeypatch.setattr(
        native,
        "_parameter_set_dataframe",
        lambda _layer, table: table.copy(deep=True),
    )
    monkeypatch.setattr(
        native,
        "_polygon_signatures",
        lambda layer: layer.polygon_signature,
    )


@pytest.mark.parametrize(
    ("region_name", "region_id", "message"),
    [
        (None, None, "exactly one"),
        ("Main Channel", 0, "exactly one"),
        ("Missing", None, "was not found"),
        ("Duplicate", None, "ambiguous"),
        (None, 3, "between 0 and"),
    ],
)
def test_region_selector_validation_precedes_backup(
    tmp_path,
    monkeypatch,
    region_name,
    region_id,
    message,
):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")
    layer = _FakeRegionLayer(
        ["Main Channel", "Duplicate", "Duplicate"],
        [pd.DataFrame()] * 3,
        base=pd.DataFrame(),
    )
    _patch_fake_native_runtime(monkeypatch, [layer])
    monkeypatch.setattr(native, "_geometry_path", lambda _path: geometry)

    with pytest.raises((ValueError, TypeError), match=message):
        native.set_infiltration_region_overrides_native(
            geometry,
            pd.DataFrame(),
            region_name=region_name,
            region_id=region_id,
            hecras_version="7.0",
        )

    assert not list(
        tmp_path.glob("*.infiltration_override.*.backup.hdf")
    )


def test_region_hole_rejection_precedes_backup(tmp_path, monkeypatch):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")
    layer = _FakeRegionLayer(
        ["Main Channel"],
        [pd.DataFrame()],
        has_hole=True,
        base=pd.DataFrame(),
    )
    _patch_fake_native_runtime(monkeypatch, [layer])
    monkeypatch.setattr(native, "_geometry_path", lambda _path: geometry)

    with pytest.raises(NotImplementedError, match="hole-free polygon"):
        native.set_infiltration_region_overrides_native(
            geometry,
            pd.DataFrame(),
            region_name="Main Channel",
            hecras_version="7.0",
        )

    assert not list(
        tmp_path.glob("*.infiltration_override.*.backup.hdf")
    )


def test_region_setter_preserves_base_geometry_names_and_other_tables(
    tmp_path,
    monkeypatch,
):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")
    base = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [70.0]}
    )
    before_selected = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [-9999.0]}
    )
    unchanged = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [80.0]}
    )
    expected = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [55.0]}
    )
    replacement = expected.copy(deep=True)
    signature = ((("Main Channel", 0),), (("Floodplain", 1),))
    pre_layer = _FakeRegionLayer(
        ["Main Channel", "Floodplain"],
        [before_selected, unchanged],
        base=base,
        polygon_signature=signature,
    )
    post_layer = _FakeRegionLayer(
        ["Main Channel", "Floodplain"],
        [expected, unchanged],
        base=base,
        polygon_signature=signature,
    )
    _patch_fake_native_runtime(monkeypatch, [pre_layer, post_layer])
    monkeypatch.setattr(native, "_geometry_path", lambda _path: geometry)
    monkeypatch.setattr(native, "_scoped_save", lambda _layer: None)
    monkeypatch.setattr(
        native,
        "_replacement_region_parameter_set",
        lambda *_args, **_kwargs: (replacement, expected.copy(deep=True)),
    )

    observed = native.set_infiltration_region_overrides_native(
        geometry,
        expected,
        region_id=0,
        hecras_version="7.0",
    )

    pd.testing.assert_frame_equal(observed, expected)
    assert pre_layer.set_calls == [(0, replacement)]
    assert observed.attrs["region_name"] == "Main Channel"
    assert observed.attrs["region_id"] == 0
    assert observed.attrs["recompute_required"] is True
    backup = Path(observed.attrs["backup_path"])
    assert backup.exists()
    assert backup.read_bytes() == b"original"


def test_native_region_getter_returns_selected_class_table_and_attrs(
    tmp_path,
    monkeypatch,
):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")
    selected = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [55.0]}
    )
    layer = _FakeRegionLayer(
        ["Main Channel", "Floodplain"],
        [selected, pd.DataFrame()],
        base=pd.DataFrame(),
    )
    _patch_fake_native_runtime(monkeypatch, [layer])
    monkeypatch.setattr(native, "_geometry_path", lambda _path: geometry)

    observed = native.get_infiltration_region_overrides_native(
        geometry,
        region_name="Main Channel",
        hecras_version="7.0",
    )

    pd.testing.assert_frame_equal(observed, selected)
    assert observed.attrs == {
        "geometry_hdf_path": str(geometry),
        "region_name": "Main Channel",
        "region_id": 0,
    }


def test_region_setter_rolls_back_failed_scoped_save(
    tmp_path,
    monkeypatch,
):
    geometry = tmp_path / "project.g01.hdf"
    geometry.write_bytes(b"original")
    table = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [-9999.0]}
    )
    expected = pd.DataFrame(
        {"Land Cover Name": ["Forest"], "Curve Number": [55.0]}
    )
    layer = _FakeRegionLayer(
        ["Main Channel"],
        [table],
        base=table,
    )
    _patch_fake_native_runtime(monkeypatch, [layer])
    monkeypatch.setattr(native, "_geometry_path", lambda _path: geometry)
    monkeypatch.setattr(
        native,
        "_replacement_region_parameter_set",
        lambda *_args, **_kwargs: (expected, expected),
    )

    def fail_save(_layer):
        geometry.write_bytes(b"partial native save")
        raise RuntimeError("forced native save failure")

    monkeypatch.setattr(native, "_scoped_save", fail_save)

    with pytest.raises(RuntimeError, match="forced native save failure"):
        native.set_infiltration_region_overrides_native(
            geometry,
            expected,
            region_name="Main Channel",
            hecras_version="7.0",
        )

    assert geometry.read_bytes() == b"original"
    backups = list(
        tmp_path.glob("*.infiltration_override.*.backup.hdf")
    )
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"original"


def test_geometry_path_requires_exact_geometry_filename_and_role(tmp_path):
    geometry = tmp_path / "project.g01.hdf"
    with h5py.File(geometry, "w") as hdf_file:
        hdf_file.attrs["File Type"] = "HEC-RAS Geometry"
        hdf_file.create_group("Geometry")

    assert native._geometry_path(geometry) == geometry.resolve()


def test_geometry_path_accepts_native_postpreprocessor_role(tmp_path):
    geometry = tmp_path / "project.g01.hdf"
    with h5py.File(geometry, "w") as hdf_file:
        hdf_file.attrs["File Type"] = "HEC-RAS Results"
        hdf_file.create_group("Geometry")

    assert native._geometry_path(geometry) == geometry.resolve()


@pytest.mark.parametrize(
    ("filename", "file_type", "root_groups", "message"),
    [
        ("project.p01.hdf", "HEC-RAS Results", ["Geometry"], r"\*\.g##\.hdf"),
        (
            "project.p01.tmp.hdf",
            "HEC-RAS Results",
            ["Geometry"],
            r"\*\.g##\.hdf",
        ),
        ("project.hdf", "HEC-RAS Geometry", ["Geometry"], r"\*\.g##\.hdf"),
        (
            "project.g01.hdf",
            "HEC-RAS Results",
            ["Geometry", "Plan Data", "Results"],
            "geometry-only",
        ),
        ("project.g01.hdf", None, ["Geometry"], "geometry-only"),
    ],
)
def test_geometry_path_rejects_non_geometry_hdf_roles(
    tmp_path,
    filename,
    file_type,
    root_groups,
    message,
):
    candidate = tmp_path / filename
    with h5py.File(candidate, "w") as hdf_file:
        if file_type is not None:
            hdf_file.attrs["File Type"] = file_type
        for group_name in root_groups:
            hdf_file.create_group(group_name)

    with pytest.raises(ValueError, match=message):
        native._geometry_path(candidate)


@pytest.mark.parametrize(
    ("version", "allowed"),
    [
        ("6.0", True),
        ("6.6", True),
        ("7.0", True),
        ("5.07", False),
        ("7.1", False),
    ],
)
def test_private_abi_version_gate(version, allowed):
    if allowed:
        assert native._qualified_version(version)
    else:
        with pytest.raises(RuntimeError, match="qualified only"):
            native._qualified_version(version)
