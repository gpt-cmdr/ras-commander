"""Opt-in bounded/full comparison using computed public models; no HEC-RAS run."""
import json
import os
from pathlib import Path
import pytest


def test_native_bounded_maps_equal_independently_masked_full_maps(tmp_path):
    filename=os.environ.get('RAS_COMMANDER_AOI_LATTICE_CASE')
    if not filename:
        pytest.skip('Set RAS_COMMANDER_AOI_LATTICE_CASE to external computed model cases')
    from scripts.benchmarks.fim_aoi_full_crop_compare import run
    result=run(json.loads(Path(filename).read_text(encoding='utf-8')),tmp_path/'compare')
    assert result['status']=='complete'
    assert all(m[k]==0 for r in result['runs'] for m in r['metrics']
        for k in ('extra','missing','different'))
