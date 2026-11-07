"""Cross-method manifest, naming and capability contracts for 1D mapping."""
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Polygon

from ras_commander.fim import FimUnsupportedError, RasFim
from ras_commander.fim import _engine, _one_d, _products
from test_fim_one_d import files, _fake_engine  # noqa: F401 - synthetic scene


@pytest.mark.parametrize("name", ["a b", "x/y", ".", "..", ""])
def test_profile_names_follow_mapping_filename_contract(files, tmp_path, name):
    with pytest.raises(ValueError, match="safe output names"):
        RasFim.prepare_one_d_model(*files, tmp_path / "prepared",
                                   profiles={name: "Max"}, allow_unqualified=True)
    assert not (tmp_path / "prepared").exists()


def test_path_mapping_uses_shared_manifest_and_named_products(files, tmp_path, monkeypatch):
    engine = _fake_engine(monkeypatch, tmp_path)
    output = tmp_path / "mapped"
    result = RasFim.map_one_d_profiles(
        *files, output, profiles={"maximum": "Max"}, bbox=(0, 0, 10, 10),
        allow_unqualified=True, max_working_mib=64, timeout=12)
    row = result.iloc[0]
    assert row.profile == "maximum" and row.crs == "EPSG:6588"
    assert row.depth_tif == str(_products.product_paths(output, "maximum")[0])
    assert row.wse_tif == str(_products.product_paths(output, "maximum")[1])
    document = json.loads((output / "fim_manifest.json").read_text())
    assert "rows" not in document
    assert document["profiles"][0]["profile"] == "maximum"
    assert document["aoi"]["bounds"] == [0, 0, 10, 10]
    assert document["aoi"]["geometry_wkb_hex"]
    assert document["aoi_mask"] == "pixel-center-bounds/1"
    assert document["options"] == {"profiles": {"maximum": "Max"}, "allow_unqualified": True,
                                   "threads": 1, "max_working_mib": 64, "timeout": 12.0}
    assert document["engine_path"] == str(engine)
    for path in files:
        assert document["inputs"][str(path)]["sha256"] == _one_d.digest(path)
    assert document["method_record"]["method_id"] == _one_d.METHOD_ID


def test_capability_key_and_request_schema_are_checked_before_output(files, tmp_path, monkeypatch):
    _fake_engine(monkeypatch, tmp_path)
    output = tmp_path / "mapped"
    for record in (
        {"elsewhere": {"method_id": _one_d.METHOD_ID}},
        {"one_d_clipped_diagnostic": {"method_id": _one_d.METHOD_ID, "request_schemas": ["other/1"]}},
    ):
        monkeypatch.setattr(_engine, "engine_method", lambda path: record)
        with pytest.raises(FimUnsupportedError, match="request contract"):
            RasFim.map_one_d_profiles(*files, output, allow_unqualified=True)
        assert not output.exists()


def test_polygon_mask_policy_and_shape_are_recorded(files, tmp_path, monkeypatch):
    import rasterio
    _fake_engine(monkeypatch, tmp_path)
    polygon = Polygon([(0, 0), (10, 0), (0, 10)])
    output = tmp_path / "mapped"
    result = RasFim.map_one_d_profiles(*files, output, polygon=polygon,
                                      aoi_crs="EPSG:6588", allow_unqualified=True)
    document = json.loads((output / "fim_manifest.json").read_text())
    assert document["aoi_mask"] == "rasterio-center-mask/1"
    assert document["aoi"]["geometry_wkb_hex"] == polygon.wkb_hex
    with rasterio.open(result.iloc[0].depth_tif) as src:
        assert 0 < np.isfinite(src.read(1)).sum() < src.width * src.height
