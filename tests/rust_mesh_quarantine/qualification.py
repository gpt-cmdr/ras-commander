"""Full immutable 5/6/7 geometry qualification. Run as a module/script.

Output JSON belongs in the packet's ignored evidence directory, not tests.
Timings describe mesh extraction only; no export or solver is benchmarked.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from functools import wraps
import hashlib
import json
import importlib
from pathlib import Path
import threading
import time

import h5py
import numpy as np
import psutil
import shapely
from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError
import ras_commander_fast_hdf as native


CACHE = Path('C:/Users/jacob/.cache/fluvial-graph-01a14bf2')
FIXTURES = [
    ('5.0.7', CACHE / 'qualification/JUL2020_D100RAS.p04.hdf', 340246,
     '37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683'),
    ('6.6', CACHE / 'fixtures/BaldEagleDamBrk.p07.hdf', 87039,
     '07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984'),
    ('7.0', CACHE / 'followup7_evidence/BaldEagleDamBrk.p18.hdf', 4425,
     '1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b'),
]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def measurements():
    record = {'native_assembly_calls': 0, 'native_read_calls': 0,
              'assembly_seconds': 0., 'read_seconds': 0.}
    process = psutil.Process()
    record['rss_start_bytes'] = process.memory_info().rss
    peak = [record['rss_start_bytes']]
    done = threading.Event()
    def sample():
        while not done.wait(.01):
            peak[0] = max(peak[0], process.memory_info().rss)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    originals = {}
    for name, prefix in [('assemble_cells', 'assembly'), ('read_numeric_batch', 'read')]:
        original = getattr(native, name)
        originals[name] = original
        @wraps(original)
        def wrapper(*args, _original=original, _prefix=prefix, **kwargs):
            record['native_' + ('assembly' if _prefix == 'assembly' else 'read') + '_calls'] += 1
            start = time.perf_counter()
            try:
                return _original(*args, **kwargs)
            finally:
                record[_prefix + '_seconds'] += time.perf_counter() - start
        setattr(native, name, wrapper)
    start = time.perf_counter()
    try:
        yield record
    finally:
        record['total_seconds'] = time.perf_counter() - start
        for name, original in originals.items():
            setattr(native, name, original)
        done.set()
        sampler.join()
        record['rss_peak_bytes'] = max(peak[0], process.memory_info().rss)
        record['rss_end_bytes'] = process.memory_info().rss
        record['adapter_and_output_seconds'] = record['total_seconds'] - record['assembly_seconds'] - record['read_seconds']


def canonical(frame):
    order = np.lexsort((frame.cell_id.to_numpy(), frame.mesh_name.to_numpy()))
    keys = list(zip(frame.mesh_name.iloc[order], map(int, frame.cell_id.iloc[order])))
    # Exact consecutive duplicate samples do not alter a polygon boundary.
    # No tolerance, snapping, repair, or removal of forward collinear vertices.
    geometries = shapely.normalize(shapely.remove_repeated_points(frame.geometry.to_numpy()[order], 0))
    return keys, shapely.to_wkb(geometries)


def run(version, path, count, expected_hash):
    assert path.is_file(), path
    before = digest(path)
    assert before == expected_hash
    with h5py.File(path, 'r') as hdf:
        attrs = {str(key): str(value) for key, value in hdf.attrs.items()}
    with measurements() as python_measure:
        reference = HdfMesh.get_mesh_cell_polygons(path, backend='python', strict=False)
    assert len(reference) == count and count > 0
    reference_keys, reference_wkb = canonical(reference)
    assert len(set(reference_keys)) == count
    result = {'version': version, 'path': str(path), 'sha256_before': before,
              'hdf_attributes': attrs, 'polygons': count, 'python': python_measure, 'native': []}
    import shapely.ops
    original_polygonize = shapely.ops.polygonize
    def forbidden(*args, **kwargs):
        raise AssertionError('Python polygonize fallback forbidden during required native qualification')
    shapely.ops.polygonize = forbidden
    try:
        baseline_diagnostics = None
        for threads in (1, 4):
            with measurements() as measure:
                actual = HdfMesh.get_mesh_cell_polygons(path, backend='rust', strict=False, threads=threads)
            assert measure['native_assembly_calls'] > 0 and measure['native_read_calls'] > 0
            assert len(actual) == count and bool(shapely.is_valid(actual.geometry.to_numpy()).all())
            keys, wkb = canonical(actual)
            assert keys == reference_keys
            mismatches = np.flatnonzero(wkb != reference_wkb)
            assert not len(mismatches), [(keys[i], shapely.from_wkb(wkb[i]).wkt, shapely.from_wkb(reference_wkb[i]).wkt) for i in mismatches[:3]]
            diagnostics = actual.attrs.get('cell_polygon_diagnostics', ())
            invalid = [dict(d) for d in diagnostics if d['status'] == 'omitted' and d['reason_code'] != 'zero_faces']
            if version == '5.0.7':
                assert sorted(d['cell_id'] for d in invalid) == [317422, 339176], invalid
                assert all(d['mesh_name'] and d['reason_code'] for d in invalid)
            else:
                assert not invalid, invalid
            if baseline_diagnostics is None:
                baseline_diagnostics = diagnostics
            assert diagnostics == baseline_diagnostics
            measure.update(threads=threads, compared_composite_ids=len(keys), compared_polygon_coordinates=len(wkb),
                           invalid_omissions=invalid, diagnostics_by_status=dict(Counter(d['status'] for d in diagnostics)))
            result['native'].append(measure)
        if version == '5.0.7':
            try:
                HdfMesh.get_mesh_cell_polygons(path, backend='rust', strict=True, threads=4)
            except MeshCellPolygonError as exc:
                assert '317422' in str(exc)
                result['strict_error'] = str(exc)
            else:
                raise AssertionError('strict native unexpectedly accepted invalid source cells')
            # Expose the second original cell identity in strict mode without
            # renumbering or changing the immutable HDF: replace only the first
            # invalid cell's count in a detached array copy used by this probe.
            from ras_commander.fast_hdf import _MESH_ARRAYS
            mesh_name = result['native'][0]['invalid_omissions'][0]['mesh_name']
            with h5py.File(path, 'r') as hdf:
                arrays = [np.ascontiguousarray(hdf[f'Geometry/2D Flow Areas/{mesh_name}/{name}'][()],
                          dtype='f8' if index in (0, 3) else 'i8')
                          for index, name in enumerate(_MESH_ARRAYS)]
            arrays[4] = arrays[4].copy()
            arrays[4][317422, 1] = 0
            try:
                native.assemble_cells(*arrays, strict=True, threads=4)
            except native.TopologyError as exc:
                assert 'cell 339176:' in str(exc), str(exc)
                result['second_strict_error_detached_array_probe'] = str(exc)
            else:
                raise AssertionError('strict accepted second invalid original cell')
        else:
            strict = HdfMesh.get_mesh_cell_polygons(path, backend='rust', strict=True)
            assert len(strict) == count
    finally:
        shapely.ops.polygonize = original_polygonize
    result['sha256_after'] = digest(path)
    assert result['sha256_after'] == before
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', choices=['all', '5.0.7', '6.6', '7.0'], default='all')
    parser.add_argument('--fixture-root', type=Path, help='Local directory of the three pinned HDF fixtures')
    args = parser.parse_args()
    if args.fixture_root is not None:
        FIXTURES = [(version, args.fixture_root / path.name, count, sha)
                    for version, path, count, sha in FIXTURES]
    assert native.API_VERSION == 1
    import ras_commander.fast_hdf as adapter
    import inspect
    binding = native.assemble_cells
    inner_name = getattr(binding, '__module__', '')
    inner = importlib.import_module(inner_name) if inner_name else native
    inner_path = Path(getattr(inner, '__file__', native.__file__))
    # Maturin packages commonly re-export the extension under an outer package.
    if inner_path.suffix.lower() != '.pyd':
        candidates = list(Path(native.__file__).parent.glob('*.pyd'))
        assert len(candidates) == 1, candidates
        inner_path = candidates[0]
    records = {'native_module': native.__file__, 'api_version': native.API_VERSION,
               'inner_pyd': str(inner_path), 'inner_pyd_sha256': digest(inner_path),
               'adapter_path': adapter.__file__, 'adapter_sha256': digest(Path(adapter.__file__)),
               'hdf_mesh_path': inspect.getfile(HdfMesh), 'hdf_mesh_sha256': digest(Path(inspect.getfile(HdfMesh))),
               'rust_mesh_path': str(Path(__file__).resolve().parents[2] / 'rust/fast-hdf/src/mesh.rs'),
               'rust_mesh_sha256': digest(Path(__file__).resolve().parents[2] / 'rust/fast-hdf/src/mesh.rs'),
               'measurement_scope': 'mesh extraction only; sampled process RSS; adapter/output residual includes Python setup', 'fixtures': []}
    for fixture in FIXTURES:
        if args.version in ('all', fixture[0]):
            records['fixtures'].append(run(*fixture))
            args.output.write_text(json.dumps(records, indent=2), encoding='utf-8')
            print(f'{fixture[0]} full coordinate/composite-ID parity passed', flush=True)
