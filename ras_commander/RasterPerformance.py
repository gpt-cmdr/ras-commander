"""Typed resource and profiling contracts for raster-heavy operations."""

from __future__ import annotations

import ctypes
import json
import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Literal, Optional, Tuple, Union

import psutil

MemoryPolicy = Literal["enforce", "warn", "ignore"]
GdalThreadSetting = Optional[Union[int, Literal["ALL_CPUS"]]]


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _normalize_gdal_threads(value: GdalThreadSetting) -> GdalThreadSetting:
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
    """Execution and resource policy for independent stored-map helpers.

    ``max_workers`` is always a ceiling. ``None`` requests automatic selection.
    The default of one preserves the legacy StoreAllMaps execution path.
    """

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
            not _is_strict_int(self.gdal_cachemax_mb) or self.gdal_cachemax_mb < 1
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
class GeoTiffWriteOptions:
    """GDAL GeoTIFF creation and overview settings for terrain consolidation."""

    compression: str = "LZW"
    compression_level: Optional[int] = None
    predictor: Optional[int] = None
    tile_size: Optional[int] = None
    bigtiff: str = "IF_SAFER"
    gdal_num_threads: GdalThreadSetting = None
    gdal_cachemax_mb: Optional[int] = None
    create_overviews: bool = True
    overview_levels: Tuple[int, ...] = (2, 4, 8, 16, 32)
    overview_resampling: str = "average"
    overview_compression: Optional[str] = None

    def __post_init__(self) -> None:
        compression = str(self.compression).strip().upper()
        if compression not in {"LZW", "DEFLATE", "ZSTD", "NONE"}:
            raise ValueError("compression must be LZW, DEFLATE, ZSTD, or NONE")
        object.__setattr__(self, "compression", compression)
        if self.compression_level is not None and (
            not _is_strict_int(self.compression_level)
            or not 1 <= self.compression_level <= 22
        ):
            raise ValueError("compression_level must be between 1 and 22")
        if self.compression_level is not None and compression not in {
            "DEFLATE",
            "ZSTD",
        }:
            raise ValueError("compression_level is supported only for DEFLATE or ZSTD")
        if (
            compression == "DEFLATE"
            and self.compression_level is not None
            and self.compression_level > 9
        ):
            raise ValueError("DEFLATE compression_level must be between 1 and 9")
        if self.predictor is not None and (
            not _is_strict_int(self.predictor) or self.predictor not in {1, 2, 3}
        ):
            raise ValueError("predictor must be 1, 2, 3, or None")
        if self.tile_size is not None and (
            not _is_strict_int(self.tile_size)
            or self.tile_size < 16
            or self.tile_size > 4096
            or self.tile_size % 16 != 0
        ):
            raise ValueError("tile_size must be a multiple of 16 from 16 to 4096")
        bigtiff = str(self.bigtiff).strip().upper()
        if bigtiff not in {"YES", "NO", "IF_NEEDED", "IF_SAFER"}:
            raise ValueError("bigtiff must be YES, NO, IF_NEEDED, or IF_SAFER")
        object.__setattr__(self, "bigtiff", bigtiff)
        object.__setattr__(
            self,
            "gdal_num_threads",
            _normalize_gdal_threads(self.gdal_num_threads),
        )
        if self.gdal_cachemax_mb is not None and (
            not _is_strict_int(self.gdal_cachemax_mb) or self.gdal_cachemax_mb < 1
        ):
            raise ValueError("gdal_cachemax_mb must be positive")
        if not isinstance(self.create_overviews, bool):
            raise ValueError("create_overviews must be boolean")
        if any(not _is_strict_int(level) for level in self.overview_levels):
            raise ValueError("overview_levels must contain integers")
        levels = tuple(self.overview_levels)
        if any(level < 2 for level in levels) or tuple(sorted(set(levels))) != levels:
            raise ValueError("overview_levels must be unique increasing integers >= 2")
        object.__setattr__(self, "overview_levels", levels)
        resampling = str(self.overview_resampling).strip().casefold()
        if resampling not in {
            "nearest",
            "average",
            "average_mp",
            "average_magphase",
            "cubic",
            "cubicspline",
            "lanczos",
            "gauss",
            "mode",
        }:
            raise ValueError("unsupported overview_resampling")
        object.__setattr__(self, "overview_resampling", resampling)
        if self.overview_compression is not None:
            overview_compression = str(self.overview_compression).strip().upper()
            if overview_compression not in {"LZW", "DEFLATE", "ZSTD", "NONE"}:
                raise ValueError("unsupported overview_compression")
            object.__setattr__(
                self,
                "overview_compression",
                overview_compression,
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerrainResourceEstimate:
    path: Path
    width: int
    height: int
    dtype: str
    cell_count: int
    float32_surface_mb: float

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


@dataclass(frozen=True)
class StoreMapResourceEstimate:
    plan_number: str
    hecras_version: Optional[str]
    map_types: Tuple[str, ...]
    job_count: int
    terrain: Tuple[TerrainResourceEstimate, ...]
    formula_version: str
    estimate_source: Literal["heuristic", "override", "floor"]
    surface_multiplier: float
    fixed_overhead_mb: int
    estimated_gdal_cache_mb: int
    estimated_worker_private_mb: int
    total_physical_mb: int
    available_physical_mb: int
    commit_total_mb: Optional[int]
    commit_limit_mb: Optional[int]
    commit_headroom_mb: Optional[int]
    effective_reserve_mb: int
    cpu_limit: int
    memory_limit: int
    request_limit: int
    job_limit: int
    selected_workers: int
    parallel_eligible: bool
    fallback_reasons: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["terrain"] = [item.to_dict() for item in self.terrain]
        return result


@dataclass(frozen=True)
class StoreMapResourceSample:
    elapsed_seconds: float
    tree_rss_mb: float
    tree_private_mb: Optional[float]
    available_physical_mb: int
    commit_headroom_mb: Optional[int]
    tree_threads: int
    process_counts: Dict[str, int]
    interval_seconds: float = 0.0
    inferred_phase: str = "initializing"
    tree_cpu_percent: float = 0.0
    machine_cpu_percent: float = 0.0
    interval_cpu_seconds: float = 0.0
    read_mib_per_second: float = 0.0
    write_mib_per_second: float = 0.0
    read_iops: float = 0.0
    write_iops: float = 0.0
    interval_read_bytes: int = 0
    interval_write_bytes: int = 0
    interval_read_operations: int = 0
    interval_write_operations: int = 0
    mean_read_size_bytes: Optional[float] = None
    mean_write_size_bytes: Optional[float] = None
    watched_file_count: int = 0
    watched_output_bytes: int = 0
    host_disk_read_mib_per_second: float = 0.0
    host_disk_write_mib_per_second: float = 0.0
    host_disk_read_iops: float = 0.0
    host_disk_write_iops: float = 0.0
    host_disk_busy_equivalent_percent: Optional[float] = None
    host_disk_mean_read_latency_ms: Optional[float] = None
    host_disk_mean_write_latency_ms: Optional[float] = None
    host_network_receive_mib_per_second: float = 0.0
    host_network_send_mib_per_second: float = 0.0
    process_metrics: Dict[str, Dict[str, Union[int, float]]] = field(
        default_factory=dict
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoreMapProfileResult:
    resource_estimate: StoreMapResourceEstimate
    settings: Dict[str, Any]
    generated_files: Dict[str, Tuple[Path, ...]]
    elapsed_seconds: float
    peak_tree_rss_mb: float
    peak_tree_private_mb: Optional[float]
    minimum_available_memory_mb: int
    minimum_commit_headroom_mb: Optional[int]
    cpu_seconds_by_process: Dict[str, float]
    read_bytes_by_process: Dict[str, int]
    write_bytes_by_process: Dict[str, int]
    read_operations_by_process: Dict[str, int]
    write_operations_by_process: Dict[str, int]
    maximum_simultaneous_helpers: int
    samples: Tuple[StoreMapResourceSample, ...]
    performance_summary: Dict[str, Any]
    phase_summary: Dict[str, Dict[str, Any]]
    output_signatures: Dict[str, Dict[str, Any]]
    report_path: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "ras-commander.store-map-profile/1",
            "status": "complete",
            "resource_estimate": self.resource_estimate.to_dict(),
            "settings": self.settings,
            "generated_files": {
                key: [str(path) for path in paths]
                for key, paths in self.generated_files.items()
            },
            "elapsed_seconds": self.elapsed_seconds,
            "peak_tree_rss_mb": self.peak_tree_rss_mb,
            "peak_tree_private_mb": self.peak_tree_private_mb,
            "minimum_available_memory_mb": self.minimum_available_memory_mb,
            "minimum_commit_headroom_mb": self.minimum_commit_headroom_mb,
            "cpu_seconds_by_process": self.cpu_seconds_by_process,
            "read_bytes_by_process": self.read_bytes_by_process,
            "write_bytes_by_process": self.write_bytes_by_process,
            "read_operations_by_process": self.read_operations_by_process,
            "write_operations_by_process": self.write_operations_by_process,
            "maximum_simultaneous_helpers": self.maximum_simultaneous_helpers,
            "samples": [sample.to_dict() for sample in self.samples],
            "performance_summary": self.performance_summary,
            "phase_summary": self.phase_summary,
            "output_signatures": self.output_signatures,
            "report_path": str(self.report_path),
        }

    def write_report(self) -> Path:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
        return self.report_path


@dataclass(frozen=True)
class RasterOperationProfileResult:
    """Portable process-tree profile for one raster operation."""

    operation: str
    settings: Dict[str, Any]
    output_path: Path
    elapsed_seconds: float
    peak_tree_rss_mb: float
    peak_tree_private_mb: Optional[float]
    minimum_available_memory_mb: int
    minimum_commit_headroom_mb: Optional[int]
    process_counters: Dict[str, Dict[str, Union[int, float]]]
    samples: Tuple[StoreMapResourceSample, ...]
    performance_summary: Dict[str, Any]
    phase_summary: Dict[str, Dict[str, Any]]
    output_signature: Dict[str, Any]
    report_path: Path

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": "ras-commander.raster-operation-profile/1",
            "status": "complete",
            "operation": self.operation,
            "settings": self.settings,
            "output_path": str(self.output_path),
            "elapsed_seconds": self.elapsed_seconds,
            "peak_tree_rss_mb": self.peak_tree_rss_mb,
            "peak_tree_private_mb": self.peak_tree_private_mb,
            "minimum_available_memory_mb": self.minimum_available_memory_mb,
            "minimum_commit_headroom_mb": self.minimum_commit_headroom_mb,
            "process_counters": self.process_counters,
            "samples": [sample.to_dict() for sample in self.samples],
            "performance_summary": self.performance_summary,
            "phase_summary": self.phase_summary,
            "output_signature": self.output_signature,
            "report_path": str(self.report_path),
        }

    def write_report(self) -> Path:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )
        return self.report_path


