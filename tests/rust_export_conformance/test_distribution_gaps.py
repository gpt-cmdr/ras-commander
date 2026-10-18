"""Separate upstream distribution gap probe: real low-zoom tile validity."""
import json
import os
from pathlib import Path

import pytest
gpd = pytest.importorskip("geopandas")
import shapely
from shapely.geometry import shape
from ras_commander import fast_hdf
from ras_commander.hdf import HdfMesh
from .helpers import decode, pack
from .test_packed_pmtiles import provenance


def test_freestiler_real_low_zoom_validity_gap(tmp_path):
    root = os.environ.get("RAS_EXPORT_FIXTURE_ROOT")
    if not root:
        pytest.skip("Set RAS_EXPORT_FIXTURE_ROOT to copied qualification HDFs")
    source = HdfMesh.get_mesh_cell_polygons(Path(root) / "BaldEagleDamBrk.p18.hdf", backend="python")
    assert not source.empty
    # Native source rings are unchanged. This is a rendering-output probe.
    source = source.to_crs(4326).reset_index(drop=True)
    layer = pack(list(source.geometry))
    layer["properties"] = {"index": list(range(len(source)))}
    output = tmp_path / "native.pmtiles"
    fast_hdf.export_pmtiles(output, {"cells": layer}, min_zoom=6, max_zoom=6,
                           backend="rust", threads=2)
    freestiler = pytest.importorskip("freestiler")
    reference = tmp_path / "reference.pmtiles"
    frame = gpd.GeoDataFrame({"index": list(range(len(source)))}, geometry=source.geometry, crs=4326)
    freestiler.freestile({"cells": frame}, reference, min_zoom=6, max_zoom=6,
                        simplification=False, quiet=True)
    _, _, tiles = decode(output)
    _, _, expected = decode(reference)
    assert tiles.keys() == expected.keys()
    invalid = []
    seen = set()
    for address, layers in tiles.items():
        ref_features = {f["properties"]["index"]: f for f in expected[address]["cells"]["features"]}
        for feature in layers["cells"]["features"]:
            i = feature["properties"]["index"]
            seen.add(i)
            assert feature["geometry"] == ref_features[i]["geometry"]
            geom = shape(feature["geometry"])
            if not geom.is_valid:
                invalid.append(dict(tile=address, index=i, mesh=str(source.iloc[i].mesh_name),
                    cell_id=int(source.iloc[i].cell_id), reason=shapely.is_valid_reason(geom),
                    geometry=feature["geometry"]))
    assert seen == set(range(len(source)))
    (tmp_path / "gap.json").write_text(json.dumps(dict(source_features=len(source),
        seen_features=len(seen), tiles=len(tiles), invalid=invalid, exact_upstream_geometry=True), indent=2))
    if invalid:
        pytest.xfail(f"Freestiler beb64b0/0.3.0 reproduces {len(invalid)} invalid integer polygons; see gap.json")
