"""Columnar qualification boundary and proposed thin Python integration.

No per-feature Python dictionaries. CRS comparison/reprojection is explicit.
"""
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pyarrow as pa
from pyproj import CRS, Transformer
import shapely

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / 'tests/rust_first_tier_exports/harness/target/debug/export-test-harness.exe'


def table(geometries, source_crs, *, target_geojson=False, declared_crs=None,
          columns=None, mesh_names=None, cell_ids=None):
    if source_crs is None:
        raise ValueError('missing source CRS')
    crs = CRS(source_crs)
    if declared_crs is not None and not crs.equals(CRS(declared_crs)):
        raise ValueError('conflicting source CRS')
    geometries = np.asarray(geometries, dtype=object)
    if np.any(shapely.has_z(geometries)) or np.any(shapely.has_m(geometries)):
        raise ValueError('XY export requires an explicit Z/M conversion policy')
    if target_geojson:
        transformer = Transformer.from_crs(crs, 4326, always_xy=True)
        geometries = shapely.transform(geometries, transformer.transform, interleaved=False)
        geometries = shapely.orient_polygons(geometries, exterior_cw=False)
        crs = CRS(4326)
    n = len(geometries)
    evidence = dict(wkt=crs.to_wkt(), projjson=crs.to_json_dict(),
        units=crs.axis_info[0].unit_name, axis_order='xy', resolved=True,
        geographic_wgs84=crs.equals(CRS(4326), ignore_axis_order=True))
    data = {'mesh_name': pa.array(mesh_names if mesh_names is not None else ['mesh'] * n, type=pa.string()),
            'cell_id': pa.array(cell_ids if cell_ids is not None else np.arange(n), type=pa.int64())}
    if columns:
        data.update(columns)
    data['geometry'] = pa.array(shapely.to_wkb(geometries, output_dimension=2, flavor='iso'), type=pa.binary())
    fields = [pa.field(k, v.type, nullable=k not in ('mesh_name', 'cell_id')) for k,v in data.items()]
    fields[-1] = fields[-1].with_metadata({'ARROW:extension:name': 'geoarrow.wkb',
        'ARROW:extension:metadata': json.dumps({'crs': crs.to_json_dict(), 'crs_type': 'projjson'})})
    schema = pa.schema(fields, metadata={'ras:export:v1': json.dumps(evidence)})
    return pa.Table.from_arrays(list(data.values()), schema=schema)


def write_input(t, path, batch_size=2):
    with pa.OSFile(str(path), 'wb') as sink, pa.ipc.new_file(sink, t.schema) as writer:
        for batch in t.to_batches(max_chunksize=batch_size):
            writer.write_batch(batch)


def export(t, directory, fmt, *, batch_size=2, max_rows=65536, name='output', check=True):
    directory = Path(directory)
    input_path = directory / (name + '.input.arrow')
    output_path = directory / (name + '.' + fmt)
    write_input(t, input_path, batch_size)
    result = subprocess.run([str(Path(os.environ.get('RAS_EXPORT_HARNESS', HARNESS))),
        str(input_path), str(output_path), fmt, str(max_rows)], capture_output=True, text=True)
    if check and result.returncode:
        raise AssertionError(result.stderr)
    return output_path, json.loads(result.stdout) if result.returncode == 0 else result
