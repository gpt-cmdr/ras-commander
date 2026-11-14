"""Experimental 7.0.1 boundary-event authoring; no solver equivalence claim.

Schema reference: gheistand/ras-agent PR 211 (Apache-2.0),
69a1a4a8fd286a7b261f50378cbcdba59a963d89. Independently implemented.
"""
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timedelta

import h5py
import numpy as np


def _text(value):
    return value.decode('latin-1').rstrip('\x00 ') if isinstance(value, bytes) else str(value)


def _date_stamp(moment, *, start=False):
    midnight = start and moment.hour == moment.minute == 0
    if midnight:
        moment -= timedelta(days=1)
    month = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
             'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')[moment.month - 1]
    clock = '2400' if midnight else f'{moment.hour:02d}{moment.minute:02d}'
    return f'{moment.day:02d}{month}{moment.year:04d} {clock}'


def _require_matching_geometry(source, destination, areas):
    def equal(a, b):
        if a.dtype.names:
            return all(equal(a[name], b[name]) for name in a.dtype.names)
        return np.array_equal(a, b, equal_nan=a.dtype.kind in 'fc')

    paths = ['Geometry/2D Flow Areas/Attributes',
             'Geometry/Boundary Condition Lines/Attributes',
             'Geometry/Boundary Condition Lines/External Faces']
    for area in areas:
        paths.extend(f'Geometry/2D Flow Areas/{area}/{name}' for name in
                     ('Faces FacePoint Indexes', 'FacePoints Coordinate'))
    # These native tables, when present, also define face/cell identity.
    optional = ['Geometry/Boundary Condition Lines/' + name for name in
                ('Polyline Info', 'Polyline Parts', 'Polyline Points')]
    for area in areas:
        optional.extend(f'Geometry/2D Flow Areas/{area}/{name}' for name in
                        ('Cells Center Coordinate', 'Faces Cell Indexes',
                         'Cells FacePoint Indexes'))
    paths.extend(path for path in optional if path in source or path in destination)
    for path in paths:
        if path not in source or path not in destination:
            raise ValueError(f'Destination geometry mismatch: missing {path}')
        a, b = source[path], destination[path]
        if (not isinstance(a, h5py.Dataset) or not isinstance(b, h5py.Dataset)
                or a.shape != b.shape or a.dtype != b.dtype
                or not equal(a[()], b[()])):
            raise ValueError(f'Destination geometry mismatch: {path}')


def _parse(path):
    boundaries = {}
    current = None
    lines = Path(path).read_text(encoding='latin-1').splitlines()
    i = 0
    defaults = {'Use DSS': 'False', 'Use Fixed Start Time': 'False',
                'Is Critical Boundary': 'False', 'Stage Hydrograph TW Check': '0',
                'DSS Path': '', 'DSS File': '',
                'Fixed Start Date/Time': ',', 'Critical Boundary Flow': '',
                'Use Restart': '0', 'Precipitation Mode': 'Disable'}
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line == 'BEGIN FILE DESCRIPTION:':
            while i < len(lines) and lines[i].strip() != 'END FILE DESCRIPTION:':
                i += 1
            if i == len(lines):
                raise ValueError('Unterminated file description')
            i += 1
            continue
        key, sep, value = line.partition('=')
        value = value.strip()
        if not sep:
            raise ValueError(f'Unsupported flow record: {line}')
        if key in ('Flow Title', 'Program Version'):
            continue
        if key == 'Boundary Location':
            fields = [x.strip() for x in value.split(',')]
            if len(fields) < 8 or any(fields[:5]) or fields[6] or any(fields[8:]):
                raise ValueError('Only external 2D boundary locations are supported')
            identity = (fields[5], fields[7])
            if not all(identity) or any('/' in x or '\x00' in x for x in identity) or identity in boundaries:
                raise ValueError('Invalid or duplicate boundary association')
            current = {}
            boundaries[identity] = current
        elif key == 'Flow Hydrograph Slope' and current is not None:
            slope = float(value)
            if not np.isfinite(slope) or slope < 0:
                raise ValueError('Flow distribution slope must be finite and nonnegative')
            current['slope'] = slope
        elif key in defaults:
            if value != defaults[key]:
                raise ValueError(f'Unsupported {key}={value}')
        elif key == 'Interval' and current is not None:
            match = re.fullmatch(r'([1-9][0-9]*)(SEC|MIN|HOUR|DAY)', value)
            if not match:
                raise ValueError('Invalid hydrograph interval')
            current['step'] = int(match[1]) / {'SEC': 86400, 'MIN': 1440, 'HOUR': 24, 'DAY': 1}[match[2]]
            current['step_seconds'] = int(match[1]) * {'SEC': 1, 'MIN': 60, 'HOUR': 3600, 'DAY': 86400}[match[2]]
        elif key in ('Flow Hydrograph', 'Friction Slope') and current is not None:
            if 'kind' in current:
                raise ValueError('Multiple forcing types on one boundary')
            current['kind'] = key
            if key == 'Friction Slope':
                values = [float(value)]
                if values[0] <= 0:
                    raise ValueError('Normal depth slope must be positive')
            else:
                count = int(value)
                if count < 2:
                    raise ValueError('Hydrograph requires at least two ordinates')
                values = []
                while len(values) < count and i < len(lines) and '=' not in lines[i]:
                    row = lines[i]
                    values.extend(float(row[k:k+8]) for k in range(0, len(row), 8) if row[k:k+8].strip())
                    i += 1
                if len(values) != count:
                    raise ValueError('Hydrograph ordinate count mismatch')
            current['values'] = values
        else:
            raise ValueError(f'Unsupported flow record: {key}')
    if not boundaries:
        raise ValueError('No boundary forcing found')
    return boundaries


