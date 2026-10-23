"""Diagnostic call profile; excluded from performance medians."""
import argparse
import cProfile
import json
from pathlib import Path
import pstats
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))


def main():
    import pyarrow as pa
    from ras_commander.fast_hdf import export_arrow
    import ras_commander_fast_hdf as native
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert hasattr(native,'validate_export_wkb')
    p=argparse.ArgumentParser();p.add_argument('--prepared',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--warm',action='store_true')
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    t=pa.ipc.open_file(args.prepared/'native.arrow').read_all()
    crs=json.loads(t.schema.metadata[b'ras:export:v1'])['projjson']
    if args.warm:
        import pyproj, shapely
    profiler=cProfile.Profile();profiler.enable()
    metrics=export_arrow(args.output/'profile.geojson',t,source_crs=crs,format='geojson',max_batch_rows=4096)
    profiler.disable();profiler.dump_stats(args.output/'adapter.prof')
    with (args.output/'profile.txt').open('w') as stream:
        pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(45)
    (args.output/'metrics.json').write_text(json.dumps(metrics,indent=2))


if __name__=='__main__':main()
