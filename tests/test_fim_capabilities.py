"""Synthetic registry contracts; no engine/model/runtime installation is required."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ras_commander.fim import FimCapabilities, FimMethodSupport, RasFim
from ras_commander.fim import _capabilities
from ras_commander.fim.errors import FimEngineError, FimEngineNotFoundError


def _entry(**updates):
    result = {
        "key": "sloping", "method_id": "sloping/1",
        "request_schemas": ["sloping-request/1"], "cli_command": "sloping",
        "api_contract": "stable", "intended_use": "mapping",
        "numerical_qualification": {
            "status": "scoped", "native_version": "6.6",
            "scope": "bounded fixture", "flags": {"fixture": ["sample"]},
        },
        "flags": {"method_id": "sloping/1", "velocity": True, "disabled": False,
                  "controls": {"modes": ["one"]}},
    }
    result.update(updates)
    return result


def _record(entry=None):
    entry = _entry() if entry is None else entry
    return {
        "engine": {"version": "0.13.0", "source_commit": "abc123"},
        "capabilities_schema": _capabilities.CAPABILITIES_SCHEMA,
        "capabilities": [entry], entry["key"]: deepcopy(entry["flags"]),
    }


def _discover(monkeypatch, record):
    monkeypatch.setattr(_capabilities._engine, "find_engine", lambda path=None: Path("engine.exe"))
    monkeypatch.setattr(_capabilities._engine, "engine_method", lambda path: record)
    return _capabilities.get_capabilities()


def test_structured_discovery_preserves_identity_and_flags(monkeypatch):
    capabilities = _discover(monkeypatch, _record())
    assert isinstance(capabilities, FimCapabilities)
    assert capabilities.engine_path == Path("engine.exe")
    assert capabilities.engine_version == "0.13.0"
    assert capabilities.source_commit == "abc123"
    method = capabilities.methods["sloping"]
    assert isinstance(method, FimMethodSupport)
    assert method.method_id == "sloping/1"
    assert method.request_schemas == ("sloping-request/1",)
    assert method.cli_command == "sloping"
    assert method.qualification_status == "scoped"
    assert method.qualified_scope == ("bounded fixture",)
    assert capabilities.supports("sloping")
    assert capabilities.supports("sloping", flag="velocity")
    assert capabilities.supports("sloping", flag="controls")
    assert not capabilities.supports("sloping", flag="disabled")
    assert not capabilities.supports("sloping", flag="unknown")
    assert not capabilities.supports("unknown")


def test_snapshot_deeply_copies_and_freezes_all_metadata(monkeypatch):
    entry = _entry(future={"nested": ["first"]})
    record = _record(entry)
    capabilities = _discover(monkeypatch, record)
    method = capabilities.methods["sloping"]
    entry["flags"]["controls"]["modes"].append("later")
    entry["future"]["nested"].append("later")
    record["engine"]["version"] = "changed"
    assert method.flags["controls"]["modes"] == ("one",)
    assert method.metadata["future"]["nested"] == ("first",)
    assert capabilities.raw_record["engine"]["version"] == "0.13.0"
    with pytest.raises(TypeError):
        capabilities.methods["new"] = method
    with pytest.raises(TypeError):
        method.flags["controls"]["new"] = True
    with pytest.raises(TypeError):
        method.numerical_qualification["flags"]["fixture"][0] = "changed"
    with pytest.raises(FrozenInstanceError):
        method.api_contract = "experimental"


def test_legacy_normalizes_version_but_never_infers_qualification(monkeypatch):
    record = {
        "step05_r2": {"method_version": "step05/2", "experimental": False,
                      "qualified": "Some free-form prose", "request_schema": "request/2"},
        "sloping": {"velocity": True},
        "future_method": {"method_id": "future/1", "experimental": True},
        "future_metadata": {"description": "not a method"},
    }
    capabilities = _discover(monkeypatch, record)
    assert capabilities.engine_version is None
    assert capabilities.source_commit is None
    assert capabilities.capabilities_schema is None
    method = capabilities.methods["step05_r2"]
    assert method.method_id == "step05/2"
    assert method.request_schemas == ("request/2",)
    assert method.api_contract == "not_declared"
    assert method.qualification_status == "not_declared"
    assert capabilities.methods["sloping"].method_id is None
    assert capabilities.supports("sloping", flag="velocity")
    assert capabilities.methods["future_method"].api_contract == "not_declared"
    assert "future_metadata" not in capabilities.methods


def test_legacy_preserves_explicit_unqualified_and_scoped_metadata(monkeypatch):
    capabilities = _discover(monkeypatch, {
        "one_d_diagnostic": {"native_parity_qualified": False, "experimental": True,
                             "native_version_qualified": "6.6"},
        "sloping": {"qualification_scope": ["fixture A", "fixture B"]},
    })
    assert capabilities.methods["one_d_diagnostic"].qualification_status == "unqualified"
    assert capabilities.supports("one_d_diagnostic")
    assert capabilities.methods["sloping"].qualified_scope == ("fixture A", "fixture B")


@pytest.mark.parametrize("field", sorted(_capabilities._ENTRY_FIELDS))
def test_structured_block_missing_fields_is_not_legacy_fallback(monkeypatch, field):
    record = _record()
    del record["capabilities"][0][field]
    with pytest.raises(FimEngineError):
        _discover(monkeypatch, record)


@pytest.mark.parametrize(("field", "value"), [
    ("key", []), ("method_id", None), ("cli_command", 2),
    ("request_schemas", "schema/1"), ("request_schemas", [2]),
    ("request_schemas", ["a", "a"]), ("api_contract", []),
    ("api_contract", "unknown"), ("intended_use", {}),
    ("numerical_qualification", []), ("numerical_qualification", {}),
    ("numerical_qualification", {"status": []}),
    ("numerical_qualification", {"status": {}}),
    ("numerical_qualification", {"status": "qualified"}), ("flags", []),
])
def test_structured_block_wrong_types_raise_engine_error(monkeypatch, field, value):
    record = _record()
    record["capabilities"][0][field] = value
    with pytest.raises(FimEngineError):
        _discover(monkeypatch, record)


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(capabilities_schema="future/2"),
    lambda r: r.pop("capabilities_schema"),
    lambda r: r.pop("capabilities"),
    lambda r: r.update(capabilities={}),
    lambda r: r["capabilities"].append(deepcopy(r["capabilities"][0])),
    lambda r: r.update(engine=[]),
    lambda r: r["engine"].update(version=[]),
    lambda r: r["sloping"].update(velocity=False),
])
def test_malformed_structured_root_and_contradictions_refused(monkeypatch, mutate):
    record = _record()
    mutate(record)
    with pytest.raises(FimEngineError):
        _discover(monkeypatch, record)


def test_structured_qualification_cannot_override_explicit_refusal(monkeypatch):
    entry = _entry()
    entry["flags"]["native_parity_qualified"] = False
    with pytest.raises(FimEngineError, match="contradicts"):
        _discover(monkeypatch, _record(entry))
    entry["numerical_qualification"]["status"] = "unqualified"
    capabilities = _discover(monkeypatch, _record(entry))
    assert capabilities.supports("sloping")
    assert capabilities.methods["sloping"].api_contract == "stable"
    assert capabilities.methods["sloping"].qualification_status == "unqualified"


def test_public_wrapper_and_support_helpers_use_typed_discovery(monkeypatch):
    record = {key: {"storage_area_surfaces": RasFim.STORAGE_AREA_METHOD}
              for key in ("sloping", "horizontal", "whole_simulation")}
    record["effective_terrain"] = {"method_id": "rasmapper-effective-terrain/1"}
    capabilities = _discover(monkeypatch, record)
    assert isinstance(RasFim.get_capabilities("requested.exe"), FimCapabilities)
    monkeypatch.setattr(RasFim, "get_capabilities", lambda path=None: capabilities)
    assert RasFim.supports_storage_areas()
    assert RasFim.supports_effective_terrain()


@pytest.mark.parametrize("error", [FimEngineNotFoundError("missing"), FileNotFoundError("missing")])
def test_helpers_return_false_only_for_missing_engine(monkeypatch, error):
    def fail(path=None):
        raise error
    monkeypatch.setattr(_capabilities._engine, "find_engine", fail)
    with pytest.raises(type(error)):
        RasFim.get_capabilities()
    assert not RasFim.supports_storage_areas()
    assert not RasFim.supports_effective_terrain()


def test_broken_engine_fault_propagates_through_public_helpers(monkeypatch):
    error = FimEngineError("engine returned malformed JSON")
    monkeypatch.setattr(_capabilities._engine, "find_engine", lambda path=None: Path("engine.exe"))
    def fail(path):
        raise error
    monkeypatch.setattr(_capabilities._engine, "engine_method", fail)
    for operation in (RasFim.get_capabilities, RasFim.supports_storage_areas,
                      RasFim.supports_effective_terrain):
        with pytest.raises(FimEngineError) as caught:
            operation()
        assert caught.value is error
