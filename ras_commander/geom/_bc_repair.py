"""Opt-in end trimming; geometry policy from gheistand/ras-agent issue 214.

Independent implementation. Ambiguous projections are rejected, never sampled
to select a longest retained piece. Distances are in model units.
"""
import h5py
import numpy as np
from shapely.geometry import LineString
from shapely.ops import substring

from .._bc_tie_provenance import GROUP, read_receipt
from ._bc_projection import project_pieces, invert_station


def prepare_repair(path, boundary_types, relative_tolerance, max_passes):
    from .GeomBcLines import GeomBcLines
    if isinstance(max_passes, bool) or not isinstance(max_passes, int) or not 1 <= max_passes <= 100:
        raise ValueError('max_repair_passes must be an integer in [1, 100]')
    types = dict(boundary_types or {})
    if any(value not in ('flow', 'normal_depth') for value in types.values()):
        raise ValueError('Repair boundary types must be flow or normal_depth')
    with h5py.File(path, 'r') as hdf:
        receipt = read_receipt(hdf, types, require_types=True)
        group = hdf[GROUP]
        info, xy = group['Polyline Info'][()], group['Polyline Points'][()]
        if info.ndim != 2 or info.shape[1] != 4 or info.dtype.kind not in 'iu':
            raise ValueError('Invalid Polyline Info')
        parts = group['Polyline Parts'][()] if 'Polyline Parts' in group else None
        if parts is not None and (parts.shape != (len(info), 2) or parts.dtype.kind not in 'iu'):
            raise ValueError('Unsupported Polyline Parts')
        offset, lines = 0, []
        for index, (start, count, part, n_parts) in enumerate(info):
            if start != offset or count < 2 or n_parts != 1 or part != index:
                raise ValueError('Repair requires contiguous single-part polyline records')
            if parts is not None and not np.array_equal(parts[index], [0, count]):
                raise ValueError('Malformed Polyline Parts offsets')
            lines.append(xy[start:start + count].copy())
            offset += int(count)
        if offset != len(xy):
            raise ValueError('Polyline coordinate count mismatch')
        rings = {name: hdf[f'Geometry/2D Flow Areas/{name}/Perimeter'][()]
                 for name in {_decode(row['SA-2D']) for row in group['Attributes'][()]}}
    point_dtype = xy.dtype if xy.dtype.kind == 'f' else np.dtype('float64')
    if point_dtype.itemsize < 4:
        raise ValueError('Unsupported coordinate precision')
    saved_types = {(r['area'], r['name']): r['type'] for r in receipt['types']} if receipt else {}
    prior_audit = receipt['audit'] if receipt else []
    audit = []
    for iteration in range(max_passes + 1):
        raw = GeomBcLines._compute_external_faces(
            path, relative_tolerance=relative_tolerance, collect_conflicts=True, polylines=lines)
        decision = GeomBcLines._arbitrate_external_faces(raw, types)
        if decision['unresolved_count']:
            raise ValueError('Unresolved shared-face arbitration tie')
        if not decision['conflicts']:
            break
        if iteration == max_passes:
            raise ValueError('Boundary repair pass limit exceeded')
        losses = {}
        for conflict in decision['conflicts']:
            saved_types.update(conflict['tie_types'])
            for claim in conflict['claims']:
                if claim['identity'] != conflict['winner']:
                    index = raw['identities'].index(claim['identity'])
                    losses.setdefault(index, set()).add(conflict['face_index'])
        for index, lost in losses.items():
            identity = raw['identities'][index]
            rows = raw['external_faces']
            rows = rows[rows['BC Line ID'] == index].to_dict('records')
            keep = [i for i, row in enumerate(rows) if int(row['Face Index']) not in lost]
            if not keep:
                raise ValueError(f'Cut would leave no span for {identity}')
            if keep != list(range(keep[0], keep[-1] + 1)):
                raise ValueError(f'Cut would split boundary {identity}')
            length = float(raw['lengths'][index])
            low = max(0., rows[keep[0]]['Station Start'])
            high = min(length, rows[keep[-1]]['Station End'])
            available = high - low
            if available <= 0:
                raise ValueError(f'Cut would leave no span for {identity}')
            if keep[0]:
                lost_row = rows[keep[0] - 1]
                low += min(1., .1 * (lost_row['Station End'] - lost_row['Station Start']), .5 * available)
            if keep[-1] != len(rows) - 1:
                lost_row = rows[keep[-1] + 1]
                high -= min(1., .1 * (lost_row['Station End'] - lost_row['Station Start']), .5 * (high - low))
            if high <= low:
                raise ValueError(f'Cut would leave no span for {identity}')
            pieces = project_pieces(lines[index], rings[identity[0]])
            origin, end = pieces[0][2], pieces[-1][3]
            if not np.isclose(abs(end-origin), length, rtol=0, atol=1e-7):
                raise ValueError(f'Certified projection disagrees with binding for {identity}')
            sign = 1 if end > origin else -1
            drawn = LineString(lines[index])
            a = 0. if low == 0 else invert_station(pieces, origin + sign*low)
            b = drawn.length if high == length else invert_station(pieces, origin + sign*high)
            if not a < b:
                raise ValueError(f'Invalid continuous trim for {identity}')
            cut = np.asarray(substring(drawn, a, b).coords, dtype=point_dtype)
            check = project_pieces(cut, rings[identity[0]])
            after = abs(check[-1][3] - check[0][2])
            if after >= length or after <= 0:
                raise ValueError(f'Serialized trim did not reduce boundary {identity}')
            audit.append({'area': identity[0], 'name': identity[1], 'pass': iteration + 1,
                          'lost_faces': sorted(lost), 'length_before': length, 'length_after': after,
                          'points_before': lines[index].tolist(), 'points_after': cut.tolist(),
                          'decisions': [_json_decision(c) for c in decision['conflicts']
                                        if c['area'] == identity[0] and c['face_index'] in lost]})
            lines[index] = cut
    # The final binding uses the actual coordinate dtype that will be stored.
    updates = {}
    if audit:
        counts = np.asarray([len(line) for line in lines], dtype=np.int64)
        offsets = np.r_[0, np.cumsum(counts)[:-1]]
        new_info = np.column_stack((offsets, counts, np.arange(len(lines)), np.ones(len(lines), dtype=int)))
        if np.max(new_info) > np.iinfo(info.dtype).max:
            raise ValueError('Repaired polyline offsets exceed native dtype')
        updates = {'Polyline Points': np.concatenate(lines).astype(point_dtype),
                   'Polyline Info': new_info.astype(info.dtype),
                   'Polyline Parts': np.column_stack((np.zeros(len(lines), dtype=int), counts)).astype(
                       parts.dtype if parts is not None else info.dtype)}
    return {**raw, 'polyline_updates': updates, 'repair_audit': audit,
            'prior_audit': prior_audit, 'tie_types': saved_types,
            'has_receipt': receipt is not None, 'changed': bool(audit)}


def _decode(value):
    return value.decode('utf-8').rstrip('\x00 ') if isinstance(value, bytes) else str(value)


def _json_decision(decision):
    return {k: v for k, v in decision.items() if k != 'tie_types'}
