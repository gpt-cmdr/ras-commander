"""One-time whole-model extraction, immutable input and explicit preparation receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def prepare(fixture, output, version, expected):
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    import shapely
    from ras_commander.hdf import HdfBase, HdfMesh, HdfResultsMesh
    from tests.rust_first_tier_exports.helpers import table, write_input
    import ras_commander
    assert Path.cwd() == ROOT and Path(ras_commander.__file__).resolve().is_relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    before = hashlib.file_digest(fixture.open('rb'), 'sha256').hexdigest()
    start = time.perf_counter()
    if version == 'regions7':
        import geopandas as gpd
        cells = gpd.read_file(fixture, layer='regions')
        cells['cell_id'] = np.arange(len(cells), dtype=np.int64)
        columns = {'classification': pa.array(cells.classification, type=pa.string()),
                   'area_acres': pa.array(cells.area_acres, type=pa.float64())}
        attrs = json.loads(fixture.with_name('computed7.json').read_text())
        diagnostics = []; physical = len(cells); summary = True
    else:
        attrs = HdfBase.get_attrs(fixture, '/')
        assert f'HEC-RAS {version}' in attrs['File Version']
        cells = HdfMesh.get_mesh_cell_polygons(fixture, engine='h5py')
        diagnostics = cells.attrs.get('cell_polygon_diagnostics', ())
        physical = sum(int(c) for _, c in HdfBase.get_2d_flow_area_names_and_counts(fixture))
        # Clear large per-cell diagnostics before pandas merge; retain omissions in receipt.
        cells.attrs = {}
        values = HdfResultsMesh.get_mesh_max_ws(fixture, round_to='1ms')
        summary = not values.empty
        if summary:
            values.attrs = {}
            cells = cells.merge(values[['mesh_name', 'cell_id', 'maximum_water_surface',
                'maximum_water_surface_time']], on=['mesh_name', 'cell_id'], validate='one_to_one')
            numeric = cells.maximum_water_surface.to_numpy(dtype=float)
            times = pa.Array.from_pandas(cells.maximum_water_surface_time).cast(pa.timestamp('ms'))
        else:
            assert version == '6.6'
            numeric = np.full(len(cells), np.nan)
            times = pa.nulls(len(cells), type=pa.timestamp('ms'))
        columns = {'max_wse': pa.array(numeric, mask=~np.isfinite(numeric)), 'peak_ms': times}
    extraction = time.perf_counter() - start
    assert len(cells) == expected, (len(cells), expected)
    assert cells.crs is not None and cells.is_valid.all() and not cells.is_empty.any()
    assert not cells.duplicated(['mesh_name', 'cell_id']).any()
    omitted = [d for d in diagnostics if d.get('status') in ('omitted','ambiguous','read_error','not_present')]
    if version == '5.0.7': assert physical - len(cells) == 2
    else: assert physical == len(cells)
    stages = {}
    for geographic, name in [(False, 'native'), (True, 'geographic')]:
        start = time.perf_counter()
        prepared = table(cells.geometry.to_numpy(), cells.crs, target_geojson=geographic,
            mesh_names=cells.mesh_name.to_numpy(), cell_ids=cells.cell_id.to_numpy(), columns=columns)
        encode = time.perf_counter() - start
        start = time.perf_counter(); write_input(prepared, output/(name+'.arrow'), batch_size=4096)
        stages[name] = {'transform_geometry_encode_seconds': encode,
            'prepared_ipc_write_seconds': time.perf_counter()-start,
            'prepared_ipc_bytes': (output/(name+'.arrow')).stat().st_size}
    assert hashlib.file_digest(fixture.open('rb'), 'sha256').hexdigest() == before
    receipt = dict(fixture=str(fixture), sha256=before, version=version, rows=len(cells),
        physical_cells=physical, omitted_source_cells=physical-len(cells), diagnostics=omitted,
        crs=cells.crs.to_wkt(), summary_available=summary, extraction_seconds=extraction,
        stages=stages, attrs=attrs, identities_unique=True,
        note='Region IDs are deterministic retained-region row IDs within mesh namespace; source-cell IDs unchanged. No repeated features.')
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2, default=str))
    print(json.dumps({k:receipt[k] for k in ['version','rows','physical_cells','omitted_source_cells','extraction_seconds']}, default=str))


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True); p.add_argument('--version',required=True)
    p.add_argument('--expected',type=int,required=True); args=p.parse_args()
    prepare(args.fixture,args.output,args.version,args.expected)
