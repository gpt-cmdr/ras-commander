from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import rasterio
from rasterio.transform import from_origin


RUNNER_PATH = (
    Path(__file__).parents[1]
    / ".claude"
    / "skills"
    / "qa-rasmapper-web-parity"
    / "scripts"
    / "rasmapper_web_parity.py"
)


@pytest.fixture(scope="module")
def parity_runner():
    spec = importlib.util.spec_from_file_location("rasmapper_web_parity", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _base_spec(tmp_path: Path) -> dict:
    return {
        "schema": "rascommander.rasmapper-web-parity/v1",
        "project": str(tmp_path / "Muncie.prj"),
        "project_crs": "EPSG:2965",
        "web_viewer_url": "https://example.test/viewer",
        "web_manifest_url": str(tmp_path / "manifest.json"),
    }


def test_load_spec_requires_schema_and_core_fields(tmp_path: Path, parity_runner) -> None:
    path = tmp_path / "review.json"
    path.write_text(json.dumps(_base_spec(tmp_path)), encoding="utf-8")

    assert parity_runner.load_spec(path)["project_crs"] == "EPSG:2965"

    path.write_text(json.dumps({"schema": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="must use schema"):
        parity_runner.load_spec(path)


def test_semantic_assertions_read_local_manifest(tmp_path: Path, parity_runner) -> None:
    manifest = {
        "schema": "rascommander.maplibre/v2",
        "tree": [
            {"id": "features"},
            {"id": "geometries"},
            {"id": "results"},
            {"id": "map-layers"},
            {"id": "terrains"},
        ],
        "layers": {"terrain": {}, "p03-depth-max": {}},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    spec = _base_spec(tmp_path) | {
        "expected_roots": ["features", "geometries", "results", "map-layers", "terrains"],
        "required_web_layers": ["terrain", "p03-depth-max"],
    }

    checks = parity_runner.semantic_assertions(spec)

    assert checks
    assert all(check["passed"] for check in checks)


def test_numeric_probes_distinguish_values_and_nodata(tmp_path: Path, parity_runner) -> None:
    raster = tmp_path / "depth.tif"
    data = np.array([[1.25, -9999.0], [3.5, 4.75]], dtype="float32")
    with rasterio.open(
        raster,
        "w",
        driver="GTiff",
        width=2,
        height=2,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-86.0, 41.0, 0.5, 0.5),
        nodata=-9999.0,
    ) as target:
        target.write(data, 1)
    spec = _base_spec(tmp_path) | {
        "numeric_probes": [
            {
                "id": "wet",
                "raster": str(raster),
                "x": -85.75,
                "y": 40.75,
                "expected": 1.25,
                "tolerance": 0.001,
            },
            {
                "id": "nodata",
                "raster": str(raster),
                "x": -85.25,
                "y": 40.75,
                "expected": 0.0,
            },
        ]
    }

    probes = parity_runner.numeric_probes(spec)

    assert probes[0]["passed"] is True
    assert probes[1]["value"] is None
    assert probes[1]["passed"] is False


def test_image_comparison_reports_identity_and_difference(tmp_path: Path, parity_runner) -> None:
    reference = tmp_path / "reference.png"
    same = tmp_path / "same.png"
    changed = tmp_path / "changed.png"
    Image.new("RGB", (20, 20), "white").save(reference)
    Image.new("RGB", (20, 20), "white").save(same)
    Image.new("RGB", (20, 20), "black").save(changed)

    identity = parity_runner.image_comparison(reference, same, None, tmp_path / "same-diff.png")
    difference = parity_runner.image_comparison(
        reference,
        changed,
        None,
        tmp_path / "changed-diff.png",
    )

    assert identity["ssim"] == pytest.approx(1.0)
    assert identity["normalized_mae"] == pytest.approx(0.0)
    assert difference["ssim"] < 0.01
    assert difference["normalized_mae"] == pytest.approx(1.0)
