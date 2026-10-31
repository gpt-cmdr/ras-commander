"""Opt-in native export on a copied public, computed HEC-RAS project.

Set RAS_NATIVE_BOUNDARY_PROJECT to its .prj and optionally
RAS_NATIVE_BOUNDARY_VERSION (default 7.0.1) and RAS_NATIVE_BOUNDARY_PLAN
(default 02). Source project files are never modified.
"""

import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import pytest

from ras_commander import RasMap, RasPrj, RasProcess, init_ras_project


@pytest.mark.integration
def test_native_inundation_boundary_on_copied_project(tmp_path_factory, monkeypatch):
    configured = os.environ.get("RAS_NATIVE_BOUNDARY_PROJECT")
    if not configured:
        pytest.skip("Set RAS_NATIVE_BOUNDARY_PROJECT to a public computed project .prj")
    gpd = pytest.importorskip("geopandas")
    source = Path(configured).resolve()
    assert source.is_file()

    # Hash every source file, including previously stored products.
    def identities(folder):
        return {
            str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*")
            if path.is_file()
        }

    source_before = identities(source.parent)
    scratch = tmp_path_factory.mktemp("boundary")
    model = scratch / "model"
    shutil.copytree(source.parent, model)
    assert max(len(str(path)) for path in model.rglob("*")) <= 240
    obj = RasPrj()
    init_ras_project(
        model / source.name,
        ras_object=obj,
        ras_version=os.environ.get("RAS_NATIVE_BOUNDARY_VERSION", "7.0.1"),
        hide_intro=True,
    )
    rasmap = RasMap.get_rasmap_path(obj)
    original = rasmap.read_bytes()
    module = importlib.import_module("ras_commander.RasProcess")
    native_helper = module.run_store_all_maps_helper
    calls = []

    def record_helper(**kwargs):
        parameters = [
            dict(node.attrib)
            for node in ET.parse(rasmap).findall(".//MapParameters")
            if node.get("OutputMode", "").startswith("Stored")
        ]
        assert len(parameters) == 1
        assert parameters[0]["MapType"] == "depth"
        assert parameters[0]["OutputMode"] == "Stored Polygon Specified Depth"
        assert parameters[0]["ContourPolygonValue"] == "0"
        result = native_helper(**kwargs)
        calls.append(
            {
                "parameters": parameters,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        )
        (scratch / "helper-calls.json").write_text(
            json.dumps(calls, indent=2), encoding="utf-8"
        )
        return result

    monkeypatch.setattr(module, "run_store_all_maps_helper", record_helper)
    plan = os.environ.get("RAS_NATIVE_BOUNDARY_PLAN", "02")
    profiles = ["Max"]
    timestamps = RasProcess.get_plan_timestamps(plan, obj)
    if timestamps:
        profiles.append(timestamps[len(timestamps) // 2])
    evidence = {
        "runtime": RasProcess.get_store_maps_runtime_provenance(obj),
        "products": [],
    }
    for index, profile in enumerate(profiles):
        result = RasProcess.store_maps(
            plan,
            profile=profile,
            render_mode="sloping",
            wse=False,
            depth=False,
            velocity=False,
            inundation_boundary=True,
            output_path=scratch / f"products-{index}",
            fix_georef=False,
            ras_object=obj,
        )
        assert rasmap.read_bytes() == original
        assert set(result) == {"inundation_boundary"}
        assert len(result["inundation_boundary"]) == 1
        path = result["inundation_boundary"][0]
        frame = gpd.read_file(path)
        assert not frame.empty and not frame.geometry.is_empty.any()
        assert frame.geometry.is_valid.all()
        assert set(frame.geom_type) <= {"Polygon", "MultiPolygon"}
        assert frame.crs is not None
        assert frame.area.sum() > 0
        assert RasProcess._stored_boundary_has_features(path)
        evidence["products"].append(
            {
                "profile": profile,
                "path": str(path),
                "features": len(frame),
                "crs": frame.crs.to_string(),
                "area_in_crs_units_squared": float(frame.area.sum()),
                "files": identities(path.parent),
            }
        )
    evidence["helper_calls"] = calls
    evidence["rasmap_restored"] = rasmap.read_bytes() == original
    evidence["source_unchanged"] = identities(source.parent) == source_before
    (scratch / "evidence.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
    assert evidence["source_unchanged"]
