"""Extract independent, single-reach HEC-RAS 1D steady breakouts.

The MVP intentionally fails closed outside one continuous 1D reach and one
steady-flow plan.  Geometry node blocks are copied verbatim; the only geometry
record changed is the downstream retained cross section's reach-length triplet,
which is reset to zero because there is no downstream cross section in the
destination model.
"""

from __future__ import annotations

import hashlib
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
        from .geom import GeomParser

        cut_lines = GeomParser.get_xs_cut_lines(geom_file)
        intersecting = cut_lines[cut_lines.geometry.intersects(polygon)].copy()
        if river is not None:
            intersecting = intersecting[intersecting["river"] == river]
        if reach is not None:
            intersecting = intersecting[intersecting["reach"] == reach]
        if intersecting.empty:
            raise ValueError("Polygon does not intersect any cross-section cut lines")

        reaches = intersecting[["river", "reach"]].drop_duplicates()
        if len(reaches) != 1:
            choices = list(reaches.itertuples(index=False, name=None))
            raise ValueError(
                f"Polygon selection must resolve to exactly one reach; found {choices}"
            )
        resolved_river, resolved_reach = reaches.iloc[0].tolist()
        station_values = intersecting["station"].map(RasBreakout1D._station_value)
        selection = RasBreakout1D.select_by_stations(
            geom_file,
            str(resolved_river),
            str(resolved_reach),
            upstream_station=float(station_values.max()),
            downstream_station=float(station_values.min()),
        )
        return Breakout1DSelection(
            river=selection.river,
            reach=selection.reach,
            stations=selection.stations,
            upstream_station=selection.upstream_station,
            downstream_station=selection.downstream_station,
            selector="polygon",
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
    ) -> Breakout1DSelection:
        """Select the continuous XS span intersected by a supplied network edge.

        ``segment`` must be a Shapely-like line in the geometry coordinate
        system.  A positive ``tolerance`` buffers it by that coordinate-system
        distance before testing intersections.
        """
        if tolerance < 0:
            raise ValueError("tolerance must be non-negative")
        search_geometry = segment.buffer(tolerance) if tolerance else segment
        selection = RasBreakout1D.select_by_polygon(
            geom_file,
            search_geometry,
            river=river,
            reach=reach,
        )
        return Breakout1DSelection(
            river=selection.river,
            reach=selection.reach,
            stations=selection.stations,
            upstream_station=selection.upstream_station,
            downstream_station=selection.downstream_station,
            selector="network_segment",
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

        geometry_file.write_text(geometry_text, encoding="utf-8", newline="")
        from .RasSteady import RasSteady

        RasSteady.write_flow_file(flow_file, flow_data)
        plan_file.write_text(
            RasBreakout1D._rewrite_plan(source_plan, project_name),
            encoding="utf-8",
            newline="",
        )
        project_file.write_text(
            RasBreakout1D._rewrite_project(source_ras.prj_file, project_name),
            encoding="utf-8",
            newline="",
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
        reach_header = lines[reach_start : nodes[0].start]
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
        excluded = (
            "Current Plan=",
            "Plan File=",
            "Geom File=",
            "Flow File=",
            "Unsteady File=",
            "QuasiSteady File=",
            "Sediment File=",
        )
        remainder = [
            line
            for line in lines
            if not line.startswith(excluded) and not line.startswith("Proj Title=")
        ]
        header = [
            f"Proj Title={project_name}\n",
            "Current Plan=p01\n",
            "Plan File=p01\n",
            "Geom File=g01\n",
            "Flow File=f01\n",
        ]
        return "".join(header + remainder)

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
    "Breakout1DResult",
    "Breakout1DSelection",
    "Breakout1DValidationReport",
]
