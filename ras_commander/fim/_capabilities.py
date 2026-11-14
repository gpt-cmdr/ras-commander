"""Typed, immutable discovery of advertised mapping-engine contracts.

Availability, API stability and numerical qualification are separate facts.
Discovery never executes a map or converts an engine fault into a missing feature.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Optional, Tuple, Union

from ..Decorators import log_call
from . import _engine
from .errors import FimEngineError

CAPABILITIES_SCHEMA = "ras-commander-fast-map-capabilities/1"
_CONTRACTS = {"stable", "experimental", "deprecated"}
_USES = {"diagnostic", "mapping", "terrain", "reduction"}
_QUALIFICATION = {"unqualified", "scoped", "not_declared"}
_LEGACY_METHODS = {
    "coupled_diagnostic", "coupled_storage_diagnostic", "one_d_diagnostic",
    "one_d_native_diagnostic", "one_d_clipped_diagnostic", "batch_session_r1",
    "step05_r2", "horizontal", "sloping", "depth_groups", "boundary",
    "whole_simulation", "effective_terrain",
}
_ENTRY_FIELDS = {
    "key", "method_id", "request_schemas", "cli_command", "api_contract",
    "intended_use", "numerical_qualification", "flags",
}


def _freeze(value: Any) -> Any:
    """Copy JSON data recursively, leaving no mutable aliases in the snapshot."""
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise FimEngineError("Capability object keys must be strings")
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise FimEngineError("Capabilities must contain finite JSON-compatible values")


def _text(value: Any, name: str, *, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FimEngineError(f"Capability {name} must be a nonempty string")
    return value


def _schemas(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise FimEngineError(f"Capability {name} must be an array of schema strings")
    result = tuple(_text(item, name) for item in value)
    if len(set(result)) != len(result):
        raise FimEngineError(f"Capability {name} contains duplicate schemas")
    return result


@dataclass(frozen=True)
class FimMethodSupport:
    """An advertised method; its presence does not establish native parity.

    Legacy engines can omit a method ID, CLI/schema declarations or stability.
    Such fields remain ``None``/empty/``not_declared`` rather than being guessed.
    All nested metadata is copied into read-only mappings and tuples.
    """

    key: str
    method_id: Optional[str]
    request_schemas: Tuple[str, ...]
    cli_command: Optional[str]
    api_contract: str
    intended_use: str
    numerical_qualification: Mapping[str, Any]
    flags: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        _text(self.key, "key")
        _text(self.method_id, "method_id", optional=True)
        _text(self.cli_command, "cli_command", optional=True)
        contract = _text(self.api_contract, "api_contract")
        intended_use = _text(self.intended_use, "intended_use")
        if contract not in _CONTRACTS | {"not_declared"} or intended_use not in _USES | {"not_declared"}:
            raise FimEngineError("Capability has an unknown API contract or intended use")
        object.__setattr__(self, "request_schemas", _schemas(self.request_schemas, "request_schemas"))
        for name in ("numerical_qualification", "flags", "metadata"):
            value = getattr(self, name)
            if not isinstance(value, Mapping):
                raise FimEngineError(f"Capability {name} must be an object")
            object.__setattr__(self, name, _freeze(value))
        status = _text(self.numerical_qualification.get("status"), "numerical_qualification.status")
        if status not in _QUALIFICATION:
            raise FimEngineError("Capability has invalid numerical_qualification status")
        if self.flags.get("native_parity_qualified") is False and status != "unqualified":
            raise FimEngineError("Capability qualification contradicts native_parity_qualified=false")

    @property
    def qualification_status(self) -> str:
        """Return the explicitly normalized numerical status, independent of API stability."""
        return self.numerical_qualification["status"]

    @property
    def qualified_scope(self) -> Tuple[str, ...]:
        """Return declared textual scopes; this is not a universal qualification claim."""
        scope = self.numerical_qualification.get("scope")
        if isinstance(scope, str):
            return (scope,)
        if isinstance(scope, tuple) and all(isinstance(item, str) for item in scope):
            return scope
        return ()


@dataclass(frozen=True)
class FimCapabilities:
    """Read-only engine identity and method registry, including the untouched raw record."""

    engine_path: Path
    engine_version: Optional[str]
    source_commit: Optional[str]
    methods: Mapping[str, FimMethodSupport]
    capabilities_schema: Optional[str] = None
    raw_record: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, "engine_path", Path(self.engine_path))
        _text(self.engine_version, "engine.version", optional=True)
        _text(self.source_commit, "engine.source_commit", optional=True)
        if self.capabilities_schema is not None and self.capabilities_schema != CAPABILITIES_SCHEMA:
            raise FimEngineError("Unsupported engine capabilities_schema")
        if not isinstance(self.methods, Mapping) or any(
            not isinstance(value, FimMethodSupport) or key != value.key
            for key, value in self.methods.items()
        ):
            raise FimEngineError("Capability methods must map keys to matching FimMethodSupport values")
        object.__setattr__(self, "methods", MappingProxyType(dict(self.methods)))
        if not isinstance(self.raw_record, Mapping):
            raise FimEngineError("Capability raw_record must be an object")
        object.__setattr__(self, "raw_record", _freeze(self.raw_record))

    @log_call
    def supports(self, key: str, *, flag: Optional[str] = None) -> bool:
        """Query advertised presence or a truthy flag, without implying qualification.

        Args:
            key: Engine registry key, such as ``sloping``.
            flag: Optional field in that method's raw flags. Missing, false or
                empty flags return False; nonempty structured controls count as advertised.

        Returns:
            Whether the requested method/flag is advertised. Inspect
            ``api_contract`` and ``numerical_qualification`` separately.
        """
        _text(key, "supports key")
        _text(flag, "supports flag", optional=True)
        method = self.methods.get(key)
        return method is not None and (flag is None or bool(method.flags.get(flag)))


def _structured_method(entry: Any) -> FimMethodSupport:
    if not isinstance(entry, Mapping):
        raise FimEngineError("Each capability entry must be an object")
    missing = _ENTRY_FIELDS - entry.keys()
    if missing:
        raise FimEngineError(f"Capability entry lacks required fields: {', '.join(sorted(missing))}")
    key = _text(entry["key"], "key")
    method_id = _text(entry["method_id"], f"{key}.method_id")
    command = _text(entry["cli_command"], f"{key}.cli_command")
    contract = _text(entry["api_contract"], f"{key}.api_contract")
    intended_use = _text(entry["intended_use"], f"{key}.intended_use")
    if contract not in _CONTRACTS or intended_use not in _USES:
        raise FimEngineError(f"Capability {key} has an unknown API contract or intended use")
    qualification = entry["numerical_qualification"]
    if not isinstance(qualification, Mapping):
        raise FimEngineError(f"Capability {key} has invalid numerical_qualification status")
    status = _text(qualification.get("status"), f"{key}.numerical_qualification.status")
    if status not in _QUALIFICATION:
        raise FimEngineError(f"Capability {key} has invalid numerical_qualification status")
    return FimMethodSupport(
        key, method_id, _schemas(entry["request_schemas"], f"{key}.request_schemas"),
        command, contract, intended_use, qualification, entry["flags"],
        {name: value for name, value in entry.items() if name not in _ENTRY_FIELDS},
    )


def _legacy_method(key: str, flags: Mapping[str, Any]) -> FimMethodSupport:
    method_id = flags.get("method_id", flags.get("method_version"))
    request_schemas = flags.get("request_schemas")
    if request_schemas is None:
        schema = flags.get("request_schema")
        request_schemas = [] if schema is None else [_text(schema, f"{key}.request_schema")]
    status = "not_declared"
    if flags.get("native_parity_qualified") is False:
        status = "unqualified"
    elif flags.get("native_version_qualified") is not None or flags.get("qualification_scope") is not None:
        status = "scoped"
    qualification = {
        "status": status,
        "native_version": flags.get("native_version_qualified"),
        "scope": flags.get("qualification_scope", flags.get("scope")),
        "flags": {name: flags[name] for name in (
            "native_parity_qualified", "native_version_qualified", "qualification_scope",
            "qualified", "qualification", "unqualified_refused",
        ) if name in flags},
    }
    return FimMethodSupport(
        key, _text(method_id, f"{key}.method_id", optional=True),
        _schemas(request_schemas, f"{key}.request_schemas"),
        _text(flags.get("cli_command"), f"{key}.cli_command", optional=True),
        flags.get("api_contract", "not_declared"),
        flags.get("intended_use", "not_declared"), qualification, flags,
    )


def _parse_capabilities(engine_path: Union[str, Path], record: Any) -> FimCapabilities:
    """Validate structured discovery or conservatively normalize legacy records."""
    if not isinstance(record, Mapping):
        raise FimEngineError("Engine method registry must be an object")
    identity = record.get("engine", {})
    if not isinstance(identity, Mapping):
        raise FimEngineError("Engine identity must be an object")
    methods = {}
    schema = record.get("capabilities_schema")
    if "capabilities_schema" in record or "capabilities" in record:
        if schema != CAPABILITIES_SCHEMA:
            raise FimEngineError("Unsupported or missing engine capabilities_schema")
        entries = record.get("capabilities")
        if not isinstance(entries, list):
            raise FimEngineError("Engine capabilities must be an array")
        for entry in entries:
            method = _structured_method(entry)
            if method.key in methods:
                raise FimEngineError(f"Duplicate capability key: {method.key}")
            if method.key in record and _freeze(record[method.key]) != method.flags:
                raise FimEngineError(f"Capability flags contradict raw method record: {method.key}")
            methods[method.key] = method
    else:
        for key, flags in record.items():
            if key == "engine":
                continue
            if key in _LEGACY_METHODS and not isinstance(flags, Mapping):
                raise FimEngineError(f"Legacy capability {key} must be an object")
            if isinstance(flags, Mapping) and (key in _LEGACY_METHODS or "method_id" in flags or "method_version" in flags):
                methods[key] = _legacy_method(key, flags)
    return FimCapabilities(
        Path(engine_path), identity.get("version"), identity.get("source_commit"),
        methods, schema, record,
    )


@log_call
def get_capabilities(engine_path: Optional[Union[str, Path]] = None) -> FimCapabilities:
    """Inspect a resolved engine without mapping, installing or swallowing failures.

    Args:
        engine_path: Optional executable path; accepts strings and Path objects.

    Returns:
        An immutable typed registry. Missing legacy declarations remain unknown.

    Raises:
        FimEngineNotFoundError: The executable is missing or cannot be launched.
        FimEngineError: The engine fails or returns malformed discovery metadata.
    """
    engine = _engine.find_engine(engine_path)
    return _parse_capabilities(engine, _engine.engine_method(engine))
