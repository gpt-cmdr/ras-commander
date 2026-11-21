"""Native preprocessing budgets propagate without changing lifecycle checks."""
from importlib import import_module
from types import SimpleNamespace

import pytest

module = import_module("ras_commander.geom.GeomMesh")
from ras_commander.geom import GeomPreprocessor


@pytest.mark.parametrize("method", ["generate", "generate_all"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, float('inf'), float('nan'), "600", None])
def test_invalid_timeout_precedes_path_resolution_and_native_loading(monkeypatch, method, value):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid timeout reached project resolution or native loading")
    monkeypatch.setattr(module, "_resolve_geom_text_path", forbidden)
    monkeypatch.setattr(module, "_load_dlls", forbidden)
    with pytest.raises(ValueError, match="preprocess_timeout must be a positive integer"):
        getattr(module.GeomMesh, method)("01", preprocess_timeout=value)


@pytest.mark.parametrize("timeout", [None, 3600])
@pytest.mark.parametrize("exists", [False, True])
def test_missing_and_stale_hdf_refresh_forward_timeout(tmp_path, monkeypatch, timeout, exists):
    text = tmp_path / "Example.g01"
    text.write_text("Geom Title=Example\n")
    hdf = text.with_suffix('.g01.hdf')
    if exists:
        hdf.write_bytes(b'old workspace')
    seen = []
    monkeypatch.setattr(module, "_mesh_hdf_consistency_issues", lambda *a, **k: [] if seen else ['stale'])
    def refresh(path, output, **kwargs):
        seen.append(kwargs)
        output.write_bytes(b'refreshed workspace')
    monkeypatch.setattr(module, "_recompile_geometry_hdf_via_rasexe", refresh)
    kwargs = {} if timeout is None else {'preprocess_timeout': timeout}
    assert module._ensure_hdf(text, recompile_via_rasexe=True, **kwargs) == hdf
    assert seen[0]['preprocess_timeout'] == (600 if timeout is None else timeout)


@pytest.mark.parametrize("timeout", [None, 3600])
@pytest.mark.parametrize("success", [True, False])
def test_native_boundary_preserves_flags_and_propagates_failure(tmp_path, monkeypatch, timeout, success):
    text = tmp_path / 'Example.g01'
    hdf = text.with_suffix('.g01.hdf')
    seen = []
    context = object()
    monkeypatch.setattr(module, '_find_plan_for_geometry', lambda *a, **k: '01')
    def preprocess(plan, **kwargs):
        seen.append(kwargs)
        if success:
            hdf.write_bytes(b'compiled workspace')
        return SimpleNamespace(success=success, error='native timeout', first_error_line=None)
    monkeypatch.setattr(GeomPreprocessor, 'run_geometry_preprocessor', preprocess)
    kwargs = {} if timeout is None else {'preprocess_timeout': timeout}
    if success:
        assert module._recompile_geometry_hdf_via_rasexe(text, hdf, ras_object=context, require_complete_products=True, **kwargs) == hdf
    else:
        with pytest.raises(RuntimeError, match='native timeout'):
            module._recompile_geometry_hdf_via_rasexe(text, hdf, ras_object=context, require_complete_products=True, **kwargs)
    assert seen[0]['max_wait'] == (600 if timeout is None else timeout)
    assert seen[0]['ras_object'] is context
    assert all(seen[0][key] for key in ('clear_geompre', 'force', 'geometry_only', 'require_complete_products'))


@pytest.mark.parametrize("timeout", [None, 3600])
def test_generate_all_forwards_initial_and_each_area_budget(tmp_path, monkeypatch, timeout):
    text = tmp_path / 'Example.g01'
    hdf = text.with_suffix('.g01.hdf')
    initial, areas = [], []
    monkeypatch.setattr(module, '_resolve_geom_text_path', lambda *a, **k: text)
    monkeypatch.setattr(module, '_load_dlls', lambda *a, **k: None)
    monkeypatch.setattr(module, '_ensure_hdf', lambda *a, **k: initial.append(k) or hdf)
    area = SimpleNamespace(FeatureCount=lambda: 2, GetFeatureName=lambda i: ['Upper', 'Lower'][i])
    monkeypatch.setattr(module, '_imports', lambda: {'RASGeometry': lambda p: SimpleNamespace(D2FlowArea=area)})
    monkeypatch.setattr(module.GeomMesh, 'generate', lambda **k: areas.append(k) or k['mesh_name'])
    kwargs = {} if timeout is None else {'preprocess_timeout': timeout}
    assert module.GeomMesh.generate_all(text, recompile_via_rasexe=True, require_complete_products=True, **kwargs) == ['Upper', 'Lower']
    for call in initial + areas:
        assert call['preprocess_timeout'] == (600 if timeout is None else timeout)
        assert call['require_complete_products'] is True
        assert call['recompile_via_rasexe'] is True
