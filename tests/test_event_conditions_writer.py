from datetime import datetime, timedelta
import hashlib
import h5py
import numpy as np
import pytest
from ras_commander import RasPreprocess


@pytest.fixture
def case(tmp_path):
    geom, plan, flow = [tmp_path / x for x in ('g.hdf', 'p.hdf', 'x.u01')]
    with h5py.File(geom, 'w') as f:
        f.attrs['File Version'] = np.bytes_('HEC-RAS 7.0.1 June 2026')
        f.attrs['Units System'] = np.bytes_('SI Units')
        f.create_dataset('Geometry/2D Flow Areas/Attributes', data=np.array([(b'A',)], dtype=[('Name', 'S16')]))
        mesh = f.require_group('Geometry/2D Flow Areas/A')
        mesh['Faces FacePoint Indexes'] = [[0, 1], [1, 2], [2, 3]]
        mesh['FacePoints Coordinate'] = np.zeros((4, 2))
        bc = f.require_group('Geometry/Boundary Condition Lines')
        bc.create_dataset('Attributes', data=np.array([(b'B', b'A', b'External', 10.)], dtype=[('Name','S16'),('SA-2D','S16'),('Type','S8'),('Length','f4')]))
        bc.create_dataset('External Faces', data=np.array([(0,0,0,1,-2.,2.),(0,1,1,2,2.,8.),(0,2,2,3,8.,12.)], dtype=[('BC Line ID','i4'),('Face Index','i4'),('FP Start Index','i4'),('FP End Index','i4'),('Station Start','f8'),('Station End','f8')]))
    with h5py.File(plan, 'w') as f:
        f.attrs['File Version'] = np.bytes_('HEC-RAS 7.0.1 June 2026')
        f.attrs['Units System'] = np.bytes_('SI Units')
        f['unrelated'] = [42]
    flow.write_text('Boundary Location=,,,,,A,,B\nInterval=1HOUR\nFlow Hydrograph= 3\n       1       2       3\n')
    return geom, plan, flow


def write(case, **kwargs):
    g, p, u = case
    return RasPreprocess.write_event_conditions(p, g, u, start_time=datetime(2000,1,1), end_time=datetime(2000,1,1,2), units='Metric', target_ras_version='7.0.1', **kwargs)


def test_flow_and_backup(case):
    original = case[1].read_bytes()
    write(case)
    assert case[1].with_name('p.hdf.events.bak').read_bytes() == original
    with h5py.File(case[1]) as f:
        ds = f['Event Conditions/Unsteady/Boundary Conditions/Flow Hydrographs/2D: A BCLine: B']
        np.testing.assert_array_equal(ds.attrs['Face Indexes'], [0,1,2])
        np.testing.assert_array_equal(ds.attrs['Face Point Indexes'], [0,1,2,3])
        np.testing.assert_array_equal(ds.attrs['Face Fraction'], [.5,1,.5])
        np.testing.assert_allclose(ds[:,0], [0,1/24,2/24], atol=4e-9, rtol=0)
        np.testing.assert_array_equal(ds[:,1], [1,2,3])
        assert f['unrelated'][0] == 42
        assert 'Completed Successfully' not in f['Event Conditions'].attrs


def test_normal_depth(case):
    case[2].write_text('Boundary Location=,,,,,A,,B\nFriction Slope=0.001\n')
    write(case)
    with h5py.File(case[1]) as f:
        assert f['Event Conditions/Unsteady/Boundary Conditions/Normal Depths/2D: A BCLine: B'][0] == np.float32(.001)


@pytest.mark.parametrize('replacement', ['Stage Hydrograph=3', 'Friction Slope=nan', 'Friction Slope=-1', 'Use DSS=True', 'Interval=0MIN', 'Flow Hydrograph=3\n     nan       2       3', 'Friction Slope=1\nFriction Slope=2', ''])
def test_reject_before_mutation(case, replacement):
    case[2].write_text('Boundary Location=,,,,,A,,B\n'+replacement+'\n')
    original = case[1].read_bytes()
    with pytest.raises(ValueError):
        write(case)
    assert case[1].read_bytes() == original
    assert not case[1].with_name('p.hdf.events.bak').exists()


@pytest.mark.parametrize('field,value', [('BC Line ID',4),('Face Index',99),('FP Start Index',3),('Station End',float('nan'))])
def test_bad_associations(case, field, value):
    with h5py.File(case[0], 'r+') as f:
        ds=f['Geometry/Boundary Condition Lines/External Faces']
        data=ds[:]; data[field][0]=value; ds[:]=data
    original=case[1].read_bytes()
    with pytest.raises(ValueError):
        write(case)
    assert case[1].read_bytes()==original


