"""Regeneration orchestration regressions and an opt-in real RAS Mapper check."""

import hashlib
import os
import platform
import shutil
import sys
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pytest

from test_geom_mesh import MockPointM, MockPointMs, _mock_generate_success

gm = import_module("ras_commander.geom.GeomMesh")


def _points(values):
    points = MockPointMs()
    for x, y in values:
        points.Add(MockPointM(x, y))
    return points


def _xy(points):
    return [(points.PointM(i).X, points.PointM(i).Y) for i in range(points.PointMCount())]


@pytest.fixture
def native_contract(monkeypatch):
    """Stand-ins model the swallowed native precondition, not mesh hydraulics."""
    class NetList(list):
        def Add(self, value):
            self.append(value)

        @classmethod
        def __class_getitem__(cls, item):
            return cls

    class NetArray:
        @classmethod
        def __class_getitem__(cls, item):
            return lambda values: values

    class MultiPoint:
        def __init__(self, points):
            self.points = points

        def PointMCount(self):
            return self.points.Count

        def PointM(self, index):
            return self.points[index]

    class Layer:
        def __init__(self, features):
            self.features = [MultiPoint(_points(values)) for values in features]

        def FeatureCount(self):
            return len(self.features)

        def __getitem__(self, index):
            return self.features[index]

        def DeleteAllFeatures(self):
            self.features.clear()

        def AddFeature(self, feature):
            self.features.append(feature)

        def GetMeshEditingPoints(self):
            if len(self.features) != 1:
                raise RuntimeError("Can't call this function with multiple multipoints")
            return self.features[0]

    class Tin:
        def __init__(self, fid):
            self.fid = fid

        def ContainsPoint(self, point):
            return self.fid * 20 < point.X < self.fid * 20 + 10 and 0 < point.Y < 10

    layer = Layer([[(2, 2), (4, 4)], [(22, 2), (24, 4)]])
    tins = [Tin(0), Tin(1)]
    state = SimpleNamespace(
        layer=layer, calls=[], silent_failure=False,
        generated=[[(3, 3), (6, 6)], [(23, 3), (26, 6)]],
    )

    class Method:
        def GetParameters(self):
            return [None] * 7

        def Invoke(self, generator, args):
            state.calls.append((args, [list(_xy(feature)) for feature in layer.features]))
            # RAS Mapper catches this precondition failure inside its method.
            if layer.FeatureCount() != 1 or state.silent_failure:
                return
            values = _xy(layer.GetMeshEditingPoints())
            for fid in args[3]:
                values = [p for p in values if not tins[fid].ContainsPoint(MockPointM(*p))]
                values.extend(state.generated[fid])
            layer.features = [MultiPoint(_points(values))]

    class PointGenerator:
        def __init__(self, geometry):
            pass

        def GetType(self):
            return SimpleNamespace(GetMethod=lambda *args: Method())

    empty = SimpleNamespace(FeatureCount=lambda: 0)
    geometry = SimpleNamespace(
        MeshPoints=layer,
        MeshPerimeters=SimpleNamespace(GetDevelopmentTin=lambda fid: tins[fid]),
        BreakLines=empty, SA2DStructures=empty, MeshRegions=empty,
        D2FlowArea=SimpleNamespace(
            FeatureCount=lambda: 2, Geometry=SimpleNamespace(MeshPoints=layer),
        ),
    )
    state.geometry = geometry
    monkeypatch.setitem(sys.modules, "System", SimpleNamespace(
        Int32=int, Object=object, Array=NetArray,
    ))
    monkeypatch.setitem(sys.modules, "System.Reflection", SimpleNamespace(
        BindingFlags=SimpleNamespace(Instance=1, NonPublic=2),
    ))
    monkeypatch.setitem(sys.modules, "System.Collections.Generic", SimpleNamespace(List=NetList))
    monkeypatch.setitem(sys.modules, "RasMapperLib", SimpleNamespace(MultiPoint=MultiPoint))
    state.ns = {
        "RASGeometry": lambda path: geometry,
        "PointGenerator": PointGenerator, "PointMs": MockPointMs,
    }
    return state


@pytest.mark.parametrize("fid", [0, 1])
def test_regenerates_selected_area_and_preserves_other_points(native_contract, fid):
    state = native_contract
    other = _xy(state.layer[1 - fid])
    seeds = gm._generate_seeds_via_net("geometry.hdf", state.ns, fid=fid)
    assert [(seeds[i].X, seeds[i].Y) for i in range(seeds.Count)] == state.generated[fid]
    args, before_call = state.calls[0]
    assert list(args[2]) == list(args[3]) == [fid]
    assert args[6] is False  # inactive areas remain present to Mapper
    assert before_call == [other]  # stale target seeds cleared before invocation
    assert _xy(state.layer.GetMeshEditingPoints()) == other + state.generated[fid]


def test_identical_regeneration_is_valid(native_contract):
    state = native_contract
    state.generated[1] = _xy(state.layer[1])
    result = gm._generate_seeds_via_net("geometry.hdf", state.ns, fid=1)
    assert [(result[i].X, result[i].Y) for i in range(result.Count)] == state.generated[1]


def test_single_area_identical_regeneration_is_valid(native_contract):
    state = native_contract
    state.layer.features = state.layer.features[:1]
    state.geometry.D2FlowArea.FeatureCount = lambda: 1
    state.generated[0] = _xy(state.layer[0])
    result = gm._generate_seeds_via_net("geometry.hdf", state.ns)
    assert [(result[i].X, result[i].Y) for i in range(result.Count)] == state.generated[0]


