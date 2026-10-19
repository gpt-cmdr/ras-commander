"""Independent h5py oracle for real structure result families.
Usage:  python -I oracle_real_structures.py FIXTURE_DIR OUT.json [name-substring ...]
Defaults select the BaldEagleDamBrk p07/p18 and JUL2020_D100RAS p04 result HDF files. Never
modifies inputs. The Rust test (tests/structures_conformance.rs, ignored) reads OUT.json via
RAS_STRUCT_ORACLE with RAS_NATIVE_FIXTURES. Floats are frozen as IEEE bit patterns plus
SHA256 of the little-endian bytes of each selected slice; no decimal float is trusted.
Nothing is assumed about layout: every attribute of every visited object is recorded as
(name, dtype, shape, raw bytes hex) exactly as h5py sees it."""
import hashlib, json, sys
from pathlib import Path
import h5py, numpy as np

BASE = 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'
FAMILIES = ['SA 2D Area Conn', 'Lateral Structures', 'Storage Areas']
UNQUALIFIED = ['Structures', 'Inline Structures', 'Bridges', 'Culverts', 'Bridges/Culverts']
DEFAULT = ['BaldEagleDamBrk.p07', 'BaldEagleDamBrk.p18', 'JUL2020_D100RAS.p04']


def raw_attr(obj, name):
    """Stored bytes exactly as HDF5 holds them (space/NUL padding preserved) via the
    low-level attribute API; high-level h5py strips string padding."""
    aid = h5py.h5a.open(obj.id, name.encode())
    buf = np.empty(aid.shape, dtype=aid.dtype)
    aid.read(buf)
    return buf


def attr_record(obj):
    out = {}
    for k in sorted(obj.attrs.keys()):
        a = raw_attr(obj, k)
        out[k] = {'dtype': str(a.dtype), 'shape': list(a.shape), 'itemsize': a.dtype.itemsize,
                  'strpad': strpad(obj, k), 'hex': a.tobytes().hex()}
    return out


def strpad(obj, name):
    """H5T string padding of the stored attribute type (0 NULLTERM, 1 NULLPAD, 2 SPACEPAD);
    None for non-string types. h5py normalizes padding on read, so raw padding bytes are only
    comparable after trimming trailing NUL/space per element."""
    t = h5py.h5a.open(obj.id, name.encode()).get_type()
    return t.get_strpad() if t.get_class() == h5py.h5t.STRING else None


def text(b):
    return b.decode('latin1') if isinstance(b, (bytes, np.bytes_)) else str(b)


def labels_of(ds):
    """Independent column-label expectation from Variable_Unit / Connections."""
    vu, cn = 'Variable_Unit' in ds.attrs, 'Connections' in ds.attrs
    if vu and cn:
        return {'state': 'corrupt'}
    if vu:
        a = raw_attr(ds, 'Variable_Unit')
        if a.shape == (ds.shape[1], 2) and a.dtype.kind == 'S':
            return {'state': 'declared', 'source': 'VariableUnit',
                    'names': [text(x) for x in a[:, 0]], 'units': [text(x) for x in a[:, 1]],
                    'itemsize': a.dtype.itemsize, 'strpad': strpad(ds, 'Variable_Unit'),
                    'hex': a.tobytes().hex()}
        return {'state': 'mismatch', 'shape': list(a.shape)}
    if cn:
        a = raw_attr(ds, 'Connections')
        if a.shape == (ds.shape[1],) and a.dtype.kind == 'S':
            return {'state': 'declared', 'source': 'Connections',
                    'names': [text(x) for x in a], 'units': None, 'itemsize': a.dtype.itemsize,
                    'strpad': strpad(ds, 'Connections'), 'hex': a.tobytes().hex()}
        return {'state': 'mismatch', 'shape': list(a.shape)}
    return {'state': 'absent'}


def units_attr(ds):
    if 'Units' not in ds.attrs:
        return None
    a = raw_attr(ds, 'Units')
    return {'text': text(a.reshape(-1)[0]) if a.size == 1 else None, 'itemsize': a.dtype.itemsize,
            'strpad': strpad(ds, 'Units'), 'hex': a.tobytes().hex()}


def bits(a):
    flat = a.reshape(-1)[:8]
    return [int(x) for x in flat.view('<u%d' % a.dtype.itemsize)]


