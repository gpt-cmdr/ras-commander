"""Constrained retry orchestration; native objects are synthetic, planner is real."""
from dataclasses import asdict
import json
from types import SimpleNamespace
import pytest
from test_geom_mesh import (
    _mock_generate_success, geom_mesh_module as module,
    MockPointMs, MockPointM, FakeMesh, FakeMeshState,
)

@pytest.fixture
def project(tmp_path, monkeypatch):
    path = tmp_path / 'example.g01'
    path.write_text('Geom Title=Example\nStorage Area=MainArea\nStorage Area Is2D=-1\nStorage Area Point Generation Data=,,50,50\nStorage Area 2D Points= 0 \nLCMann Time=0\n')
    _mock_generate_success(monkeypatch, path, has_breaklines=True)
    points = MockPointMs()
    for x in (10., 20., 30., 40.):
        points.Add(MockPointM(x, x))
    monkeypatch.setattr(module, '_generate_seeds_via_net', lambda *a, **k: points)
    calls = []
    def save_unavailable(*args):
        raise RuntimeError('test uses native cell readback')
    monkeypatch.setattr(module, '_save_mesh', save_unavailable)
    def forbidden(*a, **k):
        pytest.fail('opt-in targeted repair must not change perimeter')
    monkeypatch.setattr(module, '_reseed_after_perimeter_fix', forbidden)
    def configure(states, mismatch=False, bad_indexes=None):
        def compute(perim, seeds, constraints, ratio, ns):
            xy = [(seeds[i].X, seeds[i].Y) for i in range(seeds.Count)]
            calls.append((perim, xy, constraints, ratio))
            state = states[min(len(calls)-1, len(states)-1)]
            mesh = FakeMesh()
            mesh.MeshCompletionState = FakeMeshState(1 if state == 'Complete' else 3, state)
            mesh.NonVirtualCellCount = len(xy)
            mesh._cells = [SimpleNamespace(Point=MockPointM(x, y)) for x,y in xy]
            if mismatch:
                mesh._cells[0].Point = MockPointM(99, 99)
            mesh.BadIndexes = [0] if bad_indexes is None else bad_indexes
            mesh.CellFacesCount = lambda i: 2 if i == 0 else 4
            return mesh
        monkeypatch.setattr(module, '_compute_mesh', compute)
    return path, calls, configure

@pytest.mark.parametrize('state', ['FacePerimeterConnectionError', 'CellMinFaceError'])
def test_identity_verified_repair_preserves_constraints_and_order(project, state):
    path, calls, configure = project
    configure([state, 'Complete'])
    result = module.GeomMesh.generate(path, cell_size=50, max_iterations=3, native_seed_removal_budget=1)
    assert result.ok
    assert calls[1][1] == calls[0][1][1:]
    assert calls[1][0] is calls[0][0]
    assert calls[0][2] == calls[1][2] == 'mock_breaklines'
    assert calls[0][3] == calls[1][3]
    record = result.native_seed_repairs[0]
    assert record['removed_points'] == [{'generated_point_index':0, 'x':10., 'y':10.}]
    assert record['cumulative_removed'] == 1 and record['remaining_budget'] == 0
    assert record['seed_count_before'] == 4 and record['seed_count_after'] == 3
    assert record['perimeter_changed'] is False
    assert not result.perimeter_repairs
    json.dumps(asdict(result))

@pytest.mark.parametrize('budget,iterations,mismatch,expected', [
    (1, 1, False, 'no iteration'),
    (1, 3, True, 'unverified seed candidates'),
    (1, 3, False, 'budget exhausted'),
])
def test_fail_closed(project, budget, iterations, mismatch, expected):
    path, calls, configure = project
    configure(['FacePerimeterConnectionError'], mismatch)
    original = path.read_bytes()
    result = module.GeomMesh.generate(path, max_iterations=iterations, native_seed_removal_budget=budget)
    assert not result and expected in result.error_message
    assert path.read_bytes() == original
    assert not result.perimeter_repairs
    assert len(result.native_seed_repairs) == (1 if expected == 'budget exhausted' else 0)


