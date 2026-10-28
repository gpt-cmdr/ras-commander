"""Empty-point refresh uses the existing native bootstrap before compilation."""
from importlib import import_module
from types import SimpleNamespace

import numpy as np
import pytest

module = import_module("ras_commander.geom.GeomMesh")
from ras_commander.geom import GeomStorage


@pytest.mark.parametrize("by_index", [False, True])
@pytest.mark.parametrize("strict", [False, True])
def test_empty_area_bootstrap_precedes_hdf_validation(tmp_path, monkeypatch, by_index, strict):
    text = tmp_path / "Example.g01"
    text.write_text("Geom Title=Example\n")
    GeomStorage.set_2d_flow_area_perimeter(
        text, "Main", coordinates=[(0,0), (100,0), (100,100), (0,100)],
        point_generation_data=",,25,25",
    )
    calls = []
    monkeypatch.setattr(module, "_find_plan_for_geometry", lambda *a, **k: calls.append("plan") or "01")
    def bootstrap(path, **kwargs):
        assert calls == ["plan"]
        assert kwargs["mesh_name"] == "Main"
        assert kwargs["repair_generated_points"] is True
        assert path.with_suffix(".g01.bak").exists()
        module._patch_text_seeds(path, np.array([[25., 25.]]), mesh_name="Main")
        calls.append("bootstrap")
        return SimpleNamespace(ok=True, cell_count=1)
    monkeypatch.setattr(module.GeomMesh, "generate_computation_points", bootstrap)
    def compile_points(*args, **kwargs):
        assert calls == ["plan", "bootstrap"]
        assert kwargs["require_complete_products"] is strict
        calls.append("compile")
    monkeypatch.setattr(module, "_recompile_geometry_hdf_via_rasexe", compile_points)
    def validate(*args, **kwargs):
        assert calls == ["plan", "bootstrap", "compile"]
        assert module._read_mesh_metadata_from_text(text)["Main"]["seed_count"] == 1
        calls.append("validate")
        raise RuntimeError("stop before native preprocessing")
    monkeypatch.setattr(module, "_ensure_hdf", validate)
    result = module.GeomMesh.generate(
        text, mesh_name=None if by_index else "Main", recompile_via_rasexe=True,
        require_complete_products=strict,
    )
    assert calls == ["plan", "bootstrap", "compile", "validate"]
    assert "stop before native preprocessing" in result.error_message


@pytest.mark.parametrize("seed_count", [1, None])
def test_existing_or_missing_points_are_not_bootstrapped(tmp_path, monkeypatch, seed_count):
    text = tmp_path / "Example.g01"
    text.write_text("Geom Title=Example\n")
    monkeypatch.setattr(module, "_read_mesh_metadata_from_text", lambda _: {"Main": {"seed_count": seed_count}})
    def unexpected(*args, **kwargs):
        raise AssertionError("Must not bootstrap existing or unspecified computation points")
    monkeypatch.setattr(module.GeomMesh, "generate_computation_points", unexpected)
    assert module._bootstrap_empty_mesh_for_refresh(text, mesh_name="Main") is False


def test_missing_native_route_is_rejected_before_bootstrap(tmp_path, monkeypatch):
    text = tmp_path / "Example.g01"
    text.write_text("unchanged")
    monkeypatch.setattr(module, "_read_mesh_metadata_from_text", lambda _: {"Main": {"seed_count": 0}})
    def no_plan(*args, **kwargs):
        raise RuntimeError("no matching plan")
    monkeypatch.setattr(module, "_find_plan_for_geometry", no_plan)
    with pytest.raises(RuntimeError, match="no matching plan"):
        module._bootstrap_empty_mesh_for_refresh(text, mesh_name="Main")
    assert text.read_text() == "unchanged"


@pytest.mark.parametrize("ok,count", [(False, 0), (True, 0)])
def test_failed_or_empty_bootstrap_prevents_refresh(tmp_path, monkeypatch, ok, count):
    text = tmp_path / "Example.g01"
    text.write_text("unchanged")
    monkeypatch.setattr(module, "_read_mesh_metadata_from_text", lambda _: {"Main": {"seed_count": 0}})
    monkeypatch.setattr(module, "_find_plan_for_geometry", lambda *a, **k: "01")
    monkeypatch.setattr(module.GeomMesh, "generate_computation_points", lambda *a, **k: SimpleNamespace(ok=ok, cell_count=count, error_message="no points"))
    with pytest.raises(RuntimeError, match="bootstrap failed: no points"):
        module._bootstrap_empty_mesh_for_refresh(text, mesh_name="Main")
    assert text.read_text() == "unchanged"


def test_generate_without_refresh_does_not_bootstrap(tmp_path, monkeypatch):
    text = tmp_path / "Example.g01"
    text.write_text("unchanged")
    def unexpected(*args, **kwargs):
        raise AssertionError("No opt-in to refresh")
    monkeypatch.setattr(module, "_bootstrap_empty_mesh_for_refresh", unexpected)
    def stop(*args, **kwargs):
        raise RuntimeError("existing validation route")
    monkeypatch.setattr(module, "_ensure_hdf", stop)
    result = module.GeomMesh.generate(text, recompile_via_rasexe=False)
    assert "existing validation route" in result.error_message
    assert text.read_text() == "unchanged"
