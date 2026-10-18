"""Distinct required-native versus reference full HDF polygon construction stage."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


def worker(args):
    import numpy as np
    import pyarrow as pa
    import shapely
    import shapely.ops
    import ras_commander
    import ras_commander_fast_hdf as native
    from ras_commander.hdf import HdfBase,HdfMesh
    from tests.rust_first_tier_exports.helpers import table,write_input
    assert Path.cwd()==ROOT and Path(ras_commander.__file__).resolve().is_relative_to(ROOT)
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    before=hashlib.file_digest(args.fixture.open('rb'),'sha256').hexdigest()
    calls=[0];original=native.assemble_cells;polygonize=shapely.ops.polygonize
    def counted(*a,**kw):calls[0]+=1;return original(*a,**kw)
    def forbidden(*a,**kw):raise AssertionError('Python polygonizer used in required Rust extraction')
    if args.backend=='rust':native.assemble_cells=counted;shapely.ops.polygonize=forbidden
    print(json.dumps({'phase':'writer'}),flush=True);started=time.perf_counter()
    try:
        frame=HdfMesh.get_mesh_cell_polygons(args.fixture,backend=args.backend,threads=2 if args.backend=='rust' else None)
        elapsed=time.perf_counter()-started
    except Exception as e:
        print(json.dumps({'extraction_seconds':time.perf_counter()-started,'error_type':type(e).__name__,
            'error':str(e),'native_calls':calls[0],'required_native':args.backend=='rust'}),flush=True)
        raise
    finally:native.assemble_cells=original;shapely.ops.polygonize=polygonize
    import psutil
    memory=psutil.Process().memory_info()
    print(json.dumps({'phase':'verify'}),flush=True)
    if args.backend=='rust':assert calls[0]>0,'no native assembly calls'
    physical=sum(int(n) for _,n in HdfBase.get_2d_flow_area_names_and_counts(args.fixture))
    diagnostics=[d for d in frame.attrs.get('cell_polygon_diagnostics',()) if d.get('status') in ('omitted','ambiguous','not_present','read_error')]
    t=table(frame.geometry.to_numpy(),frame.crs,mesh_names=frame.mesh_name.to_numpy(),cell_ids=frame.cell_id.to_numpy())
    # The immutable Python-produced complete model is an independent saved oracle.
    expected=pa.ipc.open_file(args.prepared/'native.arrow').read_all()
    keys=lambda x:list(zip(x['mesh_name'].to_pylist(),x['cell_id'].to_pylist()))
    actual_keys=keys(t);expected_keys=keys(expected)
    assert len(set(actual_keys))==len(actual_keys) and set(actual_keys)==set(expected_keys)
    index={k:i for i,k in enumerate(expected_keys)};expected=expected.take(pa.array([index[k] for k in actual_keys]))
    actual=shapely.from_wkb(t['geometry'].to_numpy());wanted=shapely.from_wkb(expected['geometry'].to_numpy())
    equal=shapely.equals(actual,wanted);assert equal.all(),int((~equal).sum())
    exact=shapely.equals_exact(shapely.normalize(actual),shapely.normalize(wanted),0)
    assert hashlib.file_digest(args.fixture.open('rb'),'sha256').hexdigest()==before
    write_input(t,args.output,batch_size=4096)
    print(json.dumps({'writer_seconds':elapsed,'extraction_seconds':elapsed,'rows':len(frame),'physical_cells':physical,
        'quarantined_cells':physical-len(frame),'diagnostics':diagnostics,'native_calls':calls[0],
        'native_required':args.backend=='rust','topologically_equal_rows':int(equal.sum()),
        'normalized_coordinate_equal_rows':int(exact.sum()),'pre_verify_os_peak_rss_bytes':getattr(memory,'peak_wset',memory.rss),
        'fixture_sha256':before,'equality':{'geometry_all_equal':True,'composite_ids_unique':True}}),flush=True)


def main():
    from scripts.benchmarks.rust_whole_model_exports.benchmark import monitor
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True);p.add_argument('--prepared',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--samples',type=int,default=3)
    p.add_argument('--worker',action='store_true');p.add_argument('--backend');args=p.parse_args()
    args.fixture=args.fixture.resolve();args.prepared=args.prepared.resolve();args.output=args.output.resolve()
    if args.worker:return worker(args)
    args.output.mkdir(parents=True,exist_ok=False);records=[]
    for sample in range(args.samples):
        for backend in ['rust','python']:
            folder=args.output/f'{sample}-{backend}';folder.mkdir()
            cmd=[sys.executable,__file__,'--worker','--fixture',str(args.fixture),'--prepared',str(args.prepared),
                '--output',str(folder/'extracted.arrow'),'--backend',backend]
            result=monitor(cmd,folder,folder/'process.log');result.update(backend=backend,sample=sample)
            if result['exit_code']:
                for line in (folder/'process.log').read_text().splitlines():
                    try:detail=json.loads(line)
                    except ValueError:continue
                    if 'error_type' in detail:result.update(detail)
            records.append(result);(args.output/'results.json').write_text(json.dumps(records,indent=2))
            print(backend,sample,result['exit_code'],result.get('extraction_seconds'),flush=True)


if __name__=='__main__':main()
