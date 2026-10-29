"""Catalog planning, admission and real native-HDF block reads."""

import json
from pathlib import Path
import numpy as np
import pytest

from ras_commander.fim import FimUnsupportedError
from ras_commander.fim._catalog import (
    _check_sources,
    _plan_units,
    _worker_count,
    _write_json,
)


def job(index, times, polygon="A", key="source"):
    return dict(
        index=index,
        job_id=f"job{index}",
        timesteps=times,
        key=key,
        aoi=dict(wkb=polygon, crs="same"),
    )


def test_selector_waves_bound_staging_and_preserve_occurrences():
    jobs = [job(0, [3, 2, 3, 1, 8]), job(1, [1, 8]), job(2, [2], key="another")]
    units = _plan_units(jobs, 3)
    assert all(len(u["selectors"]) <= 3 for u in units)
    occurrences = {j["index"]: [] for j in jobs}
    for unit in units:
        for segment in unit["segments"]:
            j = segment["job"]
            occurrences[j["index"]].extend(
                j["timesteps"][segment["start"] : segment["end"]]
            )
    assert occurrences == {0: [3, 2, 3, 1, 8], 1: [1, 8], 2: [2]}


def test_identical_windows_stay_adjacent_without_changing_result_identity():
    units = _plan_units([job(0, [1], "A"), job(1, [2], "B"), job(2, [1], "A")], 8)
    assert len(units) == 1
    assert [s["job"]["index"] for s in units[0]["segments"]] == [0, 2, 1]
    assert units[0]["selectors"] == [1, 2]


def test_parallel_strategy_makes_same_source_jobs_independently_schedulable():
    units = _plan_units([job(0, [1, 2]), job(1, [2, 3])], 8, "parallel")
    assert len(units) == 2
    assert units[0]["selectors"] == [1, 2] and units[1]["selectors"] == [2, 3]


@pytest.mark.parametrize("memory,workers", [(8192, 2), (6000, 1)])
def test_global_admission_partitions_cpus_and_memory(memory, workers):
    cpus = _worker_count(
        20,
        [2, 3, 4, 5],
        threads=4,
        max_workers=2,
        memory=memory,
        working=2048,
        prepared=1024,
        headroom=256,
        writers=1,
    )
    assert len(cpus) == workers
    assert sorted(sum(cpus, [])) == [2, 3, 4, 5]
    assert len(set(sum(cpus, []))) == 4
    assert workers * (2048 + 1024 + 256) <= memory


def test_compression_cpu_partition_and_impossible_admission():
    cpus = _worker_count(8, [0, 1, 2, 3], 4, 8, 20000, 1000, 1000, 100, 2)
    assert len(cpus) == 2 and all(len(p) >= 2 for p in cpus)
    with pytest.raises(FimUnsupportedError):
        _worker_count(1, [0], 1, 1, 100, 1000, 1000, 100, 1)


def test_sources_survive_json_roundtrip_and_detect_changes(tmp_path):
    from ras_commander.fim.RasFim import _file_identity

    path = tmp_path / "source"
    path.write_bytes(b"original")
    jobs = [
        dict(
            job_id="j",
            sources=dict(hdf=dict(path=str(path), identity=_file_identity(path))),
        )
    ]
    loaded = json.loads(json.dumps(jobs))
    _check_sources(loaded)
    path.write_bytes(b"changed source")
    with pytest.raises(RuntimeError, match="source changed"):
        _check_sources(loaded)


def test_atomic_receipt_handles_numpy_and_nonfinite_metadata(tmp_path):
    path = tmp_path / "receipt.json"
    _write_json(path, dict(integer=np.int64(2), missing=np.nan, path=Path("example")))
    assert json.loads(path.read_text()) == dict(integer=2, missing=None, path="example")
    assert not path.with_suffix(".partial").exists()


@pytest.mark.parametrize("indices", [[0, 1, 2, 3], [3, 2, 1, 0]])
def test_bounded_multitime_hdf_read_preserves_bits_and_reuses_one_block(
    tmp_path, monkeypatch, indices
):
    pytest.importorskip("ras_commander_fast_hdf")
    import h5py
    from ras_commander import fast_hdf
    from ras_commander.fim._sloping import _profile_block

    values = np.arange(4 * 128, dtype=np.float32).reshape(4, 128)
    values[0, 0] = -0.0
    path = tmp_path / "rows.hdf"
    with h5py.File(path, "w") as f:
        f.create_dataset("rows", data=values, chunks=(1, 128), compression="gzip")
    original, calls = fast_hdf.read_dataset, []

    def tracked(*args, **kwargs):
        calls.append(args[1])
        return original(*args, **kwargs)

    monkeypatch.setattr(fast_hdf, "read_dataset", tracked)
    cache = {}
    with h5py.File(path) as f:
        for position, time in enumerate(indices):
            actual = _profile_block(
                f["rows"], time, 0, 128, indices[position:], cache, values.nbytes
            )
            np.testing.assert_array_equal(actual.view("u4"), values[time].view("u4"))
        assert len(calls) == 1
        assert sum(v[1].nbytes for v in cache.values()) <= values.nbytes


def test_invalid_catalog_controls_fail_without_outputs(tmp_path):
    from ras_commander import RasFim

    with pytest.raises(ValueError):
        RasFim.map_catalog([], tmp_path / "unused", max_workers=0)
    assert not (tmp_path / "unused").exists()
