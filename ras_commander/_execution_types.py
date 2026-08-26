"""Lightweight public option types shared by execution and mapping modules."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Union


MemoryPolicy = Literal["enforce", "warn", "ignore"]
GdalThreadSetting = Optional[Union[int, Literal["ALL_CPUS"]]]


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalize_gdal_threads(
    value: GdalThreadSetting,
) -> GdalThreadSetting:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("GDAL thread count must not be boolean")
    if isinstance(value, int):
        if value < 1:
            raise ValueError("GDAL thread count must be positive")
        return value
    normalized = str(value).strip().upper()
    if normalized == "ALL_CPUS":
        return "ALL_CPUS"
    if normalized.isdigit() and int(normalized) >= 1:
        return int(normalized)
    raise ValueError("GDAL thread count must be positive, ALL_CPUS, or None")


@dataclass(frozen=True)
class StoreMapPerformanceOptions:
    """Execution and resource policy for independent stored-map helpers."""

    max_workers: Optional[int] = 1
    memory_policy: MemoryPolicy = "enforce"
    minimum_worker_memory_mb: int = 600
    worker_memory_override_mb: Optional[int] = None
    reserve_memory_mb: int = 4096
    reserve_memory_fraction: float = 0.25
    gdal_num_threads_per_helper: GdalThreadSetting = 1
    gdal_cachemax_mb: Optional[int] = None
    admission_wait_timeout_seconds: float = 300.0
    admission_poll_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_workers is not None and (
            not _is_strict_int(self.max_workers) or self.max_workers < 1
        ):
            raise ValueError("max_workers must be positive or None")
        if self.memory_policy not in {"enforce", "warn", "ignore"}:
            raise ValueError("memory_policy must be enforce, warn, or ignore")
        if (
            not _is_strict_int(self.minimum_worker_memory_mb)
            or self.minimum_worker_memory_mb < 1
        ):
            raise ValueError("minimum_worker_memory_mb must be positive")
        if self.worker_memory_override_mb is not None and (
            not _is_strict_int(self.worker_memory_override_mb)
            or self.worker_memory_override_mb < 1
        ):
            raise ValueError("worker_memory_override_mb must be positive")
        if (
            self.worker_memory_override_mb is not None
            and self.memory_policy == "enforce"
        ):
            raise ValueError(
                "worker_memory_override_mb requires memory_policy='warn' or 'ignore'"
            )
        if not _is_strict_int(self.reserve_memory_mb) or self.reserve_memory_mb < 0:
            raise ValueError("reserve_memory_mb must be non-negative")
        if not 0 <= self.reserve_memory_fraction < 1:
            raise ValueError("reserve_memory_fraction must be in [0, 1)")
        if self.gdal_cachemax_mb is not None and (
            not _is_strict_int(self.gdal_cachemax_mb)
            or self.gdal_cachemax_mb < 1
        ):
            raise ValueError("gdal_cachemax_mb must be positive")
        if self.admission_wait_timeout_seconds < 0:
            raise ValueError("admission_wait_timeout_seconds must be non-negative")
        if self.admission_poll_interval_seconds <= 0:
            raise ValueError("admission_poll_interval_seconds must be positive")
        object.__setattr__(
            self,
            "gdal_num_threads_per_helper",
            _normalize_gdal_threads(self.gdal_num_threads_per_helper),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenefitAreaConfig:
    """Pair-aware configuration used by stored-map benefit analysis."""

    pre_plan_number: str
    terrain_tif: Union[str, Path]
    terrain_name: Optional[str] = None
    include_wse: bool = False
    flood_min_depth: float = 0.05
    benefit_min_depth: float = 0.25
    minimum_region_pixels: Optional[int] = 16
    analysis_boundary: Any = None
    improvement_boundary: Any = None
    polygon_output: Optional[Union[bool, str, Path]] = None
    polygon_simplify_tolerance: Optional[float] = None

    def __post_init__(self) -> None:
        if self.pre_plan_number is None or not str(self.pre_plan_number).strip():
            raise ValueError("pre_plan_number is required for BenefitArea mapping")

        # Benefit analysis is an optional geospatial feature. Defer importing
        # its implementation until a configuration is actually instantiated.
        from .RasBenefits import RasBenefits

        if self.terrain_tif is None or not str(self.terrain_tif).strip():
            raise ValueError(
                "terrain_tif is required for BenefitArea mapping. "
                f"{RasBenefits.TERRAIN_REMEDIATION}"
            )
        RasBenefits._validate_thresholds(
            self.flood_min_depth,
            self.benefit_min_depth,
        )
        RasBenefits._validate_minimum_region_pixels(self.minimum_region_pixels)
        RasBenefits._validate_polygon_simplify_tolerance(
            self.polygon_simplify_tolerance
        )


# Preserve the historical public identities for repr(), documentation, and
# pickle compatibility even though the definitions now live in a lean module.
StoreMapPerformanceOptions.__module__ = "ras_commander.RasterPerformance"
BenefitAreaConfig.__module__ = "ras_commander.RasBenefits"
