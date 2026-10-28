"""Fresh-process equivalent writers; actual timings, never an assumed speedup.

Usage: python .../benchmark.py --output working/export-benchmark --rows 10000
Input is the retained final polygon GeoPackage, repeated without simplification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


def worker(args):
    import geopandas as gpd
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyogrio
    import psutil
    from tests.rust_first_tier_exports.helpers import table,write_input
    started=time.perf_counter()
    source=gpd.read_file(args.input)
    source=source.iloc[np.arange(args.rows)%len(source)].reset_index(drop=True)
    source['cell_id']=np.arange(len(source),dtype=np.int64)
    extraction=time.perf_counter()-started
    start=time.perf_counter()
    if args.format in ('geojson','jsonl'):
        import shapely
        source=source.to_crs(4326)
        source.geometry=shapely.orient_polygons(source.geometry.to_numpy(),exterior_cw=False)
    transform=time.perf_counter()-start
    out=args.output/f'{args.route}-{args.format}-{args.sample}.{args.format}'
    prep=time.perf_counter()
    metrics={}
    if args.route=='rust':
        import ras_commander_fast_hdf as native
        assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
        t=table(source.geometry.to_numpy(),source.crs,mesh_names=source.mesh_name.to_numpy(),
            cell_ids=source.cell_id.to_numpy(),columns={
                'classification':pa.array(source.classification,type=pa.string()),
                'area_acres':pa.array(source.area_acres,type=pa.float64())})
        ipc=out.with_suffix('.input.arrow')
        write_input(t,ipc,batch_size=4096)
        prep_seconds=time.perf_counter()-prep
        export=time.perf_counter()
        metrics=json.loads(native.export_ipc_file(ipc,out,args.format,4096))
        export_seconds=time.perf_counter()-export
        ipc_bytes=ipc.stat().st_size
    else:
        source=source[['mesh_name','cell_id','classification','area_acres','geometry']]
        prep_seconds=time.perf_counter()-prep
        export=time.perf_counter()
        if args.format=='parquet': source.to_parquet(out,compression='snappy',index=False,row_group_size=65536)
        elif args.format=='arrow':
            t=table(source.geometry.to_numpy(),source.crs,mesh_names=source.mesh_name.to_numpy(),cell_ids=source.cell_id.to_numpy(),
                columns={'classification':pa.array(source.classification,type=pa.string()),'area_acres':pa.array(source.area_acres,type=pa.float64())})
            write_input(t,out,batch_size=4096)
        else:
            driver={'fgb':'FlatGeobuf','gpkg':'GPKG','geojson':'GeoJSON','jsonl':'GeoJSONSeq'}[args.format]
            options={'SPATIAL_INDEX':'YES'} if args.format in ('fgb','gpkg') else ({'COORDINATE_PRECISION':'15'} if args.format in ('geojson','jsonl') else None)
            pyogrio.write_dataframe(source,out,driver=driver,layer='features',layer_options=options)
        export_seconds=time.perf_counter()-export
        ipc_bytes=0
    writer_memory=psutil.Process().memory_info()
    # Independent geometry/identity check is outside the measured writer time.
    if args.format=='parquet':
        read=pq.read_table(out)
        assert read.num_rows==len(source) and set(read['cell_id'].to_pylist())==set(source.cell_id)
    elif args.format=='arrow': assert pa.ipc.open_file(out).read_all().num_rows==len(source)
    else:
        metadata,read=pyogrio.read_arrow(out)
        geometry_column=metadata['geometry_name'] or 'wkb_geometry'
        assert read.num_rows==len(source) and set(read['cell_id'].to_pylist())==set(source.cell_id)
    import shapely
    if args.format!='arrow':
        geometry_column='geometry' if args.format=='parquet' else geometry_column
        ordered=read.take(pa.array(np.argsort(read['cell_id'].to_numpy())))
        assert shapely.equals_exact(shapely.from_wkb(ordered[geometry_column].to_numpy()),
            source.geometry.to_numpy(),1e-12 if args.format in ('geojson','jsonl') else 0).all()
        assert ordered['classification'].to_pylist()==source.classification.tolist()
    memory=writer_memory
    record=dict(route=args.route,format=args.format,sample=args.sample,rows=len(source),
        extraction_seconds=extraction,transform_seconds=transform,prepare_seconds=prep_seconds,
        export_seconds=export_seconds,adapter_and_export_seconds=prep_seconds+export_seconds,
        rust_stages=metrics,peak_rss_bytes=getattr(memory,'peak_wset',None),output_bytes=out.stat().st_size,
        ipc_temp_bytes=ipc_bytes,
        stages_unavailable=['separate geometry encoding','separate compression','separate spatial index','peak internal temp spool'])
    print(json.dumps(record))


def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,default=ROOT/'working/fixtures/computed7_regions.gpkg')
    p.add_argument('--output',type=Path,required=True);p.add_argument('--rows',type=int,default=10000)
    p.add_argument('--samples',type=int,default=3);p.add_argument('--worker',action='store_true')
    p.add_argument('--route');p.add_argument('--format');p.add_argument('--sample',type=int)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.worker: return worker(args)
    records=[]
    for sample in range(args.samples):
        for fmt in ['arrow','parquet','fgb','geojson','jsonl','gpkg']:
            for route in ['rust','python']:
                result=subprocess.run([sys.executable,__file__,'--worker','--input',str(args.input),
                    '--output',str(args.output),'--rows',str(args.rows),'--route',route,'--format',fmt,
                    '--sample',str(sample)],text=True,capture_output=True,check=True,cwd=ROOT)
                record=json.loads(result.stdout.strip().splitlines()[-1]);records.append(record)
                print(route,fmt,sample,record['adapter_and_export_seconds'],flush=True)
                (args.output/'benchmark.json').write_text(json.dumps(dict(source=str(args.input),
                    source_sha256=hashlib.file_digest(args.input.open('rb'),'sha256').hexdigest(),
                    compression='Parquet Snappy; row group 65536; FGB/GPKG spatial indexes enabled; GDAL JSON decimal precision15, geometry tolerance1e-12',
                    notes='Native release extension. Python GDAL precision/default schema conventions differ; no speedup claim. RSS includes imports and input.',
                    samples=records),indent=2))

if __name__=='__main__': main()
