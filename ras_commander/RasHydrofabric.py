"""Hydrofabric conflation for HEC-RAS model geometry.

The conflation surface in this module deliberately separates candidate evidence
from accepted matches.  A failed or uncertain match therefore has a null
``feature_id`` and an explicit status; numeric hydrofabric identifiers are never
overloaded with sentinel error values.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import atan2, cos, degrees, exp, hypot, log, radians
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, Union

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, unary_union

from .Decorators import log_call
from .LoggingConfig import get_logger

logger = get_logger(__name__)

GeoInput = Union[gpd.GeoDataFrame, str, Path]


class ConflationStatus(str, Enum):
    """Resolution state for a model element."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class HydrofabricConflationResult:
    """Long-form model-to-hydrofabric conflation output.

    Attributes:
        matches: One resolved row per geometry, reach, and cross section.
            ``feature_id`` is populated only when ``status == 'matched'``.
        candidates: Ranked candidate rows, including every score component and
            the candidate flowpath geometry.
        huc_intersections: Geometry-footprint/HUC intersections.  Empty when no
            HUC layer was supplied.
        adapter: Name of the hydrofabric schema adapter used for normalization.
        analysis_crs: CRS in which distances, lengths, and areas were measured.
        parameters: Thresholds and weights used for the run.
    """

    matches: gpd.GeoDataFrame
    candidates: gpd.GeoDataFrame
    huc_intersections: gpd.GeoDataFrame
    adapter: str
    analysis_crs: str
    parameters: Mapping[str, Any]

    @property
    def summary(self) -> Dict[str, int]:
        """Return match-status counts without discarding element granularity."""
        counts = self.matches["status"].value_counts().to_dict()
        result = {
            status.value: int(counts.get(status.value, 0))
            for status in ConflationStatus
        }
        result["total"] = int(len(self.matches))
        return result


