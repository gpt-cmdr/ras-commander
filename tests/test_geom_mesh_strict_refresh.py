"""Strict completion reaches actual nested preprocessors during HDF refresh."""

from importlib import import_module
from types import SimpleNamespace

import pandas as pd
import pytest

from ras_commander.geom import GeomPreprocessor


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("stale", [False, True])
def test_missing_and_stale_refresh_propagate_strictness(
    tmp_path, monkeypatch, strict, stale
):
    module = import_module("ras_commander.geom.GeomMesh")
    text = tmp_path / "Model.g01"
    text.write_text("Geom Title=Synthetic\n")
    hdf = text.with_suffix(".g01.hdf")
    if stale:
        hdf.write_bytes(b"old synthetic HDF")
    ras = SimpleNamespace(
        check_initialized=lambda: None,
        get_plan_entries=lambda: pd.DataFrame(
            [{"plan_number": "01", "Geom Path": str(text)}]
        ),
    )
    calls = []

    def refresh(*args, **kwargs):
        calls.append(kwargs)
        assert kwargs["require_complete_products"] is strict
        return SimpleNamespace(
            success=False, error="controlled stop before native execution"
        )

    monkeypatch.setattr(GeomPreprocessor, "run_geometry_preprocessor", refresh)
    monkeypatch.setattr(
        module, "_mesh_hdf_consistency_issues", lambda *a, **k: ["stale synthetic HDF"]
    )
    with pytest.raises(RuntimeError, match="controlled stop"):
        module.GeomMesh.audit_domain_containment(
            text,
            ras_object=ras,
            recompile_via_rasexe=True,
            require_complete_products=strict,
        )
    assert len(calls) == 1
