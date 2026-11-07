"""Backend and flexible-input contracts for lossless 1D preparation reads."""
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from ras_commander import HdfXsec, fast_hdf
from test_fim_one_d import files  # noqa: F401 - shared synthetic HDF fixture


def _equal(actual, expected):
    assert actual.keys() == expected.keys()
    for key in expected:
        if isinstance(expected[key], np.ndarray):
            assert actual[key].dtype == expected[key].dtype
            assert actual[key].tobytes() == expected[key].tobytes()
        elif key == "levels":
            assert len(actual[key]) == len(expected[key])
            for a, b in zip(actual[key], expected[key]):
                assert a.dtype == b.dtype and a.tobytes() == b.tobytes()
        else:
            assert actual[key] == expected[key]


def test_open_handle_and_geometry_only_preserve_arrays(files, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "python")
    expected = HdfXsec.get_one_d_mapping_inputs(str(files[0]), profiles=[])
    with h5py.File(files[0], "r") as source:
        actual = HdfXsec.get_one_d_mapping_inputs(source, profiles=[])
        assert source.id.valid
    _equal(actual, expected)
    assert actual["levels"] == []


def test_auto_native_failure_preserves_python_and_required_raises(files, monkeypatch):
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "python")
    expected = HdfXsec.get_one_d_mapping_inputs(files[0], profiles=[1, "Max", 1])

    def broken(*args, **kwargs):
        raise RuntimeError("injected native 1D reader failure")

    monkeypatch.setattr(fast_hdf, "_native", lambda mode: None if mode == "python" else
                        SimpleNamespace(read_xs_geometry=broken))
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "auto")
    _equal(HdfXsec.get_one_d_mapping_inputs(files[0], profiles=[1, "Max", 1]), expected)
    monkeypatch.setenv("RAS_COMMANDER_FAST_HDF", "required")
    with pytest.raises(fast_hdf.FastHdfError):
        HdfXsec.get_one_d_mapping_inputs(files[0], profiles=[1, "Max", 1])
