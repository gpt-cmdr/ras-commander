"""Opt-in bounded/full comparison using computed public models; no HEC-RAS run."""
import json
import os
from pathlib import Path
import pytest


def test_native_bounded_maps_equal_independently_masked_full_maps(tmp_path):
    filename=os.environ.get('RAS_COMMANDER_AOI_LATTICE_CASE')
    if not filename:
        pytest.skip('Set RAS_COMMANDER_AOI_LATTICE_CASE to external computed model cases')
    from scripts.benchmarks.fim_aoi_full_crop_compare import run
    result=run(json.loads(Path(filename).read_text(encoding='utf-8')),tmp_path/'compare')
    assert result['status']=='complete'
    assert all(m[k]==0 for r in result['runs'] for m in r['metrics']
        for k in ('extra','missing','different'))


def test_prepared_context_preserves_global_pixel_center_edges(tmp_path):
    filename=os.environ.get('RAS_COMMANDER_AOI_LATTICE_CASE')
    if not filename:
        pytest.skip('Set RAS_COMMANDER_AOI_LATTICE_CASE to external computed model cases')
    import rasterio
    from ras_commander import RasFim
    from scripts.benchmarks.fim_aoi_full_crop_compare import shapes, compare
    from scripts.benchmarks.fim_supplied_wsel_compare import selector_table
    cases=json.loads(Path(filename).read_text(encoding='utf-8'))
    case=cases['models'][0]
    table=selector_table(case['hdf'],case['profiles'])
    with rasterio.open(case['terrain']) as src:
        source_transform=src.transform
    with RasFim.prepare_sloping_model(case['hdf'],case['terrain'],
            wsel_profiles=table,engine_path=cases.get('engine'),threads=4,
            render_mode='slopingPretty',reduce_shallow_to_horizontal=True,
            use_depth_weighted_faces=True,max_working_mib=4096,max_prepared_mib=4096) as model:
        full=model.map_profiles(tmp_path/'full',max_inflight_profiles=2)
        with rasterio.open(full.iloc[0].depth_tif) as src:
            polygon=shapes(src.width,src.height,src.transform)['center_edge']
            crs=src.crs
        bounded=model.map_profiles(tmp_path/'bounded',polygon=polygon,aoi_crs=crs,max_inflight_profiles=2)
        for a,b in zip(bounded.itertuples(),full.itertuples()):
            for band in ('depth_tif','wse_tif'):
                metrics=compare(getattr(a,band),getattr(b,band),polygon,source_transform)
                assert all(metrics[k]==0 for k in ('extra','missing','different'))
