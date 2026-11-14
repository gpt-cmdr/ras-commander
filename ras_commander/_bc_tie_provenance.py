"""Versioned provenance for opt-in compiled boundary repairs."""
import hashlib
import json

import numpy as np

GROUP = 'Geometry/Boundary Condition Lines'
ATTRIBUTE = 'RAS Commander Boundary Repair'
TABLES = ('Attributes', 'External Faces', 'Polyline Points', 'Polyline Info', 'Polyline Parts')


def fingerprint(hdf):
    digest = hashlib.sha256()
    paths = [f'{GROUP}/{name}' for name in TABLES]
    area_root = 'Geometry/2D Flow Areas'
    paths.append(f'{area_root}/Attributes')
    if area_root in hdf:
        for area in sorted(hdf[area_root]):
            if area == 'Attributes':
                continue
            paths.extend(f'{area_root}/{area}/{name}' for name in
                         ('Perimeter', 'Faces Cell Indexes', 'Faces FacePoint Indexes', 'FacePoints Coordinate'))
    for path in paths:
        name = path
        digest.update(name.encode())
        if path not in hdf:
            digest.update(b'absent')
            continue
        data = hdf[path][()]
        if data.dtype.hasobject:
            raise ValueError('Unsupported variable-length boundary repair table')
        digest.update(str(data.dtype.descr).encode())
        digest.update(str(data.shape).encode())
        # Ignore compound-record padding; hash every declared field instead.
        for field in data.dtype.names or (None,):
            digest.update(np.ascontiguousarray(data if field is None else data[field]).tobytes())
    return digest.hexdigest()


def read_receipt(hdf, boundary_types=None, *, require_types=False):
    if GROUP not in hdf or ATTRIBUTE not in hdf[GROUP].attrs:
        return None
    try:
        raw = hdf[GROUP].attrs[ATTRIBUTE]
        receipt = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
        if (not isinstance(receipt, dict) or receipt.get('version') != 1
                or not isinstance(receipt.get('types'), list)
                or not isinstance(receipt.get('audit'), list)
                or receipt.get('fingerprint') != fingerprint(hdf)):
            raise ValueError('Malformed or stale boundary repair provenance')
        identities = set()
        for row in receipt['types']:
            key = (row['area'], row['name'])
            if (not all(isinstance(v, str) and v for v in key)
                    or key in identities or row['type'] not in ('flow', 'normal_depth')):
                raise ValueError('Malformed boundary repair types')
            identities.add(key)
            if require_types or boundary_types is not None:
                if (boundary_types or {}).get(key) != row['type']:
                    raise ValueError(f'Boundary repair type contradiction or missing type: {key}')
        return receipt
    except (TypeError, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Malformed boundary repair provenance') from exc


def write_receipt(hdf, types, audit):
    receipt = {'version': 1, 'fingerprint': fingerprint(hdf),
               'types': [{'area': a, 'name': n, 'type': t}
                         for (a, n), t in sorted(types.items())], 'audit': audit}
    hdf[GROUP].attrs[ATTRIBUTE] = json.dumps(receipt, allow_nan=False, sort_keys=True)
    return receipt
