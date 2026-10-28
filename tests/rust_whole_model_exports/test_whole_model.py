"""Real prepared model contracts and adversarial identity audit of combined source."""
import json
import os
from pathlib import Path

import pyarrow as pa
import pytest

from scripts.benchmarks.rust_whole_model_exports.benchmark import ROOT, load, verify

# Qualification requires deliberately generated full-model files and timing logs.
# Keep a normal source checkout independent of ignored benchmark artifacts.
pytestmark = pytest.mark.skipif(
    os.environ.get("RAS_RUN_WHOLE_MODEL_EXPORT_TESTS") != "1",
    reason="opt in after preparing models and benchmark evidence (see README)",
)


@pytest.mark.parametrize('case,rows,omitted',[('cells7',4425,0),('cells6',18066,0),('regions7',72,0),('cells5',1872746,0)])
def test_complete_prepared_models(case,rows,omitted):
    path=ROOT/'working/prepared'/case
    assert (path/'receipt.json').exists(),'prepare the complete immutable model first'
    receipt=json.loads((path/'receipt.json').read_text())
    assert receipt['rows']==rows and receipt['omitted_source_cells']==omitted
    t=load(path/'native.arrow');assert t.num_rows==rows
    keys=list(zip(t['mesh_name'].to_pylist(),t['cell_id'].to_pylist()))
    assert len(set(keys))==rows
    assert load(path/'geographic.arrow').num_rows==rows
    if case=='cells7':assert len(set(t['cell_id'].to_pylist()))<rows
    if case=='cells6':assert not receipt['summary_available'] and t['max_wse'].null_count==rows
    if case=='cells5':assert not [d for d in receipt['diagnostics'] if d.get('status')=='omitted']


def test_reviewed_native_imports():
    import ras_commander
    import ras_commander_fast_hdf as native
    assert Path.cwd()==ROOT
    assert Path(ras_commander.__file__).resolve().is_relative_to(ROOT)
    assert Path(native.__file__).resolve().is_relative_to(ROOT/'.venv')
    assert hasattr(native,'validate_export_wkb')


def test_cross_batch_duplicate_identity_is_not_globally_enforced(tmp_path):
    from ras_commander.fast_hdf import export_arrow
    source=load(ROOT/'working/prepared/cells7/native.arrow').slice(0,1)
    duplicate=pa.concat_tables([source,source])
    out=tmp_path/'duplicate.arrow'
    source_crs=json.loads(source.schema.metadata[b'ras:export:v1'])['projjson']
    metrics=export_arrow(out,duplicate,source_crs=source_crs,format='arrow',max_batch_rows=1)
    assert metrics['rows']==2
    # Explicit audit finding, not a claim that the writer enforces global keys.
    with pytest.raises(AssertionError,match='duplicate expected identities'):
        verify(out,duplicate,'arrow')


@pytest.mark.parametrize('case,expected',[('cells7',72),('cells6',72),('regions7',72),('cells5',24)])
def test_all_measured_samples_verified(case,expected):
    path=ROOT/'working/qualification'/case/'results.json'
    assert path.exists(),'run the whole-model benchmark first'
    results=json.loads(path.read_text())['samples']
    assert len(results)==expected
    for r in results:
        assert r['exit_code']==0 and not r['timed_out']
        assert r['equality']['geometry_all_equal'] and r['equality']['typed_columns_all_equal']
        assert r['equality']['composite_ids_unique']
        assert r['sampled_peak_disk_bytes']>=0 and r['peak_process_rss_bytes']>0
        # A child may finish output before the next20ms sample; zero is an
        # unavailable transient peak, never evidence of zero temporary disk.
        assert r.get('output_bytes',r.get('metrics',{}).get('output_bytes',0))>0


@pytest.mark.parametrize('case,rows',[('cells7',4425),('cells6',18066)])
def test_complete_required_native_extraction(case,rows):
    results=json.loads((ROOT/'working/extraction'/case/'results.json').read_text())
    assert len(results)==6
    for result in results:
        assert result['exit_code']==0 and result['rows']==rows
        assert result['normalized_coordinate_equal_rows']==rows
        assert result['quarantined_cells']==0
        if result['backend']=='rust':assert result['native_calls']>0 and result['native_required']


def test_large_required_native_extraction():
    # The 5.0.7 case (public FEMA eBFE AustinOyster.p03) has no invalid source cells;
    # one labelled sample per backend.
    results=json.loads((ROOT/'working/extraction/cells5/results.json').read_text())
    assert {r['backend'] for r in results}=={'rust','python'}
    for result in results:
        assert result['exit_code']==0 and result['rows']==1872746
        assert result['normalized_coordinate_equal_rows']==1872746
        assert result['quarantined_cells']==0
        if result['backend']=='rust':assert result['native_calls']>0 and result['native_required']
