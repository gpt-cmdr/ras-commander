"""Bounded screening contracts; native qualification uses the public Bald Eagle model."""
from importlib import import_module
from types import SimpleNamespace

import h5py
import pytest
from test_geom_mesh import MockPointM, MockPointMs, MockPolygon, breakline_geom_text

gm = import_module('ras_commander.geom.GeomMesh')


@pytest.fixture
def screening(monkeypatch):
    ns = {'PointMs': MockPointMs, 'PointM': MockPointM, '_meshfv2d_takes_ratio': True}
    seeds = MockPointMs()
    for xy in [(2, 2), (3, 3), (4, 4), (5, 5)]:
        seeds.Add(MockPointM(*xy))
    area = SimpleNamespace(FeatureCount=lambda: 1)
    monkeypatch.setattr(gm, '_build_breaklines', lambda d, n, region, **kw: 'region' if region else 'saved')
    calls = []
    def compute(perim, candidate, lines, ratio, native):
        points = tuple((candidate[i].X, candidate[i].Y) for i in range(candidate.Count))
        calls.append((lines, ratio, points))
        bad = len(points) == 4 and lines is None and ratio == .1
        return SimpleNamespace(
            MeshCompletionState='MaxFacesPerCellExceeded' if bad else 'Complete',
            NonVirtualCellCount=len(points),
            CellFacesCount=lambda i: 9 if bad and i == 0 else 4,
            mode=lines, ratio=ratio,
        )
    monkeypatch.setattr(gm, '_compute_mesh', compute)
    monkeypatch.setattr(gm, '_autofix_max_faces', lambda *a, **kw: (None, 4, [
        MockPointM(6, 6), MockPointM(6, 6), MockPointM(.25, 5), MockPointM(2, 2)]))
    def run(**kwargs):
        args = dict(perim=MockPolygon([(0, 0), (10, 0), (10, 10), (0, 10)]),
                    seeds=seeds, d2fa=area, ratio=.0025, requested_ratio=.0025,
                    ns=ns, max_iterations=2, region_constraints=False, inset=.5, report={})
        args.update(kwargs)
        return gm._screen_mesh_robustness(**args), args['report']
    return run, calls, ns


def test_rechecks_identical_seeds_and_returns_production_mesh(screening):
    run, calls, _ = screening
    mesh, report = run()
    assert mesh.mode == 'saved' and mesh.ratio == .0025
    assert report['converged'] and report['final_seed_count'] == 5
    assert len(calls) == 18
    assert len(set(c[2] for c in calls[:9])) == 1
    assert len(set(c[2] for c in calls[9:])) == 1
    assert calls[-1][2][-1] == (6, 6)
    assert report['rounds'][0]['proposed_additions'] == 1
    assert all(c['bad_cells'] == 0 for c in report['rounds'][1]['checks'])


def test_requested_and_escalated_ratios_are_both_screened(screening):
    run, calls, _ = screening
    mesh, report = run(ratio=.2, requested_ratio=.01, region_constraints=True)
    assert {c[1] for c in calls} == {.01, .2, .05, .1}
    assert mesh.mode == 'region' and mesh.ratio == .2


@pytest.mark.parametrize('override, message', [
    ({'max_iterations': 0}, 'repair budget'),
    ({'d2fa': SimpleNamespace(FeatureCount=lambda: 2)}, 'one 2D'),
])
def test_rejects_unsupported_or_exhausted_screening(screening, override, message):
    run, _, _ = screening
    with pytest.raises((RuntimeError, ValueError), match=message):
        run(**override)


def test_no_safe_additions_fails_closed(screening, monkeypatch):
    run, _, _ = screening
    monkeypatch.setattr(gm, '_autofix_max_faces', lambda *a, **k: (None, 1, [MockPointM(.1, .1)]))
    report = {}
    with pytest.raises(RuntimeError, match='no safe'):
        run(report=report)
    assert not report['converged'] and 'error' in report


def test_growth_budget(screening, monkeypatch):
    run, _, _ = screening
    monkeypatch.setattr(gm, '_autofix_max_faces', lambda *a, **k: (None, 3, [MockPointM(i, 7) for i in (6, 7, 8)]))
    with pytest.raises(RuntimeError, match='50%'):
        run()


