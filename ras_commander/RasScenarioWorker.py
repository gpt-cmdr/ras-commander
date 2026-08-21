"""Versioned process boundary for one HEC-RAS scenario execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

from .Decorators import log_call
from .hdf.HdfResultsProducts import HdfResultsProducts
from .LoggingConfig import get_logger
from .RasScenario import RasBoundaryLink, RasRunArtifact, RasScenario

logger = get_logger(__name__)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HYDROLOGIC_PRODUCTS_SCHEMA = "hms-commander/hydrologic-product-manifest/1.0"


class RasScenarioWorkerError(RuntimeError):
    """Classified worker failure suitable for a machine-readable result."""

    def __init__(
        self,
        message: str,
        *,
        classification: str,
        exit_code: int,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.classification = classification
        self.exit_code = exit_code
        self.retryable = retryable


class RasScenarioWorker:
    """Static namespace for the RAS scenario-worker request/result contract."""

    REQUEST_SCHEMA = "ras-commander/scenario-worker-request/1.0"
    RESULT_SCHEMA = "ras-commander/scenario-worker-result/1.0"

    @staticmethod
    @log_call
    def run(
        request_path: Union[str, Path],
        result_path: Union[str, Path],
    ) -> int:
        """Execute one request and atomically write identity-bound evidence."""
        request_file = Path(request_path).resolve()
        result_file = Path(result_path).resolve()
        started_at = _utc_now()
        started_clock = time.perf_counter()
        request: Optional[Dict[str, Any]] = None
        request_sha256: Optional[str] = None
        preparation: Dict[str, Any] = {"status": "not_started"}
        execution: Dict[str, Any] = {"status": "not_started"}
        result_hdf: Optional[Dict[str, Any]] = None
        products: Optional[Dict[str, Any]] = None
        numerical_qaqc: Optional[Dict[str, Any]] = None
        conditional_findings: Optional[Dict[str, Any]] = None
        retry_evidence: Optional[Dict[str, Any]] = None
        timings: Dict[str, Any] = {}
        warnings: list[str] = []

        try:
            retained_request = RasScenarioWorker._load_request(request_file)
            request_sha256 = _json_sha256(retained_request)
            request = RasScenarioWorker._validate_request(retained_request)
            if result_file.exists():
                RasScenarioWorker._verify_completed_result(
                    result_file,
                    request_sha256=request_sha256,
                    specification_sha256=request["scenario"]["specification_sha256"],
                )
                logger.info(
                    "Verified existing RAS worker result for request %s",
                    request_sha256,
                )
                return 0

            retry_evidence = RasScenarioWorker._verify_retry_evidence(request)
            preparation = {
                "status": "not_started",
                "retry": retry_evidence,
            }

            workspace_path = Path(request["workspace"])
            product_directory = Path(request["products"]["directory"])
            if workspace_path.exists():
                raise RasScenarioWorkerError(
                    f"RAS scenario workspace already exists: {workspace_path}",
                    classification="existing_workspace",
                    exit_code=3,
                )
            if product_directory.exists():
                raise RasScenarioWorkerError(
                    "Hydraulic product destination already exists: "
                    f"{product_directory}",
                    classification="existing_product_destination",
                    exit_code=3,
                )

            RasScenarioWorker._verify_input_identities(request)
            links = tuple(
                RasBoundaryLink.from_mapping(value)
                for value in request["boundary_links"]
            )
            model_window = request["model_window"]
            source_model = request["source_model"]
            forcing_excess = request["forcing_excess"]
            execution_options = request["execution"]

            preparation_started = time.perf_counter()
            preparation = {"status": "in_progress"}
            try:
                workspace = RasScenario.prepare_workspace(
                    source_model["project"],
                    request["workspace"],
                    request["scenario"]["scenario_id"],
                    source_model["template_plan"],
                    request["hydrology"]["dss"],
                    links,
                    _parse_model_time(model_window["start"]),
                    _parse_model_time(model_window["end"]),
                    ras_exe_path=execution_options["ras_executable"],
                    linked_asset_directories=source_model["linked_asset_directories"],
                    linked_asset_cache_key=(
                        source_model["model_manifest_sha256"]
                        if source_model["linked_asset_mode"] == "shared-cache"
                        else None
                    ),
                    forcing_excess_dss=forcing_excess["dss"],
                    forcing_excess_pathname=forcing_excess["pathname"],
                    forcing_excess_interpolation=forcing_excess["interpolation"],
                    copy_hydrology=True,
                    overwrite=False,
                )
                checks = RasScenario.validate_workspace(workspace, links)
                evidence = RasScenario.inspect_workspace_evidence(
                    workspace,
                    links,
                )
            finally:
                timings["preparation_seconds"] = _elapsed(preparation_started)
            preparation = {
                "status": "passed",
                "checks": checks,
                "evidence": evidence,
                "workspace": workspace.to_dict(),
                "retry": retry_evidence,
            }

            execution_started = time.perf_counter()
            execution = {"status": "in_progress"}
            try:
                artifact = RasScenario.execute(
                    workspace,
                    ras_exe_path=execution_options["ras_executable"],
                    timeout=execution_options["timeout_seconds"],
                    num_cores=execution_options["cores"],
                )
            finally:
                timings["execution_seconds"] = _elapsed(execution_started)
            execution = artifact.to_dict()
            if artifact.status != "succeeded":
                raise RasScenarioWorker._artifact_failure(artifact)
            if source_model["linked_asset_mode"] == "shared-cache":
                preparation["linked_asset_cache_post_execution"] = (
                    RasScenario._prepare_linked_asset_cache(
                        workspace.project_folder.parent,
                        tuple(
                            Path(path)
                            for path in source_model["linked_asset_directories"]
                        ),
                        source_model["model_manifest_sha256"],
                    )
                )

            result_hdf = _file_identity(artifact.result_hdf)
            product_options = request["products"]
            product_started = time.perf_counter()
            try:
                try:
                    manifest = HdfResultsProducts.export(
                        artifact.result_hdf,
                        product_directory,
                        resolution=product_options["resolution"],
                        max_dimension=product_options["max_dimension"],
                        nodata=product_options["nodata"],
                        include_preview=product_options["include_preview"],
                    )
                except Exception as exc:
                    raise RasScenarioWorkerError(
                        f"Hydraulic product export failed: {exc}",
                        classification="product_export_failed",
                        exit_code=4,
                        retryable=isinstance(exc, OSError),
                    ) from exc
            finally:
                timings["product_export_seconds"] = _elapsed(product_started)

            product_manifest_path = (
                product_directory / HdfResultsProducts.MANIFEST_FILENAME
            )
            numerical_path = (
                product_directory / HdfResultsProducts.FILENAMES["numerical-qaqc"]
            )
            numerical_qaqc = json.loads(numerical_path.read_text(encoding="utf-8"))
            conditional_findings = dict(
                numerical_qaqc.get("compute_message_findings", {})
            )
            warnings = _conditional_warning_lines(conditional_findings)
            products = {
                "directory": str(product_directory),
                "manifest": _file_identity(product_manifest_path),
                "schema": manifest["schema"],
                "status": manifest["status"],
            }

            result = RasScenarioWorker._result_payload(
                request=request,
                request_sha256=request_sha256,
                status="succeeded",
                started_at=started_at,
                started_clock=started_clock,
                preparation=preparation,
                execution=execution,
                result_hdf=result_hdf,
                products=products,
                numerical_qaqc=numerical_qaqc,
                conditional_findings=conditional_findings,
                timings=timings,
                warnings=warnings,
                error=None,
            )
            _write_json_new(result_file, result)
            logger.info("Completed RAS scenario worker request %s", request_sha256)
            return 0
        except Exception as exc:
            failure = RasScenarioWorker._classify_exception(exc)
            result = RasScenarioWorker._result_payload(
                request=request,
                request_sha256=request_sha256,
                status="failed",
                started_at=started_at,
                started_clock=started_clock,
                preparation=preparation,
                execution=execution,
                result_hdf=result_hdf,
                products=products,
                numerical_qaqc=numerical_qaqc,
                conditional_findings=conditional_findings,
                timings=timings,
                warnings=warnings,
                error={
                    "classification": failure.classification,
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": failure.retryable,
                },
            )
            try:
                _write_json_new(result_file, result)
            except FileExistsError:
                logger.error(
                    "Refusing to replace existing RAS worker result: %s",
                    result_file,
                )
            except OSError as write_error:
                logger.error(
                    "Could not write RAS worker failure result %s: %s",
                    result_file,
                    write_error,
                )
            logger.error(
                "RAS scenario worker failed (%s): %s",
                failure.classification,
                exc,
            )
            return failure.exit_code

    @staticmethod
    def _load_request(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            raise RasScenarioWorkerError(
                f"RAS worker request does not exist: {path}",
                classification="invalid_request",
                exit_code=2,
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RasScenarioWorkerError(
                f"Could not read RAS worker request {path}: {exc}",
                classification="invalid_request",
                exit_code=2,
            ) from exc
        if not isinstance(payload, dict):
            raise RasScenarioWorkerError(
                "RAS worker request root must be a JSON object",
                classification="invalid_request",
                exit_code=2,
            )
        return payload

    @staticmethod
    def _validate_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
        _require_keys(
            payload,
            required={
                "schema",
                "scenario",
                "source_model",
                "hydrology",
                "boundary_links",
                "forcing_excess",
                "model_window",
                "workspace",
                "products",
                "execution",
            },
            optional={"retry"},
            label="request",
        )
        if payload["schema"] != RasScenarioWorker.REQUEST_SCHEMA:
            raise RasScenarioWorkerError(
                f"Unsupported RAS worker request schema: {payload['schema']!r}",
                classification="invalid_request",
                exit_code=2,
            )

        scenario = _object(payload["scenario"], "scenario")
        _require_keys(
            scenario,
            required={"scenario_id", "specification_sha256"},
            optional=set(),
            label="scenario",
        )
        normalized_scenario = {
            "scenario_id": _nonempty_string(
                scenario["scenario_id"], "scenario.scenario_id"
            ),
            "specification_sha256": _sha256_string(
                scenario["specification_sha256"],
                "scenario.specification_sha256",
            ),
        }

        source = _object(payload["source_model"], "source_model")
        _require_keys(
            source,
            required={
                "project",
                "project_file_sha256",
                "template_plan",
                "model_manifest",
                "model_manifest_sha256",
            },
            optional={"linked_asset_directories", "linked_asset_mode"},
            label="source_model",
        )
        linked_assets = source.get("linked_asset_directories", [])
        if not isinstance(linked_assets, list):
            _invalid("source_model.linked_asset_directories must be an array")
        normalized_source = {
            "project": _resolved_path(source["project"], "source_model.project"),
            "project_file_sha256": _sha256_string(
                source["project_file_sha256"],
                "source_model.project_file_sha256",
            ),
            "template_plan": _nonempty_string(
                str(source["template_plan"]), "source_model.template_plan"
            ),
            "model_manifest": _resolved_path(
                source["model_manifest"], "source_model.model_manifest"
            ),
            "model_manifest_sha256": _sha256_string(
                source["model_manifest_sha256"],
                "source_model.model_manifest_sha256",
            ),
            "linked_asset_directories": [
                _resolved_path(value, f"source_model.linked_asset_directories[{i}]")
                for i, value in enumerate(linked_assets)
            ],
            "linked_asset_mode": _choice(
                source.get("linked_asset_mode", "copy"),
                "source_model.linked_asset_mode",
                {"copy", "shared-cache"},
            ),
        }

        hydrology = _identity_input(
            payload["hydrology"],
            label="hydrology",
            file_key="dss",
            manifest_key="product_manifest",
        )
        forcing = _identity_input(
            payload["forcing_excess"],
            label="forcing_excess",
            file_key="dss",
            manifest_key="provenance_manifest",
            extra_required={"pathname"},
            extra_optional={"interpolation"},
        )
        forcing["pathname"] = _dss_pathname(
            payload["forcing_excess"]["pathname"],
            "forcing_excess.pathname",
        )
        forcing["interpolation"] = _choice(
            payload["forcing_excess"].get("interpolation", "Bilinear"),
            "forcing_excess.interpolation",
            {"Nearest", "Bilinear"},
        )

        raw_links = payload["boundary_links"]
        if not isinstance(raw_links, list) or not raw_links:
            _invalid("boundary_links must be a non-empty array")
        links: list[Dict[str, Any]] = []
        allowed_link_fields = set(RasBoundaryLink.__dataclass_fields__)
        for index, raw_link in enumerate(raw_links):
            link = _object(raw_link, f"boundary_links[{index}]")
            unknown = sorted(set(link) - allowed_link_fields)
            if unknown:
                _invalid(
                    f"Invalid boundary_links[{index}] fields: unknown "
                    + ", ".join(unknown)
                )
            try:
                normalized_link = RasBoundaryLink.from_mapping(link)
            except (TypeError, ValueError) as exc:
                raise RasScenarioWorkerError(
                    f"Invalid boundary_links[{index}]: {exc}",
                    classification="invalid_request",
                    exit_code=2,
                ) from exc
            links.append(
                {
                    name: value
                    for name, value in normalized_link.__dict__.items()
                    if value is not None
                }
            )
        if len({link["mapping_id"] for link in links}) != len(links):
            _invalid("boundary_links mapping_id values must be unique")

        window = _object(payload["model_window"], "model_window")
        _require_keys(
            window,
            required={"start", "end", "time_zone"},
            optional=set(),
            label="model_window",
        )
        start = _parse_model_time(window["start"])
        end = _parse_model_time(window["end"])
        if end <= start:
            _invalid("model_window.end must be later than model_window.start")
        normalized_window = {
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "time_zone": _nonempty_string(
                window["time_zone"], "model_window.time_zone"
            ),
        }

        product_config = _object(payload["products"], "products")
        _require_keys(
            product_config,
            required={"directory"},
            optional={"resolution", "max_dimension", "nodata", "include_preview"},
            label="products",
        )
        resolution = product_config.get("resolution")
        if resolution is not None:
            resolution = _positive_number(resolution, "products.resolution")
        max_dimension = product_config.get("max_dimension", 2048)
        if (
            isinstance(max_dimension, bool)
            or not isinstance(max_dimension, int)
            or max_dimension < 64
        ):
            _invalid("products.max_dimension must be an integer of at least 64")
        nodata = product_config.get("nodata", -9999.0)
        if (
            isinstance(nodata, bool)
            or not isinstance(nodata, (int, float))
            or not math.isfinite(nodata)
        ):
            _invalid("products.nodata must be finite and numeric")
        include_preview = product_config.get("include_preview", True)
        if not isinstance(include_preview, bool):
            _invalid("products.include_preview must be boolean")

        execution = _object(payload["execution"], "execution")
        _require_keys(
            execution,
            required={"ras_executable", "timeout_seconds", "cores"},
            optional=set(),
            label="execution",
        )

        retry = None
        if payload.get("retry") is not None:
            retry_config = _object(payload["retry"], "retry")
            _require_keys(
                retry_config,
                required={"prior_request", "prior_result"},
                optional=set(),
                label="retry",
            )
            retry = {
                "prior_request": _resolved_path(
                    retry_config["prior_request"], "retry.prior_request"
                ),
                "prior_result": _resolved_path(
                    retry_config["prior_result"], "retry.prior_result"
                ),
            }

        normalized_request = {
            "schema": RasScenarioWorker.REQUEST_SCHEMA,
            "scenario": normalized_scenario,
            "source_model": normalized_source,
            "hydrology": hydrology,
            "boundary_links": links,
            "forcing_excess": forcing,
            "model_window": normalized_window,
            "workspace": _resolved_path(payload["workspace"], "workspace"),
            "products": {
                "directory": _resolved_path(
                    product_config["directory"], "products.directory"
                ),
                "resolution": resolution,
                "max_dimension": max_dimension,
                "nodata": float(nodata),
                "include_preview": include_preview,
            },
            "execution": {
                "ras_executable": _resolved_path(
                    execution["ras_executable"], "execution.ras_executable"
                ),
                "timeout_seconds": _positive_int(
                    execution["timeout_seconds"], "execution.timeout_seconds"
                ),
                "cores": _positive_int(execution["cores"], "execution.cores"),
            },
        }
        if retry is not None:
            normalized_request["retry"] = retry
        return normalized_request

    @staticmethod
    def _verify_input_identities(request: Mapping[str, Any]) -> None:
        project = Path(request["source_model"]["project"])
        try:
            project_file = RasScenario._resolve_project_file(project)
        except (FileNotFoundError, ValueError) as exc:
            raise RasScenarioWorkerError(
                str(exc),
                classification="source_model_identity",
                exit_code=2,
            ) from exc
        _verify_file_sha256(
            project_file,
            request["source_model"]["project_file_sha256"],
            "source RAS project",
            "source_model_identity",
        )
        model_manifest = _verify_json_identity(
            request["source_model"]["model_manifest"],
            request["source_model"]["model_manifest_sha256"],
            "source RAS model manifest",
            "source_model_identity",
        )
        if str(model_manifest.get("stage", "")).casefold() != "ras":
            raise RasScenarioWorkerError(
                "Source model manifest is not a RAS-stage manifest",
                classification="source_model_identity",
                exit_code=2,
            )
        for directory in request["source_model"]["linked_asset_directories"]:
            if not Path(directory).is_dir():
                raise RasScenarioWorkerError(
                    f"Linked asset directory does not exist: {directory}",
                    classification="source_model_identity",
                    exit_code=2,
                )

        _verify_file_sha256(
            Path(request["hydrology"]["dss"]),
            request["hydrology"]["sha256"],
            "hydrology DSS",
            "hydrology_identity",
        )
        hydrology_manifest = _verify_json_identity(
            request["hydrology"]["product_manifest"],
            request["hydrology"]["product_manifest_sha256"],
            "hydrologic product manifest",
            "hydrology_identity",
        )
        if hydrology_manifest.get("schema") != _HYDROLOGIC_PRODUCTS_SCHEMA:
            raise RasScenarioWorkerError(
                "Hydrologic product manifest has an unsupported schema",
                classification="hydrology_identity",
                exit_code=2,
            )
        if (
            hydrology_manifest.get("source", {}).get("sha256")
            != request["hydrology"]["sha256"]
        ):
            raise RasScenarioWorkerError(
                "Hydrologic product manifest does not identify the supplied DSS",
                classification="hydrology_identity",
                exit_code=2,
            )

        _verify_file_sha256(
            Path(request["forcing_excess"]["dss"]),
            request["forcing_excess"]["sha256"],
            "forcing-excess DSS",
            "forcing_excess_identity",
        )
        _verify_json_identity(
            request["forcing_excess"]["provenance_manifest"],
            request["forcing_excess"]["provenance_manifest_sha256"],
            "forcing-excess provenance manifest",
            "forcing_excess_identity",
        )
        executable = Path(request["execution"]["ras_executable"])
        if not executable.is_file():
            raise RasScenarioWorkerError(
                f"HEC-RAS executable reference does not exist: {executable}",
                classification="invalid_request",
                exit_code=2,
            )

    @staticmethod
    def _verify_retry_evidence(
        request: Mapping[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Authenticate a preparation-only failure before sharing its cache."""
        retry = request.get("retry")
        if retry is None:
            return None

        def reject(message: str) -> None:
            raise RasScenarioWorkerError(
                message,
                classification="retry_evidence",
                exit_code=2,
            )

        if request["source_model"]["linked_asset_mode"] != "shared-cache":
            reject(
                "Retry requests must use source_model.linked_asset_mode=shared-cache"
            )
        prior_request_path = Path(retry["prior_request"])
        prior_result_path = Path(retry["prior_result"])
        if not prior_request_path.is_file():
            reject(f"Prior worker request does not exist: {prior_request_path}")
        if not prior_result_path.is_file():
            reject(f"Prior worker result does not exist: {prior_result_path}")

        try:
            retained_prior_request = RasScenarioWorker._load_request(
                prior_request_path
            )
            retained_prior_hash = _json_sha256(retained_prior_request)
            prior_request = RasScenarioWorker._validate_request(
                retained_prior_request
            )
            prior_result = json.loads(prior_result_path.read_text(encoding="utf-8"))
        except RasScenarioWorkerError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            reject(f"Prior worker evidence is unreadable: {exc}")
        if not isinstance(prior_result, dict):
            reject("Prior worker result root must be an object")

        prior_request_sha256 = _json_sha256(prior_request)
        legacy_prior_request = json.loads(json.dumps(prior_request))
        legacy_prior_request.pop("retry", None)
        legacy_prior_request["source_model"].pop("linked_asset_mode", None)
        accepted_prior_hashes = {
            retained_prior_hash,
            prior_request_sha256,
            _json_sha256(legacy_prior_request),
        }
        if prior_result.get("schema") != RasScenarioWorker.RESULT_SCHEMA:
            reject("Prior worker result schema does not match")
        if prior_result.get("status") != "failed":
            reject("Prior worker result is not a failed attempt")
        bound_prior_hash = prior_result.get("request", {}).get("sha256")
        if bound_prior_hash not in accepted_prior_hashes:
            reject("Prior worker result does not bind the prior request")
        if prior_result.get("preparation", {}).get("status") != "in_progress":
            reject("Prior worker failure did not occur during preparation")
        if prior_result.get("execution", {}).get("status") != "not_started":
            reject("Prior worker failure started HEC-RAS execution")
        error = prior_result.get("error")
        if not isinstance(error, dict) or not error.get("classification"):
            reject("Prior worker failure classification is missing")

        for field in ("scenario", "hydrology", "forcing_excess", "model_window"):
            if prior_request[field] != request[field]:
                reject(f"Retry changed immutable {field} inputs")
        source_identity_fields = (
            "project",
            "project_file_sha256",
            "template_plan",
            "model_manifest",
            "model_manifest_sha256",
            "linked_asset_directories",
        )
        for field in source_identity_fields:
            if prior_request["source_model"][field] != request["source_model"][field]:
                reject(f"Retry changed immutable source_model.{field}")

        prior_workspace = Path(prior_request["workspace"])
        current_workspace = Path(request["workspace"])
        if not prior_workspace.is_dir():
            reject(f"Prior failed workspace does not exist: {prior_workspace}")
        if prior_workspace == current_workspace:
            reject("Retry must use a new workspace and preserve the failed workspace")
        if prior_workspace.parent != current_workspace.parent:
            reject("Retry workspace must share the prior linked-asset cache parent")

        return {
            "status": "authenticated",
            "prior_request": _file_identity(prior_request_path),
            "prior_result": _file_identity(prior_result_path),
            "prior_request_sha256": bound_prior_hash,
            "prior_workspace": str(prior_workspace),
            "failure_classification": error["classification"],
            "cache_root": str(prior_workspace.parent),
        }

    @staticmethod
    def _artifact_failure(artifact: RasRunArtifact) -> RasScenarioWorkerError:
        if not artifact.result_exists:
            classification = "missing_hdf"
            message = "HEC-RAS result HDF is missing"
        elif artifact.result_size_bytes <= 0:
            classification = "empty_hdf"
            message = "HEC-RAS result HDF is empty"
        elif not artifact.hdf_completed_successfully:
            classification = "incomplete_hdf"
            message = "HEC-RAS result HDF has no successful completion marker"
        elif not artifact.time_window_matches:
            classification = "mismatched_result_time"
            message = "HEC-RAS result time axis does not match the request"
        elif not artifact.compute_returned_successfully:
            classification = "execution_failed"
            message = "HEC-RAS compute did not return success"
        else:
            classification = "execution_failed"
            message = "HEC-RAS execution artifact failed validation"
        if artifact.hdf_inspection_error:
            message += f": {artifact.hdf_inspection_error}"
        return RasScenarioWorkerError(
            message,
            classification=classification,
            exit_code=4,
            retryable=True,
        )

    @staticmethod
    def _verify_completed_result(
        result_path: Path,
        *,
        request_sha256: str,
        specification_sha256: str,
    ) -> Dict[str, Any]:
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RasScenarioWorkerError(
                f"Existing RAS worker result is unreadable: {result_path}",
                classification="existing_result_conflict",
                exit_code=3,
            ) from exc
        matches = (
            isinstance(result, dict)
            and result.get("schema") == RasScenarioWorker.RESULT_SCHEMA
            and result.get("status") == "succeeded"
            and result.get("request", {}).get("sha256") == request_sha256
            and result.get("scenario", {}).get("specification_sha256")
            == specification_sha256
        )
        if not matches:
            raise RasScenarioWorkerError(
                "Existing RAS worker result is not an identical completed request",
                classification="existing_result_conflict",
                exit_code=3,
            )
        for label, identity in (
            ("result HDF", result.get("result_hdf")),
            ("product manifest", result.get("products", {}).get("manifest")),
        ):
            if not isinstance(identity, dict):
                raise RasScenarioWorkerError(
                    f"Existing RAS worker result has no {label} identity",
                    classification="existing_result_conflict",
                    exit_code=3,
                )
            path = Path(str(identity.get("path", "")))
            if (
                not path.is_file()
                or path.stat().st_size != identity.get("size_bytes")
                or _sha256(path) != identity.get("sha256")
            ):
                raise RasScenarioWorkerError(
                    f"Existing RAS worker {label} failed identity verification",
                    classification="existing_result_conflict",
                    exit_code=3,
                )
        return result

    @staticmethod
    def _classify_exception(exc: Exception) -> RasScenarioWorkerError:
        if isinstance(exc, RasScenarioWorkerError):
            return exc
        if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
            return RasScenarioWorkerError(
                str(exc), classification="timeout", exit_code=4, retryable=True
            )
        if isinstance(exc, FileExistsError):
            if "linked asset cache" in str(exc).casefold():
                return RasScenarioWorkerError(
                    str(exc),
                    classification="linked_asset_cache",
                    exit_code=4,
                    retryable=True,
                )
            return RasScenarioWorkerError(
                str(exc), classification="existing_destination", exit_code=3
            )
        message = str(exc)
        lower = message.casefold()
        if "mixed newline" in lower:
            classification = "mixed_newlines"
        elif "project_uses_cloned_plan" in lower:
            classification = "wrong_current_plan"
        elif "plan_window_matches_contract" in lower:
            classification = "wrong_window"
        elif "all_boundaries_exist_in_active_geometry" in lower:
            classification = "inactive_geometry"
        elif "boundary mapping" in lower or "boundary selector" in lower:
            classification = "invalid_boundary_selector"
        elif "forcing_excess_link_matches" in lower:
            classification = "forcing_excess_link"
        elif "linked asset cache" in lower:
            classification = "linked_asset_cache"
        elif isinstance(exc, (ValueError, FileNotFoundError, TypeError)):
            classification = "preparation_failed"
        else:
            return RasScenarioWorkerError(
                message,
                classification="worker_error",
                exit_code=5,
                retryable=isinstance(exc, OSError),
            )
        return RasScenarioWorkerError(
            message, classification=classification, exit_code=4
        )

    @staticmethod
    def _result_payload(
        *,
        request: Optional[Mapping[str, Any]],
        request_sha256: Optional[str],
        status: str,
        started_at: str,
        started_clock: float,
        preparation: Mapping[str, Any],
        execution: Mapping[str, Any],
        result_hdf: Optional[Mapping[str, Any]],
        products: Optional[Mapping[str, Any]],
        numerical_qaqc: Optional[Mapping[str, Any]],
        conditional_findings: Optional[Mapping[str, Any]],
        timings: Mapping[str, Any],
        warnings: Sequence[str],
        error: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        scenario = request.get("scenario", {}) if request else {}
        complete_timings = dict(timings)
        complete_timings["total_seconds"] = _elapsed(started_clock)
        return {
            "schema": RasScenarioWorker.RESULT_SCHEMA,
            "status": status,
            "scenario": {
                "scenario_id": scenario.get("scenario_id"),
                "specification_sha256": scenario.get("specification_sha256"),
            },
            "request": {
                "schema": request.get("schema") if request else None,
                "sha256": request_sha256,
            },
            "preparation": dict(preparation),
            "execution": dict(execution),
            "result_hdf": dict(result_hdf) if result_hdf else None,
            "products": dict(products) if products else None,
            "numerical_qaqc": (dict(numerical_qaqc) if numerical_qaqc else None),
            "conditional_findings": (
                dict(conditional_findings) if conditional_findings else None
            ),
            "timings": {
                "started_at": started_at,
                "finished_at": _utc_now(),
                **complete_timings,
            },
            "warnings": list(warnings),
            "error": dict(error) if error else None,
        }


def _identity_input(
    value: Any,
    *,
    label: str,
    file_key: str,
    manifest_key: str,
    extra_required: Optional[set[str]] = None,
    extra_optional: Optional[set[str]] = None,
) -> Dict[str, Any]:
    payload = _object(value, label)
    required = {
        file_key,
        "sha256",
        manifest_key,
        f"{manifest_key}_sha256",
    } | (extra_required or set())
    _require_keys(
        payload,
        required=required,
        optional=extra_optional or set(),
        label=label,
    )
    return {
        file_key: _resolved_path(payload[file_key], f"{label}.{file_key}"),
        "sha256": _sha256_string(payload["sha256"], f"{label}.sha256"),
        manifest_key: _resolved_path(payload[manifest_key], f"{label}.{manifest_key}"),
        f"{manifest_key}_sha256": _sha256_string(
            payload[f"{manifest_key}_sha256"],
            f"{label}.{manifest_key}_sha256",
        ),
    }


def _object(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        _invalid(f"{label} must be a JSON object")
    return dict(value)


def _require_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        _invalid(f"Invalid {label} fields: " + "; ".join(details))


def _invalid(message: str) -> None:
    raise RasScenarioWorkerError(message, classification="invalid_request", exit_code=2)


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _invalid(f"{label} must be a non-empty string")
    return value.strip()


def _resolved_path(value: Any, label: str) -> str:
    return str(Path(_nonempty_string(value, label)).resolve())


def _sha256_string(value: Any, label: str) -> str:
    normalized = _nonempty_string(value, label)
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        _invalid(f"{label} must be a lowercase SHA-256 hexadecimal digest")
    return normalized


def _dss_pathname(value: Any, label: str) -> str:
    pathname = _nonempty_string(value, label)
    if not pathname.startswith("/") or not pathname.endswith("/"):
        _invalid(f"{label} must begin and end with '/'")
    return pathname


def _choice(value: Any, label: str, choices: set[str]) -> str:
    selected = _nonempty_string(value, label)
    if selected not in choices:
        _invalid(f"{label} must be one of: {', '.join(sorted(choices))}")
    return selected


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _invalid(f"{label} must be a positive integer")
    return value


def _positive_number(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        _invalid(f"{label} must be a positive number")
    return float(value)


def _parse_model_time(value: Any) -> datetime:
    text = _nonempty_string(value, "model window timestamp")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RasScenarioWorkerError(
            f"Invalid model window timestamp: {text!r}",
            classification="invalid_request",
            exit_code=2,
        ) from exc
    if parsed.tzinfo is not None:
        _invalid("Model window timestamps must be naive local/model times")
    return parsed


def _verify_file_sha256(
    path: Path,
    expected: str,
    label: str,
    classification: str,
) -> None:
    if not path.is_file() or path.stat().st_size <= 0:
        raise RasScenarioWorkerError(
            f"{label} does not exist or is empty: {path}",
            classification=classification,
            exit_code=2,
        )
    if _sha256(path) != expected:
        raise RasScenarioWorkerError(
            f"{label} checksum does not match the worker request",
            classification=classification,
            exit_code=2,
        )


def _verify_json_identity(
    path_value: str,
    expected: str,
    label: str,
    classification: str,
) -> Dict[str, Any]:
    path = Path(path_value)
    _verify_file_sha256(path, expected, label, classification)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RasScenarioWorkerError(
            f"{label} is not readable JSON: {path}",
            classification=classification,
            exit_code=2,
        ) from exc
    if not isinstance(payload, dict):
        raise RasScenarioWorkerError(
            f"{label} root must be a JSON object",
            classification=classification,
            exit_code=2,
        )
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _file_identity(path: Union[str, Path]) -> Dict[str, Any]:
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Expected output file does not exist: {file_path}")
    return {
        "path": str(file_path),
        "size_bytes": file_path.stat().st_size,
        "sha256": _sha256(file_path),
    }


def _write_json_new(path: Path, payload: Mapping[str, Any]) -> Path:
    if path.exists():
        raise FileExistsError(f"RAS worker result already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    try:
        if path.exists():
            raise FileExistsError(f"RAS worker result already exists: {path}")
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def _conditional_warning_lines(findings: Mapping[str, Any]) -> list[str]:
    return [
        f"{name}: {value.get('count')} finding(s)"
        for name, value in sorted(findings.items())
        if isinstance(value, dict) and value.get("count", 0) > 0
    ]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 6)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the ``ras-scenario-worker`` command-line interface."""
    parser = argparse.ArgumentParser(
        description="Execute one versioned ras-commander scenario-worker request."
    )
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)
    exit_code = RasScenarioWorker.run(args.request, args.result)
    if exit_code != 0:
        sys.stderr.write(f"RAS scenario worker failed; result: {args.result}\n")
    return exit_code


if __name__ == "__main__":  # pragma: no cover - subprocess boundary
    raise SystemExit(main())