def test_public_native_fixture_schema():
    # Public Bald Eagle 7.0.1 excerpt: schema observation, not equivalence.
    from pathlib import Path
    with h5py.File(Path(__file__).parent/'fixtures/bc_conflicts/BaldEagleDamBrk.p18.bclines.hdf') as f:
        assert {'Name','SA-2D','Length'} <= set(f['Geometry/Boundary Condition Lines/Attributes'].dtype.names)
        assert '7.0.1' in f.attrs['File Version'].decode()


@pytest.mark.parametrize('which,field,value', [
    (0, 'File Version', 'HEC-RAS 6.6'),
    (1, 'File Version', 'HEC-RAS 7.1'),
    (0, 'Units System', 'US Customary'),
    (1, 'Units System', 'US Customary'),
])
def test_reject_hdf_version_or_units_before_mutation(case, which, field, value):
    with h5py.File(case[which], 'r+') as f:
        f.attrs[field] = np.bytes_(value)
    original = case[1].read_bytes()
    with pytest.raises(ValueError):
        write(case)
    assert case[1].read_bytes() == original
    assert not case[1].with_name('p.hdf.events.bak').exists()


@pytest.mark.parametrize('slope', ['-0.1', 'nan', 'inf'])
def test_reject_invalid_distribution_slope(case, slope):
    with case[2].open('a') as f:
        f.write('Flow Hydrograph Slope=' + slope + '\n')
    original = case[1].read_bytes()
    with pytest.raises(ValueError):
        write(case)
    assert case[1].read_bytes() == original


def test_existing_backup_is_never_replaced(case):
    backup = case[1].with_name('p.hdf.events.bak')
    backup.write_bytes(b'previous retained backup')
    original = case[1].read_bytes()
    with pytest.raises(FileExistsError):
        write(case)
    assert case[1].read_bytes() == original
    assert backup.read_bytes() == b'previous retained backup'
    assert not list(case[1].parent.glob('*.tmp'))


def test_replacement_failure_preserves_original(case, monkeypatch):
    original = case[1].read_bytes()
    def fail(*args):
        raise OSError('injected failure')
    monkeypatch.setattr('os.replace', fail)
    with pytest.raises(OSError, match='injected'):
        write(case)
    assert case[1].read_bytes() == original
    assert case[1].with_name('p.hdf.events.bak').read_bytes() == original
    assert not list(case[1].parent.glob('*.tmp'))


def test_public_native_events_round_trip(tmp_path):
    """Reconstruct supported flow text from three native public BC records."""
    from pathlib import Path
    import shutil
    source = Path(__file__).parent / 'fixtures/bc_conflicts/BaldEagleDamBrk.p18.bclines.hdf'
    target, flow = tmp_path / 'staged.p01.hdf', tmp_path / 'public.u01'
    shutil.copy2(source, target)
    root = 'Event Conditions/Unsteady/Boundary Conditions'
    records = []
    with h5py.File(source) as f:
        for kind, group in f[root].items():
            for ds in group.values():
                area = ds.attrs['2D Flow Area'].decode()
                name = ds.attrs['BC Line'].decode()
                records.append(f'Boundary Location=,,,,,{area},,{name}\n')
                if kind == 'Flow Hydrographs':
                    values = ds[:, 1]
                    records.append(f'Interval=1HOUR\nFlow Hydrograph={len(values)}\n')
                    for offset in range(0, len(values), 10):
                        records.append(''.join(f'{v:8g}' for v in values[offset:offset + 10]) + '\n')
                    records.append('Flow Hydrograph Slope=0.001\n')
                else:
                    records.append('Friction Slope=0.0003\n')
    flow.write_text(''.join(records))
    with h5py.File(target, 'r+') as f:
        del f[root]
    RasPreprocess.write_event_conditions(
        target, source, flow, start_time=datetime(1999, 1, 1, 12),
        end_time=datetime(1999, 1, 2, 12), units='English', target_ras_version='7.0.1',
    )
    with h5py.File(source) as reference, h5py.File(target) as actual:
        for kind, group in reference[root].items():
            for name, expected in group.items():
                output = actual[f'{root}/{kind}/{name}']
                assert set(output.attrs) == set(expected.attrs)
                np.testing.assert_array_equal(output[()], expected[()])
                for key in expected.attrs:
                    if key == 'Face Fraction':
                        np.testing.assert_allclose(output.attrs[key], expected.attrs[key], atol=2e-5, rtol=0)
                    else:
                        np.testing.assert_array_equal(output.attrs[key], expected.attrs[key])
