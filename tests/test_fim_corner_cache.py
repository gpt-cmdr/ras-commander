"""Opt-in real native corner-cache mapping and prepared-context invalidation."""

import json
import os
from pathlib import Path
import shutil

import pytest


@pytest.fixture
def case():
    filename = os.environ.get("RAS_FIM_CORNER_CASE")
    if not filename:
        pytest.skip("set RAS_FIM_CORNER_CASE to a prepared real-model cache case")
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def copied_cache(case, tmp_path, *, receipt=True):
    source = Path(case["postprocessing_hdf"])
    target = tmp_path / "corners" / source.name
    target.parent.mkdir()
    shutil.copy2(source, target)
    if receipt:
        document = json.loads((source.parent / "corner_elevation_receipt.json").read_text())
        relatives = {}
        for filename in document["inputs"]:
            path = Path(filename)
            if not path.exists():
                path = (source.parent / document["relative_inputs"][filename]).resolve()
            relatives[filename] = os.path.relpath(path, target.parent).replace("\\", "/")
        document["relative_inputs"] = relatives
        (target.parent / "corner_elevation_receipt.json").write_text(json.dumps(document))
    return target


@pytest.mark.parametrize("threads", [1, 4])
def test_cache_only_mapping_matches_native(case, tmp_path, threads):
    from ras_commander import RasFim, HdfMesh
    from scripts.benchmarks.fim_sloping_compare import compare_raw
    from shapely.geometry import box

    cache = copied_cache(case, tmp_path)
    fields = {"bbox": case["bbox"]} if "bbox" in case else {}
    result = RasFim.map_sloping_profiles(
        case["hdf"], case["terrain"], tmp_path / "maps", profiles=case["profiles"],
        engine_path=case["engine"], threads=threads, max_working_mib=4096,
        render_mode="slopingPretty", use_depth_weighted_faces=True,
        reduce_shallow_to_horizontal=True, postprocessing_hdf=cache,
        corner_elevation_source="mapping_cache", **fields,
    )
    cells = HdfMesh.get_mesh_cell_polygons(case["hdf"], strict=True)
    aoi = box(*case["bbox"]) if "bbox" in case else None
    provenance = result.attrs["performance"]["corner_elevations"]
    assert provenance and all(v["source"]["layout"] == "mapping_cache" for v in provenance.values())
    for row in result.itertuples():
        for band, path in (("depth", row.depth_tif), ("wse", row.wse_tif)):
            metrics = compare_raw(path, case["references"][row.profile][band], cells, aoi, chunk_rows=256)
            assert metrics["common"] > 0
            assert all(metrics[key] == 0 for key in ("extra", "missing", "different", "outside_footprint"))


def test_cache_only_mapping_requires_receipt(case, tmp_path):
    from ras_commander import RasFim

    cache = copied_cache(case, tmp_path, receipt=False)
    with pytest.raises(ValueError, match="prepare_corner_elevations"):
        RasFim.map_sloping_profiles(
            case["hdf"], case["terrain"], tmp_path / "maps", profiles=case["profiles"],
            engine_path=case["engine"], threads=1, max_working_mib=4096,
            render_mode="slopingPretty", use_depth_weighted_faces=True,
            postprocessing_hdf=cache, corner_elevation_source="mapping_cache",
            **({"bbox": case["bbox"]} if "bbox" in case else {}),
        )
    assert not list((tmp_path / "maps").glob("*.tif"))


def test_prepared_context_invalidates_changed_cache(case, tmp_path):
    from ras_commander import RasFim
    from ras_commander.fim.errors import FimEngineError

    cache = copied_cache(case, tmp_path)
    with RasFim.prepare_sloping_model(
        case["hdf"], case["terrain"], profiles=case["profiles"],
        engine_path=case["engine"], threads=4, max_working_mib=4096,
        render_mode="slopingPretty", use_depth_weighted_faces=True,
        postprocessing_hdf=cache, corner_elevation_source="mapping_cache",
    ) as model:
        stat = cache.stat()
        os.utime(cache, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
        with pytest.raises(FimEngineError, match="changed"):
            model.map_profiles(tmp_path / "maps")
        assert model.closed
