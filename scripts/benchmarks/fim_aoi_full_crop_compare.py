"""Compare bounded maps to independently masked unbounded maps, no RAS execution."""
from pathlib import Path
import argparse
import importlib.metadata as md
import json
import platform
import sys
import time

import numpy as np
import rasterio
from rasterio.windows import Window
from ras_commander.fim._aoi_lattice import mask as lattice_mask
from shapely.affinity import affine_transform
from shapely.geometry import Polygon, MultiPolygon, LineString, box, mapping

from ras_commander import RasFim, HdfMesh
from ras_commander.fast_hdf import backend_scope
from scripts.benchmarks.fim_supplied_wsel_compare import selector_table, sha256, compare_products
import pandas as pd


def shapes(width, height, transform):
    w, h = float(width), float(height)
    items = {
        'bbox': box(.123*w, .167*h, .873*w, .891*h),
        'triangle': Polygon([(.07*w,.08*h),(.93*w,.12*h),(.71*w,.94*h)]),
        'concave': Polygon([(.06*w,.09*h),(.94*w,.09*h),(.94*w,.38*h),
            (.43*w,.38*h),(.43*w,.91*h),(.06*w,.91*h)]),
        'hole': Polygon([(.04*w,.06*h),(.96*w,.06*h),(.96*w,.94*h),(.04*w,.94*h)],
            holes=[[ (.34*w,.32*h),(.67*w,.32*h),(.67*w,.68*h),(.34*w,.68*h) ]]),
        'multipart': MultiPolygon([box(.04*w,.07*h,.43*w,.93*h),
            Polygon([(.58*w,.11*h),(.96*w,.29*h),(.91*w,.91*h),(.57*w,.77*h)])]),
        'sliver': LineString([(.061*w,.127*h),(.933*w,.871*h)]).buffer(.72, cap_style=2),
        'center_edge': box(10.5, 12.5, w-11.5, h-13.5),
        'tile_crossing': Polygon([(.017*w,.153*h),(.977*w,.193*h),(.913*w,.947*h),
            (.477*w,.709*h),(.091*w,.897*h)]),
    }
    coeffs = [transform.a, transform.b, transform.d, transform.e, transform.c, transform.f]
    return {name: affine_transform(g, coeffs) for name,g in items.items()}


def compare(candidate, reference, geometry, source_transform):
    with rasterio.open(candidate) as a, rasterio.open(reference) as b:
        assert a.crs == b.crs and a.dtypes == b.dtypes == ('float32',)
        col, row = (~b.transform) * (a.transform.c, a.transform.f)
        assert abs(col-round(col)) < 1e-6 and abs(row-round(row)) < 1e-6
        col, row = round(col), round(row)
        assert np.allclose(tuple(a.transform), tuple(b.window_transform(
            Window(col,row,a.width,a.height))), rtol=0, atol=1e-8)
        actual = a.read(1, masked=True)
        full = b.read(1, masked=True)
        # Independent NumPy AOI coverage on the FULL source lattice, not a crop transform.
        source_col, source_row = (~source_transform) * (b.transform.c, b.transform.f)
        assert abs(source_col-round(source_col)) < 1e-6 and abs(source_row-round(source_row)) < 1e-6
        inside = lattice_mask(geometry, source_transform,
            Window(round(source_col),round(source_row),b.width,b.height))
        expected_valid_full = inside & ~np.ma.getmaskarray(full)
        expected_count = int(expected_valid_full.sum())
        assert col>=0 and row>=0 and col+a.width<=b.width and row+a.height<=b.height
        expected = full.data[row:row+a.height, col:col+a.width]
        expected_valid = expected_valid_full[row:row+a.height, col:col+a.width]
        valid = ~np.ma.getmaskarray(actual)
        common = valid & expected_valid
        extra = int(np.count_nonzero(valid & ~expected_valid))
        # Count reference-valid pixels outside the candidate extent as missing too.
        missing = expected_count - int(np.count_nonzero(common))
        different = int(np.count_nonzero(actual.data[common].view('u4') != expected[common].view('u4')))
        return dict(extra=extra, missing=missing, different=different,
            expected_valid=expected_count, candidate_valid=int(valid.sum()),
            total_reference_pixels=full.size, compared_valid=int(common.sum()))


