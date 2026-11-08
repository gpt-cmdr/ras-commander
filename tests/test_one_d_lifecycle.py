"""Preparation retry and failure-policy contracts for canonical 1D mapping."""
import json
from pathlib import Path

import h5py
import pytest
from pyproj.exceptions import CRSError

from ras_commander.fim import FimPreparedOneDModel, FimUnsupportedError, RasFim
from ras_commander.fim import _engine, _one_d
from test_fim_one_d import files  # noqa: F401 - shared synthetic HDF fixture


@pytest.mark.parametrize("existing", [False, True])
def test_preparation_write_failure_cleans_owned_files_and_allows_retry(files, tmp_path, monkeypatch, existing):
    output = tmp_path / "prepared"
    if existing:
        output.mkdir()
    original = _one_d.write_json

    def fail(path, value):
        Path(str(path) + ".partial").write_text("partial")
        raise OSError("forced preparation write failure")

    monkeypatch.setattr(_one_d, "write_json", fail)
    with pytest.raises(OSError, match="forced preparation"):
        RasFim.prepare_one_d_model(*files, output, allow_unqualified=True)
    if existing:
        assert output.is_dir() and not list(output.iterdir())
    else:
        assert not output.exists()
    monkeypatch.setattr(_one_d, "write_json", original)
    assert RasFim.prepare_one_d_model(*files, output, allow_unqualified=True).validate()


def test_preparation_cleanup_does_not_remove_unowned_files(files, tmp_path, monkeypatch):
    output = tmp_path / "prepared"

    def fail(path, value):
        (output / "other-call.txt").write_text("preserve")
        raise OSError("forced preparation failure")

    monkeypatch.setattr(_one_d, "write_json", fail)
    with pytest.raises(OSError, match="forced preparation"):
        RasFim.prepare_one_d_model(*files, output, allow_unqualified=True)
    assert [path.name for path in output.iterdir()] == ["other-call.txt"]
    assert (output / "other-call.txt").read_text() == "preserve"


def test_preparation_body_error_is_not_replaced_by_later_hash_error(files, tmp_path, monkeypatch):
    original = _one_d.digest
    source_paths = {Path(path).resolve() for path in files}
    source_calls = 0

    def digest(path):
        nonlocal source_calls
        if Path(path).resolve() in source_paths:
            source_calls += 1
            if source_calls > 2:
                raise RuntimeError("secondary source hash failure")
        return original(path)

    def fail(path, value):
        raise OSError("primary preparation failure")

    monkeypatch.setattr(_one_d, "digest", digest)
    monkeypatch.setattr(_one_d, "write_json", fail)
    with pytest.raises(OSError, match="primary preparation failure"):
        RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    assert source_calls == 2


def test_missing_model_projection_is_supported_scope_error(files, tmp_path):
    with h5py.File(files[0], "a") as source:
        del source.attrs["Projection"]
    with pytest.raises(FimUnsupportedError, match="CRS") as error:
        RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    assert isinstance(error.value.__cause__, CRSError)
    assert not (tmp_path / "prepared").exists()


def test_invalid_reconstructed_projection_is_scope_error(files, tmp_path):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    receipt = prepared.receipt
    receipt["grid"]["crs"] = "invalid projection"
    (prepared.folder / "one_d_preparation.json").write_text(json.dumps(receipt))
    with pytest.raises(FimUnsupportedError) as error:
        FimPreparedOneDModel(prepared.folder).validate()
    assert isinstance(error.value.__cause__, CRSError)


def _failing_engine(monkeypatch, tmp_path, failure):
    executable = tmp_path / "fake-engine.exe"
    executable.write_bytes(b"fake engine")
    monkeypatch.setattr(_engine, "find_engine", lambda path=None: executable)
    monkeypatch.setattr(_engine, "engine_method", lambda path: {
        "one_d_clipped_diagnostic": {"method_id": _one_d.METHOD_ID},
    })

    def run(args, what, timeout=None):
        raise failure

    monkeypatch.setattr(_engine, "run_engine", run)


def test_failure_manifest_can_be_returned_without_raising(files, tmp_path, monkeypatch):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    _failing_engine(monkeypatch, tmp_path, OSError("engine execution failed"))
    output = tmp_path / "mapped"
    result = prepared.map_profiles(output, bbox=(0, 0, 10, 10), allow_unqualified=True,
                                   raise_on_failure=False)
    assert result.status.tolist() == ["failed"]
    assert "engine execution failed" in result.iloc[0].error
    assert not list(output.glob("*.tif"))
    document = json.loads((output / "fim_manifest.json").read_text())
    assert document["status"] == "failed"


def test_interrupt_survives_failure_manifest_write_error(files, tmp_path, monkeypatch):
    prepared = RasFim.prepare_one_d_model(*files, tmp_path / "prepared", allow_unqualified=True)
    interrupt = KeyboardInterrupt("cancel mapping")
    _failing_engine(monkeypatch, tmp_path, interrupt)
    original = RasFim._write_manifest

    def write(folder, manifest, details):
        if details["status"] == "failed":
            raise OSError("cannot persist failure receipt")
        return original(folder, manifest, details)

    monkeypatch.setattr(RasFim, "_write_manifest", write)
    with pytest.raises(KeyboardInterrupt, match="cancel mapping") as error:
        prepared.map_profiles(tmp_path / "mapped", bbox=(0, 0, 10, 10),
                              allow_unqualified=True, raise_on_failure=False)
    assert error.value is interrupt


def test_raise_on_failure_requires_boolean_before_engine_lookup(monkeypatch, tmp_path):
    def unexpected(*args, **kwargs):
        pytest.fail("engine must not be queried for invalid controls")
    monkeypatch.setattr(_engine, "find_engine", unexpected)
    with pytest.raises(ValueError, match="raise_on_failure"):
        _one_d.map_one_d_profiles("missing", "missing", tmp_path / "out",
                                  allow_unqualified=True, raise_on_failure=0)
