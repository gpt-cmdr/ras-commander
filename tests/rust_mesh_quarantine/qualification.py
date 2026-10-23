"""Full immutable 5/6/7 geometry qualification (bridge API_VERSION 11).

Run as a script; it is not collected by pytest. For each pinned fixture it
checks, against the Python reference (``engine="h5py"``):

* required native (``engine="native"``, threads 1 and 4) returns every
  composite ID and every normalized coordinate of the reference, with the
  reference diagnostic records exactly, and never reaches Python polygonize;
* auto mode returns exactly the reference outcome (frame and diagnostics);
* strict native fails on the first invalid source cell (5.0.7) with the
  documented ``MeshCellPolygonError``; a detached-array probe exposes the
  second invalid original cell identity without touching the HDF.

Output JSON belongs in an ignored evidence directory, not tests. Timings
describe mesh extraction only; no export or solver is benchmarked.
"""
import argparse
from collections import Counter
from contextlib import contextmanager
from functools import wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import threading
import time

import h5py
import numpy as np
import psutil
import shapely
import shapely.ops
from ras_commander import fast_hdf as adapter
from ras_commander.hdf.HdfMesh import HdfMesh, MeshCellPolygonError
import ras_commander_fast_hdf as native

API_VERSION = 11
ENGINE_COMMIT = "0b024adc7857e9fb2d364997ad002e01a939cec1"
# (stored version, file name, polygon count, SHA256 of the immutable copy)
FIXTURES = [
    ('5.0.7', 'JUL2020_D100RAS.p04.hdf', 340246,
     '37d91b9f957f78067cb0a8ae5db7cf3355f9c5d7172cb40e7931c35be78b9683'),
    ('6.6', 'BaldEagleDamBrk.p07.hdf', 87039,
     '07cad3930a679891f87bbface1ab749b82fd7d7eae6aaac3b5ff041c44280984'),
    ('7.0', 'BaldEagleDamBrk.p18.hdf', 4425,
     '1d0063a84fd131ac95ffaa2b3f6647f2ef51c7f38f23c43e8ae6c698bfc95f0b'),
]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