@pytest.mark.parametrize('state,count', [('Complete', 3), ('PointsOutsidePerimeter', 4)])
def test_unexpected_native_output_fails_closed(screening, monkeypatch, state, count):
    run, _, _ = screening
    monkeypatch.setattr(gm, '_compute_mesh', lambda *a: SimpleNamespace(
        MeshCompletionState=state, NonVirtualCellCount=count))
    with pytest.raises(RuntimeError, match='unexpected state/count'):
        run()


def test_older_constructor_rejected(screening):
    run, _, ns = screening
    ns['_meshfv2d_takes_ratio'] = False
    with pytest.raises(ValueError, match='6.6'):
        run()


@pytest.mark.parametrize('units,inset', [('US Customary', .5), ('SI', .1524)])
def test_inset_units(tmp_path, units, inset):
    path = tmp_path / 'geom.hdf'
    with h5py.File(path, 'w') as hf:
        hf.attrs['Units System'] = units
    assert gm._screening_inset(path) == inset


def test_unknown_units_rejected(tmp_path):
    path = tmp_path / 'geom.hdf'
    with h5py.File(path, 'w'):
        pass
    with pytest.raises(ValueError, match='known geometry units'):
        gm._screening_inset(path)


def test_strict_constraints_do_not_silently_drop_missing_layers():
    class Layer:
        def __init__(self, name):
            pass
    ns = {'PolylineFeatureLayer': Layer, 'Polyline': SimpleNamespace()}
    with pytest.raises(AttributeError):
        gm._build_breaklines(SimpleNamespace(Geometry=SimpleNamespace()), ns, strict=True)


@pytest.mark.parametrize('enabled', [False, True])
def test_public_opt_in_routing(monkeypatch, breakline_geom_text, enabled):
    from test_geom_mesh import _mock_generate_success, FakeMesh, FakePointCollection
    path = breakline_geom_text
    _mock_generate_success(monkeypatch, path, has_breaklines=False)
    monkeypatch.setattr(gm, '_generate_seeds_via_net', lambda *a, **k: FakePointCollection())
    calls = []
    monkeypatch.setattr(gm, '_screening_inset', lambda path: .5)
    def screen(*args):
        calls.append(args)
        args[-1].update(converged=True)
        return FakeMesh()
    monkeypatch.setattr(gm, '_screen_mesh_robustness', screen)
    result = gm.GeomMesh.generate(path, cell_size=50, robustness_screening=enabled)
    assert result.ok, result.error_message
    assert len(calls) == int(enabled)
    assert result.robustness_screening == ({'converged': True} if enabled else {})


def test_screening_failure_prevents_success_serialization(monkeypatch, breakline_geom_text):
    from test_geom_mesh import _mock_generate_success, FakePointCollection
    path = breakline_geom_text
    _mock_generate_success(monkeypatch, path, has_breaklines=False)
    monkeypatch.setattr(gm, '_generate_seeds_via_net', lambda *a, **k: FakePointCollection())
    monkeypatch.setattr(gm, '_screening_inset', lambda path: .5)
    def fail(*args):
        raise RuntimeError('screen failed')
    monkeypatch.setattr(gm, '_screen_mesh_robustness', fail)
    def unexpected(*args, **kwargs):
        pytest.fail('Failed screening must not save the candidate mesh')
    monkeypatch.setattr(gm, '_save_mesh', unexpected)
    monkeypatch.setattr(gm, '_patch_text_seeds', unexpected)
    result = gm.GeomMesh.generate(path, cell_size=50, robustness_screening=True)
    assert not result.ok and 'screen failed' in result.error_message


def test_screening_refuses_seed_fallback(monkeypatch, breakline_geom_text):
    from test_geom_mesh import _mock_generate_success
    _mock_generate_success(monkeypatch, breakline_geom_text, has_breaklines=False)
    result = gm.GeomMesh.generate(breakline_geom_text, robustness_screening=True)
    assert not result.ok and 'requires RegenerateMeshPoints' in result.error_message


def test_generate_all_forwards_opt_in(monkeypatch, breakline_geom_text):
    from test_geom_mesh import _mock_generate_success
    from ras_commander.geom.GeomMeshDataclasses import MeshResult
    _mock_generate_success(monkeypatch, breakline_geom_text, has_breaklines=False)
    captured = []
    def generate(**kwargs):
        captured.append(kwargs)
        return MeshResult(mesh_name=kwargs['mesh_name'], status='complete')
    monkeypatch.setattr(gm.GeomMesh, 'generate', generate)
    results = gm.GeomMesh.generate_all(breakline_geom_text, robustness_screening=True)
    assert len(results) == 1
    assert captured[0]['robustness_screening'] is True