@dataclass(frozen=True)
class HydrofabricAdapter:
    """Column aliases used to normalize a flowpath product.

    Custom products can use this class directly.  The three built-in subclasses
    cover NHDPlus, the current NWM hydrofabric, and NextGen-style flowpaths.
    Identifiers are normalized to strings so they cannot collide with numeric
    failure sentinels used by older workflows.
    """

    name: str
    feature_id_fields: Tuple[str, ...]
    to_feature_id_fields: Tuple[str, ...] = ()
    from_node_fields: Tuple[str, ...] = ()
    to_node_fields: Tuple[str, ...] = ()
    stream_order_fields: Tuple[str, ...] = ()
    drainage_area_fields: Tuple[str, ...] = ()
    hydrosequence_fields: Tuple[str, ...] = ()

    def normalize(self, flowpaths: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Return a copy with stable hydrofabric columns."""
        if not isinstance(flowpaths, gpd.GeoDataFrame):
            raise TypeError("flowpaths must be a GeoDataFrame before normalization")
        if flowpaths.crs is None:
            raise ValueError("flowpaths must have a CRS")

        frame = flowpaths.copy()
        id_col = _find_column(frame, None, self.feature_id_fields)
        if id_col is None:
            raise ValueError(
                f"{self.name} adapter could not find a feature identifier; "
                f"expected one of {self.feature_id_fields}"
            )

        frame["feature_id"] = frame[id_col].map(_normalise_identifier)
        if frame["feature_id"].isna().any():
            bad = int(frame["feature_id"].isna().sum())
            raise ValueError(f"flowpaths contain {bad} null/blank feature identifiers")

        canonical = {
            "to_feature_id": self.to_feature_id_fields,
            "from_node": self.from_node_fields,
            "to_node": self.to_node_fields,
            "stream_order": self.stream_order_fields,
            "drainage_area": self.drainage_area_fields,
            "hydrosequence": self.hydrosequence_fields,
        }
        for output_name, aliases in canonical.items():
            source = _find_column(frame, None, aliases)
            if source is None:
                frame[output_name] = pd.NA
            elif output_name in {"to_feature_id", "from_node", "to_node"}:
                frame[output_name] = frame[source].map(_normalise_identifier)
            else:
                frame[output_name] = pd.to_numeric(frame[source], errors="coerce")

        frame["adapter"] = self.name
        frame["source_index"] = frame.index.map(str)
        if frame["feature_id"].duplicated().any():
            logger.debug(
                "Dissolving duplicate %s flowpath feature identifiers",
                self.name,
            )
            frame = frame.dissolve(
                by="feature_id", as_index=False, aggfunc="first"
            )
        return frame


class NHDPlusAdapter(HydrofabricAdapter):
    """Adapter for NHDPlus V2 and NHDPlus HR flowlines."""

    def __init__(self) -> None:
        super().__init__(
            name="nhdplus",
            feature_id_fields=(
                "COMID", "comid", "NHDPlusID", "nhdplusid", "featureid",
                "feature_id",
            ),
            to_feature_id_fields=("ToCOMID", "tocomid", "to_feature_id"),
            from_node_fields=("FromNode", "fromnode", "from_node"),
            to_node_fields=("ToNode", "tonode", "to_node"),
            stream_order_fields=(
                "StreamOrde", "streamorde", "StreamOrder", "stream_order",
                "order",
            ),
            drainage_area_fields=(
                "TotDASqKm", "totdasqkm", "TotDASqKM", "areasqkm",
                "drainage_area", "AreaSqKm",
            ),
            hydrosequence_fields=("Hydroseq", "hydroseq", "hydrosequence"),
        )


class NWMHydrofabricAdapter(HydrofabricAdapter):
    """Adapter for the current NOAA/NWM hydrofabric flowpaths layer."""

    def __init__(self) -> None:
        super().__init__(
            name="nwm",
            feature_id_fields=("id", "feature_id", "hf_id", "comid"),
            to_feature_id_fields=(
                "to_feature_id", "toid", "to_id", "downstream_id",
            ),
            from_node_fields=("fromid", "from_id", "from_node", "nexus_from"),
            to_node_fields=("toid", "to_id", "to_node", "nexus_to"),
            stream_order_fields=("order", "stream_order", "streamorde"),
            drainage_area_fields=(
                "areasqkm", "area_sqkm", "totdasqkm", "drainage_area",
            ),
            hydrosequence_fields=("hydroseq", "hydrosequence", "hf_hydroseq"),
        )


class NextGenFlowpathAdapter(HydrofabricAdapter):
    """Adapter for NextGen-style flowpaths and nexus-linked networks."""

    def __init__(self) -> None:
        super().__init__(
            name="nextgen",
            feature_id_fields=(
                "feature_id", "id", "flowpath_id", "realized_flowpath",
            ),
            to_feature_id_fields=(
                "to_feature_id", "downstream_id", "toid", "to_id",
            ),
            from_node_fields=(
                "fromid", "from_id", "from_node", "nexus_from", "from_nexus",
            ),
            to_node_fields=(
                "toid", "to_id", "to_node", "nexus_to", "to_nexus",
            ),
            stream_order_fields=("order", "stream_order", "streamorde"),
            drainage_area_fields=(
                "areasqkm", "area_sqkm", "drainage_area", "totdasqkm",
            ),
            hydrosequence_fields=("hydroseq", "hydrosequence", "sequence"),
        )


DEFAULT_CONFLATION_WEIGHTS: Mapping[str, float] = {
    "footprint_overlap": 0.15,
    "centerline_distance": 0.20,
    "direction_agreement": 0.12,
    "xs_intersections": 0.18,
    "topological_continuity": 0.15,
    "stream_order_drainage_area": 0.10,
    "sequence_consistency": 0.10,
}

_MATCH_COLUMNS = [
    "element_type", "geometry_id", "reach_id", "xs_id", "feature_id",
    "best_candidate_feature_id", "status", "confidence_score", "score_margin",
    "candidate_count", "match_method", "reason_codes", "adapter",
    "flowpath_measure", "flowpath_measure_fraction",
    "flowpath_measure_from_end", "measure_method", "offset_distance", "geometry",
]

_CANDIDATE_COLUMNS = [
    "element_type", "geometry_id", "reach_id", "xs_id", "feature_id",
    "candidate_rank", "confidence_score", "reason_codes", "adapter",
    "footprint_overlap_score", "footprint_overlap_ratio",
    "centerline_distance_score", "centerline_mean_distance",
    "direction_agreement_score", "angular_difference_deg",
    "xs_intersection_score", "xs_intersection_count", "xs_total_count",
    "topological_continuity_score", "hydrologic_score", "stream_order",
    "drainage_area", "sequence_consistency_score", "to_feature_id",
    "hydrosequence", "flowpath_measure", "flowpath_measure_fraction",
    "flowpath_measure_from_end", "measure_method", "offset_distance", "geometry",
]


class RasHydrofabric:
    """Conflate HEC-RAS geometry with national hydrofabric flowpaths.

    This is a static namespace; do not instantiate it.
    """

    DEFAULT_WEIGHTS = DEFAULT_CONFLATION_WEIGHTS

    @staticmethod
    def get_adapter(
        adapter: Union[str, HydrofabricAdapter],
        flowpaths: Optional[gpd.GeoDataFrame] = None,
    ) -> HydrofabricAdapter:
        """Resolve a built-in, custom, or auto-detected adapter."""
        if isinstance(adapter, HydrofabricAdapter):
            return adapter
        key = str(adapter).strip().lower().replace("-", "_")
        if key in {"nhd", "nhdplus", "nhdplus_v2", "nhdplus_hr"}:
            return NHDPlusAdapter()
        if key in {"nwm", "nwm_hydrofabric", "hydrofabric"}:
            return NWMHydrofabricAdapter()
        if key in {"nextgen", "nextgen_flowpaths", "ngen"}:
            return NextGenFlowpathAdapter()
        if key != "auto":
            raise ValueError(
                "adapter must be 'auto', 'nhdplus', 'nwm', 'nextgen', or a "
                "HydrofabricAdapter instance"
            )
        if flowpaths is None:
            raise ValueError("flowpaths are required for adapter='auto'")
        names = {str(column).lower() for column in flowpaths.columns}
        if names.intersection({"comid", "nhdplusid", "streamorde"}):
            return NHDPlusAdapter()
        if names.intersection(
            {"divide_id", "nexus_id", "realized_flowpath", "flowpath_id"}
        ):
            return NextGenFlowpathAdapter()
        if names.intersection({"id", "feature_id", "hf_id"}):
            return NWMHydrofabricAdapter()
        raise ValueError(
            "Could not auto-detect the hydrofabric schema; pass an explicit "
            "adapter or HydrofabricAdapter"
        )

    @staticmethod
    @log_call
    def conflate(
        model_footprints: GeoInput,
        centerlines: GeoInput,
        cross_sections: Optional[GeoInput],
        flowpaths: GeoInput,
        *,
        adapter: Union[str, HydrofabricAdapter] = "auto",
        hucs: Optional[GeoInput] = None,
        analysis_crs: Optional[Any] = None,
        geometry_id_col: Optional[str] = "geometry_id",
        centerline_geometry_id_col: Optional[str] = "geometry_id",
        reach_id_col: Optional[str] = "reach_id",
        xs_id_col: Optional[str] = "xs_id",
        xs_reach_id_col: Optional[str] = "reach_id",
        huc_id_col: Optional[str] = None,
        flowpaths_layer: Optional[str] = None,
        hucs_layer: Optional[str] = None,
        search_distance: Optional[float] = None,
        topology_tolerance: Optional[float] = None,
        max_candidates: int = 8,
        min_confidence: float = 0.55,
        ambiguity_margin: float = 0.05,
        weights: Optional[Mapping[str, float]] = None,
        sample_count: int = 9,
    ) -> HydrofabricConflationResult:
        """Conflate model footprints, reaches, and cross sections to flowpaths.

        Candidate flowpaths are scored using model-footprint overlap, symmetric
        centerline distance, directed angular agreement, cross-section
        intersections, topological continuity, stream order/drainage area, and
        reach-to-flowpath sequence consistency.  Missing evidence is excluded
        and the remaining weights are renormalized.

        Args:
            model_footprints: Polygon GeoDataFrame (or vector path), normally one
                row per HEC-RAS geometry/model realization.
            centerlines: Reach centerlines.  ``reach_id_col`` identifies reaches.
            cross_sections: Cross-section cut lines, or ``None``.  When a reach
                identifier is absent, each cross section is assigned spatially.
            flowpaths: Hydrofabric flowpaths GeoDataFrame or vector path.
            adapter: ``'auto'``, ``'nhdplus'``, ``'nwm'``, ``'nextgen'``, or a
                custom :class:`HydrofabricAdapter`.
            hucs: Optional HUC polygon layer.  Intersections are returned without
                influencing the candidate score.
            analysis_crs: Optional projected CRS for measurements.  A local UTM
                CRS is estimated automatically when centerlines are geographic.
            search_distance: Candidate-search radius in analysis-CRS units.
            topology_tolerance: Endpoint-connectivity tolerance in analysis-CRS
                units.
            max_candidates: Maximum reach candidates retained after spatial
                preselection.
            min_confidence: Minimum accepted score in ``[0, 1]``.
            ambiguity_margin: Minimum first/second score separation.
            weights: Optional overrides for :data:`DEFAULT_CONFLATION_WEIGHTS`.

        Returns:
            :class:`HydrofabricConflationResult`.  Ambiguous and unmatched rows
            have ``feature_id=None``; their best evidence remains in
            ``best_candidate_feature_id`` and ``candidates``.
        """
        _validate_thresholds(
            max_candidates=max_candidates,
            min_confidence=min_confidence,
            ambiguity_margin=ambiguity_margin,
            sample_count=sample_count,
        )
        score_weights = _prepare_weights(weights)

        footprints = _read_geodata(model_footprints, "model_footprints")
        reaches = _read_geodata(centerlines, "centerlines")
        xs = _read_optional_geodata(cross_sections, "cross_sections")
        raw_flowpaths = _read_geodata(
            flowpaths, "flowpaths", layer=flowpaths_layer
        )
        huc_frame = _read_optional_geodata(hucs, "hucs", layer=hucs_layer)

        _require_crs(footprints, "model_footprints")
        _require_crs(reaches, "centerlines")
        _require_crs(raw_flowpaths, "flowpaths")
        if not xs.empty:
            _require_crs(xs, "cross_sections")
        if not huc_frame.empty:
            _require_crs(huc_frame, "hucs")

        selected_adapter = RasHydrofabric.get_adapter(adapter, raw_flowpaths)
        normalized_flowpaths = selected_adapter.normalize(raw_flowpaths)

        footprints, reaches, xs = _prepare_model_frames(
            footprints=footprints,
            reaches=reaches,
            cross_sections=xs,
            geometry_id_col=geometry_id_col,
            centerline_geometry_id_col=centerline_geometry_id_col,
            reach_id_col=reach_id_col,
            xs_id_col=xs_id_col,
            xs_reach_id_col=xs_reach_id_col,
        )

        target_crs = _choose_analysis_crs(reaches, footprints, analysis_crs)
        footprints = footprints.to_crs(target_crs)
        reaches = reaches.to_crs(target_crs)
        xs = xs.to_crs(target_crs) if not xs.empty else _empty_xs(target_crs)
        normalized_flowpaths = normalized_flowpaths.to_crs(target_crs)
        if not huc_frame.empty:
            huc_frame = huc_frame.to_crs(target_crs)

        unit_200m = _metres_to_crs_units(target_crs, 200.0)
        unit_5km = _metres_to_crs_units(target_crs, 5000.0)
        reach_lengths = reaches.geometry.length
        median_reach_length = float(reach_lengths[reach_lengths > 0].median())
        if not np.isfinite(median_reach_length):
            median_reach_length = unit_200m
        if search_distance is None:
            search_distance = max(
                unit_200m, min(median_reach_length * 0.25, unit_5km)
            )
        if search_distance <= 0:
            raise ValueError("search_distance must be greater than zero")
        if topology_tolerance is None:
            topology_tolerance = max(
                _metres_to_crs_units(target_crs, 20.0),
                min(median_reach_length * 0.02, unit_200m),
            )
        if topology_tolerance <= 0:
            raise ValueError("topology_tolerance must be greater than zero")

        reach_candidates = _score_reach_candidates(
            footprints=footprints,
            reaches=reaches,
            cross_sections=xs,
            flowpaths=normalized_flowpaths,
            search_distance=float(search_distance),
            topology_tolerance=float(topology_tolerance),
            max_candidates=max_candidates,
            weights=score_weights,
            sample_count=sample_count,
        )

        match_rows: list[Dict[str, Any]] = []
        candidate_rows: list[Dict[str, Any]] = []

        reach_groups = _group_records(reach_candidates, "reach_id")
        for reach in reaches.itertuples(index=False):
            rows = reach_groups.get(str(reach.reach_id), [])
            ranked = _rank_records(rows)
            candidate_rows.extend(
                _candidate_output_rows(ranked, element_type="reach")
            )
            match_rows.append(
                _resolve_match(
                    ranked,
                    element_type="reach",
                    geometry_id=str(reach.geometry_id),
                    reach_id=str(reach.reach_id),
                    xs_id=None,
                    element_geometry=reach.geometry,
                    adapter_name=selected_adapter.name,
                    min_confidence=min_confidence,
                    ambiguity_margin=ambiguity_margin,
                )
            )

        xs_candidate_rows, xs_match_rows = _resolve_cross_sections(
            cross_sections=xs,
            reach_groups=reach_groups,
            search_distance=float(search_distance),
            adapter_name=selected_adapter.name,
            min_confidence=min_confidence,
            ambiguity_margin=ambiguity_margin,
        )
        candidate_rows.extend(xs_candidate_rows)
        match_rows.extend(xs_match_rows)

        geometry_candidate_rows, geometry_match_rows = _resolve_geometries(
            footprints=footprints,
            reaches=reaches,
            reach_groups=reach_groups,
            adapter_name=selected_adapter.name,
            min_confidence=min_confidence,
            ambiguity_margin=ambiguity_margin,
        )
        candidate_rows.extend(geometry_candidate_rows)
        match_rows.extend(geometry_match_rows)

        matches = _make_matches_gdf(match_rows, target_crs)
        candidates = _make_candidates_gdf(candidate_rows, target_crs)
        huc_intersections = _build_huc_intersections(
            footprints=footprints,
            hucs=huc_frame,
            huc_id_col=huc_id_col,
            crs=target_crs,
        )

        element_order = pd.CategoricalDtype(
            categories=["geometry", "reach", "cross_section"], ordered=True
        )
        if not matches.empty:
            matches["element_type"] = matches["element_type"].astype(element_order)
            matches = matches.sort_values(
                ["element_type", "geometry_id", "reach_id", "xs_id"],
                na_position="first",
            ).reset_index(drop=True)
            matches["element_type"] = matches["element_type"].astype(str)
        if not candidates.empty:
            candidates["element_type"] = candidates["element_type"].astype(
                element_order
            )
            candidates = candidates.sort_values(
                [
                    "element_type", "geometry_id", "reach_id", "xs_id",
                    "candidate_rank",
                ],
                na_position="first",
            ).reset_index(drop=True)
            candidates["element_type"] = candidates["element_type"].astype(str)

        parameters = {
            "weights": dict(score_weights),
            "search_distance": float(search_distance),
            "topology_tolerance": float(topology_tolerance),
            "max_candidates": int(max_candidates),
            "min_confidence": float(min_confidence),
            "ambiguity_margin": float(ambiguity_margin),
            "sample_count": int(sample_count),
        }
        return HydrofabricConflationResult(
            matches=matches,
            candidates=candidates,
            huc_intersections=huc_intersections,
            adapter=selected_adapter.name,
            analysis_crs=target_crs.to_string(),
            parameters=parameters,
        )


def _validate_thresholds(
    *,
    max_candidates: int,
    min_confidence: float,
    ambiguity_margin: float,
    sample_count: int,
) -> None:
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be between 0 and 1")
    if not 0 <= ambiguity_margin <= 1:
        raise ValueError("ambiguity_margin must be between 0 and 1")
    if sample_count < 3:
        raise ValueError("sample_count must be at least 3")


def _prepare_weights(
    overrides: Optional[Mapping[str, float]],
) -> Dict[str, float]:
    result = dict(DEFAULT_CONFLATION_WEIGHTS)
    if overrides:
        unknown = set(overrides) - set(result)
        if unknown:
            raise ValueError(f"Unknown conflation weight(s): {sorted(unknown)}")
        result.update({key: float(value) for key, value in overrides.items()})
    if any(not np.isfinite(value) or value < 0 for value in result.values()):
        raise ValueError("Conflation weights must be finite and non-negative")
    if sum(result.values()) <= 0:
        raise ValueError("At least one conflation weight must be positive")
    return result


def _read_geodata(
    value: GeoInput,
    label: str,
    *,
    layer: Optional[str] = None,
) -> gpd.GeoDataFrame:
    if isinstance(value, gpd.GeoDataFrame):
        frame = value.copy()
    elif isinstance(value, (str, Path)):
        frame = gpd.read_file(Path(value), layer=layer)
    else:
        raise TypeError(f"{label} must be a GeoDataFrame or vector path")
    if "geometry" not in frame:
        raise ValueError(f"{label} has no active geometry column")
    if frame.empty:
        raise ValueError(f"{label} is empty")
    return frame


def _read_optional_geodata(
    value: Optional[GeoInput],
    label: str,
    *,
    layer: Optional[str] = None,
) -> gpd.GeoDataFrame:
    if value is None:
        return gpd.GeoDataFrame(geometry=[], crs=None)
    return _read_geodata(value, label, layer=layer)


def _require_crs(frame: gpd.GeoDataFrame, label: str) -> None:
    if frame.crs is None:
        raise ValueError(f"{label} must have a CRS")


def _find_column(
    frame: pd.DataFrame,
    explicit: Optional[str],
    aliases: Sequence[str],
) -> Optional[str]:
    lookup = {str(column).lower(): str(column) for column in frame.columns}
    candidates: Iterable[str] = (
        ((explicit,) if explicit else ()) + tuple(aliases)
    )
    for candidate in candidates:
        actual = lookup.get(str(candidate).lower())
        if actual is not None:
            return actual
    return None


def _normalise_identifier(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, (np.integer, int)):
        return str(int(value))
    if isinstance(value, (np.floating, float)) and float(value).is_integer():
        return str(int(value))
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "<na>"}:
        return None
    return text


def _prepare_model_frames(
    *,
    footprints: gpd.GeoDataFrame,
    reaches: gpd.GeoDataFrame,
    cross_sections: gpd.GeoDataFrame,
    geometry_id_col: Optional[str],
    centerline_geometry_id_col: Optional[str],
    reach_id_col: Optional[str],
    xs_id_col: Optional[str],
    xs_reach_id_col: Optional[str],
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    footprints = footprints.copy()
    reaches = reaches.copy()
    cross_sections = cross_sections.copy()

    footprint_id = _find_column(
        footprints,
        geometry_id_col,
        ("geometry_id", "geom_id", "model_id", "final_name_key", "id"),
    )
    if footprint_id is None:
        footprints["geometry_id"] = footprints.index.map(
            lambda value: f"geometry-{value}"
        )
    else:
        footprints["geometry_id"] = footprints[footprint_id].map(
            _normalise_identifier
        )
    if footprints["geometry_id"].isna().any():
        raise ValueError("model_footprints contain null/blank geometry IDs")
    if footprints["geometry_id"].duplicated().any():
        raise ValueError("model_footprints geometry IDs must be unique")

    reach_id_source = _find_column(
        reaches,
        reach_id_col,
        ("reach_id", "reach", "reach_name", "river_reach", "id"),
    )
    if reach_id_source is None:
        reaches["reach_id"] = reaches.index.map(lambda value: f"reach-{value}")
    else:
        reaches["reach_id"] = reaches[reach_id_source].map(_normalise_identifier)
    if reaches["reach_id"].isna().any():
        raise ValueError("centerlines contain null/blank reach IDs")
    if reaches["reach_id"].duplicated().any():
        raise ValueError("centerline reach IDs must be unique")

    reach_geometry_id = _find_column(
        reaches,
        centerline_geometry_id_col,
        ("geometry_id", "geom_id", "model_id", "final_name_key"),
    )
    if reach_geometry_id is not None:
        reaches["geometry_id"] = reaches[reach_geometry_id].map(
            _normalise_identifier
        )
    elif len(footprints) == 1:
        reaches["geometry_id"] = str(footprints.iloc[0]["geometry_id"])
    else:
        reaches["geometry_id"] = reaches.geometry.map(
            lambda geom: _spatial_parent_id(
                geom, footprints, "geometry_id", prefer_overlap=True
            )
        )
    unknown_geometry_ids = set(reaches["geometry_id"].dropna()) - set(
        footprints["geometry_id"]
    )
    if unknown_geometry_ids:
        raise ValueError(
            "centerlines reference unknown geometry IDs: "
            f"{sorted(map(str, unknown_geometry_ids))}"
        )
    if reaches["geometry_id"].isna().any():
        raise ValueError("Some centerlines could not be assigned to a model footprint")

    order_col = _find_column(
        reaches, None, ("stream_order", "streamorde", "order")
    )
    area_col = _find_column(
        reaches,
        None,
        ("drainage_area", "areasqkm", "totdasqkm", "area_sqkm"),
    )
    reaches["model_stream_order"] = (
        pd.to_numeric(reaches[order_col], errors="coerce")
        if order_col
        else np.nan
    )
    reaches["model_drainage_area"] = (
        pd.to_numeric(reaches[area_col], errors="coerce")
        if area_col
        else np.nan
    )

    if cross_sections.empty:
        return footprints, reaches, _empty_xs(reaches.crs)

    xs_id_source = _find_column(
        cross_sections,
        xs_id_col,
        ("xs_id", "river_station", "riverstation", "rs", "station", "id"),
    )
    if xs_id_source is None:
        cross_sections["xs_id"] = cross_sections.index.map(
            lambda value: f"xs-{value}"
        )
    else:
        cross_sections["xs_id"] = cross_sections[xs_id_source].map(
            _normalise_identifier
        )
    if cross_sections["xs_id"].isna().any():
        raise ValueError("cross_sections contain null/blank cross-section IDs")

    xs_reach_source = _find_column(
        cross_sections,
        xs_reach_id_col,
        ("reach_id", "reach", "reach_name", "river_reach"),
    )
    if xs_reach_source is not None:
        cross_sections["reach_id"] = cross_sections[xs_reach_source].map(
            _normalise_identifier
        )
    else:
        reach_for_xs = reaches.to_crs(cross_sections.crs)
        cross_sections["reach_id"] = cross_sections.geometry.map(
            lambda geom: _spatial_parent_id(
                geom, reach_for_xs, "reach_id", prefer_overlap=False
            )
        )
    unknown_reaches = set(cross_sections["reach_id"].dropna()) - set(
        reaches["reach_id"]
    )
    if unknown_reaches:
        raise ValueError(
            "cross_sections reference unknown reach IDs: "
            f"{sorted(map(str, unknown_reaches))}"
        )
    reach_to_geometry = reaches.set_index("reach_id")["geometry_id"].to_dict()
    cross_sections["geometry_id"] = cross_sections["reach_id"].map(
        reach_to_geometry
    )
    return footprints, reaches, cross_sections


def _empty_xs(crs: Any) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"xs_id": [], "reach_id": [], "geometry_id": []},
        geometry=[],
        crs=crs,
    )


def _spatial_parent_id(
    geometry: BaseGeometry,
    parents: gpd.GeoDataFrame,
    id_col: str,
    *,
    prefer_overlap: bool,
) -> Optional[str]:
    if geometry is None or geometry.is_empty:
        return None
    distances = parents.geometry.distance(geometry)
    intersecting = parents.loc[parents.geometry.intersects(geometry)]
    if not intersecting.empty:
        if prefer_overlap:
            scores = intersecting.geometry.map(
                lambda candidate: candidate.intersection(geometry).length
            )
            return str(intersecting.loc[scores.idxmax(), id_col])
        return str(intersecting.iloc[0][id_col])
    if distances.empty or not np.isfinite(distances.min()):
        return None
    return str(parents.loc[distances.idxmin(), id_col])


def _choose_analysis_crs(
    reaches: gpd.GeoDataFrame,
    footprints: gpd.GeoDataFrame,
    requested: Optional[Any],
) -> CRS:
    if requested is not None:
        target = CRS.from_user_input(requested)
        if not target.is_projected:
            raise ValueError("analysis_crs must be projected")
        return target
    source = CRS.from_user_input(reaches.crs)
    if source.is_projected:
        return source
    combined = gpd.GeoDataFrame(
        geometry=[unary_union(footprints.to_crs(reaches.crs).geometry)],
        crs=reaches.crs,
    )
    estimated = combined.estimate_utm_crs()
    if estimated is None:
        raise ValueError(
            "Could not estimate a projected CRS; pass analysis_crs explicitly"
        )
    return CRS.from_user_input(estimated)


def _metres_to_crs_units(crs: CRS, metres: float) -> float:
    axis = crs.axis_info[0] if crs.axis_info else None
    factor = float(axis.unit_conversion_factor) if axis else 1.0
    if not np.isfinite(factor) or factor <= 0:
        factor = 1.0
    return float(metres) / factor


def _score_reach_candidates(
    *,
    footprints: gpd.GeoDataFrame,
    reaches: gpd.GeoDataFrame,
    cross_sections: gpd.GeoDataFrame,
    flowpaths: gpd.GeoDataFrame,
    search_distance: float,
    topology_tolerance: float,
    max_candidates: int,
    weights: Mapping[str, float],
    sample_count: int,
) -> list[Dict[str, Any]]:
    footprint_lookup = footprints.set_index("geometry_id").geometry.to_dict()
    records: list[Dict[str, Any]] = []

    try:
        spatial_index = flowpaths.sindex
    except GEOSException:
        spatial_index = None

    for reach in reaches.itertuples(index=False):
        reach_geometry = reach.geometry
        if reach_geometry is None or reach_geometry.is_empty:
            continue
        footprint = footprint_lookup[str(reach.geometry_id)]
        search_geometry = unary_union(
            [reach_geometry.buffer(search_distance), footprint]
        )
        if spatial_index is not None:
            indices = list(
                spatial_index.query(search_geometry, predicate="intersects")
            )
            possible = flowpaths.iloc[indices]
        else:
            possible = flowpaths.loc[flowpaths.geometry.intersects(search_geometry)]
        possible = possible.loc[
            possible.geometry.notna() & ~possible.geometry.is_empty
        ]
        if possible.empty:
            continue

        reach_xs = cross_sections.loc[
            cross_sections["reach_id"].astype(str) == str(reach.reach_id)
        ]
        preliminary: list[Dict[str, Any]] = []
        for flowpath in possible.itertuples(index=False):
            flow_geometry = flowpath.geometry
            mean_distance = _symmetric_mean_distance(
                reach_geometry, flow_geometry, sample_count
            )
            overlap_ratio = _footprint_overlap_ratio(flow_geometry, footprint)
            xs_count = int(reach_xs.geometry.intersects(flow_geometry).sum())
            preliminary.append(
                {
                    "flowpath": flowpath,
                    "mean_distance": mean_distance,
                    "overlap_ratio": overlap_ratio,
                    "xs_count": xs_count,
                }
            )
        preliminary.sort(
            key=lambda item: (
                item["mean_distance"],
                -item["xs_count"],
                -item["overlap_ratio"],
            )
        )

        for item in preliminary[:max_candidates]:
            flowpath = item["flowpath"]
            flow_geometry = flowpath.geometry
            mean_distance = float(item["mean_distance"])
            overlap_ratio = float(item["overlap_ratio"])
            xs_count = int(item["xs_count"])
            angle_difference, direction_score = _direction_agreement(
                reach_geometry, flow_geometry
            )
            xs_score = (
                xs_count / len(reach_xs) if len(reach_xs) else None
            )
            sequence_score = _sequence_consistency(
                reach_geometry, flow_geometry, reach_xs
            )
            record = {
                "element_type": "reach",
                "geometry_id": str(reach.geometry_id),
                "reach_id": str(reach.reach_id),
                "xs_id": None,
                "feature_id": str(flowpath.feature_id),
                "adapter": str(flowpath.adapter),
                "footprint_overlap_score": overlap_ratio,
                "footprint_overlap_ratio": overlap_ratio,
                "centerline_distance_score": exp(
                    -mean_distance / max(search_distance * 0.5, 1e-12)
                ),
                "centerline_mean_distance": mean_distance,
                "direction_agreement_score": direction_score,
                "angular_difference_deg": angle_difference,
                "xs_intersection_score": xs_score,
                "xs_intersection_count": xs_count,
                "xs_total_count": int(len(reach_xs)),
                "topological_continuity_score": None,
                "hydrologic_score": None,
                "stream_order": _finite_or_none(flowpath.stream_order),
                "drainage_area": _finite_or_none(flowpath.drainage_area),
                "sequence_consistency_score": sequence_score,
                "to_feature_id": _normalise_identifier(flowpath.to_feature_id),
                "from_node": _normalise_identifier(flowpath.from_node),
                "to_node": _normalise_identifier(flowpath.to_node),
                "hydrosequence": _finite_or_none(flowpath.hydrosequence),
                "model_stream_order": _finite_or_none(reach.model_stream_order),
                "model_drainage_area": _finite_or_none(
                    reach.model_drainage_area
                ),
                "geometry": flow_geometry,
                "flowpath_measure": None,
                "flowpath_measure_fraction": None,
                "flowpath_measure_from_end": None,
                "measure_method": None,
                "offset_distance": None,
            }
            records.append(record)

    grouped = _group_records(records, "reach_id")
    for group in grouped.values():
        _assign_hydrologic_scores(group)

    model_adjacency = _model_adjacency(reaches, topology_tolerance)
    for record in records:
        neighbours = model_adjacency.get(str(record["reach_id"]), set())
        if not neighbours:
            record["topological_continuity_score"] = None
            continue
        supported = 0
        considered = 0
        for neighbour in neighbours:
            neighbour_candidates = grouped.get(neighbour, [])
            if not neighbour_candidates:
                continue
            considered += 1
            if any(
                _flowpaths_connected(
                    record, candidate, topology_tolerance
                )
                for candidate in neighbour_candidates
            ):
                supported += 1
        record["topological_continuity_score"] = (
            supported / considered if considered else None
        )

    for record in records:
        record["confidence_score"] = _weighted_score(record, weights)
        record["reason_codes"] = _evidence_reason_codes(record)
    return records


def _group_records(
    records: Sequence[Dict[str, Any]], key: str
) -> Dict[str, list[Dict[str, Any]]]:
    grouped: Dict[str, list[Dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record[key]), []).append(record)
    return grouped


def _assign_hydrologic_scores(group: list[Dict[str, Any]]) -> None:
    orders = [record["stream_order"] for record in group]
    areas = [record["drainage_area"] for record in group]
    finite_orders = [float(value) for value in orders if value is not None]
    finite_areas = [float(value) for value in areas if value is not None and value > 0]
    max_order = max(finite_orders) if finite_orders else None
    log_areas = [log(value) for value in finite_areas]
    min_log_area = min(log_areas) if log_areas else None
    max_log_area = max(log_areas) if log_areas else None

    for record in group:
        components: list[float] = []
        value = record["stream_order"]
        expected = record["model_stream_order"]
        if value is not None:
            if expected is not None:
                components.append(1.0 / (1.0 + abs(value - expected)))
            elif max_order and max_order > 0:
                components.append(max(0.0, min(1.0, value / max_order)))
        value = record["drainage_area"]
        expected = record["model_drainage_area"]
        if value is not None and value > 0:
            if expected is not None and expected > 0:
                components.append(exp(-abs(log(value / expected))))
            elif min_log_area is not None and max_log_area is not None:
                if max_log_area == min_log_area:
                    components.append(1.0)
                else:
                    components.append(
                        (log(value) - min_log_area) /
                        (max_log_area - min_log_area)
                    )
        record["hydrologic_score"] = (
            float(np.mean(components)) if components else None
        )


def _model_adjacency(
    reaches: gpd.GeoDataFrame, tolerance: float
) -> Dict[str, set[str]]:
    result = {str(value): set() for value in reaches["reach_id"]}
    rows = list(reaches[["reach_id", "geometry"]].itertuples(index=False))
    for index, left in enumerate(rows):
        left_endpoints = _line_endpoints(left.geometry)
        if left_endpoints is None:
            continue
        for right in rows[index + 1:]:
            right_endpoints = _line_endpoints(right.geometry)
            if right_endpoints is None:
                continue
            if min(
                point_a.distance(point_b)
                for point_a in left_endpoints
                for point_b in right_endpoints
            ) <= tolerance:
                left_id = str(left.reach_id)
                right_id = str(right.reach_id)
                result[left_id].add(right_id)
                result[right_id].add(left_id)
    return result


def _flowpaths_connected(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    tolerance: float,
) -> bool:
    if left["feature_id"] == right["feature_id"]:
        return True
    if left.get("to_feature_id") == right["feature_id"]:
        return True
    if right.get("to_feature_id") == left["feature_id"]:
        return True
    node_pairs = (
        (left.get("to_node"), right.get("from_node")),
        (right.get("to_node"), left.get("from_node")),
    )
    if any(a is not None and a == b for a, b in node_pairs):
        return True
    left_endpoints = _line_endpoints(left["geometry"])
    right_endpoints = _line_endpoints(right["geometry"])
    if left_endpoints is None or right_endpoints is None:
        return False
    return min(
        point_a.distance(point_b)
        for point_a in left_endpoints
        for point_b in right_endpoints
    ) <= tolerance


def _weighted_score(
    record: Mapping[str, Any], weights: Mapping[str, float]
) -> float:
    metrics = {
        "footprint_overlap": record.get("footprint_overlap_score"),
        "centerline_distance": record.get("centerline_distance_score"),
        "direction_agreement": record.get("direction_agreement_score"),
        "xs_intersections": record.get("xs_intersection_score"),
        "topological_continuity": record.get(
            "topological_continuity_score"
        ),
        "stream_order_drainage_area": record.get("hydrologic_score"),
        "sequence_consistency": record.get("sequence_consistency_score"),
    }
    numerator = 0.0
    denominator = 0.0
    for name, value in metrics.items():
        if value is None or not np.isfinite(value):
            continue
        weight = weights[name]
        numerator += weight * max(0.0, min(1.0, float(value)))
        denominator += weight
    return numerator / denominator if denominator else 0.0


def _evidence_reason_codes(record: Mapping[str, Any]) -> Tuple[str, ...]:
    reasons: list[str] = []
    if float(record.get("footprint_overlap_score") or 0.0) >= 0.75:
        reasons.append("FOOTPRINT_OVERLAP_STRONG")
    elif float(record.get("footprint_overlap_score") or 0.0) > 0:
        reasons.append("FOOTPRINT_OVERLAP_PARTIAL")
    if float(record.get("centerline_distance_score") or 0.0) >= 0.75:
        reasons.append("CENTERLINE_PROXIMATE")
    if float(record.get("direction_agreement_score") or 0.0) >= 0.75:
        reasons.append("DIRECTION_ALIGNED")
    xs_score = record.get("xs_intersection_score")
    if xs_score is not None and xs_score >= 0.5:
        reasons.append("XS_INTERSECTIONS_SUPPORTED")
    topology = record.get("topological_continuity_score")
    if topology is not None and topology >= 0.5:
        reasons.append("TOPOLOGY_CONTINUOUS")
    hydrologic = record.get("hydrologic_score")
    if hydrologic is not None and hydrologic >= 0.75:
        reasons.append("HYDROLOGIC_SCALE_SUPPORTED")
    sequence = record.get("sequence_consistency_score")
    if sequence is not None and sequence >= 0.75:
        reasons.append("SEQUENCE_CONSISTENT")
    return tuple(reasons)


def _rank_records(
    records: Sequence[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    ranked = sorted(
        (dict(record) for record in records),
        key=lambda record: (-float(record["confidence_score"]), record["feature_id"]),
    )
    for rank, record in enumerate(ranked, start=1):
        record["candidate_rank"] = rank
    return ranked


def _candidate_output_rows(
    ranked: Sequence[Dict[str, Any]],
    *,
    element_type: str,
) -> list[Dict[str, Any]]:
    result = []
    for record in ranked:
        output = {column: record.get(column) for column in _CANDIDATE_COLUMNS}
        output["element_type"] = element_type
        result.append(output)
    return result


def _resolve_match(
    ranked: Sequence[Dict[str, Any]],
    *,
    element_type: str,
    geometry_id: str,
    reach_id: Optional[str],
    xs_id: Optional[str],
    element_geometry: BaseGeometry,
    adapter_name: str,
    min_confidence: float,
    ambiguity_margin: float,
) -> Dict[str, Any]:
    if not ranked:
        return {
            "element_type": element_type,
            "geometry_id": geometry_id,
            "reach_id": reach_id,
            "xs_id": xs_id,
            "feature_id": None,
            "best_candidate_feature_id": None,
            "status": ConflationStatus.UNMATCHED.value,
            "confidence_score": 0.0,
            "score_margin": None,
            "candidate_count": 0,
            "match_method": "no_spatial_candidate",
            "reason_codes": ("NO_CANDIDATES",),
            "adapter": adapter_name,
            "flowpath_measure": None,
            "flowpath_measure_fraction": None,
            "flowpath_measure_from_end": None,
            "measure_method": None,
            "offset_distance": None,
            "geometry": element_geometry,
        }

    top = ranked[0]
    second_score = (
        float(ranked[1]["confidence_score"]) if len(ranked) > 1 else None
    )
    margin = (
        float(top["confidence_score"]) - second_score
        if second_score is not None
        else None
    )
    reasons = list(top.get("reason_codes") or ())
    if float(top["confidence_score"]) < min_confidence:
        status = ConflationStatus.UNMATCHED
        method = "multi_criteria_below_threshold"
        reasons.append("LOW_CONFIDENCE")
    elif margin is not None and margin < ambiguity_margin:
        status = ConflationStatus.AMBIGUOUS
        method = "multi_criteria_ambiguous"
        reasons.append("CLOSE_CANDIDATE_SCORES")
    else:
        status = ConflationStatus.MATCHED
        method = "multi_criteria_score"

    return {
        "element_type": element_type,
        "geometry_id": geometry_id,
        "reach_id": reach_id,
        "xs_id": xs_id,
        "feature_id": (
            top["feature_id"] if status is ConflationStatus.MATCHED else None
        ),
        "best_candidate_feature_id": top["feature_id"],
        "status": status.value,
        "confidence_score": float(top["confidence_score"]),
        "score_margin": margin,
        "candidate_count": len(ranked),
        "match_method": method,
        "reason_codes": tuple(dict.fromkeys(reasons)),
        "adapter": adapter_name,
        "flowpath_measure": (
            top.get("flowpath_measure")
            if status is ConflationStatus.MATCHED
            else None
        ),
        "flowpath_measure_fraction": (
            top.get("flowpath_measure_fraction")
            if status is ConflationStatus.MATCHED
            else None
        ),
        "flowpath_measure_from_end": (
            top.get("flowpath_measure_from_end")
            if status is ConflationStatus.MATCHED
            else None
        ),
        "measure_method": (
            top.get("measure_method")
            if status is ConflationStatus.MATCHED
            else None
        ),
        "offset_distance": (
            top.get("offset_distance")
            if status is ConflationStatus.MATCHED
            else None
        ),
        "geometry": element_geometry,
    }


def _resolve_cross_sections(
    *,
    cross_sections: gpd.GeoDataFrame,
    reach_groups: Mapping[str, list[Dict[str, Any]]],
    search_distance: float,
    adapter_name: str,
    min_confidence: float,
    ambiguity_margin: float,
) -> Tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    candidate_rows: list[Dict[str, Any]] = []
    match_rows: list[Dict[str, Any]] = []
    for xs in cross_sections.itertuples(index=False):
        reach_id = _normalise_identifier(xs.reach_id)
        geometry_id = str(xs.geometry_id)
        base_candidates = reach_groups.get(str(reach_id), []) if reach_id else []
        local_candidates: list[Dict[str, Any]] = []
        for base in base_candidates:
            record = dict(base)
            flowpath = record["geometry"]
            intersects = bool(xs.geometry.intersects(flowpath))
            offset = float(xs.geometry.distance(flowpath))
            proximity = exp(-offset / max(search_distance * 0.25, 1e-12))
            local_support = 0.7 * float(intersects) + 0.3 * proximity
            record["confidence_score"] = (
                0.70 * float(base["confidence_score"]) + 0.30 * local_support
            )
            measure = _along_flowpath_measure(flowpath, xs.geometry)
            record.update(measure)
            record["element_type"] = "cross_section"
            record["geometry_id"] = geometry_id
            record["reach_id"] = reach_id
            record["xs_id"] = str(xs.xs_id)
            reasons = list(base.get("reason_codes") or ())
            reasons.append("XS_DIRECT_INTERSECTION" if intersects else "XS_NEAREST")
            record["reason_codes"] = tuple(dict.fromkeys(reasons))
            local_candidates.append(record)
        ranked = _rank_records(local_candidates)
        candidate_rows.extend(
            _candidate_output_rows(ranked, element_type="cross_section")
        )
        match_rows.append(
            _resolve_match(
                ranked,
                element_type="cross_section",
                geometry_id=geometry_id,
                reach_id=reach_id,
                xs_id=str(xs.xs_id),
                element_geometry=xs.geometry,
                adapter_name=adapter_name,
                min_confidence=min_confidence,
                ambiguity_margin=ambiguity_margin,
            )
        )
    return candidate_rows, match_rows


def _resolve_geometries(
    *,
    footprints: gpd.GeoDataFrame,
    reaches: gpd.GeoDataFrame,
    reach_groups: Mapping[str, list[Dict[str, Any]]],
    adapter_name: str,
    min_confidence: float,
    ambiguity_margin: float,
) -> Tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    candidate_rows: list[Dict[str, Any]] = []
    match_rows: list[Dict[str, Any]] = []
    for footprint in footprints.itertuples(index=False):
        geometry_id = str(footprint.geometry_id)
        geometry_reach_ids = reaches.loc[
            reaches["geometry_id"].astype(str) == geometry_id, "reach_id"
        ].astype(str).tolist()
        aggregate: Dict[str, list[Dict[str, Any]]] = {}
        for reach_id in geometry_reach_ids:
            for candidate in reach_groups.get(reach_id, []):
                aggregate.setdefault(candidate["feature_id"], []).append(candidate)

        geometry_candidates: list[Dict[str, Any]] = []
        denominator = max(len(geometry_reach_ids), 1)
        for records in aggregate.values():
            representative = dict(
                max(records, key=lambda item: float(item["confidence_score"]))
            )
            support_fraction = len({item["reach_id"] for item in records}) / denominator
            representative["confidence_score"] = (
                0.70 * max(float(item["confidence_score"]) for item in records)
                + 0.30 * support_fraction
            )
            representative["element_type"] = "geometry"
            representative["geometry_id"] = geometry_id
            representative["reach_id"] = None
            representative["xs_id"] = None
            reasons = list(representative.get("reason_codes") or ())
            if support_fraction >= 0.5:
                reasons.append("MULTI_REACH_SUPPORT")
            representative["reason_codes"] = tuple(dict.fromkeys(reasons))
            geometry_candidates.append(representative)

        ranked = _rank_records(geometry_candidates)
        candidate_rows.extend(
            _candidate_output_rows(ranked, element_type="geometry")
        )
        match_rows.append(
            _resolve_match(
                ranked,
                element_type="geometry",
                geometry_id=geometry_id,
                reach_id=None,
                xs_id=None,
                element_geometry=footprint.geometry,
                adapter_name=adapter_name,
                min_confidence=min_confidence,
                ambiguity_margin=ambiguity_margin,
            )
        )
    return candidate_rows, match_rows


def _along_flowpath_measure(
    flowpath: BaseGeometry, cross_section: BaseGeometry
) -> Dict[str, Any]:
    intersection = flowpath.intersection(cross_section)
    if not intersection.is_empty:
        point = intersection.centroid
        method = "intersection"
        offset = 0.0
    else:
        point, _ = nearest_points(flowpath, cross_section)
        method = "nearest"
        offset = float(flowpath.distance(cross_section))
    length = float(flowpath.length)
    measure = float(flowpath.project(point)) if length > 0 else 0.0
    return {
        "flowpath_measure": measure,
        "flowpath_measure_fraction": measure / length if length > 0 else None,
        "flowpath_measure_from_end": length - measure if length > 0 else None,
        "measure_method": method,
        "offset_distance": offset,
    }


def _footprint_overlap_ratio(
    flowpath: BaseGeometry, footprint: BaseGeometry
) -> float:
    length = float(flowpath.length)
    if length <= 0:
        return 0.0
    try:
        overlap = float(flowpath.intersection(footprint).length)
    except Exception:
        overlap = 0.0
    return max(0.0, min(1.0, overlap / length))


def _symmetric_mean_distance(
    left: BaseGeometry, right: BaseGeometry, sample_count: int
) -> float:
    left_points = _sample_line(left, sample_count)
    right_points = _sample_line(right, sample_count)
    distances = [point.distance(right) for point in left_points]
    distances.extend(point.distance(left) for point in right_points)
    return float(np.mean(distances)) if distances else float("inf")


def _sample_line(geometry: BaseGeometry, count: int) -> list[Point]:
    line = _representative_line(geometry)
    if line is None or line.length <= 0:
        return []
    return [
        line.interpolate(float(fraction), normalized=True)
        for fraction in np.linspace(0.0, 1.0, count)
    ]


def _representative_line(geometry: BaseGeometry) -> Optional[LineString]:
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        if isinstance(merged, MultiLineString) and merged.geoms:
            return max(merged.geoms, key=lambda item: item.length)
    if hasattr(geometry, "geoms"):
        lines = [
            part for part in geometry.geoms
            if isinstance(part, (LineString, MultiLineString))
        ]
        if lines:
            return _representative_line(max(lines, key=lambda item: item.length))
    return None


def _line_endpoints(
    geometry: BaseGeometry,
) -> Optional[Tuple[Point, Point]]:
    line = _representative_line(geometry)
    if line is None or line.is_empty:
        return None
    coordinates = list(line.coords)
    if len(coordinates) < 2:
        return None
    return Point(coordinates[0]), Point(coordinates[-1])


def _direction_agreement(
    left: BaseGeometry, right: BaseGeometry
) -> Tuple[Optional[float], Optional[float]]:
    left_vector = _line_vector(left)
    right_vector = _line_vector(right)
    if left_vector is None or right_vector is None:
        return None, None
    angle_left = degrees(atan2(left_vector[1], left_vector[0])) % 360.0
    angle_right = degrees(atan2(right_vector[1], right_vector[0])) % 360.0
    difference = abs(angle_left - angle_right)
    difference = min(difference, 360.0 - difference)
    score = (cos(radians(difference)) + 1.0) / 2.0
    return difference, max(0.0, min(1.0, score))


def _line_vector(geometry: BaseGeometry) -> Optional[Tuple[float, float]]:
    line = _representative_line(geometry)
    if line is None or line.length <= 0:
        return None
    start = line.interpolate(0.1, normalized=True)
    end = line.interpolate(0.9, normalized=True)
    dx = end.x - start.x
    dy = end.y - start.y
    if hypot(dx, dy) <= 0:
        return None
    return dx, dy


def _sequence_consistency(
    centerline: BaseGeometry,
    flowpath: BaseGeometry,
    cross_sections: gpd.GeoDataFrame,
) -> Optional[float]:
    if len(cross_sections) < 2:
        return None
    model_measures: list[float] = []
    flowpath_measures: list[float] = []
    for xs_geometry in cross_sections.geometry:
        if xs_geometry is None or xs_geometry.is_empty:
            continue
        center_intersection = centerline.intersection(xs_geometry)
        if center_intersection.is_empty:
            center_point, _ = nearest_points(centerline, xs_geometry)
        else:
            center_point = center_intersection.centroid
        flow_intersection = flowpath.intersection(xs_geometry)
        if flow_intersection.is_empty:
            flow_point, _ = nearest_points(flowpath, xs_geometry)
        else:
            flow_point = flow_intersection.centroid
        model_measures.append(float(centerline.project(center_point)))
        flowpath_measures.append(float(flowpath.project(flow_point)))
    if len(model_measures) < 2:
        return None
    if np.std(model_measures) == 0 or np.std(flowpath_measures) == 0:
        return None
    correlation = float(np.corrcoef(model_measures, flowpath_measures)[0, 1])
    if not np.isfinite(correlation):
        return None
    return max(0.0, min(1.0, (correlation + 1.0) / 2.0))


def _finite_or_none(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _make_matches_gdf(
    rows: Sequence[Mapping[str, Any]], crs: CRS
) -> gpd.GeoDataFrame:
    if not rows:
        return gpd.GeoDataFrame(columns=_MATCH_COLUMNS, geometry="geometry", crs=crs)
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    for column in _MATCH_COLUMNS:
        if column not in frame:
            frame[column] = None
    return frame[_MATCH_COLUMNS]


def _make_candidates_gdf(
    rows: Sequence[Mapping[str, Any]], crs: CRS
) -> gpd.GeoDataFrame:
    if not rows:
        return gpd.GeoDataFrame(
            columns=_CANDIDATE_COLUMNS, geometry="geometry", crs=crs
        )
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    for column in _CANDIDATE_COLUMNS:
        if column not in frame:
            frame[column] = None
    return frame[_CANDIDATE_COLUMNS]


def _build_huc_intersections(
    *,
    footprints: gpd.GeoDataFrame,
    hucs: gpd.GeoDataFrame,
    huc_id_col: Optional[str],
    crs: CRS,
) -> gpd.GeoDataFrame:
    columns = [
        "geometry_id", "huc_id", "intersection_area",
        "geometry_area_fraction", "huc_area_fraction", "geometry",
    ]
    if hucs.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=crs)
    id_source = _find_column(
        hucs,
        huc_id_col,
        (
            "huc12", "HUC12", "huc10", "HUC10", "huc8", "HUC8",
            "huc_id", "huc", "id",
        ),
    )
    if id_source is None:
        raise ValueError(
            "Could not find a HUC identifier column; pass huc_id_col explicitly"
        )
    rows: list[Dict[str, Any]] = []
    for footprint in footprints.itertuples(index=False):
        footprint_area = float(footprint.geometry.area)
        possible = hucs.loc[hucs.geometry.intersects(footprint.geometry)]
        for _, huc in possible.iterrows():
            intersection = footprint.geometry.intersection(huc.geometry)
            if intersection.is_empty:
                continue
            area = float(intersection.area)
            huc_area = float(huc.geometry.area)
            rows.append(
                {
                    "geometry_id": str(footprint.geometry_id),
                    "huc_id": _normalise_identifier(huc[id_source]),
                    "intersection_area": area,
                    "geometry_area_fraction": (
                        area / footprint_area if footprint_area > 0 else None
                    ),
                    "huc_area_fraction": area / huc_area if huc_area > 0 else None,
                    "geometry": intersection,
                }
            )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=crs)
