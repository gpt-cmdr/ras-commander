"""Fresh-process adapter benchmark on repeated retained real final regions.

Peak working set includes imports/source loading; sampled temporary disk is a
lower bound, not a guaranteed spool maximum. No full-model scaling claim.
"""
import argparse
import json
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))


def child(args):
    os.environ['RAYON_NUM_THREADS']='2'
    temporary=Path(args.output)/'private-temp';temporary.mkdir()
    os.environ['TEMP']=str(temporary.resolve());os.environ['TMP']=str(temporary.resolve())
    import geopandas as gpd
    import pandas as pd
    import numpy as np
    import pyarrow as pa
    import psutil
    import ras_commander
    import ras_commander_fast_hdf as native
    from ras_commander import fast_hdf
    from rust_first_tier_exports.helpers import table
    import freestiler
    assert Path.cwd().resolve()==ROOT
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT/'ras_commander')
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert hasattr(native,'validate_export_wkb')
    assert Path(sys.modules['ras_commander_fast_hdf.ras_commander_fast_hdf'].__file__).resolve().is_relative_to(ROOT/'.venv')
    started=time.perf_counter();source=gpd.read_file(args.fixture,layer='regions',fid_as_index=True)
    copies=[]
    for replica in range((args.count+len(source)-1)//len(source)):
        block=source.copy()
        block['cell_id']=block.index.to_numpy(dtype=np.int64)
        block['mesh_name']=block.mesh_name+'::replica='+str(replica)
        copies.append(block)
    source=gpd.GeoDataFrame(pd.concat(copies,ignore_index=True).iloc[:args.count],crs=source.crs)
    source=source[['mesh_name','cell_id','classification','area_acres','geometry']]
    loading=time.perf_counter()-started;started=time.perf_counter();metrics={}
    if args.child=='typed':
        t=table(source.geometry.to_numpy(),source.crs,mesh_names=source.mesh_name.to_numpy(),cell_ids=source.cell_id.to_numpy(),
            columns={'classification':pa.array(source.classification,type=pa.string()),'area_acres':pa.array(source.area_acres)})
    preparation=time.perf_counter()-started;started=time.perf_counter()
    if args.child=='typed':
        metrics=fast_hdf.export_arrow_pmtiles(Path(args.output)/'bundle',t,source_crs=source.crs,
            min_zoom=12,max_zoom=12,max_batch_rows=256,threads=2)
        output=Path(args.output)/'bundle/tiles.pmtiles'
    else:
        output=Path(args.output)/'reference.pmtiles'
        freestiler.freestile({'features':source},output,min_zoom=12,max_zoom=12,simplification=False,quiet=True)
    elapsed=time.perf_counter()-started
    report=dict(route=args.child,rows=len(source),loading_seconds=loading,preparation_seconds=preparation,
        export_seconds=elapsed,adapter_plus_export_seconds=preparation+elapsed,native_metrics=metrics,
        process_peak_working_set_bytes=psutil.Process().memory_info().peak_wset,
        archive_bytes=output.stat().st_size,output=str(output))
    (Path(args.output)/'sample.json').write_text(json.dumps(report,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fixture',required=True)
    p.add_argument('--output',required=True);p.add_argument('--count',type=int,default=512)
    p.add_argument('--samples',type=int,default=3);p.add_argument('--child',choices=['typed','reference'])
    args=p.parse_args()
    if args.child:return child(args)
    import psutil
    from rust_export_conformance.helpers import decode
    import shapely
    from shapely.geometry import shape
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    jobs=[(route,i) for route in ['typed','reference'] for i in range(args.samples)]
    random.Random(18).shuffle(jobs);reports=[]
    for route,i in jobs:
        folder=output/f'{route}-{i}';folder.mkdir()
        process=subprocess.Popen([sys.executable,__file__,'--fixture',args.fixture,'--output',str(folder),'--count',str(args.count),'--child',route])
        peak=0;samples=0
        while process.poll() is None:
            total=0
            for path in folder.rglob('*'):
                if path.is_file() and 'bundle' not in path.relative_to(folder).parts and path.name not in ('reference.pmtiles','sample.json'):
                    try:total+=path.stat().st_size
                    except FileNotFoundError:pass
            peak=max(peak,total);samples+=1;time.sleep(.004)
        if process.returncode:raise RuntimeError(f'{route} failed: {process.returncode}')
        report=json.loads((folder/'sample.json').read_text());report.update(sampled_temporary_peak_bytes=peak,poll_samples=samples)
        reports.append(report)
    for i in range(args.samples):
        a=decode(output/f'typed-{i}/bundle/tiles.pmtiles')[2];b=decode(output/f'reference-{i}/reference.pmtiles')[2]
        assert a.keys()==b.keys()
        def records(layer):return {(f['properties']['mesh_name'],f['properties']['cell_id']):(shapely.normalize(shape(f['geometry'])).wkb,f['properties']) for f in layer['features']}
        for address in a:assert records(a[address]['features'])==records(b[address]['features'])
    medians={route:{key:statistics.median(r[key] for r in reports if r['route']==route)
        for key in ['preparation_seconds','export_seconds','adapter_plus_export_seconds','process_peak_working_set_bytes','sampled_temporary_peak_bytes','archive_bytes']}
        for route in ['typed','reference']}
    (output/'measurements.json').write_text(json.dumps(dict(samples=reports,medians=medians,decoded_geometry_properties_equal=True,
        caveats='Whole-process working set; sampled temporary disk lower bound; repeated real footprint; no codec-build parity or whole-model scaling claim.'),indent=2))
    print(json.dumps(medians,indent=2))


if __name__=='__main__':main()