def run(cases, output):
    output.mkdir(parents=True,exist_ok=False)
    engine = cases.get('engine')
    engine_info = RasFim.get_engine_info(engine)
    engine_file = engine_info['engine_path']
    engine_sha = sha256(engine_file)
    receipt = dict(status='in_progress', python=sys.version, platform=platform.platform(),
        packages={p:md.version(p) for p in ('ras-commander','ras-commander-fast-map','ras-commander-fast-hdf')},
        source_commit=cases['commander_commit'], engine=engine_info['method']['engine'], engine_sha256=engine_sha,
        criterion='Full reference independently masked by NumPy global-terrain-lattice/1; complete masks and valid float32 bits; no resampling/cutoff',
        runs=[], sources={}, errors=[], unbounded_baselines=[], harness_sha256=sha256(Path(__file__)))
    try:
        for case in cases['models']:
            label=case['label']; hdf=case['hdf']; terrain=case['terrain']
            import re
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', label):
                raise ValueError('Model label must be a safe directory name')
            receipt['sources'][label] = {p:sha256(p) for p in [hdf,terrain]}
            with backend_scope('rust'):
                table=selector_table(hdf,case['profiles'])
                if label=='davis':
                    table['window_peak']=np.maximum(table['t0054'],table['t0108']).round(3)
                table=table.sample(frac=1,random_state=924)
                cells=HdfMesh.get_mesh_cell_polygons(hdf,strict=True,engine='native',threads=4)
            cells=cells.merge(table,on=['mesh_name','cell_id'],validate='one_to_one')
            cells['cell_idx']=np.arange(len(cells),dtype=np.int64)
            names=list(table.columns[2:])
            options=[('horizontal',{}),('sloping',dict(render_mode='sloping'))]
            options += [('faces-r%d-w%d'%(r,w),dict(render_mode='slopingPretty',
                reduce_shallow_to_horizontal=bool(r),use_depth_weighted_faces=bool(w)))
                for r in (0,1) for w in (0,1)]
            with rasterio.open(terrain) as src:
                source_transform = src.transform
                terrain_info=dict(width=src.width,height=src.height,blocks=src.block_shapes,
                    transform=list(src.transform),tiled=src.is_tiled)
            for mode,flags in options:
                if cases.get('modes') and mode not in cases['modes']:
                    continue
                started=time.perf_counter()
                target=output/label/mode
                def map_it(folder,mask=None):
                    kw=dict(engine_path=engine,threads=4,writer_threads=1,max_working_mib=case.get('max_working_mib',4096),
                        write_floodplain=False,**(mask or {}))
                    if mode=='horizontal':
                        return RasFim.map_horizontal_profiles(cells,terrain,folder,
                            profiles=names,min_depth=0,hdf_path=hdf,**kw)
                    return RasFim.map_sloping_profiles(hdf,terrain,folder,
                        wsel_profiles=table,max_inflight_profiles=2,**flags,**kw)
                try:
                    full=map_it(target/'full')
                    if cases.get('baseline_root'):
                        prior=Path(cases['baseline_root'])/label/mode/'full'/'fim_manifest.json'
                        before=pd.DataFrame(json.loads(prior.read_text(encoding='utf-8'))['profiles'])
                        metrics=compare_products(full,before)
                        receipt['unbounded_baselines'].append(dict(model=label,mode=mode,metrics=metrics))
                    with rasterio.open(full.iloc[0].depth_tif) as ds:
                        geometries=shapes(ds.width,ds.height,ds.transform)
                        grid=dict(width=ds.width,height=ds.height,transform=list(ds.transform),crs=str(ds.crs))
                    for name,geometry in geometries.items():
                        if cases.get('shapes') and name not in cases['shapes']:
                            continue
                        mask=dict(bbox=geometry.bounds) if name=='bbox' else dict(polygon=geometry,aoi_crs=cells.crs)
                        bounded=map_it(target/name,mask)
                        metrics=[]
                        for a,b in zip(bounded.itertuples(),full.itertuples()):
                            assert a.profile==b.profile
                            for band in ('depth_tif','wse_tif'):
                                metrics.append(dict(profile=a.profile,band=band,
                                    **compare(getattr(a,band),getattr(b,band),geometry,source_transform)))
                        ok=all(m[k]==0 for m in metrics for k in ('extra','missing','different'))
                        receipt['runs'].append(dict(model=label,mode=mode,shape=name,passed=ok,
                            grid=grid,terrain=terrain_info,geometry=mapping(geometry),metrics=metrics))
                        print(label,mode,name,'PASS' if ok else 'FAIL',
                            'valid='+str(sum(m['expected_valid'] for m in metrics)),flush=True)
                except Exception as e:
                    receipt['errors'].append(dict(model=label,mode=mode,error=repr(e)))
                    print(label,mode,'ERROR',repr(e),flush=True)
                elapsed = time.perf_counter()-started
                print('elapsed',round(elapsed,3),flush=True)
                (output/'comparison.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
            assert receipt['sources'][label]=={p:sha256(p) for p in [hdf,terrain]}
        assert sha256(engine_file) == engine_sha
        receipt['status']='complete' if not receipt['errors'] and all(r['passed'] for r in receipt['runs']) else 'failed'
    finally:
        (output/'comparison.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(receipt['status'], 'runs',len(receipt['runs']), 'errors',len(receipt['errors']),flush=True)
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('case',type=Path);parser.add_argument('output',type=Path)
    args=parser.parse_args()
    receipt=run(json.loads(args.case.read_text()),args.output)
    raise SystemExit(0 if receipt['status']=='complete' else 1)
