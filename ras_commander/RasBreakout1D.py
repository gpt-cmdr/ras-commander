"""Extract and assemble independent HEC-RAS 1D steady breakouts.

Single-source extraction intentionally fails closed outside one continuous 1D
reach and one steady-flow plan. Multi-source assembly joins adjacent main-stem
reach slices selected by :meth:`RasBreakout1D.plan_network_edge`, restations the
retained nodes, and preserves their geometry payloads and source provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, Union

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.ops import unary_union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasNetworkConflation import (
    NetworkAdapter,
    NetworkEdgeCoveragePlanResult,
    NetworkEdgeCoverageResult,
    RasNetworkConflation,
)
from .RasPrj import RasPrj


if TYPE_CHECKING:
    from .ComputeResults import FlowPathPolicyResult


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


@dataclass
class Breakout1DAssemblyResult:
    """Artifacts and evidence produced by multi-source reach assembly.

    ``station_map_gdf`` is the authoritative source-to-destination node map.
    ``seams_gdf`` records the accepted centerline join and the adjacent source
    cross sections.  A provisional result preserves source overbank lengths and
    uses channel distance only for each new cross-source interval.  Pass audited
    ``flow_path_policy_results`` to :meth:`RasBreakout1D.assemble_network_edge`
    in a second destination to finalize those overbank lengths.
    """

    source_models: Mapping[str, RasPrj]
    destination_ras: RasPrj
    plan: "Breakout1DPlan"
    project_file: Path
    plan_file: Path
    geometry_file: Path
    flow_file: Path
    station_map_gdf: gpd.GeoDataFrame
    seams_gdf: gpd.GeoDataFrame
    validation: Breakout1DValidationReport
    boundary_provenance: str
    flow_path_policy: str
    reach_lengths_finalized: bool
    source_geometry_sha256: Mapping[str, str]
    compute_result: Any = None


@dataclass(frozen=True)
class Breakout1DSourceCatalog:
    """Normalized source models and geometry used to plan network breakouts."""

    models_df: pd.DataFrame
    footprints_gdf: gpd.GeoDataFrame
    centerlines_gdf: gpd.GeoDataFrame
    cross_sections_gdf: gpd.GeoDataFrame
    analysis_crs: str
    parameters: Mapping[str, Any]

    @property
    def summary(self) -> dict[str, int]:
        """Return catalog counts, including exact geometry duplicates."""
        active = self.models_df["included"].astype(bool)
        duplicate = self.models_df["duplicate_of"].notna()
        return {
            "source_models": int(len(self.models_df)),
            "included_models": int(active.sum()),
            "duplicate_models": int(duplicate.sum()),
            "reaches": int(len(self.centerlines_gdf)),
            "cross_sections": int(len(self.cross_sections_gdf)),
        }

    @log_call
    def write(
        self, directory: Union[str, Path], *, overwrite: bool = False
    ) -> Path:
        """Persist the catalog as Parquet and GeoParquet tables."""
        directory = Path(directory)
        outputs = {
            "models": directory / "models.parquet",
            "footprints": directory / "footprints.parquet",
            "centerlines": directory / "centerlines.parquet",
            "cross_sections": directory / "cross_sections.parquet",
            "metadata": directory / "catalog.json",
        }
        existing = [path for path in outputs.values() if path.exists()]
        if existing and not overwrite:
            raise FileExistsError(
                "Catalog outputs already exist: "
                + ", ".join(str(path) for path in existing)
            )
        directory.mkdir(parents=True, exist_ok=True)
        self.models_df.to_parquet(outputs["models"], index=False)
        self.footprints_gdf.to_parquet(outputs["footprints"], index=False)
        self.centerlines_gdf.to_parquet(outputs["centerlines"], index=False)
        self.cross_sections_gdf.to_parquet(
            outputs["cross_sections"], index=False
        )
        outputs["metadata"].write_text(
            json.dumps(
                {
                    "catalog_version": "1",
                    "analysis_crs": self.analysis_crs,
                    "parameters": dict(self.parameters),
                    "summary": self.summary,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return directory

    @classmethod
    @log_call
    def read(cls, directory: Union[str, Path]) -> "Breakout1DSourceCatalog":
        """Load a catalog written by :meth:`write`."""
        directory = Path(directory)
        metadata = json.loads(
            (directory / "catalog.json").read_text(encoding="utf-8")
        )
        if str(metadata.get("catalog_version")) != "1":
            raise ValueError(
                "Unsupported breakout source catalog version: "
                f"{metadata.get('catalog_version')!r}"
            )
        return cls(
            models_df=pd.read_parquet(directory / "models.parquet"),
            footprints_gdf=gpd.read_parquet(directory / "footprints.parquet"),
            centerlines_gdf=gpd.read_parquet(directory / "centerlines.parquet"),
            cross_sections_gdf=gpd.read_parquet(
                directory / "cross_sections.parquet"
            ),
            analysis_crs=str(metadata["analysis_crs"]),
            parameters=dict(metadata.get("parameters", {})),
        )


@dataclass(frozen=True)
class Breakout1DPlan:
    """Auditable source-coverage plan for one directed network edge.

    This first planning surface resolves model coverage and the best matching
    source reach inside each model. It does not yet approve or write the final
    cross-model hydraulic geometry seam.
    """

    edge_id: str
    source_models_df: pd.DataFrame
    reach_assignments_df: gpd.GeoDataFrame
    handoff_diagnostics_df: gpd.GeoDataFrame
    edge_coverage: NetworkEdgeCoverageResult
    coverage_plan: NetworkEdgeCoveragePlanResult
    analysis_crs: str
    parameters: Mapping[str, Any]

    @property
    def status(self) -> str:
        """Return the edge-level plan status, including handoff eligibility."""
        rows = self.coverage_plan.plans_df
        if len(rows) != 1:
            return "uncovered"
        coverage_status = str(rows.iloc[0]["status"])
        if (
            coverage_status == "multi_source_ready"
            and not self.handoff_diagnostics_df.empty
            and not self.handoff_diagnostics_df["handoff_eligible"].all()
        ):
            return "multi_source_handoff_conflict"
        return coverage_status

    @property
    def join_ready(self) -> bool:
        """Return whether coverage and every cross-model handoff are eligible."""
        return self.status in {"single_source_ready", "multi_source_ready"}

    @property
    def source_slices_df(self) -> gpd.GeoDataFrame:
        """Return selected upstream-to-downstream source ownership slices."""
        return self.coverage_plan.source_slices_df

    @property
    def seams_df(self) -> gpd.GeoDataFrame:
        """Return provisional footprint-overlap seam locations."""
        return self.coverage_plan.seams_df


@dataclass(frozen=True)
class _NodeBlock:
    start: int
    end: int
    type_code: int
    station: str


@dataclass
class _AssemblySource:
    """Resolved source-reach state used only while writing an assembly."""

    geometry_id: str
    ras_object: RasPrj
    plan: Mapping[str, Any]
    reach_id: str
    river: str
    reach: str
    centerline: Any
    lines: list[str]
    reach_start: int
    nodes: list[_NodeBlock]
    xs_rows: gpd.GeoDataFrame
    node_records: list[dict[str, Any]]
    direct_node_indexes: tuple[int, ...]
    inundation_node_indexes: tuple[int, ...]
    retained_start_index: int
    retained_end_index: int
    segment_start: float = 0.0
    segment_end: float = 0.0
    destination_offset: float = 0.0


class RasBreakout1D:
    """Static workflow for extracting or assembling a 1D steady breakout."""

    @staticmethod
    @log_call
    def catalog_sources(
        source_models: Mapping[str, RasPrj],
        *,
        plan_numbers: Optional[Mapping[str, Union[str, int]]] = None,
        model_footprints: Optional[gpd.GeoDataFrame] = None,
        analysis_crs: Optional[Any] = None,
        deduplicate: bool = True,
    ) -> Breakout1DSourceCatalog:
        """Catalog steady 1D source models for network-edge planning.

        ``source_models`` maps stable caller-defined model IDs to initialized
        :class:`RasPrj` objects. Exact duplicate geometry files are retained in
        ``models_df`` for provenance but excluded from the spatial catalog by
        default. Supplied footprints are authoritative. When omitted, an HDF
        project footprint is preferred and legacy text geometry falls back to
        the convex hull of its centerlines and cross-section cut lines.

        The returned tables use one projected ``analysis_crs`` and can be
        persisted with :meth:`Breakout1DSourceCatalog.write` as GeoParquet.
        """
        if not isinstance(source_models, Mapping) or not source_models:
            raise ValueError("source_models must be a non-empty mapping")
        normalized_sources: dict[str, RasPrj] = {}
        for raw_id, ras_object in source_models.items():
            source_id = str(raw_id).strip()
            if not source_id:
                raise ValueError("source_models contains a blank source model ID")
            if source_id in normalized_sources:
                raise ValueError(f"Duplicate source model ID: {source_id}")
            if not isinstance(ras_object, RasPrj) or not ras_object.is_initialized:
                raise TypeError(
                    f"source_models[{source_id!r}] must be an initialized RasPrj"
                )
            normalized_sources[source_id] = ras_object

        normalized_plan_numbers: dict[str, Union[str, int]] = {}
        if plan_numbers is not None:
            if not isinstance(plan_numbers, Mapping):
                raise TypeError("plan_numbers must be a mapping")
            for raw_id, plan_number in plan_numbers.items():
                source_id = str(raw_id).strip()
                if source_id in normalized_plan_numbers:
                    raise ValueError(
                        f"Duplicate plan_numbers source ID: {source_id}"
                    )
                normalized_plan_numbers[source_id] = plan_number
            unknown_plan_ids = sorted(
                set(normalized_plan_numbers) - set(normalized_sources)
            )
            if unknown_plan_ids:
                raise ValueError(
                    "plan_numbers contain unknown source model IDs: "
                    + ", ".join(unknown_plan_ids)
                )

        supplied_footprints = None
        if model_footprints is not None:
            if not isinstance(model_footprints, gpd.GeoDataFrame):
                raise TypeError("model_footprints must be a GeoDataFrame")
            if model_footprints.crs is None:
                raise ValueError("model_footprints must have a CRS")
            if "geometry_id" not in model_footprints.columns:
                raise ValueError("model_footprints must contain geometry_id")
            supplied_footprints = model_footprints.copy()
            supplied_footprints["geometry_id"] = supplied_footprints[
                "geometry_id"
            ].map(lambda value: str(value).strip())
            if supplied_footprints["geometry_id"].duplicated().any():
                raise ValueError("model_footprints geometry_id values must be unique")
            unknown = sorted(
                set(supplied_footprints["geometry_id"]) - set(normalized_sources)
            )
            if unknown:
                raise ValueError(
                    "model_footprints contain unknown source model IDs: "
                    + ", ".join(unknown)
                )

        crs_candidates = [analysis_crs]
        if supplied_footprints is not None:
            crs_candidates.append(supplied_footprints.crs)
        crs_candidates.extend(
            ras_object.project_crs for ras_object in normalized_sources.values()
        )
        target_crs_input = next(
            (value for value in crs_candidates if value is not None), None
        )
        if target_crs_input is None:
            raise ValueError(
                "analysis_crs is required when source projects and supplied "
                "footprints do not provide a CRS"
            )
        target_crs = CRS.from_user_input(target_crs_input)
        if not target_crs.is_projected:
            raise ValueError("analysis_crs must be projected")
        if supplied_footprints is not None:
            supplied_footprints = supplied_footprints.to_crs(target_crs)

        from .RasSteady import RasSteady

        resolved: list[dict[str, Any]] = []
        for source_id in sorted(normalized_sources):
            ras_object = normalized_sources[source_id]
            plan_number = normalized_plan_numbers.get(source_id)
            plan = RasBreakout1D._resolve_source_plan(ras_object, plan_number)
            flow_data = RasSteady.read_flow_file(plan["flow_path"])
            resolved.append(
                {
                    "geometry_id": source_id,
                    "ras_object": ras_object,
                    "plan": plan,
                    "geometry_hash": RasBreakout1D._sha256(plan["geometry_path"]),
                    "profile_names": tuple(flow_data.get("profile_names", ())),
                    "profile_count": int(flow_data.get("number_of_profiles", 0)),
                }
            )

        canonical_by_hash: dict[str, str] = {}
        model_rows: list[dict[str, Any]] = []
        for item in resolved:
            geometry_hash = item["geometry_hash"]
            duplicate_of = canonical_by_hash.get(geometry_hash)
            if duplicate_of is None:
                canonical_by_hash[geometry_hash] = item["geometry_id"]
            included = not (deduplicate and duplicate_of is not None)
            item["duplicate_of"] = duplicate_of
            item["included"] = included
            ras_object = item["ras_object"]
            plan = item["plan"]
            model_rows.append(
                {
                    "geometry_id": item["geometry_id"],
                    "project_path": str(Path(ras_object.prj_file).resolve()),
                    "project_name": str(ras_object.project_name),
                    "plan_number": str(plan["plan_number"]),
                    "geometry_path": str(Path(plan["geometry_path"]).resolve()),
                    "flow_path": str(Path(plan["flow_path"]).resolve()),
                    "geometry_sha256": geometry_hash,
                    "duplicate_of": duplicate_of,
                    "included": included,
                    "project_crs": ras_object.project_crs,
                    "units_system": RasBreakout1D._project_units_system(
                        ras_object.prj_file
                    ),
                    "ras_version": RasBreakout1D._keyword_value(
                        plan["plan_path"], "Program Version"
                    ),
                    "profile_count": item["profile_count"],
                    "profile_names": item["profile_names"],
                }
            )

        footprint_rows: list[dict[str, Any]] = []
        centerline_frames: list[gpd.GeoDataFrame] = []
        cross_section_frames: list[gpd.GeoDataFrame] = []
        from .geom import GeomParser

        for item in resolved:
            if not item["included"]:
                continue
            source_id = item["geometry_id"]
            ras_object = item["ras_object"]
            geom_file = Path(item["plan"]["geometry_path"])
            source_crs = CRS.from_user_input(
                ras_object.project_crs or target_crs
            )
            centerlines = GeomParser.get_river_centerlines(geom_file)
            cross_sections = GeomParser.get_xs_cut_lines(geom_file)
            if centerlines.empty:
                raise ValueError(f"Source model {source_id} has no river centerline")
            if len(cross_sections) < 2:
                raise ValueError(
                    f"Source model {source_id} must contain at least two GIS "
                    "cross-section cut lines"
                )
            centerlines = centerlines.set_crs(source_crs, allow_override=True).to_crs(
                target_crs
            )
            cross_sections = cross_sections.set_crs(
                source_crs, allow_override=True
            ).to_crs(target_crs)
            centerlines.insert(0, "geometry_id", source_id)
            centerlines.insert(
                1,
                "reach_id",
                centerlines.apply(
                    lambda row: RasBreakout1D._catalog_reach_id(
                        source_id, row["river"], row["reach"]
                    ),
                    axis=1,
                ),
            )
            cross_sections.insert(0, "geometry_id", source_id)
            cross_sections.insert(
                1,
                "reach_id",
                cross_sections.apply(
                    lambda row: RasBreakout1D._catalog_reach_id(
                        source_id, row["river"], row["reach"]
                    ),
                    axis=1,
                ),
            )
            cross_sections.insert(
                2,
                "xs_id",
                cross_sections.apply(
                    lambda row: f"{row['reach_id']}::{row['station']}", axis=1
                ),
            )
            centerline_frames.append(centerlines)
            cross_section_frames.append(cross_sections)

            supplied = None
            if supplied_footprints is not None:
                matches = supplied_footprints.loc[
                    supplied_footprints["geometry_id"] == source_id
                ]
                if len(matches) == 1:
                    supplied = matches.iloc[0].geometry
                elif len(matches) == 0:
                    raise ValueError(
                        f"model_footprints has no row for source model {source_id}"
                    )
            if supplied is not None:
                footprint_geometry = supplied
                footprint_source = "supplied"
            else:
                footprint_geometry, footprint_source = (
                    RasBreakout1D._catalog_footprint(
                        geom_file,
                        centerlines,
                        cross_sections,
                        source_crs=source_crs,
                        target_crs=target_crs,
                    )
                )
            if footprint_geometry is None or footprint_geometry.is_empty:
                raise ValueError(f"Source model {source_id} has an empty footprint")
            footprint_rows.append(
                {
                    "geometry_id": source_id,
                    "footprint_source": footprint_source,
                    "geometry": footprint_geometry,
                }
            )

        models_columns = [
            "geometry_id", "project_path", "project_name", "plan_number",
            "geometry_path", "flow_path", "geometry_sha256", "duplicate_of",
            "included", "project_crs", "units_system", "ras_version",
            "profile_count", "profile_names",
        ]
        models_df = pd.DataFrame(model_rows, columns=models_columns).sort_values(
            "geometry_id"
        ).reset_index(drop=True)
        footprints_gdf = gpd.GeoDataFrame(
            footprint_rows,
            columns=["geometry_id", "footprint_source", "geometry"],
            geometry="geometry",
            crs=target_crs,
        ).sort_values("geometry_id").reset_index(drop=True)
        centerlines_gdf = gpd.GeoDataFrame(
            pd.concat(centerline_frames, ignore_index=True),
            geometry="geometry",
            crs=target_crs,
        ).sort_values(["geometry_id", "river", "reach"]).reset_index(drop=True)
        cross_sections_gdf = gpd.GeoDataFrame(
            pd.concat(cross_section_frames, ignore_index=True),
            geometry="geometry",
            crs=target_crs,
        ).sort_values(
            ["geometry_id", "river", "reach", "station"]
        ).reset_index(drop=True)
        return Breakout1DSourceCatalog(
            models_df=models_df,
            footprints_gdf=footprints_gdf,
            centerlines_gdf=centerlines_gdf,
            cross_sections_gdf=cross_sections_gdf,
            analysis_crs=target_crs.to_string(),
            parameters={"deduplicate": bool(deduplicate)},
        )

    @staticmethod
    @log_call
    def plan_network_edge(
        source_catalog: Breakout1DSourceCatalog,
        network_edges: Union[gpd.GeoDataFrame, str, Path],
        *,
        edge_id: Optional[Union[str, int]] = None,
        adapter: Union[str, NetworkAdapter] = "auto",
        network_edges_layer: Optional[str] = None,
        min_xs_intersections: int = 2,
        xs_tolerance: float = 0.0,
        max_centerline_offset: Optional[float] = None,
        gap_tolerance: float = 0.0,
        max_cross_centerline_xs: int = 1,
    ) -> Breakout1DPlan:
        """Plan source-model coverage for one directed network edge.

        Footprints generate candidate models. A model is retained only when one
        source reach has at least ``min_xs_intersections`` cut lines meeting the
        edge and those sections form a monotonic upstream-to-downstream sequence
        in edge-coordinate order. The extent-first coverage planner then chooses
        a deterministic minimum-switch model chain.

        The returned seam points are provisional footprint handoffs. Geometry
        assembly must still evaluate source-centerline intersections, duplicate
        cut lines, structures, station identifiers, and steady-flow continuity.

        A cross-model handoff fails closed when more than
        ``max_cross_centerline_xs`` source cross sections intersect both selected
        river centerlines. This prevents the overlapping tributary/main-stem
        geometry seen in invalid candidates from being treated as join-ready.
        """
        if not isinstance(source_catalog, Breakout1DSourceCatalog):
            raise TypeError(
                "source_catalog must be a Breakout1DSourceCatalog"
            )
        if isinstance(min_xs_intersections, bool) or not isinstance(
            min_xs_intersections, int
        ):
            raise TypeError("min_xs_intersections must be an integer")
        if min_xs_intersections < 1:
            raise ValueError("min_xs_intersections must be at least 1")
        if isinstance(max_cross_centerline_xs, bool) or not isinstance(
            max_cross_centerline_xs, int
        ):
            raise TypeError("max_cross_centerline_xs must be an integer")
        if max_cross_centerline_xs < 0:
            raise ValueError("max_cross_centerline_xs must be non-negative")
        xs_tolerance = RasBreakout1D._nonnegative_distance(
            xs_tolerance, "xs_tolerance"
        )
        gap_tolerance = RasBreakout1D._nonnegative_distance(
            gap_tolerance, "gap_tolerance"
        )
        if max_centerline_offset is not None:
            max_centerline_offset = RasBreakout1D._nonnegative_distance(
                max_centerline_offset, "max_centerline_offset"
            )

        from shapely.ops import nearest_points

        raw_coverage = RasNetworkConflation.classify_edges(
            source_catalog.footprints_gdf[["geometry_id", "geometry"]],
            network_edges,
            adapter=adapter,
            network_edges_layer=network_edges_layer,
            analysis_crs=source_catalog.analysis_crs,
        )
        available_edge_ids = sorted(
            raw_coverage.edge_summary_df["edge_id"].astype(str).unique()
        )
        if edge_id is None:
            if len(available_edge_ids) != 1:
                raise ValueError(
                    "edge_id is required unless exactly one intersecting network "
                    f"edge is supplied; found {len(available_edge_ids)}"
                )
            resolved_edge_id = available_edge_ids[0]
        else:
            resolved_edge_id = str(edge_id)
            if resolved_edge_id not in available_edge_ids:
                raise ValueError(
                    f"Network edge {resolved_edge_id!r} has no catalog footprint "
                    "coverage"
                )
        edge_row = raw_coverage.edge_summary_df.loc[
            raw_coverage.edge_summary_df["edge_id"].astype(str)
            == resolved_edge_id
        ].iloc[0]
        edge_geometry = edge_row.geometry
        xs_test_geometry = (
            edge_geometry.buffer(xs_tolerance)
            if xs_tolerance > 0
            else edge_geometry
        )

        assignment_rows: list[dict[str, Any]] = []
        relationships = raw_coverage.coverage_df.loc[
            raw_coverage.coverage_df["edge_id"].astype(str)
            == resolved_edge_id
        ]
        for relationship in relationships.itertuples(index=False):
            source_id = str(relationship.geometry_id)
            source_centerlines = source_catalog.centerlines_gdf.loc[
                source_catalog.centerlines_gdf["geometry_id"].astype(str)
                == source_id
            ]
            source_cross_sections = source_catalog.cross_sections_gdf.loc[
                source_catalog.cross_sections_gdf["geometry_id"].astype(str)
                == source_id
            ]
            candidates: list[dict[str, Any]] = []
            for centerline in source_centerlines.itertuples(index=False):
                reach_xs = source_cross_sections.loc[
                    source_cross_sections["reach_id"] == centerline.reach_id
                ]
                intersected = reach_xs.loc[
                    reach_xs.intersects(xs_test_geometry)
                ].copy()
                measures = []
                if not intersected.empty:
                    intersected["_station_value"] = intersected["station"].map(
                        RasBreakout1D._station_value
                    )
                    intersected = intersected.sort_values(
                        "_station_value", ascending=False
                    )
                    for xs_geometry in intersected.geometry:
                        edge_point, _ = nearest_points(edge_geometry, xs_geometry)
                        measures.append(float(edge_geometry.project(edge_point)))
                sequence = RasBreakout1D._measure_sequence(
                    measures, tolerance=max(xs_tolerance, 1e-9)
                )
                covered_parts = raw_coverage.coverage_parts_df.loc[
                    (
                        raw_coverage.coverage_parts_df["edge_id"].astype(str)
                        == resolved_edge_id
                    )
                    & (
                        raw_coverage.coverage_parts_df["geometry_id"].astype(str)
                        == source_id
                    )
                ]
                sample_points = []
                for part in covered_parts.geometry:
                    if part is None or part.is_empty or part.length <= 0:
                        continue
                    sample_points.extend(
                        part.interpolate(fraction, normalized=True)
                        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0)
                    )
                offsets = [
                    float(point.distance(centerline.geometry))
                    for point in sample_points
                ]
                candidates.append(
                    {
                        "geometry_id": source_id,
                        "edge_id": resolved_edge_id,
                        "reach_id": str(centerline.reach_id),
                        "river": str(centerline.river),
                        "reach": str(centerline.reach),
                        "xs_intersection_count": int(len(intersected)),
                        "xs_measure_start": min(measures) if measures else None,
                        "xs_measure_end": max(measures) if measures else None,
                        "xs_sequence": sequence,
                        "centerline_offset_mean": (
                            float(sum(offsets) / len(offsets)) if offsets else None
                        ),
                        "geometry": centerline.geometry,
                    }
                )

            candidates.sort(
                key=lambda item: (
                    -item["xs_intersection_count"],
                    (
                        item["centerline_offset_mean"]
                        if item["centerline_offset_mean"] is not None
                        else float("inf")
                    ),
                    item["reach_id"],
                )
            )
            best = candidates[0] if candidates else None
            ambiguous = False
            if best is not None and len(candidates) > 1:
                runner_up = candidates[1]
                runner_offset = runner_up["centerline_offset_mean"]
                best_offset = best["centerline_offset_mean"]
                ambiguous = (
                    runner_up["xs_intersection_count"]
                    == best["xs_intersection_count"]
                    and math.isclose(
                        (
                            runner_offset
                            if runner_offset is not None
                            else float("inf")
                        ),
                        best_offset if best_offset is not None else float("inf"),
                        rel_tol=0.0,
                        abs_tol=max(xs_tolerance, 1e-9),
                    )
                )
            reason_codes: list[str] = []
            if best is None:
                status = "unmatched"
                reason_codes.append("NO_REACH")
                best = {
                    "geometry_id": source_id,
                    "edge_id": resolved_edge_id,
                    "reach_id": None,
                    "river": None,
                    "reach": None,
                    "xs_intersection_count": 0,
                    "xs_measure_start": None,
                    "xs_measure_end": None,
                    "xs_sequence": "unavailable",
                    "centerline_offset_mean": None,
                    "geometry": None,
                }
            elif ambiguous:
                status = "ambiguous"
                reason_codes.append("AMBIGUOUS_REACH")
            elif best["xs_intersection_count"] < min_xs_intersections:
                status = "unmatched"
                reason_codes.append("INSUFFICIENT_XS_INTERSECTIONS")
            elif best["xs_sequence"] != "with_edge":
                status = "unmatched"
                reason_codes.append("XS_SEQUENCE_CONFLICT")
            elif (
                max_centerline_offset is not None
                and best["centerline_offset_mean"] is not None
                and best["centerline_offset_mean"] > max_centerline_offset
            ):
                status = "unmatched"
                reason_codes.append("CENTERLINE_OFFSET")
            else:
                status = "confirmed"
            assignment_rows.append(
                {
                    **best,
                    "status": status,
                    "reason_codes": tuple(reason_codes),
                }
            )

        assignment_columns = [
            "geometry_id", "edge_id", "reach_id", "river", "reach",
            "xs_intersection_count", "xs_measure_start", "xs_measure_end",
            "xs_sequence", "centerline_offset_mean", "status",
            "reason_codes", "geometry",
        ]
        reach_assignments = gpd.GeoDataFrame(
            assignment_rows,
            columns=assignment_columns,
            geometry="geometry",
            crs=source_catalog.analysis_crs,
        ).sort_values(
            ["status", "xs_intersection_count", "geometry_id"],
            ascending=[True, False, True],
        ).reset_index(drop=True)
        confirmed_ids = set(
            reach_assignments.loc[
                reach_assignments["status"] == "confirmed", "geometry_id"
            ].astype(str)
        )
        if not confirmed_ids:
            raise ValueError(
                f"No source reaches were confirmed for network edge {resolved_edge_id}"
            )
        confirmed_footprints = source_catalog.footprints_gdf.loc[
            source_catalog.footprints_gdf["geometry_id"].astype(str).isin(
                confirmed_ids
            )
        ]
        confirmed_coverage = RasNetworkConflation.classify_edges(
            confirmed_footprints[["geometry_id", "geometry"]],
            network_edges,
            adapter=adapter,
            network_edges_layer=network_edges_layer,
            analysis_crs=source_catalog.analysis_crs,
        )
        coverage_plan = RasNetworkConflation.plan_edge_coverage(
            confirmed_coverage,
            edge_ids=[resolved_edge_id],
            gap_tolerance=gap_tolerance,
        )
        selected_source_order = tuple(
            dict.fromkeys(
                coverage_plan.source_slices_df["geometry_id"].astype(str)
            )
        )
        selected_source_ids = set(selected_source_order)
        source_order = {
            source_id: index
            for index, source_id in enumerate(selected_source_order)
        }
        source_models_df = source_catalog.models_df.loc[
            source_catalog.models_df["geometry_id"].astype(str).isin(
                selected_source_ids
            )
        ].copy()
        source_models_df["_source_order"] = source_models_df[
            "geometry_id"
        ].astype(str).map(source_order)
        source_models_df = source_models_df.sort_values(
            "_source_order"
        ).drop(columns="_source_order").reset_index(drop=True)
        handoff_diagnostics = RasBreakout1D._handoff_diagnostics(
            source_catalog,
            reach_assignments,
            coverage_plan,
            max_cross_centerline_xs=max_cross_centerline_xs,
        )
        return Breakout1DPlan(
            edge_id=resolved_edge_id,
            source_models_df=source_models_df,
            reach_assignments_df=reach_assignments,
            handoff_diagnostics_df=handoff_diagnostics,
            edge_coverage=confirmed_coverage,
            coverage_plan=coverage_plan,
            analysis_crs=source_catalog.analysis_crs,
            parameters={
                "adapter": getattr(adapter, "name", str(adapter)),
                "min_xs_intersections": min_xs_intersections,
                "xs_tolerance": xs_tolerance,
                "max_centerline_offset": max_centerline_offset,
                "gap_tolerance": gap_tolerance,
                "max_cross_centerline_xs": max_cross_centerline_xs,
                "seam_status": "provisional_footprint_handoff",
            },
        )

    @staticmethod
    @log_call
    def assemble_network_edge(
        source_models: Mapping[str, RasPrj],
        source_catalog: Breakout1DSourceCatalog,
        breakout_plan: Breakout1DPlan,
        destination: Union[str, Path],
        *,
        destination_name: Optional[str] = None,
        destination_river: Optional[str] = None,
        destination_reach: str = "Main",
        upstream_buffer_distance: Optional[float] = None,
        downstream_buffer_distance: Optional[float] = None,
        inundation_overlap_xs: int = 1,
        boundary_mode: str = "auto",
        downstream_boundary: Optional[Mapping[str, Any]] = None,
        flow_path_policy_results: Optional[
            Mapping[int, "FlowPathPolicyResult"]
        ] = None,
        run: bool = False,
        verify_run: bool = True,
        compute_kwargs: Optional[Mapping[str, Any]] = None,
    ) -> Breakout1DAssemblyResult:
        """Write one restationed reach from adjacent source-model reaches.

        The directed network edge and accepted source order come from
        ``breakout_plan``.  Cross sections intersecting the edge are assigned to
        the source owning that edge interval.  When the edge is fully covered,
        omitted hydraulic buffers default to 10 percent upstream and 25 percent
        downstream of the assembled main-channel length represented by the
        direct target span. ``inundation_overlap_xs`` marks the smaller
        raster-export domain without reducing the computational model.

        Complete retained node payloads are copied from the source geometries;
        only ``Type RM Length L Ch R`` is rewritten.  Every retained node is
        restationed from the downstream end of the joined centerline, main
        channel lengths are recomputed from that line, and station-keyed steady
        flow changes are rewritten to the destination reach.

        With no ``flow_path_policy_results``, source LOB/ROB lengths are
        preserved within each source and the new cross-source interval uses its
        channel length provisionally.  For a final geometry, pass one
        :class:`FlowPathPolicyResult` per seam, keyed by zero-based seam index,
        after auditing a provisional assembled geometry.  Regenerate-policy
        evidence replaces all LOB/ROB lengths; preserve-policy evidence replaces
        only the corresponding join interval with the clipped review-segment
        lengths.
        """
        if not isinstance(source_catalog, Breakout1DSourceCatalog):
            raise TypeError("source_catalog must be a Breakout1DSourceCatalog")
        if not isinstance(breakout_plan, Breakout1DPlan):
            raise TypeError("breakout_plan must be a Breakout1DPlan")
        if not breakout_plan.join_ready:
            raise ValueError(
                "breakout_plan is not join-ready: "
                f"status={breakout_plan.status!r}"
            )
        if breakout_plan.status != "multi_source_ready":
            raise ValueError(
                "assemble_network_edge requires a multi-source-ready plan"
            )
        if not isinstance(source_models, Mapping) or not source_models:
            raise ValueError("source_models must be a non-empty mapping")
        if isinstance(inundation_overlap_xs, bool) or not isinstance(
            inundation_overlap_xs, int
        ):
            raise TypeError("inundation_overlap_xs must be an integer")
        if inundation_overlap_xs < 0:
            raise ValueError("inundation_overlap_xs must be non-negative")
        if upstream_buffer_distance is not None:
            upstream_buffer_distance = RasBreakout1D._nonnegative_distance(
                upstream_buffer_distance, "upstream_buffer_distance"
            )
        if downstream_buffer_distance is not None:
            downstream_buffer_distance = RasBreakout1D._nonnegative_distance(
                downstream_buffer_distance, "downstream_buffer_distance"
            )
        if flow_path_policy_results is not None and not isinstance(
            flow_path_policy_results, Mapping
        ):
            raise TypeError("flow_path_policy_results must be a mapping")

        destination = Path(destination)
        RasBreakout1D._prepare_empty_destination(destination)
        project_name = RasBreakout1D._safe_project_name(
            destination_name or destination.name
        )
        river_name = RasBreakout1D._assembly_reach_name(
            destination_river or str(breakout_plan.edge_id)[:16],
            "destination_river",
        )
        reach_name = RasBreakout1D._assembly_reach_name(
            destination_reach, "destination_reach"
        )

        assembly = RasBreakout1D._build_multi_source_assembly(
            source_models,
            source_catalog,
            breakout_plan,
            destination_river=river_name,
            destination_reach=reach_name,
            upstream_buffer_distance=upstream_buffer_distance,
            downstream_buffer_distance=downstream_buffer_distance,
            inundation_overlap_xs=inundation_overlap_xs,
            boundary_mode=boundary_mode,
            downstream_boundary=downstream_boundary,
            flow_path_policy_results=flow_path_policy_results,
        )

        template_source = assembly["sources"][0]
        project_file = destination / f"{project_name}.prj"
        plan_file = destination / f"{project_name}.p01"
        geometry_file = destination / f"{project_name}.g01"
        flow_file = destination / f"{project_name}.f01"
        geometry_file.write_text(
            assembly["geometry_text"], encoding="utf-8", newline="\r\n"
        )
        from .RasSteady import RasSteady

        RasSteady.write_flow_file(flow_file, assembly["flow_data"])
        plan_file.write_text(
            RasBreakout1D._rewrite_plan(
                Path(template_source.plan["plan_path"]), project_name
            ),
            encoding="utf-8",
            newline="\r\n",
        )
        project_file.write_text(
            RasBreakout1D._rewrite_project(
                template_source.ras_object.prj_file, project_name
            ),
            encoding="utf-8",
            newline="\r\n",
        )

        for source_id, expected_hash in assembly[
            "source_geometry_sha256"
        ].items():
            source_path = Path(
                next(
                    source.plan["geometry_path"]
                    for source in assembly["sources"]
                    if source.geometry_id == source_id
                )
            )
            if RasBreakout1D._sha256(source_path) != expected_hash:
                raise RuntimeError(
                    f"Source geometry {source_id!r} changed during assembly"
                )

        destination_ras = RasPrj()
        destination_ras.initialize(
            destination,
            template_source.ras_object.ras_exe_path,
            suppress_logging=True,
            prj_file=project_file,
            load_results_summary=False,
            load_hdf_metadata=False,
        )
        validation = RasBreakout1D._validate_multi_source_assembly(
            destination_ras,
            station_map_gdf=assembly["station_map_gdf"],
            seams_gdf=assembly["seams_gdf"],
            source_geometry_sha256=assembly["source_geometry_sha256"],
            source_paths={
                source.geometry_id: Path(source.plan["geometry_path"])
                for source in assembly["sources"]
            },
            profile_names=tuple(assembly["flow_data"]["profile_names"]),
            reach_lengths_finalized=assembly["reach_lengths_finalized"],
        )
        validation.raise_for_errors()
        result = Breakout1DAssemblyResult(
            source_models={
                source.geometry_id: source.ras_object
                for source in assembly["sources"]
            },
            destination_ras=destination_ras,
            plan=breakout_plan,
            project_file=project_file,
            plan_file=plan_file,
            geometry_file=geometry_file,
            flow_file=flow_file,
            station_map_gdf=assembly["station_map_gdf"],
            seams_gdf=assembly["seams_gdf"],
            validation=validation,
            boundary_provenance=assembly["boundary_provenance"],
            flow_path_policy=assembly["flow_path_policy"],
            reach_lengths_finalized=assembly["reach_lengths_finalized"],
            source_geometry_sha256=assembly["source_geometry_sha256"],
        )
        if run:
            result.compute_result = RasBreakout1D.run(
                result,
                verify=verify_run,
                **dict(compute_kwargs or {}),
            )
        logger.info(
            "Assembled %s from %d source models with %d retained cross sections",
            project_file,
            len(result.source_models),
            int((result.station_map_gdf["source_node_type"] == 1).sum()),
        )
        return result

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
        breakout: Union[Breakout1DResult, Breakout1DAssemblyResult, RasPrj],
        *,
        plan_number: Union[str, int] = "01",
        verify: bool = True,
        **compute_kwargs: Any,
    ) -> Any:
        """Explicitly run a destination breakout through ``RasCmdr``."""
        from .RasCmdr import RasCmdr

        ras_object = (
            breakout.destination_ras
            if isinstance(
                breakout, (Breakout1DResult, Breakout1DAssemblyResult)
            )
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
    def _build_multi_source_assembly(
        source_models: Mapping[str, RasPrj],
        source_catalog: Breakout1DSourceCatalog,
        breakout_plan: Breakout1DPlan,
        *,
        destination_river: str,
        destination_reach: str,
        upstream_buffer_distance: Optional[float],
        downstream_buffer_distance: Optional[float],
        inundation_overlap_xs: int,
        boundary_mode: str,
        downstream_boundary: Optional[Mapping[str, Any]],
        flow_path_policy_results: Optional[
            Mapping[int, "FlowPathPolicyResult"]
        ],
    ) -> dict[str, Any]:
        """Resolve source slices and author one in-memory joined reach."""
        from shapely.geometry import LineString
        from shapely.ops import linemerge, nearest_points, substring

        normalized_models = {
            str(source_id): ras_object
            for source_id, ras_object in source_models.items()
        }
        slice_rows = breakout_plan.source_slices_df.sort_values(
            "source_order"
        )
        source_chain = list(slice_rows["geometry_id"].astype(str))
        if len(source_chain) < 2:
            raise ValueError("At least two source slices are required for assembly")
        if len(source_chain) != len(set(source_chain)):
            raise NotImplementedError(
                "A source model repeated in non-contiguous ownership slices is "
                "not supported by the current writer"
            )
        missing_models = sorted(set(source_chain) - set(normalized_models))
        if missing_models:
            raise ValueError(
                "source_models is missing planned source IDs: "
                + ", ".join(missing_models)
            )

        edge_rows = breakout_plan.coverage_plan.plans_df.loc[
            breakout_plan.coverage_plan.plans_df["edge_id"].astype(str)
            == breakout_plan.edge_id
        ]
        if len(edge_rows) != 1:
            raise ValueError("breakout_plan must contain exactly one target edge")
        edge_geometry = edge_rows.iloc[0].geometry
        if not isinstance(edge_geometry, LineString):
            edge_geometry = linemerge(edge_geometry)
        if not isinstance(edge_geometry, LineString) or edge_geometry.length <= 0:
            raise ValueError("Target edge must resolve to one non-empty LineString")
        edge_length = float(edge_geometry.length)
        fully_covered = bool(edge_rows.iloc[0]["fully_covered"])
        upstream_buffer = (
            float(upstream_buffer_distance)
            if upstream_buffer_distance is not None
            else None
        )
        downstream_buffer = (
            float(downstream_buffer_distance)
            if downstream_buffer_distance is not None
            else None
        )
        xs_tolerance = float(breakout_plan.parameters.get("xs_tolerance", 0.0))
        assignments = breakout_plan.reach_assignments_df.loc[
            breakout_plan.reach_assignments_df["status"] == "confirmed"
        ]
        assignment_by_source = {
            str(row.geometry_id): row for row in assignments.itertuples(index=False)
        }
        catalog_models = source_catalog.models_df.copy()
        if "geometry_id" in catalog_models:
            catalog_models["geometry_id"] = catalog_models["geometry_id"].astype(str)

        sources: list[_AssemblySource] = []
        source_hashes: dict[str, str] = {}
        profile_names: Optional[tuple[str, ...]] = None
        units_system: Optional[str] = None
        for source_id in source_chain:
            ras_object = normalized_models[source_id]
            if not isinstance(ras_object, RasPrj) or not ras_object.is_initialized:
                raise TypeError(
                    f"source_models[{source_id!r}] must be an initialized RasPrj"
                )
            assignment = assignment_by_source.get(source_id)
            if assignment is None:
                raise ValueError(f"No confirmed reach assignment for {source_id!r}")
            model_rows = catalog_models.loc[
                catalog_models["geometry_id"] == source_id
            ]
            if len(model_rows) != 1:
                raise ValueError(
                    f"Catalog model {source_id!r} resolved {len(model_rows)} times"
                )
            model_row = model_rows.iloc[0]
            project_crs = model_row.get("project_crs")
            if pd.notna(project_crs) and str(project_crs).strip():
                if CRS.from_user_input(project_crs) != CRS.from_user_input(
                    source_catalog.analysis_crs
                ):
                    raise ValueError(
                        f"Source {source_id!r} project CRS must match the catalog "
                        "analysis CRS before text geometry blocks can be combined"
                    )
            plan_number = (
                model_row.get("plan_number")
                if pd.notna(model_row.get("plan_number"))
                else None
            )
            source_plan = RasBreakout1D._resolve_source_plan(
                ras_object, plan_number
            )
            geometry_path = Path(source_plan["geometry_path"])
            geometry_hash = RasBreakout1D._sha256(geometry_path)
            catalog_hash = model_row.get("geometry_sha256")
            if pd.notna(catalog_hash) and str(catalog_hash) != geometry_hash:
                raise ValueError(
                    f"Source geometry {source_id!r} no longer matches its catalog hash"
                )
            source_hashes[source_id] = geometry_hash

            current_profiles = tuple(model_row.get("profile_names", ()))
            if not current_profiles:
                from .RasSteady import RasSteady

                current_profiles = tuple(
                    RasSteady.read_flow_file(source_plan["flow_path"])[
                        "profile_names"
                    ]
                )
            if profile_names is None:
                profile_names = current_profiles
            elif current_profiles != profile_names:
                raise ValueError(
                    "All source plans must use identical steady profile names and "
                    f"order; {source_id!r} has {current_profiles!r}, expected "
                    f"{profile_names!r}"
                )
            current_units = model_row.get("units_system")
            if pd.notna(current_units) and str(current_units).strip():
                if units_system is None:
                    units_system = str(current_units)
                elif str(current_units) != units_system:
                    raise ValueError(
                        "All source models must use the same units system; "
                        f"{source_id!r} has {current_units!r}, expected "
                        f"{units_system!r}"
                    )

            centerline = assignment.geometry
            if not isinstance(centerline, LineString):
                centerline = linemerge(centerline)
            if not isinstance(centerline, LineString) or centerline.length <= 0:
                raise ValueError(
                    f"Source centerline {source_id!r} is not one LineString"
                )
            xs_rows = source_catalog.cross_sections_gdf.loc[
                source_catalog.cross_sections_gdf["reach_id"].astype(str)
                == str(assignment.reach_id)
            ].copy()
            if xs_rows.empty:
                raise ValueError(f"Source reach {assignment.reach_id!r} has no cut lines")
            xs_rows["_station_value"] = xs_rows["station"].map(
                RasBreakout1D._station_value
            )
            xs_rows = xs_rows.sort_values("_station_value", ascending=False)
            preliminary_measures = []
            for xs_geometry in xs_rows.geometry:
                center_point, _ = nearest_points(centerline, xs_geometry)
                preliminary_measures.append(float(centerline.project(center_point)))
            if len(preliminary_measures) >= 2 and (
                preliminary_measures[-1] < preliminary_measures[0]
            ):
                centerline = LineString(list(centerline.coords)[::-1])
            xs_rows["_source_measure"] = [
                float(centerline.project(nearest_points(centerline, geometry)[0]))
                for geometry in xs_rows.geometry
            ]
            if any(
                right <= left + 1e-9
                for left, right in zip(
                    xs_rows["_source_measure"],
                    xs_rows["_source_measure"].iloc[1:],
                )
            ):
                raise ValueError(
                    f"Cross sections on {source_id!r}/{assignment.reach_id!r} "
                    "are not strictly ordered along the source centerline"
                )
            xs_rows["_edge_distance"] = xs_rows.geometry.distance(edge_geometry)
            xs_rows["_edge_measure"] = [
                float(edge_geometry.project(nearest_points(edge_geometry, geometry)[0]))
                for geometry in xs_rows.geometry
            ]

            lines, reach_start, nodes = RasBreakout1D._target_reach_parts(
                geometry_path, str(assignment.river), str(assignment.reach)
            )
            if RasBreakout1D._selection_has_lateral_structure(
                geometry_path,
                Breakout1DSelection(
                    river=str(assignment.river),
                    reach=str(assignment.reach),
                    stations=tuple(xs_rows["station"].astype(str)),
                    upstream_station=str(xs_rows.iloc[0]["station"]),
                    downstream_station=str(xs_rows.iloc[-1]["station"]),
                    selector="network_edge_assembly",
                ),
            ):
                raise NotImplementedError(
                    "Lateral structures are outside the multi-source 1D writer MVP"
                )
            node_records = RasBreakout1D._assembly_node_records(
                source_id,
                str(assignment.reach_id),
                str(assignment.river),
                str(assignment.reach),
                centerline,
                xs_rows,
                lines,
                nodes,
            )
            sources.append(
                _AssemblySource(
                    geometry_id=source_id,
                    ras_object=ras_object,
                    plan=source_plan,
                    reach_id=str(assignment.reach_id),
                    river=str(assignment.river),
                    reach=str(assignment.reach),
                    centerline=centerline,
                    lines=lines,
                    reach_start=reach_start,
                    nodes=nodes,
                    xs_rows=xs_rows,
                    node_records=node_records,
                    direct_node_indexes=(),
                    inundation_node_indexes=(),
                    retained_start_index=0,
                    retained_end_index=0,
                )
            )

        seam_records = RasBreakout1D._resolve_assembly_seams(
            sources, breakout_plan, edge_geometry
        )
        seam_measures = [float(item["edge_measure"]) for item in seam_records]
        if any(
            right <= left + 1e-9
            for left, right in zip(seam_measures, seam_measures[1:])
        ):
            raise ValueError("Resolved centerline joins are not downstream ordered")

        for source_index, source in enumerate(sources):
            lower = 0.0 if source_index == 0 else seam_measures[source_index - 1]
            upper = (
                edge_length
                if source_index == len(sources) - 1
                else seam_measures[source_index]
            )
            natural = [
                record for record in source.node_records if record["node_type"] == 1
            ]
            direct = [
                record
                for record in natural
                if record["edge_distance"] <= xs_tolerance + 1e-9
                and record["edge_measure"] >= lower - 1e-9
                and record["edge_measure"] <= upper + 1e-9
            ]
            if not direct:
                raise ValueError(
                    f"Source {source.geometry_id!r} owns no cross section at its "
                    "resolved centerline interval"
                )
            direct_indexes = tuple(int(record["node_index"]) for record in direct)
            inundation_indexes = list(direct_indexes)
            if source_index == len(sources) - 1 and inundation_overlap_xs:
                natural_indexes = [int(record["node_index"]) for record in natural]
                last_direct_position = natural_indexes.index(direct_indexes[-1])
                inundation_indexes.extend(
                    natural_indexes[
                        last_direct_position + 1 :
                        last_direct_position + 1 + inundation_overlap_xs
                    ]
                )
            source.direct_node_indexes = direct_indexes
            source.inundation_node_indexes = tuple(dict.fromkeys(inundation_indexes))
            source.retained_start_index = direct_indexes[0]
            source.retained_end_index = source.inundation_node_indexes[-1]

        direct_main_channel_length = 0.0
        for source_index, source in enumerate(sources):
            natural = [
                record for record in source.node_records if record["node_type"] == 1
            ]
            direct = [
                record
                for record in natural
                if record["node_index"] in source.direct_node_indexes
            ]
            start = (
                float(direct[0]["source_measure"])
                if source_index == 0
                else float(
                    seam_records[source_index - 1]["downstream_source_measure"]
                )
            )
            end = (
                float(direct[-1]["source_measure"])
                if source_index == len(sources) - 1
                else float(seam_records[source_index]["upstream_source_measure"])
            )
            direct_main_channel_length += max(0.0, end - start)
            if source_index:
                direct_main_channel_length += float(
                    seam_records[source_index - 1]["connector_length"]
                )
        if upstream_buffer is None:
            upstream_buffer = (
                direct_main_channel_length * 0.10 if fully_covered else 0.0
            )
        if downstream_buffer is None:
            downstream_buffer = (
                direct_main_channel_length * 0.25 if fully_covered else 0.0
            )

        first_source = sources[0]
        first_natural = [
            record
            for record in first_source.node_records
            if record["node_type"] == 1
        ]
        if upstream_buffer > 0:
            first_source.retained_start_index = (
                RasBreakout1D._expand_assembly_boundary(
                    first_natural,
                    first_source.direct_node_indexes[0],
                    upstream_buffer,
                    upstream=True,
                )
            )
        last_source = sources[-1]
        last_natural = [
            record
            for record in last_source.node_records
            if record["node_type"] == 1
        ]
        if downstream_buffer > 0:
            last_source.retained_end_index = max(
                last_source.retained_end_index,
                RasBreakout1D._expand_assembly_boundary(
                    last_natural,
                    last_source.direct_node_indexes[-1],
                    downstream_buffer,
                    upstream=False,
                ),
            )

        boundary_extension = max(
            1e-3, min(1.0, direct_main_channel_length * 1e-4)
        )
        for index, source in enumerate(sources):
            retained_natural = [
                record
                for record in source.node_records
                if record["node_type"] == 1
                and source.retained_start_index
                <= record["node_index"]
                <= source.retained_end_index
            ]
            source.segment_start = (
                max(
                    0.0,
                    float(retained_natural[0]["source_measure"])
                    - boundary_extension,
                )
                if index == 0
                else float(seam_records[index - 1]["downstream_source_measure"])
            )
            source.segment_end = (
                min(
                    float(source.centerline.length),
                    float(retained_natural[-1]["source_measure"])
                    + boundary_extension,
                )
                if index == len(sources) - 1
                else float(seam_records[index]["upstream_source_measure"])
            )
            if source.segment_end <= source.segment_start + 1e-9:
                raise ValueError(
                    f"Source segment {source.geometry_id!r} has non-positive "
                    "length after applying joins"
                )
            for record in retained_natural:
                measure = float(record["source_measure"])
                if not (
                    source.segment_start - 1e-6
                    <= measure
                    <= source.segment_end + 1e-6
                ):
                    raise ValueError(
                        f"Retained cross section {record['source_station']!r} is "
                        f"outside the joined source segment {source.geometry_id!r}"
                    )

        joined_coordinates: list[tuple[float, float]] = []
        running_length = 0.0
        for index, source in enumerate(sources):
            segment = substring(
                source.centerline, source.segment_start, source.segment_end
            )
            if not isinstance(segment, LineString) or len(segment.coords) < 2:
                raise ValueError(
                    f"Source {source.geometry_id!r} did not produce a usable segment"
                )
            if index:
                connector_start = seam_records[index - 1]["upstream_point"]
                connector_end = seam_records[index - 1]["downstream_point"]
                connector = LineString([connector_start, connector_end])
                if connector.length > 1e-9:
                    RasBreakout1D._append_coordinates(
                        joined_coordinates, list(connector.coords)
                    )
                    running_length += float(connector.length)
            source.destination_offset = running_length
            RasBreakout1D._append_coordinates(
                joined_coordinates, list(segment.coords)
            )
            running_length += float(segment.length)
        joined_centerline = LineString(joined_coordinates)
        if not joined_centerline.is_simple:
            raise ValueError("Joined river centerline is self-intersecting")

        retained_records: list[dict[str, Any]] = []
        for source in sources:
            for record in source.node_records:
                if not (
                    source.retained_start_index
                    <= record["node_index"]
                    <= source.retained_end_index
                ):
                    continue
                item = dict(record)
                item["centerline_measure"] = source.destination_offset + (
                    float(record["source_measure"]) - source.segment_start
                )
                item["in_direct_domain"] = (
                    record["node_type"] == 1
                    and record["node_index"] in source.direct_node_indexes
                )
                item["in_inundation_domain"] = (
                    record["node_type"] == 1
                    and record["node_index"] in source.inundation_node_indexes
                )
                retained_records.append(item)
        retained_records.sort(key=lambda item: item["centerline_measure"])
        RasBreakout1D._reject_cross_source_xs_intersections(retained_records)

        total_length = float(joined_centerline.length)
        station_origin_measure = max(
            float(record["centerline_measure"])
            for record in retained_records
            if record["node_type"] == 1
        )
        for output_index, record in enumerate(retained_records):
            record["node_index"] = output_index
            record["destination_station"] = RasBreakout1D._format_station(
                station_origin_measure - float(record["centerline_measure"])
            )
        destination_station_values = [
            RasBreakout1D._station_value(record["destination_station"])
            for record in retained_records
        ]
        if any(
            upstream <= downstream
            for upstream, downstream in zip(
                destination_station_values, destination_station_values[1:]
            )
        ):
            raise ValueError(
                "Restationing produced duplicate or non-decreasing destination "
                "node stations"
            )

        flow_path_policy, reach_lengths_finalized = (
            RasBreakout1D._apply_assembly_reach_lengths(
                retained_records,
                seam_records,
                flow_path_policy_results,
            )
        )
        station_map = RasBreakout1D._assembly_station_map(
            retained_records,
            seam_records,
            destination_river,
            destination_reach,
            source_catalog.analysis_crs,
        )
        seams_gdf = RasBreakout1D._assembly_seams_frame(
            seam_records,
            retained_records,
            source_catalog.analysis_crs,
        )
        geometry_text = RasBreakout1D._assembly_geometry_text(
            sources[0],
            retained_records,
            joined_centerline,
            destination_river,
            destination_reach,
        )
        flow_data, boundary_provenance = RasBreakout1D._assembly_flow_data(
            sources,
            retained_records,
            destination_river,
            destination_reach,
            boundary_mode=boundary_mode,
            downstream_boundary=downstream_boundary,
        )
        natural_records = [
            record for record in retained_records if record["node_type"] == 1
        ]
        direct_records = [
            record for record in natural_records if record["in_direct_domain"]
        ]
        inundation_overlap_applied = sum(
            bool(record["in_inundation_domain"])
            and not bool(record["in_direct_domain"])
            for record in natural_records
        )
        station_map.attrs.update(
            {
                "edge_id": breakout_plan.edge_id,
                "edge_length": edge_length,
                "main_channel_length": direct_main_channel_length,
                "joined_centerline_length": total_length,
                "upstream_buffer_distance": upstream_buffer,
                "downstream_buffer_distance": downstream_buffer,
                "upstream_buffer_applied": float(
                    direct_records[0]["centerline_measure"]
                )
                - float(natural_records[0]["centerline_measure"]),
                "downstream_buffer_applied": float(
                    natural_records[-1]["centerline_measure"]
                )
                - float(direct_records[-1]["centerline_measure"]),
                "inundation_overlap_xs": inundation_overlap_xs,
                "inundation_overlap_xs_applied": int(
                    inundation_overlap_applied
                ),
                "flow_path_policy": flow_path_policy,
                "reach_lengths_finalized": reach_lengths_finalized,
            }
        )
        return {
            "sources": sources,
            "geometry_text": geometry_text,
            "flow_data": flow_data,
            "station_map_gdf": station_map,
            "seams_gdf": seams_gdf,
            "boundary_provenance": boundary_provenance,
            "flow_path_policy": flow_path_policy,
            "reach_lengths_finalized": reach_lengths_finalized,
            "source_geometry_sha256": source_hashes,
        }

    @staticmethod
    def _assembly_node_records(
        source_id: str,
        reach_id: str,
        river: str,
        reach: str,
        centerline: Any,
        xs_rows: gpd.GeoDataFrame,
        lines: Sequence[str],
        nodes: Sequence[_NodeBlock],
    ) -> list[dict[str, Any]]:
        """Map text nodes to centerline measures without changing their blocks."""
        records: list[dict[str, Any]] = []
        for node_index, node in enumerate(nodes):
            xs_match = xs_rows.loc[
                xs_rows["station"].map(RasBreakout1D._station_value)
                == RasBreakout1D._station_value(node.station)
            ]
            if node.type_code == 1:
                if len(xs_match) != 1:
                    raise ValueError(
                        f"Natural cross section {source_id!r}/{node.station!r} "
                        f"resolved {len(xs_match)} catalog cut lines"
                    )
                xs = xs_match.iloc[0]
                source_measure = float(xs["_source_measure"])
                geometry = xs.geometry
                edge_measure = float(xs["_edge_measure"])
                edge_distance = float(xs["_edge_distance"])
            else:
                source_measure = float("nan")
                geometry = None
                edge_measure = float("nan")
                edge_distance = float("nan")
            left, channel, right = RasBreakout1D._parse_type_rm_lengths(
                lines[node.start]
            )
            payload = "".join(lines[node.start + 1 : node.end])
            records.append(
                {
                    "source_geometry_id": source_id,
                    "source_reach_id": reach_id,
                    "source_river": river,
                    "source_reach": reach,
                    "source_node_index": node_index,
                    "node_index": node_index,
                    "node_type": int(node.type_code),
                    "source_station": str(node.station),
                    "source_measure": source_measure,
                    "edge_measure": edge_measure,
                    "edge_distance": edge_distance,
                    "source_left_length": left,
                    "source_channel_length": channel,
                    "source_right_length": right,
                    "source_payload_sha256": hashlib.sha256(
                        payload.encode("utf-8")
                    ).hexdigest(),
                    "source_line": lines[node.start],
                    "payload_lines": list(lines[node.start + 1 : node.end]),
                    "geometry": geometry,
                }
            )

        natural_positions = [
            index for index, record in enumerate(records) if record["node_type"] == 1
        ]
        for index, record in enumerate(records):
            if record["node_type"] == 1:
                continue
            upstream_positions = [value for value in natural_positions if value < index]
            downstream_positions = [value for value in natural_positions if value > index]
            if not upstream_positions or not downstream_positions:
                raise ValueError(
                    f"Structure {source_id!r}/{record['source_station']!r} is not "
                    "bracketed by natural cross sections"
                )
            upstream = records[upstream_positions[-1]]
            downstream = records[downstream_positions[0]]
            upper_station = RasBreakout1D._station_value(
                upstream["source_station"]
            )
            lower_station = RasBreakout1D._station_value(
                downstream["source_station"]
            )
            node_station = RasBreakout1D._station_value(record["source_station"])
            if not lower_station <= node_station <= upper_station:
                raise ValueError(
                    f"Structure station {record['source_station']!r} is outside "
                    "its bracketing cross-section stations"
                )
            denominator = upper_station - lower_station
            fraction = (
                (upper_station - node_station) / denominator
                if denominator > 0
                else 0.5
            )
            source_measure = float(upstream["source_measure"]) + fraction * (
                float(downstream["source_measure"])
                - float(upstream["source_measure"])
            )
            record["source_measure"] = source_measure
            record["geometry"] = centerline.interpolate(source_measure)
        return records

    @staticmethod
    def _resolve_assembly_seams(
        sources: Sequence[_AssemblySource],
        breakout_plan: Breakout1DPlan,
        edge_geometry: Any,
    ) -> list[dict[str, Any]]:
        """Resolve each provisional footprint seam to the source centerlines."""
        from shapely.geometry import LineString
        from shapely.ops import nearest_points

        diagnostics = breakout_plan.handoff_diagnostics_df.set_index("seam_index")
        planned = breakout_plan.seams_df.set_index("seam_index")
        records: list[dict[str, Any]] = []
        for seam_index, (upstream, downstream) in enumerate(
            zip(sources, sources[1:])
        ):
            if seam_index not in diagnostics.index or seam_index not in planned.index:
                raise ValueError(f"Missing handoff evidence for seam {seam_index}")
            diagnostic = diagnostics.loc[seam_index]
            if not bool(diagnostic["handoff_eligible"]):
                raise ValueError(
                    f"Seam {seam_index} is not eligible: "
                    f"{diagnostic['reason_codes']}"
                )
            planned_point = planned.loc[seam_index].geometry
            intersection = upstream.centerline.intersection(downstream.centerline)
            if not intersection.is_empty:
                join_point = nearest_points(intersection, planned_point)[0]
                upstream_point = join_point
                downstream_point = join_point
                join_method = "centerline_intersection"
            else:
                upstream_point, downstream_point = nearest_points(
                    upstream.centerline, downstream.centerline
                )
                join_method = "nearest_connector"
            connector = LineString([upstream_point, downstream_point])
            midpoint = connector.interpolate(0.5, normalized=True)
            edge_measure = float(edge_geometry.project(midpoint))
            records.append(
                {
                    "edge_id": breakout_plan.edge_id,
                    "seam_index": seam_index,
                    "upstream_geometry_id": upstream.geometry_id,
                    "downstream_geometry_id": downstream.geometry_id,
                    "join_method": join_method,
                    "connector_length": float(connector.length),
                    "edge_measure": edge_measure,
                    "upstream_source_measure": float(
                        upstream.centerline.project(upstream_point)
                    ),
                    "downstream_source_measure": float(
                        downstream.centerline.project(downstream_point)
                    ),
                    "upstream_point": upstream_point,
                    "downstream_point": downstream_point,
                    "geometry": (
                        upstream_point if connector.length <= 1e-9 else connector
                    ),
                }
            )
        return records

    @staticmethod
    def _expand_assembly_boundary(
        natural_records: Sequence[Mapping[str, Any]],
        boundary_node_index: int,
        distance: float,
        *,
        upstream: bool,
    ) -> int:
        """Expand to the first source cross section meeting a channel distance."""
        indexes = [int(record["node_index"]) for record in natural_records]
        position = indexes.index(boundary_node_index)
        boundary_measure = float(natural_records[position]["source_measure"])
        candidates = (
            range(position - 1, -1, -1)
            if upstream
            else range(position + 1, len(natural_records))
        )
        selected = boundary_node_index
        for candidate in candidates:
            selected = int(natural_records[candidate]["node_index"])
            applied = abs(
                float(natural_records[candidate]["source_measure"])
                - boundary_measure
            )
            if applied >= distance:
                break
        return selected

    @staticmethod
    def _append_coordinates(
        target: list[tuple[float, float]], coordinates: Sequence[Any]
    ) -> None:
        """Append connected coordinates while removing only a duplicate endpoint."""
        values = [(float(item[0]), float(item[1])) for item in coordinates]
        if not values:
            return
        if target and target[-1] == values[0]:
            target.extend(values[1:])
        else:
            target.extend(values)

    @staticmethod
    def _reject_cross_source_xs_intersections(
        records: Sequence[Mapping[str, Any]],
    ) -> None:
        """Fail closed when retained cross-source GIS cut lines intersect."""
        natural = [record for record in records if record["node_type"] == 1]
        conflicts = []
        for index, first in enumerate(natural):
            for second in natural[index + 1 :]:
                if first["source_geometry_id"] == second["source_geometry_id"]:
                    continue
                if first["geometry"].intersects(second["geometry"]):
                    conflicts.append(
                        (
                            first["source_geometry_id"],
                            first["source_station"],
                            second["source_geometry_id"],
                            second["source_station"],
                        )
                    )
        if conflicts:
            raise ValueError(
                "Retained cross sections from different sources intersect: "
                f"{conflicts[:5]}"
            )

    @staticmethod
    def _apply_assembly_reach_lengths(
        records: list[dict[str, Any]],
        seam_records: list[dict[str, Any]],
        policy_results: Optional[Mapping[int, "FlowPathPolicyResult"]],
    ) -> tuple[str, bool]:
        """Set LOB/channel/ROB lengths under the audited two-policy contract."""
        preserve = "preserve_and_recompute_only_at_join_boundary"
        regenerate = "regenerate_and_recompute"
        natural = [record for record in records if record["node_type"] == 1]
        seam_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
        for seam in seam_records:
            upstream = [
                record
                for record in natural
                if record["source_geometry_id"]
                == seam["upstream_geometry_id"]
            ][-1]
            downstream = [
                record
                for record in natural
                if record["source_geometry_id"]
                == seam["downstream_geometry_id"]
            ][0]
            seam["upstream_record"] = upstream
            seam["downstream_record"] = downstream
            seam_by_pair[
                (upstream["source_geometry_id"], downstream["source_geometry_id"])
            ] = seam

        normalized_results = (
            {int(key): value for key, value in policy_results.items()}
            if policy_results is not None
            else {}
        )
        if normalized_results:
            expected_keys = {int(item["seam_index"]) for item in seam_records}
            if set(normalized_results) != expected_keys:
                raise ValueError(
                    "flow_path_policy_results keys must match seam indexes: "
                    f"expected={sorted(expected_keys)} "
                    f"actual={sorted(normalized_results)}"
                )
            policies = {
                str(getattr(value, "recommended_policy", ""))
                for value in normalized_results.values()
            }
            if len(policies) != 1 or not policies <= {preserve, regenerate}:
                raise ValueError(
                    "All flow_path_policy_results must contain the same supported "
                    f"recommendation; found {sorted(policies)}"
                )
            policy = next(iter(policies))
            finalized = True
        else:
            policy = preserve
            finalized = False

        regenerated_by_station: dict[str, tuple[float, float]] = {}
        if policy == regenerate and normalized_results:
            evidence = next(iter(normalized_results.values())).xs_metrics_df
            for row in evidence.itertuples(index=False):
                if bool(row.reach_end):
                    continue
                left = float(row.len_left_recomputed)
                right = float(row.len_right_recomputed)
                if not math.isfinite(left) or not math.isfinite(right):
                    raise ValueError(
                        f"Regenerated flow-path length is missing at station {row.RS}"
                    )
                if str(row.RS) in regenerated_by_station:
                    raise ValueError(
                        "Regenerated policy evidence contains duplicate river "
                        f"station {row.RS!r}; pass evidence for one assembled reach"
                    )
                regenerated_by_station[str(row.RS)] = (left, right)

        for index, record in enumerate(natural):
            if index == len(natural) - 1:
                record["left_length"] = 0.0
                record["channel_length"] = 0.0
                record["right_length"] = 0.0
                record["length_policy"] = "reach_end"
                continue
            downstream = natural[index + 1]
            channel = float(downstream["centerline_measure"]) - float(
                record["centerline_measure"]
            )
            if channel <= 0:
                raise ValueError("Destination cross-section measures are not ordered")
            same_source = (
                record["source_geometry_id"]
                == downstream["source_geometry_id"]
            )
            if policy == regenerate and normalized_results:
                matches = [
                    values
                    for station, values in regenerated_by_station.items()
                    if RasBreakout1D._stations_equal(
                        station, record["destination_station"]
                    )
                ]
                if len(matches) != 1:
                    raise ValueError(
                        "Regenerated policy evidence did not resolve station "
                        f"{record['destination_station']!r} exactly once"
                    )
                left, right = matches[0]
                length_policy = regenerate
            elif same_source:
                left = record["source_left_length"]
                right = record["source_right_length"]
                if left is None or right is None:
                    raise ValueError(
                        "Natural cross-section overbank lengths cannot be blank"
                    )
                length_policy = "source_overbanks_preserved"
            else:
                seam = seam_by_pair[
                    (
                        record["source_geometry_id"],
                        downstream["source_geometry_id"],
                    )
                ]
                if normalized_results:
                    evidence = normalized_results[int(seam["seam_index"])]
                    segments = evidence.join_segments_gdf
                    required_columns = {
                        "upstream_rs",
                        "downstream_rs",
                        "side",
                        "length",
                    }
                    if not required_columns <= set(segments.columns):
                        raise ValueError(
                            f"Seam {seam['seam_index']} flow-path evidence is "
                            f"missing {sorted(required_columns - set(segments.columns))}"
                        )
                    segments = segments.loc[
                        segments["upstream_rs"].map(
                            lambda value: RasBreakout1D._stations_equal(
                                value, record["destination_station"]
                            )
                        )
                        & segments["downstream_rs"].map(
                            lambda value: RasBreakout1D._stations_equal(
                                value, downstream["destination_station"]
                            )
                        )
                    ]
                    lengths = {
                        str(row.side): float(row.length)
                        for row in segments.itertuples(index=False)
                    }
                    if set(lengths) != {"left", "right"}:
                        raise ValueError(
                            f"Seam {seam['seam_index']} requires one left and one "
                            "right clipped flow-path segment"
                        )
                    left, right = lengths["left"], lengths["right"]
                    length_policy = preserve
                else:
                    left = channel
                    right = channel
                    length_policy = "provisional_join_channel_fallback"
            record["left_length"] = float(left)
            record["channel_length"] = channel
            record["right_length"] = float(right)
            record["length_policy"] = length_policy
        for record in records:
            if record["node_type"] != 1:
                record["left_length"] = None
                record["channel_length"] = None
                record["right_length"] = None
                record["length_policy"] = "not_applicable"
        return policy, finalized

    @staticmethod
    def _assembly_station_map(
        records: Sequence[Mapping[str, Any]],
        seam_records: Sequence[Mapping[str, Any]],
        destination_river: str,
        destination_reach: str,
        crs: str,
    ) -> gpd.GeoDataFrame:
        """Build the public source-to-destination node provenance table."""
        join_upstream = {
            id(item["upstream_record"]) for item in seam_records
        }
        join_downstream = {
            id(item["downstream_record"]) for item in seam_records
        }
        rows = []
        for record in records:
            rows.append(
                {
                    "node_index": int(record["node_index"]),
                    "source_geometry_id": record["source_geometry_id"],
                    "source_reach_id": record["source_reach_id"],
                    "source_river": record["source_river"],
                    "source_reach": record["source_reach"],
                    "source_node_type": int(record["node_type"]),
                    "source_station": record["source_station"],
                    "destination_river": destination_river,
                    "destination_reach": destination_reach,
                    "destination_station": record["destination_station"],
                    "centerline_measure": float(record["centerline_measure"]),
                    "left_length": record["left_length"],
                    "channel_length": record["channel_length"],
                    "right_length": record["right_length"],
                    "length_policy": record["length_policy"],
                    "in_direct_domain": bool(record["in_direct_domain"]),
                    "in_inundation_domain": bool(
                        record["in_inundation_domain"]
                    ),
                    "is_join_upstream": id(record) in join_upstream,
                    "is_join_downstream": id(record) in join_downstream,
                    "source_payload_sha256": record["source_payload_sha256"],
                    "geometry": record["geometry"],
                }
            )
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _assembly_seams_frame(
        seam_records: Sequence[Mapping[str, Any]],
        records: Sequence[Mapping[str, Any]],
        crs: str,
    ) -> gpd.GeoDataFrame:
        """Build the public resolved-seam evidence table."""
        rows = []
        for seam in seam_records:
            upstream = seam["upstream_record"]
            downstream = seam["downstream_record"]
            rows.append(
                {
                    "edge_id": seam["edge_id"],
                    "seam_index": int(seam["seam_index"]),
                    "upstream_geometry_id": seam["upstream_geometry_id"],
                    "downstream_geometry_id": seam["downstream_geometry_id"],
                    "join_method": seam["join_method"],
                    "connector_length": float(seam["connector_length"]),
                    "edge_measure": float(seam["edge_measure"]),
                    "upstream_source_measure": float(
                        seam["upstream_source_measure"]
                    ),
                    "downstream_source_measure": float(
                        seam["downstream_source_measure"]
                    ),
                    "upstream_source_station": upstream["source_station"],
                    "downstream_source_station": downstream["source_station"],
                    "upstream_destination_station": upstream[
                        "destination_station"
                    ],
                    "downstream_destination_station": downstream[
                        "destination_station"
                    ],
                    "join_left_length": float(upstream["left_length"]),
                    "join_channel_length": float(upstream["channel_length"]),
                    "join_right_length": float(upstream["right_length"]),
                    "length_policy": upstream["length_policy"],
                    "geometry": seam["geometry"],
                }
            )
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)

    @staticmethod
    def _assembly_geometry_text(
        template_source: _AssemblySource,
        records: Sequence[Mapping[str, Any]],
        joined_centerline: Any,
        destination_river: str,
        destination_reach: str,
    ) -> str:
        """Write a single reach while preserving every retained node payload."""
        domain_start = RasBreakout1D._first_geometry_domain_line(
            template_source.lines
        )
        first_node = template_source.nodes[0].start
        reach_header = list(
            template_source.lines[template_source.reach_start:first_node]
        )
        reach_header = RasBreakout1D._replace_reach_header(
            reach_header,
            joined_centerline,
            destination_river,
            destination_reach,
        )
        output = list(template_source.lines[:domain_start]) + reach_header
        for record in records:
            if record["node_type"] == 1:
                line = RasBreakout1D._rewrite_type_rm(
                    record["source_line"],
                    record["node_type"],
                    record["destination_station"],
                    record["left_length"],
                    record["channel_length"],
                    record["right_length"],
                )
            else:
                line = RasBreakout1D._rewrite_type_rm(
                    record["source_line"],
                    record["node_type"],
                    record["destination_station"],
                    None,
                    None,
                    None,
                    preserve_lengths=True,
                )
            output.append(line)
            output.extend(record["payload_lines"])
        if output and not output[-1].endswith(("\n", "\r")):
            output[-1] += "\n"
        return "".join(output)

    @staticmethod
    def _replace_reach_header(
        reach_header: Sequence[str],
        centerline: Any,
        river: str,
        reach: str,
    ) -> list[str]:
        """Replace the reach identity and ``Reach XY`` coordinate block."""
        header = list(reach_header)
        header[0] = f"River Reach={river},{reach}\n"
        reach_xy_index = next(
            (
                index
                for index, line in enumerate(header)
                if line.lstrip().startswith("Reach XY=")
            ),
            None,
        )
        coordinates = list(centerline.coords)
        values = [value for coordinate in coordinates for value in coordinate[:2]]
        coordinate_lines = [
            "".join(
                RasBreakout1D._format_coordinate(value)
                for value in values[index : index + 4]
            )
            + "\n"
            for index in range(0, len(values), 4)
        ]
        replacement = [f"Reach XY= {len(coordinates)}\n"] + coordinate_lines
        if reach_xy_index is None:
            return header[:1] + replacement + header[1:]
        count_match = _NUMBER_RE.search(header[reach_xy_index].split("=", 1)[-1])
        if count_match is None:
            raise ValueError("Malformed Reach XY count in source reach header")
        old_count = int(float(count_match.group(0)))
        old_end = reach_xy_index + 1 + math.ceil(old_count / 2)
        return header[:reach_xy_index] + replacement + header[old_end:]

    @staticmethod
    def _assembly_flow_data(
        sources: Sequence[_AssemblySource],
        records: Sequence[Mapping[str, Any]],
        destination_river: str,
        destination_reach: str,
        *,
        boundary_mode: str,
        downstream_boundary: Optional[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], str]:
        """Merge compatible steady flows and rewrite every location key."""
        from .RasSteady import RasSteady

        source_data = [
            RasSteady.read_flow_file(source.plan["flow_path"])
            for source in sources
        ]
        profiles = tuple(source_data[0]["profile_names"])
        changes: list[dict[str, Any]] = []
        for source, data in zip(sources, source_data):
            source_records = [
                record
                for record in records
                if record["source_geometry_id"] == source.geometry_id
                and record["node_type"] == 1
            ]
            upper = RasBreakout1D._station_value(
                source_records[0]["source_station"]
            )
            lower = RasBreakout1D._station_value(
                source_records[-1]["source_station"]
            )
            source_changes = sorted(
                [
                    item
                    for item in data["flow_changes"]
                    if item["river"] == source.river
                    and item["reach"] == source.reach
                ],
                key=lambda item: RasBreakout1D._station_value(item["station"]),
                reverse=True,
            )
            if not source_changes:
                raise ValueError(
                    f"Source {source.geometry_id!r} has no flow changes on its "
                    "selected reach"
                )
            upstream_candidates = [
                item
                for item in source_changes
                if RasBreakout1D._station_value(item["station"]) >= upper
            ]
            active = upstream_candidates[-1] if upstream_candidates else source_changes[0]
            selected_changes = [
                dict(item)
                for item in source_changes
                if lower
                <= RasBreakout1D._station_value(item["station"])
                <= upper
            ]
            if not any(
                RasBreakout1D._stations_equal(item["station"], upper)
                for item in selected_changes
            ):
                propagated = dict(active)
                propagated["station"] = str(source_records[0]["source_station"])
                propagated["river_station"] = propagated["station"]
                selected_changes.append(propagated)
            for item in selected_changes:
                destination_station = RasBreakout1D._map_assembly_station(
                    item["station"], source_records
                )
                changes.append(
                    {
                        **item,
                        "river": destination_river,
                        "reach": destination_reach,
                        "station": destination_station,
                        "river_station": destination_station,
                    }
                )

        changes.sort(
            key=lambda item: RasBreakout1D._station_value(item["station"]),
            reverse=True,
        )
        deduplicated = []
        for change in changes:
            if deduplicated and RasBreakout1D._stations_equal(
                deduplicated[-1]["station"], change["station"]
            ):
                if list(deduplicated[-1]["flows"]) != list(change["flows"]):
                    raise ValueError(
                        "Different source flows resolve to the same destination "
                        f"station {change['station']!r}"
                    )
                continue
            deduplicated.append(change)

        last_source = sources[-1]
        last_records = [
            record
            for record in records
            if record["source_geometry_id"] == last_source.geometry_id
            and record["node_type"] == 1
        ]
        last_selection = Breakout1DSelection(
            river=last_source.river,
            reach=last_source.reach,
            stations=tuple(record["source_station"] for record in last_records),
            upstream_station=str(last_records[0]["source_station"]),
            downstream_station=str(last_records[-1]["source_station"]),
            selector="network_edge_assembly",
        )
        boundary_data, boundary_provenance = RasBreakout1D._extract_flow_data(
            last_source.plan["flow_path"],
            last_selection,
            source_geometry=Path(last_source.plan["geometry_path"]),
            source_plan_hdf=RasBreakout1D._expected_plan_hdf(
                Path(last_source.plan["plan_path"])
            ),
            boundary_mode=boundary_mode,
            downstream_boundary=downstream_boundary,
        )
        first_source = sources[0]
        first_boundaries = [
            item
            for item in source_data[0].get("boundaries", [])
            if item["river"] == first_source.river
            and item["reach"] == first_source.reach
        ]
        first_boundaries = RasSteady._expand_boundaries(
            first_boundaries, len(profiles)
        )
        last_boundaries = RasSteady._expand_boundaries(
            boundary_data["boundaries"], len(profiles)
        )
        boundaries = []
        for profile_number in range(1, len(profiles) + 1):
            first = next(
                (
                    item
                    for item in first_boundaries
                    if int(item.get("profile", 0)) == profile_number
                ),
                {},
            )
            last = next(
                (
                    item
                    for item in last_boundaries
                    if int(item.get("profile", 0)) == profile_number
                ),
                {},
            )
            boundaries.append(
                RasSteady.boundary(
                    destination_river,
                    destination_reach,
                    profile=profile_number,
                    upstream=first.get(
                        "upstream", {"type": RasSteady.NO_BOUNDARY}
                    ),
                    downstream=last.get(
                        "downstream", {"type": RasSteady.NO_BOUNDARY}
                    ),
                )
            )
        return (
            {
                "flow_title": f"Assembled - {source_data[0].get('flow_title', '')}",
                "program_version": source_data[0].get("program_version", ""),
                "profile_names": list(profiles),
                "number_of_profiles": len(profiles),
                "flow_changes": deduplicated,
                "boundaries": boundaries,
                "dss_import": source_data[0].get("dss_import"),
            },
            boundary_provenance,
        )

    @staticmethod
    def _map_assembly_station(
        source_station: Any,
        source_records: Sequence[Mapping[str, Any]],
    ) -> str:
        """Map an arbitrary source station through bracketing retained XSs."""
        value = RasBreakout1D._station_value(source_station)
        exact = [
            record
            for record in source_records
            if RasBreakout1D._stations_equal(record["source_station"], value)
        ]
        if len(exact) == 1:
            return str(exact[0]["destination_station"])
        for upstream, downstream in zip(source_records, source_records[1:]):
            upper = RasBreakout1D._station_value(upstream["source_station"])
            lower = RasBreakout1D._station_value(downstream["source_station"])
            if lower <= value <= upper:
                fraction = (upper - value) / (upper - lower)
                upstream_destination = RasBreakout1D._station_value(
                    upstream["destination_station"]
                )
                downstream_destination = RasBreakout1D._station_value(
                    downstream["destination_station"]
                )
                mapped = upstream_destination + fraction * (
                    downstream_destination - upstream_destination
                )
                return RasBreakout1D._format_station(mapped)
        raise ValueError(
            f"Flow-change station {source_station!r} is outside retained source XSs"
        )

    @staticmethod
    def _validate_multi_source_assembly(
        destination_ras: RasPrj,
        *,
        station_map_gdf: gpd.GeoDataFrame,
        seams_gdf: gpd.GeoDataFrame,
        source_geometry_sha256: Mapping[str, str],
        source_paths: Mapping[str, Path],
        profile_names: tuple[str, ...],
        reach_lengths_finalized: bool,
    ) -> Breakout1DValidationReport:
        """Validate the written reach, provenance, lengths, flow, and sources."""
        destination = RasBreakout1D._resolve_source_plan(destination_ras, "01")
        natural_map = station_map_gdf.loc[
            station_map_gdf["source_node_type"] == 1
        ].reset_index(drop=True)
        destination_xs = RasBreakout1D._all_natural_cross_sections(
            destination["geometry_path"]
        ).reset_index(drop=True)
        from .RasSteady import RasSteady

        flow_data = RasSteady.read_flow_file(destination["flow_path"])
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

        add(
            "retained_cross_sections",
            len(destination_xs) == len(natural_map),
            f"expected={len(natural_map)} actual={len(destination_xs)}",
        )
        actual_stations = tuple(destination_xs["RS"].astype(str))
        expected_stations = tuple(natural_map["destination_station"].astype(str))
        add(
            "restationed_cross_sections",
            actual_stations == expected_stations,
            f"expected={expected_stations} actual={actual_stations}",
        )
        destination_river = str(natural_map.iloc[0]["destination_river"])
        destination_reach = str(natural_map.iloc[0]["destination_reach"])
        geometry_lines, _, destination_nodes = RasBreakout1D._target_reach_parts(
            destination["geometry_path"], destination_river, destination_reach
        )
        expected_nodes = station_map_gdf.reset_index(drop=True)
        node_identity_matches = len(destination_nodes) == len(expected_nodes)
        payload_matches = node_identity_matches
        if node_identity_matches:
            for index, node in enumerate(destination_nodes):
                expected = expected_nodes.iloc[index]
                node_identity_matches &= (
                    int(node.type_code) == int(expected["source_node_type"])
                    and RasBreakout1D._stations_equal(
                        node.station, expected["destination_station"]
                    )
                )
                payload = "".join(geometry_lines[node.start + 1 : node.end])
                payload_matches &= (
                    hashlib.sha256(payload.encode("utf-8")).hexdigest()
                    == expected["source_payload_sha256"]
                )
        add(
            "restationed_nodes",
            node_identity_matches,
            "all cross sections and structures retain order with new stations",
        )
        add(
            "node_payload_content",
            payload_matches,
            "every retained node payload matches its source SHA-256",
        )
        station_values = [
            RasBreakout1D._station_value(value) for value in expected_stations
        ]
        add(
            "station_order",
            all(
                upstream > downstream
                for upstream, downstream in zip(
                    station_values, station_values[1:]
                )
            ),
            "destination river stations strictly decrease downstream",
        )
        destination_reaches = destination_xs[["River", "Reach"]].drop_duplicates()
        add(
            "single_reach",
            len(destination_reaches) == 1,
            f"destination reaches={destination_reaches.to_dict('records')}",
        )
        length_matches = len(destination_xs) == len(natural_map)
        if length_matches:
            for index, row in destination_xs.iterrows():
                expected = natural_map.iloc[index]
                length_matches &= all(
                    math.isclose(
                        float(row[column]),
                        float(expected[expected_column]),
                        rel_tol=0.0,
                        abs_tol=0.01,
                    )
                    for column, expected_column in (
                        ("Length_Left", "left_length"),
                        ("Length_Channel", "channel_length"),
                        ("Length_Right", "right_length"),
                    )
                )
        add(
            "reach_lengths",
            length_matches,
            "destination LOB/channel/ROB lengths match the assembly map",
        )
        flow_reaches = {
            (item["river"], item["reach"])
            for item in flow_data["flow_changes"]
        }
        destination_pair = (destination_river, destination_reach)
        add(
            "steady_flow_reach",
            flow_reaches == {destination_pair},
            f"flow-change reaches={sorted(flow_reaches)}",
        )
        add(
            "steady_profiles",
            tuple(flow_data["profile_names"]) == profile_names,
            f"expected={profile_names} actual={tuple(flow_data['profile_names'])}",
        )
        boundary_reaches = {
            (item["river"], item["reach"])
            for item in flow_data.get("boundaries", [])
        }
        add(
            "steady_boundaries",
            boundary_reaches == {destination_pair},
            f"boundary reaches={sorted(boundary_reaches)}",
        )
        immutable = all(
            RasBreakout1D._sha256(Path(source_paths[source_id])) == digest
            for source_id, digest in source_geometry_sha256.items()
        )
        add(
            "source_geometry_immutable",
            immutable,
            "all source geometry hashes are unchanged",
        )
        add(
            "resolved_seams",
            bool(
                not seams_gdf.empty
                and seams_gdf["join_method"].isin(
                    ["centerline_intersection", "nearest_connector"]
                ).all()
            ),
            f"resolved seam count={len(seams_gdf)}",
        )
        add(
            "flow_path_lengths_finalized",
            reach_lengths_finalized,
            (
                "flow-path policy evidence applied"
                if reach_lengths_finalized
                else "provisional join LOB/ROB lengths require a flow-path audit"
            ),
            severity="INFO" if reach_lengths_finalized else "WARNING",
        )
        return Breakout1DValidationReport(
            pd.DataFrame(
                checks,
                columns=["check", "severity", "passed", "detail"],
            )
        )

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
        for precision in range(8, -1, -1):
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
    def _parse_type_rm_lengths(
        line: str,
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Return the optional LOB/channel/ROB fields from a node header."""
        if "=" not in line:
            raise ValueError(f"Malformed Type RM line: {line!r}")
        values = [value.strip() for value in line.split("=", 1)[1].split(",")]
        while len(values) < 5:
            values.append("")

        def number(value: str) -> Optional[float]:
            return float(value) if value else None

        return number(values[2]), number(values[3]), number(values[4])

    @staticmethod
    def _rewrite_type_rm(
        line: str,
        type_code: int,
        station: str,
        left: Optional[float],
        channel: Optional[float],
        right: Optional[float],
        *,
        preserve_lengths: bool = False,
    ) -> str:
        """Rewrite a node identifier and, for XSs, its reach-length triplet."""
        newline = (
            "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        )
        body = line[: -len(newline)] if newline else line
        left_text, values_text = body.split("=", 1)
        values = [value.strip() for value in values_text.split(",")]
        while len(values) < 5:
            values.append("")
        values[0] = f" {int(type_code)} "
        values[1] = str(station)
        if not preserve_lengths:
            values[2] = RasBreakout1D._format_length(left)
            values[3] = RasBreakout1D._format_length(channel)
            values[4] = RasBreakout1D._format_length(right)
        return f"{left_text}={','.join(values)}{newline}"

    @staticmethod
    def _format_length(value: Optional[float]) -> str:
        if value is None:
            return ""
        if not math.isfinite(float(value)) or float(value) < 0:
            raise ValueError(f"Reach length must be finite and non-negative: {value}")
        return f"{float(value):.3f}".rstrip("0").rstrip(".")

    @staticmethod
    def _format_station(value: float) -> str:
        if not math.isfinite(float(value)) or float(value) < -1e-6:
            raise ValueError(f"River station must be finite and non-negative: {value}")
        normalized = 0.0 if abs(float(value)) <= 5e-7 else float(value)
        return f"{normalized:.3f}".rstrip("0").rstrip(".")

    @staticmethod
    def _assembly_reach_name(value: Any, name: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError(f"{name} must not be blank")
        if "," in text:
            raise ValueError(f"{name} must not contain a comma")
        if len(text) > 16:
            raise ValueError(f"{name} must not exceed 16 characters")
        return text

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
    def _handoff_diagnostics(
        source_catalog: Breakout1DSourceCatalog,
        reach_assignments: gpd.GeoDataFrame,
        coverage_plan: NetworkEdgeCoveragePlanResult,
        *,
        max_cross_centerline_xs: int,
    ) -> gpd.GeoDataFrame:
        """Evaluate whether consecutive source reaches form a clean handoff."""
        columns = [
            "edge_id",
            "seam_index",
            "upstream_geometry_id",
            "downstream_geometry_id",
            "upstream_reach_id",
            "downstream_reach_id",
            "centerline_distance",
            "centerline_intersects",
            "upstream_xs_intersect_both_count",
            "downstream_xs_intersect_both_count",
            "upstream_xs_intersect_both_ids",
            "downstream_xs_intersect_both_ids",
            "cross_centerline_xs_count",
            "cross_centerline_xs_ids",
            "max_cross_centerline_xs",
            "handoff_eligible",
            "reason_codes",
            "geometry",
        ]
        confirmed = reach_assignments.loc[
            reach_assignments["status"] == "confirmed"
        ]
        assignment_by_source = {
            str(row.geometry_id): row for row in confirmed.itertuples(index=False)
        }
        rows: list[dict[str, Any]] = []
        for seam in coverage_plan.seams_df.itertuples(index=False):
            upstream_id = str(seam.upstream_geometry_id)
            downstream_id = str(seam.downstream_geometry_id)
            if upstream_id == downstream_id:
                continue
            upstream = assignment_by_source.get(upstream_id)
            downstream = assignment_by_source.get(downstream_id)
            reason_codes: list[str] = []
            if upstream is None or downstream is None:
                reason_codes.append("MISSING_CONFIRMED_REACH")
                rows.append(
                    {
                        "edge_id": str(seam.edge_id),
                        "seam_index": int(seam.seam_index),
                        "upstream_geometry_id": upstream_id,
                        "downstream_geometry_id": downstream_id,
                        "upstream_reach_id": getattr(upstream, "reach_id", None),
                        "downstream_reach_id": getattr(downstream, "reach_id", None),
                        "centerline_distance": None,
                        "centerline_intersects": False,
                        "upstream_xs_intersect_both_count": 0,
                        "downstream_xs_intersect_both_count": 0,
                        "upstream_xs_intersect_both_ids": (),
                        "downstream_xs_intersect_both_ids": (),
                        "cross_centerline_xs_count": 0,
                        "cross_centerline_xs_ids": (),
                        "max_cross_centerline_xs": max_cross_centerline_xs,
                        "handoff_eligible": False,
                        "reason_codes": tuple(reason_codes),
                        "geometry": seam.geometry,
                    }
                )
                continue

            upstream_line = upstream.geometry
            downstream_line = downstream.geometry
            upstream_xs = source_catalog.cross_sections_gdf.loc[
                source_catalog.cross_sections_gdf["reach_id"]
                == upstream.reach_id
            ]
            downstream_xs = source_catalog.cross_sections_gdf.loc[
                source_catalog.cross_sections_gdf["reach_id"]
                == downstream.reach_id
            ]
            upstream_cross_both_mask = (
                upstream_xs.intersects(upstream_line)
                & upstream_xs.intersects(downstream_line)
            )
            downstream_cross_both_mask = (
                downstream_xs.intersects(downstream_line)
                & downstream_xs.intersects(upstream_line)
            )
            upstream_cross_both_ids = tuple(
                upstream_xs.loc[upstream_cross_both_mask, "xs_id"].astype(str)
            )
            downstream_cross_both_ids = tuple(
                downstream_xs.loc[downstream_cross_both_mask, "xs_id"].astype(str)
            )
            upstream_cross_both = len(upstream_cross_both_ids)
            downstream_cross_both = len(downstream_cross_both_ids)
            cross_centerline_xs_ids = (
                upstream_cross_both_ids + downstream_cross_both_ids
            )
            cross_centerline_xs_count = (
                upstream_cross_both + downstream_cross_both
            )
            if cross_centerline_xs_count > max_cross_centerline_xs:
                reason_codes.append("MULTIPLE_XS_INTERSECT_BOTH_CENTERLINES")
            rows.append(
                {
                    "edge_id": str(seam.edge_id),
                    "seam_index": int(seam.seam_index),
                    "upstream_geometry_id": upstream_id,
                    "downstream_geometry_id": downstream_id,
                    "upstream_reach_id": str(upstream.reach_id),
                    "downstream_reach_id": str(downstream.reach_id),
                    "centerline_distance": float(
                        upstream_line.distance(downstream_line)
                    ),
                    "centerline_intersects": bool(
                        upstream_line.intersects(downstream_line)
                    ),
                    "upstream_xs_intersect_both_count": upstream_cross_both,
                    "downstream_xs_intersect_both_count": downstream_cross_both,
                    "upstream_xs_intersect_both_ids": upstream_cross_both_ids,
                    "downstream_xs_intersect_both_ids": downstream_cross_both_ids,
                    "cross_centerline_xs_count": cross_centerline_xs_count,
                    "cross_centerline_xs_ids": cross_centerline_xs_ids,
                    "max_cross_centerline_xs": max_cross_centerline_xs,
                    "handoff_eligible": not reason_codes,
                    "reason_codes": tuple(reason_codes),
                    "geometry": seam.geometry,
                }
            )
        crs = coverage_plan.seams_df.crs or source_catalog.centerlines_gdf.crs
        return gpd.GeoDataFrame(
            rows,
            columns=columns,
            geometry="geometry",
            crs=crs,
        )

    @staticmethod
    def _catalog_reach_id(source_id: str, river: Any, reach: Any) -> str:
        """Return a globally unique reach identifier for a source catalog."""
        return f"{source_id}::{str(river).strip()}::{str(reach).strip()}"

    @staticmethod
    def _measure_sequence(
        measures: Sequence[float], *, tolerance: float
    ) -> str:
        """Classify XS measures ordered by decreasing HEC-RAS station."""
        if len(measures) < 2:
            return "insufficient"
        deltas = [right - left for left, right in zip(measures, measures[1:])]
        if all(delta >= -tolerance for delta in deltas):
            return "with_edge"
        if all(delta <= tolerance for delta in deltas):
            return "against_edge"
        return "nonmonotonic"

    @staticmethod
    def _catalog_footprint(
        geom_file: Path,
        centerlines: gpd.GeoDataFrame,
        cross_sections: gpd.GeoDataFrame,
        *,
        source_crs: CRS,
        target_crs: CRS,
    ) -> tuple[Any, str]:
        """Prefer an HDF footprint, with a legacy text-geometry fallback."""
        geom_hdf = Path(f"{geom_file}.hdf")
        if geom_hdf.is_file():
            try:
                from .hdf import HdfProject

                footprint, _ = HdfProject.get_project_extent(
                    geom_hdf,
                    include_1d=True,
                    include_2d=False,
                    include_storage=False,
                    buffer_percent=0.0,
                    geometry_type="footprint",
                )
                if footprint is not None and not footprint.empty:
                    if footprint.crs is None:
                        footprint = footprint.set_crs(
                            source_crs, allow_override=True
                        )
                    footprint = footprint.to_crs(target_crs)
                    return unary_union(footprint.geometry.tolist()), "geometry_hdf"
            except Exception as exc:
                logger.debug(
                    "Could not derive source-catalog footprint from %s: %s",
                    geom_hdf,
                    exc,
                )
        geometry = unary_union(
            centerlines.geometry.tolist() + cross_sections.geometry.tolist()
        ).convex_hull
        return geometry, "geometry_text_convex_hull"

    @staticmethod
    def _project_units_system(project_file: Union[str, Path]) -> Optional[str]:
        """Return the HEC-RAS project units declaration when present."""
        for line in Path(project_file).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            normalized = line.strip().lower()
            if normalized == "english units":
                return "English"
            if normalized in {"si units", "metric units"}:
                return "SI"
        return None

    @staticmethod
    def _keyword_value(
        path: Union[str, Path], keyword: str
    ) -> Optional[str]:
        """Read the first exact ``keyword=value`` entry from a RAS text file."""
        prefix = f"{keyword}="
        for line in Path(path).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines():
            if line.startswith(prefix):
                value = line.split("=", 1)[1].strip()
                return value or None
        return None

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
    "Breakout1DAssemblyResult",
    "Breakout1DPlan",
    "Breakout1DSourceCatalog",
    "Breakout1DDomainSelection",
    "Breakout1DResult",
    "Breakout1DSelection",
    "Breakout1DValidationReport",
]
