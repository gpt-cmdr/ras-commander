"""Whole real identity-preserving exports, process/disk monitoring, independent equality.

Four routes: reviewed Python adapter, already-spooled IPC native entry, resident
native RecordBatch iterator, and existing native-backed Python writers.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
FORMATS=['arrow','parquet','fgb','geojson','jsonl','gpkg']
ROUTES=['adapter','ipc','direct','python']


def emit(phase):
    print(json.dumps({'phase':phase}),flush=True)


def load(path):
    import pyarrow as pa
    # Eager prepared input is intentional and included in process RSS/preparation.
    return pa.ipc.open_file(path).read_all()


def verify(output,expected,fmt):
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pyogrio
    from pyproj import CRS
    import shapely
    if fmt=='arrow': actual=pa.ipc.open_file(output).read_all();geom='geometry';crs=None
    elif fmt=='parquet':
        actual=pq.read_table(output);geom='geometry'
        metadata=json.loads(pq.read_metadata(output).metadata[b'geo'])
        crs=CRS.from_json_dict(metadata['columns']['geometry']['crs'])
    else:
        meta,actual=pyogrio.read_arrow(output);geom=meta['geometry_name'] or 'wkb_geometry'
        crs=CRS(meta['crs'])
    assert actual.num_rows==expected.num_rows
    keys=lambda t:list(zip(t['mesh_name'].to_pylist(),map(int,t['cell_id'].to_pylist())))
    original=keys(expected);found=keys(actual)
    assert len(set(original))==len(original),'duplicate expected identities'
    assert len(set(found))==len(found),'duplicate reopened identities'
    assert set(original)==set(found),'missing or altered composite identities'
    positions={key:i for i,key in enumerate(original)}
    order=pa.array([positions[key] for key in found]);expected=expected.take(order)
    # Compare source topology/coordinates for every feature, not just envelope/count.
    g=shapely.from_wkb(actual[geom].to_numpy());wanted=shapely.from_wkb(expected['geometry'].to_numpy())
    assert shapely.equals_exact(g,wanted,1e-12 if fmt in ('geojson','jsonl') else 0).all()
    for name in expected.column_names:
        if name=='geometry':continue
        left=actual[name];right=expected[name]
        if pa.types.is_timestamp(right.type):
            if fmt in ('fgb','geojson','jsonl'):right=right.cast(pa.int64())
            else:left=left.cast(pa.timestamp('ms'))
        # All-null JSON properties may be inferred as untyped null/string by GDAL.
        if right.null_count==right.length():assert left.null_count==left.length();continue
        if pa.types.is_floating(right.type):
            assert np.allclose(left.cast(pa.float64()).to_numpy(),right.to_numpy(),rtol=0,atol=1e-12,equal_nan=True),name
        else:assert left.to_pylist()==right.to_pylist(),name
    target=json.loads(expected.schema.metadata[b'ras:export:v1'])['projjson']
    if crs is not None: assert crs.equals(CRS(target),ignore_axis_order=True)
    return {'verified_rows':expected.num_rows,'composite_ids_unique':True,'geometry_all_equal':True,
        'typed_columns_all_equal':True,'reader':'PyArrow' if fmt in ('arrow','parquet') else 'GDAL/pyogrio',
        'coordinate_tolerance':1e-12 if fmt in ('geojson','jsonl') else 0}


def worker(args):
    import numpy as np
    import pyarrow as pa
    import pyogrio
    import geopandas as gpd
    from pyproj import CRS
    import shapely
    import ras_commander
    from ras_commander import fast_hdf
    import ras_commander_fast_hdf as native
    assert Path.cwd()==ROOT and Path(ras_commander.__file__).resolve().is_relative_to(ROOT)
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert hasattr(native,'validate_export_wkb'),'review patch binding missing'
    geographic=args.format in ('geojson','jsonl')
    input=args.prepared/('geographic.arrow' if geographic else 'native.arrow')
    emit('prepare');start=time.perf_counter();t=load(input)
    evidence=json.loads(t.schema.metadata[b'ras:export:v1']);crs=CRS(evidence['projjson'])
    # Adapter deliberately transforms original native input; equality uses prepared geographic.
    source=load(args.prepared/'native.arrow') if geographic and args.route=='adapter' else t
    source_crs=CRS(json.loads(source.schema.metadata[b'ras:export:v1'])['projjson'])
    frame=None;baseline=t
    if args.route=='python':
        if args.format in ('fgb','geojson','jsonl'):
            for index,field in enumerate(baseline.schema):
                if pa.types.is_timestamp(field.type): baseline=baseline.set_column(index,field.name,baseline.column(index).cast(pa.int64()))
        if args.format=='parquet':
            fields={name:t[name].to_pandas() for name in t.column_names if name!='geometry'}
            frame=gpd.GeoDataFrame(fields,geometry=shapely.from_wkb(t['geometry'].to_numpy()),crs=crs)
    prepare_seconds=time.perf_counter()-start
    emit('writer');start=time.perf_counter();metrics={}
    diagnostics={}
    if args.route=='adapter':
        # Diagnostic wrappers time the real reviewed functions without editing them.
        original_new=pa.ipc.new_file; original_export=native.export_ipc_file
        original_validate=native.validate_export_wkb
        diagnostics={'staged_ipc_bytes':0,'ipc_write_api_seconds':0.,'source_wkb_validation_seconds':0.}
        class TimedWriter:
            def __init__(self,writer):self.writer=writer
            def __enter__(self):self.writer.__enter__();return self
            def write_batch(self,*a,**kw):
                clock=time.perf_counter()
                try:return self.writer.write_batch(*a,**kw)
                finally:diagnostics['ipc_write_api_seconds']+=time.perf_counter()-clock
            def __exit__(self,*a):
                clock=time.perf_counter()
                try:return self.writer.__exit__(*a)
                finally:diagnostics['ipc_write_api_seconds']+=time.perf_counter()-clock
        def timed_new(*a,**kw):
            clock=time.perf_counter();writer=original_new(*a,**kw)
            diagnostics['ipc_write_api_seconds']+=time.perf_counter()-clock
            return TimedWriter(writer)
        def timed_export(input,*a,**kw):
            diagnostics['staged_ipc_bytes']=Path(input).stat().st_size
            diagnostics['pre_native_adapter_seconds']=time.perf_counter()-start
            return original_export(input,*a,**kw)
        def timed_validate(*a,**kw):
            clock=time.perf_counter()
            try:return original_validate(*a,**kw)
            finally:diagnostics['source_wkb_validation_seconds']+=time.perf_counter()-clock
        pa.ipc.new_file=timed_new;native.export_ipc_file=timed_export;native.validate_export_wkb=timed_validate
        try:metrics=fast_hdf.export_arrow(args.output,source,source_crs=source_crs,format=args.format,max_batch_rows=4096)
        finally:pa.ipc.new_file=original_new;native.export_ipc_file=original_export;native.validate_export_wkb=original_validate
    elif args.route=='ipc':
        metrics=json.loads(native.export_ipc_file(input,args.output,args.format,4096))
    elif args.route=='python':
        if args.format=='arrow':
            from tests.rust_first_tier_exports.helpers import write_input
            write_input(t,args.output,batch_size=4096)
        elif args.format=='parquet':frame.to_parquet(args.output,compression='snappy',index=False,row_group_size=65536)
        else:
            options={'SPATIAL_INDEX':'YES'} if args.format in ('fgb','gpkg') else {'COORDINATE_PRECISION':'15'}
            pyogrio.write_arrow(baseline,args.output,layer='features',driver={'fgb':'FlatGeobuf','gpkg':'GPKG','geojson':'GeoJSON','jsonl':'GeoJSONSeq'}[args.format],
                geometry_name='geometry',geometry_type='Unknown',crs=crs.to_wkt(),layer_options=options)
    else:raise ValueError(args.route)
    writer_seconds=time.perf_counter()-start
    import psutil
    writer_memory=psutil.Process().memory_info()
    emit('verify');start=time.perf_counter();equality=verify(args.output,t,args.format)
    print(json.dumps({'prepare_seconds':prepare_seconds,'writer_seconds':writer_seconds,'metrics':metrics,
        'verify_seconds':time.perf_counter()-start,'equality':equality,'output_bytes':args.output.stat().st_size,
        'prepared_ipc_bytes':input.stat().st_size,'adapter_diagnostics':diagnostics,
        'pre_verify_os_peak_rss_bytes':getattr(writer_memory,'peak_wset',writer_memory.rss)}),flush=True)


def disk_bytes(folder):
    total=0;files={}
    for directory,_,names in os.walk(folder):
        for name in names:
            path=Path(directory)/name
            try:size=path.stat().st_size
            except (FileNotFoundError,PermissionError):continue
            total+=size;files[str(path)]=size
    return total,files


def monitor(command,folder,log,timeout=600):
    import psutil
    env=os.environ.copy();env['TEMP']=str(folder/'temp');env['TMP']=str(folder/'temp');env['TMPDIR']=str(folder/'temp')
    (folder/'temp').mkdir(exist_ok=True)
    started=time.perf_counter();proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    state={'phase':'startup','lines':[]};observations=[]
    def reader():
        for line in proc.stdout:
            state['lines'].append(line)
            try:
                item=json.loads(line)
                if 'phase' in item:state['phase']=item['phase']
            except ValueError:pass
    thread=threading.Thread(target=reader,daemon=True);thread.start();process=psutil.Process(proc.pid)
    killed=False
    while proc.poll() is None:
        if time.perf_counter()-started>timeout:
            proc.kill();killed=True;break
        try:
            mem=process.memory_info();rss=mem.rss;peak=getattr(mem,'peak_wset',rss)
            for child in process.children(recursive=True):
                try:childmem=child.memory_info();rss+=childmem.rss;peak+=getattr(childmem,'peak_wset',childmem.rss)
                except psutil.Error:pass
        except psutil.Error:rss=peak=0
        total,files=disk_bytes(folder);temp=sum(size for path,size in files.items() if '/temp/' in path.replace('\\','/'))
        ipc=sum(size for path,size in files.items() if path.endswith('input.arrow'))
        # Adapter IPC is inside a ras-export directory, independent of basename.
        ipc=sum(size for path,size in files.items() if Path(path).name=='input.arrow')
        observations.append({'seconds':time.perf_counter()-started,'phase':state['phase'],'rss':rss,'process_peak':peak,
            'disk_bytes':total,'system_temp_bytes':temp,'adapter_ipc_bytes':ipc})
        time.sleep(.02)
    proc.wait();thread.join(timeout=2);log.write_text(''.join(state['lines']))
    (folder/'monitor.json').write_text(json.dumps(observations))
    records=[]
    for line in state['lines']:
        try: records.append(json.loads(line))
        except ValueError:pass
    result=next((r for r in reversed(records) if 'writer_seconds' in r),{})
    result.update(exit_code=proc.returncode,timed_out=killed,wall_seconds=time.perf_counter()-started,
        peak_process_rss_bytes=max((o['process_peak'] for o in observations),default=0),
        sampled_writer_rss_bytes=max((o['rss'] for o in observations if o['phase']=='writer'),default=0),
        sampled_peak_disk_bytes=max((o['disk_bytes'] for o in observations),default=0),
        sampled_system_temp_bytes=max((o['system_temp_bytes'] for o in observations),default=0),
        sampled_adapter_ipc_bytes=max((o['adapter_ipc_bytes'] for o in observations),default=0),
        monitoring='20ms samples plus OS lifetime peak working set; may miss short-lived temp peaks')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=3);p.add_argument('--formats',nargs='+',default=FORMATS)
    p.add_argument('--routes',nargs='+',default=ROUTES);p.add_argument('--worker',action='store_true');p.add_argument('--format');p.add_argument('--route')
    args=p.parse_args();args.prepared=args.prepared.resolve();args.output=args.output.resolve()
    if args.worker:return worker(args)
    args.output.mkdir(parents=True,exist_ok=False);records=[]
    for sample in range(args.samples):
        for fmt in args.formats:
            for route in args.routes:
                folder=args.output/f'{sample}-{fmt}-{route}';folder.mkdir();out=folder/('output.'+fmt)
                if route=='direct':
                    command=[str(ROOT/'rust/fast-hdf/target/release/whole-export-harness.exe'),str(args.prepared/('geographic.arrow' if fmt in ('geojson','jsonl') else 'native.arrow')),str(out),fmt]
                else:
                    command=[sys.executable,__file__,'--worker','--prepared',str(args.prepared),'--output',str(out),'--format',fmt,'--route',route]
                result=monitor(command,folder,folder/'process.log')
                if route=='direct' and result['exit_code']==0:
                    # Rust harness does not use its own reader as an oracle.
                    try:result['equality']=verify(out,load(args.prepared/('geographic.arrow' if fmt in ('geojson','jsonl') else 'native.arrow')),fmt)
                    except Exception as e:result['verification_error']=repr(e);result['exit_code']=2
                result.update(sample=sample,format=fmt,route=route)
                if out.exists():result['output_sha256']=hashlib.file_digest(out.open('rb'),'sha256').hexdigest()
                records.append(result)
                (args.output/'results.json').write_text(json.dumps({'prepared_receipt':json.loads((args.prepared/'receipt.json').read_text()),
                    'samples':records,'unavailable':['isolated third-party encoding/compression/index times','exact short-lived temp peak'],
                    'direct_path':'resident Vec<RecordBatch> loaded from IPC before writer timer; input transfer still counted separately; not constant-memory'},indent=2))
                print(route,fmt,sample,'exit',result['exit_code'],'seconds',result.get('writer_seconds'),flush=True)


if __name__=='__main__':main()
