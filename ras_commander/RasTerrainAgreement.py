"""Cross-section geometry versus terrain agreement analysis.

The implementation is intentionally independent of any hydrofabric or network
model.  It compares HEC-RAS station/elevation profiles with profiles sampled
from either an arbitrary raster or the active terrain registered in RAS Mapper.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Union

import numpy as np
import pandas as pd

from .Decorators import log_call
from .LoggingConfig import get_logger


logger = get_logger(__name__)


XS_METRICS_COLUMNS = [
    "xs_id",
    "river",
    "reach",
    "rs",
    "n_source_points",
    "n_terrain_points",
    "n_comparison_points",
    "source_station_min",
    "source_station_max",
    "terrain_station_min",
    "terrain_station_max",
    "station_overlap",
    "station_coverage_ratio",
    "source_vertical_range",
    "source_thalweg_elevation",
    "terrain_thalweg_elevation",
    "thalweg_elevation_difference",
    "source_thalweg_station",
    "terrain_thalweg_station",
    "thalweg_station_difference",
    "residual_mean",
    "residual_std",
    "residual_min",
    "residual_max",
    "residual_p25",
    "residual_p50",
    "residual_p75",
    "rmse",
    "nrmse",
    "pearson_correlation",
    "max_shifted_correlation",
    "shift_distance",
    "stage_count",
    "avg_inundation_overlap",
    "avg_top_width_agreement",
    "avg_flow_area_agreement",
    "avg_flow_area_overlap",
    "avg_hydraulic_radius_agreement",
    "valid",
    "reason_codes",
    "flagged",
    "flag_reasons",
]


STAGE_METRICS_COLUMNS = [
    "xs_id",
    "river",
    "reach",
    "rs",
    "stage",
    "source_top_width",
    "terrain_top_width",
    "top_width_agreement",
    "inundation_overlap",
    "source_flow_area",
    "terrain_flow_area",
    "flow_area_agreement",
    "flow_area_overlap",
    "source_wetted_perimeter",
    "terrain_wetted_perimeter",
    "source_hydraulic_radius",
    "terrain_hydraulic_radius",
    "hydraulic_radius_agreement",
    "residual_mean",
    "residual_std",
    "residual_min",
    "residual_max",
    "residual_p25",
    "residual_p50",
    "residual_p75",
    "rmse",
    "nrmse",
    "valid",
    "reason_codes",
]


DEFAULT_FLAG_THRESHOLDS = {
    "max_nrmse": 0.20,
    "min_pearson_correlation": 0.90,
    "min_inundation_overlap": 0.80,
    "min_flow_area_overlap": 0.80,
    "max_abs_normalized_thalweg_difference": 0.10,
    "min_station_coverage_ratio": 0.90,
}


_SERIOUS_REASON_CODES = {
    "CRS_NOT_VERIFIED",
    "INSUFFICIENT_SOURCE_POINTS",
    "INSUFFICIENT_TERRAIN_POINTS",
    "MISSING_PROFILE_CRS",
    "MISSING_RASTER_CRS",
    "MISSING_CUT_LINE",
    "MISSING_TERRAIN_PROFILE",
    "NO_STATION_OVERLAP",
    "NO_VALID_STAGE_RANGE",
    "NONFINITE_SOURCE_VALUES_DROPPED",
    "NONFINITE_TERRAIN_VALUES_DROPPED",
    "RASTER_INTERNAL_NODATA_GAP",
    "RASTER_NO_VALID_SAMPLES",
    "RASTER_OUT_OF_BOUNDS_SAMPLES",
    "TERRAIN_PROFILE_NO_VALID_SAMPLES",
    "ZERO_SOURCE_STATION_SPAN",
}


_INVALID_PROFILE_REASON_CODES = {
    "MISSING_PROFILE_CRS",
    "MISSING_RASTER_CRS",
    "MISSING_CUT_LINE",
    "RASTER_INTERNAL_NODATA_GAP",
    "RASTER_NO_VALID_SAMPLES",
    "RASTER_OUT_OF_BOUNDS_SAMPLES",
    "TERRAIN_PROFILE_NO_VALID_SAMPLES",
}


@dataclass
class TerrainAgreementResult:
    """Structured return value for a terrain agreement analysis."""

    xs_metrics_df: pd.DataFrame
    stage_metrics_df: pd.DataFrame
    model_summary: Dict[str, Any]
    flagged_xs: pd.DataFrame
    figures: Optional[Dict[str, Any]] = None


@dataclass
class _ProfileRecord:
    xs_id: str
    profile: np.ndarray
    river: str = ""
    reach: str = ""
    rs: str = ""
    geometry: Any = None
    reasons: set[str] = field(default_factory=set)


@dataclass
class _ProfileCollection:
    records: Dict[str, _ProfileRecord]
    crs: Any = None


@dataclass
class _PreparedProfile:
    points: np.ndarray
    interp_points: np.ndarray
    reasons: set[str]


class RasTerrainAgreement:
    """Static workflow for geometry-versus-terrain cross-section QA."""

    @staticmethod
    @log_call
    def analyze(
        geometry_profiles: Any,
        *,
        terrain_profiles: Any = None,
        terrain_raster: Optional[Union[str, Path]] = None,
        ras_project_path: Optional[Union[str, Path]] = None,
        geom_hdf_path: Optional[Union[str, Path]] = None,
        profile_crs: Any = None,
        sample_interval: Optional[float] = None,
        stages: Optional[Union[Sequence[float], Mapping[str, Sequence[float]]]] = None,
        comparison_interval: Optional[float] = None,
        max_shift: Optional[float] = None,
        default_stage_count: int = 10,
        flag_thresholds: Optional[Mapping[str, float]] = None,
        make_figures: bool = False,
        ras_object=None,
    ) -> TerrainAgreementResult:
        """Compare geometry profiles against supplied, raster, or RAS terrain profiles.

        ``geometry_profiles`` may be a mapping of cross-section IDs to Nx2
        station/elevation arrays, a DataFrame/GeoDataFrame with a
        ``station_elevation`` column, a geometry HDF path, or a plain-text
        geometry path.  Automatic terrain sampling requires cut-line geometry,
        which is provided by ``HdfXsec.get_cross_sections()`` or the input
        GeoDataFrame.

        Exactly one terrain source must be supplied:

        * ``terrain_profiles``: pre-sampled station/elevation profiles;
        * ``terrain_raster``: any raster readable by rasterio; or
        * ``ras_project_path``: the active terrain registered in RAS Mapper,
          sampled through ``RasTerrainMod.get_terrain_profile()``.

        NRMSE is RMSE divided by the source profile elevation range.  Positive
        ``shift_distance`` means the terrain profile would be moved toward
        increasing station to maximize Pearson correlation.
        """
        supplied = sum(
            value is not None
            for value in (terrain_profiles, terrain_raster, ras_project_path)
        )
        if supplied != 1:
            raise ValueError(
                "Supply exactly one of terrain_profiles, terrain_raster, or "
                "ras_project_path"
            )
        if sample_interval is not None and sample_interval <= 0:
            raise ValueError("sample_interval must be greater than zero")

        source = RasTerrainAgreement._coerce_profiles(
            geometry_profiles,
            profile_crs=profile_crs,
            ras_object=ras_object,
        )

        if terrain_profiles is not None:
            terrain = RasTerrainAgreement._coerce_profiles(terrain_profiles)
        elif terrain_raster is not None:
            terrain = RasTerrainAgreement._sample_arbitrary_raster(
                source,
                Path(terrain_raster),
                sample_interval=sample_interval,
            )
        else:
            resolved_hdf = geom_hdf_path
            if resolved_hdf is None and isinstance(geometry_profiles, (str, Path)):
                candidate = Path(geometry_profiles)
                if candidate.suffix.lower() == ".hdf":
                    resolved_hdf = candidate
            if resolved_hdf is None:
                raise ValueError(
                    "geom_hdf_path is required to sample a registered RAS Mapper terrain"
                )
            terrain = RasTerrainAgreement._sample_registered_terrain(
                source,
                ras_project_path=ras_project_path,
                geom_hdf_path=Path(resolved_hdf),
                ras_object=ras_object,
            )

        return RasTerrainAgreement._compare_collections(
            source,
            terrain,
            stages=stages,
            comparison_interval=comparison_interval,
            max_shift=max_shift,
            default_stage_count=default_stage_count,
            flag_thresholds=flag_thresholds,
            make_figures=make_figures,
        )

    @staticmethod
    @log_call
    def compare_profiles(
        geometry_profiles: Any,
        terrain_profiles: Any,
        *,
        stages: Optional[Union[Sequence[float], Mapping[str, Sequence[float]]]] = None,
        comparison_interval: Optional[float] = None,
        max_shift: Optional[float] = None,
        default_stage_count: int = 10,
        flag_thresholds: Optional[Mapping[str, float]] = None,
        make_figures: bool = False,
    ) -> TerrainAgreementResult:
        """Compare pre-sampled source and terrain station/elevation profiles."""
        return RasTerrainAgreement._compare_collections(
            RasTerrainAgreement._coerce_profiles(geometry_profiles),
            RasTerrainAgreement._coerce_profiles(terrain_profiles),
            stages=stages,
            comparison_interval=comparison_interval,
            max_shift=max_shift,
            default_stage_count=default_stage_count,
            flag_thresholds=flag_thresholds,
            make_figures=make_figures,
        )

    @staticmethod
    def _coerce_profiles(
        profiles: Any,
        *,
        profile_crs: Any = None,
        ras_object=None,
    ) -> _ProfileCollection:
        if isinstance(profiles, _ProfileCollection):
            return profiles

        if isinstance(profiles, (str, Path)):
            path = Path(profiles)
            if not path.exists():
                raise FileNotFoundError(f"Geometry profile source not found: {path}")
            if path.suffix.lower() == ".hdf":
                from .hdf.HdfXsec import HdfXsec

                return RasTerrainAgreement._coerce_profiles(
                    HdfXsec.get_cross_sections(str(path), ras_object=ras_object),
                    profile_crs=profile_crs,
                )

            from .geom.GeomCrossSection import GeomCrossSection

            xs_df = GeomCrossSection.get_cross_sections(path)
            records: Dict[str, _ProfileRecord] = {}
            for row in xs_df.itertuples(index=False):
                river = str(getattr(row, "River"))
                reach = str(getattr(row, "Reach"))
                rs = str(getattr(row, "RS"))
                xs_id = RasTerrainAgreement._make_xs_id(river, reach, rs)
                records[xs_id] = _ProfileRecord(
                    xs_id=xs_id,
                    profile=RasTerrainAgreement._as_profile_array(
                        GeomCrossSection.get_station_elevation(path, river, reach, rs)
                    ),
                    river=river,
                    reach=reach,
                    rs=rs,
                )
            return _ProfileCollection(dict(sorted(records.items())), profile_crs)

        if isinstance(profiles, pd.DataFrame):
            crs = (
                profile_crs
                if profile_crs is not None
                else getattr(profiles, "crs", None)
            )
            records = {}
            for index, row in profiles.iterrows():
                profile_value = RasTerrainAgreement._first_present(
                    row,
                    (
                        "station_elevation",
                        "profile",
                        "source_profile",
                        "terrain_profile",
                    ),
                )
                river = str(
                    RasTerrainAgreement._first_present(row, ("River", "river"), "")
                )
                reach = str(
                    RasTerrainAgreement._first_present(row, ("Reach", "reach"), "")
                )
                rs = str(RasTerrainAgreement._first_present(row, ("RS", "rs"), ""))
                raw_id = RasTerrainAgreement._first_present(
                    row, ("xs_id", "XS_ID"), None
                )
                xs_id = (
                    str(raw_id)
                    if raw_id not in (None, "")
                    else (
                        RasTerrainAgreement._make_xs_id(river, reach, rs)
                        if any((river, reach, rs))
                        else str(index)
                    )
                )
                if xs_id in records:
                    raise ValueError(f"Duplicate cross-section ID: {xs_id}")
                records[xs_id] = _ProfileRecord(
                    xs_id=xs_id,
                    profile=RasTerrainAgreement._as_profile_array(profile_value),
                    river=river,
                    reach=reach,
                    rs=rs,
                    geometry=RasTerrainAgreement._first_present(
                        row, ("geometry",), None
                    ),
                )
            return _ProfileCollection(dict(sorted(records.items())), crs)

        if isinstance(profiles, Mapping):
            records = {}
            for key in sorted(profiles, key=lambda value: str(value)):
                value = profiles[key]
                metadata = value if isinstance(value, Mapping) else {}
                profile_value = value
                if isinstance(value, Mapping):
                    profile_value = RasTerrainAgreement._first_present(
                        value,
                        (
                            "station_elevation",
                            "profile",
                            "source_profile",
                            "terrain_profile",
                        ),
                    )
                xs_id = str(metadata.get("xs_id", key))
                records[xs_id] = _ProfileRecord(
                    xs_id=xs_id,
                    profile=RasTerrainAgreement._as_profile_array(profile_value),
                    river=str(metadata.get("river", metadata.get("River", ""))),
                    reach=str(metadata.get("reach", metadata.get("Reach", ""))),
                    rs=str(metadata.get("rs", metadata.get("RS", ""))),
                    geometry=metadata.get("geometry"),
                )
            return _ProfileCollection(dict(sorted(records.items())), profile_crs)

        raise TypeError(
            "Profiles must be a mapping, DataFrame/GeoDataFrame, geometry HDF path, "
            "or plain-text geometry path"
        )

    @staticmethod
    def _sample_arbitrary_raster(
        source: _ProfileCollection,
        raster_path: Path,
        *,
        sample_interval: Optional[float],
    ) -> _ProfileCollection:
        if not raster_path.exists():
            raise FileNotFoundError(f"Terrain raster not found: {raster_path}")
        try:
            import rasterio
            from shapely.ops import transform as transform_geometry
        except ImportError as exc:
            raise ImportError(
                "rasterio and shapely are required to sample an arbitrary terrain raster"
            ) from exc
        from .terrain.RasTerrain import RasTerrain

        records: Dict[str, _ProfileRecord] = {}
        with rasterio.open(raster_path) as dataset:
            if source.crs is None or dataset.crs is None:
                reason = (
                    "MISSING_PROFILE_CRS"
                    if source.crs is None
                    else "MISSING_RASTER_CRS"
                )
                logger.warning(
                    "Cannot safely sample %s: %s",
                    raster_path,
                    reason,
                )
                for xs_id, record in source.records.items():
                    records[xs_id] = RasTerrainAgreement._empty_terrain_record(
                        record, set(record.reasons) | {reason}
                    )
                return _ProfileCollection(dict(sorted(records.items())), source.crs)

            interval = sample_interval
            if interval is None:
                interval = max(
                    abs(float(dataset.transform.a)), abs(float(dataset.transform.e))
                )
            if not np.isfinite(interval) or interval <= 0:
                raise ValueError("Could not derive a positive raster sampling interval")

            transformer = None
            if source.crs is not None and dataset.crs is not None:
                try:
                    from pyproj import CRS, Transformer

                    source_crs = CRS.from_user_input(source.crs)
                    raster_crs = CRS.from_user_input(dataset.crs)
                    if source_crs != raster_crs:
                        transformer = Transformer.from_crs(
                            source_crs, raster_crs, always_xy=True
                        ).transform
                except Exception as exc:
                    raise ValueError(
                        f"Unable to transform cross sections into raster CRS {dataset.crs}: {exc}"
                    ) from exc

            for xs_id, record in source.records.items():
                reasons = set(record.reasons)
                line = RasTerrain._as_linestring(record.geometry)
                if line is None:
                    reasons.add("MISSING_CUT_LINE")
                    records[xs_id] = RasTerrainAgreement._empty_terrain_record(
                        record, reasons
                    )
                    continue
                if transformer is not None:
                    line = transform_geometry(transformer, line)
                if line.length <= 0:
                    reasons.add("MISSING_CUT_LINE")
                    records[xs_id] = RasTerrainAgreement._empty_terrain_record(
                        record, reasons
                    )
                    continue

                source_profile = RasTerrainAgreement._prepare_profile(
                    record.profile, "SOURCE"
                )
                if len(source_profile.interp_points) < 2:
                    reasons.add("INSUFFICIENT_SOURCE_POINTS")
                    records[xs_id] = RasTerrainAgreement._empty_terrain_record(
                        record, reasons
                    )
                    continue
                count = max(2, int(np.ceil(line.length / interval)) + 1)
                distances = np.linspace(0.0, float(line.length), count)
                coords = [
                    line.interpolate(float(distance)).coords[0]
                    for distance in distances
                ]
                in_bounds = np.asarray(
                    [
                        0 <= row < dataset.height and 0 <= column < dataset.width
                        for row, column in (dataset.index(x, y) for x, y in coords)
                    ],
                    dtype=bool,
                )
                samples = np.full(count, np.nan, dtype=float)
                bounded_coords = [
                    coord for coord, keep in zip(coords, in_bounds) if keep
                ]
                if bounded_coords:
                    bounded_samples = [
                        float(value[0]) if not np.ma.is_masked(value[0]) else np.nan
                        for value in dataset.sample(
                            bounded_coords, indexes=1, masked=True
                        )
                    ]
                    samples[in_bounds] = bounded_samples
                source_min = float(source_profile.interp_points[0, 0])
                source_max = float(source_profile.interp_points[-1, 0])
                stations = source_min + (distances / line.length) * (
                    source_max - source_min
                )
                valid = np.isfinite(samples)
                if not np.all(in_bounds):
                    reasons.add("RASTER_OUT_OF_BOUNDS_SAMPLES")
                if not np.any(valid):
                    reasons.add("RASTER_NO_VALID_SAMPLES")
                elif not np.all(valid):
                    reasons.add("RASTER_NODATA_SAMPLES_DROPPED")
                    valid_indices = np.flatnonzero(valid)
                    if np.any(~valid[valid_indices[0] : valid_indices[-1] + 1]):
                        reasons.add("RASTER_INTERNAL_NODATA_GAP")
                    else:
                        reasons.add("RASTER_EDGE_NODATA_TRUNCATED")
                records[xs_id] = _ProfileRecord(
                    xs_id=xs_id,
                    profile=np.column_stack((stations[valid], samples[valid])),
                    river=record.river,
                    reach=record.reach,
                    rs=record.rs,
                    geometry=record.geometry,
                    reasons=reasons,
                )

        return _ProfileCollection(dict(sorted(records.items())), source.crs)

    @staticmethod
    def _sample_registered_terrain(
        source: _ProfileCollection,
        *,
        ras_project_path: Union[str, Path],
        geom_hdf_path: Path,
        ras_object=None,
    ) -> _ProfileCollection:
        if ras_project_path is None and ras_object is not None:
            ras_project_path = getattr(ras_object, "project_folder", None)
        if ras_project_path is None:
            raise ValueError("ras_project_path or ras_object is required")
        if not geom_hdf_path.exists():
            raise FileNotFoundError(f"Geometry HDF not found: {geom_hdf_path}")

        from ._land_classification_helper import resolve_project_paths
        from .RasMap import RasMap
        from .terrain.RasTerrain import RasTerrain
        from .terrain.RasTerrainMod import RasTerrainMod

        project_paths = resolve_project_paths(ras_project_path)
        if not project_paths.rasmap_path.exists():
            raise FileNotFoundError(
                f"RAS Mapper file not found: {project_paths.rasmap_path}"
            )
        terrain_layers = RasMap.list_terrain_layers(
            project_paths.rasmap_path,
            ras_object=ras_object,
        )
        if terrain_layers.empty:
            raise ValueError(f"No terrain is registered in {project_paths.rasmap_path}")
        if len(terrain_layers) != 1:
            names = ", ".join(sorted(terrain_layers["name"].astype(str)))
            raise ValueError(
                "Registered-terrain sampling is ambiguous because "
                f"{len(terrain_layers)} terrains are registered ({names}). "
                "RasTerrainMod cannot select a terrain by name; export the intended "
                "terrain with RasTerrain.export_rasmapper_terrain() and pass it as "
                "terrain_raster."
            )

        records = {}
        for xs_id, record in source.records.items():
            reasons = set(record.reasons)
            line = RasTerrain._as_linestring(record.geometry)
            if line is None:
                reasons.add("MISSING_CUT_LINE")
                records[xs_id] = RasTerrainAgreement._empty_terrain_record(
                    record, reasons
                )
                continue
            coords = list(line.coords)
            sampled = RasTerrainMod.get_terrain_profile(
                project_paths.rasmap_path,
                geom_hdf_path,
                x_coords=[float(coord[0]) for coord in coords],
                y_coords=[float(coord[1]) for coord in coords],
                ras_object=ras_object,
            )
            sampled_array = RasTerrainAgreement._as_profile_array(sampled)
            source_profile = RasTerrainAgreement._prepare_profile(
                record.profile, "SOURCE"
            )
            if len(sampled_array) >= 2 and len(source_profile.interp_points) >= 2:
                native_min = float(np.nanmin(sampled_array[:, 0]))
                native_span = float(np.nanmax(sampled_array[:, 0]) - native_min)
                source_min = float(source_profile.interp_points[0, 0])
                source_span = float(
                    source_profile.interp_points[-1, 0]
                    - source_profile.interp_points[0, 0]
                )
                if native_span > 0:
                    sampled_array[:, 0] = (
                        source_min
                        + ((sampled_array[:, 0] - native_min) / native_span)
                        * source_span
                    )
            if len(sampled_array) < 2:
                reasons.add("TERRAIN_PROFILE_NO_VALID_SAMPLES")
            records[xs_id] = _ProfileRecord(
                xs_id=xs_id,
                profile=sampled_array,
                river=record.river,
                reach=record.reach,
                rs=record.rs,
                geometry=record.geometry,
                reasons=reasons,
            )

        return _ProfileCollection(dict(sorted(records.items())), source.crs)

    @staticmethod
    def _compare_collections(
        source: _ProfileCollection,
        terrain: _ProfileCollection,
        *,
        stages,
        comparison_interval,
        max_shift,
        default_stage_count,
        flag_thresholds,
        make_figures,
    ) -> TerrainAgreementResult:
        if comparison_interval is not None and comparison_interval <= 0:
            raise ValueError("comparison_interval must be greater than zero")
        if max_shift is not None and max_shift < 0:
            raise ValueError("max_shift cannot be negative")
        if int(default_stage_count) < 1:
            raise ValueError("default_stage_count must be at least one")

        thresholds = dict(DEFAULT_FLAG_THRESHOLDS)
        if flag_thresholds is not None:
            thresholds = dict(flag_thresholds)

        xs_rows = []
        stage_rows = []
        plot_data = {}
        for xs_id, src_record in source.records.items():
            terrain_record = terrain.records.get(xs_id)
            xs_row, rows, prepared = RasTerrainAgreement._compare_one(
                src_record,
                terrain_record,
                stages=RasTerrainAgreement._stages_for_xs(stages, xs_id),
                comparison_interval=comparison_interval,
                max_shift=max_shift,
                default_stage_count=int(default_stage_count),
                thresholds=thresholds,
            )
            xs_rows.append(xs_row)
            stage_rows.extend(rows)
            if prepared is not None:
                plot_data[xs_id] = prepared

        xs_df = pd.DataFrame(xs_rows, columns=XS_METRICS_COLUMNS)
        stage_df = pd.DataFrame(stage_rows, columns=STAGE_METRICS_COLUMNS)
        if not xs_df.empty:
            xs_df = xs_df.sort_values("xs_id", kind="stable").reset_index(drop=True)
        if not stage_df.empty:
            stage_df = stage_df.sort_values(
                ["xs_id", "stage"], kind="stable"
            ).reset_index(drop=True)
        flagged = xs_df.loc[xs_df["flagged"].fillna(False)].reset_index(drop=True)
        figures = RasTerrainAgreement._make_figures(plot_data) if make_figures else None
        return TerrainAgreementResult(
            xs_metrics_df=xs_df,
            stage_metrics_df=stage_df,
            model_summary=RasTerrainAgreement._summarize_model(xs_df, stage_df),
            flagged_xs=flagged,
            figures=figures,
        )

    @staticmethod
    def _compare_one(
        source_record: _ProfileRecord,
        terrain_record: Optional[_ProfileRecord],
        *,
        stages,
        comparison_interval,
        max_shift,
        default_stage_count,
        thresholds,
    ):
        base = RasTerrainAgreement._empty_xs_row(source_record)
        reasons = set(source_record.reasons)
        source = RasTerrainAgreement._prepare_profile(source_record.profile, "SOURCE")
        reasons.update(source.reasons)
        base["n_source_points"] = int(len(source.points))

        if terrain_record is None:
            reasons.add("MISSING_TERRAIN_PROFILE")
            return RasTerrainAgreement._finish_invalid(base, reasons), [], None

        reasons.update(terrain_record.reasons)
        terrain = RasTerrainAgreement._prepare_profile(
            terrain_record.profile, "TERRAIN"
        )
        reasons.update(terrain.reasons)
        base["n_terrain_points"] = int(len(terrain.points))

        if reasons & _INVALID_PROFILE_REASON_CODES:
            return RasTerrainAgreement._finish_invalid(base, reasons), [], None

        if len(source.interp_points) < 2 or len(terrain.interp_points) < 2:
            if len(source.interp_points) < 2:
                reasons.add("INSUFFICIENT_SOURCE_POINTS")
            if len(terrain.interp_points) < 2:
                reasons.add("INSUFFICIENT_TERRAIN_POINTS")
            return RasTerrainAgreement._finish_invalid(base, reasons), [], None

        source_min, source_max = source.interp_points[[0, -1], 0]
        terrain_min, terrain_max = terrain.interp_points[[0, -1], 0]
        overlap_min = max(source_min, terrain_min)
        overlap_max = min(source_max, terrain_max)
        overlap = float(overlap_max - overlap_min)
        source_span = float(source_max - source_min)
        coverage = overlap / source_span if source_span > 0 else np.nan
        base.update(
            {
                "source_station_min": float(source_min),
                "source_station_max": float(source_max),
                "terrain_station_min": float(terrain_min),
                "terrain_station_max": float(terrain_max),
                "station_overlap": max(0.0, overlap),
                "station_coverage_ratio": coverage,
            }
        )
        if overlap <= 0:
            reasons.add("NO_STATION_OVERLAP")
            return RasTerrainAgreement._finish_invalid(base, reasons), [], None

        src_clip = RasTerrainAgreement._clip_profile(
            source.points, overlap_min, overlap_max
        )
        terrain_clip = RasTerrainAgreement._clip_profile(
            terrain.points, overlap_min, overlap_max
        )
        grid = RasTerrainAgreement._comparison_grid(
            source.interp_points,
            terrain.interp_points,
            overlap_min,
            overlap_max,
            comparison_interval,
        )
        src_values = np.interp(
            grid, source.interp_points[:, 0], source.interp_points[:, 1]
        )
        terrain_values = np.interp(
            grid, terrain.interp_points[:, 0], terrain.interp_points[:, 1]
        )
        residual = src_values - terrain_values
        residual_metrics = RasTerrainAgreement._residual_metrics(
            residual,
            normalization_range=float(np.ptp(src_values)),
        )
        if not np.isfinite(residual_metrics["nrmse"]):
            reasons.add("ZERO_SOURCE_ELEVATION_RANGE")

        pearson, correlation_reason = RasTerrainAgreement._pearson(
            src_values, terrain_values
        )
        if correlation_reason:
            reasons.add(correlation_reason)
        max_corr, shift_distance = RasTerrainAgreement._shifted_correlation(
            grid,
            src_values,
            terrain.interp_points,
            max_shift=max_shift,
        )

        source_thalweg_index = int(np.argmin(src_clip[:, 1]))
        terrain_thalweg_index = int(np.argmin(terrain_clip[:, 1]))
        source_thalweg_elevation = float(src_clip[source_thalweg_index, 1])
        terrain_thalweg_elevation = float(terrain_clip[terrain_thalweg_index, 1])
        source_vertical_range = float(np.ptp(src_values))
        selected_stages = RasTerrainAgreement._resolve_stages(
            stages,
            src_clip,
            terrain_clip,
            default_stage_count,
        )
        if len(selected_stages) == 0:
            reasons.add("NO_VALID_STAGE_RANGE")

        stage_rows = [
            RasTerrainAgreement._stage_metrics(
                source_record,
                stage=float(stage),
                source_profile=src_clip,
                terrain_profile=terrain_clip,
                grid=grid,
                source_values=src_values,
                terrain_values=terrain_values,
                source_vertical_range=source_vertical_range,
            )
            for stage in selected_stages
        ]
        valid_stage_rows = [row for row in stage_rows if row["valid"]]

        base.update(
            {
                "n_comparison_points": int(len(grid)),
                "source_vertical_range": source_vertical_range,
                "source_thalweg_elevation": source_thalweg_elevation,
                "terrain_thalweg_elevation": terrain_thalweg_elevation,
                "thalweg_elevation_difference": (
                    source_thalweg_elevation - terrain_thalweg_elevation
                ),
                "source_thalweg_station": float(src_clip[source_thalweg_index, 0]),
                "terrain_thalweg_station": float(
                    terrain_clip[terrain_thalweg_index, 0]
                ),
                "thalweg_station_difference": float(
                    src_clip[source_thalweg_index, 0]
                    - terrain_clip[terrain_thalweg_index, 0]
                ),
                **residual_metrics,
                "pearson_correlation": pearson,
                "max_shifted_correlation": max_corr,
                "shift_distance": shift_distance,
                "stage_count": int(len(stage_rows)),
                "avg_inundation_overlap": RasTerrainAgreement._mean_rows(
                    valid_stage_rows, "inundation_overlap"
                ),
                "avg_top_width_agreement": RasTerrainAgreement._mean_rows(
                    valid_stage_rows, "top_width_agreement"
                ),
                "avg_flow_area_agreement": RasTerrainAgreement._mean_rows(
                    valid_stage_rows, "flow_area_agreement"
                ),
                "avg_flow_area_overlap": RasTerrainAgreement._mean_rows(
                    valid_stage_rows, "flow_area_overlap"
                ),
                "avg_hydraulic_radius_agreement": RasTerrainAgreement._mean_rows(
                    valid_stage_rows, "hydraulic_radius_agreement"
                ),
                "valid": True,
            }
        )
        flag_reasons = RasTerrainAgreement._flag_reasons(base, reasons, thresholds)
        base["reason_codes"] = RasTerrainAgreement._join_reasons(reasons)
        base["flag_reasons"] = RasTerrainAgreement._join_reasons(flag_reasons)
        base["flagged"] = bool(flag_reasons)
        return base, stage_rows, (source.points, terrain.points, selected_stages)

    @staticmethod
    def _stage_metrics(
        record: _ProfileRecord,
        *,
        stage: float,
        source_profile: np.ndarray,
        terrain_profile: np.ndarray,
        grid: np.ndarray,
        source_values: np.ndarray,
        terrain_values: np.ndarray,
        source_vertical_range: float,
    ) -> Dict[str, Any]:
        source_hyd = RasTerrainAgreement._hydraulic_properties(source_profile, stage)
        terrain_hyd = RasTerrainAgreement._hydraulic_properties(terrain_profile, stage)
        source_intervals = RasTerrainAgreement._wet_intervals(source_profile, stage)
        terrain_intervals = RasTerrainAgreement._wet_intervals(terrain_profile, stage)
        union_width = RasTerrainAgreement._interval_measure(
            RasTerrainAgreement._merge_intervals(source_intervals + terrain_intervals)
        )
        intersection_width = RasTerrainAgreement._interval_intersection_measure(
            source_intervals, terrain_intervals
        )
        reasons = set()
        if union_width <= 0:
            reasons.add("NO_INUNDATION_AT_STAGE")
            inundation_overlap = np.nan
        else:
            inundation_overlap = intersection_width / union_width

        flow_area_overlap = RasTerrainAgreement._flow_area_overlap(
            source_profile,
            terrain_profile,
            stage,
        )

        wet_mask = (source_values < stage) | (terrain_values < stage)
        if np.any(wet_mask):
            residual = source_values[wet_mask] - terrain_values[wet_mask]
            residual_metrics = RasTerrainAgreement._residual_metrics(
                residual, normalization_range=source_vertical_range
            )
        else:
            residual_metrics = RasTerrainAgreement._nan_residual_metrics()

        valid = bool(union_width > 0 and np.isfinite(flow_area_overlap))
        return {
            "xs_id": record.xs_id,
            "river": record.river,
            "reach": record.reach,
            "rs": record.rs,
            "stage": stage,
            "source_top_width": source_hyd["top_width"],
            "terrain_top_width": terrain_hyd["top_width"],
            "top_width_agreement": RasTerrainAgreement._agreement(
                source_hyd["top_width"], terrain_hyd["top_width"]
            ),
            "inundation_overlap": inundation_overlap,
            "source_flow_area": source_hyd["flow_area"],
            "terrain_flow_area": terrain_hyd["flow_area"],
            "flow_area_agreement": RasTerrainAgreement._agreement(
                source_hyd["flow_area"], terrain_hyd["flow_area"]
            ),
            "flow_area_overlap": flow_area_overlap,
            "source_wetted_perimeter": source_hyd["wetted_perimeter"],
            "terrain_wetted_perimeter": terrain_hyd["wetted_perimeter"],
            "source_hydraulic_radius": source_hyd["hydraulic_radius"],
            "terrain_hydraulic_radius": terrain_hyd["hydraulic_radius"],
            "hydraulic_radius_agreement": RasTerrainAgreement._agreement(
                source_hyd["hydraulic_radius"], terrain_hyd["hydraulic_radius"]
            ),
            **residual_metrics,
            "valid": valid,
            "reason_codes": RasTerrainAgreement._join_reasons(reasons),
        }

    @staticmethod
    def _prepare_profile(profile: np.ndarray, label: str) -> _PreparedProfile:
        values = np.asarray(profile, dtype=float)
        reasons = set()
        if values.ndim != 2 or values.shape[1] < 2:
            return _PreparedProfile(
                np.empty((0, 2), dtype=float),
                np.empty((0, 2), dtype=float),
                {f"INSUFFICIENT_{label}_POINTS"},
            )
        values = values[:, :2]
        finite = np.isfinite(values).all(axis=1)
        if not np.all(finite):
            reasons.add(f"NONFINITE_{label}_VALUES_DROPPED")
            values = values[finite]
        if len(values) == 0:
            return _PreparedProfile(values, values, reasons)
        values = values[np.argsort(values[:, 0], kind="stable")]
        if np.any(np.diff(values[:, 0]) == 0):
            reasons.add(f"DUPLICATE_{label}_STATIONS")
        # Preserve the lower side of vertical walls for signal interpolation.
        # The original duplicate points remain in ``points`` so piecewise
        # hydraulic calculations still retain the vertical segment itself.
        grouped = (
            pd.DataFrame(values, columns=["station", "elevation"])
            .groupby("station", sort=True, as_index=False)["elevation"]
            .min()
        )
        interp_points = grouped[["station", "elevation"]].to_numpy(dtype=float)
        if len(interp_points) >= 2 and interp_points[-1, 0] == interp_points[0, 0]:
            reasons.add(f"ZERO_{label}_STATION_SPAN")
        return _PreparedProfile(values, interp_points, reasons)

    @staticmethod
    def _comparison_grid(source, terrain, low, high, interval):
        if interval is not None:
            count = max(2, int(np.ceil((high - low) / interval)) + 1)
        else:
            count = max(101, len(source), len(terrain))
            count = min(count, 10001)
        return np.linspace(low, high, count)

    @staticmethod
    def _clip_profile(profile, low, high):
        prepared = RasTerrainAgreement._prepare_profile(profile, "PROFILE")
        interior = prepared.points[
            (prepared.points[:, 0] >= low) & (prepared.points[:, 0] <= high)
        ]
        endpoint_values = np.interp(
            [low, high], prepared.interp_points[:, 0], prepared.interp_points[:, 1]
        )
        combined = np.vstack(
            ([low, endpoint_values[0]], interior, [high, endpoint_values[1]])
        )
        return combined[np.argsort(combined[:, 0], kind="stable")]

    @staticmethod
    def _resolve_stages(stages, source, terrain, count):
        if stages is not None:
            values = np.asarray(stages, dtype=float).reshape(-1)
            return np.unique(values[np.isfinite(values)])

        low = max(float(np.min(source[:, 1])), float(np.min(terrain[:, 1])))
        high = min(
            float(min(source[0, 1], source[-1, 1])),
            float(min(terrain[0, 1], terrain[-1, 1])),
        )
        if high <= low:
            high = min(float(np.max(source[:, 1])), float(np.max(terrain[:, 1])))
        if high <= low:
            return np.asarray([], dtype=float)
        increment = (high - low) / count
        return np.linspace(low + increment, high, count)

    @staticmethod
    def _hydraulic_properties(profile, stage):
        flow_area = 0.0
        wetted_perimeter = 0.0
        for (x1, z1), (x2, z2) in zip(profile[:-1], profile[1:]):
            dx = float(x2 - x1)
            dz = float(z2 - z1)
            d1 = max(float(stage - z1), 0.0)
            d2 = max(float(stage - z2), 0.0)
            if d1 == 0.0 and d2 == 0.0:
                continue
            if (z1 < stage) == (z2 < stage):
                wet_fraction = 1.0
            elif z1 == z2:
                wet_fraction = 0.0
            else:
                wet_fraction = abs(float((stage - (z1 if z1 < stage else z2)) / dz))
                wet_fraction = min(1.0, max(0.0, wet_fraction))
            if d1 > 0.0 and d2 > 0.0:
                flow_area += 0.5 * (d1 + d2) * abs(dx)
            else:
                # Only the wet fraction of a crossing segment contributes.
                # Its depth varies linearly from the wet endpoint to zero at
                # the stage intersection, forming a triangle.
                flow_area += 0.5 * max(d1, d2) * abs(dx) * wet_fraction
            wetted_perimeter += wet_fraction * float(np.hypot(dx, dz))
        intervals = RasTerrainAgreement._wet_intervals(profile, stage)
        top_width = RasTerrainAgreement._interval_measure(intervals)
        radius = flow_area / wetted_perimeter if wetted_perimeter > 0 else 0.0
        return {
            "top_width": float(top_width),
            "flow_area": float(flow_area),
            "wetted_perimeter": float(wetted_perimeter),
            "hydraulic_radius": float(radius),
        }

    @staticmethod
    def _flow_area_overlap(source_profile, terrain_profile, stage):
        """Return the exact piecewise-linear flow-area overlap ratio."""
        source = RasTerrainAgreement._prepare_profile(
            source_profile, "SOURCE"
        ).interp_points
        terrain = RasTerrainAgreement._prepare_profile(
            terrain_profile, "TERRAIN"
        ).interp_points
        low = max(float(source[0, 0]), float(terrain[0, 0]))
        high = min(float(source[-1, 0]), float(terrain[-1, 0]))
        stations = np.unique(
            np.concatenate(
                (
                    [low, high],
                    source[(source[:, 0] > low) & (source[:, 0] < high), 0],
                    terrain[(terrain[:, 0] > low) & (terrain[:, 0] < high), 0],
                )
            )
        )

        # At waterline crossings depth changes slope, so include those roots.
        source_z = np.interp(stations, source[:, 0], source[:, 1])
        terrain_z = np.interp(stations, terrain[:, 0], terrain[:, 1])
        waterline_roots = []
        for elevations in (source_z, terrain_z):
            for index in range(len(stations) - 1):
                first = float(elevations[index] - stage)
                second = float(elevations[index + 1] - stage)
                if first * second < 0:
                    fraction = -first / (second - first)
                    waterline_roots.append(
                        float(
                            stations[index]
                            + fraction * (stations[index + 1] - stations[index])
                        )
                    )
        if waterline_roots:
            stations = np.unique(np.concatenate((stations, waterline_roots)))

        source_depth = np.maximum(
            stage - np.interp(stations, source[:, 0], source[:, 1]), 0.0
        )
        terrain_depth = np.maximum(
            stage - np.interp(stations, terrain[:, 0], terrain[:, 1]), 0.0
        )

        # Where the profiles cross, the min/max depth functions switch.
        difference = source_depth - terrain_depth
        profile_roots = []
        for index in range(len(stations) - 1):
            first = float(difference[index])
            second = float(difference[index + 1])
            if first * second < 0:
                fraction = -first / (second - first)
                profile_roots.append(
                    float(
                        stations[index]
                        + fraction * (stations[index + 1] - stations[index])
                    )
                )
        if profile_roots:
            stations = np.unique(np.concatenate((stations, profile_roots)))
            source_depth = np.maximum(
                stage - np.interp(stations, source[:, 0], source[:, 1]), 0.0
            )
            terrain_depth = np.maximum(
                stage - np.interp(stations, terrain[:, 0], terrain[:, 1]), 0.0
            )

        union_area = RasTerrainAgreement._integrate(
            np.maximum(source_depth, terrain_depth), stations
        )
        if union_area <= 0:
            return np.nan
        intersection_area = RasTerrainAgreement._integrate(
            np.minimum(source_depth, terrain_depth), stations
        )
        return float(intersection_area / union_area)

    @staticmethod
    def _integrate(values, stations):
        trapezoid = getattr(np, "trapezoid", None)
        if trapezoid is None:
            trapezoid = np.trapz
        return float(trapezoid(values, stations))

    @staticmethod
    def _wet_intervals(profile, stage):
        intervals = []
        for (x1, z1), (x2, z2) in zip(profile[:-1], profile[1:]):
            if x1 == x2:
                continue
            wet1 = z1 < stage
            wet2 = z2 < stage
            if wet1 and wet2:
                intervals.append((float(min(x1, x2)), float(max(x1, x2))))
            elif wet1 != wet2 and z1 != z2:
                intersection = float(x1 + (stage - z1) * (x2 - x1) / (z2 - z1))
                wet_x = float(x1 if wet1 else x2)
                intervals.append((min(wet_x, intersection), max(wet_x, intersection)))
        return RasTerrainAgreement._merge_intervals(intervals)

    @staticmethod
    def _merge_intervals(intervals):
        cleaned = sorted((float(a), float(b)) for a, b in intervals if b > a)
        merged = []
        for start, end in cleaned:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        return [(start, end) for start, end in merged]

    @staticmethod
    def _interval_measure(intervals):
        return float(sum(end - start for start, end in intervals))

    @staticmethod
    def _interval_intersection_measure(first, second):
        first = RasTerrainAgreement._merge_intervals(first)
        second = RasTerrainAgreement._merge_intervals(second)
        total = 0.0
        i = j = 0
        while i < len(first) and j < len(second):
            low = max(first[i][0], second[j][0])
            high = min(first[i][1], second[j][1])
            total += max(0.0, high - low)
            if first[i][1] < second[j][1]:
                i += 1
            else:
                j += 1
        return float(total)

    @staticmethod
    def _residual_metrics(residual, normalization_range):
        residual = np.asarray(residual, dtype=float)
        residual = residual[np.isfinite(residual)]
        if len(residual) == 0:
            return RasTerrainAgreement._nan_residual_metrics()
        rmse = float(np.sqrt(np.mean(np.square(residual))))
        return {
            "residual_mean": float(np.mean(residual)),
            "residual_std": float(np.std(residual)),
            "residual_min": float(np.min(residual)),
            "residual_max": float(np.max(residual)),
            "residual_p25": float(np.percentile(residual, 25)),
            "residual_p50": float(np.percentile(residual, 50)),
            "residual_p75": float(np.percentile(residual, 75)),
            "rmse": rmse,
            "nrmse": rmse / normalization_range if normalization_range > 0 else np.nan,
        }

    @staticmethod
    def _nan_residual_metrics():
        return {
            "residual_mean": np.nan,
            "residual_std": np.nan,
            "residual_min": np.nan,
            "residual_max": np.nan,
            "residual_p25": np.nan,
            "residual_p50": np.nan,
            "residual_p75": np.nan,
            "rmse": np.nan,
            "nrmse": np.nan,
        }

    @staticmethod
    def _pearson(first, second):
        first = np.asarray(first, dtype=float)
        second = np.asarray(second, dtype=float)
        finite = np.isfinite(first) & np.isfinite(second)
        first = first[finite]
        second = second[finite]
        if len(first) < 3:
            return np.nan, "INSUFFICIENT_CORRELATION_POINTS"
        first_std = float(np.std(first))
        second_std = float(np.std(second))
        if first_std == 0 or second_std == 0:
            if first_std == 0 and second_std == 0 and np.allclose(first, second):
                return 1.0, None
            return np.nan, "ZERO_VARIANCE_PROFILE"
        return float(np.corrcoef(first, second)[0, 1]), None

    @staticmethod
    def _shifted_correlation(grid, source_values, terrain_points, max_shift):
        if len(grid) < 3:
            return np.nan, np.nan
        step = float(np.median(np.diff(grid)))
        if not np.isfinite(step) or step <= 0:
            return np.nan, np.nan
        span = float(grid[-1] - grid[0])
        limit = min(span * 0.25, max_shift) if max_shift is not None else span * 0.25
        shift_count = int(np.floor(limit / step))
        shifts = np.arange(-shift_count, shift_count + 1, dtype=float) * step
        candidates = []
        for shift in shifts:
            terrain_query = grid - shift
            valid = (terrain_query >= terrain_points[0, 0]) & (
                terrain_query <= terrain_points[-1, 0]
            )
            if int(np.sum(valid)) < 3:
                continue
            shifted = np.interp(
                terrain_query[valid], terrain_points[:, 0], terrain_points[:, 1]
            )
            corr, _ = RasTerrainAgreement._pearson(source_values[valid], shifted)
            if np.isfinite(corr):
                candidates.append((float(corr), float(shift)))
        if not candidates:
            return np.nan, np.nan
        best = max(candidates, key=lambda item: (item[0], -abs(item[1]), -item[1]))
        return best

    @staticmethod
    def _agreement(first, second):
        if not np.isfinite(first) or not np.isfinite(second):
            return np.nan
        denominator = abs(first) + abs(second)
        if denominator == 0:
            return 1.0
        return float(np.clip(1.0 - abs(first - second) / denominator, 0.0, 1.0))

    @staticmethod
    def _flag_reasons(row, reasons, thresholds):
        flags = set(reasons) & _SERIOUS_REASON_CODES
        checks = (
            (
                "max_nrmse",
                row["nrmse"],
                lambda value, limit: value > limit,
                "NRMSE_HIGH",
            ),
            (
                "min_pearson_correlation",
                row["pearson_correlation"],
                lambda value, limit: value < limit,
                "PEARSON_CORRELATION_LOW",
            ),
            (
                "min_inundation_overlap",
                row["avg_inundation_overlap"],
                lambda value, limit: value < limit,
                "INUNDATION_OVERLAP_LOW",
            ),
            (
                "min_flow_area_overlap",
                row["avg_flow_area_overlap"],
                lambda value, limit: value < limit,
                "FLOW_AREA_OVERLAP_LOW",
            ),
            (
                "min_station_coverage_ratio",
                row["station_coverage_ratio"],
                lambda value, limit: value < limit,
                "STATION_COVERAGE_LOW",
            ),
        )
        for key, value, comparison, reason in checks:
            if (
                key in thresholds
                and np.isfinite(value)
                and comparison(value, thresholds[key])
            ):
                flags.add(reason)
        key = "max_abs_normalized_thalweg_difference"
        if key in thresholds and row["source_vertical_range"] > 0:
            normalized = (
                abs(row["thalweg_elevation_difference"]) / row["source_vertical_range"]
            )
            if normalized > thresholds[key]:
                flags.add("THALWEG_DIFFERENCE_HIGH")
        return flags

    @staticmethod
    def _summarize_model(xs_df, stage_df):
        summary = {
            "cross_section_count": int(len(xs_df)),
            "valid_cross_section_count": int(xs_df["valid"].fillna(False).sum())
            if not xs_df.empty
            else 0,
            "flagged_cross_section_count": int(xs_df["flagged"].fillna(False).sum())
            if not xs_df.empty
            else 0,
            "stage_count": int(len(stage_df)),
            "valid_stage_count": int(stage_df["valid"].fillna(False).sum())
            if not stage_df.empty
            else 0,
        }
        aggregate_columns = [
            "rmse",
            "nrmse",
            "thalweg_elevation_difference",
            "pearson_correlation",
            "max_shifted_correlation",
            "avg_inundation_overlap",
            "avg_top_width_agreement",
            "avg_flow_area_agreement",
            "avg_flow_area_overlap",
            "avg_hydraulic_radius_agreement",
        ]
        for column in aggregate_columns:
            values = pd.to_numeric(
                xs_df.get(column, pd.Series(dtype=float)), errors="coerce"
            )
            finite = values[np.isfinite(values)]
            summary[f"mean_{column}"] = float(finite.mean()) if len(finite) else np.nan
            summary[f"median_{column}"] = (
                float(finite.median()) if len(finite) else np.nan
            )
        reason_counts = Counter()
        if not xs_df.empty:
            for value in xs_df["reason_codes"].fillna(""):
                reason_counts.update(reason for reason in value.split(";") if reason)
        summary["reason_counts"] = dict(sorted(reason_counts.items()))
        return summary

    @staticmethod
    def _make_figures(plot_data):
        try:
            import matplotlib.pyplot as plt
        except ImportError as exc:
            raise ImportError("matplotlib is required when make_figures=True") from exc
        figures = {}
        for xs_id in sorted(plot_data):
            source, terrain, stages = plot_data[xs_id]
            figure, axis = plt.subplots(figsize=(9, 4.5))
            axis.plot(source[:, 0], source[:, 1], label="Geometry", linewidth=1.6)
            axis.plot(terrain[:, 0], terrain[:, 1], label="Terrain", linewidth=1.2)
            for stage in stages:
                axis.axhline(stage, color="0.8", linewidth=0.5, zorder=0)
            axis.set(title=xs_id, xlabel="Station", ylabel="Elevation")
            axis.legend()
            axis.grid(alpha=0.2)
            figure.tight_layout()
            figures[xs_id] = figure
        return figures

    @staticmethod
    def _as_profile_array(profile):
        if profile is None:
            return np.empty((0, 2), dtype=float)
        if isinstance(profile, pd.DataFrame):
            lower = {str(column).lower(): column for column in profile.columns}
            station = lower.get("station")
            elevation = lower.get("elevation")
            if station is None or elevation is None:
                raise ValueError(
                    "Profile DataFrames require Station/station and Elevation/elevation columns"
                )
            return profile[[station, elevation]].to_numpy(dtype=float)
        values = np.asarray(profile, dtype=float)
        if values.ndim != 2 or values.shape[1] < 2:
            raise ValueError("Station/elevation profiles must be Nx2 arrays")
        return values[:, :2]

    @staticmethod
    def _first_present(values, names, default=...):
        for name in names:
            if name in values and values[name] is not None:
                return values[name]
        if default is not ...:
            return default
        raise ValueError(f"Required profile field not found; expected one of {names}")

    @staticmethod
    def _make_xs_id(river, reach, rs):
        return f"{river}|{reach}|{rs}"

    @staticmethod
    def _stages_for_xs(stages, xs_id):
        if isinstance(stages, Mapping):
            return stages.get(xs_id)
        return stages

    @staticmethod
    def _empty_terrain_record(source, reasons):
        return _ProfileRecord(
            xs_id=source.xs_id,
            profile=np.empty((0, 2), dtype=float),
            river=source.river,
            reach=source.reach,
            rs=source.rs,
            geometry=source.geometry,
            reasons=reasons,
        )

    @staticmethod
    def _empty_xs_row(record):
        row = {column: np.nan for column in XS_METRICS_COLUMNS}
        row.update(
            {
                "xs_id": record.xs_id,
                "river": record.river,
                "reach": record.reach,
                "rs": record.rs,
                "n_source_points": 0,
                "n_terrain_points": 0,
                "n_comparison_points": 0,
                "stage_count": 0,
                "valid": False,
                "reason_codes": "",
                "flagged": True,
                "flag_reasons": "",
            }
        )
        return row

    @staticmethod
    def _finish_invalid(row, reasons):
        row["valid"] = False
        row["reason_codes"] = RasTerrainAgreement._join_reasons(reasons)
        row["flagged"] = True
        row["flag_reasons"] = RasTerrainAgreement._join_reasons(reasons)
        return row

    @staticmethod
    def _join_reasons(reasons):
        return ";".join(sorted(reason for reason in reasons if reason))

    @staticmethod
    def _mean_rows(rows, column):
        values = np.asarray([row[column] for row in rows], dtype=float)
        values = values[np.isfinite(values)]
        return float(np.mean(values)) if len(values) else np.nan


__all__ = [
    "RasTerrainAgreement",
    "TerrainAgreementResult",
    "XS_METRICS_COLUMNS",
    "STAGE_METRICS_COLUMNS",
]
