"""Generate synthetic structure-result fixtures; run as: python -I make_fixtures.py OUTDIR
Needs h5py/numpy only (not needed at Rust test runtime). Writes *.h5 and manifest.json with
SHA256 and hand-written expectations (never produced by the Rust code). Layout mirrors what
real HEC-RAS 6.x files were observed to contain (see oracle_real_structures.py): family groups
below Unsteady Time Series, per-structure groups with Node Pointer, Variable_Unit tables,
Geometry/Structures/Attributes and Geometry/Storage Areas/Attributes identity tables."""
import hashlib, json, sys
from pathlib import Path
import h5py, numpy as np

BASE = 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'
T = 4
LATERALS = [('R1', 'Reach1', '100'), ('R1', 'Reach1', '200')]


def s(values, width):
    return np.array([v.encode() for v in values], dtype='S%d' % width)


def text_attr(obj, name, raw):
    dt = h5py.string_dtype('ascii', len(raw))
    obj.attrs.create(name, np.array(raw, dtype=dt), dtype=dt)


def var_unit(ds, pairs, width=16):
    ds.attrs.create('Variable_Unit', np.array([[a.encode(), b.encode()] for a, b in pairs],
                                              dtype='S%d' % width))


def data(seed, cols):
    return (np.arange(T * cols, dtype='<f4').reshape(T, cols) + np.float32(seed)).astype('<f4')


def time_axis(f):
    g = f.require_group(BASE)
    g.create_dataset('Time', data=np.arange(T, dtype='<f8') / 24.0)
    g.create_dataset('Time Date Stamp', data=s(['01JAN2020 %02d:00:00' % h for h in range(T)], 19))


def geometry_structures(f, laterals, connections):
    rows = [('Lateral', r, rc, rs, '', '', '') for r, rc, rs in laterals]
    rows += [('Connection', '', '', '', c, us, ds) for c, us, ds in connections]
    dt = np.dtype([('Type', 'S16'), ('River', 'S16'), ('Reach', 'S16'), ('RS', 'S8'),
                   ('Connection', 'S16'), ('US SA/2D', 'S16'), ('DS SA/2D', 'S16')])
    arr = np.array([tuple(x.encode() for x in r) for r in rows], dtype=dt)
    f.create_dataset('Geometry/Structures/Attributes', data=arr)


def geometry_storage(f, names):
    dt = np.dtype([('Name', 'S16'), ('Mode', 'S18')])
    f.create_dataset('Geometry/Storage Areas/Attributes',
                     data=np.array([(n.encode(), b'Elevation Volume') for n in names], dtype=dt))


def structure_group(fam, name, pointer, seed):
    g = fam.create_group(name)
    g.attrs['Node Pointer'] = np.int32(pointer)
    sv = g.create_dataset('Structure Variables', data=data(seed, 2))
    var_unit(sv, [('Total Flow', 'cfs'), ('Stage HW', 'ft')])
    g.create_dataset('Weir Variables', data=data(seed + 100, 3))
    g.create_dataset('Geometric Info/Face Points', data=np.arange(5, dtype='<i4'))
    flow = g.create_dataset('HW TW Segments/Flow', data=data(seed + 200, 3))
    text_attr(flow, 'Units', b'cfs')
    g.create_dataset('HW TW Segments/HW TW Station', data=np.arange(3, dtype='<f4'))
    return g


def lateral_family(f, opts):
    fam = f.require_group(BASE + '/Lateral Structures')
    names = [' '.join(x) for x in LATERALS]
    if opts.get('duplicate_names'):
        names = [names[0], names[0] + ' ']
    for i, n in enumerate(names):
        pointer = 7 if opts.get('duplicate_pointer') else 10 + i
        structure_group(fam, n, pointer, 10 * (i + 1))
    if opts.get('stray_dataset'):
        fam.create_dataset('stray', data=np.zeros((T, 1), dtype='<f4'))
    if opts.get('short_series'):
        del fam[names[1]]['Weir Variables']
        fam[names[1]].create_dataset('Weir Variables', data=np.zeros((T - 1, 3), dtype='<f4'))
    if opts.get('label_mismatch'):
        sv = fam[names[0]]['Structure Variables']
        del sv.attrs['Variable_Unit']
        var_unit(sv, [('A', 'x'), ('B', 'y'), ('C', 'z')])
    if opts.get('unmatched_lateral'):
        fam.move(names[1], 'R1 Reach1 999')
    if opts.get('both_labels'):
        fam[names[0]]['Structure Variables'].attrs.create('Connections', np.array([b'a', b'b'], dtype='S8'))
    if opts.get('int_series'):
        fam[names[0]].create_dataset('Counts', data=np.zeros((T, 2), dtype='<i4'))


def sa2d_family(f, opts):
    fam = f.require_group(BASE + '/SA 2D Area Conn')
    structure_group(fam, 'A Conn1', 20, 1)
    structure_group(fam, 'Dam', 21, 2)
    if opts.get('sa_unmatched'):
        fam.move('Dam', 'Weirdly Named')


