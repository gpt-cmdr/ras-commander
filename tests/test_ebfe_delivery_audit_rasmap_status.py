"""Regression tests for status-aware eBFE delivery audit consumption."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from ras_commander._rasmap_schema import create_rasmap_dataframe


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "ebfe_delivery_audit.py"
SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "_ebfe_delivery_audit_under_test",
    SCRIPT_PATH,
)
assert SCRIPT_SPEC is not None and SCRIPT_SPEC.loader is not None
delivery_audit = importlib.util.module_from_spec(SCRIPT_SPEC)
sys.modules[SCRIPT_SPEC.name] = delivery_audit
SCRIPT_SPEC.loader.exec_module(delivery_audit)


def _project(rasmap_df):
    return SimpleNamespace(
        plan_df=pd.DataFrame(columns=["flow_type", "HDF_Results_Path"]),
        boundaries_df=pd.DataFrame(),
        rasmap_df=rasmap_df,
    )


def _isolate_project_probes(monkeypatch, rasmap_path: Path):
    monkeypatch.setattr(delivery_audit, "extract_project_crs", lambda *args: None)
    monkeypatch.setattr(delivery_audit, "find_rasmap", lambda *args: rasmap_path)
    monkeypatch.setattr(delivery_audit, "get_asset_crs", lambda *args: None)
    monkeypatch.setattr(delivery_audit, "compare_crs", lambda *args: True)


def test_failed_rasmap_status_gates_legacy_and_raw_layer_fallbacks(
    monkeypatch,
    tmp_path: Path,
):
    rasmap_path = tmp_path / "Broken.rasmap"
    rasmap_path.write_text("<RASMapper>", encoding="utf-8")
    rasmap_df = create_rasmap_dataframe(
        rasmap_path=rasmap_path,
        rasmap_status="failed",
        rasmap_error="ParseError: invalid XML",
    )
    rasmap_df.at[0, "terrain_hdf_path"] = [str(tmp_path / "stale-terrain.hdf")]
    _isolate_project_probes(monkeypatch, rasmap_path)

    def unexpected_raw_fallback(*args, **kwargs):
        raise AssertionError("failed documents must not be reparsed as raw layers")

    monkeypatch.setattr(
        delivery_audit,
        "rasmap_layer_paths",
        unexpected_raw_fallback,
    )

    audit = delivery_audit.audit_loaded_project(tmp_path, _project(rasmap_df))

    assert audit.rasmap_status == "failed"
    assert audit.terrain_layers == []
    assert audit.land_cover_layers == []
    assert "RAS Mapper parse failed: ParseError: invalid XML" in audit.issues


def test_partial_status_keeps_unaffected_delivery_fields(
    monkeypatch,
    tmp_path: Path,
):
    rasmap_path = tmp_path / "Partial.rasmap"
    rasmap_path.write_text("<RASMapper />", encoding="utf-8")
    terrain_path = tmp_path / "Terrain.hdf"
    landcover_path = tmp_path / "LandCover.hdf"
    rasmap_df = create_rasmap_dataframe(
        rasmap_path=rasmap_path,
        rasmap_status="parsed_with_errors",
        rasmap_field_errors={
            "infiltration_hdf_path": "ValueError: missing Filename"
        },
    )
    rasmap_df.at[0, "terrain_hdf_path"] = [str(terrain_path)]
    rasmap_df.at[0, "landcover_hdf_path"] = [str(landcover_path)]
    _isolate_project_probes(monkeypatch, rasmap_path)

    audit = delivery_audit.audit_loaded_project(tmp_path, _project(rasmap_df))

    assert audit.rasmap_status == "parsed_with_errors"
    assert audit.rasmap_field_errors == {
        "infiltration_hdf_path": "ValueError: missing Filename"
    }
    assert audit.terrain_layers == [str(terrain_path)]
    assert audit.land_cover_layers == [str(landcover_path)]
    assert (
        "RAS Mapper field extraction failed: infiltration_hdf_path" in audit.issues
    )
