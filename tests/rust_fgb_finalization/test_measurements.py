import json
import os
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get('RAS_RUN_FGB_MEASUREMENTS') != '1',
    reason='opt in after generating baseline/candidate release measurement artifacts',
)


@pytest.mark.parametrize('case,rows',[('cells7',4425),('cells6',18066),('cells5',340246)])
def test_full_model_release_equality_and_build_identity(case,rows):
    records=json.loads((ROOT/'working/fgb-finalization/measurements'/case/'results.json').read_text())
    assert len(records)==6
    binaries={variant:{r['binary_sha256'] for r in records if r['variant']==variant} for variant in ['baseline','candidate']}
    assert all(len(hashes)==1 for hashes in binaries.values())
    assert binaries['baseline']!=binaries['candidate']
    for r in records:
        assert r['exit_code']==0 and r['equality']['verified_rows']==rows
        assert r['equality']['geometry_all_equal'] and r['equality']['typed_columns_all_equal']
        assert r['bbox']['independently_verified'] and r['bbox']['features']>0
    # Buffering must not alter any bytes, schema, feature sorting or index.
    assert len({r['output_sha256'] for r in records})==1