def _write_events(plan_hdf, geom_hdf, flow_file, start_time, end_time, units, target_ras_version):
    unit_labels = {'Metric': 'SI Units', 'English': 'US Customary'}
    if target_ras_version != '7.0.1' or units not in unit_labels:
        raise ValueError('Experimental writer requires 7.0.1 and Metric or English units')
    if not isinstance(start_time, datetime) or not isinstance(end_time, datetime) or start_time.tzinfo or end_time.tzinfo or end_time <= start_time:
        raise ValueError('Supply increasing naive local simulation datetimes')
    if any(t.second or t.microsecond for t in (start_time, end_time)):
        raise ValueError('Simulation times require whole minutes')
    target = Path(plan_hdf)
    if target.resolve() in (Path(geom_hdf).resolve(), Path(flow_file).resolve()):
        raise ValueError('Output must differ from source files')
    from .fast_hdf import release_native_sessions
    from .geom.GeomPreprocessor import GeomPreprocessor
    release_native_sessions(target, Path(geom_hdf))
    GeomPreprocessor._require_closed_geometry_hdf(target)
    GeomPreprocessor._require_closed_geometry_hdf(Path(geom_hdf))
    boundaries = _parse(flow_file)
    prepared = []
    with h5py.File(geom_hdf, 'r') as geometry:
        if re.match(r'^HEC-RAS 7\.0\.1(?:\s|$)', _text(geometry.attrs.get('File Version', ''))) is None:
            raise ValueError('Geometry must declare HEC-RAS 7.0.1')
        if _text(geometry.attrs.get('Units System', '')) != unit_labels[units]:
            raise ValueError('Geometry units must explicitly match requested units')
        areas = [_text(r['Name']) for r in geometry['Geometry/2D Flow Areas/Attributes'][:]]
        attrs = geometry['Geometry/Boundary Condition Lines/Attributes'][:]
        external = geometry['Geometry/Boundary Condition Lines/External Faces'][:]
        if len(set(areas)) != len(areas):
            raise ValueError('Duplicate 2D area names')
        for name in ('BC Line ID', 'Face Index', 'FP Start Index', 'FP End Index'):
            if external.dtype[name].kind not in 'iu':
                raise ValueError('External Faces indexes must have integer dtype')
        identities = [(_text(r['SA-2D']), _text(r['Name'])) for r in attrs]
        if len(set(identities)) != len(identities) or set(identities) != set(boundaries):
            raise ValueError('Missing, unknown, or duplicate boundary associations')
        if np.any((external['BC Line ID'] < 0) | (external['BC Line ID'] >= len(attrs))):
            raise ValueError('Unknown External Faces boundary ID')
        for index, (identity, row) in enumerate(zip(identities, attrs)):
            area, name = identity
            if _text(row['Type']) != 'External':
                raise ValueError('Only External boundary types are supported')
            if area not in areas:
                raise ValueError('Unknown 2D area')
            bc = boundaries[identity]
            if 'kind' not in bc:
                raise ValueError('Missing boundary forcing')
            length = float(row['Length'])
            rows = external[external['BC Line ID'] == index]
            a, b = rows['Station Start'].astype(float), rows['Station End'].astype(float)
            if not np.isfinite(length) or length <= 0 or not np.all(np.isfinite([a, b])) or np.any(b <= a):
                raise ValueError('Invalid boundary length or stations')
            fraction = (np.minimum(b, length) - np.maximum(a, 0)) / (b-a)
            keep = np.flatnonzero(fraction > 0)
            if not len(keep) or np.any(np.diff(keep) != 1):
                raise ValueError('Boundary has no contiguous overlapping faces')
            selected = rows[keep]
            if np.any(selected['FP End Index'][:-1] != selected['FP Start Index'][1:]):
                raise ValueError('Disconnected boundary face points')
            if a[keep[0]] > 0 or b[keep[-1]] < length or not np.allclose(b[keep[:-1]], a[keep[1:]], rtol=0, atol=1e-6):
                raise ValueError('Boundary stations do not cover BC Length')
            faces = selected['Face Index']
            points = np.r_[selected['FP Start Index'][:1], selected['FP End Index']]
            mesh = geometry[f'Geometry/2D Flow Areas/{area}']
            for ids, limit in ((faces, len(mesh['Faces FacePoint Indexes'])), (points, len(mesh['FacePoints Coordinate']))):
                if np.any(ids < 0) or np.any(ids >= limit) or np.any(ids > np.iinfo(np.int32).max):
                    raise ValueError('Invalid face or face-point indexes')
            if len(np.unique(faces)) != len(faces):
                raise ValueError('Duplicate boundary faces')
            for face, p0, p1 in zip(faces, points[:-1], points[1:]):
                if set(mesh['Faces FacePoint Indexes'][int(face)]) != {p0, p1}:
                    raise ValueError('Face-point association mismatch')
            values = np.asarray(bc['values'], dtype=float)
            if bc['kind'] == 'Flow Hydrograph':
                if 'step' not in bc:
                    raise ValueError('Missing hydrograph interval')
                times = np.arange(len(values)) * bc['step']
                duration = end_time - start_time
                if (len(values) - 1) * bc['step_seconds'] < duration.days * 86400 + duration.seconds:
                    raise ValueError('Hydrograph does not cover simulation window')
                values = np.column_stack((times, values))
            with np.errstate(over='ignore'):
                data = values.astype('float32')
            if not np.all(np.isfinite(data)) or (data.ndim == 2 and np.any(np.diff(data[:, 0]) <= 0)):
                raise ValueError('Nonfinite data or invalid float32 time basis')
            slope = np.float32(bc.get('slope', 0))
            if not np.isfinite(slope):
                raise ValueError('Flow distribution slope exceeds float32 range')
            prepared.append((area, name, areas.index(area)+1, data, faces.astype('int32'), points.astype('int32'), fraction[keep].astype('float32'), slope))
    group_path = 'Event Conditions/Unsteady/Boundary Conditions'
    with h5py.File(target, 'r') as existing, h5py.File(geom_hdf, 'r') as geometry:
        if re.match(r'^HEC-RAS 7\.0\.1(?:\s|$)', _text(existing.attrs.get('File Version', ''))) is None:
            raise ValueError('Destination must declare HEC-RAS 7.0.1')
        if _text(existing.attrs.get('Units System', '')) != unit_labels[units]:
            raise ValueError('Destination units must match requested units')
        _require_matching_geometry(geometry, existing, areas)
        if group_path in existing and len(existing[group_path]):
            raise ValueError('Destination already has boundary forcing; use a fresh staged copy')
    fd, temporary = tempfile.mkstemp(prefix=target.name+'.', suffix='.tmp', dir=target.parent)
    os.close(fd)
    temporary = Path(temporary)
    try:
        shutil.copy2(target, temporary)
        with h5py.File(temporary, 'r+') as output:
            root = output.require_group(group_path)
            for area, name, node, data, faces, points, fractions, slope in prepared:
                kind = 'Flow Hydrographs' if data.ndim == 2 else 'Normal Depths'
                ds = root.require_group(kind).create_dataset(f'2D: {area} BCLine: {name}', data=data, chunks=data.shape, compression='gzip')
                for key, value in {'2D Flow Area': area, 'BC Line': name, 'Check TW Stage': 'False'}.items():
                    ds.attrs[key] = np.bytes_(value.encode('latin-1'))
                ds.attrs['Face Indexes'] = faces
                ds.attrs['Face Point Indexes'] = points
                ds.attrs['Face Fraction'] = fractions
                ds.attrs['Node Index'] = np.int32(node)
                if data.ndim == 2:
                    ds.attrs['Data Type'] = np.bytes_('INST-VAL')
                    ds.attrs['Interval'] = np.bytes_('Days')
                    ds.attrs['EG Slope For Distributing Flow'] = slope
                    for key, moment in (('Start Date', start_time), ('End Date', end_time)):
                        stamp = _date_stamp(moment, start=key == 'Start Date')
                        ds.attrs[key] = np.bytes_(stamp)
        # Exclusive backup creation never overwrites a prior retained copy.
        backup = target.with_name(target.name+'.events.bak')
        backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(backup_fd, 'wb') as saved, target.open('rb') as original:
                shutil.copyfileobj(original, saved)
        except BaseException:
            # Exclusive creation succeeded: this attempt owns the incomplete
            # backup. Existing backups never reach this cleanup path.
            backup.unlink(missing_ok=True)
            raise
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
