"""Integration review: source encoding and field metadata must survive adapters."""
import json
from pathlib import Path
import numpy as np
import pyarrow as pa
import pytest
import shapely
from shapely.geometry import Point
from .helpers import ROOT, table
from ras_commander.fast_hdf import export_arrow

@pytest.mark.parametrize("fmt", ["geojson", "jsonl"])
@pytest.mark.parametrize("encoding", ["ewkb", "trailing", "nested_ewkb"])
def test_source_encoding_rejected_before_reprojection(tmp_path, fmt, encoding):
    geom = Point(1, 2)
    if encoding == "ewkb":
        raw = shapely.to_wkb(shapely.set_srid(geom, 3857), include_srid=True)
    elif encoding == "nested_ewkb":
        # A plain multi header does not make its EWKB child acceptable.
        import struct
        child = shapely.to_wkb(shapely.set_srid(geom, 3857), include_srid=True)
        raw = struct.pack("<BII", 1, 4, 1) + child
    else:
        raw = shapely.to_wkb(geom) + b"junk"
    source = table([geom], 4326)
    source = source.set_column(source.schema.get_field_index("geometry"),
        source.schema.field("geometry"), pa.array([raw], type=pa.binary()))
    with pytest.raises(ValueError):
        export_arrow(tmp_path/"output", source, source_crs=4326, format=fmt)
    assert not list(tmp_path.iterdir())


def test_geometry_field_metadata_preserved(tmp_path):
    source = table([Point(1, 2)], 4326)
    field = source.schema.field("geometry")
    metadata = dict(field.metadata)
    metadata[b"source-provenance"] = b"fixture:mesh:cell"
    extension = json.loads(metadata[b"ARROW:extension:metadata"])
    extension["application-provenance"] = "original geometry"
    metadata[b"ARROW:extension:metadata"] = json.dumps(extension).encode()
    source = source.set_column(source.schema.get_field_index("geometry"),
        field.with_metadata(metadata), source["geometry"])
    output = tmp_path/"out.arrow"
    export_arrow(output, source, source_crs=4326, format="arrow")
    result = pa.ipc.open_file(output).read_all()
    actual = result.schema.field("geometry").metadata
    assert actual[b"source-provenance"] == metadata[b"source-provenance"]
    assert json.loads(actual[b"ARROW:extension:metadata"])["application-provenance"] == "original geometry"
    assert result["geometry"].equals(source["geometry"])


def test_borrowed_source_buffers_support_slices_and_null_bitmap(tmp_path):
    import ras_commander_fast_hdf as native
    assert Path(native.__file__).resolve().is_relative_to(ROOT/".venv")
    source = table([Point(1, 2), None, Point(3, 4)], 4326).slice(1, 2)
    output = tmp_path/"out.geojson"
    metrics = export_arrow(output, source, source_crs=4326, format="geojson")
    assert metrics["rows"] == 2
    features = json.loads(output.read_text())["features"]
    assert features[0]["geometry"] is None
    assert features[1]["geometry"]["coordinates"] == [3.0, 4.0]
    values = source["geometry"].chunk(0)
    bits, offsets, data = values.buffers()
    native.validate_export_wkb(np.frombuffer(offsets, dtype=np.int32),
        np.frombuffer(data, dtype=np.uint8), np.frombuffer(bits, dtype=np.uint8),
        values.offset, len(values))
    with pytest.raises(ValueError):
        native.validate_export_wkb(np.array([0, 20], dtype=np.int32),
            np.array([0], dtype=np.uint8), None, 0, 1)
