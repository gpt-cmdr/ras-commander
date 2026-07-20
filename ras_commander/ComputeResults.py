"""
ComputeResults - Backward-compatible result dataclasses for compute functions.

These dataclasses wrap execution results with additional results_df data while
preserving backward compatibility with existing code that uses bool, Dict, or Tuple returns.

Classes:
    ComputeResult: Result of compute_plan() - backward compatible with bool
    ComputeParallelResult: Result of compute_parallel/test_mode - backward compatible with Dict[str, bool]
    RasControlResult: Result of RasControl.run_plan() - backward compatible with Tuple[bool, List[str]]
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Iterator, Tuple, Any
import pandas as pd


@dataclass
class ComputeResult:
    """
    Result of RasCmdr.compute_plan().

    Backward compatible with bool via __bool__. Existing code like
    ``if RasCmdr.compute_plan("01"):`` continues to work unchanged.

    Attributes:
        success: Whether the execution succeeded.
        results_df_row: Single row from results_df for the executed plan,
            or None if unavailable (e.g., failed execution, dest_folder used,
            or results_df extraction error).

    Examples:
        # Old usage (still works):
        if RasCmdr.compute_plan("01"):
            print("done")

        # New usage:
        result = RasCmdr.compute_plan("01")
        if result:
            print(result.results_df_row['runtime_complete_process_hours'])
    """
    success: bool
    results_df_row: Optional[pd.Series] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        has_row = self.results_df_row is not None
        return f"ComputeResult({status}, results_df_row={'available' if has_row else 'None'})"


@dataclass
class ComputeParallelResult:
    """
    Result of RasCmdr.compute_parallel() and compute_test_mode().

    Backward compatible with Dict[str, bool] via __getitem__, items(), keys(), values().
    Existing code like ``for plan, ok in results.items():`` continues to work unchanged.

    Attributes:
        execution_results: Dict mapping plan numbers to success booleans.
        results_df: DataFrame containing results_df rows for executed plans only.
            May be empty if no results could be extracted.

    Examples:
        # Old usage (still works):
        results = RasCmdr.compute_parallel(["01", "02"])
        for plan, ok in results.items():
            print(f"{plan}: {ok}")

        # New usage:
        results = RasCmdr.compute_parallel(["01", "02"])
        print(results.results_df[['plan_number', 'completed', 'vol_error_percent']])

    Note:
        __bool__ returns True if execution_results has any entries,
        False if empty (whether due to error or no plans to execute).
    """
    execution_results: Dict[str, bool] = field(default_factory=dict)
    results_df: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())

    def __getitem__(self, key: str) -> bool:
        return self.execution_results[key]

    def __contains__(self, key: str) -> bool:
        return key in self.execution_results

    def __iter__(self) -> Iterator[str]:
        return iter(self.execution_results)

    def __len__(self) -> int:
        return len(self.execution_results)

    def __bool__(self) -> bool:
        return bool(self.execution_results)

    def items(self):
        return self.execution_results.items()

    def keys(self):
        return self.execution_results.keys()

    def values(self):
        return self.execution_results.values()

    def get(self, key: str, default: Any = None) -> Any:
        return self.execution_results.get(key, default)

    def __repr__(self) -> str:
        n_success = sum(1 for v in self.execution_results.values() if v)
        n_total = len(self.execution_results)
        return f"ComputeParallelResult({n_success}/{n_total} succeeded, results_df={len(self.results_df)} rows)"


@dataclass
class RasControlResult:
    """
    Result of RasControl.run_plan().

    Backward compatible with Tuple[bool, List[str]] via __iter__.
    Existing code like ``success, msgs = RasControl.run_plan("01")`` continues to work.

    Attributes:
        success: Whether the execution succeeded.
        messages: List of computation messages from HEC-RAS COM interface.
        results_df_row: Single row from results_df for the executed plan,
            or None if unavailable.

    Examples:
        # Old usage (still works):
        success, msgs = RasControl.run_plan("01")

        # New usage - access results_df_row (requires attribute access):
        result = RasControl.run_plan("01")
        if result.results_df_row is not None:
            print(result.results_df_row['runtime_complete_process_hours'])

    Note:
        results_df_row is only accessible via attribute access, not tuple
        unpacking. Tuple unpacking (``success, msgs = ...``) only yields
        success and messages via __iter__.
    """
    success: bool
    messages: List[str] = field(default_factory=list)
    results_df_row: Optional[pd.Series] = None

    def __bool__(self) -> bool:
        return self.success

    def __iter__(self) -> Iterator:
        return iter((self.success, self.messages))

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        n_msgs = len(self.messages)
        has_row = self.results_df_row is not None
        return f"RasControlResult({status}, {n_msgs} messages, results_df_row={'available' if has_row else 'None'})"


@dataclass
class PreprocessResult:
    """
    Result of RasPreprocess.preprocess_plan().

    Backward compatible with bool via __bool__. Existing code like
    ``if RasPreprocess.preprocess_plan("01"):`` works unchanged.

    Attributes:
        success: Whether preprocessing succeeded.
        plan_number: Plan number that was preprocessed (e.g., "01").
        geometry_number: Geometry number extracted from plan file (e.g., "04").
        tmp_hdf_path: Path to the generated .tmp.hdf file, or None on failure.
        b_file_path: Path to the generated .b## file, or None on failure.
        x_file_path: Path to the generated .x## file, or None on failure.
        elapsed_seconds: Wall-clock time for preprocessing.
        error: Error message if preprocessing failed, None on success.

    Examples:
        # Simple usage (bool-compatible):
        if RasPreprocess.preprocess_plan("01"):
            print("Ready for Linux execution")

        # Rich usage:
        result = RasPreprocess.preprocess_plan("01")
        if result:
            print(f"Completed in {result.elapsed_seconds:.1f}s")
            print(f"  tmp.hdf: {result.tmp_hdf_path}")
            print(f"  .b file: {result.b_file_path}")
            print(f"  .x file: {result.x_file_path}")
    """
    success: bool
    plan_number: str = ""
    geometry_number: Optional[str] = None
    tmp_hdf_path: Optional[Path] = None
    b_file_path: Optional[Path] = None
    x_file_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return f"PreprocessResult({status}, plan={self.plan_number}, geom={self.geometry_number}, time={time_str})"


@dataclass
class GeometryPreprocessResult:
    """
    Result of GeomPreprocessor.run_geometry_preprocessor().

    This result is for delivery/assembly validation: run the HEC-RAS geometry
    preprocessor, capture detailed compute messages, and report whether blocking
    errors were found. It is intentionally separate from ``PreprocessResult``,
    which is tuned for creating Linux unsteady-compute prerequisite files.
    """
    success: bool
    plan_number: str = ""
    geometry_number: Optional[str] = None
    flow_type: str = "Unknown"
    elapsed_seconds: float = 0.0
    command: str = ""
    return_code: Optional[int] = None
    signal_detected: Optional[str] = None
    compute_message_paths: List[Path] = field(default_factory=list)
    artifact_paths: List[Path] = field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    first_error_line: Optional[str] = None
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return (
            "GeometryPreprocessResult("
            f"{status}, plan={self.plan_number}, geom={self.geometry_number}, "
            f"flow_type={self.flow_type}, time={time_str})"
        )


@dataclass
class GeometryLayerResult:
    """
    Result of a single RasGeometryCompute layer-generation call.

    Returned by RasGeometryCompute.generate_edge_lines() /
    generate_interpolation_surface() / generate_flow_paths(). Backward compatible
    with bool via __bool__.

    Attributes:
        success: Whether the layer was generated (or already present when skipped).
        layer: Native HDF group written, e.g. "River Edge Lines".
        geom_hdf_path: Geometry HDF that was operated on.
        skipped: True when the layer already existed and overwrite=False.
        backup_path: Path to the dated GeoJSON backup of pre-existing features,
            when one was written before overwriting.
        elapsed_seconds: Wall-clock time for the generation call.
        error: Error message on failure, else None.
    """
    success: bool
    layer: str
    geom_hdf_path: Path
    skipped: bool = False
    backup_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        if self.skipped:
            status = 'SKIPPED'
        elif self.success:
            status = 'SUCCESS'
        else:
            status = 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return f"GeometryLayerResult({status}, layer={self.layer!r}, time={time_str})"


@dataclass
class GeometryCompleteResult:
    """
    Result of RasGeometryCompute.compute_geometry() (RASGeometry.CompleteForComputations).

    Backward compatible with bool via __bool__. Distinct from
    GeometryPreprocessResult, which wraps HEC-RAS's numerical geometry
    preprocessor (a different pipeline).

    Attributes:
        success: Whether the geometry-completion pipeline succeeded.
        geom_hdf_path: Geometry HDF that was completed.
        edge_lines_written: River Edge Lines present after the run.
        interpolation_surface_written: XS Interpolation Surfaces present after the run.
        flow_paths_written: River Flow Paths present after the run.
        backup_path: Path to a dated GeoJSON backup written before overwriting, if any.
        elapsed_seconds: Wall-clock time for the call.
        error: Error message on failure, else None.
    """
    success: bool
    geom_hdf_path: Path
    edge_lines_written: bool = False
    interpolation_surface_written: bool = False
    flow_paths_written: bool = False
    backup_path: Optional[Path] = None
    elapsed_seconds: float = 0.0
    error: Optional[str] = None

    def __bool__(self) -> bool:
        return self.success

    def __repr__(self) -> str:
        status = 'SUCCESS' if self.success else 'FAILED'
        time_str = f"{self.elapsed_seconds:.1f}s" if self.elapsed_seconds > 0 else "N/A"
        return (
            f"GeometryCompleteResult({status}, "
            f"edge_lines={self.edge_lines_written}, "
            f"interp_surface={self.interpolation_surface_written}, "
            f"flow_paths={self.flow_paths_written}, time={time_str})"
        )
