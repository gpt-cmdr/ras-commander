"""Interleaved prior-release/candidate FGB, identical prepared whole-model batches."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from scripts.benchmarks.rust_whole_model_exports.benchmark import load,monitor,verify


def check_bbox(output,expected):
    import pyogrio
    import shapely
    geometry=shapely.from_wkb(expected['geometry'].to_numpy())
    point=geometry[0].representative_point();bounds=geometry[0].bounds
    epsilon=min(bounds[2]-bounds[0],bounds[3]-bounds[1])*1e-6
    box=shapely.box(point.x-epsilon,point.y-epsilon,point.x+epsilon,point.y+epsilon)
    assert geometry[0].contains(box)
    _,found=pyogrio.read_arrow(output,bbox=box.bounds)
    mask=shapely.intersects(geometry,box)
    keys=lambda t:set(zip(t['mesh_name'].to_pylist(),t['cell_id'].to_pylist()))
    assert keys(found)==keys(expected.filter(mask)), 'indexed bbox mismatch'
    return {'bbox':list(box.bounds),'features':found.num_rows,'independently_verified':True}


def worker(args):
    if args.variant=='baseline':sys.path.insert(0,str(ROOT/'working/fgb-finalization/baseline'))
    import ras_commander_fast_hdf as native
    binary=importlib.import_module(native.export_ipc_file.__module__)
    expected_root=ROOT/'working/fgb-finalization/baseline' if args.variant=='baseline' else ROOT/'.venv'
    assert Path(binary.__file__).resolve().is_relative_to(expected_root)
    assert hasattr(native,'validate_export_wkb')
    emit=lambda p:print(json.dumps({'phase':p}),flush=True)
    emit('prepare');expected=load(args.prepared/'native.arrow')
    emit('writer');start=time.perf_counter()
    metrics=json.loads(native.export_ipc_file(args.prepared/'native.arrow',args.output,'fgb',4096))
    elapsed=time.perf_counter()-start
    import psutil
    memory=psutil.Process().memory_info()
    emit('verify');equality=verify(args.output,expected,'fgb');bbox=check_bbox(args.output,expected)
    print(json.dumps({'writer_seconds':elapsed,'metrics':metrics,'equality':equality,'bbox':bbox,
        'output_bytes':args.output.stat().st_size,'pre_verify_os_peak_rss_bytes':getattr(memory,'peak_wset',memory.rss),
        'binary':binary.__file__,'binary_sha256':hashlib.file_digest(Path(binary.__file__).open('rb'),'sha256').hexdigest()}),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--samples',type=int,default=3);p.add_argument('--worker',action='store_true');p.add_argument('--variant')
    args=p.parse_args();args.prepared=args.prepared.resolve();args.output=args.output.resolve()
    if args.worker:return worker(args)
    args.output.mkdir(parents=True,exist_ok=False);records=[]
    for sample in range(args.samples):
        # Alternate which build runs first, while remaining sequential.
        for variant in (['baseline','candidate'] if sample%2==0 else ['candidate','baseline']):
            folder=args.output/f'{sample}-{variant}';folder.mkdir();out=folder/'output.fgb'
            cmd=[sys.executable,__file__,'--worker','--prepared',str(args.prepared),'--output',str(out),'--variant',variant]
            result=monitor(cmd,folder,folder/'process.log');result.update(sample=sample,variant=variant)
            if out.exists():result['output_sha256']=hashlib.file_digest(out.open('rb'),'sha256').hexdigest()
            records.append(result);(args.output/'results.json').write_text(json.dumps(records,indent=2))
            print(variant,sample,'exit',result['exit_code'],result.get('writer_seconds'),flush=True)


if __name__=='__main__':main()
