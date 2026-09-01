"""Extract independent, single-reach HEC-RAS 1D steady breakouts.

The MVP intentionally fails closed outside one continuous 1D reach and one
steady-flow plan. Geometry node blocks are copied verbatim. The river centerline
is clipped to the retained boundary cross sections and the downstream retained
cross section's reach-length triplet is reset to zero because there is no
downstream cross section in the destination model.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasPrj import RasPrj


logger = get_logger(__name__)


_TYPE_RM_PREFIX = "Type RM Length L Ch R ="
_NUMBER_RE = re.compile(r"[-+]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][-+]?\d+)?")


@dataclass(frozen=True)
class Breakout1DSelection:
    """A resolved continuous cross-section slice on one river/reach."""

    river: str
    reach: str
    stations: tuple[str, ...]
    upstream_station: str
    downstream_station: str
    selector: str = "stations"


@dataclass(frozen=True)
class Breakout1DDomainSelection:
    """Nested selections for computation and inundation-raster export.

    ``direct_selection`` is the cross-section span intersected by the network
    edge. ``inundation_selection`` adds the requested shared downstream cross
    section. ``computation_selection`` adds hydraulic buffer distance while
    always containing the inundation selection.
    """

    direct_selection: Breakout1DSelection
    inundation_selection: Breakout1DSelection
    computation_selection: Breakout1DSelection
    inside_fraction: Optional[float]
    main_channel_length: float
    upstream_buffer_distance: float
    downstream_buffer_distance: float
    upstream_buffer_applied: float
    downstream_buffer_applied: float
    automatic_upstream_buffer: bool
    automatic_downstream_buffer: bool
    inundation_overlap_xs: int
    inundation_overlap_xs_applied: int


@dataclass
class Breakout1DValidationReport:
    """Structural checks for an extracted breakout."""

    checks_df: pd.DataFrame

    @property
    def is_valid(self) -> bool:
        errors = self.checks_df[self.checks_df["severity"] == "ERROR"]
        return bool(errors.empty or errors["passed"].all())

    def raise_for_errors(self) -> None:
        """Raise when any structural error check failed."""
        failures = self.checks_df[
            (self.checks_df["severity"] == "ERROR") & (~self.checks_df["passed"])
        ]
        if not failures.empty:
            detail = "; ".join(failures["detail"].astype(str).tolist())
            raise ValueError(f"Breakout structural validation failed: {detail}")


@dataclass
class Breakout1DResult:
    """Artifacts and initialized project objects produced by extraction."""

    source_ras: RasPrj
    destination_ras: RasPrj
    selection: Breakout1DSelection
    project_file: Path
    plan_file: Path
    geometry_file: Path
    flow_file: Path
    validation: Breakout1DValidationReport
    boundary_provenance: str
    source_geometry_sha256: str
    compute_result: Any = None


@dataclass(frozen=True)
class _NodeBlock:
    start: int
    end: int
    type_code: int
    station: str


class RasBreakout1D:
    """Static workflow for extracting an independent 1D steady breakout."""

    @staticmethod
    @log_call
    def select_by_stations(
        geom_file: Union[str, Path],
        river: str,
        reach: str,
        upstream_station: Union[str, float, int],
        downstream_station: Union[str, float, int],
    ) -> Breakout1DSelection:
        """Select every cross section between inclusive station bounds."""
        xs_df = RasBreakout1D._reach_cross_sections(geom_file, river, reach)
        upstream = RasBreakout1D._station_value(upstream_station)
        downstream = RasBreakout1D._station_value(downstream_station)
        if upstream <= downstream:
            raise ValueError(
                "upstream_station must be greater than downstream_station for "
                "the one-reach MVP"
            )

        station_values = xs_df["RS"].map(RasBreakout1D._station_value)
        selected = xs_df[(station_values <= upstream) & (station_values >= downstream)]
        if len(selected) < 2:
            raise ValueError(
                "Station bounds must retain at least two cross sections; "
                f"found {len(selected)}"
            )
        selected = selected.assign(
            _station_value=selected["RS"].map(RasBreakout1D._station_value)
        )
        selected = selected.sort_values("_station_value", ascending=False)
        return Breakout1DSelection(
            river=river,
            reach=reach,
            stations=tuple(selected["RS"].astype(str)),
            upstream_station=str(selected.iloc[0]["RS"]),
            downstream_station=str(selected.iloc[-1]["RS"]),
            selector="stations",
        )

    @staticmethod
    @log_call
    def select_by_cross_sections(
        geom_file: Union[str, Path],
        river: str,
        reach: str,
        stations: Sequence[Union[str, float, int]],
    ) -> Breakout1DSelection:
        """Resolve a supplied, contiguous cross-section set on one reach.

        Non-contiguous sets fail closed.  A later multi-segment workflow can
        define how gaps should be reconnected without weakening this contract.
        """
        xs_df = RasBreakout1D._reach_cross_sections(geom_file, river, reach)
        if len(stations) < 2:
            raise ValueError("At least two cross sections are required")

        requested = {RasBreakout1D._station_value(value) for value in stations}
        source_values = [RasBreakout1D._station_value(value) for value in xs_df["RS"]]
        missing = sorted(requested.difference(source_values), reverse=True)
        if missing:
            raise ValueError(f"Cross sections are absent from the reach: {missing}")

        positions = sorted(source_values.index(value) for value in requested)
        expected_positions = list(range(positions[0], positions[-1] + 1))
        if positions != expected_positions:
            raise ValueError(
                "Supplied cross sections must be a contiguous source-reach slice"
            )

        selected = xs_df.iloc[positions[0] : positions[-1] + 1].copy()
        selected = selected.assign(
            _station_value=selected["RS"].map(RasBreakout1D._station_value)
        )
        selected = selected.sort_values("_station_value", ascending=False)
        return Breakout1DSelection(
            river=river,
            reach=reach,
            stations=tuple(selected["RS"].astype(str)),
            upstream_station=str(selected.iloc[0]["RS"]),
            downstream_station=str(selected.iloc[-1]["RS"]),
            selector="cross_sections",
        )

    @staticmethod
    @log_call
    def select_by_polygon(
        geom_file: Union[str, Path],
        polygon: Any,
        *,
        river: Optional[str] = None,
        reach: Optional[str] = None,
    ) -> Breakout1DSelection:
        """Select the continuous reach span whose XS cut lines intersect a polygon.

        The polygon and geometry cut lines must use the same coordinate system.
        If ``river`` and ``reach`` are omitted, the intersections must resolve to
        exactly one reach.
        """
        reach_xs, start, end = RasBreakout1D._intersecting_xs_span(
            geom_file,
            polygon,
            river=river,
            reach=reach,
            geometry_label="Polygon",
        )
        return RasBreakout1D._selection_from_reach_positions(
            reach_xs,
            start,
            end,
            selector="polygon",
            minimum_cross_sections=2,
        )

    @staticmethod
    @log_call
    def select_by_network_edge(
        geom_file: Union[str, Path],
        network_edge: Any,
        *,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        tolerance: float = 0.0,
        downstream_overlap_xs: int = 1,
        upstream_buffer_distance: float = 0.0,
        downstream_buffer_distance: float = 0.0,
    ) -> Breakout1DSelection:
        """Select the continuous XS span associated with a network edge.

        ``network_edge`` must be a Shapely-like line in the geometry coordinate
        system. A positive ``tolerance`` buffers it in spatial coordinate-system
        units before testing intersections. Optional upstream and downstream
        buffer distances use HEC-RAS main-channel reach-length/model units. The
        first cross section at or beyond each requested distance is retained, or
        selection stops at the reach terminus.

        By default, the selection also includes the next cross section
        downstream of the distance-buffered span. That shared boundary section
        preserves the Ripple1D breakout convention and gives an internal reach
        a usable downstream boundary.

        Set ``downstream_overlap_xs=0`` to retain only directly intersected cross
        sections.  Values greater than one are supported for workflows that
        need a wider shared transition zone; the selection stops at the source
        reach boundary when fewer downstream sections are available.
        """
        if isinstance(downstream_overlap_xs, bool) or not isinstance(
            downstream_overlap_xs, int
        ):
            raise TypeError("downstream_overlap_xs must be an integer")
        if downstream_overlap_xs < 0:
            raise ValueError("downstream_overlap_xs must be non-negative")
        upstream_buffer_distance = RasBreakout1D._nonnegative_distance(
            upstream_buffer_distance, "upstream_buffer_distance"
        )
        downstream_buffer_distance = RasBreakout1D._nonnegative_distance(
            downstream_buffer_distance, "downstream_buffer_distance"
        )
        selection = RasBreakout1D._direct_network_edge_selection(
            geom_file,
            network_edge,
            river=river,
            reach=reach,
            tolerance=tolerance,
        )
        selection, _, _ = RasBreakout1D._expand_selection_by_channel_distance(
            geom_file,
            selection,
            upstream_buffer_distance=upstream_buffer_distance,
            downstream_buffer_distance=downstream_buffer_distance,
        )
        if downstream_overlap_xs:
            selection = RasBreakout1D._expand_downstream_cross_sections(
                geom_file,
                selection,
                downstream_overlap_xs,
            )
        if len(selection.stations) < 2:
            raise ValueError(
                "Network-edge selection must retain at least two cross sections "
                "after buffers and downstream overlap"
            )
        return RasBreakout1D._retag_selection(selection, "network_edge")

    @staticmethod
    @log_call
    def select_domains_by_network_edge(
        geom_file: Union[str, Path],
        network_edge: Any,
        *,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        tolerance: float = 0.0,
        inside_fraction: Optional[float] = None,
        upstream_buffer_distance: Optional[float] = None,
        downstream_buffer_distance: Optional[float] = None,
        upstream_buffer_fraction: float = 0.10,
        downstream_buffer_fraction: float = 0.25,
        inundation_overlap_xs: int = 1,
        fully_inside_tolerance: float = 1e-9,
    ) -> Breakout1DDomainSelection:
        """Resolve nested hydraulic-computation and raster-export domains.

        Explicit buffer distances override percentage defaults independently.
        When ``inside_fraction`` indicates that the network edge is fully inside
        the model, omitted distances default to 10% upstream and 25% downstream
        of the source reach's main-channel length. For partial edges, omitted
        distances resolve to zero. Expansion stops at the available reach
        termini.

        The inundation selection requests ``inundation_overlap_xs`` shared
        downstream cross sections and reports how many were available. The
        computation selection always contains that strict export selection,
        even when no hydraulic distance buffer is requested.
        """
        normalized_inside_fraction = RasBreakout1D._optional_fraction(
            inside_fraction, "inside_fraction"
        )
        upstream_buffer_fraction = RasBreakout1D._fraction(
            upstream_buffer_fraction, "upstream_buffer_fraction"
        )
        downstream_buffer_fraction = RasBreakout1D._fraction(
            downstream_buffer_fraction, "downstream_buffer_fraction"
        )
        fully_inside_tolerance = RasBreakout1D._nonnegative_distance(
            fully_inside_tolerance, "fully_inside_tolerance"
        )
        if fully_inside_tolerance >= 1.0:
            raise ValueError("fully_inside_tolerance must be less than 1")
        if isinstance(inundation_overlap_xs, bool) or not isinstance(
            inundation_overlap_xs, int
        ):
            raise TypeError("inundation_overlap_xs must be an integer")
        if inundation_overlap_xs < 0:
            raise ValueError("inundation_overlap_xs must be non-negative")

        direct = RasBreakout1D._direct_network_edge_selection(
            geom_file,
            network_edge,
            river=river,
            reach=reach,
            tolerance=tolerance,
        )
        direct = RasBreakout1D._retag_selection(direct, "network_edge_direct")
        main_channel_length = RasBreakout1D._main_channel_length(
            geom_file, direct.river, direct.reach
        )
        fully_inside = (
            normalized_inside_fraction is not None
            and normalized_inside_fraction >= 1.0 - fully_inside_tolerance
        )
        automatic_upstream = upstream_buffer_distance is None and fully_inside
        automatic_downstream = (
            downstream_buffer_distance is None and fully_inside
        )
        if upstream_buffer_distance is None:
            resolved_upstream = (
                upstream_buffer_fraction * main_channel_length
                if automatic_upstream
                else 0.0
            )
        else:
            resolved_upstream = RasBreakout1D._nonnegative_distance(
                upstream_buffer_distance, "upstream_buffer_distance"
            )
        if downstream_buffer_distance is None:
            resolved_downstream = (
                downstream_buffer_fraction * main_channel_length
                if automatic_downstream
                else 0.0
            )
        else:
            resolved_downstream = RasBreakout1D._nonnegative_distance(
                downstream_buffer_distance, "downstream_buffer_distance"
            )

        inundation = RasBreakout1D._expand_downstream_cross_sections(
            geom_file, direct, inundation_overlap_xs
        )
        inundation = RasBreakout1D._retag_selection(
            inundation, "network_edge_inundation"
        )
        computation, applied_upstream, applied_downstream = (
            RasBreakout1D._expand_selection_by_channel_distance(
                geom_file,
                direct,
                upstream_buffer_distance=resolved_upstream,
                downstream_buffer_distance=resolved_downstream,
            )
        )
        computation = RasBreakout1D._union_selections(
            geom_file, computation, inundation
        )
        if len(computation.stations) < 2:
            raise ValueError(
                "Network-edge domains must retain at least two cross sections; "
                "the selected edge reaches a model terminus without an available "
                "overlap section"
            )
        computation = RasBreakout1D._retag_selection(
            computation, "network_edge_computation"
        )
        reach_xs = RasBreakout1D._reach_cross_sections(
            geom_file, direct.river, direct.reach
        )
        _, direct_end = RasBreakout1D._selection_positions(reach_xs, direct)
        _, inundation_end = RasBreakout1D._selection_positions(
            reach_xs, inundation
        )
        applied_overlap = inundation_end - direct_end
        return Breakout1DDomainSelection(
            direct_selection=direct,
            inundation_selection=inundation,
            computation_selection=computation,
            inside_fraction=normalized_inside_fraction,
            main_channel_length=main_channel_length,
            upstream_buffer_distance=resolved_upstream,
            downstream_buffer_distance=resolved_downstream,
            upstream_buffer_applied=applied_upstream,
            downstream_buffer_applied=applied_downstream,
            automatic_upstream_buffer=automatic_upstream,
            automatic_downstream_buffer=automatic_downstream,
            inundation_overlap_xs=inundation_overlap_xs,
            inundation_overlap_xs_applied=applied_overlap,
        )

    @staticmethod
    @log_call
    def select_network_edge_domains(
        geom_file: Union[str, Path],
        network_edge: Any,
        *,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        tolerance: float = 0.0,
        inside_fraction: Optional[float] = None,
        upstream_buffer_distance: Optional[float] = None,
        downstream_buffer_distance: Optional[float] = None,
        upstream_buffer_fraction: float = 0.10,
        downstream_buffer_fraction: float = 0.25,
        inundation_overlap_xs: int = 1,
        fully_inside_tolerance: float = 1e-9,
    ) -> Breakout1DDomainSelection:
        """Compatibility alias for :meth:`select_domains_by_network_edge`."""
        return RasBreakout1D.select_domains_by_network_edge(
            geom_file,
            network_edge,
            river=river,
            reach=reach,
            tolerance=tolerance,
            inside_fraction=inside_fraction,
            upstream_buffer_distance=upstream_buffer_distance,
            downstream_buffer_distance=downstream_buffer_distance,
            upstream_buffer_fraction=upstream_buffer_fraction,
            downstream_buffer_fraction=downstream_buffer_fraction,
            inundation_overlap_xs=inundation_overlap_xs,
            fully_inside_tolerance=fully_inside_tolerance,
        )

    @staticmethod
    @log_call
    def select_by_network_segment(
        geom_file: Union[str, Path],
        segment: Any,
        *,
        river: Optional[str] = None,
        reach: Optional[str] = None,
        tolerance: float = 0.0,
        downstream_overlap_xs: int = 1,
        upstream_buffer_distance: float = 0.0,
        downstream_buffer_distance: float = 0.0,
    ) -> Breakout1DSelection:
        """Alias for :meth:`select_by_network_edge`."""
        return RasBreakout1D.select_by_network_edge(
            geom_file,
            segment,
            river=river,
            reach=reach,
            tolerance=tolerance,
            downstream_overlap_xs=downstream_overlap_xs,
            upstream_buffer_distance=upstream_buffer_distance,
            downstream_buffer_distance=downstream_buffer_distance,
        )

    @staticmethod
    @log_call
    def extract_reach(
        source_ras: RasPrj,
        destination: Union[str, Path],
        river: str,
        reach: str,
        upstream_station: Union[str, float, int],
        downstream_station: Union[str, float, int],
        *,
        plan_number: Optional[Union[str, int]] = None,
        destination_name: Optional[str] = None,
        boundary_mode: str = "auto",
        source_plan_hdf: Optional[Union[str, Path]] = None,
        downstream_boundary: Optional[Mapping[str, Any]] = None,
        run: bool = False,
        verify_run: bool = True,
        compute_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> Breakout1DResult:
        """Extract one station-bounded reach into a new steady project."""
        plan = RasBreakout1D._resolve_source_plan(source_ras, plan_number)
        selection = RasBreakout1D.select_by_stations(
            plan["geometry_path"],
            river,
            reach,
            upstream_station,
            downstream_station,
        )
        return RasBreakout1D.extract_selection(
            source_ras,
            destination,
            selection,
            plan_number=plan["plan_number"],
            destination_name=destination_name,
            boundary_mode=boundary_mode,
            source_plan_hdf=source_plan_hdf,
            downstream_boundary=downstream_boundary,
            run=run,
            verify_run=verify_run,
            compute_kwargs=compute_kwargs,
        )

    @staticmethod
    @log_call
    def extract_selection(
        source_ras: RasPrj,
        destination: Union[str, Path],
        selection: Breakout1DSelection,
        *,
        plan_number: Optional[Union[str, int]] = None,
        destination_name: Optional[str] = None,
        boundary_mode: str = "auto",
        source_plan_hdf: Optional[Union[str, Path]] = None,
        downstream_boundary: Optional[Mapping[str, Any]] = None,
        run: bool = False,
        verify_run: bool = True,
        compute_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> Breakout1DResult:
        """Extract a previously resolved one-reach selection.

        ``boundary_mode='auto'`` uses source-plan WSE at an internal downstream
        cut when results exist, otherwise preserves the source reach boundary
        and records that fallback in the result.  ``'source_results'`` requires
        a usable steady plan HDF.  ``'preserve'`` always keeps the source reach
        boundary.  ``downstream_boundary`` overrides all three modes.
        """
        if not isinstance(source_ras, RasPrj) or not source_ras.is_initialized:
            raise TypeError("source_ras must be an initialized RasPrj instance")
        plan = RasBreakout1D._resolve_source_plan(source_ras, plan_number)
        destination = Path(destination)
        RasBreakout1D._prepare_empty_destination(destination)
        project_name = RasBreakout1D._safe_project_name(
            destination_name or destination.name
        )

        source_geom = plan["geometry_path"]
        source_flow = plan["flow_path"]
        source_plan = plan["plan_path"]
        source_geom_hash = RasBreakout1D._sha256(source_geom)

        geometry_text = RasBreakout1D._extract_geometry_text(source_geom, selection)
        flow_data, boundary_provenance = RasBreakout1D._extract_flow_data(
            source_flow,
            selection,
            source_geometry=source_geom,
            source_plan_hdf=(
                Path(source_plan_hdf)
                if source_plan_hdf is not None
                else RasBreakout1D._expected_plan_hdf(source_plan)
            ),
            boundary_mode=boundary_mode,
            downstream_boundary=downstream_boundary,
        )

        project_file = destination / f"{project_name}.prj"
        plan_file = destination / f"{project_name}.p01"
        geometry_file = destination / f"{project_name}.g01"
        flow_file = destination / f"{project_name}.f01"

        geometry_file.write_text(geometry_text, encoding="utf-8", newline="\r\n")
        from .RasSteady import RasSteady

        RasSteady.write_flow_file(flow_file, flow_data)
        plan_file.write_text(
            RasBreakout1D._rewrite_plan(source_plan, project_name),
            encoding="utf-8",
            newline="\r\n",
        )
        project_file.write_text(
            RasBreakout1D._rewrite_project(source_ras.prj_file, project_name),
            encoding="utf-8",
            newline="\r\n",
        )

        if RasBreakout1D._sha256(source_geom) != source_geom_hash:
            raise RuntimeError("Source geometry changed during breakout extraction")

        destination_ras = RasPrj()
        destination_ras.initialize(
            destination,
            source_ras.ras_exe_path,
            suppress_logging=True,
            prj_file=project_file,
            load_results_summary=False,
            load_hdf_metadata=False,
        )

        validation = RasBreakout1D.validate(
            source_ras,
            destination_ras,
            selection,
            source_plan_number=plan["plan_number"],
            source_geometry_sha256=source_geom_hash,
            boundary_provenance=boundary_provenance,
        )
        validation.raise_for_errors()
        result = Breakout1DResult(
            source_ras=source_ras,
            destination_ras=destination_ras,
            selection=selection,
            project_file=project_file,
            plan_file=plan_file,
            geometry_file=geometry_file,
            flow_file=flow_file,
            validation=validation,
            boundary_provenance=boundary_provenance,
            source_geometry_sha256=source_geom_hash,
        )
        if run:
            result.compute_result = RasBreakout1D.run(
                result,
                verify=verify_run,
                **dict(compute_kwargs or {}),
            )
        logger.info(
            "Created one-reach breakout %s with %d retained cross sections",
            project_file,
            len(selection.stations),
        )
        return result

    @staticmethod
    @log_call
    def run(
        breakout: Union[Breakout1DResult, RasPrj],
        *,
        plan_number: Union[str, int] = "01",
        verify: bool = True,
        **compute_kwargs: Any,
    ) -> Any:
        """Explicitly run a destination breakout through ``RasCmdr``."""
        from .RasCmdr import RasCmdr

        ras_object = (
            breakout.destination_ras
            if isinstance(breakout, Breakout1DResult)
            else breakout
        )
        if not isinstance(ras_object, RasPrj) or not ras_object.is_initialized:
            raise TypeError("breakout must contain an initialized RasPrj instance")
        compute_kwargs.setdefault("clear_geompre", True)
        return RasCmdr.compute_plan(
            plan_number,
            ras_object=ras_object,
            verify=verify,
            **compute_kwargs,
        )

    @staticmethod
    @log_call
    def validate(
        source_ras: RasPrj,
        destination_ras: RasPrj,
        selection: Breakout1DSelection,
        *,
        source_plan_number: Optional[Union[str, int]] = None,
        source_geometry_sha256: Optional[str] = None,
        boundary_provenance: str = "unknown",
    ) -> Breakout1DValidationReport:
        """Validate project links, retained blocks, reach lengths, and flow data."""
        source = RasBreakout1D._resolve_source_plan(source_ras, source_plan_number)
        destination = RasBreakout1D._resolve_source_plan(destination_ras, "01")
        geometry_comparison = RasBreakout1D.compare_geometry(
            source["geometry_path"],
            destination["geometry_path"],
            selection,
        )
        from .RasSteady import RasSteady

        destination_flow = RasSteady.read_flow_file(destination["flow_path"])
        destination_xs = RasBreakout1D._reach_cross_sections(
            destination["geometry_path"], selection.river, selection.reach
        )
        source_xs = RasBreakout1D._reach_cross_sections(
            source["geometry_path"], selection.river, selection.reach
        )
        all_destination_xs = RasBreakout1D._all_natural_cross_sections(
            destination["geometry_path"]
        )

        checks: list[dict[str, Any]] = []

        def add(check: str, passed: bool, detail: str, severity: str = "ERROR") -> None:
            checks.append(
                {
                    "check": check,
                    "severity": severity,
                    "passed": bool(passed),
                    "detail": detail,
                }
            )

        expected = set(selection.stations)
        actual = set(destination_xs["RS"].astype(str))
        add(
            "retained_cross_sections",
            actual == expected,
            f"expected={sorted(expected)} actual={sorted(actual)}",
        )
        destination_reaches = all_destination_xs[["River", "Reach"]].drop_duplicates()
        add(
            "single_reach",
            len(destination_reaches) == 1,
            f"destination reaches={destination_reaches.to_dict('records')}",
        )
        add(
            "cross_section_block_content",
            bool(geometry_comparison["content_equal"].all()),
            "all retained cross-section payloads match the source",
        )
        structure_matches = geometry_comparison.attrs.get(
            "structure_blocks_equal", False
        )
        add(
            "structure_block_content",
            bool(structure_matches),
            "all intervening structure blocks match the source",
        )
        downstream_row = destination_xs[
            destination_xs["RS"].map(RasBreakout1D._station_value)
            == RasBreakout1D._station_value(selection.downstream_station)
        ]
        lengths_zero = False
        if len(downstream_row) == 1:
            lengths_zero = all(
                float(downstream_row.iloc[0][column]) == 0.0
                for column in ("Length_Left", "Length_Channel", "Length_Right")
            )
        add(
            "downstream_reach_lengths",
            lengths_zero,
            "new downstream cross-section L/Ch/R reach lengths are zero",
        )
        upstream_value = RasBreakout1D._station_value(selection.upstream_station)
        source_upstream = source_xs[
            source_xs["RS"].map(RasBreakout1D._station_value) == upstream_value
        ]
        destination_upstream = destination_xs[
            destination_xs["RS"].map(RasBreakout1D._station_value) == upstream_value
        ]
        upstream_lengths_equal = False
        if len(source_upstream) == 1 and len(destination_upstream) == 1:
            length_columns = ("Length_Left", "Length_Channel", "Length_Right")
            upstream_lengths_equal = all(
                float(source_upstream.iloc[0][column])
                == float(destination_upstream.iloc[0][column])
                for column in length_columns
            )
        add(
            "upstream_reach_lengths",
            upstream_lengths_equal,
            "upstream retained cross-section keeps its lengths to the next "
            "retained downstream node",
        )
        flow_changes = destination_flow["flow_changes"]
        flow_change_reaches = {(item["river"], item["reach"]) for item in flow_changes}
        add(
            "steady_flow_reach",
            flow_change_reaches == {(selection.river, selection.reach)},
            f"flow-change reaches={sorted(flow_change_reaches)}",
        )
        has_upstream_flow = any(
            RasBreakout1D._stations_equal(item["station"], selection.upstream_station)
            for item in flow_changes
        )
        add(
            "upstream_flow_change",
            has_upstream_flow,
            "a flow-change record exists at the new upstream limit",
        )
        add(
            "project_relationships",
            (
                Path(destination["geometry_path"])
                == Path(destination_ras.project_folder)
                / f"{destination_ras.project_name}.g01"
                and Path(destination["flow_path"])
                == Path(destination_ras.project_folder)
                / f"{destination_ras.project_name}.f01"
            ),
            "plan 01 references destination geometry 01 and steady flow 01",
        )
        if source_geometry_sha256 is not None:
            add(
                "source_immutable",
                RasBreakout1D._sha256(source["geometry_path"]) == source_geometry_sha256,
                "source geometry SHA-256 is unchanged",
            )
        add(
            "boundary_provenance",
            boundary_provenance != "source_reach_fallback",
            f"boundary provenance={boundary_provenance}",
            severity="WARNING",
        )
        return Breakout1DValidationReport(pd.DataFrame(checks))

    @staticmethod
    @log_call
    def compare_geometry(
        source_geometry: Union[str, Path],
        destination_geometry: Union[str, Path],
        selection: Breakout1DSelection,
    ) -> pd.DataFrame:
        """Compare complete retained source/destination geometry node blocks."""
        source_lines, _, source_nodes = RasBreakout1D._target_reach_parts(
            source_geometry, selection.river, selection.reach
        )
        destination_lines, _, destination_nodes = RasBreakout1D._target_reach_parts(
            destination_geometry, selection.river, selection.reach
        )
        source_xs = {node.station: node for node in source_nodes if node.type_code == 1}
        destination_xs = {
            node.station: node for node in destination_nodes if node.type_code == 1
        }
        rows = []
        for station in selection.stations:
            source_key = RasBreakout1D._matching_station_key(source_xs, station)
            destination_key = RasBreakout1D._matching_station_key(destination_xs, station)
            source_node = source_xs[source_key]
            destination_node = destination_xs[destination_key]
            source_block = source_lines[source_node.start : source_node.end]
            destination_block = destination_lines[
                destination_node.start : destination_node.end
            ]
            rows.append(
                {
                    "River": selection.river,
                    "Reach": selection.reach,
                    "RS": station,
                    "content_equal": source_block[1:] == destination_block[1:],
                    "source_block_sha256": RasBreakout1D._text_sha256(
                        "".join(source_block[1:])
                    ),
                    "destination_block_sha256": RasBreakout1D._text_sha256(
                        "".join(destination_block[1:])
                    ),
                }
            )

        lower = RasBreakout1D._station_value(selection.downstream_station)
        upper = RasBreakout1D._station_value(selection.upstream_station)
        source_structures = [
            node
            for node in source_nodes
            if node.type_code != 1
            and lower <= RasBreakout1D._station_value(node.station) <= upper
        ]
        destination_structures = [
            node for node in destination_nodes if node.type_code != 1
        ]
        source_structure_text = [
            "".join(source_lines[node.start : node.end]) for node in source_structures
        ]
        destination_structure_text = [
            "".join(destination_lines[node.start : node.end])
            for node in destination_structures
        ]
        result = pd.DataFrame(rows)
        result.attrs["structure_blocks_equal"] = (
            source_structure_text == destination_structure_text
        )
        result.attrs["source_structure_count"] = len(source_structures)
        result.attrs["destination_structure_count"] = len(destination_structures)
        return result

    @staticmethod
    @log_call
    def compare_results(
        source_plan_hdf: Union[str, Path],
        destination_plan_hdf: Union[str, Path],
        selection: Breakout1DSelection,
    ) -> pd.DataFrame:
        """Compare steady results at retained sections and return numeric deltas."""
        from .hdf import HdfResultsPlan

        source = HdfResultsPlan.get_steady_results(Path(source_plan_hdf))
        destination = HdfResultsPlan.get_steady_results(Path(destination_plan_hdf))
        keys = ["river", "reach", "node_id", "profile"]

        def retained(frame: pd.DataFrame) -> pd.DataFrame:
            frame = frame[
                (frame["river"] == selection.river)
                & (frame["reach"] == selection.reach)
            ].copy()
            wanted = {RasBreakout1D._station_value(value) for value in selection.stations}
            return frame[frame["node_id"].map(RasBreakout1D._station_value).isin(wanted)]

        merged = retained(source).merge(
            retained(destination),
            on=keys,
            how="outer",
            suffixes=("_source", "_destination"),
            indicator=True,
            validate="one_to_one",
        )
        common_numeric = sorted(
            {
                column[: -len("_source")]
                for column in merged.columns
                if column.endswith("_source")
                and f"{column[: -len('_source')]}_destination" in merged.columns
                and pd.api.types.is_numeric_dtype(merged[column])
            }
        )
        for column in common_numeric:
            merged[f"{column}_delta"] = (
                merged[f"{column}_destination"] - merged[f"{column}_source"]
            )
        return merged

    @staticmethod
    def _resolve_source_plan(
        ras_object: RasPrj, plan_number: Optional[Union[str, int]]
    ) -> dict[str, Any]:
        if not isinstance(ras_object, RasPrj) or not ras_object.is_initialized:
            raise TypeError("ras_object must be an initialized RasPrj instance")
        if plan_number is None:
            current = RasBreakout1D._current_plan_number(ras_object.prj_file)
            if current is not None:
                plan_number = current
            elif len(ras_object.plan_df) == 1:
                plan_number = str(ras_object.plan_df.iloc[0]["plan_number"])
            else:
                raise ValueError("plan_number is required when no current plan is set")
        normalized = str(plan_number).lower().removeprefix("p").zfill(2)
        rows = ras_object.plan_df[
            ras_object.plan_df["plan_number"].astype(str).str.zfill(2) == normalized
        ]
        if len(rows) != 1:
            raise ValueError(f"Plan {normalized} was not found exactly once")
        row = rows.iloc[0]
        if str(row.get("flow_type", "")).lower() != "steady":
            raise ValueError("RasBreakout1D MVP supports steady-flow plans only")
        sediment_number = row.get("sediment_number")
        if pd.notna(sediment_number) and str(sediment_number).strip():
            raise ValueError("Sediment plans are outside the RasBreakout1D MVP")
        geometry_type = str(row.get("geometry_type", ""))
        has_2d = row.get("has_2d_mesh", False)
        has_2d = False if pd.isna(has_2d) else bool(has_2d)
        if has_2d or geometry_type not in {"1D", "Unknown", "nan", ""}:
            raise ValueError(
                "RasBreakout1D MVP supports pure 1D geometry only; "
                f"plan geometry is {geometry_type}"
            )
        geometry_path = Path(str(row["Geom Path"]))
        flow_path = Path(str(row["Flow Path"]))
        plan_path = Path(str(row["full_path"]))
        for path in (geometry_path, flow_path, plan_path):
            if not path.is_file():
                raise FileNotFoundError(path)
        return {
            "plan_number": normalized,
            "geometry_path": geometry_path,
            "flow_path": flow_path,
            "plan_path": plan_path,
            "row": row,
        }

    @staticmethod
    def _extract_geometry_text(
        geom_file: Union[str, Path], selection: Breakout1DSelection
    ) -> str:
        lines, reach_start, nodes = RasBreakout1D._target_reach_parts(
            geom_file, selection.river, selection.reach
        )
        if RasBreakout1D._selection_has_lateral_structure(geom_file, selection):
            raise NotImplementedError(
                "Lateral structures are outside the one-reach RasBreakout1D MVP"
            )
        natural_nodes = [node for node in nodes if node.type_code == 1]
        selected_nodes = [
            node
            for node in natural_nodes
            if any(
                RasBreakout1D._stations_equal(node.station, station)
                for station in selection.stations
            )
        ]
        if len(selected_nodes) != len(selection.stations):
            raise ValueError("Selection does not resolve uniquely in source geometry")
        selected_positions = sorted(nodes.index(node) for node in selected_nodes)
        start_pos, end_pos = selected_positions[0], selected_positions[-1]
        retained_nodes = nodes[start_pos : end_pos + 1]
        retained_natural = [node for node in retained_nodes if node.type_code == 1]
        if len(retained_natural) != len(selection.stations):
            raise ValueError("Selection is not a continuous source-reach slice")

        domain_start = RasBreakout1D._first_geometry_domain_line(lines)
        reach_header = RasBreakout1D._clip_reach_header(
            geom_file,
            lines[reach_start : nodes[0].start],
            selection,
        )
        output = list(lines[:domain_start]) + list(reach_header)
        downstream_value = RasBreakout1D._station_value(selection.downstream_station)
        for node in retained_nodes:
            block = list(lines[node.start : node.end])
            if (
                node.type_code == 1
                and RasBreakout1D._station_value(node.station) == downstream_value
            ):
                block[0] = RasBreakout1D._zero_reach_lengths(block[0])
            output.extend(block)
        if output and not output[-1].endswith(("\n", "\r")):
            output[-1] += "\n"
        return "".join(output)

    @staticmethod
    def _clip_reach_header(
        geom_file: Union[str, Path],
        reach_header: Sequence[str],
        selection: Breakout1DSelection,
    ) -> list[str]:
        """Clip ``Reach XY`` to the retained upstream/downstream XS crossings.

        A breakout must not retain the removed portions of its source river
        centerline. HEC-RAS uses that line while regenerating the interpolation
        surface, and a full-source line paired with a shorter XS slice can
        produce self-intersecting edge lines. If legacy geometry lacks usable
        GIS cut lines, the original header is retained and node extraction still
        succeeds.
        """
        from shapely.ops import nearest_points, substring

        from .geom import GeomParser

        header = list(reach_header)
        reach_xy_index = next(
            (
                index
                for index, line in enumerate(header)
                if line.lstrip().startswith("Reach XY=")
            ),
            None,
        )
        if reach_xy_index is None:
            return header

        count_match = _NUMBER_RE.search(header[reach_xy_index].split("=", 1)[-1])
        if count_match is None:
            return header
        source_point_count = int(float(count_match.group(0)))
        coordinate_line_count = math.ceil(source_point_count / 2)
        coordinate_end = reach_xy_index + 1 + coordinate_line_count
        if coordinate_end > len(header):
            return header

        centerlines = GeomParser.get_river_centerlines(geom_file)
        centerlines = centerlines[
            (centerlines["river"] == selection.river)
            & (centerlines["reach"] == selection.reach)
        ]
        cut_lines = GeomParser.get_xs_cut_lines(geom_file)
        cut_lines = cut_lines[
            (cut_lines["river"] == selection.river)
            & (cut_lines["reach"] == selection.reach)
        ]
        if len(centerlines) != 1 or cut_lines.empty:
            return header

        centerline = centerlines.iloc[0].geometry

        def boundary_measure(station: str) -> Optional[float]:
            matches = cut_lines[
                cut_lines["station"].map(RasBreakout1D._station_value)
                == RasBreakout1D._station_value(station)
            ]
            if len(matches) != 1:
                return None
            center_point, _ = nearest_points(centerline, matches.iloc[0].geometry)
            if center_point.distance(matches.iloc[0].geometry) > 1e-6:
                return None
            return float(centerline.project(center_point))

        upstream_measure = boundary_measure(selection.upstream_station)
        downstream_measure = boundary_measure(selection.downstream_station)
        if upstream_measure is None or downstream_measure is None:
            return header
        lower_measure, upper_measure = sorted((upstream_measure, downstream_measure))
        if math.isclose(lower_measure, upper_measure, abs_tol=1e-9):
            return header

        clipped = substring(centerline, lower_measure, upper_measure)
        if clipped.geom_type != "LineString" or len(clipped.coords) < 2:
            return header
        coordinates = list(clipped.coords)
        values = [value for coordinate in coordinates for value in coordinate[:2]]
        coordinate_lines = [
            "".join(
                RasBreakout1D._format_coordinate(value)
                for value in values[index : index + 4]
            )
            + "\n"
            for index in range(0, len(values), 4)
        ]
        return (
            header[:reach_xy_index]
            + [f"Reach XY= {len(coordinates)}\n"]
            + coordinate_lines
            + header[coordinate_end:]
        )

    @staticmethod
    def _format_coordinate(value: float) -> str:
        """Return one HEC-RAS 16-character GIS coordinate field."""
        for precision in (3, 2, 1, 0):
            formatted = f"{float(value):.{precision}f}"
            if len(formatted) <= 16:
                return formatted.rjust(16)
        scientific = f"{float(value):.8E}"
        if len(scientific) > 16:
            raise ValueError(f"Coordinate cannot fit a 16-character field: {value}")
        return scientific.rjust(16)

    @staticmethod
    def _extract_flow_data(
        flow_file: Union[str, Path],
        selection: Breakout1DSelection,
        *,
        source_geometry: Path,
        source_plan_hdf: Path,
        boundary_mode: str,
        downstream_boundary: Optional[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        from .RasSteady import RasSteady

        data = RasSteady.read_flow_file(flow_file)
        target_changes = [
            item
            for item in data["flow_changes"]
            if item["river"] == selection.river and item["reach"] == selection.reach
        ]
        if not target_changes:
            raise ValueError("Source steady flow has no changes on the selected reach")
        upper = RasBreakout1D._station_value(selection.upstream_station)
        lower = RasBreakout1D._station_value(selection.downstream_station)
        changes_with_values = sorted(
            (
                (RasBreakout1D._station_value(item["station"]), item)
                for item in target_changes
            ),
            reverse=True,
            key=lambda value: value[0],
        )
        upstream_candidates = [
            item for value, item in changes_with_values if value >= upper
        ]
        if upstream_candidates:
            active_upstream = upstream_candidates[-1]
        else:
            active_upstream = changes_with_values[0][1]

        retained_changes = [
            dict(item) for value, item in changes_with_values if lower <= value <= upper
        ]
        if not any(
            RasBreakout1D._stations_equal(item["station"], selection.upstream_station)
            for item in retained_changes
        ):
            propagated = dict(active_upstream)
            propagated["station"] = selection.upstream_station
            propagated["river_station"] = selection.upstream_station
            retained_changes.append(propagated)
        retained_changes.sort(
            key=lambda item: RasBreakout1D._station_value(item["station"]),
            reverse=True,
        )

        source_xs = RasBreakout1D._reach_cross_sections(
            source_geometry,
            selection.river,
            selection.reach,
            allow_missing=True,
        )
        original_downstream = None
        if not source_xs.empty:
            original_downstream = str(
                source_xs.loc[
                    source_xs["RS"].map(RasBreakout1D._station_value).idxmin(), "RS"
                ]
            )
        internal_cut = original_downstream is None or not RasBreakout1D._stations_equal(
            original_downstream, selection.downstream_station
        )
        source_boundaries = [
            item
            for item in data.get("boundaries", [])
            if item["river"] == selection.river and item["reach"] == selection.reach
        ]

        mode = boundary_mode.strip().lower()
        if mode not in {"auto", "preserve", "source_results"}:
            raise ValueError(
                "boundary_mode must be 'auto', 'preserve', or 'source_results'"
            )
        if downstream_boundary is not None:
            boundaries = [
                RasSteady.boundary(
                    selection.river,
                    selection.reach,
                    downstream=dict(downstream_boundary),
                )
            ]
            provenance = "caller"
        elif (
            internal_cut
            and mode in {"auto", "source_results"}
            and source_plan_hdf.is_file()
        ):
            boundaries = RasBreakout1D._known_wse_boundaries(
                source_plan_hdf, data, selection, source_boundaries
            )
            provenance = "source_results"
        elif internal_cut and mode == "source_results":
            raise FileNotFoundError(
                "source_results boundary mode requires a computed steady plan HDF: "
                f"{source_plan_hdf}"
            )
        else:
            if not source_boundaries:
                raise ValueError("Source reach has no steady boundary conditions")
            boundaries = source_boundaries
            provenance = "source_reach_fallback" if internal_cut else "source_reach"
        data["flow_changes"] = retained_changes
        data["boundaries"] = boundaries
        data["flow_title"] = f"Breakout - {data.get('flow_title', '')}".strip()
        data.pop("unparsed_lines", None)
        return data, provenance

    @staticmethod
    def _known_wse_boundaries(
        source_hdf: Path,
        flow_data: Mapping[str, Any],
        selection: Breakout1DSelection,
        source_boundaries: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        from .RasSteady import RasSteady
        from .hdf import HdfResultsPlan

        wse = HdfResultsPlan.get_steady_wse(source_hdf)
        if "Profile" not in wse.columns:
            wse["Profile"] = flow_data["profile_names"][0]
        wanted_value = RasBreakout1D._station_value(selection.downstream_station)
        wse = wse[
            (wse["River"] == selection.river)
            & (wse["Reach"] == selection.reach)
            & (wse["Station"].map(RasBreakout1D._station_value) == wanted_value)
        ]
        if len(wse) != len(flow_data["profile_names"]):
            raise ValueError(
                "Source HDF does not contain exactly one downstream WSE per profile"
            )
        upstream_by_profile = {
            int(item.get("profile", item.get("profile_number", 0))): item.get(
                "upstream", {"type": RasSteady.NO_BOUNDARY}
            )
            for item in source_boundaries
            if item.get("profile", item.get("profile_number")) is not None
        }
        boundaries = []
        for profile_number, profile_name in enumerate(
            flow_data["profile_names"], start=1
        ):
            row = wse[wse["Profile"] == profile_name]
            if len(row) != 1:
                raise ValueError(
                    f"Source HDF profile {profile_name!r} is missing or ambiguous"
                )
            boundaries.append(
                RasSteady.boundary(
                    selection.river,
                    selection.reach,
                    profile=profile_number,
                    upstream=upstream_by_profile.get(
                        profile_number, {"type": RasSteady.NO_BOUNDARY}
                    ),
                    downstream=RasSteady.known_water_surface(float(row.iloc[0]["WSE"])),
                )
            )
        return boundaries

    @staticmethod
    def _reach_cross_sections(
        geom_file: Union[str, Path],
        river: str,
        reach: str,
        *,
        allow_missing: bool = False,
    ) -> pd.DataFrame:
        from .geom import GeomCrossSection

        try:
            result = GeomCrossSection.get_cross_sections(
                geom_file, river=river, reach=reach
            )
        except FileNotFoundError:
            if allow_missing:
                return pd.DataFrame()
            raise
        if result.empty:
            if allow_missing:
                return result
            raise ValueError(f"No geometry nodes found for {river}/{reach}")
        natural = result[result["Type"] == 1].copy()
        if natural.empty:
            raise ValueError(f"No natural cross sections found for {river}/{reach}")
        if natural["RS"].map(RasBreakout1D._station_value).duplicated().any():
            raise ValueError("Duplicate numeric river stations are unsupported")
        return natural.reset_index(drop=True)

    @staticmethod
    def _direct_network_edge_selection(
        geom_file: Union[str, Path],
        network_edge: Any,
        *,
        river: Optional[str],
        reach: Optional[str],
        tolerance: float,
    ) -> Breakout1DSelection:
        tolerance = RasBreakout1D._nonnegative_distance(tolerance, "tolerance")
        search_geometry = (
            network_edge.buffer(tolerance) if tolerance else network_edge
        )
        reach_xs, start, end = RasBreakout1D._intersecting_xs_span(
            geom_file,
            search_geometry,
            river=river,
            reach=reach,
            geometry_label="Network edge",
        )
        return RasBreakout1D._selection_from_reach_positions(
            reach_xs,
            start,
            end,
            selector="network_edge_direct",
            minimum_cross_sections=1,
        )

    @staticmethod
    def _intersecting_xs_span(
        geom_file: Union[str, Path],
        search_geometry: Any,
        *,
        river: Optional[str],
        reach: Optional[str],
        geometry_label: str,
    ) -> tuple[pd.DataFrame, int, int]:
        from .geom import GeomParser

        cut_lines = GeomParser.get_xs_cut_lines(geom_file)
        intersecting = cut_lines[
            cut_lines.geometry.intersects(search_geometry)
        ].copy()
        if river is not None:
            intersecting = intersecting[intersecting["river"] == river]
        if reach is not None:
            intersecting = intersecting[intersecting["reach"] == reach]
        if intersecting.empty:
            raise ValueError(
                f"{geometry_label} does not intersect any cross-section cut lines"
            )

        reaches = intersecting[["river", "reach"]].drop_duplicates()
        if len(reaches) != 1:
            choices = list(reaches.itertuples(index=False, name=None))
            raise ValueError(
                f"{geometry_label} selection must resolve to exactly one reach; "
                f"found {choices}"
            )
        resolved_river, resolved_reach = reaches.iloc[0].tolist()
        reach_xs = RasBreakout1D._reach_cross_sections(
            geom_file, str(resolved_river), str(resolved_reach)
        )
        intersected_values = {
            RasBreakout1D._station_value(value)
            for value in intersecting["station"]
        }
        positions = [
            position
            for position, value in enumerate(reach_xs["RS"])
            if RasBreakout1D._station_value(value) in intersected_values
        ]
        if not positions:
            raise ValueError(
                f"{geometry_label} intersections could not be resolved in the reach"
            )
        return reach_xs, min(positions), max(positions)

    @staticmethod
    def _selection_from_reach_positions(
        reach_xs: pd.DataFrame,
        start: int,
        end: int,
        *,
        selector: str,
        minimum_cross_sections: int,
    ) -> Breakout1DSelection:
        if start < 0 or end < start or end >= len(reach_xs):
            raise ValueError("Cross-section position bounds are invalid")
        selected = reach_xs.iloc[start : end + 1]
        if len(selected) < minimum_cross_sections:
            raise ValueError(
                f"Selection must retain at least {minimum_cross_sections} cross "
                f"sections; found {len(selected)}"
            )
        stations = tuple(selected["RS"].astype(str))
        return Breakout1DSelection(
            river=str(selected.iloc[0]["River"]),
            reach=str(selected.iloc[0]["Reach"]),
            stations=stations,
            upstream_station=stations[0],
            downstream_station=stations[-1],
            selector=selector,
        )

    @staticmethod
    def _main_channel_length(
        geom_file: Union[str, Path], river: str, reach: str
    ) -> float:
        reach_xs = RasBreakout1D._reach_cross_sections(geom_file, river, reach)
        lengths = pd.to_numeric(reach_xs["Length_Channel"], errors="coerce")
        if lengths.isna().any() or (~lengths.map(math.isfinite)).any():
            raise ValueError("Main-channel reach lengths must be finite numbers")
        if (lengths < 0).any():
            raise ValueError("Main-channel reach lengths must be non-negative")
        return float(lengths.sum())

    @staticmethod
    def _expand_selection_by_channel_distance(
        geom_file: Union[str, Path],
        selection: Breakout1DSelection,
        *,
        upstream_buffer_distance: float,
        downstream_buffer_distance: float,
    ) -> tuple[Breakout1DSelection, float, float]:
        upstream_buffer_distance = RasBreakout1D._nonnegative_distance(
            upstream_buffer_distance, "upstream_buffer_distance"
        )
        downstream_buffer_distance = RasBreakout1D._nonnegative_distance(
            downstream_buffer_distance, "downstream_buffer_distance"
        )
        reach_xs = RasBreakout1D._reach_cross_sections(
            geom_file, selection.river, selection.reach
        )
        upstream_position, downstream_position = RasBreakout1D._selection_positions(
            reach_xs, selection
        )

        start = upstream_position
        applied_upstream = 0.0
        while start > 0 and applied_upstream < upstream_buffer_distance:
            start -= 1
            applied_upstream += RasBreakout1D._channel_length_at(reach_xs, start)

        end = downstream_position
        applied_downstream = 0.0
        while (
            end < len(reach_xs) - 1
            and applied_downstream < downstream_buffer_distance
        ):
            applied_downstream += RasBreakout1D._channel_length_at(reach_xs, end)
            end += 1

        expanded = RasBreakout1D._selection_from_reach_positions(
            reach_xs,
            start,
            end,
            selector=selection.selector,
            minimum_cross_sections=1,
        )
        return expanded, applied_upstream, applied_downstream

    @staticmethod
    def _expand_downstream_cross_sections(
        geom_file: Union[str, Path],
        selection: Breakout1DSelection,
        count: int,
    ) -> Breakout1DSelection:
        if isinstance(count, bool) or not isinstance(count, int):
            raise TypeError("downstream cross-section overlap must be an integer")
        if count < 0:
            raise ValueError("downstream cross-section overlap must be non-negative")
        reach_xs = RasBreakout1D._reach_cross_sections(
            geom_file, selection.river, selection.reach
        )
        upstream_position, downstream_position = RasBreakout1D._selection_positions(
            reach_xs, selection
        )
        end = min(downstream_position + count, len(reach_xs) - 1)
        return RasBreakout1D._selection_from_reach_positions(
            reach_xs,
            upstream_position,
            end,
            selector=selection.selector,
            minimum_cross_sections=1,
        )

    @staticmethod
    def _union_selections(
        geom_file: Union[str, Path],
        first: Breakout1DSelection,
        second: Breakout1DSelection,
    ) -> Breakout1DSelection:
        if (first.river, first.reach) != (second.river, second.reach):
            raise ValueError("Selections must belong to the same river/reach")
        reach_xs = RasBreakout1D._reach_cross_sections(
            geom_file, first.river, first.reach
        )
        first_start, first_end = RasBreakout1D._selection_positions(reach_xs, first)
        second_start, second_end = RasBreakout1D._selection_positions(
            reach_xs, second
        )
        start = min(first_start, second_start)
        end = max(first_end, second_end)
        return RasBreakout1D._selection_from_reach_positions(
            reach_xs,
            start,
            end,
            selector=first.selector,
            minimum_cross_sections=1,
        )

    @staticmethod
    def _selection_positions(
        reach_xs: pd.DataFrame, selection: Breakout1DSelection
    ) -> tuple[int, int]:
        values = [RasBreakout1D._station_value(value) for value in reach_xs["RS"]]

        def resolve(station: str) -> int:
            target = RasBreakout1D._station_value(station)
            matches = [
                index
                for index, value in enumerate(values)
                if abs(float(value) - target) <= 1e-9
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Selection station {station!r} could not be resolved uniquely"
                )
            return int(matches[0])

        upstream = resolve(selection.upstream_station)
        downstream = resolve(selection.downstream_station)
        if upstream > downstream:
            raise ValueError("Selection order does not follow the source reach")
        return upstream, downstream

    @staticmethod
    def _channel_length_at(reach_xs: pd.DataFrame, position: int) -> float:
        value = float(reach_xs.iloc[position]["Length_Channel"])
        if not math.isfinite(value) or value < 0:
            raise ValueError("Main-channel reach lengths must be finite and non-negative")
        return value

    @staticmethod
    def _nonnegative_distance(value: Any, name: str) -> float:
        if isinstance(value, bool):
            raise TypeError(f"{name} must be a finite number")
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{name} must be a finite number") from exc
        if not math.isfinite(normalized):
            raise ValueError(f"{name} must be finite")
        if normalized < 0:
            raise ValueError(f"{name} must be non-negative")
        return normalized

    @staticmethod
    def _optional_fraction(value: Any, name: str) -> Optional[float]:
        if value is None:
            return None
        normalized = RasBreakout1D._nonnegative_distance(value, name)
        if normalized > 1:
            raise ValueError(f"{name} must be between 0 and 1")
        return normalized

    @staticmethod
    def _fraction(value: Any, name: str) -> float:
        normalized = RasBreakout1D._optional_fraction(value, name)
        if normalized is None:
            raise TypeError(f"{name} must be a finite number")
        return normalized

    @staticmethod
    def _retag_selection(
        selection: Breakout1DSelection, selector: str
    ) -> Breakout1DSelection:
        return Breakout1DSelection(
            river=selection.river,
            reach=selection.reach,
            stations=selection.stations,
            upstream_station=selection.upstream_station,
            downstream_station=selection.downstream_station,
            selector=selector,
        )

    @staticmethod
    def _all_natural_cross_sections(geom_file: Union[str, Path]) -> pd.DataFrame:
        from .geom import GeomCrossSection

        result = GeomCrossSection.get_cross_sections(geom_file)
        return result[result["Type"] == 1].reset_index(drop=True)

    @staticmethod
    def _target_reach_parts(
        geom_file: Union[str, Path], river: str, reach: str
    ) -> tuple[list[str], int, list[_NodeBlock]]:
        path = Path(geom_file)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        reach_starts: list[tuple[int, str, str]] = []
        for index, line in enumerate(lines):
            parsed = RasBreakout1D._parse_reach_header(line)
            if parsed is not None:
                reach_starts.append((index, parsed[0], parsed[1]))
        matches = [
            item for item in reach_starts if item[1] == river and item[2] == reach
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected exactly one reach {river}/{reach}; found {len(matches)}"
            )
        reach_start = matches[0][0]
        later_domain_starts = [
            index
            for index in range(reach_start + 1, len(lines))
            if RasBreakout1D._is_geometry_domain_header(lines[index])
        ]
        reach_end = min(later_domain_starts) if later_domain_starts else len(lines)
        node_starts = [
            index
            for index in range(reach_start + 1, reach_end)
            if lines[index].startswith(_TYPE_RM_PREFIX)
        ]
        if not node_starts:
            raise ValueError(f"Reach {river}/{reach} has no geometry nodes")
        nodes = []
        for position, start in enumerate(node_starts):
            end = (
                node_starts[position + 1]
                if position + 1 < len(node_starts)
                else reach_end
            )
            type_code, station = RasBreakout1D._parse_type_rm(lines[start])
            nodes.append(_NodeBlock(start, end, type_code, station))
        return lines, reach_start, nodes

    @staticmethod
    def _selection_has_lateral_structure(
        geom_file: Union[str, Path], selection: Breakout1DSelection
    ) -> bool:
        from .geom import GeomLateral

        laterals = GeomLateral.get_lateral_structures(geom_file, river=selection.river)
        if laterals.empty:
            return False
        laterals = laterals[laterals["Reach"] == selection.reach]
        upper = RasBreakout1D._station_value(selection.upstream_station)
        lower = RasBreakout1D._station_value(selection.downstream_station)
        for row in laterals.itertuples(index=False):
            if row.StartRS is None or row.EndRS is None:
                return True
            start = RasBreakout1D._station_value(row.StartRS)
            end = RasBreakout1D._station_value(row.EndRS)
            lateral_upper = max(start, end)
            lateral_lower = min(start, end)
            if lateral_lower <= upper and lateral_upper >= lower:
                return True
        return False

    @staticmethod
    def _parse_type_rm(line: str) -> tuple[int, str]:
        if "=" not in line:
            raise ValueError(f"Malformed Type RM line: {line!r}")
        values = [value.strip() for value in line.split("=", 1)[1].split(",")]
        if len(values) < 2:
            raise ValueError(f"Malformed Type RM line: {line!r}")
        return int(values[0] or 1), values[1]

    @staticmethod
    def _parse_reach_header(line: str) -> Optional[tuple[str, str]]:
        stripped = line.strip()
        if stripped.startswith("River Reach="):
            values = stripped.split("=", 1)[1].split(",")
            if len(values) >= 2:
                return values[0].strip(), values[1].strip()
        if stripped.startswith("Reach="):
            values = stripped.split("=", 1)[1].split(",")
            if len(values) >= 2:
                return values[0].strip(), values[1].strip()
        return None

    @staticmethod
    def _is_geometry_domain_header(line: str) -> bool:
        stripped = line.strip()
        return (
            RasBreakout1D._parse_reach_header(line) is not None
            or stripped.startswith("Junct Name=")
            or stripped.startswith("Storage Area=")
            or stripped.startswith("2D Flow Area=")
            or stripped.startswith("Connection=")
            or stripped.startswith("SA/2D Area Conn=")
        )

    @staticmethod
    def _first_geometry_domain_line(lines: Sequence[str]) -> int:
        for index, line in enumerate(lines):
            if RasBreakout1D._is_geometry_domain_header(line):
                return index
        raise ValueError("Geometry file has no river/reach domain records")

    @staticmethod
    def _zero_reach_lengths(line: str) -> str:
        newline = (
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        )
        body = line[: -len(newline)] if newline else line
        left, right = body.split("=", 1)
        values = right.split(",")
        while len(values) < 5:
            values.append("")
        values[2:5] = ["0", "0", "0"]
        return f"{left}={','.join(values)}{newline}"

    @staticmethod
    def _rewrite_plan(source_plan: Path, project_name: str) -> str:
        lines = source_plan.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        output = []
        saw_geom = False
        saw_flow = False
        for line in lines:
            if line.startswith("Geom File="):
                output.append("Geom File=g01\n")
                saw_geom = True
            elif line.startswith("Flow File="):
                output.append("Flow File=f01\n")
                saw_flow = True
            elif line.startswith(("Unsteady File=", "QuasiSteady File=")):
                continue
            elif line.startswith("Plan Title="):
                title = line.split("=", 1)[1].strip()
                output.append(f"Plan Title={project_name} - {title}\n")
            else:
                output.append(line)
        if not saw_geom:
            output.append("Geom File=g01\n")
        if not saw_flow:
            output.append("Flow File=f01\n")
        return "".join(output)

    @staticmethod
    def _rewrite_project(source_project: Path, project_name: str) -> str:
        lines = source_project.read_text(encoding="utf-8", errors="replace").splitlines(
            keepends=True
        )
        replacements = {
            "Proj Title=": f"Proj Title={project_name}\n",
            "Current Plan=": "Current Plan=p01\n",
            "Plan File=": "Plan File=p01\n",
            "Geom File=": "Geom File=g01\n",
            "Flow File=": "Flow File=f01\n",
        }
        excluded = ("Unsteady File=", "QuasiSteady File=", "Sediment File=")
        seen = {prefix: False for prefix in replacements}
        output: list[str] = []
        for line in lines:
            prefix = next(
                (candidate for candidate in replacements if line.startswith(candidate)),
                None,
            )
            if prefix is not None:
                if not seen[prefix]:
                    output.append(replacements[prefix])
                    seen[prefix] = True
                continue
            if line.startswith(excluded):
                continue
            output.append(line)

        missing = [replacements[prefix] for prefix, found in seen.items() if not found]
        if missing:
            insertion = 1 if output and output[0].startswith("Proj Title=") else 0
            output[insertion:insertion] = missing
        return "".join(output)

    @staticmethod
    def _prepare_empty_destination(destination: Path) -> None:
        if destination.exists():
            if not destination.is_dir():
                raise FileExistsError(f"Destination is not a directory: {destination}")
            if any(destination.iterdir()):
                raise FileExistsError(
                    f"Destination must be absent or empty: {destination}"
                )
        else:
            destination.mkdir(parents=True)

    @staticmethod
    def _safe_project_name(value: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value)).strip(" .")
        if not safe:
            raise ValueError("destination_name must contain a usable project name")
        return safe

    @staticmethod
    def _current_plan_number(project_file: Union[str, Path]) -> Optional[str]:
        for line in (
            Path(project_file)
            .read_text(encoding="utf-8", errors="replace")
            .splitlines()
        ):
            if line.startswith("Current Plan="):
                return line.split("=", 1)[1].strip().lower().removeprefix("p").zfill(2)
        return None

    @staticmethod
    def _expected_plan_hdf(plan_file: Path) -> Path:
        return Path(f"{plan_file}.hdf")

    @staticmethod
    def _station_value(value: Union[str, float, int]) -> float:
        match = _NUMBER_RE.search(str(value).replace(",", ""))
        if match is None:
            raise ValueError(f"River station is not numeric: {value!r}")
        return float(match.group(0))

    @staticmethod
    def _stations_equal(left: Any, right: Any) -> bool:
        return (
            abs(RasBreakout1D._station_value(left) - RasBreakout1D._station_value(right))
            <= 1e-9
        )

    @staticmethod
    def _matching_station_key(nodes: Mapping[str, _NodeBlock], station: str) -> str:
        matches = [key for key in nodes if RasBreakout1D._stations_equal(key, station)]
        if len(matches) != 1:
            raise ValueError(
                f"Station {station!r} resolved {len(matches)} times in geometry"
            )
        return matches[0]

    @staticmethod
    def _sha256(path: Union[str, Path]) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _text_sha256(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "RasBreakout1D",
    "Breakout1DDomainSelection",
    "Breakout1DResult",
    "Breakout1DSelection",
    "Breakout1DValidationReport",
]
