import os

import pytest

from ras_commander.geom import GeomReferenceFeatures as Ref


@pytest.fixture
def geom(tmp_path):
    path = tmp_path / 'model.g01'
    path.write_bytes(b'Geom Title=legacy\xff\nIC Point Name=Reference Point Keep\r\n'
                     b'IC Point Position=8,9\r\nReference Point Name=Old   \r\n'
                     b'Reference Point Position=1.00,2.00\r\nUnrelated=keep\nLCMann Table=0\r\nTail')
    return path


def test_replace_and_remove_preserve_unrelated_bytes(geom):
    before = geom.read_bytes()
    backup = Ref.replace_reference_points(geom, [{'name':'New, point','x':3,'y':4}],
                                          expected_existing_names=['Old'])
    assert backup.read_bytes() == before
    assert b'Reference Point Name=New, point' in geom.read_bytes()
    # Public getter is strict UTF-8; the mutation still preserves legacy bytes.
    Ref.replace_reference_points(geom, [], expected_existing_names=['New, point'], create_backup=False)
    assert geom.read_bytes() == before.replace(b'Reference Point Name=Old   \r\nReference Point Position=1.00,2.00\r\n', b'')


@pytest.mark.parametrize('ending', [b'\n', b'\r\n', b'\r'])
def test_add_noop_and_filter(tmp_path, ending):
    path = tmp_path / 'model.g01'
    path.write_bytes(ending.join([b'Geom Title=Example', b'LCMann Table=0', b'']))
    points = [{'name':'First','x':1,'y':2}, {'name':'Second','x':3,'y':4}]
    assert Ref.replace_reference_points(path, points, create_backup=False) is None
    assert Ref.get_reference_points(path) == points
    before = path.read_bytes()
    Ref.replace_reference_points(path, points, create_backup=False)
    assert path.read_bytes() == before
    Ref.replace_reference_points(path, points[1:], expected_existing_names=['First','Second'], create_backup=False)
    assert Ref.get_reference_points(path) == points[1:]
    assert path.read_bytes().endswith(b'LCMann Table=0' + ending)


@pytest.mark.parametrize('points', [[{'name':'x','x':float('nan'),'y':1}],
                                   [{'name':'x','x':1}], [None],
                                   [{'name':'x','x':1,'y':2}]*2,
                                   [{'name':'x\ny','x':1,'y':2}]])
def test_invalid_input_leaves_source_and_no_backup(geom, points):
    before = geom.read_bytes()
    with pytest.raises((ValueError, TypeError)):
        Ref.replace_reference_points(geom, points)
    assert geom.read_bytes() == before
    assert list(geom.parent.iterdir()) == [geom]


def test_guard_before_mutation(geom):
    before = geom.read_bytes()
    with pytest.raises(ValueError, match='population changed'):
        Ref.replace_reference_points(geom, [], expected_existing_names=[])
    assert geom.read_bytes() == before


@pytest.mark.parametrize('records', [b'Reference Point Position=1,2\n',
                                    b'Reference Point Name=x\n',
                                    b'Reference Point Name=x\nReference Point Position=nan,2\n',
                                    b'Reference Point Name=x\nReference Point Position=1,2\n'*2])
def test_malformed_existing_refused(tmp_path, records):
    path = tmp_path / 'model.g01'
    path.write_bytes(records)
    with pytest.raises(ValueError):
        Ref.replace_reference_points(path, [])
    assert path.read_bytes() == records


def test_replace_failure_retains_original_and_backup(geom, monkeypatch):
    before = geom.read_bytes()
    def fail(*args):
        raise OSError('injected replacement failure')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        Ref.replace_reference_points(geom, [])
    assert geom.read_bytes() == before
    assert geom.with_suffix('.g01.bak').read_bytes() == before
    assert not list(geom.parent.glob('*.tmp'))


@pytest.mark.integration
def test_public_bald_eagle_roundtrip(tmp_path):
    import shutil
    from pathlib import Path
    from ras_commander import init_ras_project
    project = os.environ.get('RAS_BC_PUBLIC_EXAMPLE')
    if not project:
        pytest.skip('Set RAS_BC_PUBLIC_EXAMPLE to extracted public Bald Eagle project')
    ras = init_ras_project(project, '7.0.1', load_results_summary=False, hide_intro=True)
    source = Path(ras.geom_df.iloc[0]['hdf_path']).with_suffix('')
    path = tmp_path / 'public.g01'
    shutil.copy2(source, path)
    existing = Ref.get_reference_points(path)
    before = path.read_bytes()
    Ref.replace_reference_points(path, existing, create_backup=False)
    assert path.read_bytes() == before
    Ref.replace_reference_points(path, existing + [{'name':'Replacement regression','x':1.,'y':2.}], create_backup=False)
    assert len(Ref.get_reference_points(path)) == len(existing) + 1
    Ref.replace_reference_points(path, [], expected_existing_names=[p['name'] for p in existing] + ['Replacement regression'])
    assert Ref.get_reference_points(path) == []
