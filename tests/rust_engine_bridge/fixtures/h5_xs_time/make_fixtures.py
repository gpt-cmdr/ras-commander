"""Generate synthetic 1D unsteady XS fixtures; run as: python -I make_fixtures.py OUTDIR
Needs h5py/numpy only. xs_time_ok has an unsteady Time axis whose length equals the XS result
rows; xs_time_mismatch has a longer Time axis. Writes manifest.json with SHA256."""
import hashlib, json, sys
from pathlib import Path
import h5py, numpy as np

BASE = 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'
ROWS = 3


def build(path, time_rows):
    with h5py.File(path, 'w') as f:
        names = [('River A', 'Reach 1', '100'), ('River A', 'Reach 1', '200')]
        dt = np.dtype([('River', 'S16'), ('Reach', 'S16'), ('RS', 'S8')])
        f.create_dataset('Geometry/Cross Sections/Attributes',
                         data=np.array([tuple(x.encode() for x in n) for n in names], dtype=dt))
        rdt = np.dtype([('River', 'S16'), ('Reach', 'S16'), ('Station', 'S8')])
        f.create_dataset(BASE + '/Cross Sections/Cross Section Attributes',
                         data=np.array([tuple(x.encode() for x in n) for n in names], dtype=rdt))
        f.create_dataset(BASE + '/Cross Sections/Water Surface',
                         data=np.arange(ROWS * 2, dtype='<f4').reshape(ROWS, 2))
        f.create_dataset(BASE + '/Time', data=np.arange(time_rows, dtype='<f8') / 24.0)


out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
manifest = {}
for name, rows in (('xs_time_ok', ROWS), ('xs_time_mismatch', ROWS + 1)):
    p = out / (name + '.h5')
    build(p, rows)
    manifest[name + '.h5'] = hashlib.sha256(p.read_bytes()).hexdigest()
(out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
