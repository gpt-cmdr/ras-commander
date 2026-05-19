"""
ManningsFromLandCover - 1D Manning's n assignment from NLCD rasters.

This module samples land-cover raster values along cross-section GIS cut lines,
maps NLCD classes to Manning's n values, applies spatial calibration overrides,
and writes HEC-RAS-compatible horizontal variation blocks.
"""

from pathlib import Path
from collections.abc import Iterable as IterableABC, Mapping as MappingABC
import math
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

import numpy as np
import pandas as pd

from ..Decorators import log_call
from ..LoggingConfig import get_logger
from .GeomCrossSection import GeomCrossSection
from .GeomLandCover import GeomLandCover
from .GeomParser import GeomParser

logger = get_logger(__name__)


class ManningsFromLandCover:
    """
    Assign 1D cross-section Manning's n values from NLCD land-cover rasters.

    All methods are static and designed to be used without instantiation.
    """

    DEFAULT_MAX_BLOCKS = 20

    DEFAULT_NLCD_MANNINGS = {
        11: ("Open Water", 0.025),
        12: ("Perennial Ice/Snow", 0.030),
        21: ("Developed, Open Space", 0.040),
        22: ("Developed, Low Intensity", 0.065),
        23: ("Developed, Medium Intensity", 0.090),
        24: ("Developed, High Intensity", 0.120),
        31: ("Barren Land", 0.035),
        41: ("Deciduous Forest", 0.120),
        42: ("Evergreen Forest", 0.140),
        43: ("Mixed Forest", 0.130),
        51: ("Dwarf Scrub", 0.080),
        52: ("Shrub/Scrub", 0.080),
        71: ("Grassland/Herbaceous", 0.040),
        72: ("Sedge/Herbaceous", 0.045),
        73: ("Lichens", 0.040),
        74: ("Moss", 0.050),
        81: ("Pasture/Hay", 0.035),
        82: ("Cultivated Crops", 0.040),
        90: ("Woody Wetlands", 0.100),
        95: ("Emergent Herbaceous Wetlands", 0.070),
    }

    _N_VALUE_COLUMNS = (
        "n_value",
        "mannings_n",
        "ManningsN",
        "MainChannel",
        "Base Mannings n Value",
        "Base Manning's n Value",
        "Manning's n",
        "Mannings n",
    )
    _CODE_COLUMNS = (
        "nlcd_code",
        "NLCD Code",
        "land_cover_code",
        "Land Cover Code",
        "code",
        "Code",
        "pixel_value",
        "ID",
    )
    _NAME_COLUMNS = (
        "land_cover_name",
        "Land Cover Name",
        "class_name",
        "Class Name",
        "Name",
        "Region Name",
    )
    _PREVIEW_COLUMNS = [
        "River",
        "Reach",
        "RS",
        "Station",
        "EndStation",
        "n_value",
        "Subsection",
        "raw_block_count",
        "final_block_count",
        "sample_count",
        "area_weight",
        "nlcd_codes",
        "sources",
        "merged_count",
    ]

    @staticmethod
    @log_call
    def assign(
        geometry_path: Union[str, Path],
        land_cover_raster: Union[str, Path],
        mannings_table: Optional[Any] = None,
        calibration_regions: Optional[Any] = None,
        max_blocks: int = DEFAULT_MAX_BLOCKS,
    ) -> dict:
        """
        Assign Manning's n values to all matching 1D cross sections.

        Args:
            geometry_path: HEC-RAS text geometry file path (``.g##``).
            land_cover_raster: NLCD GeoTIFF path. A land-cover sidecar HDF may
                also be supplied; the matching TIF is resolved automatically.
            mannings_table: Optional mapping/DataFrame overriding the built-in
                NLCD code to Manning's n table.
            calibration_regions: Optional polygon overrides. Accepts a
                GeoDataFrame/DataFrame, list of dicts, or a dict with
                ``land_cover`` and ``geometry`` entries.
            max_blocks: Maximum Manning's n blocks per cross section. HEC-RAS
                6.6 rejects 21 or more, so the default is 20.

        Returns:
            dict with summary counts and the preview DataFrame that was written.
        """
        max_blocks = ManningsFromLandCover._validate_max_blocks(max_blocks)
        geometry_path = Path(geometry_path)

        preview_df = ManningsFromLandCover.preview(
            geometry_path,
            land_cover_raster,
            xs_id=None,
            mannings_table=mannings_table,
            calibration_regions=calibration_regions,
            max_blocks=max_blocks,
        )

        processed = 0
        for (river, reach, rs), xs_blocks in preview_df.groupby(["River", "Reach", "RS"], sort=False):
            write_df = xs_blocks.sort_values("Station")[["Station", "n_value", "Subsection"]].copy()
            GeomCrossSection.set_mannings_n(
                geometry_path,
                str(river),
                str(reach),
                str(rs),
                write_df,
            )
            processed += 1

        all_xs_count = len(GeomCrossSection.get_cross_sections(geometry_path))
        return {
            "geometry_path": str(geometry_path),
            "land_cover_raster": str(ManningsFromLandCover._resolve_land_cover_input(land_cover_raster)[0]),
            "max_blocks": max_blocks,
            "cross_sections_total": all_xs_count,
            "cross_sections_processed": processed,
            "cross_sections_skipped": max(all_xs_count - processed, 0),
            "blocks_written": int(len(preview_df)),
            "details": preview_df,
        }

    @staticmethod
    @log_call
    def preview(
        geometry_path: Union[str, Path],
        land_cover_raster: Union[str, Path],
        xs_id: Optional[Any] = None,
        mannings_table: Optional[Any] = None,
        calibration_regions: Optional[Any] = None,
        max_blocks: int = DEFAULT_MAX_BLOCKS,
    ) -> pd.DataFrame:
        """
        Preview Manning's n blocks generated from land-cover sampling.

        Args:
            geometry_path: HEC-RAS text geometry file path (``.g##``).
            land_cover_raster: NLCD GeoTIFF path or land-cover sidecar HDF.
            xs_id: Optional cross-section identifier. Accepts unique RS,
                ``river|reach|rs``, ``(river, reach, rs)``, or a mapping.
            mannings_table: Optional base table override.
            calibration_regions: Optional polygon override definitions.
            max_blocks: Maximum block count to enforce in the preview.

        Returns:
            DataFrame with one row per final Manning's n breakpoint.
        """
        max_blocks = ManningsFromLandCover._validate_max_blocks(max_blocks)
        geometry_path = Path(geometry_path)
        if not geometry_path.exists():
            raise FileNotFoundError(f"Geometry file not found: {geometry_path}")

        raster_path, landcover_hdf_path = ManningsFromLandCover._resolve_land_cover_input(
            land_cover_raster
        )
        code_to_n, code_to_name = ManningsFromLandCover._resolve_mannings_lookup(
            geometry_path,
            mannings_table,
        )

        try:
            import rasterio
        except ImportError as exc:
            raise ImportError(
                "rasterio is required for Manning's n assignment from land cover."
            ) from exc

        cut_lines = GeomParser.get_xs_cut_lines(geometry_path)
        if xs_id is not None:
            xs_df = GeomCrossSection.get_cross_sections(geometry_path)
            river, reach, rs = GeomCrossSection._resolve_xs_identifier(xs_id, xs_df)
            cut_lines = cut_lines[
                (cut_lines["river"].astype(str) == river)
                & (cut_lines["reach"].astype(str) == reach)
                & (cut_lines["station"].astype(str) == rs)
            ]

        rows = []
        with rasterio.open(raster_path) as src:
            regions = []
            regions.extend(
                ManningsFromLandCover._load_land_cover_sidecar_regions(
                    landcover_hdf_path,
                    src.crs,
                    code_to_n,
                    code_to_name,
                )
            )
            regions.extend(
                ManningsFromLandCover._coerce_calibration_regions(
                    calibration_regions,
                    src.crs,
                    code_to_n,
                    code_to_name,
                    default_source="geometry",
                )
            )
            regions.extend(
                ManningsFromLandCover._load_geometry_hdf_regions(
                    geometry_path,
                    src.crs,
                    code_to_n,
                    code_to_name,
                )
            )

            for _, xs_row in cut_lines.iterrows():
                river = str(xs_row["river"])
                reach = str(xs_row["reach"])
                rs = str(xs_row["station"])

                try:
                    sta_elev = GeomCrossSection.get_station_elevation(
                        geometry_path,
                        river,
                        reach,
                        rs,
                    )
                except ValueError as exc:
                    logger.warning(f"Skipping {river}/{reach}/RS {rs}: {exc}")
                    continue

                if sta_elev.empty:
                    logger.warning(f"Skipping {river}/{reach}/RS {rs}: empty station/elevation data")
                    continue

                banks = GeomCrossSection.get_bank_stations(
                    geometry_path,
                    river,
                    reach,
                    rs,
                )
                samples = ManningsFromLandCover._sample_cross_section(
                    src,
                    xs_row["geometry"],
                    sta_elev,
                    code_to_n,
                    code_to_name,
                    regions,
                )
                if samples.empty:
                    logger.warning(f"Skipping {river}/{reach}/RS {rs}: no valid land-cover samples")
                    continue

                blocks, raw_block_count = ManningsFromLandCover._samples_to_blocks(
                    samples,
                    sta_elev,
                    banks,
                    max_blocks,
                )
                for block in blocks:
                    rows.append({
                        "River": river,
                        "Reach": reach,
                        "RS": rs,
                        "Station": block["start_station"],
                        "EndStation": block["end_station"],
                        "n_value": block["n_value"],
                        "Subsection": block["subsection"],
                        "raw_block_count": raw_block_count,
                        "final_block_count": len(blocks),
                        "sample_count": len(samples),
                        "area_weight": block["area"],
                        "nlcd_codes": ",".join(str(c) for c in sorted(block["codes"])),
                        "sources": ",".join(sorted(block["sources"])),
                        "merged_count": block["merged_count"],
                    })

        if not rows:
            return pd.DataFrame(columns=ManningsFromLandCover._PREVIEW_COLUMNS)

        return pd.DataFrame(rows, columns=ManningsFromLandCover._PREVIEW_COLUMNS)

    @staticmethod
    @log_call
    def default_mannings_table() -> pd.DataFrame:
        """Return the built-in NLCD to Manning's n lookup table."""
        return pd.DataFrame([
            {
                "nlcd_code": code,
                "land_cover_name": name,
                "n_value": n_value,
            }
            for code, (name, n_value) in sorted(
                ManningsFromLandCover.DEFAULT_NLCD_MANNINGS.items()
            )
        ])

    @staticmethod
    @log_call
    def default_landcover_classification_table(
        percent_impervious: Optional[Mapping[int, float]] = None,
        sanitize_names: bool = True,
    ) -> pd.DataFrame:
        """
        Return the built-in NLCD table in ``RasMap.add_landcover_layer()`` shape.

        The returned DataFrame maps source NLCD raster values to the HEC-RAS
        land-cover sidecar class ID, class name, and starter Manning's n value.
        ``percent_impervious`` may override the optional sidecar percent
        impervious field by NLCD code. By default class names are sanitized for
        RASMapper sidecar authoring because RAS rejects ``/`` and ``\\`` in
        land-cover classifications.
        """
        percent_lookup = {
            int(code): float(value)
            for code, value in (percent_impervious or {}).items()
        }
        rows = []
        for code, (class_name, n_value) in sorted(
            ManningsFromLandCover.DEFAULT_NLCD_MANNINGS.items()
        ):
            rows.append(
                {
                    "source_value": int(code),
                    "class_id": int(code),
                    "class_name": (
                        str(class_name).replace("/", "-").replace("\\", "-")
                        if sanitize_names
                        else str(class_name)
                    ),
                    "mannings_n": float(n_value),
                    "percent_impervious": percent_lookup.get(int(code), 0.0),
                }
            )
        return pd.DataFrame(
            rows,
            columns=[
                "source_value",
                "class_id",
                "class_name",
                "mannings_n",
                "percent_impervious",
            ],
        )

    @staticmethod
    def _validate_max_blocks(max_blocks: int) -> int:
        max_blocks = int(max_blocks)
        if max_blocks < 1:
            raise ValueError("max_blocks must be at least 1")
        return max_blocks

    @staticmethod
    def _resolve_land_cover_input(land_cover_raster: Union[str, Path]) -> Tuple[Path, Optional[Path]]:
        source_path = Path(land_cover_raster)
        suffix = source_path.suffix.lower()

        if suffix in {".hdf", ".h5"}:
            hdf_path = source_path
            if not hdf_path.exists():
                raise FileNotFoundError(f"Land cover HDF not found: {hdf_path}")
            candidates = [hdf_path.with_suffix(".tif")]
            candidates.extend(sorted(hdf_path.parent.glob(f"{hdf_path.stem}*.tif")))
            for candidate in candidates:
                if candidate.exists():
                    return candidate, hdf_path
            raise FileNotFoundError(f"Land cover TIF not found for sidecar: {hdf_path}")

        raster_path = source_path
        if not raster_path.exists():
            raise FileNotFoundError(f"Land cover raster not found: {raster_path}")

        hdf_path = raster_path.with_suffix(".hdf")
        return raster_path, hdf_path if hdf_path.exists() else None

    @staticmethod
    def _resolve_mannings_lookup(
        geometry_path: Path,
        mannings_table: Optional[Any],
    ) -> Tuple[Dict[int, float], Dict[int, str]]:
        base_df = ManningsFromLandCover.default_mannings_table()
        code_to_n = {
            int(row["nlcd_code"]): float(row["n_value"])
            for _, row in base_df.iterrows()
        }
        code_to_name = {
            int(row["nlcd_code"]): str(row["land_cover_name"])
            for _, row in base_df.iterrows()
        }

        try:
            geom_base = GeomLandCover.get_base_mannings_n(geometry_path)
        except Exception as exc:
            logger.debug(f"Could not read geometry base Manning's n table: {exc}")
            geom_base = pd.DataFrame()

        if not geom_base.empty:
            ManningsFromLandCover._apply_table_override(
                geom_base,
                code_to_n,
                code_to_name,
                replace_names=False,
            )

        if mannings_table is not None:
            ManningsFromLandCover._apply_table_override(
                mannings_table,
                code_to_n,
                code_to_name,
                replace_names=True,
            )

        return code_to_n, code_to_name

    @staticmethod
    def _apply_table_override(
        table: Any,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
        replace_names: bool,
    ) -> None:
        if isinstance(table, MappingABC):
            for key, value in table.items():
                code = ManningsFromLandCover._nlcd_code_from_value(key, code_to_name)
                name = code_to_name.get(code, str(key)) if code is not None else str(key)
                n_value = value
                if isinstance(value, MappingABC):
                    n_value = ManningsFromLandCover._first_present(value, ManningsFromLandCover._N_VALUE_COLUMNS)
                    name = str(
                        ManningsFromLandCover._first_present(
                            value,
                            ManningsFromLandCover._NAME_COLUMNS,
                            default=name,
                        )
                    )
                if code is None:
                    continue
                code_to_n[int(code)] = float(n_value)
                if replace_names:
                    code_to_name[int(code)] = name
            return

        df = pd.DataFrame(table).copy()
        if df.empty:
            return

        for _, row in df.iterrows():
            row_dict = row.to_dict()
            raw_code = ManningsFromLandCover._first_present(
                row_dict,
                ManningsFromLandCover._CODE_COLUMNS,
            )
            raw_name = ManningsFromLandCover._first_present(
                row_dict,
                ManningsFromLandCover._NAME_COLUMNS,
            )
            n_value = ManningsFromLandCover._first_present(
                row_dict,
                ManningsFromLandCover._N_VALUE_COLUMNS,
            )
            if n_value is None:
                continue

            code = ManningsFromLandCover._nlcd_code_from_value(
                raw_code if raw_code is not None else raw_name,
                code_to_name,
            )
            if code is None:
                continue

            code_to_n[int(code)] = float(n_value)
            if replace_names and raw_name is not None:
                code_to_name[int(code)] = str(raw_name)

    @staticmethod
    def _load_land_cover_sidecar_regions(
        landcover_hdf_path: Optional[Path],
        raster_crs: Any,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
    ) -> List[dict]:
        if landcover_hdf_path is None or not Path(landcover_hdf_path).exists():
            return []

        try:
            from ..hdf.HdfLandCover import HdfLandCover
            polygons = HdfLandCover.get_classification_polygons(landcover_hdf_path)
            raster_map = HdfLandCover.get_landcover_raster_map(landcover_hdf_path)
        except Exception as exc:
            logger.debug(f"Could not read land-cover sidecar regions: {exc}")
            return []

        if polygons is None or len(polygons) == 0:
            return []

        class_to_n = {}
        if raster_map is not None and len(raster_map) > 0:
            for _, row in raster_map.iterrows():
                class_to_n[str(row["class_name"])] = float(row["mannings_n"])

        polygons = polygons.copy()
        if class_to_n and "n_value" not in polygons.columns:
            polygons["n_value"] = polygons["class_name"].map(class_to_n)

        return ManningsFromLandCover._coerce_calibration_regions(
            polygons,
            raster_crs,
            code_to_n,
            code_to_name,
            default_source="land_cover",
        )

    @staticmethod
    def _load_geometry_hdf_regions(
        geometry_path: Path,
        raster_crs: Any,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
    ) -> List[dict]:
        geom_hdf = Path(str(geometry_path) + ".hdf")
        if not geom_hdf.exists():
            return []

        try:
            from ..hdf.HdfLandCover import HdfLandCover
            cal_table = HdfLandCover.get_mannings_calibration_table(geom_hdf)
            region_polygons = HdfLandCover.get_mannings_region_polygons(geom_hdf)
        except Exception as exc:
            logger.debug(f"Could not read geometry HDF calibration regions: {exc}")
            return []

        if cal_table is None or cal_table.empty or region_polygons is None or len(region_polygons) == 0:
            return []

        land_cover_col = "Land Cover Name"
        base_col = "Base Manning's n Value"
        region_columns = [
            col for col in cal_table.columns
            if col not in {land_cover_col, base_col}
        ]
        rows = []
        for _, region_row in region_polygons.iterrows():
            region_name = str(region_row["Name"])
            if region_name not in region_columns:
                continue
            for _, cal_row in cal_table.iterrows():
                n_value = float(cal_row[region_name])
                if n_value <= 0:
                    continue
                rows.append({
                    "geometry": region_row["geometry"],
                    "Region Name": region_name,
                    "Land Cover Name": cal_row[land_cover_col],
                    "n_value": n_value,
                    "source": "geometry",
                })

        return ManningsFromLandCover._coerce_calibration_regions(
            pd.DataFrame(rows),
            raster_crs,
            code_to_n,
            code_to_name,
            default_source="geometry",
        )

    @staticmethod
    def _coerce_calibration_regions(
        calibration_regions: Optional[Any],
        raster_crs: Any,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
        default_source: str,
    ) -> List[dict]:
        if calibration_regions is None:
            return []

        regions = []

        source_map = {
            "land_cover": "land_cover",
            "landcover": "land_cover",
            "land_cover_regions": "land_cover",
            "geometry": "geometry",
            "geometry_regions": "geometry",
        }
        if (
            isinstance(calibration_regions, MappingABC)
            and set(calibration_regions).issubset(set(source_map))
        ):
            handled = False
            for key, value in calibration_regions.items():
                mapped_source = source_map.get(str(key))
                if mapped_source is None:
                    continue
                handled = True
                regions.extend(
                    ManningsFromLandCover._coerce_calibration_regions(
                        value,
                        raster_crs,
                        code_to_n,
                        code_to_name,
                        default_source=mapped_source,
                    )
                )
            if handled:
                return regions

        data = calibration_regions
        if hasattr(data, "to_crs") and getattr(data, "crs", None) is not None and raster_crs is not None:
            try:
                if data.crs != raster_crs:
                    data = data.to_crs(raster_crs)
            except Exception as exc:
                logger.debug(f"Could not reproject calibration regions: {exc}")

        if isinstance(data, pd.DataFrame):
            records = data.to_dict("records")
        elif isinstance(data, MappingABC):
            records = [dict(data)]
        else:
            records = list(data) if isinstance(data, IterableABC) and not isinstance(data, (str, bytes)) else [data]

        for record in records:
            if not isinstance(record, MappingABC):
                record = {"geometry": record}
            geometry = ManningsFromLandCover._coerce_geometry(record.get("geometry"))
            if geometry is None:
                continue

            source = str(record.get("source", record.get("level", default_source)))
            priority = int(record.get("priority", 2 if source == "geometry" else 1))
            n_value = ManningsFromLandCover._first_present(
                record,
                ManningsFromLandCover._N_VALUE_COLUMNS,
            )
            raw_code = ManningsFromLandCover._first_present(
                record,
                ManningsFromLandCover._CODE_COLUMNS,
            )
            raw_name = ManningsFromLandCover._first_present(
                record,
                ManningsFromLandCover._NAME_COLUMNS,
            )
            code = ManningsFromLandCover._nlcd_code_from_value(
                raw_code if raw_code is not None else raw_name,
                code_to_name,
            )

            if n_value is None and code is not None:
                n_value = code_to_n.get(int(code))
            if n_value is None:
                continue

            regions.append({
                "geometry": geometry,
                "n_value": float(n_value),
                "nlcd_code": int(code) if code is not None else None,
                "land_cover_name": str(raw_name) if raw_name is not None else None,
                "name": str(record.get("Region Name", record.get("Name", source))),
                "source": source,
                "priority": priority,
                "order": len(regions),
            })

        return regions

    @staticmethod
    def _sample_cross_section(
        src: Any,
        cut_line: Any,
        sta_elev: pd.DataFrame,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
        regions: List[dict],
    ) -> pd.DataFrame:
        try:
            from shapely.geometry import Point
        except ImportError as exc:
            raise ImportError("shapely is required for land-cover sampling.") from exc

        sta_elev = sta_elev.sort_values("Station").reset_index(drop=True)
        station_min = float(sta_elev["Station"].iloc[0])
        station_max = float(sta_elev["Station"].iloc[-1])
        station_range = station_max - station_min
        if station_range <= 0 or cut_line.length <= 0:
            return pd.DataFrame()

        raster_res = [abs(float(res)) for res in src.res if res and math.isfinite(float(res))]
        spacing = min(raster_res) if raster_res else station_range / 100.0
        sample_count = max(2, int(math.ceil(float(cut_line.length) / spacing)) + 1)
        fractions = np.linspace(0.0, 1.0, sample_count)
        stations = station_min + fractions * station_range
        elevations = np.interp(
            stations,
            sta_elev["Station"].to_numpy(dtype=float),
            sta_elev["Elevation"].to_numpy(dtype=float),
        )
        points = [cut_line.interpolate(float(frac), normalized=True) for frac in fractions]
        coords = [(point.x, point.y) for point in points]

        rows = []
        for station, elevation, point, sample in zip(
            stations,
            elevations,
            points,
            src.sample(coords, masked=True),
        ):
            code = ManningsFromLandCover._sample_to_code(sample, src.nodata)
            if code is None:
                continue
            n_value, source = ManningsFromLandCover._resolve_sample_n(
                code,
                Point(point.x, point.y),
                code_to_n,
                code_to_name,
                regions,
            )
            if n_value is None or pd.isna(n_value):
                continue

            rows.append({
                "station": float(station),
                "elevation": float(elevation),
                "x": float(point.x),
                "y": float(point.y),
                "nlcd_code": int(code),
                "land_cover_name": code_to_name.get(int(code), str(code)),
                "n_value": float(n_value),
                "source": source,
            })

        return pd.DataFrame(rows)

    @staticmethod
    def _sample_to_code(sample: Any, nodata: Optional[float]) -> Optional[int]:
        arr = np.ma.asarray(sample)
        if arr.size == 0:
            return None
        value = arr[0]
        if np.ma.is_masked(value):
            return None
        if pd.isna(value):
            return None
        numeric = float(value)
        if nodata is not None and math.isclose(numeric, float(nodata), rel_tol=0.0, abs_tol=0.0):
            return None
        return int(round(numeric))

    @staticmethod
    def _resolve_sample_n(
        code: int,
        point: Any,
        code_to_n: Dict[int, float],
        code_to_name: Dict[int, str],
        regions: List[dict],
    ) -> Tuple[Optional[float], str]:
        n_value = code_to_n.get(int(code))
        source = "base"

        for region in sorted(regions, key=lambda item: (item["priority"], item["order"])):
            region_code = region.get("nlcd_code")
            if region_code is not None and int(region_code) != int(code):
                continue
            if region_code is None and region.get("land_cover_name"):
                sample_name = ManningsFromLandCover._normalize_name(code_to_name.get(int(code), ""))
                region_name = ManningsFromLandCover._normalize_name(region["land_cover_name"])
                if sample_name and region_name and sample_name != region_name:
                    continue
            if region["geometry"].covers(point):
                n_value = float(region["n_value"])
                source = f"{region['source']}:{region['name']}"

        return n_value, source

    @staticmethod
    def _samples_to_blocks(
        samples: pd.DataFrame,
        sta_elev: pd.DataFrame,
        banks: Optional[Tuple[float, float]],
        max_blocks: int,
    ) -> Tuple[List[dict], int]:
        samples = samples.sort_values("station").reset_index(drop=True)
        if samples.empty:
            return [], 0

        blocks = []
        current = ManningsFromLandCover._new_block(samples.iloc[0])
        for _, row in samples.iloc[1:].iterrows():
            if math.isclose(
                float(row["n_value"]),
                float(current["n_value"]),
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                current["codes"].add(int(row["nlcd_code"]))
                current["sources"].add(str(row["source"]))
                continue
            blocks.append(current)
            current = ManningsFromLandCover._new_block(row)
        blocks.append(current)

        station_min = float(sta_elev["Station"].min())
        station_max = float(sta_elev["Station"].max())
        if blocks:
            blocks[0]["start_station"] = station_min
        for idx, block in enumerate(blocks):
            block["end_station"] = (
                blocks[idx + 1]["start_station"]
                if idx + 1 < len(blocks)
                else station_max
            )

        blocks = ManningsFromLandCover._split_blocks_at_banks(blocks, banks)
        ManningsFromLandCover._refresh_block_geometry(blocks, sta_elev, banks)
        blocks = ManningsFromLandCover._coalesce_same_side_blocks(blocks)
        ManningsFromLandCover._refresh_block_geometry(blocks, sta_elev, banks)

        raw_block_count = len(blocks)
        if len(blocks) > max_blocks:
            blocks = ManningsFromLandCover._enforce_block_limit(blocks, max_blocks, sta_elev, banks)

        return blocks, raw_block_count

    @staticmethod
    def _new_block(row: pd.Series) -> dict:
        return {
            "start_station": float(row["station"]),
            "end_station": float(row["station"]),
            "n_value": float(row["n_value"]),
            "codes": {int(row["nlcd_code"])},
            "sources": {str(row["source"])},
            "area": 0.0,
            "subsection": "Unknown",
            "merged_count": 1,
        }

    @staticmethod
    def _split_blocks_at_banks(blocks: List[dict], banks: Optional[Tuple[float, float]]) -> List[dict]:
        if banks is None:
            return blocks

        split_points = [float(banks[0]), float(banks[1])]
        split_blocks = []
        for block in blocks:
            starts = [block["start_station"]]
            ends = []
            for split_station in split_points:
                if block["start_station"] < split_station < block["end_station"]:
                    ends.append(split_station)
                    starts.append(split_station)
            ends.append(block["end_station"])

            for start, end in zip(starts, ends):
                new_block = block.copy()
                new_block["codes"] = set(block["codes"])
                new_block["sources"] = set(block["sources"])
                new_block["start_station"] = float(start)
                new_block["end_station"] = float(end)
                split_blocks.append(new_block)

        return split_blocks

    @staticmethod
    def _refresh_block_geometry(
        blocks: List[dict],
        sta_elev: pd.DataFrame,
        banks: Optional[Tuple[float, float]],
    ) -> None:
        thalweg_station = ManningsFromLandCover._thalweg_station(sta_elev)
        for block in blocks:
            block["area"] = ManningsFromLandCover._section_area(
                sta_elev,
                block["start_station"],
                block["end_station"],
            )
            block["subsection"] = ManningsFromLandCover._classify_subsection(
                block["start_station"],
                block["end_station"],
                banks,
                thalweg_station,
            )

    @staticmethod
    def _coalesce_same_side_blocks(blocks: List[dict]) -> List[dict]:
        if not blocks:
            return []

        merged = [blocks[0]]
        for block in blocks[1:]:
            prior = merged[-1]
            if (
                prior["subsection"] == block["subsection"]
                and math.isclose(prior["n_value"], block["n_value"], rel_tol=0.0, abs_tol=1e-9)
            ):
                prior["end_station"] = block["end_station"]
                prior["codes"].update(block["codes"])
                prior["sources"].update(block["sources"])
                prior["merged_count"] += block["merged_count"]
            else:
                merged.append(block)

        return merged

    @staticmethod
    def _enforce_block_limit(
        blocks: List[dict],
        max_blocks: int,
        sta_elev: pd.DataFrame,
        banks: Optional[Tuple[float, float]],
    ) -> List[dict]:
        blocks = [block.copy() for block in blocks]

        while len(blocks) > max_blocks:
            candidates = ManningsFromLandCover._merge_candidates(blocks, banks, sta_elev)
            if not candidates:
                raise ValueError(
                    f"Cannot reduce Manning's n blocks to max_blocks={max_blocks} "
                    "without merging across the main channel"
                )

            _, _, _, merge_idx = min(candidates)
            blocks = (
                blocks[:merge_idx]
                + [ManningsFromLandCover._merge_blocks(blocks[merge_idx], blocks[merge_idx + 1])]
                + blocks[merge_idx + 2:]
            )
            ManningsFromLandCover._refresh_block_geometry(blocks, sta_elev, banks)
            blocks = ManningsFromLandCover._coalesce_same_side_blocks(blocks)
            ManningsFromLandCover._refresh_block_geometry(blocks, sta_elev, banks)

        return blocks

    @staticmethod
    def _merge_candidates(
        blocks: List[dict],
        banks: Optional[Tuple[float, float]],
        sta_elev: pd.DataFrame,
    ) -> List[Tuple[int, float, float, int]]:
        thalweg_station = ManningsFromLandCover._thalweg_station(sta_elev)
        main_left = float(banks[0]) if banks is not None else thalweg_station
        main_right = float(banks[1]) if banks is not None else thalweg_station

        candidates = []
        for idx in range(len(blocks) - 1):
            left = blocks[idx]
            right = blocks[idx + 1]
            if left["subsection"] != right["subsection"]:
                continue

            subsection = left["subsection"]
            side_priority = 1 if subsection == "Channel" else 0
            if subsection == "LOB":
                distance = max(0.0, main_left - right["end_station"])
            elif subsection == "ROB":
                distance = max(0.0, left["start_station"] - main_right)
            else:
                distance = 0.0

            n_diff = abs(float(left["n_value"]) - float(right["n_value"]))
            candidates.append((side_priority, -distance, n_diff, idx))

        return candidates

    @staticmethod
    def _merge_blocks(left: dict, right: dict) -> dict:
        left_area = max(float(left["area"]), max(left["end_station"] - left["start_station"], 0.0))
        right_area = max(float(right["area"]), max(right["end_station"] - right["start_station"], 0.0))
        total_area = left_area + right_area
        if total_area <= 0:
            merged_n = (float(left["n_value"]) + float(right["n_value"])) / 2.0
        else:
            merged_n = (
                float(left["n_value"]) * left_area
                + float(right["n_value"]) * right_area
            ) / total_area

        return {
            "start_station": left["start_station"],
            "end_station": right["end_station"],
            "n_value": float(merged_n),
            "codes": set(left["codes"]) | set(right["codes"]),
            "sources": set(left["sources"]) | set(right["sources"]),
            "area": total_area,
            "subsection": left["subsection"],
            "merged_count": int(left["merged_count"]) + int(right["merged_count"]),
        }

    @staticmethod
    def _section_area(sta_elev: pd.DataFrame, left: float, right: float) -> float:
        sta_elev = sta_elev.sort_values("Station")
        min_station = float(sta_elev["Station"].iloc[0])
        max_station = float(sta_elev["Station"].iloc[-1])
        left = max(float(left), min_station)
        right = min(float(right), max_station)
        if right <= left:
            return 0.0

        stations = sta_elev["Station"].to_numpy(dtype=float)
        elevations = sta_elev["Elevation"].to_numpy(dtype=float)
        inside = stations[(stations > left) & (stations < right)]
        eval_stations = np.concatenate(([left], inside, [right]))
        eval_elevations = np.interp(eval_stations, stations, elevations)
        reference_elevation = float(np.max(elevations))
        depths = np.maximum(reference_elevation - eval_elevations, 0.0)
        if hasattr(np, "trapezoid"):
            area = float(np.trapezoid(depths, eval_stations))
        else:
            area = float(np.trapz(depths, eval_stations))
        return max(area, right - left)

    @staticmethod
    def _classify_subsection(
        start_station: float,
        end_station: float,
        banks: Optional[Tuple[float, float]],
        thalweg_station: float,
    ) -> str:
        start_station = float(start_station)
        end_station = float(end_station)
        if banks is not None:
            left_bank, right_bank = float(banks[0]), float(banks[1])
            if end_station <= left_bank:
                return "LOB"
            if start_station >= right_bank:
                return "ROB"
            return "Channel"

        if end_station <= thalweg_station:
            return "LOB"
        if start_station >= thalweg_station:
            return "ROB"
        return "Channel"

    @staticmethod
    def _thalweg_station(sta_elev: pd.DataFrame) -> float:
        idx = sta_elev["Elevation"].astype(float).idxmin()
        return float(sta_elev.loc[idx, "Station"])

    @staticmethod
    def _coerce_geometry(geometry: Any) -> Optional[Any]:
        if geometry is None:
            return None
        if hasattr(geometry, "geom_type"):
            return geometry
        try:
            missing = pd.isna(geometry)
            if isinstance(missing, (bool, np.bool_)) and missing:
                return None
        except (TypeError, ValueError):
            pass
        try:
            from shapely.geometry import shape, Polygon
            if isinstance(geometry, MappingABC):
                return shape(geometry)
            if isinstance(geometry, (list, tuple)):
                return Polygon(geometry)
        except Exception:
            return None
        return None

    @staticmethod
    def _first_present(
        values: Mapping[str, Any],
        candidates: Iterable[str],
        default: Any = None,
    ) -> Any:
        for candidate in candidates:
            if candidate not in values:
                continue
            value = values[candidate]
            if value is None:
                continue
            try:
                if pd.isna(value):
                    continue
            except (TypeError, ValueError):
                pass
            return value
        return default

    @staticmethod
    def _nlcd_code_from_value(value: Any, code_to_name: Dict[int, str]) -> Optional[int]:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, float) and math.isfinite(value) and value.is_integer():
            return int(value)

        text = str(value).strip()
        if not text:
            return None
        try:
            return int(float(text))
        except ValueError:
            pass

        match = re.search(r"\b(\d{2,3})\b", text)
        if match:
            return int(match.group(1))

        normalized = ManningsFromLandCover._normalize_name(text)
        for code, name in code_to_name.items():
            if ManningsFromLandCover._normalize_name(name) == normalized:
                return int(code)
        return None

    @staticmethod
    def _normalize_name(value: Any) -> str:
        text = str(value).lower().strip()
        return re.sub(r"[^a-z0-9]+", "", text)
