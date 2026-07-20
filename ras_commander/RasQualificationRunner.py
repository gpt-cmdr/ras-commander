"""Process-isolated execution for HEC-RAS qualification operations.

The runner deliberately executes every configured operation in a fresh Python
process.  HEC-RAS, RasMapperLib, and Wine can hang or retain file locks after a
failed operation; process isolation gives each step an enforceable timeout and
lets the parent preserve a fail-closed receipt even when a child is terminated.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasQualification import ExecutorProfile, RasQualification, _json_value
from .RasUtils import RasUtils


logger = get_logger(__name__)


DEFAULT_ACTION_HANDLER = "ras_commander.RasQualificationActions:execute"


def _mapping(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Expected a mapping, got {type(value).__name__}")
    return dict(value)


def _expand_path(value: Union[str, Path]) -> Path:
    return RasUtils.safe_resolve(Path(os.path.expandvars(os.path.expanduser(str(value)))))


def _stream_evidence(text: str, tail_length: int = 8000) -> Dict[str, Any]:
    encoded = text.encode("utf-8", errors="replace")
    return {
        "length": len(text),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "tail": text[-tail_length:],
    }


@dataclass(frozen=True)
class QualificationActionSpec:
    """One real-product operation executed by the qualification runner."""

    operation_id: str
    handler: str
    timeout_seconds: int = 600
    parameters: Mapping[str, Any] = field(default_factory=dict)
    worker_runtime: str = "configured"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "QualificationActionSpec":
        data = dict(value)
        operation_id = str(data.get("id", "")).strip()
        handler = str(data.get("handler") or DEFAULT_ACTION_HANDLER).strip()
        if operation_id not in RasQualification.KNOWN_OPERATIONS:
            raise ValueError(f"Unknown qualification operation: {operation_id}")
        if ":" not in handler:
            raise ValueError(
                f"Action {operation_id} requires handler='package.module:function'"
            )
        timeout_seconds = int(data.get("timeout_seconds", 600))
        if timeout_seconds <= 0:
            raise ValueError(f"Action {operation_id} timeout_seconds must be positive")
        parameters = data.get("parameters") or {}
        if not isinstance(parameters, Mapping):
            raise TypeError(f"Action {operation_id} parameters must be a mapping")
        worker_runtime = str(data.get("worker_runtime", "configured")).lower()
        if worker_runtime not in {"configured", "native"}:
            raise ValueError(
                f"Action {operation_id} worker_runtime must be "
                "'configured' or 'native'"
            )
        return cls(
            operation_id,
            handler,
            timeout_seconds,
            dict(parameters),
            worker_runtime,
        )


@dataclass(frozen=True)
class QualificationRunConfig:
    """Serializable configuration for a native-Windows or Wine lane run."""

    profile: ExecutorProfile
    expected_version: str
    ras_executable: Path
    source_project: Path
    workspace_root: Path
    receipt_path: Path
    fixture: Mapping[str, Any]
    actions: Sequence[QualificationActionSpec]
    executor: Mapping[str, Any] = field(default_factory=dict)
    wine: Mapping[str, Any] = field(default_factory=dict)
    stop_on_failure: bool = False

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        manifest_path: Optional[Union[str, Path]] = None,
    ) -> "QualificationRunConfig":
        data = dict(value)
        profile = ExecutorProfile(str(data["profile"]))
        expected_version = RasUtils.normalize_ras_version(
            data.get("expected_version", "7.0.1")
        )
        if not expected_version:
            raise ValueError("expected_version is required")

        base = Path(manifest_path).parent if manifest_path is not None else Path.cwd()

        def resolved(name: str) -> Path:
            raw = Path(os.path.expandvars(os.path.expanduser(str(data[name]))))
            if not raw.is_absolute():
                raw = base / raw
            return _expand_path(raw)

        fixture = _mapping(data.get("fixture") or {})
        if not fixture.get("id"):
            raise ValueError("fixture.id is required")
        actions = tuple(
            QualificationActionSpec.from_mapping(item)
            for item in data.get("actions", [])
        )
        duplicates = [
            operation_id
            for operation_id in {item.operation_id for item in actions}
            if sum(item.operation_id == operation_id for item in actions) > 1
        ]
        if duplicates:
            raise ValueError(f"Duplicate action specifications: {sorted(duplicates)}")

        executor = _mapping(data.get("executor") or {})
        worker_command = executor.get("worker_command")
        if worker_command is not None and (
            isinstance(worker_command, (str, bytes))
            or not isinstance(worker_command, Sequence)
            or not worker_command
        ):
            raise TypeError("executor.worker_command must be a nonempty JSON array")
        path_mode = str(executor.get("payload_path_mode", "native")).lower()
        if path_mode not in {"native", "wine"}:
            raise ValueError("executor.payload_path_mode must be 'native' or 'wine'")
        executor["payload_path_mode"] = path_mode
        if worker_command is not None:
            executor["worker_command"] = [str(item) for item in worker_command]

        wine = _mapping(data.get("wine") or {})
        if profile == ExecutorProfile.LINUX_WINE_WINDOWS_RAS:
            if not executor.get("worker_command"):
                raise ValueError(
                    "Wine qualification requires executor.worker_command for a "
                    "Wine-hosted Windows Python worker"
                )
            if path_mode != "wine":
                raise ValueError(
                    "Wine qualification requires executor.payload_path_mode='wine'"
                )

        return cls(
            profile=profile,
            expected_version=expected_version,
            ras_executable=resolved("ras_executable"),
            source_project=resolved("source_project"),
            workspace_root=resolved("workspace_root"),
            receipt_path=resolved("receipt_path"),
            fixture=fixture,
            actions=actions,
            executor=executor,
            wine=wine,
            stop_on_failure=bool(data.get("stop_on_failure", False)),
        )

    @classmethod
    def from_json(cls, manifest_path: Union[str, Path]) -> "QualificationRunConfig":
        path = Path(manifest_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != RasQualification.SCHEMA_VERSION:
            raise ValueError(
                f"Manifest schema_version must be {RasQualification.SCHEMA_VERSION}"
            )
        return cls.from_mapping(data, manifest_path=path)


class RasQualificationRunner:
    """Execute and checkpoint a fail-closed qualification receipt."""

    def __init__(self, config: QualificationRunConfig):
        self.config = config
        self.action_specs = {item.operation_id: item for item in config.actions}
        self.run_directory = config.receipt_path.parent / (
            f"{config.receipt_path.stem}-run"
        )
        self.run_directory.mkdir(parents=True, exist_ok=True)
        self.logs_directory = self.run_directory / "operation-logs"
        self.logs_directory.mkdir(parents=True, exist_ok=True)
        self.context_path = self.run_directory / "context.json"
        self.context: Dict[str, Any] = {}
        self.receipt: Dict[str, Any] = {}
        self._wine_to_worker_cache: Dict[str, str] = {}
        self._wine_to_host_cache: Dict[str, str] = {}

    @staticmethod
    def _prepare_wine_gdal_bridge(
        prefix: Path,
        active_ras_executable: Path,
        python_site_packages: Union[str, Path],
    ) -> Dict[str, Any]:
        """Create a prefix-relative application GDAL link for RasMapperLib."""
        site_packages_relative = Path(str(python_site_packages))
        if site_packages_relative.is_absolute():
            raise ValueError("wine.python_site_packages must be prefix-relative")
        python_dir = prefix / site_packages_relative.parent.parent
        gdal_source = active_ras_executable.parent / "GDAL"
        gdal_link = python_dir / "GDAL"
        required = (
            gdal_source / "bin64",
            gdal_source / "common" / "data",
        )
        if not all(path.is_dir() for path in required):
            raise FileNotFoundError(
                "The isolated HEC-RAS installation has no usable GDAL tree: "
                f"{gdal_source}"
            )

        prefix_resolved = prefix.resolve(strict=False)
        if gdal_link.is_symlink():
            resolved = gdal_link.resolve(strict=False)
            if not resolved.is_relative_to(prefix_resolved):
                gdal_link.unlink()
        elif gdal_link.exists() and not (
            (gdal_link / "bin64").is_dir()
            and (gdal_link / "common" / "data").is_dir()
        ):
            raise RuntimeError(
                "Refusing to replace a non-usable, non-link GDAL path in the "
                f"isolated Wine prefix: {gdal_link}"
            )

        if not gdal_link.exists():
            python_dir.mkdir(parents=True, exist_ok=True)
            relative_target = Path(os.path.relpath(gdal_source, python_dir))
            gdal_link.symlink_to(relative_target, target_is_directory=True)

        usable = bool(
            (gdal_link / "bin64").is_dir()
            and (gdal_link / "common" / "data").is_dir()
        )
        resolved_target = gdal_link.resolve(strict=False)
        target_within_prefix = resolved_target.is_relative_to(prefix_resolved)
        if not usable or not target_within_prefix:
            raise RuntimeError(
                "Wine GDAL bridge is not usable and isolated within the task "
                f"prefix: {gdal_link} -> {resolved_target}"
            )
        return {
            "path": str(gdal_link),
            "resolved_target": str(resolved_target),
            "relative_link": gdal_link.is_symlink()
            and not Path(os.readlink(gdal_link)).is_absolute(),
            "target_within_prefix": target_within_prefix,
            "usable": usable,
        }

    @staticmethod
    def _package_tree_fingerprint(root: Path) -> tuple[str, int]:
        """Fingerprint importable package files while ignoring bytecode caches."""
        digest = hashlib.sha256()
        files = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ]
        for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\x00")
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            digest.update(b"\x00")
        return digest.hexdigest(), len(files)

    @classmethod
    def _synchronize_wine_worker_package(
        cls,
        prefix: Path,
        python_site_packages: Union[str, Path],
    ) -> Dict[str, Any]:
        """Install the running ras-commander revision into an isolated prefix."""
        site_packages_relative = Path(str(python_site_packages))
        if site_packages_relative.is_absolute():
            raise ValueError("wine.python_site_packages must be prefix-relative")

        source = Path(__file__).resolve().parent
        destination = prefix / site_packages_relative / source.name
        prefix_resolved = prefix.resolve(strict=True)
        destination_parent = destination.parent.resolve(strict=False)
        if not destination_parent.is_relative_to(prefix_resolved):
            raise RuntimeError(
                "Refusing to synchronize the Wine worker package outside the "
                f"isolated prefix: {destination}"
            )

        source_fingerprint, source_file_count = cls._package_tree_fingerprint(source)
        same_location = source.resolve(strict=True) == destination.resolve(strict=False)
        if not same_location:
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(
                source,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
        destination_fingerprint, destination_file_count = (
            cls._package_tree_fingerprint(destination)
        )
        matched = bool(
            source_fingerprint == destination_fingerprint
            and source_file_count == destination_file_count
        )
        if not matched:
            raise RuntimeError(
                "The isolated Wine worker package does not match the running "
                "ras-commander revision"
            )
        return {
            "source": str(source),
            "destination": str(destination),
            "source_fingerprint": source_fingerprint,
            "destination_fingerprint": destination_fingerprint,
            "source_file_count": source_file_count,
            "destination_file_count": destination_file_count,
            "matched": matched,
            "same_location": same_location,
        }

    def _worker_environment(self, *, native_worker: bool = False) -> Dict[str, str]:
        environment = os.environ.copy()
        if native_worker or (
            self.config.executor.get("payload_path_mode", "native") != "wine"
        ):
            package_root = str(Path(__file__).resolve().parent.parent)
            existing_pythonpath = environment.get("PYTHONPATH", "")
            pythonpath_entries = [
                entry for entry in existing_pythonpath.split(os.pathsep) if entry
            ]
            if package_root not in pythonpath_entries:
                pythonpath_entries.insert(0, package_root)
            environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
        configured = self.config.executor.get("environment") or {}
        if not isinstance(configured, Mapping):
            raise TypeError("executor.environment must be a mapping")
        if self.context.get("wine_prefix"):
            environment.update(
                {
                    "WINEPREFIX": str(self.context["wine_prefix"]),
                    "WINEARCH": "win64",
                    "WINEDEBUG": str(self.config.wine.get("winedebug", "-all")),
                }
            )
            dll_overrides = self.config.wine.get(
                "dll_overrides", "winemenubuilder.exe=d;winedbg.exe=d"
            )
            if dll_overrides:
                environment["WINEDLLOVERRIDES"] = str(dll_overrides)
            wine_executable = self.config.wine.get("wine_executable")
            if wine_executable:
                environment["RAS_COMMANDER_WINE_EXECUTABLE"] = str(
                    wine_executable
                )
            winepath_executable = self.config.executor.get(
                "winepath_executable"
            )
            if winepath_executable:
                environment["RAS_COMMANDER_WINEPATH_EXECUTABLE"] = str(
                    winepath_executable
                )
        environment.update(
            {
                str(key): os.path.expandvars(str(value))
                for key, value in configured.items()
            }
        )
        return environment

    def _winepath_executable(self) -> str:
        configured = self.config.executor.get("winepath_executable")
        if configured:
            return str(configured)
        command = self.config.executor.get("worker_command") or []
        if command:
            candidate = Path(str(command[0]))
            if candidate.parent != Path(".") or candidate.is_absolute():
                sibling = candidate.with_name("winepath")
                if sibling.exists():
                    return str(sibling)
        return "winepath"

    def _winepath(self, value: str, direction: str) -> str:
        cache = (
            self._wine_to_worker_cache
            if direction == "-w"
            else self._wine_to_host_cache
        )
        if value in cache:
            return cache[value]
        process = subprocess.run(
            [self._winepath_executable(), direction, value],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=self._worker_environment(),
            check=False,
        )
        if process.returncode != 0 or not process.stdout.strip():
            raise RuntimeError(
                f"winepath {direction} failed for {value}: "
                f"{(process.stderr or process.stdout).strip()}"
            )
        converted = process.stdout.strip().splitlines()[-1]
        cache[value] = converted
        return converted

    def _to_worker_paths(self, value: Any) -> Any:
        if self.config.executor.get("payload_path_mode", "native") != "wine":
            return value
        if isinstance(value, Mapping):
            return {str(key): self._to_worker_paths(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_worker_paths(item) for item in value]
        if isinstance(value, tuple):
            return [self._to_worker_paths(item) for item in value]
        if isinstance(value, str) and Path(value).is_absolute():
            return self._winepath(value, "-w")
        return value

    def _to_host_paths(self, value: Any) -> Any:
        if self.config.executor.get("payload_path_mode", "native") != "wine":
            return value
        if isinstance(value, Mapping):
            return {str(key): self._to_host_paths(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_host_paths(item) for item in value]
        if isinstance(value, str) and re.match(r"^[A-Za-z]:[\\/]", value):
            return self._winepath(value, "-u")
        return value

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Could not terminate qualification process tree %s: %s", process.pid, exc)
            try:
                process.kill()
            except OSError:
                pass

    def _write_context(self) -> None:
        self.context_path.write_text(
            json.dumps(_json_value(self.context), indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )

    def _checkpoint(self) -> None:
        self._write_context()
        RasQualification.write_receipt(self.receipt, self.config.receipt_path)

    def _prepare(self) -> None:
        installation = RasQualification.inspect_installation(
            self.config.ras_executable,
            expected_version=self.config.expected_version,
        )
        source_fingerprint = RasQualification.project_tree_fingerprint(
            self.config.source_project
        )
        fixture = dict(self.config.fixture)
        configured_fingerprint = fixture.get("source_fingerprint")
        if configured_fingerprint and configured_fingerprint != source_fingerprint:
            raise RuntimeError(
                "Configured fixture.source_fingerprint does not match source project: "
                f"{configured_fingerprint} != {source_fingerprint}"
            )
        fixture["source_fingerprint"] = source_fingerprint

        wine_prefix_receipt = None
        stage_root = self.config.workspace_root
        active_ras_executable = self.config.ras_executable
        if self.config.profile == ExecutorProfile.LINUX_WINE_WINDOWS_RAS:
            wine_binary = str(self.config.wine.get("wine_executable", "wine"))
            prefix_root_value = self.config.wine.get(
                "prefix_root", self.config.workspace_root / "wine-prefixes"
            )
            prefix_root = _expand_path(prefix_root_value)
            template_value = self.config.wine.get("template_prefix")
            template_prefix = (
                _expand_path(template_value) if template_value is not None else None
            )
            if template_prefix is None:
                raise ValueError(
                    "Wine qualification requires wine.template_prefix so the "
                    "qualified installation can be cloned per task"
                )
            initialize_value = self.config.wine.get("initialize")
            initialize_prefix = (
                bool(initialize_value)
                if initialize_value is not None
                else template_prefix is None
            )
            wine_prefix_receipt = RasQualification.create_isolated_wine_prefix(
                prefix_root,
                task_id=f"{fixture['id']}-{self.config.profile.value}",
                wine_executable=wine_binary,
                initialize=initialize_prefix,
                timeout=int(self.config.wine.get("timeout_seconds", 600)),
                display=self.config.wine.get("display"),
                template_prefix=template_prefix,
                wineboot_dll_overrides=self.config.wine.get(
                    "wineboot_dll_overrides", "winemenubuilder.exe=d"
                ),
            )
            try:
                executable_relative = self.config.ras_executable.relative_to(
                    template_prefix
                )
            except ValueError as exc:
                raise ValueError(
                    "Wine ras_executable must be inside wine.template_prefix; "
                    "workers may not execute the shared template installation"
                ) from exc
            active_ras_executable = (
                Path(wine_prefix_receipt["prefix"]) / executable_relative
            )
            isolated_installation = RasQualification.inspect_installation(
                active_ras_executable,
                expected_version=self.config.expected_version,
            )
            template_components = installation.get("components") or {}
            isolated_components = isolated_installation.get("components") or {}
            component_hashes_match = bool(template_components) and all(
                isinstance(template_components.get(name), Mapping)
                and isinstance(isolated_components.get(name), Mapping)
                and template_components[name].get("sha256")
                == isolated_components[name].get("sha256")
                for name in template_components
            )
            isolated_identity_matches = bool(
                isolated_installation.get("version_matches")
                and isolated_installation.get("required_components_present")
                and component_hashes_match
            )
            expected_runtime_packages = self.config.wine.get("runtime_packages")
            runtime_packages = None
            runtime_packages_match = True
            site_packages_value = self.config.wine.get("python_site_packages")
            worker_package_sync = None
            if bool(self.config.wine.get("sync_current_package", True)):
                if not site_packages_value:
                    raise ValueError(
                        "wine.python_site_packages is required when "
                        "wine.sync_current_package is enabled"
                    )
                worker_package_sync = self._synchronize_wine_worker_package(
                    Path(wine_prefix_receipt["prefix"]),
                    site_packages_value,
                )
            if expected_runtime_packages is not None:
                if not isinstance(expected_runtime_packages, Mapping):
                    raise TypeError("wine.runtime_packages must be a mapping")
                site_packages_value = self.config.wine.get("python_site_packages")
                if not site_packages_value:
                    raise ValueError(
                        "wine.python_site_packages is required when "
                        "wine.runtime_packages is configured"
                    )
                site_packages_relative = Path(str(site_packages_value))
                if site_packages_relative.is_absolute():
                    raise ValueError("wine.python_site_packages must be prefix-relative")
                runtime_packages = RasQualification.inspect_python_packages(
                    Path(wine_prefix_receipt["prefix"]) / site_packages_relative,
                    expected_runtime_packages,
                )
                runtime_packages_match = bool(runtime_packages.get("all_match"))
            gdal_bridge = None
            if site_packages_value:
                gdal_bridge = self._prepare_wine_gdal_bridge(
                    Path(wine_prefix_receipt["prefix"]),
                    active_ras_executable,
                    site_packages_value,
                )
            wine_prefix_receipt.update(
                {
                    "isolated_ras_executable": str(active_ras_executable),
                    "isolated_installation": isolated_installation,
                    "isolated_component_hashes_match": component_hashes_match,
                    "isolated_installation_identity_matches": isolated_identity_matches,
                    "runtime_packages": runtime_packages,
                    "runtime_packages_match": runtime_packages_match,
                    "worker_package_sync": worker_package_sync,
                    "gdal_bridge": gdal_bridge,
                }
            )
            if not isolated_identity_matches:
                raise RuntimeError(
                    "Isolated Wine prefix HEC-RAS installation identity does not "
                    "match the qualified template"
                )
            marker = Path(wine_prefix_receipt["prefix"]) / ".ras-commander-prefix.json"
            wine_prefix_receipt["marker"] = str(marker)
            wine_prefix_receipt["marker_sha256"] = RasQualification.file_sha256(marker)
            if bool(self.config.wine.get("stage_inside_prefix", True)):
                stage_root = (
                    Path(wine_prefix_receipt["prefix"])
                    / "drive_c"
                    / "ras-qualification-projects"
                )

        stage = RasQualification.stage_project(
            self.config.source_project,
            stage_root,
            task_id=f"{fixture['id']}-{self.config.profile.value}",
            path_variant="standard",
        )
        self.receipt = RasQualification.create_run_receipt(
            self.config.profile,
            installation=installation,
            fixture=fixture,
        )
        self.context = {
            "schema_version": RasQualification.SCHEMA_VERSION,
            "executor_profile": self.config.profile.value,
            "expected_version": self.config.expected_version,
            "ras_executable": str(active_ras_executable),
            "template_ras_executable": str(self.config.ras_executable),
            "source_project": str(self.config.source_project),
            "workspace_root": str(stage_root),
            "host_workspace_root": str(self.config.workspace_root),
            "run_directory": str(self.run_directory),
            "project_folder": stage["destination"],
            "project_file": stage["project_file"],
            "fixture": fixture,
            "stage": stage,
        }
        if wine_prefix_receipt is not None:
            self.context.update(
                {
                    "wine_prefix": wine_prefix_receipt["prefix"],
                    "wine_executable": wine_prefix_receipt["wine_executable"],
                    "wine_prefix_receipt": wine_prefix_receipt,
                }
            )

        installation_passed = bool(
            installation.get("version_matches")
            and installation.get("required_components_present")
        )
        RasQualification.record_operation(
            self.receipt,
            "installation.detect",
            "passed" if installation_passed else "failed",
            evidence=installation if installation_passed else None,
            diagnostics=None if installation_passed else installation,
        )
        if wine_prefix_receipt is not None:
            prefix_passed = bool(
                wine_prefix_receipt.get("initialized")
                and wine_prefix_receipt.get("marker_sha256")
                and wine_prefix_receipt.get("wine_arch") == "win64"
                and wine_prefix_receipt.get("isolated_installation_identity_matches")
                and wine_prefix_receipt.get("runtime_packages_match", True)
            )
            RasQualification.record_operation(
                self.receipt,
                "wine_prefix.create",
                "passed" if prefix_passed else "failed",
                evidence=wine_prefix_receipt if prefix_passed else None,
                diagnostics=None if prefix_passed else wine_prefix_receipt,
            )
        RasQualification.record_operation(
            self.receipt,
            "project.clone",
            "passed",
            evidence=stage,
        )
        self._checkpoint()

    def _operation_paths(self, operation_id: str) -> tuple[Path, Path]:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", operation_id)
        payload_path = self.run_directory / f"{safe_id}.payload.json"
        result_path = self.run_directory / f"{safe_id}.result.json"
        return payload_path, result_path

    def _run_action(self, spec: QualificationActionSpec) -> Dict[str, Any]:
        payload_path, result_path = self._operation_paths(spec.operation_id)
        result_path.unlink(missing_ok=True)
        before_fingerprint = RasQualification.project_tree_fingerprint(
            self.context["project_folder"]
        )
        payload = {
            "operation_id": spec.operation_id,
            "handler": spec.handler,
            "parameters": dict(spec.parameters),
            "context": {**self.context, "operation_id": spec.operation_id},
            "result_path": str(result_path),
        }
        native_worker = spec.worker_runtime == "native"
        worker_payload = payload if native_worker else self._to_worker_paths(payload)
        payload_path.write_text(
            json.dumps(_json_value(worker_payload), indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )

        configured_worker = (
            None
            if native_worker
            else self.config.executor.get("worker_command")
        )
        command = [
            *(
                [os.path.expandvars(str(item)) for item in configured_worker]
                if configured_worker
                else [sys.executable]
            ),
            "-m",
            "ras_commander.RasQualificationRunner",
            "worker",
            str(
                payload_path
                if native_worker
                else self._to_worker_paths(str(payload_path))
            ),
        ]
        popen_kwargs: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "cwd": str(self.run_directory),
            "env": self._worker_environment(native_worker=native_worker),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        executor_lock = None
        lock_release = None
        if spec.operation_id != "locking.project":
            executor_lock = RasQualification.acquire_project_lock(
                self.context["project_folder"],
                owner=(
                    f"qualification-runner:{self.context['fixture']['id']}:"
                    f"{spec.operation_id}"
                ),
            )

        started = time.monotonic()
        try:
            process = subprocess.Popen(command, **popen_kwargs)
            timed_out = False
            try:
                stdout, stderr = process.communicate(timeout=spec.timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._terminate_process_tree(process)
                try:
                    stdout, stderr = process.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", "worker did not exit after process-tree termination"
        finally:
            if executor_lock is not None:
                lock_release = RasQualification.release_project_lock(executor_lock)
        duration = time.monotonic() - started
        project_lock_evidence = (
            {
                "mode": "self_test",
                "outer_lock_skipped": True,
            }
            if executor_lock is None
            else {
                **executor_lock,
                "release": lock_release,
            }
        )

        log_data = {
            "operation_id": spec.operation_id,
            "handler": spec.handler,
            "worker_runtime": spec.worker_runtime,
            "command": command,
            "timeout_seconds": spec.timeout_seconds,
            "timed_out": timed_out,
            "return_code": process.returncode,
            "duration_seconds": duration,
            "project_lock": project_lock_evidence,
            "stdout": _stream_evidence(stdout or ""),
            "stderr": _stream_evidence(stderr or ""),
        }
        log_path = self.logs_directory / f"{re.sub(r'[^A-Za-z0-9_.-]+', '-', spec.operation_id)}.json"
        log_path.write_text(
            json.dumps(_json_value(log_data), indent=2, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )

        outcome: Dict[str, Any] = {}
        if result_path.is_file():
            try:
                outcome = _mapping(
                    self._to_host_paths(
                        json.loads(result_path.read_text(encoding="utf-8"))
                    )
                )
            except (OSError, ValueError, TypeError) as exc:
                outcome = {"passed": False, "diagnostics": {"result_read_error": str(exc)}}

        after_fingerprint = RasQualification.project_tree_fingerprint(
            self.context["project_folder"]
        )
        evidence = outcome.get("evidence") or {}
        if isinstance(evidence, Mapping):
            evidence = dict(evidence)
        else:
            evidence = {"invalid_handler_evidence": _json_value(evidence)}
        evidence.update(
            {
                "project_fingerprint_before": before_fingerprint,
                "project_fingerprint_after": after_fingerprint,
                "operation_log": str(log_path),
                "duration_seconds": duration,
                "executor_project_lock": project_lock_evidence,
            }
        )
        diagnostics = outcome.get("diagnostics") or {}
        if not isinstance(diagnostics, Mapping):
            diagnostics = {"handler_diagnostics": _json_value(diagnostics)}
        diagnostics = dict(diagnostics)
        diagnostics.update(
            {
                "timed_out": timed_out,
                "return_code": process.returncode,
                "worker_result_present": result_path.is_file(),
                "operation_log": str(log_path),
            }
        )

        passed = bool(
            not timed_out
            and process.returncode == 0
            and outcome.get("passed") is True
            and evidence
        )
        return {
            "passed": passed,
            "evidence": evidence,
            "diagnostics": diagnostics,
            "context_updates": outcome.get("context_updates") or {},
            "artifacts": outcome.get("artifacts") or {},
            "series": outcome.get("series") or {},
        }

    @log_call
    def run(self) -> Dict[str, Any]:
        self._prepare()
        not_applicable = RasQualification._PROFILE_NOT_APPLICABLE.get(
            self.config.profile.value,
            set(),
        )
        built_in = {"installation.detect", "project.clone"}
        if self.config.profile == ExecutorProfile.LINUX_WINE_WINDOWS_RAS:
            built_in.add("wine_prefix.create")
        failed = False

        for operation_id in RasQualification.REQUIRED_OPERATIONS:
            if operation_id in built_in or operation_id in not_applicable:
                continue
            spec = self.action_specs.get(operation_id)
            if spec is None:
                RasQualification.record_operation(
                    self.receipt,
                    operation_id,
                    "failed",
                    diagnostics={"reason": "no action configured"},
                )
                failed = True
                self._checkpoint()
                continue

            outcome = self._run_action(spec)
            context_updates = outcome.get("context_updates")
            if isinstance(context_updates, Mapping):
                self.context.update(_json_value(dict(context_updates)))
            artifacts = outcome.get("artifacts")
            if isinstance(artifacts, Mapping):
                self.receipt.setdefault("artifacts", {}).update(_json_value(dict(artifacts)))
            series = outcome.get("series")
            if isinstance(series, Mapping):
                self.receipt.setdefault("series", {}).update(_json_value(dict(series)))

            status = "passed" if outcome["passed"] else "failed"
            RasQualification.record_operation(
                self.receipt,
                operation_id,
                status,
                # Failed operations are often the most important qualification
                # evidence. Preserve content fingerprints, partial artifacts,
                # rollback proof, and process timing instead of retaining only
                # the exit diagnostics.
                evidence=outcome["evidence"],
                diagnostics=outcome["diagnostics"],
            )
            failed = failed or not outcome["passed"]
            self._checkpoint()
            if not outcome["passed"] and self.config.stop_on_failure:
                break

        # Configured diagnostics retain their evidence in the receipt but do
        # not decide production qualification.  They run after all critical
        # actions so a brittle direct interop probe cannot block preprocessing.
        for operation_id in RasQualification.DIAGNOSTIC_OPERATIONS:
            spec = self.action_specs.get(operation_id)
            if spec is None:
                continue
            outcome = self._run_action(spec)
            context_updates = outcome.get("context_updates")
            if isinstance(context_updates, Mapping):
                self.context.update(_json_value(dict(context_updates)))
            artifacts = outcome.get("artifacts")
            if isinstance(artifacts, Mapping):
                self.receipt.setdefault("artifacts", {}).update(
                    _json_value(dict(artifacts))
                )
            series = outcome.get("series")
            if isinstance(series, Mapping):
                self.receipt.setdefault("series", {}).update(
                    _json_value(dict(series))
                )
            status = "passed" if outcome["passed"] else "failed"
            RasQualification.record_operation(
                self.receipt,
                operation_id,
                status,
                evidence=outcome["evidence"],
                diagnostics=outcome["diagnostics"],
            )
            self._checkpoint()

        validation = RasQualification.validate_run_receipt(
            self.receipt,
            expected_profile=self.config.profile,
            expected_version=self.config.expected_version,
        )
        self.receipt["validation"] = validation
        self.receipt["runner_passed"] = bool(not failed and validation["passed"])
        self._checkpoint()
        return self.receipt


def _resolve_handler(handler: str):
    module_name, function_name = handler.rsplit(":", 1)
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)
    if not callable(function):
        raise TypeError(f"Qualification handler is not callable: {handler}")
    return function


def _worker(payload_path: Union[str, Path]) -> int:
    payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    result_path = Path(payload["result_path"])
    result: Dict[str, Any]
    try:
        function = _resolve_handler(str(payload["handler"]))
        returned = function(
            _mapping(payload.get("context") or {}),
            **_mapping(payload.get("parameters") or {}),
        )
        result = _mapping(returned)
        if result.get("passed") is not True:
            result.setdefault("diagnostics", {})
    except BaseException as exc:
        result = {
            "passed": False,
            "diagnostics": {
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            },
        }
    result_path.write_text(
        json.dumps(_json_value(result), indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return 0 if result.get("passed") is True else 1


def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="HEC-RAS qualification runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="execute a qualification manifest")
    run_parser.add_argument("manifest")
    worker_parser = subparsers.add_parser("worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("payload")
    arguments = parser.parse_args(argv)

    if arguments.command == "worker":
        return _worker(arguments.payload)

    config = QualificationRunConfig.from_json(arguments.manifest)
    receipt = RasQualificationRunner(config).run()
    print(json.dumps(receipt.get("validation", {}), indent=2, sort_keys=True))
    return 0 if receipt.get("runner_passed") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