def selection(ds, T):
    n = ds.shape[1]
    rows = (1 if T > 1 else 0, T, 7)
    cols = (0, n, max(1, n // 5))
    a = np.asarray(ds[rows[0]:rows[1]:rows[2], cols[0]:cols[1]:cols[2]])
    le = np.ascontiguousarray(a.astype(a.dtype.newbyteorder('<'), copy=False))
    return {'rows': list(rows), 'cols': list(cols), 'shape': list(a.shape), 'dtype': str(a.dtype),
            'sha256_le': hashlib.sha256(le.tobytes()).hexdigest(), 'first_bits': bits(le)}


def walk(group, rel, series, statics):
    for name in sorted(group.keys()):
        o = group[name]
        r = name if not rel else rel + '/' + name
        if isinstance(o, h5py.Dataset):
            if o.ndim == 1:
                statics.append(r)
            else:
                series.append((r, o))
        elif not (rel == '' and name == 'Geometric Info'):
            walk(o, r, series, statics)


def series_record(r, ds, T, with_sel):
    rec = {'relative': r, 'shape': list(ds.shape), 'dtype': str(ds.dtype),
           'rank': ds.ndim, 'rows_match_time': bool(ds.shape[0] == T),
           'attrs': attr_record(ds), 'labels': labels_of(ds) if ds.ndim == 2 else None,
           'units_attr': units_attr(ds)}
    if with_sel and ds.ndim == 2 and ds.dtype.kind == 'f':
        rec['selection'] = selection(ds, T)
    return rec


def geometry_expect(f, fam, names):
    if fam == 'Storage Areas':
        t = f['Geometry/Storage Areas/Attributes'][()]
        rows = {text(n).strip(): i for i, n in enumerate(t['Name'])}
        ids = {}
        for g in names:
            i = rows.get(g.strip())
            ids[g] = None if i is None else {'row': i, 'name': text(t['Name'][i])}
        return {'table_rows': len(t), 'ids': ids}
    t = f['Geometry/Structures/Attributes'][()]
    typ = [text(x).strip() for x in t['Type']]
    if fam == 'Lateral Structures':
        sel = [i for i, x in enumerate(typ) if x == 'Lateral']
        key = {}
        for i in sel:
            k = ' '.join([text(t['River'][i]).strip(), text(t['Reach'][i]).strip(), text(t['RS'][i]).strip()])
            key[k] = i
        ids = {}
        for g in names:
            i = key.get(g)
            ids[g] = None if i is None else {'row': i, 'river': text(t['River'][i]),
                                             'reach': text(t['Reach'][i]), 'station': text(t['RS'][i])}
        return {'table_rows': len(sel), 'ids': ids}
    sel = [i for i, x in enumerate(typ) if x == 'Connection']
    ids = {}
    for g in names:
        hits = []
        for i in sel:
            c = text(t['Connection'][i]).strip()
            us, ds = text(t['US SA/2D'][i]).strip(), text(t['DS SA/2D'][i]).strip()
            if g == c or g == us + ' ' + c or g == ds + ' ' + c:
                hits.append(i)
        ids[g] = {'rows': hits}
        if len(hits) == 1:
            i = hits[0]
            ids[g].update({'connection': text(t['Connection'][i]),
                           'upstream': text(t['US SA/2D'][i]), 'downstream': text(t['DS SA/2D'][i])})
    return {'table_rows': len(sel), 'ids': ids}


def family_record(f, fam):
    base = f[BASE]
    T = base['Time'].shape[0]
    if fam not in base:
        return {'present': False}
    g = base[fam]
    names = sorted(k for k, v in g.items() if isinstance(v, h5py.Group))
    fam_ds = sorted(k for k, v in g.items() if isinstance(v, h5py.Dataset))
    rec = {'present': True, 'time_rows': T, 'group_names': names, 'family_dataset_names': fam_ds,
           'geometry': geometry_expect(f, fam, names), 'structures': [], 'family_series': []}
    for d in fam_ds:
        rec['family_series'].append(series_record(d, g[d], T, True))
    pick = sorted({0, len(names) // 2, len(names) - 1}) if names else []
    for idx, n in enumerate(names):
        series, statics = [], []
        walk(g[n], '', series, statics)
        np_ = int(g[n].attrs['Node Pointer']) if 'Node Pointer' in g[n].attrs else None
        rec['structures'].append({
            'name': n, 'node_pointer': np_, 'group_attrs': attr_record(g[n]),
            'static_datasets': statics,
            'series': [series_record(r, ds, T, idx in pick) for r, ds in series]})
    return rec


def main():
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    wanted = sys.argv[3:] or DEFAULT
    result = {'format': 1, 'base': BASE, 'files': {}}
    for p in sorted(root.glob('*.hdf')):
        if not any(w in p.name for w in wanted):
            continue
        with h5py.File(p, 'r') as f:
            base = f[BASE]
            result['files'][p.name] = {
                'size': p.stat().st_size, 'time_rows': base['Time'].shape[0],
                'steady': 'Results/Steady' in f,
                'unqualified_present': [n for n in UNQUALIFIED if n in base],
                'families': {fam: family_record(f, fam) for fam in FAMILIES}}
    out.write_text(json.dumps(result, indent=1, sort_keys=True))
    print('wrote', out, {k: v['time_rows'] for k, v in result['files'].items()})


main()