def test_cumulative_indexes_are_per_iteration(project):
    path, calls, configure = project
    configure(['FacePerimeterConnectionError', 'CellMinFaceError', 'Complete'])
    result = module.GeomMesh.generate(path, max_iterations=3, native_seed_removal_budget=2)
    assert result.ok
    assert [r['cumulative_removed'] for r in result.native_seed_repairs] == [1,2]
    assert [r['removed_points'][0]['x'] for r in result.native_seed_repairs] == [10.,20.]
    assert calls[-1][1] == [(30.,30.),(40.,40.)]

@pytest.mark.parametrize('value', [True, False, -1, 8193, 1.5, '1', None])
@pytest.mark.parametrize('method', ['generate', 'generate_all'])
def test_validation_before_resolution(monkeypatch, value, method):
    monkeypatch.setattr(module, '_resolve_geom_text_path', lambda *a, **k: pytest.fail('resolved before validation'))
    with pytest.raises(ValueError, match='native_seed_removal_budget'):
        getattr(module.GeomMesh, method)('missing.g01', native_seed_removal_budget=value)


def test_generate_all_forwards_budget(project, monkeypatch):
    path, _, _ = project
    calls=[]
    monkeypatch.setattr(module.GeomMesh, 'generate', lambda **kw: calls.append(kw) or module.MeshResult('MainArea','complete'))
    module.GeomMesh.generate_all(path, native_seed_removal_budget=7)
    assert calls and all(c['native_seed_removal_budget'] == 7 for c in calls)


def test_default_uses_existing_ratio_retry(project):
    path, calls, configure=project
    configure(['FacePerimeterConnectionError', 'Complete'])
    result=module.GeomMesh.generate(path, max_iterations=2)
    assert result.ok and not result.native_seed_repairs
    assert calls[0][1] == calls[1][1]
    assert calls[1][3] > calls[0][3]



@pytest.mark.parametrize('bad_indexes,expected', [([0, 1], 'planning failed'), ([0, 9], 'unverified'), ([0.5], 'unverified')])
def test_rejects_oversized_or_invalid_native_candidates(project, bad_indexes, expected):
    path, calls, configure = project
    configure(['FacePerimeterConnectionError'], bad_indexes=bad_indexes)
    result = module.GeomMesh.generate(path, max_iterations=3, native_seed_removal_budget=1)
    assert not result and expected in result.error_message
    assert not result.native_seed_repairs and len(calls) == 1


def test_partial_identity_match_does_not_remove_any_seed(project):
    path, calls, configure = project
    configure(['FacePerimeterConnectionError'], mismatch=True, bad_indexes=[0, 1])
    result = module.GeomMesh.generate(path, max_iterations=3, native_seed_removal_budget=2)
    assert not result and 'unverified' in result.error_message
    assert not result.native_seed_repairs and len(calls) == 1


@pytest.mark.parametrize('bad_indexes', [[], [0, 1, 2, 3]])
def test_empty_or_entire_seed_selection_is_refused(project, bad_indexes):
    path, calls, configure = project
    configure(['FacePerimeterConnectionError'], bad_indexes=bad_indexes)
    result = module.GeomMesh.generate(path, max_iterations=3, native_seed_removal_budget=8192)
    assert not result and not result.native_seed_repairs
    assert len(calls) == 1


def test_unrelated_state_retains_existing_retry(project):
    path, calls, configure = project
    configure(['OtherNativeError', 'Complete'])
    result = module.GeomMesh.generate(path, max_iterations=2, native_seed_removal_budget=1)
    assert result.ok and not result.native_seed_repairs
    assert calls[0][1] == calls[1][1]
    assert calls[1][3] > calls[0][3]
