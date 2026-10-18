"""Separate integrator binding/adapter proposal qualification."""
import json
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pyogrio
import pytest
from pyproj import CRS
from shapely.geometry import Point
import shapely

from .helpers import ROOT, table


def test_native_provenance():
    native=pytest.importorskip('ras_commander_fast_hdf')
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert hasattr(native,'export_ipc_file')


@pytest.mark.parametrize('fmt',['arrow','parquet','fgb','gpkg','geojson','jsonl'])
def test_thin_adapter(tmp_path,fmt):
    pytest.importorskip('ras_commander_fast_hdf')
    from ras_commander.fast_hdf import export_arrow
    source=table([Point(1000000,2000000),Point(1000001,2000001)],2277,
        columns={'time_ms':pa.array([32503680000123,None],type=pa.timestamp('ms'))})
    out=tmp_path/('native.'+fmt)
    metrics=export_arrow(out,source,source_crs=2277,format=fmt,max_batch_rows=1)
    assert metrics['batches']==2 and metrics['rows']==2
    if fmt=='arrow': assert pa.ipc.open_file(out).read_all()['geometry'].equals(source['geometry'])
    elif fmt=='parquet': assert pq.read_table(out)['geometry'].equals(source['geometry'])
    else:
        meta,actual=pyogrio.read_arrow(out)
        expected=table([Point(1000000,2000000),Point(1000001,2000001)],2277,target_geojson=fmt in ('geojson','jsonl'))
        actual=actual.take(pa.array(np.argsort(actual['cell_id'].to_numpy())))
        assert shapely.equals_exact(shapely.from_wkb(actual[meta['geometry_name'] or 'wkb_geometry'].to_numpy()),
            shapely.from_wkb(expected['geometry'].to_numpy()),1e-12).all()


def test_thin_adapter_missing_conflicting_crs_and_cleanup(tmp_path):
    pytest.importorskip('ras_commander_fast_hdf')
    from ras_commander.fast_hdf import export_arrow
    t=table([Point(1,2)],4326)
    for crs in [None,3857]:
        with pytest.raises(ValueError): export_arrow(tmp_path/'out',t,source_crs=crs,format='arrow')
    assert not list(tmp_path.iterdir())


def test_reader_batch_limit_and_geometry_dimension(tmp_path):
    pytest.importorskip('ras_commander_fast_hdf')
    from ras_commander.fast_hdf import export_arrow
    t=table([Point(1,2),Point(2,3)],4326)
    reader=pa.RecordBatchReader.from_batches(t.schema,t.to_batches())
    with pytest.raises(ValueError,match='max_batch_rows'):
        export_arrow(tmp_path/'out',reader,source_crs=4326,format='arrow',max_batch_rows=1)
    assert not list(tmp_path.iterdir())