def storage_family(f, opts):
    fam = f.require_group(BASE + '/Storage Areas')
    for i, n in enumerate(['Pool1', 'Pool2']):
        g = fam.create_group(n)
        var_unit(g.create_dataset('Storage Area Variables', data=data(30 + i, 2)),
                 [('Stage', 'ft'), ('Net Inflow', 'cfs')])
        c = g.create_dataset('Connections to Storage Area', data=data(40 + i, 2))
        c.attrs.create('Connections', np.array([b'Precip', b' LSDam'], dtype='S64'))
    flow = fam.create_dataset('Flow', data=data(50, 2))
    text_attr(flow, 'Flow', b'cfs')
    ws = fam.create_dataset('Water Surface', data=data(60, 2))
    text_attr(ws, 'Stage', b'ft')


def build(path, opts):
    with h5py.File(path, 'w', libver='earliest') as f:
        if not opts.get('no_time'):
            time_axis(f)
        else:
            f.require_group(BASE)
        if not opts.get('no_geometry_table'):
            laterals = list(LATERALS)
            if opts.get('count_mismatch'):
                laterals.append(('R1', 'Reach1', '300'))
            if opts.get('duplicate_geometry'):
                laterals[1] = laterals[0]
            geometry_structures(f, laterals, [('Conn1', 'A', 'B'), ('Dam', 'Pool1', 'A')])
        geometry_storage(f, ['Pool1', 'PoolX' if opts.get('unmatched_storage') else 'Pool2'])
        lateral_family(f, opts)
        sa2d_family(f, opts)
        if opts.get('dataset_as_family'):
            f.create_dataset(BASE + '/Storage Areas', data=np.zeros((T, 2), dtype='<f4'))
        else:
            storage_family(f, opts)
        if opts.get('inline'):
            f.require_group(BASE + '/Inline Structures/X')


# name -> (options, expected status per family, expected aggregate status)
CASES = {
    'good': ({}, ('Supported', 'Supported', 'Supported'), 'Supported'),
    'missing_attribute_table': ({'no_geometry_table': True},
                                ('Unsupported:IdentityLayout', 'Unsupported:IdentityLayout', 'Supported'),
                                'Unsupported:IdentityLayout'),
    'count_mismatch': ({'count_mismatch': True}, ('Supported', 'Corrupt', 'Supported'), 'Corrupt'),
    'wrong_object_type': ({'stray_dataset': True}, ('Supported', 'Corrupt', 'Supported'), 'Corrupt'),
    'duplicate_names': ({'duplicate_names': True}, ('Supported', 'Corrupt', 'Supported'), 'Corrupt'),
    'duplicate_geometry_identity': ({'duplicate_geometry': True},
                                    ('Supported', 'Unsupported:IdentityLayout', 'Supported'),
                                    'Unsupported:IdentityLayout'),
    'unmatched_lateral_group': ({'unmatched_lateral': True},
                                ('Supported', 'Unsupported:IdentityLayout', 'Supported'),
                                'Unsupported:IdentityLayout'),
    'unmatched_storage_name': ({'unmatched_storage': True},
                               ('Supported', 'Supported', 'Unsupported:IdentityLayout'),
                               'Unsupported:IdentityLayout'),
    'both_label_attributes': ({'both_labels': True}, ('Supported', 'Supported', 'Supported'), 'Supported'),
    'duplicate_node_pointer': ({'duplicate_pointer': True}, ('Supported', 'Corrupt', 'Supported'), 'Corrupt'),
    'row_count_vs_time_axis': ({'short_series': True}, ('Supported', 'Corrupt', 'Supported'), 'Corrupt'),
    'missing_time_axis': ({'no_time': True}, ('Corrupt', 'Corrupt', 'Corrupt'), 'Corrupt'),
    'label_count_mismatch': ({'label_mismatch': True}, ('Supported', 'Supported', 'Supported'), 'Supported'),
    'unmatched_connection': ({'sa_unmatched': True},
                             ('Unsupported:IdentityLayout', 'Supported', 'Supported'),
                             'Unsupported:IdentityLayout'),
    'unqualified_inline_group': ({'inline': True}, ('Supported', 'Supported', 'Supported'),
                                 'Unsupported:Schema'),
    'storage_is_dataset': ({'dataset_as_family': True}, ('Supported', 'Supported', 'Corrupt'), 'Corrupt'),
    'integer_series': ({'int_series': True}, ('Supported', 'Supported', 'Supported'), 'Supported'),
}


def frozen_read():
    a = data(20, 2)[1:4:2, 0:2:1]
    return {'rows': [1, 4, 2], 'cols': [0, 2, 1], 'shape': list(a.shape),
            'bits': [int(x) for x in a.reshape(-1).view('<u4')]}


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    manifest = {'generator': 'make_fixtures.py', 'time_rows': T, 'laterals': [' '.join(x) for x in LATERALS],
                'frozen_read': dict(frozen_read(), structure='R1 Reach1 200',
                                    relative='Structure Variables'),
                'fixtures': {}}
    for name, (opts, per, agg) in CASES.items():
        path = out / (name + '.h5')
        build(path, opts)
        manifest['fixtures'][name] = {
            'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'expect': {'sa2d': per[0], 'lateral': per[1], 'storage': per[2], 'aggregate': agg}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True))


main()
