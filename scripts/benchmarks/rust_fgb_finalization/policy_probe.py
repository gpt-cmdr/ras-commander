"""Read-only strict policy reproduction, no fallback or source edits."""
import argparse
import importlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))


if __name__=='__main__':
    import ras_commander_fast_hdf as native
    from ras_commander.hdf import HdfMesh
    import shapely.ops
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    original=shapely.ops.polygonize
    def forbidden(*args,**kwargs):raise AssertionError('Python fallback occurred')
    shapely.ops.polygonize=forbidden;records=[]
    try:
        for strict in [False,True]:
            started=time.perf_counter()
            try:
                result=HdfMesh.get_mesh_cell_polygons(ROOT/'working/fixtures/JUL2020_D100RAS.p04.hdf',
                    backend='rust',strict=strict,threads=2)
                record={'strict':strict,'rows':len(result),'diagnostics':result.attrs}
            except Exception as e:record={'strict':strict,'error_type':type(e).__name__,'error':str(e)}
            record['seconds']=time.perf_counter()-started;records.append(record)
    finally:shapely.ops.polygonize=original
    a.output.write_text(json.dumps(records,indent=2,default=str));print(json.dumps(records,indent=2,default=str))