@contextmanager
def measurements():
    """Count/time native assembly and adapter dataset reads; sample RSS at 10 ms."""
    record = {'native_assembly_calls': 0, 'dataset_read_calls': 0,
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
    # Reads go through adapter.read_datasets (native HdfSession batches), which
    # _assemble resolves at call time; assembly goes through the module binding.
    targets = [(native, 'assemble_cells', 'native_assembly_calls', 'assembly_seconds'),
               (adapter, 'read_datasets', 'dataset_read_calls', 'read_seconds')]
    originals = []
    for owner, name, calls, seconds in targets:
        original = getattr(owner, name)
        originals.append((owner, name, original))

        @wraps(original)
        def wrapper(*args, _original=original, _calls=calls, _seconds=seconds, **kwargs):
            record[_calls] += 1
            start = time.perf_counter()
            try:
                return _original(*args, **kwargs)
            finally:
                record[_seconds] += time.perf_counter() - start
        setattr(owner, name, wrapper)
    start = time.perf_counter()
    try:
        yield record
    finally:
        record['total_seconds'] = time.perf_counter() - start
        for owner, name, original in originals:
            setattr(owner, name, original)
        done.set()
        sampler.join()
        record['rss_peak_bytes'] = max(peak[0], process.memory_info().rss)
        record['rss_end_bytes'] = process.memory_info().rss
        record['adapter_and_output_seconds'] = (
            record['total_seconds'] - record['assembly_seconds'] - record['read_seconds'])


@contextmanager
def python_polygonize_forbidden():
    original = shapely.ops.polygonize

    def forbidden(*args, **kwargs):
        raise AssertionError('Python polygonize fallback forbidden during required native qualification')
    shapely.ops.polygonize = forbidden
    try:
        yield
    finally:
        shapely.ops.polygonize = original


@contextmanager
def fast_hdf_env(value):
    previous = os.environ.get('RAS_COMMANDER_FAST_HDF')
    os.environ['RAS_COMMANDER_FAST_HDF'] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop('RAS_COMMANDER_FAST_HDF', None)
        else:
            os.environ['RAS_COMMANDER_FAST_HDF'] = previous


def canonical(frame):
    order = np.lexsort((frame.cell_id.to_numpy(), frame.mesh_name.to_numpy()))
    keys = list(zip(frame.mesh_name.iloc[order], map(int, frame.cell_id.iloc[order])))
    # Exact consecutive duplicate samples do not alter a polygon boundary.
    # No tolerance, snapping, repair, or removal of forward collinear vertices.
    geometries = shapely.normalize(shapely.remove_repeated_points(frame.geometry.to_numpy()[order], 0))
    return keys, shapely.to_wkb(geometries)


def compare(actual, reference_keys, reference_wkb, reference_diagnostics, label):
    keys, wkb = canonical(actual)
    assert keys == reference_keys, label
    mismatches = np.flatnonzero(wkb != reference_wkb)
    assert not len(mismatches), (label, [(keys[i], shapely.from_wkb(wkb[i]).wkt,
                                          shapely.from_wkb(reference_wkb[i]).wkt)
                                         for i in mismatches[:3]])
    diagnostics = actual.attrs.get('cell_polygon_diagnostics', ())
    assert diagnostics == reference_diagnostics, label
    return keys, wkb, diagnostics


def run(version, path, count, expected_hash):
    assert path.is_file(), path
    before = digest(path)
    assert before == expected_hash, (path, before)
    with h5py.File(path, 'r') as hdf:
        attrs = {str(key): str(value) for key, value in hdf.attrs.items()}
    with measurements() as python_measure:
        reference = HdfMesh.get_mesh_cell_polygons(path, engine='h5py', strict=False, diagnostics=True)
    assert python_measure['native_assembly_calls'] == 0
    assert len(reference) == count and count > 0
    reference_keys, reference_wkb = canonical(reference)
    reference_diagnostics = reference.attrs.get('cell_polygon_diagnostics', ())
    assert len(set(reference_keys)) == count
    result = {'version': version, 'path': str(path), 'sha256_before': before,
              'hdf_attributes': attrs, 'polygons': count, 'python': python_measure,
              'reference_diagnostics_by_status': dict(Counter(d['status'] for d in reference_diagnostics)),
              'native': []}
    with python_polygonize_forbidden():
        for threads in (1, 4):
            with measurements() as measure:
                actual = HdfMesh.get_mesh_cell_polygons(path, engine='native', strict=False, threads=threads,
                                                      diagnostics=True)
            assert measure['native_assembly_calls'] > 0 and measure['dataset_read_calls'] > 0
            assert len(actual) == count and bool(shapely.is_valid(actual.geometry.to_numpy()).all())
            keys, wkb, diagnostics = compare(actual, reference_keys, reference_wkb,
                                             reference_diagnostics, f'rust threads={threads}')
            invalid = [dict(d) for d in diagnostics
                       if d['status'] == 'omitted' and d['reason_code'] == 'no_polygon']
            if version == '5.0.7':
                assert sorted(d['cell_id'] for d in invalid) == [317422, 339176], invalid
                assert all(d['mesh_name'] for d in invalid)
            else:
                assert not invalid, invalid
            measure.update(threads=threads, compared_composite_ids=len(keys),
                           compared_polygon_geometries=len(wkb), invalid_omissions=invalid,
                           diagnostics_by_status=dict(Counter(d['status'] for d in diagnostics)))
            result['native'].append(measure)
        if version == '5.0.7':
            try:
                HdfMesh.get_mesh_cell_polygons(path, engine='native', strict=True, threads=4)
            except MeshCellPolygonError as exc:
                assert 'cell 317422:' in str(exc), str(exc)
                result['strict_error'] = str(exc)
            else:
                raise AssertionError('strict native unexpectedly accepted invalid source cells')
            # Expose the second original cell identity in strict mode without
            # renumbering or changing the immutable HDF: replace only the first
            # invalid cell's count in a detached array copy used by this probe.
            mesh_name = result['native'][0]['invalid_omissions'][0]['mesh_name']
            with h5py.File(path, 'r') as hdf:
                arrays = [np.ascontiguousarray(hdf[f'Geometry/2D Flow Areas/{mesh_name}/{name}'][()],
                                               dtype='f8' if index in (0, 3) else 'i8')
                          for index, name in enumerate(adapter._MESH_ARRAYS)]
            arrays[4] = arrays[4].copy()
            arrays[4][317422, 1] = 0
            try:
                native.assemble_cells(*arrays, strict=True, threads=4)
            except native.TopologyError as exc:
                assert 'cell 339176:' in str(exc), str(exc)
                assert exc.mesh_structure_error is False
                result['second_strict_error_detached_array_probe'] = str(exc)
            else:
                raise AssertionError('strict accepted second invalid original cell')
        else:
            strict = HdfMesh.get_mesh_cell_polygons(path, engine='native', strict=True)
            assert len(strict) == count
    # Auto: exactly the Python reference outcome (native first, h5py on refusal).
    adapter.close_sessions()
    with fast_hdf_env('auto'), measurements() as measure:
        auto = HdfMesh.get_mesh_cell_polygons(path, engine='auto', strict=False, diagnostics=True)
    compare(auto, reference_keys, reference_wkb, reference_diagnostics, 'auto')
    assert auto.crs == reference.crs
    result['auto'] = measure
    if version == '5.0.7':
        outcomes = []
        for engine in ('h5py', 'auto'):
            with fast_hdf_env('auto'):
                try:
                    HdfMesh.get_mesh_cell_polygons(path, engine=engine, strict=True)
                except Exception as exc:  # noqa: BLE001 - the exception is the outcome
                    outcomes.append((type(exc), str(exc)))
                else:
                    outcomes.append(None)
        assert outcomes[0] is not None and outcomes[0][0] is MeshCellPolygonError, outcomes
        assert outcomes[1] == outcomes[0], outcomes
        result['strict_auto_equals_python'] = outcomes[0][1]
    adapter.close_sessions()
    result['sha256_after'] = digest(path)
    assert result['sha256_after'] == before
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--version', choices=['all', '5.0.7', '6.6', '7.0'], default='all')
    parser.add_argument('--fixture-root', type=Path,
                        default=Path(os.environ['RAS_QUAL_FIXTURES']) if os.environ.get('RAS_QUAL_FIXTURES') else None,
                        help='Local directory holding the three pinned HDF fixtures '
                             '(default: $RAS_QUAL_FIXTURES)')
    args = parser.parse_args()
    if args.fixture_root is None:
        parser.error('--fixture-root (or RAS_QUAL_FIXTURES) is required')
    assert native.API_VERSION == API_VERSION, native.API_VERSION
    assert native.ENGINE_COMMIT == ENGINE_COMMIT, native.ENGINE_COMMIT
    adapter._reset_native()
    assert adapter.available(), 'ras_commander.fast_hdf does not accept the installed extension'
    module_dir = Path(native.__file__).resolve().parent
    binaries = [p for p in module_dir.iterdir() if p.suffix.lower() in {'.pyd', '.so', '.dylib'}]
    assert len(binaries) == 1, binaries
    mesh_rs = Path(__file__).resolve().parents[2] / 'rust/fast-hdf/src/mesh.rs'
    records = {'native_module': native.__file__, 'api_version': native.API_VERSION,
               'engine_commit': native.ENGINE_COMMIT,
               'inner_binary': str(binaries[0]), 'inner_binary_sha256': digest(binaries[0]),
               'adapter_path': adapter.__file__, 'adapter_sha256': digest(Path(adapter.__file__)),
               'hdf_mesh_path': inspect.getfile(HdfMesh),
               'hdf_mesh_sha256': digest(Path(inspect.getfile(HdfMesh))),
               'bridge_mesh_rs_path': str(mesh_rs),
               'bridge_mesh_rs_sha256': digest(mesh_rs) if mesh_rs.is_file() else None,
               'measurement_scope': 'mesh extraction only; sampled process RSS; '
                                    'adapter/output residual includes Python setup',
               'fixtures': []}
    for version, name, count, sha in FIXTURES:
        if args.version in ('all', version):
            records['fixtures'].append(run(version, args.fixture_root / name, count, sha))
            args.output.write_text(json.dumps(records, indent=2, default=str), encoding='utf-8')
            print(f'{version} full coordinate/composite-ID/diagnostic parity passed '
                  '(required native and auto)', flush=True)


if __name__ == '__main__':
    main()
