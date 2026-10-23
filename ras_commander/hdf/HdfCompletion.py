"""Read-only result-clock coverage, separate from execution-success policy."""

from pathlib import Path
from typing import Union

import h5py
import numpy as np

from ..Decorators import log_call, standardize_input
from ..fast_hdf import read_attr, read_typed
from ..LoggingConfig import get_logger
from .HdfUtils import HdfUtils


logger = get_logger(__name__)


class HdfCompletion:
    """Inspect stored output evidence without treating requested dates as results."""

    @staticmethod
    @log_call
    @standardize_input(file_type="plan_hdf")
    def inspect_time_coverage(hdf_file: Union[h5py.File, str, Path]) -> dict:
        """Compare the Base Output clock with the declared simulation window.

        Returns a dictionary with ``status`` (``covered``, ``not_covered``,
        ``unsupported`` or ``not_applicable``), ``reason``, declared/observed
        endpoints and row count. ``covered`` only means the stored clock spans
        the requested window; it is not a claim of solver or hydraulic success,
        nor a validation of every result array. Missing/malformed evidence is
        unsupported, never successful. Pure steady results are not applicable.

        No output-cadence allowance is applied: an output ending before the
        declared end is ``not_covered``, including off-cadence ends. Native
        execution completion is separate from literal clock coverage.
        Native 6.6 and 7.0.1 qualification runs completed
        a 17-minute simulation with five-minute output ending at minute 15;
        this inspector reports ``not_covered`` for those stored clocks.
        No completion policy in RasCmdr is changed by this inspector.
        Numeric Time alone is not promoted to calendar evidence; milliseconds
        take priority, with a seconds-only fallback for legacy output.

        Args:
            hdf_file: Open HDF handle, plan-HDF path, or plan number. The input
                decorator accepts ``ras_object=`` for project resolution.

        Returns:
            dict: Coverage status, reason, clock source, row count and declared
            and observed endpoints. Endpoints are naive ``datetime`` objects
            in the stored model clock, or None when evidence is unavailable.

        Raises:
            OSError: The input HDF cannot be opened or read.
        """
        result = {
            "status": "unsupported", "reason": None,
            "declared_start": None, "declared_end": None,
            "observed_start": None, "observed_end": None,
            "row_count": 0, "clock_source": None,
        }

        def text(value):
            if isinstance(value, bytes):
                return value.decode("utf-8").strip()
            if isinstance(value, str):
                return value.strip()
            raise ValueError("Expected a scalar string")

        def unsupported(reason):
            result["reason"] = reason
            logger.debug("Unsupported output clock in %s: %s", hdf_file.filename, reason)
            return result

        if "Results/Unsteady" not in hdf_file:
            if "Results/Steady" in hdf_file:
                result.update(status="not_applicable", reason="steady_profiles_have_no_clock")
                return result
            return unsupported("unknown_result_layout")
        if "Results/Steady" in hdf_file:
            return unsupported("mixed_steady_unsteady_results")

        info = hdf_file.get("Plan Data/Plan Information")
        if not isinstance(info, h5py.Group):
            return unsupported("missing_plan_information")
        try:
            start = read_attr(info, "Simulation Start Time", None)
            end = read_attr(info, "Simulation End Time", None)
            window = read_attr(info, "Time Window", None)
            declared = None
            if start is not None or end is not None:
                if start is None or end is None:
                    return unsupported("partial_declared_window")
                declared = tuple(HdfUtils.parse_ras_datetime(text(v)) for v in (start, end))
            if window is not None:
                parts = text(window).split(" to ")
                if len(parts) != 2:
                    return unsupported("invalid_declared_window")
                legacy = tuple(HdfUtils.parse_ras_datetime(v.strip()) for v in parts)
                if declared is not None and legacy != declared:
                    return unsupported("conflicting_declared_windows")
                declared = legacy
            if declared is None:
                return unsupported("missing_declared_window")
            result["declared_start"], result["declared_end"] = declared
            if declared[1] <= declared[0]:
                return unsupported("invalid_declared_window")
        except (ValueError, TypeError, UnicodeError):
            return unsupported("invalid_declared_window")

        base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
        group = hdf_file.get(base)
        if not isinstance(group, h5py.Group):
            return unsupported("missing_base_output_clock")
        clocks = []
        for name, parse in (
            ("Time Date Stamp (ms)", HdfUtils.parse_ras_datetime_ms),
            ("Time Date Stamp", HdfUtils.parse_ras_datetime),
        ):
            dataset = group.get(name)
            if dataset is None:
                continue
            if not isinstance(dataset, h5py.Dataset) or dataset.ndim != 1 or dataset.size == 0:
                return unsupported("invalid_timestamp_axis")
            try:
                stamps = [parse(text(value)) for value in read_typed(dataset, slice(None))]
            except (ValueError, TypeError, UnicodeError, OverflowError):
                return unsupported("invalid_timestamp_axis")
            # Seconds-only output can repeat for subsecond computations.
            if any(right < left for left, right in zip(stamps, stamps[1:])):
                return unsupported("nonmonotonic_timestamp_axis")
            clocks.append((name, stamps))
        if not clocks:
            return unsupported("missing_timestamp_axis")
        source, stamps = clocks[0]
        if len(clocks) == 2:
            seconds = clocks[1][1]
            if len(seconds) != len(stamps) or any(
                a.replace(microsecond=0) != b for a, b in zip(stamps, seconds)
            ):
                return unsupported("conflicting_timestamp_axes")
        numeric = group.get("Time")
        if (
            not isinstance(numeric, h5py.Dataset) or numeric.ndim != 1
            or numeric.shape[0] != len(stamps) or numeric.dtype.kind not in "fiu"
        ):
            return unsupported("invalid_numeric_time_axis")
        values = read_typed(numeric, slice(None))
        if not np.all(np.isfinite(values)) or np.any(values[1:] <= values[:-1]):
            return unsupported("invalid_numeric_time_axis")
        result.update(
            observed_start=stamps[0], observed_end=stamps[-1],
            row_count=len(stamps), clock_source=f"{base}/{source}",
        )
        if stamps[0] > declared[0]:
            result.update(status="not_covered", reason="start_not_observed")
        elif stamps[-1] < declared[1]:
            result.update(status="not_covered", reason="end_not_observed")
        else:
            result.update(status="covered", reason="stored_clock_spans_declared_window")
        return result
