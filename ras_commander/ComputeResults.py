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