@dataclass(frozen=True)
class SystemMemorySnapshot:
    total_physical_mb: int
    available_physical_mb: int
    commit_total_mb: Optional[int]
    commit_limit_mb: Optional[int]

    @property
    def commit_headroom_mb(self) -> Optional[int]:
        if self.commit_total_mb is None or self.commit_limit_mb is None:
            return None
        return max(0, self.commit_limit_mb - self.commit_total_mb)


class _PerformanceInformation(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("CommitTotal", ctypes.c_size_t),
        ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t),
        ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t),
        ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t),
        ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t),
        ("PageSize", ctypes.c_size_t),
        ("HandleCount", ctypes.c_ulong),
        ("ProcessCount", ctypes.c_ulong),
        ("ThreadCount", ctypes.c_ulong),
    ]


def get_system_memory_snapshot() -> SystemMemorySnapshot:
    """Return physical and Windows commit state without changing the system."""
    virtual = psutil.virtual_memory()
    total_physical_mb = int(virtual.total // (1024 * 1024))
    available_physical_mb = int(virtual.available // (1024 * 1024))
    commit_total_mb = None
    commit_limit_mb = None
    if os.name == "nt":
        information = _PerformanceInformation()
        information.cb = ctypes.sizeof(information)
        try:
            success = ctypes.windll.psapi.GetPerformanceInfo(
                ctypes.byref(information),
                information.cb,
            )
        except (AttributeError, OSError):
            success = False
        if success:
            page_size = int(information.PageSize)
            commit_total_mb = int(information.CommitTotal * page_size // (1024 * 1024))
            commit_limit_mb = int(information.CommitLimit * page_size // (1024 * 1024))
    return SystemMemorySnapshot(
        total_physical_mb=total_physical_mb,
        available_physical_mb=available_physical_mb,
        commit_total_mb=commit_total_mb,
        commit_limit_mb=commit_limit_mb,
    )


class ProcessTreeProfiler:
    """Sample the current process and descendants during a profiled operation."""

    def __init__(
        self,
        sample_interval_seconds: float = 0.2,
        watch_paths: Optional[Tuple[Path, ...]] = None,
    ) -> None:
        if sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")
        self.sample_interval_seconds = sample_interval_seconds
        self.watch_paths = tuple(Path(path) for path in (watch_paths or ()))
        self.logical_cpu_count = max(1, psutil.cpu_count(logical=True) or 1)
        self.root = psutil.Process()
        self.started = time.perf_counter()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._records: Dict[int, Dict[str, Any]] = {}
        self._root_baseline = self._process_counters(self.root)
        self.peak_tree_rss_mb = 0.0
        self.peak_tree_private_mb: Optional[float] = None
        initial_memory = get_system_memory_snapshot()
        self.minimum_available_memory_mb = initial_memory.available_physical_mb
        self.minimum_commit_headroom_mb = initial_memory.commit_headroom_mb
        self.maximum_simultaneous_helpers = 0
        self.samples: list[StoreMapResourceSample] = []
        self._last_recorded_elapsed = 0.0
        self._last_grouped_counters: Dict[str, Dict[str, Union[int, float]]] = {}
        self._last_watched_output_bytes = 0
        self._last_host_counters = self._host_counters()

    @staticmethod
    def _process_counters(process: psutil.Process) -> Dict[str, Any]:
        with process.oneshot():
            memory = process.memory_info()
            try:
                private_bytes = process.memory_full_info().private
            except (
                AttributeError,
                OSError,
                psutil.AccessDenied,
                psutil.NoSuchProcess,
            ):
                # Wine does not implement the Windows
                # NtQueryVirtualMemory(MemoryWorkingSetInformation) query used
                # by psutil for USS/private-memory details and reports
                # WinError 87. RSS and any basic private counter remain useful
                # for profiling, so degrade gracefully instead of preventing
                # the raster operation from running.
                private_bytes = getattr(memory, "private", None)
            io = process.io_counters()
            cpu = process.cpu_times()
            return {
                "name": process.name(),
                "rss": int(memory.rss),
                "private": int(private_bytes) if private_bytes is not None else None,
                "threads": int(process.num_threads()),
                "cpu": float(cpu.user + cpu.system),
                "read_bytes": int(io.read_bytes),
                "write_bytes": int(io.write_bytes),
                "read_operations": int(io.read_count),
                "write_operations": int(io.write_count),
            }

    @staticmethod
    def _host_counters() -> Dict[str, Optional[int]]:
        """Return host-wide disk and network counters when available."""
        disk = psutil.disk_io_counters()
        network = psutil.net_io_counters()
        disk_busy_time = getattr(disk, "busy_time", None)
        return {
            "disk_read_bytes": int(getattr(disk, "read_bytes", 0) or 0),
            "disk_write_bytes": int(getattr(disk, "write_bytes", 0) or 0),
            "disk_read_operations": int(getattr(disk, "read_count", 0) or 0),
            "disk_write_operations": int(getattr(disk, "write_count", 0) or 0),
            "disk_read_time_ms": int(getattr(disk, "read_time", 0) or 0),
            "disk_write_time_ms": int(getattr(disk, "write_time", 0) or 0),
            "disk_busy_time_ms": (
                int(disk_busy_time) if disk_busy_time is not None else None
            ),
            "network_receive_bytes": int(getattr(network, "bytes_recv", 0) or 0),
            "network_send_bytes": int(getattr(network, "bytes_sent", 0) or 0),
        }

    def start(self) -> None:
        self._sample(force_record=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=max(2.0, self.sample_interval_seconds * 4))
        self._sample(force_record=True)

    def _run(self) -> None:
        while not self._stop.wait(self.sample_interval_seconds):
            self._sample()

    def _watched_file_snapshot(self) -> Tuple[int, int]:
        """Inspect only direct output children to avoid an SMB observer effect."""
        file_count = 0
        total_bytes = 0
        for watch_path in self.watch_paths:
            try:
                if not watch_path.is_dir():
                    continue
                with os.scandir(watch_path) as entries:
                    for entry in entries:
                        if not entry.is_file() or Path(
                            entry.name
                        ).suffix.casefold() not in {
                            ".tif",
                            ".tiff",
                            ".vrt",
                            ".hdf",
                        }:
                            continue
                        stat = entry.stat()
                        file_count += 1
                        total_bytes += stat.st_size
            except (FileNotFoundError, NotADirectoryError, OSError):
                continue
        return file_count, total_bytes

    @staticmethod
    def _infer_phase(
        process_counts: Dict[str, int],
        output_growing: bool,
    ) -> str:
        normalized = {name.casefold(): count for name, count in process_counts.items()}
        if normalized.get("gdaladdo.exe", 0):
            return "gdal_overviews"
        if normalized.get("gdal_translate.exe", 0):
            return "gdal_translate_and_tiff_write"
        if normalized.get("rasprocess.exe", 0):
            return "terrain_native"
        if normalized.get("rasstoremaphelper.exe", 0):
            if output_growing:
                return "store_map_native_output_growing"
            return "store_map_native"
        return "python_or_idle"

    def _grouped_counters_raw(
        self,
    ) -> Dict[str, Dict[str, Union[int, float]]]:
        result: Dict[str, Dict[str, Union[int, float]]] = defaultdict(
            lambda: {
                "cpu_seconds": 0.0,
                "read_bytes": 0,
                "write_bytes": 0,
                "read_operations": 0,
                "write_operations": 0,
            }
        )
        for record in self._records.values():
            latest = record.get("latest")
            if latest is None:
                continue
            baseline = record["baseline"]
            grouped = result[record["name"]]
            for key in (
                "cpu",
                "read_bytes",
                "write_bytes",
                "read_operations",
                "write_operations",
            ):
                delta = max(0, latest[key] - baseline.get(key, 0))
                target = "cpu_seconds" if key == "cpu" else key
                grouped[target] += delta
        return dict(sorted(result.items()))

    def _sample(self, force_record: bool = False) -> None:
        try:
            processes = [self.root, *self.root.children(recursive=True)]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            processes = [self.root]

        rss = 0
        private = 0
        private_known = False
        threads = 0
        counts: Dict[str, int] = defaultdict(int)
        for process in processes:
            try:
                counters = self._process_counters(process)
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
            pid = process.pid
            record = self._records.setdefault(
                pid,
                {
                    "name": counters["name"],
                    "baseline": (
                        self._root_baseline
                        if pid == self.root.pid
                        else {
                            "cpu": 0.0,
                            "read_bytes": 0,
                            "write_bytes": 0,
                            "read_operations": 0,
                            "write_operations": 0,
                        }
                    ),
                },
            )
            record["latest"] = counters
            rss += counters["rss"]
            if counters["private"] is not None:
                private += counters["private"]
                private_known = True
            threads += counters["threads"]
            counts[counters["name"]] += 1

        snapshot = get_system_memory_snapshot()
        self.peak_tree_rss_mb = max(self.peak_tree_rss_mb, rss / (1024 * 1024))
        if private_known:
            value = private / (1024 * 1024)
            self.peak_tree_private_mb = max(self.peak_tree_private_mb or 0.0, value)
        self.minimum_available_memory_mb = min(
            self.minimum_available_memory_mb,
            snapshot.available_physical_mb,
        )
        if snapshot.commit_headroom_mb is not None:
            self.minimum_commit_headroom_mb = min(
                (
                    self.minimum_commit_headroom_mb
                    if self.minimum_commit_headroom_mb is not None
                    else snapshot.commit_headroom_mb
                ),
                snapshot.commit_headroom_mb,
            )
        self.maximum_simultaneous_helpers = max(
            self.maximum_simultaneous_helpers,
            counts.get("RasStoreMapHelper.exe", 0),
        )

        elapsed = time.perf_counter() - self.started
        interval_seconds = max(0.0, elapsed - self._last_recorded_elapsed)
        if not force_record and interval_seconds < self.sample_interval_seconds * 0.5:
            return

        grouped = self._grouped_counters_raw()
        watched_file_count, watched_output_bytes = self._watched_file_snapshot()
        host_counters = self._host_counters()

        if not self.samples:
            self.samples.append(
                StoreMapResourceSample(
                    elapsed_seconds=round(elapsed, 3),
                    tree_rss_mb=round(rss / (1024 * 1024), 3),
                    tree_private_mb=(
                        round(private / (1024 * 1024), 3) if private_known else None
                    ),
                    available_physical_mb=snapshot.available_physical_mb,
                    commit_headroom_mb=snapshot.commit_headroom_mb,
                    tree_threads=threads,
                    process_counts=dict(sorted(counts.items())),
                    inferred_phase="initializing",
                    watched_file_count=watched_file_count,
                    watched_output_bytes=watched_output_bytes,
                )
            )
            self._last_recorded_elapsed = elapsed
            self._last_grouped_counters = grouped
            self._last_watched_output_bytes = watched_output_bytes
            self._last_host_counters = host_counters
            return

        metric_keys = (
            "cpu_seconds",
            "read_bytes",
            "write_bytes",
            "read_operations",
            "write_operations",
        )
        process_deltas: Dict[str, Dict[str, Union[int, float]]] = {}
        for name in set(grouped) | set(self._last_grouped_counters):
            current = grouped.get(name, {})
            previous = self._last_grouped_counters.get(name, {})
            process_deltas[name] = {
                key: max(0, current.get(key, 0) - previous.get(key, 0))
                for key in metric_keys
            }

        totals = {
            key: sum(float(values[key]) for values in process_deltas.values())
            for key in metric_keys
        }
        interval_cpu_seconds = float(totals["cpu_seconds"])
        interval_read_bytes = int(totals["read_bytes"])
        interval_write_bytes = int(totals["write_bytes"])
        interval_read_operations = int(totals["read_operations"])
        interval_write_operations = int(totals["write_operations"])
        # Windows process CPU counters are coarser than a very short forced
        # final sample. A 10 ms floor prevents meaningless rate spikes while
        # preserving cumulative counters and phase totals.
        divisor = max(interval_seconds, 0.01)
        tree_cpu_percent = interval_cpu_seconds / divisor * 100.0

        process_metrics: Dict[str, Dict[str, Union[int, float]]] = {}
        for name, delta in sorted(process_deltas.items()):
            cpu_percent = float(delta["cpu_seconds"]) / divisor * 100.0
            process_metrics[name] = {
                "cpu_percent": round(cpu_percent, 3),
                "machine_cpu_percent": round(
                    cpu_percent / self.logical_cpu_count,
                    3,
                ),
                "read_mib_per_second": round(
                    float(delta["read_bytes"]) / (1024 * 1024) / divisor,
                    3,
                ),
                "write_mib_per_second": round(
                    float(delta["write_bytes"]) / (1024 * 1024) / divisor,
                    3,
                ),
                "read_iops": round(
                    float(delta["read_operations"]) / divisor,
                    3,
                ),
                "write_iops": round(
                    float(delta["write_operations"]) / divisor,
                    3,
                ),
            }

        host_deltas: Dict[str, Optional[int]] = {}
        for key, value in host_counters.items():
            previous = self._last_host_counters.get(key)
            host_deltas[key] = (
                max(0, value - previous)
                if value is not None and previous is not None
                else None
            )
        host_disk_read_operations = host_deltas["disk_read_operations"] or 0
        host_disk_write_operations = host_deltas["disk_write_operations"] or 0
        output_growing = watched_output_bytes > self._last_watched_output_bytes
        phase = self._infer_phase(dict(counts), output_growing)
        self.samples.append(
            StoreMapResourceSample(
                elapsed_seconds=round(elapsed, 3),
                tree_rss_mb=round(rss / (1024 * 1024), 3),
                tree_private_mb=(
                    round(private / (1024 * 1024), 3) if private_known else None
                ),
                available_physical_mb=snapshot.available_physical_mb,
                commit_headroom_mb=snapshot.commit_headroom_mb,
                tree_threads=threads,
                process_counts=dict(sorted(counts.items())),
                interval_seconds=round(interval_seconds, 3),
                inferred_phase=phase,
                tree_cpu_percent=round(tree_cpu_percent, 3),
                machine_cpu_percent=round(
                    tree_cpu_percent / self.logical_cpu_count,
                    3,
                ),
                interval_cpu_seconds=round(interval_cpu_seconds, 6),
                read_mib_per_second=round(
                    interval_read_bytes / (1024 * 1024) / divisor,
                    3,
                ),
                write_mib_per_second=round(
                    interval_write_bytes / (1024 * 1024) / divisor,
                    3,
                ),
                read_iops=round(interval_read_operations / divisor, 3),
                write_iops=round(interval_write_operations / divisor, 3),
                interval_read_bytes=interval_read_bytes,
                interval_write_bytes=interval_write_bytes,
                interval_read_operations=interval_read_operations,
                interval_write_operations=interval_write_operations,
                mean_read_size_bytes=(
                    interval_read_bytes / interval_read_operations
                    if interval_read_operations
                    else None
                ),
                mean_write_size_bytes=(
                    interval_write_bytes / interval_write_operations
                    if interval_write_operations
                    else None
                ),
                watched_file_count=watched_file_count,
                watched_output_bytes=watched_output_bytes,
                host_disk_read_mib_per_second=round(
                    (host_deltas["disk_read_bytes"] or 0) / (1024 * 1024) / divisor,
                    3,
                ),
                host_disk_write_mib_per_second=round(
                    (host_deltas["disk_write_bytes"] or 0) / (1024 * 1024) / divisor,
                    3,
                ),
                host_disk_read_iops=round(
                    host_disk_read_operations / divisor,
                    3,
                ),
                host_disk_write_iops=round(
                    host_disk_write_operations / divisor,
                    3,
                ),
                host_disk_busy_equivalent_percent=(
                    round(
                        (host_deltas["disk_busy_time_ms"] or 0) / 10.0 / divisor,
                        3,
                    )
                    if host_deltas["disk_busy_time_ms"] is not None
                    else None
                ),
                host_disk_mean_read_latency_ms=(
                    (host_deltas["disk_read_time_ms"] or 0) / host_disk_read_operations
                    if host_disk_read_operations
                    else None
                ),
                host_disk_mean_write_latency_ms=(
                    (host_deltas["disk_write_time_ms"] or 0)
                    / host_disk_write_operations
                    if host_disk_write_operations
                    else None
                ),
                host_network_receive_mib_per_second=round(
                    (host_deltas["network_receive_bytes"] or 0)
                    / (1024 * 1024)
                    / divisor,
                    3,
                ),
                host_network_send_mib_per_second=round(
                    (host_deltas["network_send_bytes"] or 0) / (1024 * 1024) / divisor,
                    3,
                ),
                process_metrics=process_metrics,
            )
        )
        self._last_recorded_elapsed = elapsed
        self._last_grouped_counters = grouped
        self._last_watched_output_bytes = watched_output_bytes
        self._last_host_counters = host_counters

    def grouped_counters(self) -> Dict[str, Dict[str, Union[int, float]]]:
        result = self._grouped_counters_raw()
        for values in result.values():
            values["cpu_seconds"] = round(float(values["cpu_seconds"]), 3)
        return dict(sorted(result.items()))

    def performance_summary(self) -> Dict[str, Any]:
        counters = self._grouped_counters_raw()
        elapsed = max(
            self.samples[-1].elapsed_seconds if self.samples else 0.0,
            0.001,
        )
        cpu_seconds = sum(float(values["cpu_seconds"]) for values in counters.values())
        read_bytes = sum(int(values["read_bytes"]) for values in counters.values())
        write_bytes = sum(int(values["write_bytes"]) for values in counters.values())
        read_operations = sum(
            int(values["read_operations"]) for values in counters.values()
        )
        write_operations = sum(
            int(values["write_operations"]) for values in counters.values()
        )
        measured_samples = [
            sample for sample in self.samples if sample.interval_seconds > 0
        ]
        sampled_seconds = max(
            sum(sample.interval_seconds for sample in measured_samples),
            0.001,
        )
        host_busy_samples = [
            sample
            for sample in measured_samples
            if sample.host_disk_busy_equivalent_percent is not None
        ]
        host_read_operations = sum(
            sample.host_disk_read_iops * sample.interval_seconds
            for sample in measured_samples
        )
        host_write_operations = sum(
            sample.host_disk_write_iops * sample.interval_seconds
            for sample in measured_samples
        )
        return {
            "logical_cpu_count": self.logical_cpu_count,
            "cpu_percent_semantics": (
                "tree_cpu_percent uses 100 percent per fully utilized logical CPU; "
                "machine_cpu_percent divides by logical_cpu_count"
            ),
            "io_counter_semantics": (
                "process I/O transfer counters include cached and remote file I/O; "
                "they are not physical disk queue or latency counters"
            ),
            "host_counter_semantics": (
                "host disk and network rates are machine-wide and can include "
                "unrelated activity; disk busy is 100 percent per concurrently "
                "busy physical device, can exceed 100 percent, and is null when "
                "the platform does not expose busy time"
            ),
            "phase_inference_semantics": (
                "phases are inferred from descendant executable names and direct "
                "output-file growth; metrics cover the whole process tree and can "
                "represent mixed work when parallel descendants overlap; treat "
                "very short phase transitions as approximate"
            ),
            "cpu_seconds": round(cpu_seconds, 3),
            "average_tree_cpu_percent": round(cpu_seconds / elapsed * 100.0, 3),
            "average_machine_cpu_percent": round(
                cpu_seconds / elapsed / self.logical_cpu_count * 100.0,
                3,
            ),
            "peak_tree_cpu_percent": max(
                (sample.tree_cpu_percent for sample in self.samples),
                default=0.0,
            ),
            "peak_machine_cpu_percent": max(
                (sample.machine_cpu_percent for sample in self.samples),
                default=0.0,
            ),
            "average_read_mib_per_second": round(
                read_bytes / (1024 * 1024) / elapsed,
                3,
            ),
            "average_write_mib_per_second": round(
                write_bytes / (1024 * 1024) / elapsed,
                3,
            ),
            "peak_read_mib_per_second": max(
                (sample.read_mib_per_second for sample in self.samples),
                default=0.0,
            ),
            "peak_write_mib_per_second": max(
                (sample.write_mib_per_second for sample in self.samples),
                default=0.0,
            ),
            "average_read_iops": round(read_operations / elapsed, 3),
            "average_write_iops": round(write_operations / elapsed, 3),
            "peak_read_iops": max(
                (sample.read_iops for sample in self.samples),
                default=0.0,
            ),
            "peak_write_iops": max(
                (sample.write_iops for sample in self.samples),
                default=0.0,
            ),
            "mean_read_size_bytes": (
                read_bytes / read_operations if read_operations else None
            ),
            "mean_write_size_bytes": (
                write_bytes / write_operations if write_operations else None
            ),
            "average_host_disk_read_mib_per_second": round(
                sum(
                    sample.host_disk_read_mib_per_second * sample.interval_seconds
                    for sample in measured_samples
                )
                / sampled_seconds,
                3,
            ),
            "average_host_disk_write_mib_per_second": round(
                sum(
                    sample.host_disk_write_mib_per_second * sample.interval_seconds
                    for sample in measured_samples
                )
                / sampled_seconds,
                3,
            ),
            "average_host_disk_read_iops": round(
                host_read_operations / sampled_seconds,
                3,
            ),
            "average_host_disk_write_iops": round(
                host_write_operations / sampled_seconds,
                3,
            ),
            "average_host_disk_busy_equivalent_percent": (
                round(
                    sum(
                        (sample.host_disk_busy_equivalent_percent or 0.0)
                        * sample.interval_seconds
                        for sample in host_busy_samples
                    )
                    / max(
                        sum(sample.interval_seconds for sample in host_busy_samples),
                        0.001,
                    ),
                    3,
                )
                if host_busy_samples
                else None
            ),
            "average_host_disk_read_latency_ms": (
                sum(
                    (sample.host_disk_mean_read_latency_ms or 0.0)
                    * sample.host_disk_read_iops
                    * sample.interval_seconds
                    for sample in measured_samples
                )
                / host_read_operations
                if host_read_operations
                else None
            ),
            "average_host_disk_write_latency_ms": (
                sum(
                    (sample.host_disk_mean_write_latency_ms or 0.0)
                    * sample.host_disk_write_iops
                    * sample.interval_seconds
                    for sample in measured_samples
                )
                / host_write_operations
                if host_write_operations
                else None
            ),
            "average_host_network_receive_mib_per_second": round(
                sum(
                    sample.host_network_receive_mib_per_second * sample.interval_seconds
                    for sample in measured_samples
                )
                / sampled_seconds,
                3,
            ),
            "average_host_network_send_mib_per_second": round(
                sum(
                    sample.host_network_send_mib_per_second * sample.interval_seconds
                    for sample in measured_samples
                )
                / sampled_seconds,
                3,
            ),
            "peak_host_disk_read_mib_per_second": max(
                (sample.host_disk_read_mib_per_second for sample in self.samples),
                default=0.0,
            ),
            "peak_host_disk_write_mib_per_second": max(
                (sample.host_disk_write_mib_per_second for sample in self.samples),
                default=0.0,
            ),
            "peak_host_disk_read_iops": max(
                (sample.host_disk_read_iops for sample in self.samples),
                default=0.0,
            ),
            "peak_host_disk_write_iops": max(
                (sample.host_disk_write_iops for sample in self.samples),
                default=0.0,
            ),
            "peak_host_disk_busy_equivalent_percent": (
                max(
                    sample.host_disk_busy_equivalent_percent
                    for sample in host_busy_samples
                )
                if host_busy_samples
                else None
            ),
            "peak_host_network_receive_mib_per_second": max(
                (sample.host_network_receive_mib_per_second for sample in self.samples),
                default=0.0,
            ),
            "peak_host_network_send_mib_per_second": max(
                (sample.host_network_send_mib_per_second for sample in self.samples),
                default=0.0,
            ),
        }

    def phase_summary(self) -> Dict[str, Dict[str, Any]]:
        phases: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "elapsed_seconds": 0.0,
                "cpu_seconds": 0.0,
                "read_bytes": 0,
                "write_bytes": 0,
                "read_operations": 0,
                "write_operations": 0,
                "peak_tree_rss_mb": 0.0,
                "peak_tree_private_mb": 0.0,
                "host_disk_read_mib": 0.0,
                "host_disk_write_mib": 0.0,
                "host_disk_read_operations": 0.0,
                "host_disk_write_operations": 0.0,
                "host_disk_busy_percent_seconds": 0.0,
                "host_disk_busy_seconds": 0.0,
                "host_network_receive_mib": 0.0,
                "host_network_send_mib": 0.0,
                "peak_host_disk_busy_equivalent_percent": 0.0,
            }
        )
        for sample in self.samples:
            if sample.interval_seconds <= 0:
                continue
            phase = phases[sample.inferred_phase]
            phase["elapsed_seconds"] += sample.interval_seconds
            phase["cpu_seconds"] += sample.interval_cpu_seconds
            phase["read_bytes"] += sample.interval_read_bytes
            phase["write_bytes"] += sample.interval_write_bytes
            phase["read_operations"] += sample.interval_read_operations
            phase["write_operations"] += sample.interval_write_operations
            phase["peak_tree_rss_mb"] = max(
                phase["peak_tree_rss_mb"],
                sample.tree_rss_mb,
            )
            phase["peak_tree_private_mb"] = max(
                phase["peak_tree_private_mb"],
                sample.tree_private_mb or 0.0,
            )
            phase["host_disk_read_mib"] += (
                sample.host_disk_read_mib_per_second * sample.interval_seconds
            )
            phase["host_disk_write_mib"] += (
                sample.host_disk_write_mib_per_second * sample.interval_seconds
            )
            phase["host_disk_read_operations"] += (
                sample.host_disk_read_iops * sample.interval_seconds
            )
            phase["host_disk_write_operations"] += (
                sample.host_disk_write_iops * sample.interval_seconds
            )
            if sample.host_disk_busy_equivalent_percent is not None:
                phase["host_disk_busy_percent_seconds"] += (
                    sample.host_disk_busy_equivalent_percent * sample.interval_seconds
                )
                phase["host_disk_busy_seconds"] += sample.interval_seconds
            phase["host_network_receive_mib"] += (
                sample.host_network_receive_mib_per_second * sample.interval_seconds
            )
            phase["host_network_send_mib"] += (
                sample.host_network_send_mib_per_second * sample.interval_seconds
            )
            phase["peak_host_disk_busy_equivalent_percent"] = max(
                phase["peak_host_disk_busy_equivalent_percent"],
                sample.host_disk_busy_equivalent_percent or 0.0,
            )

        result: Dict[str, Dict[str, Any]] = {}
        for name, phase in sorted(phases.items()):
            seconds = max(float(phase["elapsed_seconds"]), 0.001)
            read_operations = int(phase["read_operations"])
            write_operations = int(phase["write_operations"])
            read_bytes = int(phase["read_bytes"])
            write_bytes = int(phase["write_bytes"])
            result[name] = {
                "elapsed_seconds": round(seconds, 3),
                "cpu_seconds": round(float(phase["cpu_seconds"]), 3),
                "average_tree_cpu_percent": round(
                    float(phase["cpu_seconds"]) / seconds * 100.0,
                    3,
                ),
                "average_machine_cpu_percent": round(
                    float(phase["cpu_seconds"])
                    / seconds
                    / self.logical_cpu_count
                    * 100.0,
                    3,
                ),
                "read_mib": round(read_bytes / (1024 * 1024), 3),
                "write_mib": round(write_bytes / (1024 * 1024), 3),
                "average_read_mib_per_second": round(
                    read_bytes / (1024 * 1024) / seconds,
                    3,
                ),
                "average_write_mib_per_second": round(
                    write_bytes / (1024 * 1024) / seconds,
                    3,
                ),
                "read_operations": read_operations,
                "write_operations": write_operations,
                "average_read_iops": round(read_operations / seconds, 3),
                "average_write_iops": round(write_operations / seconds, 3),
                "mean_read_size_bytes": (
                    read_bytes / read_operations if read_operations else None
                ),
                "mean_write_size_bytes": (
                    write_bytes / write_operations if write_operations else None
                ),
                "peak_tree_rss_mb": round(float(phase["peak_tree_rss_mb"]), 3),
                "peak_tree_private_mb": round(
                    float(phase["peak_tree_private_mb"]),
                    3,
                ),
                "average_host_disk_read_mib_per_second": round(
                    float(phase["host_disk_read_mib"]) / seconds,
                    3,
                ),
                "average_host_disk_write_mib_per_second": round(
                    float(phase["host_disk_write_mib"]) / seconds,
                    3,
                ),
                "average_host_disk_read_iops": round(
                    float(phase["host_disk_read_operations"]) / seconds,
                    3,
                ),
                "average_host_disk_write_iops": round(
                    float(phase["host_disk_write_operations"]) / seconds,
                    3,
                ),
                "average_host_disk_busy_equivalent_percent": (
                    round(
                        float(phase["host_disk_busy_percent_seconds"])
                        / max(float(phase["host_disk_busy_seconds"]), 0.001),
                        3,
                    )
                    if phase["host_disk_busy_seconds"]
                    else None
                ),
                "peak_host_disk_busy_equivalent_percent": (
                    round(
                        float(phase["peak_host_disk_busy_equivalent_percent"]),
                        3,
                    )
                    if phase["host_disk_busy_seconds"]
                    else None
                ),
                "average_host_network_receive_mib_per_second": round(
                    float(phase["host_network_receive_mib"]) / seconds,
                    3,
                ),
                "average_host_network_send_mib_per_second": round(
                    float(phase["host_network_send_mib"]) / seconds,
                    3,
                ),
            }
        return result
