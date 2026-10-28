"""Supplemental synthetic 1D evidence, never a real HEC-RAS model oracle.
Run: python -I generate_1d.py OUTPUT_DIRECTORY (h5py and numpy required).
Derived from the bounded 1D proof packet's make_oracles.py supplemental section, MIT.
"""
from pathlib import Path
import sys
import h5py
import numpy as np

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for kind in ['steady', 'unsteady']:
    steady = kind == 'steady'
    base = 'Results/Steady/Output/Output Blocks/Base Output/Steady Profiles' if steady else 'Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series'
    with h5py.File(out / (kind + '.h5'), 'w', libver='earliest') as f:
        rows = np.zeros(2, dtype=[('River','S8'),('Reach','S8'),('RS','S8'),('Name','S8'),('Left Bank','<f4'),('Right Bank','<f4')])
        for key in ['River', 'Reach', 'RS']:
            rows[key] = [b'a', b'b']
        f['Geometry/Cross Sections/Attributes'] = rows
        if steady:
            f[base + '/Profile Names'] = np.array([b'p1', b'p2'], dtype='S8')
        identity = np.zeros(2, dtype=[('River','S8'),('Reach','S8'),('Station','S8')])
        for key in identity.dtype.names:
            identity[key] = [b'a', b'b']
        ip = 'Results/Steady/Output/Geometry Info/Cross Section Attributes' if steady else base + '/Cross Sections/Cross Section Attributes'
        f[ip] = identity
        values = np.array([[1,2],[3,4]] if steady else [[1,2],[3,4],[5,6]], dtype='<f4')
        f[base + '/Cross Sections/Water Surface'] = values
        f[base + '/Cross Sections/Flow'] = values.astype('<f8')