def test_missing_development_tin_is_rejected_before_point_mutation(native_contract):
    state = native_contract
    before = [_xy(state.layer[i]) for i in range(2)]
    state.geometry.MeshPerimeters.GetDevelopmentTin = lambda fid: None
    with pytest.raises(gm._MeshRegenerationError, match="no development TIN"):
        gm._generate_seeds_via_net("geometry.hdf", state.ns, fid=1)
    assert [_xy(state.layer[i]) for i in range(2)] == before
    assert state.calls == []


def test_swallowed_native_failure_does_not_return_non_target_points(native_contract):
    state = native_contract
    state.silent_failure = True
    with pytest.raises(gm._MeshRegenerationError, match="no computation points.*area 1"):
        gm._generate_seeds_via_net("geometry.hdf", state.ns, fid=1)
    assert _xy(state.layer.GetMeshEditingPoints()) == [(2, 2), (4, 4)]


@pytest.mark.parametrize("fid", [-1, 2])
def test_invalid_area_is_rejected_before_point_mutation(native_contract, fid):
    state = native_contract
    before = [_xy(state.layer[i]) for i in range(2)]
    with pytest.raises(ValueError, match="out of range"):
        gm._generate_seeds_via_net("geometry.hdf", state.ns, fid=fid)
    assert [_xy(state.layer[i]) for i in range(2)] == before
    assert state.calls == []


def test_generate_does_not_fallback_or_save_after_known_native_failure(monkeypatch, tmp_path):
    text = tmp_path / "geometry.g01"
    text.write_text("Geom Title=Regression\n")
    _mock_generate_success(monkeypatch, text, has_breaklines=False)

    def fail(*args, **kwargs):
        raise gm._MeshRegenerationError("no regenerated target points")

    def unexpected(*args, **kwargs):
        pytest.fail("Known regeneration failure must not fallback or save points")

    monkeypatch.setattr(gm, "_generate_seeds_via_net", fail)
    monkeypatch.setattr(gm, "_generate_seeds_safe", unexpected)
    monkeypatch.setattr(gm, "_save_mesh", unexpected)
    monkeypatch.setattr(gm, "_patch_text_seeds", unexpected)
    result = gm.GeomMesh.generate(text, mesh_name="MainArea", cell_size=50)
    assert not result.ok
    assert "[MainArea] Native point regeneration failed" in result.error_message


@pytest.mark.integration
@pytest.mark.destructive_copy
@pytest.mark.skipif(
    platform.system() != "Windows" or os.environ.get("RAS_COMMANDER_RUN_HECRAS_INTEGRATION") != "1",
    reason="requires opt-in Windows RAS Mapper runtime",
)
@pytest.mark.parametrize("fid", [0, 1])
def test_real_bald_eagle_multi_area_regenerates_changed_spacing(tmp_path, fid):
    """The stale-point bug fails this real-project check on unpatched main."""
    from ras_commander import RasExamples
    from test_geom_mesh_grid_anchor import _hecras_dir

    project = RasExamples.extract_project("BaldEagleCrkMulti2D", output_path=tmp_path, suffix="regeneration")
    hdf = tmp_path / f"area-{fid}.hdf"
    shutil.copy2(project / "BaldEagleDamBrk.g11.hdf", hdf)
    hd = _hecras_dir()
    gm._load_dlls(hd)
    ns = gm._imports()
    loaded = []
    load = ns["RASGeometry"]

    def capture(path):
        geometry = load(path)
        loaded.append(geometry)
        return geometry

    baseline = load(str(hdf))
    name = baseline.D2FlowArea.GetFeatureName(fid)
    original = np.asarray(_xy(baseline.MeshPoints[fid]))
    other = np.asarray(_xy(baseline.MeshPoints[1 - fid]))
    spacing = gm._read_cell_size_from_hdf(hdf, name)
    gm._sync_cell_size_to_hdf(hdf, spacing * 0.75, mesh_name=name)
    fingerprint = hashlib.sha256(hdf.read_bytes()).hexdigest()
    ns = {**ns, "RASGeometry": capture}
    generated = gm._generate_seeds_via_net(str(hdf), ns, fid=fid)
    result = np.asarray([(generated[i].X, generated[i].Y) for i in range(generated.Count)])
    assert len(result) > 0
    # A different ordering of the same stored coordinates is not regeneration.
    assert not np.array_equal(
        result[np.lexsort((result[:, 1], result[:, 0]))],
        original[np.lexsort((original[:, 1], original[:, 0]))],
    )
    tin = loaded[-1].MeshPerimeters.GetDevelopmentTin(fid)
    assert all(tin.ContainsPoint(generated[i]) for i in range(generated.Count))
    merged = loaded[-1].MeshPoints.GetMeshEditingPoints()
    preserved = np.asarray([
        (merged.PointM(i).X, merged.PointM(i).Y)
        for i in range(merged.PointMCount())
        if not tin.ContainsPoint(merged.PointM(i))
    ])
    np.testing.assert_array_equal(preserved, other)
    assert hashlib.sha256(hdf.read_bytes()).hexdigest() == fingerprint
    repeated = gm._generate_seeds_via_net(str(hdf), ns, fid=fid)
    np.testing.assert_array_equal(
        np.asarray([(repeated[i].X, repeated[i].Y) for i in range(repeated.Count)]), result,
    )
