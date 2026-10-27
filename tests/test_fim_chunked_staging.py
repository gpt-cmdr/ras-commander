"""Native HDF staging bounds, bit preservation and partial-file cleanup."""
import h5py
import numpy as np
import pytest

from ras_commander.fim._sloping import _stage_profiles


def test_max_staging_reads_bounded_native_slabs_and_preserves_bits(tmp_path, monkeypatch):
    from ras_commander import fast_hdf

    values = np.linspace(-23, 41, 103, dtype="float32")
    values[5] = -0.0
    source = tmp_path / "source.hdf"
    with h5py.File(source, "w") as handle:
        handle["maximum"] = np.stack([values, values])
    calls = []
    read = fast_hdf.read_dataset

    def bounded(dataset, selection, **options):
        calls.append(selection)
        assert options["backend"] == "rust"
        assert selection[1].stop - selection[1].start <= 8
        return read(dataset, selection, **options)

    monkeypatch.setattr(fast_hdf, "read_dataset", bounded)
    units, views, size = _stage_profiles(source, tmp_path, [{"mesh_name": "mesh", "cell_count": len(values)}], [{"dataset": "/maximum"}], {"max": "Max", "alias": "Max"}, deduplicate=True, chunk_bytes=32)
    actual = np.fromfile(tmp_path / units[0]["values_files"][0], dtype="<f4")
    np.testing.assert_array_equal(actual.view("u4"), values.view("u4"))
    assert len(calls) == 13 and size == values.nbytes and views == 0
    assert units[0]["values_files"] == units[1]["values_files"]


def test_staging_admits_before_read_and_cleans_invalid_partial(tmp_path, monkeypatch):
    from ras_commander import fast_hdf
    from ras_commander.fim.errors import FimUnsupportedError

    source = tmp_path / "source.hdf"
    with h5py.File(source, "w") as handle:
        handle["maximum"] = np.array([[1, 2, np.nan], [0, 0, 0]], dtype="float32")
    args = (source, tmp_path, [{"mesh_name": "mesh", "cell_count": 3}], [{"dataset": "/maximum"}], {"max": "Max"})
    read = fast_hdf.read_dataset
    monkeypatch.setattr(fast_hdf, "read_dataset", lambda *a, **k: pytest.fail("read before admission"))
    with pytest.raises(FimUnsupportedError):
        _stage_profiles(*args, max_staged_bytes=11)
    monkeypatch.setattr(fast_hdf, "read_dataset", read)
    with pytest.raises(ValueError, match="Invalid complete cell profile"):
        _stage_profiles(*args, chunk_bytes=4)
    assert not list(tmp_path.glob("values-*"))
