"""pythonnet helpers for HEC-RAS/RAS Mapper interop."""

from .clr_bootstrap import find_hecras_install, is_hecras_available, load_clr
from ._profile_interop import (
    query_polyline_flow,
    query_polyline_flow_timeseries,
    query_polyline_pipe_flow,
    query_polyline_pipe_flow_timeseries,
    query_polyline_pipe_velocity,
    query_polyline_pipe_velocity_timeseries,
    query_polyline_velocity,
    query_polyline_velocity_difference,
    query_polyline_velocity_timeseries,
    query_polyline_wse,
    query_polyline_wse_difference,
    query_polyline_wse_timeseries,
)

__all__ = [
    "find_hecras_install",
    "is_hecras_available",
    "load_clr",
    "query_polyline_flow",
    "query_polyline_flow_timeseries",
    "query_polyline_pipe_flow",
    "query_polyline_pipe_flow_timeseries",
    "query_polyline_pipe_velocity",
    "query_polyline_pipe_velocity_timeseries",
    "query_polyline_velocity",
    "query_polyline_velocity_difference",
    "query_polyline_velocity_timeseries",
    "query_polyline_wse",
    "query_polyline_wse_difference",
    "query_polyline_wse_timeseries",
]
