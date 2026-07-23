"""
RasMap - Parses HEC-RAS mapper configuration files (.rasmap)

This module provides functionality to extract and organize information from
HEC-RAS mapper configuration files, including paths to terrain, soil, and land cover data.
It also includes functions to automate the post-processing of stored maps.

This module is part of the ras-commander library and uses a centralized logging configuration.

Logging Configuration:
- The logging is set up in the logging_config.py file.
- A @log_call decorator is available to automatically log function calls.
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

Classes:
    RasMap: Class for parsing and accessing HEC-RAS mapper configuration.

-----

All of the methods in this class are static and are designed to be used without instantiation.

List of Functions in RasMap:
- parse_rasmap(): Parse a .rasmap file and extract relevant information
- get_rasmap_path(): Get the path to the .rasmap file based on the current project
- initialize_rasmap_df(): Initialize the rasmap_df as part of project initialization
- get_terrain_names(): Extracts terrain layer names from a given .rasmap file
- list_map_layers(): List all map layers in the RASMapper configuration file
- list_reference_map_layers(): List shapefile/GeoJSON reference map layers
- list_basemap_layers(): List standard basemap layers registered in .rasmap
- set_map_layer_visibility(): Toggle reference, basemap, and land-classification map layers
- add_reference_map_layer(): Add a shapefile/GeoJSON reference map layer
- add_basemap_layer(): Add a standard basemap layer
- add_map_layer(): Add a map layer to the RASMapper configuration file
- remove_map_layer(): Remove a map layer from the RASMapper configuration file
- list_geometry_layers(): List top-level geometries and child geometry elements
- list_geometry_features(): List HDF geometry features inside a layer
- list_land_classification_polygons(): List sidecar classification polygon overrides
- add_land_classification_polygon(): Add sidecar classification polygon override
- update_land_classification_polygon(): Update sidecar classification polygon override
- delete_land_classification_polygon(): Delete sidecar classification polygon override
- set_geometry_layer_visibility(): Toggle child geometry elements such as mesh, XS, and structures
- list_result_layers(): List RASMapper result plan and child layers
- set_result_layer_visibility(): Toggle result plan and result child layers
- get_current_view(): Read the RASMapper CurrentView bounds
- set_current_view(): Write the RASMapper CurrentView bounds
- set_terrain_layer_visibility(): Toggle terrain layers for RASMapper inspection
- list_terrain_display_settings(): List persisted terrain display settings
- get_terrain_display_settings(): Read persisted terrain display settings for one terrain
- set_terrain_display_settings(): Write persisted terrain display settings
- set_update_legend_with_view(): Enable viewport-updated legends on raster surface layers
- zoom_to_geometry_layer(): Zoom CurrentView to HDF-derived geometry element extents
- get_geometry_feature_bounds(): Get HDF-derived extents for a selected feature
- open_rasmapper(): Launch standalone RasMapper.exe against the project .rasmap
- capture_rasmapper_snapshot(): Capture a visible RASMapper window screenshot
- create_spatial_review_package(): Build a RASMapper QA/QC evidence bundle
- postprocess_stored_maps(): Automates the generation of stored floodplain map outputs via GUI automation
- store_all_maps(): Headless stored map generation using RasStoreMapHelper.exe (no GUI required)
- get_results_folder(): Get the folder path containing raster results for a specified plan
- get_results_raster(): Get the .vrt file path for a specified plan and variable name
- set_water_surface_render_mode(): Set the water surface rendering mode (horizontal or sloped)
- get_water_surface_render_mode(): Get the current water surface rendering mode
- add_terrain_layer(): Add terrain layer to RASMapper configuration
- list_results_plans(): List all plan result layers in the RASMapper configuration
- ensure_results_plan_layer(): Register a plan HDF as a RASMapper result layer
- ensure_2d_encroachment_plan_layers(): Register editable 2D encroachment plan layers
- list_results_map_layers(): List RASMapper result map layers
- add_results_map_layer(): Add a RASMapper result map layer
- list_calculated_layers(): List all calculated layers across all plan results
- add_calculated_layer(): Add a calculated layer with .rasscript to the RASMapper configuration
- remove_calculated_layer(): Remove a calculated layer from the RASMapper configuration
- add_wse_comparison_layers(): Batch add WSE comparison layers for existing/proposed plan pairs
"""

import os
import re
import subprocess
import warnings
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import pandas as pd
import shutil
from typing import Union, Optional, Dict, List, Any, Sequence, Tuple, TYPE_CHECKING

import numpy as np

from .RasPrj import ras
from .RasPlan import RasPlan
from .RasCmdr import RasCmdr
from .RasUtils import RasUtils
from .RasGuiAutomation import RasGuiAutomation
from .RasBenefits import BenefitAreaConfig
from .RasterPerformance import StoreMapPerformanceOptions
from .LoggingConfig import get_logger
from .Decorators import log_call
from ._native_helper import (
    normalize_store_map_render_mode,
    run_store_all_maps_helper,
)

if TYPE_CHECKING:
    from geopandas import GeoDataFrame

logger = get_logger(__name__)


def _resolve_optional_ras_project_path(
    ras_project_path: Optional[Union[str, Path]] = None,
    ras_object=None,
) -> Union[str, Path]:
    """Resolve either an explicit project path or the active RasPrj object."""
    if (
        ras_object is None
        and ras_project_path is not None
        and hasattr(
            ras_project_path,
            "check_initialized",
        )
    ):
        ras_object = ras_project_path
        ras_project_path = None

    if ras_project_path is not None:
        return ras_project_path

    ras_obj = ras_object or ras
    ras_obj.check_initialized()
    return ras_obj.project_folder


def _sanitize_vbnet_identifier(name: str) -> str:
    """Convert a string to a valid VB.NET identifier for use in .rasscript Dim statements.

    Replaces dots, spaces, hyphens, and other non-alphanumeric characters with underscores.
    Prepends '_' if the result starts with a digit.
    """
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if sanitized and sanitized[0].isdigit():
        sanitized = "_" + sanitized
    return sanitized


def _resolve_plan_file_for_rasmap(
    plan_number_or_path: Union[str, int, float, Path],
    ras_object=None,
) -> Path:
    """Resolve a plan number or direct plan path for RASMapper XML helpers."""
    candidate = Path(str(plan_number_or_path))
    if candidate.exists() and re.search(r"\.p\d{2,3}$", candidate.name, re.IGNORECASE):
        return RasUtils.safe_resolve(candidate)

    ras_obj = ras_object or ras
    ras_obj.check_initialized()
    plan_path = RasPlan.get_plan_path(plan_number_or_path, ras_object=ras_obj)
    if plan_path is None or not Path(plan_path).exists():
        raise FileNotFoundError(f"Plan file not found for plan: {plan_number_or_path}")
    return RasUtils.safe_resolve(Path(plan_path))


def _project_name_from_plan_path(plan_path: Path) -> str:
    return re.sub(r"\.p\d{2,3}$", "", plan_path.name, flags=re.IGNORECASE)


def _read_plan_text_value(plan_path: Path, key: str) -> str:
    if not plan_path.exists():
        return ""
    for line in plan_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _plan_display_name_for_rasmap(plan_path: Path) -> str:
    return (
        _read_plan_text_value(plan_path, "Short Identifier")
        or _read_plan_text_value(plan_path, "Plan Title")
        or plan_path.stem
    )


def _infer_plan_geometry_hdf(plan_path: Path) -> Optional[Path]:
    geom_file = _read_plan_text_value(plan_path, "Geom File")
    if not geom_file:
        return None
    project_name = _project_name_from_plan_path(plan_path)
    return plan_path.parent / f"{project_name}.{geom_file}.hdf"


def _rasmap_relative_path(project_folder: Path, target_path: Union[str, Path]) -> str:
    from . import _land_classification_helper as _lch

    return _lch.to_rasmap_relative_path(project_folder, target_path)


def _normalize_rasmap_filename(filename: Optional[str]) -> str:
    if not filename:
        return ""
    return filename.replace("/", "\\").lower()


# Default diverging color ramp for WSE comparison layers (blue=benefit, white=zero, red=adverse)
# .NET ARGB signed Int32: Blue(-16776961), Cyan(-16724737), White(-1), Orange(-23296), Red(-65536)
_WSE_COMPARISON_DEFAULT_COLORS = "-16776961,-16724737,-1,-23296,-65536"
_WSE_COMPARISON_DEFAULT_VALUES = "-2,-1,0,1,2"


_WSE_COMPARISON_RASSCRIPT_TEMPLATE = """\
Imports System
Imports System.Linq
Imports System.Collections.Generic

Namespace RasterCode
  Public Class Processor
    Public Shared Function ProcessTile(inputTiles As List(of Single())) As Single()
      Const NoData As Single = -9999.0
      Dim length As Integer = inputTiles.First().Length
      For Each tile As Single() In inputTiles
        If tile Is Nothing OrElse tile.Length <> length Then Throw New ArgumentException("Tile has invalid dimensions.")
      Next

      Dim returnArray(length - 1) as Single
      For i as Integer = 0 to length - 1
        Dim WSE_Exist As Single = inputTiles(0)(i)
        Dim WSE_Prop As Single = inputTiles(1)(i)
        Dim {exist_terrain_var} As Single = inputTiles(2)(i)
        Dim {prop_terrain_var} As Single = inputTiles(3)(i)
        Dim Output As Single = NoData

' #BEGINSCRIPT:
'  WSE Comparison: Proposed - Existing (positive=rise/adverse, negative=drop/benefit)
'  {layer_name}
'  Requirements: Water surfaces 'WSE_Exist' and 'WSE_Prop'
'                Terrains '{exist_terrain_var}' (existing) and '{prop_terrain_var}' (proposed)
' #VARIABLES:
'  'WSE_Exist' is the cell value from 'WSE_Exist = {exist_plan} | elevation | 2147483647 | Fixed Profile'
'  'WSE_Prop' is the cell value from 'WSE_Prop = {prop_plan} | elevation | 2147483647 | Fixed Profile'
'  '{exist_terrain_var}' is the cell value from '{exist_terrain_name}'
'  '{prop_terrain_var}' is the cell value from '{prop_terrain_name}'
'-------------------------------------------------------
If WSE_Exist = NoData AndAlso WSE_Prop = NoData Then
  ' Both plans are dry at this cell
  Output = NoData
Else
  ' Substitute terrain elevation where a plan is dry
  If WSE_Exist = NoData Then WSE_Exist = {exist_terrain_var}
  If WSE_Prop = NoData Then WSE_Prop = {prop_terrain_var}
  Output = WSE_Prop - WSE_Exist
End If
' #ENDSCRIPT:

        returnArray(i) = Output
      Next

      return returnArray
    End Function
  End Class
End Namespace

' #VARIABLE: WSE_Exist = {exist_plan} | elevation | 2147483647 | Fixed Profile
' #VARIABLE: WSE_Prop = {prop_plan} | elevation | 2147483647 | Fixed Profile

' #TERRAIN: {exist_terrain_var} = {exist_terrain_name}
' #TERRAIN: {prop_terrain_var} = {prop_terrain_name}
"""


class RasMap:
    """
    Class for parsing and accessing information from HEC-RAS mapper configuration files (.rasmap).

    This class provides methods to extract paths to terrain, soil, land cover data,
    and various project settings from the .rasmap file associated with a HEC-RAS project.
    It also includes functionality to automate the post-processing of stored maps.
    """

    @staticmethod
    @log_call
    def parse_rasmap(rasmap_path: Union[str, Path], ras_object=None) -> pd.DataFrame:
        """
        Parse a .rasmap file and extract relevant information.

        Args:
            rasmap_path (Union[str, Path]): Path to the .rasmap file.
            ras_object: Optional RAS object instance.

        Returns:
            pd.DataFrame: DataFrame containing extracted information from the .rasmap file.
        """
        rasmap_path = Path(rasmap_path)
        from . import _land_classification_helper as _lch

        if not rasmap_path.exists():
            logger.error(f"RASMapper file not found: {rasmap_path}")
            return _lch.empty_rasmap_dataframe()

        try:
            data = _lch.empty_rasmap_dataframe().to_dict(orient="list")

            # Read the file content
            with open(rasmap_path, "r", encoding="utf-8") as f:
                xml_content = f.read()

            # Check if it's a valid XML file
            if not xml_content.strip().startswith("<"):
                logger.error(f"File does not appear to be valid XML: {rasmap_path}")
                return pd.DataFrame(data)

            # Parse the XML file
            try:
                tree = ET.parse(rasmap_path)
                root = tree.getroot()
            except ET.ParseError as e:
                logger.error(f"Error parsing XML in {rasmap_path}: {e}")
                return _lch.empty_rasmap_dataframe()

            # Extract projection path
            try:
                projection_elem = root.find(".//RASProjectionFilename")
                if projection_elem is not None and "Filename" in projection_elem.attrib:
                    projection_path = _lch.resolve_rasmap_relative_path(
                        rasmap_path.parent,
                        projection_elem.attrib["Filename"],
                    )
                    data["projection_path"][0] = (
                        str(projection_path) if projection_path is not None else None
                    )
            except Exception as e:
                logger.warning(f"Error extracting projection path: {e}")

            # Extract profile lines path
            try:
                profile_lines_elem = root.find(
                    ".//Features/Layer[@Name='Profile Lines']"
                )
                if (
                    profile_lines_elem is not None
                    and "Filename" in profile_lines_elem.attrib
                ):
                    profile_lines_path = _lch.resolve_rasmap_relative_path(
                        rasmap_path.parent,
                        profile_lines_elem.attrib["Filename"],
                    )
                    if profile_lines_path is not None:
                        data["profile_lines_path"][0].append(str(profile_lines_path))
            except Exception as e:
                logger.warning(f"Error extracting profile lines path: {e}")

            try:
                land_layers = RasMap.list_land_classification_layers(
                    rasmap_path,
                    ras_object=ras_object,
                )
                if not land_layers.empty:
                    for kind, target_column in (
                        ("soils", "soil_layer_path"),
                        ("infiltration", "infiltration_hdf_path"),
                        ("landcover", "landcover_hdf_path"),
                    ):
                        paths = [
                            str(path)
                            for path in land_layers.loc[
                                land_layers["classification_kind"] == kind,
                                "resolved_path",
                            ]
                            .dropna()
                            .tolist()
                        ]
                        data[target_column][0] = paths
            except Exception as e:
                logger.warning(f"Error extracting land-classification layer paths: {e}")

            # Extract terrain HDF paths
            try:
                terrain_layers = root.findall(".//Terrains/Layer")
                for layer in terrain_layers:
                    if "Filename" in layer.attrib:
                        terrain_path = _lch.resolve_rasmap_relative_path(
                            rasmap_path.parent,
                            layer.attrib["Filename"],
                        )
                        if terrain_path is not None:
                            data["terrain_hdf_path"][0].append(str(terrain_path))
            except Exception as e:
                logger.warning(f"Error extracting terrain HDF paths: {e}")

            try:
                reference_layers = RasMap.list_reference_map_layers(
                    rasmap_path,
                    ras_object=ras_object,
                )
                if not reference_layers.empty:
                    data["reference_map_layer_names"][0] = (
                        reference_layers["name"].dropna().tolist()
                    )
                    data["reference_map_layer_path"][0] = [
                        str(path)
                        for path in reference_layers["resolved_path"].dropna().tolist()
                    ]
            except Exception as e:
                logger.warning(f"Error extracting reference map layers: {e}")

            try:
                basemap_layers = RasMap.list_basemap_layers(
                    rasmap_path,
                    ras_object=ras_object,
                )
                if not basemap_layers.empty:
                    data["basemap_layer_names"][0] = (
                        basemap_layers["name"].dropna().tolist()
                    )
                    data["basemap_layer_path"][0] = [
                        str(path)
                        for path in basemap_layers["resolved_path"].dropna().tolist()
                    ]
            except Exception as e:
                logger.warning(f"Error extracting basemap layers: {e}")

            # Extract current settings
            current_settings = {}
            try:
                settings_elem = root.find(".//CurrentSettings")
                if settings_elem is not None:
                    # Extract ProjectSettings
                    project_settings_elem = settings_elem.find("ProjectSettings")
                    if project_settings_elem is not None:
                        for child in project_settings_elem:
                            current_settings[child.tag] = child.text

                    # Extract Folders
                    folders_elem = settings_elem.find("Folders")
                    if folders_elem is not None:
                        for child in folders_elem:
                            current_settings[child.tag] = child.text

                data["current_settings"][0] = current_settings
            except Exception as e:
                logger.warning(f"Error extracting current settings: {e}")

            # Create DataFrame
            df = pd.DataFrame(data)
            logger.debug(
                "Parsed RASMapper file: %s (terrains=%d, reference_layers=%d, basemaps=%d)",
                rasmap_path.name,
                len(data.get("terrain_hdf_path", [[]])[0] or []),
                len(data.get("reference_map_layer_names", [[]])[0] or []),
                len(data.get("basemap_layer_names", [[]])[0] or []),
            )
            return df

        except Exception as e:
            logger.error(
                f"Unexpected error processing RASMapper file {rasmap_path}: {e}"
            )
            return _lch.empty_rasmap_dataframe()

    @staticmethod
    @log_call
    def list_land_classification_layers(
        ras_project_path: Union[str, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List semantic land-classification layers from a project .rasmap file.

        Classifies each ``Type="LandCoverLayer"`` entry as ``landcover``,
        ``soils``, ``infiltration``, or ``unknown`` using filename and selected
        parameter semantics rather than exact display names.

        Args:
            ras_project_path: Project folder, .prj file, or .rasmap file.
            ras_object: Optional RasPrj object. Present for API consistency.

        Returns:
            DataFrame with one row per LandCoverLayer entry.
        """
        ras_project_path = Path(ras_project_path)
        from . import _land_classification_helper as _lch

        project_paths = _lch.resolve_project_paths(ras_project_path)
        rasmap_path = project_paths.rasmap_path

        columns = [
            "name",
            "type",
            "checked",
            "filename",
            "resolved_path",
            "selected_parameter",
            "classification_kind",
            "classification_layer_count",
            "classification_layer_filenames",
            "classification_layer_paths",
        ]

        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return pd.DataFrame(columns=columns)

        try:
            root = ET.parse(rasmap_path).getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return pd.DataFrame(columns=columns)

        map_layers = root.find("MapLayers")
        if map_layers is None:
            return pd.DataFrame(columns=columns)

        records = []
        for layer in map_layers.findall("Layer"):
            if layer.attrib.get("Type") != "LandCoverLayer":
                continue
            records.append(
                _lch.build_land_classification_record(
                    layer,
                    project_paths.project_folder,
                )
            )

        if not records:
            return pd.DataFrame(columns=columns)

        return pd.DataFrame(records, columns=columns)

    @staticmethod
    @log_call
    def list_terrain_layers(
        ras_project_path: Union[str, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List terrain layers registered in a project .rasmap file.

        Args:
            ras_project_path: Project folder, .prj file, or .rasmap file.
            ras_object: Optional RasPrj object. Present for API consistency.

        Returns:
            DataFrame with one row per ``Terrains/Layer`` entry.
        """
        ras_project_path = Path(ras_project_path)
        from . import _land_classification_helper as _lch

        project_paths = _lch.resolve_project_paths(ras_project_path)
        rasmap_path = project_paths.rasmap_path
        columns = [
            "name",
            "filename",
            "resolved_path",
            "checked",
            "type",
            "resample_method",
            "surface_on",
        ]

        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return pd.DataFrame(columns=columns)

        try:
            root = ET.parse(rasmap_path).getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return pd.DataFrame(columns=columns)

        records = []
        for layer in root.findall(".//Terrains/Layer"):
            filename = layer.attrib.get("Filename")
            resolved_path = _lch.resolve_rasmap_relative_path(
                project_paths.project_folder,
                filename,
            )
            surface = layer.find("Surface")
            records.append(
                {
                    "name": layer.attrib.get("Name", ""),
                    "filename": filename,
                    "resolved_path": (
                        str(resolved_path) if resolved_path is not None else None
                    ),
                    "checked": layer.attrib.get("Checked", "True").lower() == "true",
                    "type": layer.attrib.get("Type", ""),
                    "resample_method": layer.findtext("ResampleMethod"),
                    "surface_on": (
                        surface.attrib.get("On", "False").lower() == "true"
                        if surface is not None
                        else None
                    ),
                }
            )

        return pd.DataFrame(records, columns=columns)

    @staticmethod
    @log_call
    def list_landcover_layers(
        ras_project_path: Union[str, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """List land-cover layers registered in a project .rasmap file."""
        layers = RasMap.list_land_classification_layers(
            ras_project_path,
            ras_object=ras_object,
        )
        return layers.loc[layers["classification_kind"] == "landcover"].copy()

    @staticmethod
    @log_call
    def list_soils_layers(
        ras_project_path: Union[str, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """List hydrologic soils layers registered in a project .rasmap file."""
        layers = RasMap.list_land_classification_layers(
            ras_project_path,
            ras_object=ras_object,
        )
        return layers.loc[layers["classification_kind"] == "soils"].copy()

    @staticmethod
    @log_call
    def list_infiltration_layers(
        ras_project_path: Union[str, Path],
        ras_object=None,
    ) -> pd.DataFrame:
        """List infiltration layers registered in a project .rasmap file."""
        layers = RasMap.list_land_classification_layers(
            ras_project_path,
            ras_object=ras_object,
        )
        return layers.loc[layers["classification_kind"] == "infiltration"].copy()

    @staticmethod
    @log_call
    def list_land_classification_polygons(
        layer_hdf_path: Union[str, Path],
        ras_object=None,
    ) -> "GeoDataFrame":
        """
        List classification polygon overrides stored in a land-classification HDF.

        Args:
            layer_hdf_path: Land-cover, soils, or infiltration sidecar HDF.
            ras_object: Optional RasPrj object. Present for API consistency.

        Returns:
            GeoDataFrame with ``polygon_index``, ``class_name``, and geometry.
        """
        from . import _land_classification_helper as _lch

        return _lch.list_land_classification_polygons(layer_hdf_path)

    @staticmethod
    @log_call
    def add_land_classification_polygon(
        layer_hdf_path: Union[str, Path],
        polygon: Any,
        class_name: str,
        class_id: Optional[int] = None,
        variable_values: Optional[dict[str, Any]] = None,
        backup: bool = True,
        ras_object=None,
    ) -> "GeoDataFrame":
        """
        Add a classification polygon override to a land-cover, soils, or infiltration HDF.

        The method writes the RAS Mapper ``/Classification Polygons`` group and
        upserts the affected ``/Raster Map`` and/or ``/Variables`` class rows.
        Existing compiled geometry HDFs should be preprocessed again before
        simulation so HEC-RAS consumes the new override.
        """
        from . import _land_classification_helper as _lch

        return _lch.add_land_classification_polygon(
            layer_hdf_path=layer_hdf_path,
            polygon=polygon,
            class_name=class_name,
            class_id=class_id,
            variable_values=variable_values,
            backup=backup,
        )

    @staticmethod
    @log_call
    def update_land_classification_polygon(
        layer_hdf_path: Union[str, Path],
        polygon_index: int,
        polygon: Optional[Any] = None,
        class_name: Optional[str] = None,
        class_id: Optional[int] = None,
        variable_values: Optional[dict[str, Any]] = None,
        backup: bool = True,
        ras_object=None,
    ) -> "GeoDataFrame":
        """
        Update a classification polygon's geometry, class name, or class values.

        ``polygon_index`` is the zero-based index returned by
        :meth:`list_land_classification_polygons`.
        """
        from . import _land_classification_helper as _lch

        return _lch.update_land_classification_polygon(
            layer_hdf_path=layer_hdf_path,
            polygon_index=polygon_index,
            polygon=polygon,
            class_name=class_name,
            class_id=class_id,
            variable_values=variable_values,
            backup=backup,
        )

    @staticmethod
    @log_call
    def delete_land_classification_polygon(
        layer_hdf_path: Union[str, Path],
        polygon_index: Optional[int] = None,
        class_name: Optional[str] = None,
        remove_unused_class: bool = False,
        backup: bool = True,
        ras_object=None,
    ) -> "GeoDataFrame":
        """
        Delete classification polygon overrides by index or class name.

        By default this removes only the polygon records. Set
        ``remove_unused_class=True`` to also remove class rows from ``Raster Map``
        and ``Variables`` when no remaining polygon uses that class.
        """
        from . import _land_classification_helper as _lch

        return _lch.delete_land_classification_polygon(
            layer_hdf_path=layer_hdf_path,
            polygon_index=polygon_index,
            class_name=class_name,
            remove_unused_class=remove_unused_class,
            backup=backup,
        )

    @staticmethod
    @log_call
    def add_landcover_layer(
        ras_project_path: Union[str, Path],
        source_path: Union[str, Path],
        classification_table: Union[pd.DataFrame, str, Path],
        cell_size: float,
        source_field: Optional[str] = None,
        output_hdf_path: Optional[Union[str, Path]] = None,
        restrict_to_extent: Optional[Any] = None,
        layer_name: str = "LandCover",
        buffer_distance: float = 0.0,
        ras_object=None,
    ) -> Path:
        """
        Create and register a land-cover classification layer for a RAS project.

        ``restrict_to_extent`` may be a valid Shapely ``Polygon``, a
        ``MultiPolygon`` containing exactly one non-empty polygonal part, a
        one-effective-geometry GeoSeries/GeoDataFrame, a four-value bounds
        tuple/list, a bounds dict/object, or ``RasMapperLib.Extent``.
        ``buffer_distance`` is applied before raster bounds are derived, in
        project CRS units, and defaults to ``0.0``. Callers are responsible for
        supplying geometry in the project CRS. Empty, invalid, non-polygon, and
        true multipart geometry inputs raise ``ValueError``.
        """
        ras_project_path = Path(ras_project_path)
        source_path = Path(source_path)
        output_hdf_path = Path(output_hdf_path) if output_hdf_path is not None else None
        from . import _land_classification_helper as _lch

        return _lch.add_landcover_layer(
            ras_project_path=ras_project_path,
            source_path=source_path,
            classification_table=classification_table,
            cell_size=cell_size,
            source_field=source_field,
            output_hdf_path=output_hdf_path,
            restrict_to_extent=restrict_to_extent,
            layer_name=layer_name,
            buffer_distance=buffer_distance,
        )

    @staticmethod
    @log_call
    def add_soils_layer(
        ras_project_path: Union[str, Path],
        gssurgo_path: Union[str, Path],
        cell_size: float,
        output_hdf_path: Optional[Union[str, Path]] = None,
        restrict_to_extent: Optional[Any] = None,
        buffer_distance: float = 0.0,
        ras_object=None,
    ) -> Path:
        """
        Create and register a soils layer from direct GSSURGO input.

        ``restrict_to_extent`` accepts the same polygon and legacy bounds inputs
        as :meth:`add_landcover_layer`. ``buffer_distance`` is applied in project
        CRS units before raster bounds are derived and defaults to ``0.0``.
        Multipart, empty, invalid, and non-polygon geometry inputs fail closed.
        """
        ras_project_path = Path(ras_project_path)
        gssurgo_path = Path(gssurgo_path)
        output_hdf_path = Path(output_hdf_path) if output_hdf_path is not None else None
        from . import _land_classification_helper as _lch

        return _lch.add_soils_layer(
            ras_project_path=ras_project_path,
            gssurgo_path=gssurgo_path,
            cell_size=cell_size,
            output_hdf_path=output_hdf_path,
            restrict_to_extent=restrict_to_extent,
            buffer_distance=buffer_distance,
        )

    @staticmethod
    @log_call
    def add_infiltration_layer(
        ras_project_path: Union[str, Path],
        infiltration_method: str = "scs_curve_number",
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        soil_layer_path: Optional[Union[str, Path]] = None,
        output_hdf_path: Optional[Union[str, Path]] = None,
        scs_reset_time_hours: Optional[float] = None,
        ras_object=None,
    ) -> Path:
        """
        Create and register an infiltration classification layer.
        """
        ras_project_path = Path(ras_project_path)
        landcover_hdf_path = (
            Path(landcover_hdf_path) if landcover_hdf_path is not None else None
        )
        soil_layer_path = Path(soil_layer_path) if soil_layer_path is not None else None
        output_hdf_path = Path(output_hdf_path) if output_hdf_path is not None else None
        from . import _land_classification_helper as _lch

        return _lch.add_infiltration_layer(
            ras_project_path=ras_project_path,
            infiltration_method=infiltration_method,
            landcover_hdf_path=landcover_hdf_path,
            soil_layer_path=soil_layer_path,
            output_hdf_path=output_hdf_path,
            scs_reset_time_hours=scs_reset_time_hours,
        )

    @staticmethod
    @log_call
    def associate_geometry_layers(
        ras_project_path: Union[str, Path],
        geom_file: Union[str, Path],
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        soil_layer_path: Optional[Union[str, Path]] = None,
        infiltration_hdf_path: Optional[Union[str, Path]] = None,
        terrain_hdf_path: Optional[Union[str, Path]] = None,
        sediment_soils_hdf_path: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> Path:
        """
        Associate terrain / classification layers to a compiled geometry HDF.

        This public workflow writes HEC-RAS ``/Geometry`` association
        attributes directly with h5py. Use
        ``RasProcess.validate_geometry_association_cli()`` only as an optional
        native-reference validator on disposable or intentionally mutated HDFs.

        ``soil_layer_path`` is retained for compatibility with the
        land-classification workflow. Use ``sediment_soils_hdf_path`` for the
        HEC-RAS ``SedimentSoilsFilename`` geometry association.
        """
        ras_project_path = Path(ras_project_path)
        geom_file = Path(geom_file)
        landcover_hdf_path = (
            Path(landcover_hdf_path) if landcover_hdf_path is not None else None
        )
        soil_layer_path = Path(soil_layer_path) if soil_layer_path is not None else None
        infiltration_hdf_path = (
            Path(infiltration_hdf_path) if infiltration_hdf_path is not None else None
        )
        terrain_hdf_path = (
            Path(terrain_hdf_path) if terrain_hdf_path is not None else None
        )
        sediment_soils_hdf_path = (
            Path(sediment_soils_hdf_path)
            if sediment_soils_hdf_path is not None
            else None
        )
        from . import _land_classification_helper as _lch

        return _lch.associate_geometry_layers(
            ras_project_path=ras_project_path,
            geom_file=geom_file,
            landcover_hdf_path=landcover_hdf_path,
            soil_layer_path=soil_layer_path,
            infiltration_hdf_path=infiltration_hdf_path,
            terrain_hdf_path=terrain_hdf_path,
            sediment_soils_hdf_path=sediment_soils_hdf_path,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def set_geometry_association(
        geom_number: Union[str, Path],
        terrain_hdf_path: Optional[Union[str, Path]] = None,
        landcover_hdf_path: Optional[Union[str, Path]] = None,
        infiltration_hdf_path: Optional[Union[str, Path]] = None,
        sediment_soils_hdf_path: Optional[Union[str, Path]] = None,
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
        validate: bool = True,
    ) -> Path:
        """
        Associate terrain / classification layers directly on a geometry HDF.
        """
        from .geom.GeomMesh import GeomMesh

        return GeomMesh.set_geometry_association(
            geom_number,
            terrain_hdf_path=terrain_hdf_path,
            landcover_hdf_path=landcover_hdf_path,
            infiltration_hdf_path=infiltration_hdf_path,
            sediment_soils_hdf_path=sediment_soils_hdf_path,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
            validate=validate,
        )

    @staticmethod
    @log_call
    def get_geometry_association(
        geom_number: Union[str, Path],
        hecras_dir: Optional[Union[str, Path]] = None,
        ras_object=None,
        resolve_paths: bool = True,
    ) -> dict:
        """
        Read terrain / classification associations from a geometry HDF.
        """
        from .geom.GeomMesh import GeomMesh

        return GeomMesh.get_geometry_association(
            geom_number,
            hecras_dir=hecras_dir,
            ras_object=ras_object,
            resolve_paths=resolve_paths,
        )

    @staticmethod
    @log_call
    def get_hdf_geometry_association(
        hdf_path: Union[str, Path],
        resolve_paths: bool = True,
        include_2d_area_attrs: bool = True,
        ras_object=None,
    ) -> dict:
        """
        Read ``/Geometry`` association attrs from a geometry, plan, or result HDF.

        This is read-only and intended for QA/QC workflows that need to audit
        terrain, land-cover, infiltration, or sediment bed-material links
        already stored in HEC-RAS HDF artifacts.
        """
        from ._geometry_association import read_geometry_association

        return read_geometry_association(
            hdf_path,
            resolve_paths=resolve_paths,
            include_2d_area_attrs=include_2d_area_attrs,
        )

    @staticmethod
    @log_call
    def recompute_property_tables(
        ras_project_path: Union[str, Path],
        geom_file: Union[str, Path],
        ras_object=None,
    ) -> Path:
        """
        Recompute geometry preprocessing and property tables for a compiled geometry.
        """
        ras_project_path = Path(ras_project_path)
        geom_file = Path(geom_file)
        from . import _land_classification_helper as _lch

        return _lch.recompute_property_tables(
            ras_project_path,
            geom_file,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def get_rasmap_path(ras_object=None) -> Optional[Path]:
        """
        Get the path to the .rasmap file based on the current project.

        Args:
            ras_object: Optional RAS object instance.

        Returns:
            Optional[Path]: Path to the .rasmap file if found, None otherwise.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        project_name = ras_obj.project_name
        project_folder = ras_obj.project_folder
        rasmap_path = project_folder / f"{project_name}.rasmap"

        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return None

        return rasmap_path

    @staticmethod
    @log_call
    def initialize_rasmap_df(ras_object=None) -> pd.DataFrame:
        """
        Initialize the rasmap_df as part of project initialization.

        Args:
            ras_object: Optional RAS object instance.

        Returns:
            pd.DataFrame: DataFrame containing information from the .rasmap file.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()
        from . import _land_classification_helper as _lch

        rasmap_path = RasMap.get_rasmap_path(ras_obj)
        if rasmap_path is None:
            logger.debug(
                "No .rasmap file found for this project. Creating empty rasmap_df."
            )
            return _lch.empty_rasmap_dataframe()

        return RasMap.parse_rasmap(rasmap_path, ras_obj)

    @staticmethod
    @log_call
    def get_terrain_names(rasmap_path: Union[str, Path]) -> List[str]:
        """
        Extracts terrain layer names from a given .rasmap file.

        Args:
            rasmap_path (Union[str, Path]): Path to the .rasmap file.

        Returns:
            List[str]: A list of terrain names.

        Raises:
            FileNotFoundError: If the rasmap file does not exist.
            ValueError: If the file is not a valid XML or lacks a 'Terrains' section.
        """
        rasmap_path = Path(rasmap_path)
        if not rasmap_path.is_file():
            raise FileNotFoundError(f"The file '{rasmap_path}' does not exist.")

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(
                f"Failed to parse the RASMAP file. Ensure it is a valid XML file. Error: {e}"
            )

        terrains_element = root.find("Terrains")
        if terrains_element is None:
            logger.debug("No Terrains section found in %s", rasmap_path.name)
            return []

        terrain_names = [
            layer.get("Name")
            for layer in terrains_element.findall("Layer")
            if layer.get("Name")
        ]
        logger.debug(
            "Found %d terrain layer(s) in %s: %s",
            len(terrain_names),
            rasmap_path.name,
            terrain_names,
        )
        return terrain_names

    @staticmethod
    @log_call
    def list_map_layers(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        as_dataframe: Optional[bool] = None,
        ras_object=None,
    ) -> Union[pd.DataFrame, List[Dict[str, Any]]]:
        """
        List top-level ``MapLayers`` entries in the RASMapper configuration.

        Args:
            ras_project_path: Project folder, .prj file, or .rasmap file. If omitted,
                the active project is used.
            as_dataframe: Return a DataFrame when True. When omitted, explicit
                ``ras_project_path`` calls return a DataFrame and legacy active-project
                calls return the historical list-of-dicts shape.
            ras_object: Optional RasPrj object instance.

        Returns:
            DataFrame with one row per top-level map layer, or legacy
            ``list[dict]`` when called in legacy mode.

        Examples:
            >>> from ras_commander import RasMap
            >>> layers = RasMap.list_map_layers("/path/to/project")
            >>> layers[["name", "type", "category", "filename"]]
        """
        from . import _rasmap_layer_helper as _mlh

        legacy_active_call = ras_project_path is None or (
            ras_object is None
            and ras_project_path is not None
            and hasattr(ras_project_path, "check_initialized")
        )
        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        layers = _mlh.list_map_layers(project_path)

        legacy_mode = as_dataframe is False or (
            as_dataframe is None and legacy_active_call
        )
        if legacy_mode:
            warnings.warn(
                "RasMap.list_map_layers() without an explicit project path returns "
                "the legacy list[dict] shape. Pass as_dataframe=True or an explicit "
                "project path for the DataFrame map-layer catalog.",
                FutureWarning,
                stacklevel=2,
            )
            return layers[["name", "type", "filename", "checked"]].to_dict(
                orient="records",
            )

        logger.debug("Found %d map layer(s) in .rasmap", len(layers))
        return layers

    @staticmethod
    @log_call
    def list_reference_map_layers(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List shapefile and GeoJSON reference map layers in a project ``.rasmap``.

        Reference map layers are top-level ``MapLayers/Layer`` entries with
        ``Type`` set to ``PointFeatureLayer``, ``PolylineFeatureLayer``, or
        ``PolygonFeatureLayer``.
        """
        from . import _rasmap_layer_helper as _mlh

        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        return _mlh.list_reference_map_layers(project_path)

    @staticmethod
    @log_call
    def list_basemap_layers(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """List WMS basemap layers registered in a project ``.rasmap``."""
        from . import _rasmap_layer_helper as _mlh

        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        return _mlh.list_basemap_layers(project_path)

    @staticmethod
    @log_call
    def set_map_layer_visibility(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        checked: bool = True,
        layer_name: Optional[Union[str, Sequence[str]]] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        category: Optional[Union[str, Sequence[str]]] = None,
        exclusive: bool = False,
        ras_object=None,
    ) -> int:
        """
        Toggle top-level RASMapper ``MapLayers`` entries.

        Targets reference maps, basemaps, land-classification layers, or other
        map-layer entries by name, type, or category. When no selector is
        supplied, all map layers are targeted. Use ``exclusive=True`` with
        ``checked=True`` to hide every non-matching map layer and show only the
        layers needed for a figure.
        """
        from . import _rasmap_layer_helper as _mlh

        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        return _mlh.set_map_layer_visibility(
            project_path,
            checked=checked,
            layer_name=layer_name,
            layer_type=layer_type,
            category=category,
            exclusive=exclusive,
        )

    @staticmethod
    @log_call
    def list_standard_basemap_layers() -> pd.DataFrame:
        """List standard HEC-RAS 6.x basemap layer names supported for insertion."""
        from . import _rasmap_layer_helper as _mlh

        return _mlh.list_available_basemaps()

    @staticmethod
    @log_call
    def add_reference_map_layer(
        ras_project_path: Optional[Union[str, Path]] = None,
        source_path: Optional[Union[str, Path]] = None,
        *,
        layer_name: Optional[str] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        checked: bool = True,
        label_field: Optional[str] = None,
        label_config: Optional[Dict[str, Any]] = None,
        symbology: Optional[Dict[str, Any]] = None,
        replace_existing: bool = True,
        validate_geojson_wgs84: bool = True,
        ras_object=None,
    ) -> Path:
        """
        Add or replace a shapefile/GeoJSON reference map layer in ``.rasmap``.

        GeoJSON sources are validated for RASMapper compatibility before the XML
        is changed. They must either declare WGS84/EPSG:4326 or have coordinate
        bounds consistent with WGS84 longitude/latitude.
        """
        if source_path is None:
            if ras_project_path is None:
                raise TypeError("source_path is required")
            source_path = ras_project_path
            ras_project_path = None

        from . import _rasmap_layer_helper as _mlh

        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        return _mlh.add_reference_map_layer(
            project_path,
            source_path,
            layer_name=layer_name,
            layer_type=layer_type,
            checked=checked,
            label_field=label_field,
            label_config=label_config,
            symbology=symbology,
            replace_existing=replace_existing,
            validate_geojson_wgs84=validate_geojson_wgs84,
        )

    @staticmethod
    @log_call
    def add_basemap_layer(
        ras_project_path: Optional[Union[str, Path]] = None,
        basemap_name: Optional[str] = None,
        *,
        checked: bool = True,
        replace_existing: bool = True,
        ras_object=None,
    ) -> Path:
        """
        Add or replace a standard HEC-RAS basemap layer in ``.rasmap``.

        Use :meth:`list_standard_basemap_layers` to discover valid names.
        """
        if basemap_name is None:
            if ras_project_path is None:
                raise TypeError("basemap_name is required")
            basemap_name = str(ras_project_path)
            ras_project_path = None

        from . import _rasmap_layer_helper as _mlh

        project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object=ras_object,
        )
        return _mlh.add_basemap_layer(
            project_path,
            basemap_name,
            checked=checked,
            replace_existing=replace_existing,
        )

    @staticmethod
    @log_call
    def add_map_layer(
        layer_name: str,
        layer_file: Union[str, Path],
        layer_type: str = "PolylineFeatureLayer",
        checked: bool = True,
        label_field: Optional[str] = None,
        label_config: Optional[Dict[str, Any]] = None,
        symbology: Optional[Dict[str, Any]] = None,
        replace_existing: bool = False,
        validate_geojson_wgs84: bool = True,
        ras_object=None,
    ) -> bool:
        """
        Add a reference map layer to the RASMapper configuration file.

        This legacy active-project method is retained for compatibility. New code
        should use :meth:`add_reference_map_layer`, which returns the modified
        ``.rasmap`` path and accepts an explicit project path.

        Args:
            layer_name: Display name for the layer in RASMapper.
            layer_file: Path to GeoJSON, shapefile, or other supported file.
            layer_type: RASMapper layer type:
                - "PolylineFeatureLayer" (default) - for lines (cross-sections)
                - "PolygonFeatureLayer" - for polygons
                - "PointFeatureLayer" - for points
            checked: Whether layer is visible by default (True).
            label_field: Field name to use for labels (e.g., "dss_path").
            label_config: Optional label configuration dict with keys:
                - "font_size": float (default 8.25)
                - "color": int (default -16777216 = black)
                - "position": int (0=center, 1=above, etc.)
            symbology: Optional symbology configuration dict with keys:
                - "line_color": tuple (R, G, B, A)
                - "line_width": int
                - "fill_color": tuple (R, G, B, A) for polygons
            replace_existing: Replace an existing reference layer with the same name.
                Default False preserves the historical append behavior.
            validate_geojson_wgs84: Raise if a GeoJSON source is not WGS84-compatible.
            ras_object: Optional RasPrj object instance.

        Returns:
            bool: True if layer was successfully added.

        Raises:
            FileNotFoundError: If .rasmap file doesn't exist.
            ValueError: If layer_file doesn't exist.

        Note:
            **GeoJSON files MUST be in WGS84 (EPSG:4326) coordinate system** for
            RASMapper to display them correctly. Always reproject your GeoDataFrame
            to WGS84 before saving:

            >>> gdf_wgs84 = gdf.to_crs("EPSG:4326")
            >>> gdf_wgs84.to_file("output.geojson", driver="GeoJSON")

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>>
            >>> # Add boundary conditions GeoJSON
            >>> RasMap.add_map_layer(
            ...     layer_name="Boundary Conditions",
            ...     layer_file="boundary_cross_sections.geojson",
            ...     label_field="dss_path"
            ... )
            >>>
            >>> # Add with custom symbology
            >>> RasMap.add_map_layer(
            ...     layer_name="BC Locations",
            ...     layer_file="bc_points.shp",
            ...     layer_type="PointFeatureLayer",
            ...     symbology={"line_color": (255, 0, 0, 255), "line_width": 2}
            ... )
        """
        warnings.warn(
            "RasMap.add_map_layer() is a legacy alias for reference layers. "
            "Use RasMap.add_reference_map_layer() for new workflows.",
            FutureWarning,
            stacklevel=2,
        )
        RasMap.add_reference_map_layer(
            None,
            layer_file,
            layer_name=layer_name,
            layer_type=layer_type,
            checked=checked,
            label_field=label_field,
            label_config=label_config,
            symbology=symbology,
            replace_existing=replace_existing,
            validate_geojson_wgs84=validate_geojson_wgs84,
            ras_object=ras_object,
        )
        return True

    @staticmethod
    @log_call
    def remove_map_layer(layer_name: str, ras_object=None) -> bool:
        """
        Remove a map layer from the RASMapper configuration file (.rasmap).

        Args:
            layer_name: Name of the layer to remove.
            ras_object: Optional RasPrj object instance.

        Returns:
            bool: True if layer was found and removed, False if not found.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> RasMap.remove_map_layer("Boundary Conditions")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return False

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return False

        map_layers = root.find("MapLayers")
        if map_layers is None:
            logger.warning("No MapLayers section found in .rasmap")
            return False

        # Find and remove layer by name
        for layer in map_layers.findall("Layer"):
            if layer.get("Name") == layer_name:
                map_layers.remove(layer)
                tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
                logger.info("Removed map layer '%s'", layer_name)
                logger.debug("Updated RASMapper file: %s", rasmap_path)
                return True

        logger.warning(f"Layer '{layer_name}' not found in .rasmap")
        return False

    @staticmethod
    @log_call
    def list_geometries(ras_object=None) -> List[Dict[str, Any]]:
        """
        List all geometry layers in the RASMapper configuration file.

        Args:
            ras_object: Optional RasPrj object instance.

        Returns:
            List[Dict[str, Any]]: List of dicts with geometry info:
                [{"name": str, "filename": str, "geom_number": str, "checked": bool}, ...]

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> geoms = RasMap.list_geometries()
            >>> for g in geoms:
            ...     print(f"{g['geom_number']}: {g['name']} - Visible: {g['checked']}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return []

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return []

        geometries_elem = root.find("Geometries")
        if geometries_elem is None:
            logger.debug("No Geometries section found in .rasmap")
            return []

        geometries = []
        for layer in geometries_elem.findall("Layer"):
            filename = layer.get("Filename", "")
            # Extract geometry number from filename (e.g., ".\BaldEagle.g08.hdf" -> "08")
            import re

            match = re.search(r"\.g(\d+)\.hdf", filename)
            geom_num = match.group(1) if match else ""

            geometries.append(
                {
                    "name": layer.get("Name", ""),
                    "filename": filename,
                    "geom_number": geom_num,
                    "checked": layer.get("Checked", "").lower() == "true",
                }
            )

        logger.debug("Found %d geometries in .rasmap", len(geometries))
        return geometries

    @staticmethod
    @log_call
    def set_geometry_visibility(
        geom_identifier: str, visible: bool = True, ras_object=None
    ) -> bool:
        """
        Set visibility of a specific geometry layer in RASMapper.

        Args:
            geom_identifier: Geometry to modify - can be:
                - Geometry name (e.g., "1D-2D Dam Break Model Refined Grid")
                - Geometry number (e.g., "08" or "g08")
                - Filename pattern (e.g., "g08.hdf")
            visible: True to show geometry, False to hide.
            ras_object: Optional RasPrj object instance.

        Returns:
            bool: True if geometry was found and modified.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> # Show geometry by number
            >>> RasMap.set_geometry_visibility("08", visible=True)
            >>> # Hide geometry by name
            >>> RasMap.set_geometry_visibility("Old Geometry", visible=False)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return False

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return False

        geometries_elem = root.find("Geometries")
        if geometries_elem is None:
            logger.warning("No Geometries section found in .rasmap")
            return False

        # Normalize identifier for matching
        identifier_lower = geom_identifier.lower().strip()
        # Handle "g08" -> "08" format
        if identifier_lower.startswith("g") and identifier_lower[1:].isdigit():
            identifier_lower = identifier_lower[1:]

        found = False
        for layer in geometries_elem.findall("Layer"):
            name = layer.get("Name", "")
            filename = layer.get("Filename", "")

            # Check if this layer matches the identifier
            matches = (
                name.lower() == identifier_lower
                or identifier_lower in filename.lower()
                or f".g{identifier_lower}." in filename.lower()
                or f".g{identifier_lower.zfill(2)}." in filename.lower()
            )

            if matches:
                layer.set("Checked", "True" if visible else "False")
                logger.info(f"Set geometry '{name}' visibility to {visible}")
                found = True
                break

        if found:
            tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
            return True
        else:
            logger.warning(f"Geometry '{geom_identifier}' not found in .rasmap")
            return False

    @staticmethod
    @log_call
    def set_all_geometries_visibility(
        visible: bool = False, except_geom: Optional[str] = None, ras_object=None
    ) -> int:
        """
        Set visibility for all geometry layers, optionally excluding one.

        This is useful for hiding all geometries except the one you want to display.

        Args:
            visible: True to show all geometries, False to hide all.
            except_geom: Optional geometry to exclude from visibility change.
                Can be geometry name, number (e.g., "08"), or filename pattern.
            ras_object: Optional RasPrj object instance.

        Returns:
            int: Number of geometries modified.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> # Hide all geometries except G08
            >>> RasMap.set_all_geometries_visibility(visible=False, except_geom="08")
            >>> # Then show only G08
            >>> RasMap.set_geometry_visibility("08", visible=True)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return 0

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return 0

        geometries_elem = root.find("Geometries")
        if geometries_elem is None:
            logger.warning("No Geometries section found in .rasmap")
            return 0

        # Normalize except identifier for matching
        except_lower = None
        if except_geom:
            except_lower = except_geom.lower().strip()
            if except_lower.startswith("g") and except_lower[1:].isdigit():
                except_lower = except_lower[1:]

        modified_count = 0
        for layer in geometries_elem.findall("Layer"):
            name = layer.get("Name", "")
            filename = layer.get("Filename", "")

            # Check if this is the exception geometry
            if except_lower:
                is_exception = (
                    name.lower() == except_lower
                    or except_lower in filename.lower()
                    or f".g{except_lower}." in filename.lower()
                    or f".g{except_lower.zfill(2)}." in filename.lower()
                )
                if is_exception:
                    # Set opposite visibility for exception
                    layer.set("Checked", "False" if visible else "True")
                    logger.debug(f"Exception: Set geometry '{name}' to {not visible}")
                    modified_count += 1
                    continue

            # Set visibility for all others
            layer.set("Checked", "True" if visible else "False")
            modified_count += 1

        if modified_count > 0:
            tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
            logger.info(f"Modified visibility for {modified_count} geometries")

        return modified_count

    @staticmethod
    @log_call
    def list_geometry_layers(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List top-level geometries and child geometry elements from ``.rasmap``.

        This is the discoverable RASMapper tree view for geometry automation.
        It includes both compiled geometry HDF entries and child elements such as
        ``RASXS``, ``RASD2FlowArea``, ``MeshPerimeterLayer``, and structure
        layers. Use this when deciding what to toggle before opening RASMapper or
        taking documentation screenshots.

        Args:
            ras_project_path: Project folder, ``.prj`` file, or ``.rasmap`` file.
                If omitted, the active ``RasPrj`` object is used.
            ras_object: Optional ``RasPrj`` object instance.

        Returns:
            pd.DataFrame: One row per top-level geometry and child geometry
                element, including layer id, layer type, visibility state, and
                resolved geometry HDF path.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.list_geometry_layers(resolved_project_path)

    @staticmethod
    @log_call
    def set_geometry_layer_visibility(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        checked: bool = True,
        layer_id: Optional[str] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        layer_name: Optional[str] = None,
        geometry_name: Optional[str] = None,
        geometry_number: Optional[str] = None,
        exclusive: bool = False,
        ras_object=None,
    ) -> int:
        """
        Toggle child geometry elements in the RASMapper tree.

        This complements ``set_geometry_visibility()``, which toggles a whole
        compiled geometry. ``set_geometry_layer_visibility()`` targets child
        elements inside that geometry, such as cross sections, 2D flow areas,
        mesh perimeters, and structures.

        Args:
            ras_project_path: Project folder, ``.prj`` file, or ``.rasmap`` file.
                If omitted, the active ``RasPrj`` object is used.
            checked: ``True`` to show matching elements, ``False`` to hide them.
            layer_id: Stable id from ``list_geometry_layers()``.
            layer_type: RASMapper child layer type, such as ``"RASD2FlowArea"``,
                or a sequence of layer types for combined QA views.
            layer_name: Optional child layer display name.
            geometry_name: Optional parent geometry display name filter.
            geometry_number: Optional parent geometry number filter, such as
                ``"04"`` or ``"g04"``.
            exclusive: If ``True``, hide all geometries and child elements first,
                then show only the matching parent geometry and selected child
                element. This is useful for screenshot workflows.
            ras_object: Optional ``RasPrj`` object instance.

        Returns:
            int: Number of XML visibility attributes modified.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_geometry_layer_visibility(
            resolved_project_path,
            checked=checked,
            layer_id=layer_id,
            layer_type=layer_type,
            layer_name=layer_name,
            geometry_name=geometry_name,
            geometry_number=geometry_number,
            exclusive=exclusive,
        )

    @staticmethod
    @log_call
    def list_result_layers(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List RASMapper result plans and child result layers.

        The returned DataFrame includes the top-level ``RASResults`` plan rows
        and nested result layers such as depth, WSE, velocity, or calculated
        layers, with their current visibility state.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.list_result_layers(resolved_project_path)

    @staticmethod
    @log_call
    def set_result_layer_visibility(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        checked: bool = True,
        layer_id: Optional[str] = None,
        plan_name: Optional[Union[str, Sequence[str]]] = None,
        layer_name: Optional[Union[str, Sequence[str]]] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        exclusive: bool = False,
        ras_object=None,
    ) -> int:
        """
        Toggle RASMapper result plans and child result layers.

        When no selector is supplied, all result layers are targeted. Use
        ``exclusive=True`` with ``checked=True`` to hide every non-matching
        result layer and show only the selected result plan or map type needed
        for a figure.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_result_layer_visibility(
            resolved_project_path,
            checked=checked,
            layer_id=layer_id,
            plan_name=plan_name,
            layer_name=layer_name,
            layer_type=layer_type,
            exclusive=exclusive,
        )

    @staticmethod
    @log_call
    def list_geometry_features(
        geometry_hdf_path: Union[str, Path],
        *,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
    ) -> pd.DataFrame:
        """
        List HDF geometry features for supported RASMapper layers.

        This is more granular than ``list_geometry_layers()``. It exposes
        feature names, indexes, and bounds for objects such as 2D
        flow areas, lateral structures, breaklines, and cross sections.
        """
        from . import _rasmap_control_helper as _rch

        return _rch.list_geometry_features(
            geometry_hdf_path,
            layer_type=layer_type,
        )

    @staticmethod
    @log_call
    def get_current_view(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Read the ``CurrentView`` bounds from a project ``.rasmap`` file.

        Bounds are in the project/RASMapper coordinate system. The returned
        dictionary also includes the resolved projection file path when the
        ``.rasmap`` references one.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.get_current_view(resolved_project_path)

    @staticmethod
    @log_call
    def set_current_view(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        min_x: float,
        min_y: float,
        max_x: float,
        max_y: float,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Write the ``CurrentView`` bounds in a project ``.rasmap`` file.

        Use this before launching standalone RASMapper when you want a
        deterministic documentation or QA/QC viewport.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_current_view(
            resolved_project_path,
            min_x=min_x,
            min_y=min_y,
            max_x=max_x,
            max_y=max_y,
        )

    @staticmethod
    @log_call
    def set_terrain_layer_visibility(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        terrain_name: Optional[str] = None,
        checked: bool = True,
        exclusive: bool = False,
        surface_on: bool = True,
        ras_object=None,
    ) -> int:
        """
        Toggle RASMapper terrain-layer visibility in a project ``.rasmap``.

        Args:
            ras_project_path: Project folder, ``.prj`` file, or ``.rasmap`` file.
                If omitted, the active ``RasPrj`` object is used.
            terrain_name: Optional terrain layer display name. When omitted, all
                terrain layers are targeted.
            checked: ``True`` to show matching terrain layers.
            exclusive: If ``True``, hide non-matching terrain layers first.
            surface_on: Keep the terrain ``<Surface On="...">`` state aligned
                with the checked state.
            ras_object: Optional ``RasPrj`` object instance.

        Returns:
            int: Number of XML attributes/elements modified.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_terrain_layer_visibility(
            resolved_project_path,
            terrain_name=terrain_name,
            checked=checked,
            exclusive=exclusive,
            surface_on=surface_on,
        )

    @staticmethod
    @log_call
    def list_terrain_display_settings(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        terrain_name: Optional[str] = None,
        ras_object=None,
    ) -> pd.DataFrame:
        """
        List terrain display settings persisted in a project ``.rasmap`` file.

        The returned DataFrame includes hillshade, contour, and stitch-edge
        display controls for each ``Type="TerrainLayer"`` entry. These settings
        are read directly from RASMapper XML; no GUI automation is used.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.list_terrain_display_settings(
            resolved_project_path,
            terrain_name=terrain_name,
        )

    @staticmethod
    @log_call
    def get_terrain_display_settings(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        terrain_name: Optional[str] = None,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Read persisted terrain display settings for one terrain layer.

        Provide ``terrain_name`` when the project has multiple terrain layers.
        The name match uses the RASMapper display name.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.get_terrain_display_settings(
            resolved_project_path,
            terrain_name=terrain_name,
        )

    @staticmethod
    @log_call
    def set_terrain_display_settings(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        terrain_name: Optional[str] = None,
        hillshade_enabled: Optional[bool] = None,
        hillshade_z_factor: Optional[float] = None,
        contour_enabled: Optional[bool] = None,
        contour_interval: Optional[float] = None,
        stitch_edges_enabled: Optional[bool] = None,
        stitch_tin_edges_enabled: Optional[bool] = None,
        level0_stitch_edges_enabled: Optional[bool] = None,
        level0_stitch_tin_edges_enabled: Optional[bool] = None,
        remove_stitch_rendering_enabled: Optional[bool] = None,
        ras_object=None,
    ) -> int:
        """
        Write persisted terrain display settings in a project ``.rasmap`` file.

        Args:
            ras_project_path: Project folder, ``.prj`` file, or ``.rasmap`` file.
                If omitted, the active ``RasPrj`` object is used.
            terrain_name: Optional terrain layer display name. When omitted, all
                terrain layers are targeted.
            hillshade_enabled: Toggle ``Symbology/HillShade`` display.
            hillshade_z_factor: Set the hillshade Z factor where persisted.
            contour_enabled: Toggle ``Symbology/Contour`` display.
            contour_interval: Set the contour interval where persisted.
            stitch_edges_enabled: Toggle ``Plot stitch TIN edges``.
            level0_stitch_edges_enabled: Toggle ``Plot Level0 stitch TIN edges``.
            remove_stitch_rendering_enabled: Toggle ``Remove Stitch Rendering``.
            ras_object: Optional ``RasPrj`` object instance.

        Returns:
            int: Number of XML attributes/elements modified.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_terrain_display_settings(
            resolved_project_path,
            terrain_name=terrain_name,
            hillshade_enabled=hillshade_enabled,
            hillshade_z_factor=hillshade_z_factor,
            contour_enabled=contour_enabled,
            contour_interval=contour_interval,
            stitch_edges_enabled=stitch_edges_enabled,
            stitch_tin_edges_enabled=stitch_tin_edges_enabled,
            level0_stitch_edges_enabled=level0_stitch_edges_enabled,
            level0_stitch_tin_edges_enabled=level0_stitch_tin_edges_enabled,
            remove_stitch_rendering_enabled=remove_stitch_rendering_enabled,
        )

    @staticmethod
    @log_call
    def set_update_legend_with_view(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        checked: bool = True,
        include_results: bool = True,
        include_terrain: bool = True,
        include_geometry: bool = False,
        include_map_layers: bool = False,
        ras_object=None,
    ) -> int:
        """
        Set RASMapper ``Update Legend with View`` for raster surface fills.

        RASMapper persists this checkbox as ``RegenerateForScreen`` on
        ``SurfaceFill`` XML elements. By default this targets result layers and
        terrain layers, which are the surfaces most commonly used in inspection
        screenshots.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.set_update_legend_with_view(
            resolved_project_path,
            checked=checked,
            include_results=include_results,
            include_terrain=include_terrain,
            include_geometry=include_geometry,
            include_map_layers=include_map_layers,
        )

    @staticmethod
    @log_call
    def get_geometry_layer_bounds(
        geometry_hdf_path: Union[str, Path],
        *,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Read HDF-derived bounds for a compiled geometry or geometry element.

        Args:
            geometry_hdf_path: Path to a compiled ``.g##.hdf`` file.
            layer_type: Optional RASMapper child layer type. When omitted, bounds
                are computed from all recognized geometry coordinate datasets.

        Returns:
            Dict[str, Any]: Bounds, source dataset paths, and point count.
        """
        from . import _rasmap_control_helper as _rch

        return _rch.geometry_layer_bounds(
            geometry_hdf_path,
            layer_type=layer_type,
        )

    @staticmethod
    @log_call
    def get_geometry_feature_bounds(
        geometry_hdf_path: Union[str, Path],
        *,
        layer_type: str,
        feature_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        feature_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Read HDF-derived bounds for a selected geometry feature.

        Select the feature with ``feature_id`` from ``list_geometry_features()``,
        a display name, or a zero-based feature index.
        """
        from . import _rasmap_control_helper as _rch

        return _rch.geometry_feature_bounds(
            geometry_hdf_path,
            layer_type=layer_type,
            feature_id=feature_id,
            feature_name=feature_name,
            feature_index=feature_index,
        )

    @staticmethod
    @log_call
    def zoom_to_geometry_layer(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        layer_id: Optional[str] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        layer_name: Optional[str] = None,
        geometry_name: Optional[str] = None,
        geometry_number: Optional[str] = None,
        feature_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        feature_index: Optional[int] = None,
        padding_fraction: Optional[float] = None,
        min_padding: float = 0.0,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Set ``CurrentView`` to the HDF-derived extent of a geometry element.

        Select the target with a ``layer_id`` from ``list_geometry_layers()`` or
        with a combination of parent geometry and child layer filters. Pass a
        sequence to ``layer_type`` to zoom to the combined extent of multiple
        geometry elements. To center the viewport on one feature inside a layer,
        pass ``feature_id``, ``feature_name``, or ``feature_index``; the layer
        stays visible, but the viewport is centered on that feature. When
        ``padding_fraction`` is omitted, layer views use 5% per-side padding and
        feature views use 25% per-side padding, which expands the feature extent
        by 50% overall for surrounding mesh context.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.zoom_to_geometry_layer(
            resolved_project_path,
            layer_id=layer_id,
            layer_type=layer_type,
            layer_name=layer_name,
            geometry_name=geometry_name,
            geometry_number=geometry_number,
            feature_id=feature_id,
            feature_name=feature_name,
            feature_index=feature_index,
            padding_fraction=padding_fraction,
            min_padding=min_padding,
        )

    @staticmethod
    @log_call
    def open_rasmapper(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        rasmapper_exe_path: Optional[Union[str, Path]] = None,
        ras_version: Optional[str] = None,
        wait: bool = False,
        ras_object=None,
    ) -> subprocess.Popen:
        """
        Launch standalone ``RasMapper.exe`` directly against the project ``.rasmap``.

        This avoids HEC-RAS menu automation. It is intended for inspection and
        documentation workflows after the ``.rasmap`` view/layer state has been
        configured.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.open_rasmapper(
            resolved_project_path,
            rasmapper_exe_path=rasmapper_exe_path,
            ras_version=ras_version,
            ras_object=ras_object,
            wait=wait,
        )

    @staticmethod
    @log_call
    def capture_rasmapper_snapshot(
        *,
        pid: Optional[int] = None,
        output_path: Optional[Union[str, Path]] = None,
        delay_seconds: float = 1.0,
        timeout_seconds: float = 1800.0,
        poll_interval_seconds: float = 0.5,
    ) -> Optional[Path]:
        """
        Capture a visible standalone RASMapper window to PNG.

        Args:
            pid: Optional RASMapper process id returned by ``open_rasmapper()``.
            output_path: Optional PNG output path.
            delay_seconds: Initial delay before capture polling starts.
            timeout_seconds: Maximum time to wait for a visible RASMapper window.
                Defaults to 1800 seconds because large projects can take many
                minutes to open in RASMapper.
            poll_interval_seconds: Window polling interval.

        Returns:
            Optional[Path]: Screenshot path, or ``None`` if no window was found.
        """
        from . import _rasmap_control_helper as _rch

        return _rch.capture_rasmapper_snapshot(
            pid=pid,
            output_path=output_path,
            delay_seconds=delay_seconds,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    @staticmethod
    @log_call
    def close_rasmapper(*, pid: Optional[int] = None) -> int:
        """
        Close visible standalone RASMapper windows.

        Args:
            pid: Optional process id to restrict which RASMapper window is closed.

        Returns:
            int: Number of visible RASMapper windows sent a close message.
        """
        from . import _rasmap_control_helper as _rch

        return _rch.close_rasmapper(pid=pid)

    @staticmethod
    @log_call
    def screenshot_model(
        ras_project_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        *,
        delay_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
        ras_version: Optional[str] = None,
        configure_layers: bool = True,
    ) -> Optional[Path]:
        """
        One-call screenshot: backup rasmap, open RASMapper, capture, close, restore.

        This is a convenience wrapper around ``open_rasmapper``,
        ``capture_rasmapper_snapshot``, and ``close_rasmapper`` for the
        common case of capturing a model's current RASMapper view.

        Args:
            ras_project_path: Path to the .prj file (no init_ras_project needed).
            output_path: Where to save the PNG. Defaults to
                ``{project_folder}/{project_name}_screenshot.png``.
            delay_seconds: Wait time for RASMapper to render before capture.
            timeout_seconds: Max time to wait for RASMapper window.
            ras_version: HEC-RAS version for finding RASMapper.exe.
            configure_layers: If True (default), enable terrain and geometry layers
                in the .rasmap before opening RASMapper so the screenshot shows
                model content. The original .rasmap is restored afterward.

        Returns:
            Path to the saved PNG, or None if capture failed.
        """
        import shutil
        from . import _rasmap_control_helper as _rch

        prj_path = Path(ras_project_path)
        project_folder = prj_path.parent
        project_name = prj_path.stem
        rasmap_path = project_folder / f"{project_name}.rasmap"

        # Backup .rasmap
        rasmap_backup = None
        if rasmap_path.exists():
            rasmap_backup = rasmap_path.with_suffix(".rasmap.screenshot_bak")
            shutil.copy2(rasmap_path, rasmap_backup)

        # Enable terrain and geometry layers and zoom view to the model extent so
        # the screenshot is not blank.  Errors are suppressed — the original .rasmap
        # is restored in the finally block regardless.
        if configure_layers and rasmap_path.exists():
            try:
                _rch.set_terrain_layer_visibility(rasmap_path, checked=True)
            except Exception:
                pass
            try:
                _rch.set_geometry_layer_visibility(rasmap_path, checked=True)
            except Exception:
                pass
            try:
                _rch.zoom_to_geometry_layer(rasmap_path)
            except Exception:
                pass

        # Default output path
        if output_path is None:
            output_path = project_folder / f"{project_name}_screenshot.png"
        output_path = Path(output_path)

        screenshot_result = None
        try:
            proc = _rch.open_rasmapper(
                prj_path,
                ras_version=ras_version,
                wait=False,
            )
            pid = proc.pid if proc else None

            screenshot_result = _rch.capture_rasmapper_snapshot(
                pid=pid,
                output_path=output_path,
                delay_seconds=delay_seconds,
                timeout_seconds=timeout_seconds,
            )

            _rch.close_rasmapper(pid=pid)
        finally:
            # Restore .rasmap from backup
            if rasmap_backup and rasmap_backup.exists():
                shutil.copy2(rasmap_backup, rasmap_path)
                rasmap_backup.unlink()

        if screenshot_result and screenshot_result.exists():
            logger.info("Screenshot saved: %s", screenshot_result.name)
            logger.debug("Screenshot path: %s", screenshot_result)
        else:
            logger.warning("Screenshot capture returned no file")

        return screenshot_result

    @staticmethod
    @log_call
    def screenshot_model_gallery(
        models: List[Tuple[Union[str, Path], str]],
        output_dir: Union[str, Path],
        *,
        delay_seconds: float = 5.0,
        timeout_seconds: float = 1800.0,
        ras_version: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Capture screenshots of multiple models into a gallery directory.

        Args:
            models: List of (project_path, label) tuples. Each project_path
                is a .prj file; label is used for the output filename.
            output_dir: Directory for all screenshots.
            delay_seconds: Render wait per model.
            timeout_seconds: Max wait per model.
            ras_version: HEC-RAS version for finding RASMapper.exe.

        Returns:
            List of dicts with keys: label, project_path, screenshot_path, success.
        """
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        results = []
        for project_path, label in models:
            safe_label = "".join(c if c.isalnum() or c in "-_ " else "_" for c in label)
            png_path = out / f"{safe_label}.png"

            try:
                result_path = RasMap.screenshot_model(
                    project_path,
                    output_path=png_path,
                    delay_seconds=delay_seconds,
                    timeout_seconds=timeout_seconds,
                    ras_version=ras_version,
                )
                results.append(
                    {
                        "label": label,
                        "project_path": str(project_path),
                        "screenshot_path": str(result_path) if result_path else None,
                        "success": result_path is not None and result_path.exists(),
                    }
                )
            except Exception as e:
                logger.error(f"Failed to screenshot '{label}': {e}")
                results.append(
                    {
                        "label": label,
                        "project_path": str(project_path),
                        "screenshot_path": None,
                        "success": False,
                    }
                )

        successful = sum(1 for r in results if r["success"])
        logger.info(
            "Screenshot gallery complete: %s/%s captured", successful, len(models)
        )
        logger.debug("Screenshot gallery output directory: %s", out)
        return results

    @staticmethod
    @log_call
    def create_spatial_review_package(
        ras_project_path: Optional[Union[str, Path]] = None,
        *,
        output_dir: Optional[Union[str, Path]] = None,
        geometry_number: Optional[str] = None,
        geometry_name: Optional[str] = None,
        layer_type: Optional[Union[str, Sequence[str]]] = None,
        layer_name: Optional[str] = None,
        feature_id: Optional[str] = None,
        feature_name: Optional[str] = None,
        feature_index: Optional[int] = None,
        terrain_name: Optional[str] = None,
        result_plan_name: Optional[Union[str, Sequence[str]]] = None,
        result_layer_name: Optional[Union[str, Sequence[str]]] = None,
        result_layer_type: Optional[Union[str, Sequence[str]]] = None,
        map_layer_name: Optional[Union[str, Sequence[str]]] = None,
        map_layer_type: Optional[Union[str, Sequence[str]]] = None,
        map_layer_category: Optional[Union[str, Sequence[str]]] = None,
        include_terrain: bool = True,
        include_results: bool = False,
        include_map_layers: bool = False,
        exclusive_geometry: bool = True,
        exclusive_terrain: bool = True,
        exclusive_results: bool = True,
        exclusive_map_layers: bool = True,
        update_legend_with_view: bool = True,
        zoom_to_layer: bool = True,
        padding_fraction: Optional[float] = None,
        min_padding: float = 0.0,
        capture_snapshot: bool = False,
        snapshot_filename: str = "rasmapper_spatial_review.png",
        delay_seconds: float = 5.0,
        snapshot_timeout_seconds: float = 1800.0,
        snapshot_poll_interval_seconds: float = 0.5,
        close_after_capture: bool = True,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        dpi: Optional[int] = None,
        expanded_tree_paths: Optional[Sequence[str]] = None,
        ramp_id: Optional[str] = None,
        range_mode: Optional[str] = None,
        selected_layer: Optional[str] = None,
        result_profile: Optional[str] = None,
        render_mode: Optional[str] = None,
        basemap: Optional[str] = None,
        web_manifest_url: Optional[str] = None,
        rasmapper_exe_path: Optional[Union[str, Path]] = None,
        ras_version: Optional[str] = None,
        strict_preflight: bool = True,
        require_snapshot: bool = False,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Build a deterministic RASMapper spatial QA/QC evidence bundle.

        The bundle records before/after ``.rasmap`` state, layer catalogs,
        preflight checks, view/zoom metadata, and a findings template. It is
        headless by default; pass ``capture_snapshot=True`` to launch standalone
        RASMapper and add a screenshot on a Windows review machine. The
        ``snapshot_timeout_seconds`` parameter defaults to 1800 seconds and can
        be shortened for smoke tests or lengthened for very large projects.
        Feature-focused views keep the full RASMapper layer visible and center
        on the selected HDF feature, with 50% overall viewport expansion by
        default for surrounding mesh and terrain context. Result and map layers
        are hidden by default unless included or selected, which keeps review
        figures deterministic.
        """
        from . import _rasmap_control_helper as _rch

        resolved_project_path = _resolve_optional_ras_project_path(
            ras_project_path,
            ras_object,
        )
        return _rch.create_spatial_review_package(
            resolved_project_path,
            output_dir=output_dir,
            geometry_number=geometry_number,
            geometry_name=geometry_name,
            layer_type=layer_type,
            layer_name=layer_name,
            feature_id=feature_id,
            feature_name=feature_name,
            feature_index=feature_index,
            terrain_name=terrain_name,
            result_plan_name=result_plan_name,
            result_layer_name=result_layer_name,
            result_layer_type=result_layer_type,
            map_layer_name=map_layer_name,
            map_layer_type=map_layer_type,
            map_layer_category=map_layer_category,
            include_terrain=include_terrain,
            include_results=include_results,
            include_map_layers=include_map_layers,
            exclusive_geometry=exclusive_geometry,
            exclusive_terrain=exclusive_terrain,
            exclusive_results=exclusive_results,
            exclusive_map_layers=exclusive_map_layers,
            update_legend_with_view=update_legend_with_view,
            zoom_to_layer=zoom_to_layer,
            padding_fraction=padding_fraction,
            min_padding=min_padding,
            capture_snapshot=capture_snapshot,
            snapshot_filename=snapshot_filename,
            delay_seconds=delay_seconds,
            snapshot_timeout_seconds=snapshot_timeout_seconds,
            snapshot_poll_interval_seconds=snapshot_poll_interval_seconds,
            close_after_capture=close_after_capture,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            dpi=dpi,
            expanded_tree_paths=expanded_tree_paths,
            ramp_id=ramp_id,
            range_mode=range_mode,
            selected_layer=selected_layer,
            result_profile=result_profile,
            render_mode=render_mode,
            basemap=basemap,
            web_manifest_url=web_manifest_url,
            rasmapper_exe_path=rasmapper_exe_path,
            ras_version=ras_version,
            strict_preflight=strict_preflight,
            require_snapshot=require_snapshot,
            ras_object=ras_object,
        )

    @staticmethod
    @log_call
    def ensure_rasmap_compatible(ras_object=None, auto_upgrade=True) -> Dict[str, Any]:
        """
        Ensure .rasmap file is compatible with current HEC-RAS version.

        For HEC-RAS 5.0.7 projects opened in HEC-RAS 6.x, the .rasmap file needs to be
        upgraded to the 6.x format (adds <Results> section). This function detects
        version incompatibility and attempts automatic upgrade via GUI automation.

        Args:
            ras_object: Optional RasPrj object instance (default: global ras).
            auto_upgrade (bool): If True, attempt automatic upgrade via GUI automation.
                If False, only detect version and return status without upgrading.

        Returns:
            Dict[str, Any]: Status dictionary with keys:
                - 'status' (str): One of:
                    - 'ready': .rasmap is already compatible
                    - 'upgraded': Successfully upgraded .rasmap file
                    - 'manual_needed': Upgrade required but auto-upgrade failed
                - 'message' (str): Human-readable status message
                - 'version' (str): Detected .rasmap version (e.g., "5.0.7", "7.0")

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>>
            >>> # Check compatibility (auto-upgrade if needed)
            >>> result = RasMap.ensure_rasmap_compatible(auto_upgrade=True)
            >>> print(result['status'])  # 'ready', 'upgraded', or 'manual_needed'
            >>>
            >>> # Check only (no auto-upgrade)
            >>> result = RasMap.ensure_rasmap_compatible(auto_upgrade=False)

        Notes:
            - Detection Logic:
                * Parses .rasmap XML for <Version> element
                * Checks for <Results> section (present in 6.x, missing in 5.0.7)
                * Upgrade needed if version starts with "5." AND no <Results> section

            - Auto-upgrade Process (if auto_upgrade=True):
                * Opens HEC-RAS with the project
                * Uses GUI automation to click "GIS Tools" > "RAS Mapper"
                * Waits for RASMapper to open (triggers .rasmap upgrade dialog)
                * Closes RASMapper and HEC-RAS
                * Verifies upgrade by re-parsing .rasmap

            - Integration:
                * Called automatically by postprocess_stored_maps()
                * Should be called before RasProcess.store_maps() workflows
                * Always needed before RasProcess.store_maps()
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get .rasmap path
        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"

        if not rasmap_path.exists():
            logger.warning(f"No .rasmap file found: {rasmap_path}")
            return {
                "status": "manual_needed",
                "message": f"No .rasmap file found at {rasmap_path}",
                "version": None,
            }

        # Parse .rasmap XML to detect version
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Extract version
            version_elem = root.find("Version")
            version = version_elem.text if version_elem is not None else "unknown"

            # Check for Results section (present in 6.x, missing in 5.0.7)
            results_elem = root.find("Results")

            # Determine if upgrade needed
            needs_upgrade = (
                version.startswith("5.")  # Old version number
                and results_elem is None  # Missing modern Results section
            )

            if not needs_upgrade:
                logger.debug(".rasmap file is already compatible (version %s)", version)
                return {
                    "status": "ready",
                    "message": f"Already compatible (version {version})",
                    "version": version,
                }

            logger.info(f".rasmap file needs upgrade from version {version}")

        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return {
                "status": "manual_needed",
                "message": f"XML parse error: {e}",
                "version": None,
            }

        # If upgrade not needed or auto_upgrade disabled, return status
        if not auto_upgrade:
            return {
                "status": "manual_needed",
                "message": f"Upgrade needed from version {version} (auto_upgrade=False)",
                "version": version,
            }

        # Attempt GUI automation to upgrade .rasmap
        logger.info("Attempting automatic .rasmap upgrade via GUI automation...")

        try:
            # Import GUI automation (lazy import to avoid dependencies if not needed)
            try:
                import win32gui
                import win32con
                import time
                import subprocess
                import sys
            except ImportError as e:
                logger.error(f"GUI automation requires win32gui: {e}")
                return {
                    "status": "manual_needed",
                    "message": f"GUI automation requires pywin32 package: {e}",
                    "version": version,
                }

            # Open HEC-RAS with project
            ras_exe = ras_obj.ras_exe_path
            prj_path = str(ras_obj.prj_file)

            logger.debug("Opening HEC-RAS for .rasmap upgrade")
            logger.debug("HEC-RAS upgrade command: %s %s", ras_exe, prj_path)

            if sys.platform == "win32":
                process = subprocess.Popen(f'"{ras_exe}" "{prj_path}"')
            else:
                raise RuntimeError("GUI automation only supported on Windows")

            # Wait for HEC-RAS main window to appear
            time.sleep(5)  # Initial wait

            # Find HEC-RAS main window
            hecras_hwnd = None
            for _ in range(30):  # Try for up to 30 seconds
                hecras_hwnd = win32gui.FindWindow(
                    None, f"HEC-RAS {ras_obj.ras_version}"
                )
                if hecras_hwnd:
                    break
                time.sleep(1)

            if not hecras_hwnd:
                logger.error("Could not find HEC-RAS window")
                process.terminate()
                return {
                    "status": "manual_needed",
                    "message": "HEC-RAS window not found (GUI automation failed)",
                    "version": version,
                }

            logger.debug("Found HEC-RAS window handle: %s", hecras_hwnd)

            # Helper function to find RASMapper window
            def find_rasmapper_window():
                """Find any RAS Mapper window"""

                def callback(hwnd, windows):
                    if win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(
                        hwnd
                    ):
                        try:
                            window_title = win32gui.GetWindowText(hwnd)
                            if "RAS Mapper" in window_title:
                                windows.append((hwnd, window_title))
                        except:
                            pass
                    return True

                windows = []
                win32gui.EnumWindows(callback, windows)
                return windows

            # Helper function to wait for window to appear
            def wait_for_window(find_window_func, timeout=90, check_interval=2):
                """Wait for a window to appear"""
                start_time = time.time()
                while time.time() - start_time < timeout:
                    windows = find_window_func()
                    if windows:
                        return windows
                    time.sleep(check_interval)
                return None

            # Helper function to close RASMapper
            def close_rasmapper():
                """Close RASMapper window"""
                windows = find_rasmapper_window()
                for hwnd, title in windows:
                    try:
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        logger.debug(f"Sent WM_CLOSE to RASMapper window: {title}")
                        return True
                    except:
                        pass
                return False

            # Step 1: Open RASMapper via menu
            logger.debug("Opening RASMapper via menu")
            win32gui.SetForegroundWindow(hecras_hwnd)
            time.sleep(0.5)

            # Enumerate menus to find "GIS Tools" > "RAS Mapper"
            menu_bar = win32gui.GetMenu(hecras_hwnd)
            if menu_bar:
                menu_count = win32gui.GetMenuItemCount(menu_bar)
                rasmapper_found = False

                for i in range(menu_count):
                    submenu = win32gui.GetSubMenu(menu_bar, i)
                    if submenu:
                        submenu_count = win32gui.GetMenuItemCount(submenu)
                        for j in range(submenu_count):
                            try:
                                # Get menu item info
                                menu_id = win32gui.GetMenuItemID(submenu, j)
                                # Try to get menu string (may not work for all items)

                                # For RASMapper, we'll try a different approach
                                # Send the menu command for typical RASMapper menu ID
                                # This varies by version, so we'll try clicking and checking
                                if menu_id > 0:
                                    # Try sending this menu command
                                    win32gui.PostMessage(
                                        hecras_hwnd, win32con.WM_COMMAND, menu_id, 0
                                    )
                                    time.sleep(1)

                                    # Check if RASMapper opened
                                    if find_rasmapper_window():
                                        logger.debug(
                                            "RASMapper opened successfully via menu"
                                        )
                                        rasmapper_found = True
                                        break
                            except:
                                continue
                        if rasmapper_found:
                            break

                # Fallback: Try keyboard shortcut
                if not rasmapper_found:
                    logger.debug("Menu enumeration failed, trying keyboard shortcut")
                    import win32api

                    win32api.keybd_event(0x12, 0, 0, 0)  # Alt down
                    time.sleep(0.1)
                    win32api.keybd_event(ord("G"), 0, 0, 0)  # G
                    time.sleep(0.1)
                    win32api.keybd_event(0x12, 0, 0x0002, 0)  # Alt up
                    time.sleep(0.5)
                    win32api.keybd_event(ord("M"), 0, 0, 0)  # M for Mapper
                    time.sleep(0.1)

            # Step 2: Wait for RASMapper window to appear (60-90 second timeout)
            logger.debug("Waiting for RASMapper to open (up to 90 seconds)")
            rasmapper_windows = wait_for_window(
                find_rasmapper_window, timeout=90, check_interval=2
            )

            if not rasmapper_windows:
                logger.error("RASMapper window did not appear within timeout")
                return {
                    "status": "manual_needed",
                    "message": "RASMapper window did not open automatically. Please open RASMapper manually.",
                    "version": version,
                }

            logger.debug("RASMapper opened")
            logger.debug("RASMapper window title: %s", rasmapper_windows[0][1])

            # Step 3: Wait 2 additional seconds for .rasmap file write
            logger.debug("Allowing time for .rasmap update")
            time.sleep(2)

            # Step 4: Close RASMapper cleanly (with retry)
            logger.debug("Attempting to close RASMapper")
            close_attempts = 0
            max_attempts = 10

            while close_attempts < max_attempts:
                if close_rasmapper():
                    logger.debug("Sent close message to RASMapper")
                    break
                logger.debug(
                    f"Retry {close_attempts+1}/{max_attempts} to close RASMapper..."
                )
                time.sleep(2)
                close_attempts += 1

            if close_attempts >= max_attempts:
                logger.warning("Could not send close message to RASMapper")

            # Step 5: Wait until RASMapper is fully closed
            logger.debug("Waiting for RASMapper to fully close")
            close_wait_start = time.time()
            close_timeout = 30

            while time.time() - close_wait_start < close_timeout:
                if not find_rasmapper_window():
                    logger.debug("RASMapper closed successfully")
                    break
                logger.debug("Waiting for RASMapper to fully close...")
                time.sleep(2)

            # Step 6: Close HEC-RAS
            logger.debug("Closing HEC-RAS")
            win32gui.PostMessage(hecras_hwnd, win32con.WM_CLOSE, 0, 0)
            time.sleep(1)

            # Wait for HEC-RAS to close
            try:
                process.wait(timeout=10)
                logger.debug("HEC-RAS closed")
            except:
                logger.warning("HEC-RAS did not close cleanly, may still be running")

            # Re-parse .rasmap to verify upgrade
            time.sleep(1)
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
            results_elem = root.find("Results")

            if results_elem is not None:
                logger.info(".rasmap file successfully upgraded")
                return {
                    "status": "upgraded",
                    "message": f"Successfully upgraded from version {version}",
                    "version": version,
                }
            else:
                logger.warning(".rasmap file was not upgraded")
                return {
                    "status": "manual_needed",
                    "message": "Upgrade verification failed - please open RASMapper manually",
                    "version": version,
                }

        except Exception as e:
            logger.error(f"GUI automation failed: {e}")
            return {
                "status": "manual_needed",
                "message": f"Auto-upgrade failed: {e}. Please open RASMapper manually.",
                "version": version,
            }

    @staticmethod
    @log_call
    def postprocess_stored_maps(
        plan_number: Union[str, List[str]],
        specify_terrain: Optional[str] = None,
        layers: Union[str, List[str]] = None,
        ras_object: Optional[Any] = None,
        auto_click_compute: bool = True,
    ) -> bool:
        """
        Automates the generation of stored floodplain map outputs (e.g., .tif files).

        This function modifies the plan and .rasmap files to generate floodplain maps
        for one or more plans, then restores the original files.

        Args:
            plan_number (Union[str, List[str]]): Plan number(s) to generate maps for.
            specify_terrain (Optional[str]): The name of a specific terrain to use.
            layers (Union[str, List[str]], optional): A list of map layers to generate.
                Defaults to ['WSEL', 'Velocity', 'Depth'].
            ras_object (Optional[Any]): The RAS project object.
            auto_click_compute (bool, optional): If True, uses GUI automation to automatically
                click "Run > Unsteady Flow Analysis" and "Compute" button. If False, just
                opens HEC-RAS and waits for manual execution. Defaults to True.

        Returns:
            bool: True if the process completed successfully, False otherwise.

        Notes:
            - auto_click_compute=True: Automated GUI workflow (clicks menu and Compute button)
            - auto_click_compute=False: Manual workflow (user must click Compute)
            - Automatically calls ensure_rasmap_compatible() to upgrade 5.0.7→6.x .rasmap files
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # ── Version validation: only 6.x is verified for correct output ──
        # HEC-RAS 5.0.7 floodplain mapping is UNTESTED and may produce
        # incorrect results if the project was ever opened in a newer version.
        # Verified 2026-03-23: GUI floodplain mapping (Run RASMapper= -1)
        # produces pixel-perfect output for HEC-RAS 6.3.1 and 6.6.
        ras_version = getattr(ras_obj, "ras_version", None) or ""
        if ras_version.startswith("5.") or ras_version.startswith("4."):
            raise RuntimeError(
                f"postprocess_stored_maps() is not supported for HEC-RAS {ras_version}.\n\n"
                "REASON: HEC-RAS 5.x floodplain mapping output has not been validated\n"
                "against manual RASMapper benchmarks, and 5.x projects opened in newer\n"
                "versions become corrupted. Only HEC-RAS 6.x (6.3.1, 6.6+) is verified\n"
                "to produce pixel-perfect raster output via the GUI floodplain mapping path.\n\n"
                "If you need 5.x support, please open a GitHub issue with test data."
            )

        # Ensure .rasmap compatibility (upgrade 5.0.7 to 6.x if needed)
        logger.debug("Checking .rasmap compatibility")
        compat_result = RasMap.ensure_rasmap_compatible(
            ras_object=ras_obj, auto_upgrade=True
        )

        if compat_result["status"] == "manual_needed":
            logger.error(
                f".rasmap upgrade required but failed: {compat_result['message']}\n\n"
                "Manual steps required:\n"
                "1. Open project in HEC-RAS\n"
                "2. Click 'GIS Tools' > 'RAS Mapper'\n"
                "3. Wait for RASMapper to open (this upgrades .rasmap)\n"
                "4. Close RASMapper and HEC-RAS\n"
                "5. Re-run this function"
            )
            return False
        elif compat_result["status"] == "upgraded":
            logger.debug(".rasmap successfully upgraded: %s", compat_result["message"])
        else:  # 'ready'
            logger.debug(
                ".rasmap compatibility check passed: %s", compat_result["message"]
            )

        if layers is None:
            layers = ["WSEL", "Velocity", "Depth"]
        elif isinstance(layers, str):
            layers = [layers]

        # Convert plan_number to list if it's a string
        plan_number_list = (
            [plan_number] if isinstance(plan_number, str) else plan_number
        )

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        rasmap_backup_path = rasmap_path.with_suffix(
            f"{rasmap_path.suffix}.storedmap.bak"
        )

        # Store plan paths and their backups
        plan_paths = []
        plan_backup_paths = []
        plan_results_folders = {}  # Map plan_num to results folder name

        for plan_num in plan_number_list:
            plan_path = Path(RasPlan.get_plan_path(plan_num, ras_obj))
            plan_backup_path = plan_path.with_suffix(
                f"{plan_path.suffix}.storedmap.bak"
            )
            plan_paths.append(plan_path)
            plan_backup_paths.append(plan_backup_path)

            # Get the Short Identifier for this plan to determine results folder
            plan_df = ras_obj.plan_df
            plan_info = plan_df[plan_df["plan_number"] == plan_num]
            if not plan_info.empty:
                short_id = plan_info.iloc[0]["Short Identifier"]
                if pd.notna(short_id) and short_id:
                    plan_results_folders[plan_num] = short_id
                else:
                    # Fallback: use plan number if no Short Identifier
                    plan_results_folders[plan_num] = f"Plan_{plan_num}"
                    logger.warning(
                        f"Plan {plan_num} has no Short Identifier, using 'Plan_{plan_num}' as folder name"
                    )
            else:
                plan_results_folders[plan_num] = f"Plan_{plan_num}"
                logger.warning(
                    f"Could not find plan {plan_num} in plan_df, using 'Plan_{plan_num}' as folder name"
                )

        def _create_map_element(name, map_type, results_folder, profile_name="Max"):
            # Generate filename: "WSE (Max).vrt", "Depth (Max).vrt", etc.
            filename = f"{name} ({profile_name}).vrt"
            relative_path = f".\\{results_folder}\\{filename}"

            map_params = {
                "MapType": map_type,
                "OutputMode": "Stored Current Terrain",
                "StoredFilename": relative_path,  # Required for stored maps
                "ProfileIndex": "2147483647",
                "ProfileName": profile_name,
            }

            # Create Layer element with Filename attribute
            layer_elem = ET.Element(
                "Layer",
                Name=name,
                Type="RASResultsMap",
                Checked="True",
                Filename=relative_path,  # Required for stored maps
            )

            map_params_elem = ET.SubElement(layer_elem, "MapParameters")
            for k, v in map_params.items():
                map_params_elem.set(k, str(v))
            return layer_elem

        try:
            # --- 1. Backup and Modify Plan Files ---
            for plan_num, plan_path, plan_backup_path in zip(
                plan_number_list, plan_paths, plan_backup_paths
            ):
                logger.debug(
                    "Backing up plan file %s to %s", plan_path, plan_backup_path
                )
                shutil.copy2(plan_path, plan_backup_path)

                logger.debug(
                    "Updating plan run flags for floodplain mapping for plan %s",
                    plan_num,
                )
                RasPlan.update_run_flags(
                    plan_num,
                    geometry_preprocessor=True,
                    unsteady_flow_simulation=False,
                    post_processor=False,
                    floodplain_mapping=True,
                    ras_object=ras_obj,
                )

            # --- 2. Backup and Modify RASMAP File ---
            logger.debug(
                "Backing up rasmap file %s to %s", rasmap_path, rasmap_backup_path
            )
            shutil.copy2(rasmap_path, rasmap_backup_path)

            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            results_section = root.find("Results")
            if results_section is None:
                raise ValueError(f"No <Results> section found in {rasmap_path}")

            # Process each plan's results layer
            for plan_num in plan_number_list:
                plan_hdf_part = f".p{plan_num}.hdf"
                results_layer = None
                for layer in results_section.findall("Layer[@Type='RASResults']"):
                    filename = layer.get("Filename")
                    if filename and plan_hdf_part.lower() in filename.lower():
                        results_layer = layer
                        break

                if results_layer is None:
                    # Create a new RASResults layer for this plan
                    plan_hdf_filename = f".\\{ras_obj.project_name}.p{plan_num}.hdf"
                    plan_info = ras_obj.plan_df[
                        ras_obj.plan_df["plan_number"] == plan_num
                    ]
                    if not plan_info.empty:
                        layer_name = plan_info.iloc[0].get(
                            "Plan Title", f"Plan {plan_num}"
                        )
                        if pd.isna(layer_name) or not layer_name:
                            layer_name = f"Plan {plan_num}"
                    else:
                        layer_name = f"Plan {plan_num}"

                    results_layer = ET.SubElement(
                        results_section,
                        "Layer",
                        Name=layer_name,
                        Type="RASResults",
                        Checked="True",
                        Expanded="True",
                        Filename=plan_hdf_filename,
                    )
                    logger.debug(
                        "Created new RASResults layer '%s' for plan %s (none existed in .rasmap)",
                        layer_name,
                        plan_num,
                    )

                # Map user-provided layer names to HEC-RAS variable names and map types
                # Note: "WSE" is the correct HEC-RAS convention (not "WSEL")
                map_definitions = {
                    "WSE": "elevation",
                    "WSEL": "elevation",  # Accept both for backward compatibility, but use "WSE" in output
                    "Velocity": "velocity",
                    "Depth": "depth",
                }

                # Get the results folder for this plan
                results_folder = plan_results_folders.get(plan_num, f"Plan_{plan_num}")

                for layer_name in layers:
                    if layer_name in map_definitions:
                        map_type = map_definitions[layer_name]

                        # Convert WSEL to WSE for output (HEC-RAS convention)
                        output_name = "WSE" if layer_name == "WSEL" else layer_name

                        map_elem = _create_map_element(
                            output_name, map_type, results_folder
                        )
                        results_layer.append(map_elem)
                        logger.debug(
                            "Added '%s' stored map to results layer for plan %s",
                            output_name,
                            plan_num,
                        )

            if specify_terrain:
                terrains_elem = root.find("Terrains")
                if terrains_elem is not None:
                    for layer in list(terrains_elem):
                        if layer.get("Name") != specify_terrain:
                            terrains_elem.remove(layer)
                    logger.debug(
                        "Filtered terrains, keeping only '%s'", specify_terrain
                    )

            tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)

            # --- 3. Execute HEC-RAS ---
            if auto_click_compute:
                # Use GUI automation to automatically click menu and Compute button
                logger.info("Using GUI automation to run floodplain mapping...")

                # Note: For multiple plans, we run the first plan's automation
                # The user can manually run additional plans if needed
                first_plan = plan_number_list[0]

                success = RasGuiAutomation.open_and_compute(
                    plan_number=first_plan,
                    ras_object=ras_obj,
                    auto_click_compute=True,
                    wait_for_user=True,
                )

                if len(plan_number_list) > 1:
                    logger.info(
                        f"Note: GUI automation ran plan {first_plan}. "
                        f"Please manually run remaining plans: {', '.join(plan_number_list[1:])}"
                    )

                if not success:
                    logger.error("Floodplain mapping computation failed.")
                    return False

            else:
                # Manual mode: Just open HEC-RAS and wait for user to execute
                logger.info("Opening HEC-RAS...")
                ras_exe = ras_obj.ras_exe_path
                prj_path = f'"{str(ras_obj.prj_file)}"'
                command = f"{ras_exe} {prj_path}"

                try:
                    import sys
                    import subprocess

                    if sys.platform == "win32":
                        hecras_process = subprocess.Popen(command)
                    else:
                        hecras_process = subprocess.Popen([ras_exe, prj_path])

                    logger.debug(
                        "HEC-RAS opened with Process ID: %s", hecras_process.pid
                    )
                    logger.info(
                        f"Please run plan(s) {', '.join(plan_number_list)} using the 'Compute Multiple' window in HEC-RAS to generate floodplain mapping results."
                    )

                    # Wait for HEC-RAS to close
                    logger.debug("Waiting for HEC-RAS to close")
                    hecras_process.wait()
                    logger.debug("HEC-RAS has closed")

                    success = True

                except Exception as e:
                    logger.error(f"Failed to launch HEC-RAS: {e}")
                    success = False

                if not success:
                    logger.error("Floodplain mapping computation failed.")
                    return False

            logger.info("Floodplain mapping computation successful.")
            return True

        except Exception as e:
            logger.error(f"Error in postprocess_stored_maps: {e}")
            return False

        finally:
            # --- 4. Restore Files ---
            for plan_path, plan_backup_path in zip(plan_paths, plan_backup_paths):
                if plan_backup_path.exists():
                    logger.debug(
                        "Restoring original plan file from %s", plan_backup_path
                    )
                    shutil.move(plan_backup_path, plan_path)
            if rasmap_backup_path.exists():
                logger.debug(
                    "Restoring original rasmap file from %s", rasmap_backup_path
                )
                shutil.move(rasmap_backup_path, rasmap_path)

    # ── Cross-version validation registry ──────────────────────────────────
    # Only version+mode combos verified pixel-perfect against manual RASMapper
    # benchmarks should be listed here. Updated 2026-03-23.
    VALIDATED_MAP_CONFIGURATIONS = {
        # (version_prefix, render_mode) -> status
        # "pixel-perfect" = verified 0.000 diff against manual benchmark
        # "untested" = allowed with warning
        ("6.3", "horizontal"): "pixel-perfect",  # Spring Creek 6.31_Hz, 2026-03-23
    }

    @staticmethod
    @log_call
    def store_all_maps(
        plan_number: Optional[
            Union[
                str,
                int,
                float,
                Sequence[Union[str, int, float]],
            ]
        ] = None,
        render_mode: str = None,
        ras_object: Optional[Any] = None,
        timeout: int = 600,
        *,
        mode: str = "auto",
        output_folder: Optional[str] = None,
        output_path: Optional[Union[str, Path]] = None,
        profile: str = "Max",
        timesteps: Optional[
            Union[int, str, datetime, Sequence[Union[int, str, datetime]]]
        ] = None,
        max_timesteps: Optional[int] = None,
        map_types: Optional[Union[str, Sequence[str]]] = None,
        wse: Optional[bool] = None,
        depth: Optional[bool] = None,
        velocity: Optional[bool] = None,
        froude: Optional[bool] = None,
        shear_stress: Optional[bool] = None,
        depth_x_velocity: Optional[bool] = None,
        depth_x_velocity_sq: Optional[bool] = None,
        inundation_boundary: Optional[bool] = None,
        arrival_time: Optional[bool] = None,
        duration: Optional[bool] = None,
        percent_inundated: Optional[bool] = None,
        arrival_depth: float = 0.0,
        clear_existing: bool = True,
        fix_georef: bool = True,
        ras_version: Optional[str] = None,
        terrain_name: Optional[str] = None,
        benefit_area: Optional[BenefitAreaConfig] = None,
        performance: Optional[StoreMapPerformanceOptions] = None,
        raise_on_error: bool = False,
    ) -> Dict[str, Any]:
        """Generate RASMapper stored maps through one canonical API.

        ``mode`` selects the operation without requiring a second
        ``store_all_maps`` implementation:

        - ``"configured"`` runs ras-commander's packaged RAS Mapper helper
          for every stored map already configured in the ``.rasmap``. This is
          the compatibility behavior of historic
          ``RasMap.store_all_maps(plan_number)`` calls.
        - ``"native"`` is a deprecated alias for ``"configured"``. It does
          not invoke ``RasProcess.exe``: that executable does not honor the
          required stored-map interpolation/render-mode behavior.
        - ``"selected"`` configures and generates selected map products for
          one or more plans. ``performance=StoreMapPerformanceOptions(...)``
          enables memory-admitted map-level parallelism.
        - ``"timesteps"`` generates selected products for requested output
          timesteps.
        - ``"all_plans"`` applies the selected-map configuration to every
          project plan with an HDF result.
        - ``"auto"`` preserves a plain historic call as ``"configured"``,
          uses ``"all_plans"`` when ``plan_number`` is omitted, and otherwise
          selects ``"selected"`` or ``"timesteps"`` when advanced options are
          supplied.

        The result always contains ``success``, resolved ``mode``, ``plans``,
        and ``render_mode``. Configured plan results add ``files_by_type``;
        timestep results add a nested ``timesteps`` mapping. File paths are
        strings so the summary is directly JSON serializable.

        Args:
            plan_number: One flexible plan number (for example ``1`` or
                ``"01"``) or a plan sequence for ``configured``/``selected``/
                ``timesteps``. Omit it for ``all_plans``.
            render_mode: Optional water-surface rendering override.
            ras_object: Initialized project object; defaults to the active project.
            timeout: Per-helper timeout in seconds.
            mode: ``auto``, ``configured``, ``selected``, ``timesteps``, or
                ``all_plans``. ``native`` remains a deprecated compatibility
                alias for ``configured``.
            output_folder: Relative ``.rasmap`` StoredFilename folder name for
                configured non-timestep modes. It is not an output destination.
            output_path: Destination directory to which generated products are
                moved. Multi-plan modes create ``plan_XX`` children.
            profile: ``Max``, ``Min``, or a timestamp for configured
                non-timestep modes.
            timesteps, max_timesteps: Timestep selectors for ``timesteps`` mode.
            map_types: One product name or a sequence of names. Do not combine
                with individual product flags. Defaults are WSE/Depth/Velocity
                for selected/all-plans and Depth only for timesteps.
            wse, depth, velocity, froude, shear_stress, depth_x_velocity,
                depth_x_velocity_sq, inundation_boundary, arrival_time,
                duration, percent_inundated: Individual product flags.
            arrival_depth: Threshold for whole-simulation configured products.
            clear_existing, fix_georef: Configured-map execution controls.
            ras_version: Optional installed mapping-runtime version.
            terrain_name: Registered terrain selection for non-timestep modes.
            benefit_area: Optional single-plan benefit-area configuration.
            performance: Typed map-helper execution and memory policy.
            raise_on_error: Re-raise a per-plan runtime failure instead of
                retaining it in the summary.

        Raises:
            ValueError: If the selected mode cannot honor an option, no plans
                are available, or no map product is selected.
        """
        from .RasProcess import RasProcess

        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        requested_mode = str(mode).strip().casefold().replace("-", "_")
        if requested_mode == "native":
            warnings.warn(
                "mode='native' is deprecated because stored maps are generated "
                "by ras-commander's packaged RAS Mapper helper, not "
                "RasProcess.exe. Use mode='configured'.",
                DeprecationWarning,
                stacklevel=2,
            )

        mode_aliases = {
            "legacy": "configured",
            "native": "configured",
            "native_all": "configured",
            "plan": "selected",
            "project": "all_plans",
            "all": "all_plans",
        }
        resolved_mode = mode_aliases.get(requested_mode, requested_mode)
        valid_modes = {"auto", "configured", "selected", "timesteps", "all_plans"}
        if resolved_mode not in valid_modes:
            raise ValueError(
                "mode must be auto, configured, selected, timesteps, or all_plans"
            )

        requested_flags = {
            "wse": wse,
            "depth": depth,
            "velocity": velocity,
            "froude": froude,
            "shear_stress": shear_stress,
            "depth_x_velocity": depth_x_velocity,
            "depth_x_velocity_sq": depth_x_velocity_sq,
            "inundation_boundary": inundation_boundary,
            "arrival_time": arrival_time,
            "duration": duration,
            "percent_inundated": percent_inundated,
        }
        advanced_requested = any(
            (
                output_folder is not None,
                output_path is not None,
                profile != "Max",
                timesteps is not None,
                max_timesteps is not None,
                map_types is not None,
                any(value is not None for value in requested_flags.values()),
                arrival_depth != 0.0,
                clear_existing is not True,
                fix_georef is not True,
                ras_version is not None,
                terrain_name is not None,
                benefit_area is not None,
                performance is not None,
                raise_on_error is not False,
            )
        )
        if resolved_mode == "auto":
            if timesteps is not None or max_timesteps is not None:
                resolved_mode = "timesteps"
            elif plan_number is None:
                resolved_mode = "all_plans"
            elif advanced_requested:
                resolved_mode = "selected"
            else:
                resolved_mode = "configured"

        if resolved_mode == "configured":
            if plan_number is None:
                raise ValueError("plan_number is required for mode='configured'")
            if not isinstance(plan_number, (str, int, float)) and not list(plan_number):
                raise ValueError("mode='configured' requires at least one plan")
            if advanced_requested:
                raise ValueError(
                    "mode='configured' only accepts plan_number, render_mode, "
                    "ras_object, and timeout; use mode='selected' for output, "
                    "map, terrain, or performance options"
                )
            configured_plan_numbers = (
                [RasUtils.normalize_ras_number(plan_number)]
                if isinstance(plan_number, (str, int, float))
                else [RasUtils.normalize_ras_number(value) for value in plan_number]
            )
            result = RasMap._store_all_maps_configured(
                (
                    configured_plan_numbers[0]
                    if len(configured_plan_numbers) == 1
                    else configured_plan_numbers
                ),
                render_mode=render_mode,
                ras_object=ras_obj,
                timeout=timeout,
            )
            result["mode"] = "configured"
            return result

        if resolved_mode == "all_plans" and plan_number is not None:
            raise ValueError("plan_number must be omitted for mode='all_plans'")
        if resolved_mode in {"selected", "timesteps"} and plan_number is None:
            raise ValueError(f"plan_number is required for mode='{resolved_mode}'")
        if resolved_mode != "timesteps" and timesteps is not None:
            raise ValueError("timesteps are only valid with mode='timesteps'")
        if resolved_mode != "timesteps" and max_timesteps is not None:
            raise ValueError("max_timesteps is only valid with mode='timesteps'")
        if resolved_mode == "timesteps":
            unsupported_timestep_options = []
            if output_folder is not None:
                unsupported_timestep_options.append("output_folder (use output_path)")
            if profile != "Max":
                unsupported_timestep_options.append("profile")
            if arrival_depth != 0.0:
                unsupported_timestep_options.append("arrival_depth")
            if terrain_name is not None:
                unsupported_timestep_options.append("terrain_name")
            if benefit_area is not None:
                unsupported_timestep_options.append("benefit_area")
            if unsupported_timestep_options:
                raise ValueError(
                    "mode='timesteps' does not support: "
                    + ", ".join(unsupported_timestep_options)
                )

        supported_map_types = tuple(requested_flags)
        supported_map_type_set = set(supported_map_types)
        explicit_map_selection = map_types is not None or any(
            value is not None for value in requested_flags.values()
        )
        if map_types is not None:
            if any(value is not None for value in requested_flags.values()):
                raise ValueError(
                    "map_types cannot be combined with individual map flags"
                )
            map_type_values = (map_types,) if isinstance(map_types, str) else map_types
            normalized_types = {
                str(value).strip().casefold().replace(" ", "_")
                for value in map_type_values
            }
            unknown_types = sorted(normalized_types - supported_map_type_set)
            if unknown_types:
                raise ValueError("unsupported map_types: " + ", ".join(unknown_types))
            map_flags = {name: name in normalized_types for name in supported_map_types}
        elif any(value is not None for value in requested_flags.values()):
            map_flags = {name: bool(value) for name, value in requested_flags.items()}
        elif benefit_area is not None:
            # BenefitArea has configuration-dependent defaults in RasProcess.
            map_flags = dict(requested_flags)
        elif resolved_mode == "timesteps":
            map_flags = {name: name == "depth" for name in supported_map_types}
        else:
            map_flags = {
                name: name in {"wse", "depth", "velocity"}
                for name in supported_map_types
            }

        if explicit_map_selection and not any(map_flags.values()):
            raise ValueError("At least one stored-map product must be selected")

        if resolved_mode == "timesteps":
            unsupported_timestep_products = sorted(
                name
                for name in (
                    "inundation_boundary",
                    "arrival_time",
                    "duration",
                    "percent_inundated",
                )
                if map_flags.get(name)
            )
            if unsupported_timestep_products:
                raise ValueError(
                    "mode='timesteps' does not support: "
                    + ", ".join(unsupported_timestep_products)
                )

        if resolved_mode == "all_plans":
            plan_numbers = [
                RasUtils.normalize_ras_number(row["plan_number"])
                for _, row in ras_obj.plan_df.iterrows()
                if (
                    ras_obj.project_folder
                    / f"{ras_obj.project_name}.p{RasUtils.normalize_ras_number(row['plan_number'])}.hdf"
                ).exists()
            ]
        else:
            raw_plan_numbers = (
                [plan_number]
                if isinstance(plan_number, (str, int, float))
                else list(plan_number)
            )
            plan_numbers = [
                RasUtils.normalize_ras_number(value) for value in raw_plan_numbers
            ]

        if not plan_numbers:
            raise ValueError("No plans with HDF results are available for stored maps")
        if benefit_area is not None and len(plan_numbers) != 1:
            raise ValueError("benefit_area requires exactly one selected plan")

        summary: Dict[str, Any] = {
            "success": True,
            "mode": resolved_mode,
            "plans": {},
            "render_mode": (
                normalize_store_map_render_mode(render_mode)
                if render_mode is not None
                else None
            ),
        }
        multiple_plans = len(plan_numbers) > 1 or resolved_mode == "all_plans"

        for plan_num in plan_numbers:
            plan_output_folder = (
                f"{output_folder}_{plan_num}"
                if output_folder is not None and multiple_plans
                else output_folder
            )
            plan_output_path = (
                Path(output_path) / f"plan_{plan_num}"
                if output_path is not None and multiple_plans
                else output_path
            )
            shared_arguments = {
                "plan_number": plan_num,
                "output_folder": plan_output_folder,
                "output_path": plan_output_path,
                "profile": profile,
                "render_mode": render_mode,
                **map_flags,
                "arrival_depth": arrival_depth,
                "clear_existing": clear_existing,
                "fix_georef": fix_georef,
                "ras_object": ras_obj,
                "ras_version": ras_version,
                "timeout": timeout,
                "performance": performance,
            }
            if terrain_name is not None:
                shared_arguments["terrain_name"] = terrain_name
            if benefit_area is not None:
                shared_arguments["benefit_area"] = benefit_area

            try:
                if resolved_mode == "timesteps":
                    timestep_arguments = {
                        key: value
                        for key, value in shared_arguments.items()
                        if key
                        not in {
                            "output_folder",
                            "profile",
                            "inundation_boundary",
                            "arrival_time",
                            "duration",
                            "percent_inundated",
                            "arrival_depth",
                            "terrain_name",
                            "benefit_area",
                        }
                    }
                    generated_by_timestep = RasProcess.store_maps_at_timesteps(
                        timesteps=timesteps,
                        max_timesteps=max_timesteps,
                        **timestep_arguments,
                    )
                    timestep_summary = {
                        timestamp: {
                            map_type: [str(path) for path in paths]
                            for map_type, paths in generated.items()
                        }
                        for timestamp, generated in generated_by_timestep.items()
                    }
                    flat_files = [
                        path
                        for generated in timestep_summary.values()
                        for paths in generated.values()
                        for path in paths
                    ]
                    summary["plans"][plan_num] = {
                        "success": True,
                        "timesteps": timestep_summary,
                        "files": flat_files,
                    }
                else:
                    generated = RasProcess.store_maps(**shared_arguments)
                    files_by_type = {
                        map_type: [str(path) for path in paths]
                        for map_type, paths in generated.items()
                    }
                    flat_files = [
                        path for paths in files_by_type.values() for path in paths
                    ]
                    output_directories = sorted(
                        {str(Path(path).parent) for path in flat_files}
                    )
                    summary["plans"][plan_num] = {
                        "success": True,
                        "output_dir": (
                            output_directories[0]
                            if len(output_directories) == 1
                            else None
                        ),
                        "files": flat_files,
                        "files_by_type": files_by_type,
                    }
            except Exception as exc:
                logger.error("Failed to generate maps for plan %s: %s", plan_num, exc)
                summary["success"] = False
                summary["plans"][plan_num] = {
                    "success": False,
                    "error": str(exc),
                }
                if raise_on_error:
                    raise

        return summary

    @staticmethod
    def _store_all_maps_configured(
        plan_number: Union[str, List[str]],
        render_mode: str = None,
        ras_object: Optional[Any] = None,
        timeout: int = 600,
    ) -> Dict[str, Any]:
        """
        Generate stored floodplain map rasters headlessly using RasStoreMapHelper.exe.

        This method sets the rendering mode correctly and generates map rasters
        without requiring the HEC-RAS GUI. It addresses a bug in RasProcess.exe
        StoreAllMaps where HEC-RAS 6.x ignores the RenderMode setting from the
        .rasmap file.

        The helper exe is bundled with ras-commander and executed from the
        installed package path when possible. If needed, it can be staged into
        a user-writable cache directory without modifying the HEC-RAS
        installation.

        Args:
            plan_number: Plan number(s) to generate maps for (e.g. "01" or ["01", "02"]).
            render_mode: Rendering mode override. If None, reads from .rasmap file.
                Valid values: "horizontal", "sloping", "slopingPretty".
            ras_object: Optional RAS project object.
            timeout: Timeout in seconds per plan (default: 600).

        Returns:
            Dict with keys:
                - "success" (bool): True if all plans completed successfully.
                - "plans" (dict): Per-plan results with output file lists.
                - "render_mode" (str): The rendering mode used.

        Raises:
            RuntimeError: If HEC-RAS version is 5.x or earlier (untested).
            FileNotFoundError: If required files are missing.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "7.0")
            >>> result = RasMap.store_all_maps("01", render_mode="horizontal")
            >>> print(result["success"])
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Version guard: only 6.x is validated
        ras_version = getattr(ras_obj, "ras_version", None) or ""
        exe_path_str = str(getattr(ras_obj, "ras_exe_path", ""))
        # Try to detect version from exe path (e.g. "...\6.6\Ras.exe")
        if not ras_version:
            for segment in Path(exe_path_str).parts:
                if segment and segment[0].isdigit():
                    ras_version = segment
                    break

        if ras_version.startswith("5.") or ras_version.startswith("4."):
            raise RuntimeError(
                f"store_all_maps() is not supported for HEC-RAS {ras_version}.\n"
                "HEC-RAS 5.x/4.x map generation has not been validated with this method."
            )

        # Locate HEC-RAS directory from ras_exe_path
        hecras_dir = Path(exe_path_str).parent
        if not hecras_dir.exists():
            raise FileNotFoundError(f"HEC-RAS directory not found: {hecras_dir}")

        # Determine render mode
        if render_mode is None:
            render_mode = RasMap.get_water_surface_render_mode(ras_object=ras_obj)
            if render_mode is None:
                render_mode = {"mode": "horizontal"}
                logger.warning(
                    "No RenderMode found in .rasmap, defaulting to 'horizontal'"
                )

        helper_mode = normalize_store_map_render_mode(render_mode)

        # Process plan numbers
        plan_number_list = (
            [plan_number] if isinstance(plan_number, str) else list(plan_number)
        )

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            raise FileNotFoundError(f".rasmap file not found: {rasmap_path}")

        results = {"success": True, "plans": {}, "render_mode": helper_mode}

        for plan_num in plan_number_list:
            result_hdf = (
                ras_obj.project_folder / f"{ras_obj.project_name}.p{plan_num}.hdf"
            )
            if not result_hdf.exists():
                logger.warning(
                    f"Skipping plan {plan_num} — no result HDF: {result_hdf}"
                )
                results["plans"][plan_num] = {
                    "success": False,
                    "error": "No result HDF",
                }
                results["success"] = False
                continue

            logger.debug(
                "Generating stored maps for plan %s (mode=%s)", plan_num, helper_mode
            )

            try:
                proc = run_store_all_maps_helper(
                    hecras_dir=hecras_dir,
                    render_mode=helper_mode,
                    rasmap_path=rasmap_path,
                    result_hdf_path=result_hdf,
                    timeout=timeout,
                    working_dir=ras_obj.project_folder,
                )

                if proc.returncode == 0:
                    logger.debug(
                        "Plan %s: StoreAllMaps completed successfully", plan_num
                    )
                    logger.debug(
                        "Plan %s StoreAllMaps stdout: %s", plan_num, proc.stdout
                    )

                    # Collect output files
                    plan_info = ras_obj.plan_df[
                        ras_obj.plan_df["plan_number"] == plan_num
                    ]
                    if not plan_info.empty:
                        short_id = plan_info.iloc[0].get(
                            "Short Identifier", f"Plan_{plan_num}"
                        )
                        if pd.isna(short_id) or not short_id:
                            short_id = f"Plan_{plan_num}"
                    else:
                        short_id = f"Plan_{plan_num}"

                    output_dir = ras_obj.project_folder / short_id.strip()
                    output_files = []
                    if output_dir.exists():
                        output_files = list(output_dir.glob("*.tif")) + list(
                            output_dir.glob("*.vrt")
                        )

                    results["plans"][plan_num] = {
                        "success": True,
                        "output_dir": str(output_dir),
                        "files": [str(f) for f in output_files],
                        "stdout": proc.stdout,
                    }
                else:
                    logger.error(
                        "Plan %s: StoreAllMaps failed (exit code %s)",
                        plan_num,
                        proc.returncode,
                    )
                    logger.debug(
                        "Plan %s StoreAllMaps stderr: %s", plan_num, proc.stderr
                    )
                    logger.debug(
                        "Plan %s StoreAllMaps stdout: %s", plan_num, proc.stdout
                    )
                    results["plans"][plan_num] = {
                        "success": False,
                        "error": proc.stderr or proc.stdout,
                        "exit_code": proc.returncode,
                    }
                    results["success"] = False

            except subprocess.TimeoutExpired:
                logger.error(
                    f"Plan {plan_num}: StoreAllMaps timed out after {timeout}s"
                )
                results["plans"][plan_num] = {"success": False, "error": "Timeout"}
                results["success"] = False

        successful_plans = sum(
            1 for result in results["plans"].values() if result.get("success")
        )
        logger.info(
            "Stored map generation complete: %s/%s plans succeeded (mode=%s)",
            successful_plans,
            len(plan_number_list),
            helper_mode,
        )
        return results

    @staticmethod
    @log_call
    def get_results_folder(
        plan_number: Union[str, int, float], ras_object=None
    ) -> Path:
        """
        Get the folder path containing raster results for a specified plan.

        HEC-RAS creates output folders based on the plan's Short Identifier.
        Windows folder naming replaces special characters with underscores.

        Args:
            plan_number (Union[str, int, float]): Plan number (accepts flexible formats like 1, "01", "001").
            ras_object: Optional RAS object instance.

        Returns:
            Path: Path to the mapping output folder.

        Raises:
            ValueError: If the plan number is not found or output folder doesn't exist.

        Examples:
            >>> folder = RasMap.get_results_folder("01")
            >>> folder = RasMap.get_results_folder(1)
            >>> folder = RasMap.get_results_folder("08", ras_object=my_project)

        Notes:
            - Normalizes plan number to two-digit format ("01", "02", etc.)
            - Retrieves Short Identifier from plan_df
            - Normalizes Short ID for Windows folder naming (special chars -> underscores)
            - Searches project folder for matching output directory
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Normalize plan number to two-digit format
        plan_number = RasUtils.normalize_ras_number(plan_number)

        # Get plan metadata from plan_df
        plan_df = ras_obj.plan_df
        plan_info = plan_df[plan_df["plan_number"] == plan_number]

        if plan_info.empty:
            raise ValueError(
                f"Plan {plan_number} not found in project. "
                f"Available plans: {list(plan_df['plan_number'])}"
            )

        short_id = plan_info.iloc[0]["Short Identifier"]

        if pd.isna(short_id) or not short_id:
            raise ValueError(
                f"Plan {plan_number} does not have a Short Identifier. "
                "Check the plan file for missing metadata."
            )

        # Normalize Short ID to match Windows folder naming
        # RASMapper replaces special characters for Windows compatibility
        replacements = {
            "/": "_",
            "\\": "_",
            ":": "_",
            "*": "_",
            "?": "_",
            '"': "_",
            "<": "_",
            ">": "_",
            "|": "_",
            "+": "_",
            " ": "_",
        }

        normalized = short_id
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # Remove trailing underscores
        normalized = normalized.rstrip("_")

        # Search for output folder in project directory
        project_folder = ras_obj.project_folder

        # Try exact match with Short ID
        exact_match = project_folder / short_id
        if exact_match.exists() and exact_match.is_dir():
            logger.debug("Found output folder by exact match: %s", exact_match)
            return exact_match

        # Try normalized name
        normalized_match = project_folder / normalized
        if normalized_match.exists() and normalized_match.is_dir():
            logger.debug(
                "Found output folder by normalized match: %s", normalized_match
            )
            return normalized_match

        # Try partial match (contains)
        for item in project_folder.iterdir():
            if not item.is_dir():
                continue
            folder_name = item.name
            # Check if short_id is contained in folder name or vice versa
            if short_id in folder_name or folder_name in short_id:
                logger.debug("Found output folder by partial match: %s", item)
                return item
            # Check normalized version
            if normalized in folder_name or folder_name in normalized:
                logger.debug(
                    "Found output folder by normalized partial match: %s", item
                )
                return item

        # No folder found
        raise ValueError(
            f"Output folder not found for plan {plan_number} (Short ID: '{short_id}'). "
            f"Expected folder name: '{normalized}' in {project_folder}. "
            "Ensure the plan has been run and RASMapper has exported results."
        )

    @staticmethod
    @log_call
    def get_results_raster(
        plan_number: Union[str, int, float], variable_name: str, ras_object=None
    ) -> Path:
        """
        Get the .vrt file path for a specified plan and variable name.

        This function locates VRT (Virtual Raster) files exported by RASMapper
        for a specific hydraulic variable (e.g., WSE, Depth, Velocity).

        Args:
            plan_number (Union[str, int, float]): Plan number (accepts flexible formats).
            variable_name (str): Variable name to search for in VRT filenames (e.g., "WSE", "Depth", "Velocity").
            ras_object: Optional RAS object instance.

        Returns:
            Path: Path to the matching .vrt file.

        Raises:
            ValueError: If no matching files or multiple matching files are found.

        Examples:
            >>> vrt = RasMap.get_results_raster("01", "WSE")
            >>> vrt = RasMap.get_results_raster(1, "Depth")
            >>> vrt = RasMap.get_results_raster("08", "WSE (Max)", ras_object=my_project)

        Notes:
            - Uses get_results_folder() to locate the output directory
            - Searches for .vrt files containing the variable_name (case-insensitive)
            - If multiple files match, lists all matches and raises an error
            - User should make variable_name more specific to narrow results
            - VRT files are lightweight virtual rasters that reference underlying .tif tiles
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Get the mapping folder for this plan
        mapping_folder = RasMap.get_results_folder(plan_number, ras_obj)

        # List all .vrt files in the folder
        vrt_files = list(mapping_folder.glob("*.vrt"))

        if not vrt_files:
            raise ValueError(
                f"No .vrt files found in mapping folder: {mapping_folder}. "
                "Ensure RASMapper has exported raster results for this plan."
            )

        # Filter files containing variable_name (case-insensitive)
        matching_files = [
            f for f in vrt_files if variable_name.lower() in f.name.lower()
        ]

        # Handle results
        if len(matching_files) == 0:
            available_files = [f.name for f in vrt_files]
            raise ValueError(
                f"No .vrt files found matching variable name '{variable_name}' in {mapping_folder}. "
                f"Available files: {available_files}. "
                "Try making variable_name more specific or check for typos."
            )
        elif len(matching_files) == 1:
            logger.debug("Found matching VRT file: %s", matching_files[0])
            return matching_files[0]
        else:
            logger.debug(
                "Multiple .vrt files match '%s': %s",
                variable_name,
                [f.name for f in matching_files],
            )

            raise ValueError(
                f"Multiple .vrt files ({len(matching_files)}) match variable name '{variable_name}'. "
                f"Matching files: {[f.name for f in matching_files]}. "
                "Please make variable_name more specific (e.g., 'WSE (Max)' instead of 'WSE')."
            )

    @staticmethod
    @log_call
    def set_water_surface_render_mode(
        mode: str = "horizontal",
        reduce_shallow_to_horizontal: bool = True,
        use_depth_weighted_faces: bool = False,
        ras_object=None,
    ) -> bool:
        """
        Set the water surface rendering mode in the RASMapper configuration file.

        This modifies the .rasmap file to change how RASMapper renders water surfaces
        when generating raster outputs. The setting affects stored map exports and
        on-screen display.

        Args:
            mode (str): Rendering mode. Options:
                - "horizontal": Constant water surface elevation per mesh cell.
                  Each cell displays a single, flat water surface. Faster rendering.
                - "sloping": Sloped water surface using 4-corner cell elevations.
                  Basic interpolation within each cell.
                - "slopingPretty": Enhanced sloped mode using 8-point interpolation
                  (4 corners + 4 face centers). Smoothest visualization.
                  Supports optional reduce_shallow_to_horizontal and
                  use_depth_weighted_faces flags.
            reduce_shallow_to_horizontal (bool): When True, shallow cells fall back
                to horizontal rendering. Only applies to slopingPretty mode.
                Default: True.
            use_depth_weighted_faces (bool): When True, face contributions are
                weighted by depth. Only applies to slopingPretty mode.
                Default: False.
            ras_object: Optional RAS object instance.

        Returns:
            bool: True if successful, False otherwise.

        Raises:
            ValueError: If an invalid mode is specified.
            FileNotFoundError: If the .rasmap file doesn't exist.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "7.0")
            >>>
            >>> # Set horizontal mode (flat WSE per cell)
            >>> RasMap.set_water_surface_render_mode("horizontal")
            >>>
            >>> # Set basic sloping mode (4-corner interpolation)
            >>> RasMap.set_water_surface_render_mode("sloping")
            >>>
            >>> # Set slopingPretty mode (8-point interpolation, smoothest)
            >>> RasMap.set_water_surface_render_mode("slopingPretty")
            >>>
            >>> # slopingPretty with depth-weighted faces (HEC-RAS 6.31 style)
            >>> RasMap.set_water_surface_render_mode(
            ...     "slopingPretty",
            ...     reduce_shallow_to_horizontal=True,
            ...     use_depth_weighted_faces=True
            ... )

        Notes:
            - Changes take effect the next time RASMapper generates raster outputs
            - "horizontal" mode uses constant WSE per cell
            - "sloping" mode uses 4-corner interpolation within each cell
            - "slopingPretty" mode uses 8-point interpolation for smoothest results
            - The original .rasmap file is modified in place (no backup created)
            - The legacy mode name "sloped" is accepted as an alias for "slopingPretty"
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Validate and normalize mode
        mode_lower = mode.lower()
        # Accept legacy alias
        if mode_lower == "sloped":
            mode_lower = "slopingpretty"
        valid_modes = {"horizontal", "sloping", "slopingpretty"}
        if mode_lower not in valid_modes:
            raise ValueError(
                f"Invalid mode '{mode}'. Valid options: 'horizontal', 'sloping', 'slopingPretty'"
            )

        # Get rasmap path
        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")

        try:
            # Parse the XML file
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            # Find or create RenderMode element
            render_mode_elem = root.find("RenderMode")
            if render_mode_elem is None:
                # Insert after Units element or at the end
                units_elem = root.find("Units")
                if units_elem is not None:
                    idx = list(root).index(units_elem) + 1
                    render_mode_elem = ET.Element("RenderMode")
                    root.insert(idx, render_mode_elem)
                else:
                    render_mode_elem = ET.SubElement(root, "RenderMode")

            # Find existing depth-weighted and reduce-shallow elements
            depth_weighted_elem = root.find("UseDepthWeightedFaces")
            reduce_shallow_elem = root.find("ReduceShallowToHorizontal")

            if mode_lower == "horizontal":
                render_mode_elem.text = "horizontal"

                # Remove sloped-specific elements if present
                if depth_weighted_elem is not None:
                    root.remove(depth_weighted_elem)
                if reduce_shallow_elem is not None:
                    root.remove(reduce_shallow_elem)

                logger.info("Set water surface render mode to 'horizontal'")

            elif mode_lower == "sloping":
                render_mode_elem.text = "sloping"

                # Remove slopingPretty-specific elements if present
                if depth_weighted_elem is not None:
                    root.remove(depth_weighted_elem)
                if reduce_shallow_elem is not None:
                    root.remove(reduce_shallow_elem)

                logger.info("Set water surface render mode to 'sloping'")

            elif mode_lower == "slopingpretty":
                render_mode_elem.text = "slopingPretty"

                # Add/update reduce-shallow element
                if reduce_shallow_to_horizontal:
                    if reduce_shallow_elem is None:
                        idx = list(root).index(render_mode_elem) + 1
                        reduce_shallow_elem = ET.Element("ReduceShallowToHorizontal")
                        root.insert(idx, reduce_shallow_elem)
                    reduce_shallow_elem.text = "true"
                else:
                    if reduce_shallow_elem is not None:
                        root.remove(reduce_shallow_elem)

                # Add/update depth-weighted faces element
                if use_depth_weighted_faces:
                    if depth_weighted_elem is None:
                        # Insert after RenderMode (or after ReduceShallowToHorizontal if present)
                        after_elem = (
                            reduce_shallow_elem
                            if reduce_shallow_elem is not None
                            else render_mode_elem
                        )
                        idx = list(root).index(after_elem) + 1
                        depth_weighted_elem = ET.Element("UseDepthWeightedFaces")
                        root.insert(idx, depth_weighted_elem)
                    depth_weighted_elem.text = "true"
                else:
                    if depth_weighted_elem is not None:
                        root.remove(depth_weighted_elem)

                logger.info(
                    f"Set water surface render mode to 'slopingPretty' "
                    f"(reduceShallow={reduce_shallow_to_horizontal}, "
                    f"depthWeighted={use_depth_weighted_faces})"
                )

            # Write the modified XML back
            tree.write(rasmap_path, encoding="utf-8", xml_declaration=True)
            logger.debug("Updated RASMapper configuration: %s", rasmap_path)

            return True

        except Exception as e:
            logger.error(f"Error setting water surface render mode: {e}")
            return False

    @staticmethod
    @log_call
    def get_water_surface_render_mode(ras_object=None) -> Optional[dict]:
        """
        Get the current water surface rendering mode from the RASMapper configuration.

        Args:
            ras_object: Optional RAS object instance.

        Returns:
            Optional[dict]: Rendering mode configuration with keys:
                - "mode": The rendering mode string — "horizontal", "sloping",
                  or "slopingPretty"
                - "reduce_shallow_to_horizontal": bool, whether shallow cells
                  fall back to horizontal (only for slopingPretty)
                - "use_depth_weighted_faces": bool, whether face contributions
                  are depth-weighted (only for slopingPretty)
                Returns None if .rasmap file not found or mode not set.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project(r"C:/Projects/MyModel", "7.0")
            >>> render_info = RasMap.get_water_surface_render_mode()
            >>> print(f"Mode: {render_info['mode']}")
            >>> # For slopingPretty, check flags:
            >>> if render_info['mode'] == 'slopingPretty':
            ...     print(f"Depth weighted: {render_info['use_depth_weighted_faces']}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return None

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()

            render_mode_elem = root.find("RenderMode")
            if render_mode_elem is None or render_mode_elem.text is None:
                return None

            mode_text = render_mode_elem.text.strip()

            # Read associated flags
            depth_weighted_elem = root.find("UseDepthWeightedFaces")
            reduce_shallow_elem = root.find("ReduceShallowToHorizontal")

            has_depth_weighted = (
                depth_weighted_elem is not None
                and depth_weighted_elem.text is not None
                and depth_weighted_elem.text.strip().lower() == "true"
            )
            has_reduce_shallow = (
                reduce_shallow_elem is not None
                and reduce_shallow_elem.text is not None
                and reduce_shallow_elem.text.strip().lower() == "true"
            )

            # Normalize mode text to canonical form
            mode_lower = mode_text.lower()
            if mode_lower == "horizontal":
                canonical_mode = "horizontal"
            elif mode_lower == "slopingpretty":
                canonical_mode = "slopingPretty"
            elif mode_lower == "sloping":
                # "sloping" with both flags is effectively slopingPretty (HEC-RAS 6.31 style)
                if has_depth_weighted and has_reduce_shallow:
                    canonical_mode = "slopingPretty"
                else:
                    canonical_mode = "sloping"
            else:
                logger.warning(f"Unknown render mode in rasmap: {mode_text}")
                canonical_mode = mode_text

            return {
                "mode": canonical_mode,
                "reduce_shallow_to_horizontal": has_reduce_shallow,
                "use_depth_weighted_faces": has_depth_weighted,
            }

        except Exception as e:
            logger.error(f"Error reading water surface render mode: {e}")
            return None

    # map_ras_results() removed - use RasProcess.store_maps() instead
    # RasProcess.exe works on both Windows (native) and Linux (Wine)

    @staticmethod
    @log_call
    def scan_results_folders(ras_folder: Path) -> Dict[str, Dict]:
        """
        Scan RAS project folder for results folders containing raster files.

        Args:
            ras_folder: Path to HEC-RAS project folder containing .prj file

        Returns:
            Dictionary mapping folder names to folder information:
            {folder_name: {'path': Path, 'has_vrt': bool, 'has_tif': bool}}

        Examples:
            >>> folders = RasMap.scan_results_folders(Path("/path/to/project"))
            >>> for name, info in folders.items():
            ...     print(f"{name}: {info['path']}")
        """
        results = {}
        for folder in ras_folder.iterdir():
            if folder.is_dir() and not folder.name.startswith("."):
                # Check for raster files
                tif_files = list(folder.glob("*.tif"))
                vrt_files = list(folder.glob("*.vrt"))

                if tif_files or vrt_files:
                    results[folder.name] = {
                        "path": folder,
                        "has_vrt": len(vrt_files) > 0,
                        "has_tif": len(tif_files) > 0,
                    }
                    logger.debug(
                        f"Found results folder: {folder.name} "
                        f"(VRT: {len(vrt_files)}, TIF: {len(tif_files)})"
                    )
        return results

    @staticmethod
    @log_call
    def find_results_folder(ras_folder: Path, short_id: str) -> Optional[Path]:
        """
        Find results folder for a plan Short ID.

        Args:
            ras_folder: Path to HEC-RAS project folder
            short_id: Plan Short Identifier (from plan file)

        Returns:
            Path to results folder, or None if not found

        Examples:
            >>> folder = RasMap.find_results_folder(Path("/path/to/project"), "H100_CP")
        """
        # Normalize Short ID to match Windows folder naming
        # RASMapper replaces special characters for Windows compatibility
        replacements = {
            "/": "_",
            "\\": "_",
            ":": "_",
            "*": "_",
            "?": "_",
            '"': "_",
            "<": "_",
            ">": "_",
            "|": "_",
            "+": "_",
            " ": "_",
        }

        normalized = short_id
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)

        # Remove trailing underscores
        normalized = normalized.rstrip("_")

        # Scan for folders
        folders = RasMap.scan_results_folders(ras_folder)

        # Try exact match
        if short_id in folders:
            return folders[short_id]["path"]

        # Try normalized name
        if normalized in folders:
            return folders[normalized]["path"]

        # Try partial match
        for folder_name, folder_info in folders.items():
            # Check if short_id is contained in folder name or vice versa
            if short_id in folder_name or folder_name in short_id:
                return folder_info["path"]
            # Check normalized version
            if normalized in folder_name or folder_name in normalized:
                return folder_info["path"]

        return None

    @staticmethod
    @log_call
    def resolve_raster_paths(results_folder: Path) -> Dict[str, Optional[Path]]:
        """
        Resolve WSE and Depth raster paths from results folder.

        Priority order:
        1. Unsteady flow VRT files (e.g., "Depth (Max).vrt")
        2. Steady flow VRT files (e.g., "Depth.vrt")
        3. Unsteady flow TIF files (e.g., "Depth (Max).tif")
        4. Steady flow TIF files (e.g., "Depth.tif")

        Args:
            results_folder: Path to RASMapper results folder

        Returns:
            Dictionary with 'wse' and 'depth' paths (or None if not found)

        Examples:
            >>> rasters = RasMap.resolve_raster_paths(Path("/path/to/project/H100_CP"))
            >>> wse_path = rasters['wse']
            >>> depth_path = rasters['depth']
        """
        result = {"wse": None, "depth": None}

        # Priority 1: Look for unsteady flow VRT files (with "max")
        for vrt_file in results_folder.glob("*.vrt"):
            name_lower = vrt_file.name.lower()
            if "depth" in name_lower and "max" in name_lower:
                result["depth"] = vrt_file
                logger.debug(f"Found unsteady depth VRT: {vrt_file.name}")
            elif "wse" in name_lower and "max" in name_lower:
                result["wse"] = vrt_file
                logger.debug(f"Found unsteady WSE VRT: {vrt_file.name}")

        # Priority 2: Look for steady flow VRT files (without "max") - only if not already found
        if not result["depth"] or not result["wse"]:
            for vrt_file in results_folder.glob("*.vrt"):
                name_lower = vrt_file.name.lower()
                name_base = vrt_file.stem.lower()

                # Match depth files - steady flow patterns
                if (
                    not result["depth"]
                    and "depth" in name_lower
                    and "max" not in name_lower
                ):
                    if (
                        name_base == "depth"
                        or name_base.startswith("depth (")
                        or name_base.startswith("depth ")
                        or name_base.startswith("depth_grid")
                    ):
                        result["depth"] = vrt_file
                        logger.debug(f"Found steady depth VRT: {vrt_file.name}")

                # Match WSE files - steady flow patterns
                elif (
                    not result["wse"]
                    and "wse" in name_lower
                    and "max" not in name_lower
                ):
                    if (
                        name_base == "wse"
                        or name_base.startswith("wse (")
                        or name_base.startswith("wse ")
                        or name_base.startswith("wse_grid")
                    ):
                        result["wse"] = vrt_file
                        logger.debug(f"Found steady WSE VRT: {vrt_file.name}")

        # Priority 3: Fall back to unsteady flow TIF files if no VRT found
        if not result["depth"] or not result["wse"]:
            for tif_file in results_folder.glob("*.tif"):
                name_lower = tif_file.name.lower()
                if (
                    not result["depth"]
                    and "depth" in name_lower
                    and "max" in name_lower
                ):
                    result["depth"] = tif_file
                    logger.debug(f"Found unsteady depth TIF: {tif_file.name}")
                elif not result["wse"] and "wse" in name_lower and "max" in name_lower:
                    result["wse"] = tif_file
                    logger.debug(f"Found unsteady WSE TIF: {tif_file.name}")

        # Priority 4: Fall back to steady flow TIF files if still not found
        if not result["depth"] or not result["wse"]:
            for tif_file in results_folder.glob("*.tif"):
                name_lower = tif_file.name.lower()
                name_base = tif_file.stem.lower()

                # Match depth TIF files - steady flow patterns
                if (
                    not result["depth"]
                    and "depth" in name_lower
                    and "max" not in name_lower
                ):
                    if (
                        name_base == "depth"
                        or name_base.startswith("depth (")
                        or name_base.startswith("depth ")
                        or name_base.startswith("depth_grid")
                    ):
                        result["depth"] = tif_file
                        logger.debug(f"Found steady depth TIF: {tif_file.name}")

                # Match WSE TIF files - steady flow patterns
                elif (
                    not result["wse"]
                    and "wse" in name_lower
                    and "max" not in name_lower
                ):
                    if (
                        name_base == "wse"
                        or name_base.startswith("wse (")
                        or name_base.startswith("wse ")
                        or name_base.startswith("wse_grid")
                    ):
                        result["wse"] = tif_file
                        logger.debug(f"Found steady WSE TIF: {tif_file.name}")

        # Log detected model type
        if result["depth"] or result["wse"]:
            depth_path = str(result.get("depth", "")).lower()
            wse_path = str(result.get("wse", "")).lower()
            if "max" in depth_path or "max" in wse_path:
                logger.debug("Detected unsteady flow model in %s", results_folder.name)
            else:
                logger.debug("Detected steady flow model in %s", results_folder.name)

        return result

    @staticmethod
    @log_call
    def find_steady_raster(
        results_folder: Path, profile_name: str, raster_type: str
    ) -> Optional[Path]:
        """
        Find steady state raster for a specific profile.

        Args:
            results_folder: Path to RASMapper results folder
            profile_name: Profile name (e.g., "1Pct", "10Pct", "50Pct")
            raster_type: Type of raster ('WSE' or 'Depth')

        Returns:
            Path to raster file, or None if not found

        Examples:
            >>> raster = RasMap.find_steady_raster(Path("/path/to/project/H100_CP"), "10Pct", "WSE")
        """
        # Search patterns for steady state profile-specific rasters
        # Pattern 1: Standard format with parentheses "WSE (1Pct).vrt"
        pattern1 = f"{raster_type} ({profile_name}).vrt"
        vrt_path = results_folder / pattern1
        if vrt_path.exists():
            logger.debug(f"Found steady raster (pattern 1): {vrt_path.name}")
            return vrt_path

        # Pattern 2: Terrain-specific variant "WSE (1Pct).Terrain.{terrain_name}.tif"
        pattern2 = f"{raster_type} ({profile_name}).Terrain.*.tif"
        tif_files = list(results_folder.glob(pattern2))
        if tif_files:
            logger.debug(f"Found steady raster (pattern 2): {tif_files[0].name}")
            return tif_files[0]

        # Pattern 3: Underscore format "WSE_1Pct.vrt"
        pattern3 = f"{raster_type}_{profile_name}.vrt"
        alt_vrt = results_folder / pattern3
        if alt_vrt.exists():
            logger.debug(f"Found steady raster (pattern 3): {alt_vrt.name}")
            return alt_vrt

        # Pattern 4: Space instead of underscore "WSE 1Pct.vrt"
        pattern4 = f"{raster_type} {profile_name}.vrt"
        space_vrt = results_folder / pattern4
        if space_vrt.exists():
            logger.debug(f"Found steady raster (pattern 4): {space_vrt.name}")
            return space_vrt

        # Pattern 5: TIF variant without terrain suffix
        pattern5 = f"{raster_type} ({profile_name}).tif"
        tif_path = results_folder / pattern5
        if tif_path.exists():
            logger.debug(f"Found steady raster (pattern 5): {tif_path.name}")
            return tif_path

        logger.warning(
            f"Could not find steady state raster for profile '{profile_name}', type {raster_type}. "
            f"Searched in: {results_folder}"
        )
        return None

    # =========================================================================
    # Map Layer Validation Methods (delegated to RasMapValidation)
    # =========================================================================
    # These methods are maintained here for backward compatibility.
    # Implementation lives in RasMapValidation.py.

    from .RasMapValidation import RasMapValidation as _RMV

    check_layer_format = _RMV.check_layer_format
    check_layer_crs = _RMV.check_layer_crs
    check_raster_metadata = _RMV.check_raster_metadata
    check_spatial_extent = _RMV.check_spatial_extent
    check_terrain_layer = _RMV.check_terrain_layer
    check_land_cover_layer = _RMV.check_land_cover_layer
    check_layer = _RMV.check_layer
    is_valid_layer = _RMV.is_valid_layer

    del _RMV  # Clean up class namespace

    @staticmethod
    @log_call
    def add_terrain_layer(
        terrain_hdf: Union[str, Path],
        rasmap_path: Union[str, Path],
        layer_name: str = "Terrain",
        projection_prj: Optional[Union[str, Path]] = None,
        ras_object=None,
    ) -> None:
        """
        Add terrain layer to RASMapper configuration.

        After creating terrain with RasTerrain.create_terrain_hdf(),
        register it in project's .rasmap file. This method creates the
        required XML structure in the Terrains section.

        Args:
            terrain_hdf: Path to terrain HDF file (e.g., "./Terrain/MyTerrain.hdf")
            rasmap_path: Path to .rasmap file to modify
            layer_name: Display name for terrain layer (default: "Terrain")
            projection_prj: Path to ESRI PRJ file. If provided, updates
                RASProjectionFilename element. Default: None (keeps existing).
            ras_object: Optional RasPrj object instance (default: global ras).

        Returns:
            None

        Raises:
            FileNotFoundError: If rasmap_path or terrain_hdf does not exist.
            ValueError: If rasmap file is not valid XML.

        Example:
            >>> from ras_commander import RasMap
            >>>
            >>> # After creating terrain HDF
            >>> RasMap.add_terrain_layer(
            ...     terrain_hdf="./Terrain/Terrain50.hdf",
            ...     rasmap_path="./Project.rasmap",
            ...     layer_name="Terrain50"
            ... )
            >>>
            >>> # With projection file
            >>> RasMap.add_terrain_layer(
            ...     terrain_hdf="./Terrain/NewTerrain.hdf",
            ...     rasmap_path="./Project.rasmap",
            ...     layer_name="NewTerrain",
            ...     projection_prj="./Terrain/Projection.prj"
            ... )

        Notes:
            - Creates Terrains section if it doesn't exist
            - Generates XML structure compatible with HEC-RAS 6.x:
              <Terrains Checked="True" Expanded="True">
                <Layer Name="{layer_name}" Type="TerrainLayer" Checked="True"
                       Filename=".\\Terrain\\{name}.hdf">
                  <ResampleMethod>near</ResampleMethod>
                  <Surface On="True" />
                </Layer>
              </Terrains>
            - Calculates relative path from .rasmap to terrain HDF
            - If layer with same name exists, it will be replaced
        """
        rasmap_path = Path(rasmap_path)
        terrain_hdf = Path(terrain_hdf)

        # Validate files exist
        if not rasmap_path.exists():
            raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")

        if not terrain_hdf.exists():
            raise FileNotFoundError(f"Terrain HDF file not found: {terrain_hdf}")

        if projection_prj is not None:
            projection_prj = Path(projection_prj)
            if not projection_prj.exists():
                raise FileNotFoundError(
                    f"Projection PRJ file not found: {projection_prj}"
                )

        # Parse existing rasmap
        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Error parsing .rasmap XML: {e}")

        # Import safe_resolve to preserve Windows drive letters on mapped network drives
        from .RasUtils import RasUtils

        # Calculate relative path from rasmap to terrain HDF
        rasmap_dir = RasUtils.safe_resolve(rasmap_path.parent)
        terrain_hdf_resolved = RasUtils.safe_resolve(terrain_hdf)

        try:
            # Calculate relative path
            rel_path = terrain_hdf_resolved.relative_to(rasmap_dir)
            # Format as Windows-style relative path with .\ prefix
            rel_path_str = ".\\" + str(rel_path).replace("/", "\\")
        except ValueError:
            # If terrain is not relative to rasmap dir, use absolute path
            logger.warning(
                f"Terrain HDF is not under rasmap directory. Using absolute path."
            )
            rel_path_str = str(terrain_hdf_resolved).replace("/", "\\")

        # Find or create Terrains section
        terrains = root.find("Terrains")
        if terrains is None:
            # Create Terrains section - insert after common elements
            terrains = ET.Element("Terrains")
            terrains.set("Checked", "True")
            terrains.set("Expanded", "True")

            # Find appropriate insertion point (after Results if exists, else after Geometries)
            insert_index = 0
            for i, child in enumerate(root):
                if child.tag in ["Results", "Geometries", "EventConditions"]:
                    insert_index = i + 1
            root.insert(insert_index, terrains)
            logger.debug("Created new Terrains section in .rasmap file")

        # Check for existing layer with same name and remove it
        existing_layer = None
        for layer in terrains.findall("Layer"):
            if layer.get("Name") == layer_name:
                existing_layer = layer
                break

        if existing_layer is not None:
            terrains.remove(existing_layer)
            logger.debug("Replaced existing terrain layer: %s", layer_name)

        # Create terrain layer element
        layer = ET.SubElement(terrains, "Layer")
        layer.set("Name", layer_name)
        layer.set("Type", "TerrainLayer")
        layer.set("Checked", "True")
        layer.set("Filename", rel_path_str)

        # Add default settings (matching HEC-RAS 6.x format)
        resample = ET.SubElement(layer, "ResampleMethod")
        resample.text = "near"

        surface = ET.SubElement(layer, "Surface")
        surface.set("On", "True")

        # Update projection reference if provided
        if projection_prj is not None:
            try:
                prj_rel_path = RasUtils.safe_resolve(projection_prj).relative_to(
                    rasmap_dir
                )
                prj_rel_path_str = ".\\" + str(prj_rel_path).replace("/", "\\")
            except ValueError:
                prj_rel_path_str = str(RasUtils.safe_resolve(projection_prj)).replace(
                    "/", "\\"
                )

            # Find or create RASProjectionFilename element
            proj_elem = root.find("RASProjectionFilename")
            if proj_elem is None:
                # Insert after Version element
                proj_elem = ET.Element("RASProjectionFilename")
                version_elem = root.find("Version")
                if version_elem is not None:
                    insert_idx = list(root).index(version_elem) + 1
                else:
                    insert_idx = 0
                root.insert(insert_idx, proj_elem)

            proj_elem.set("Filename", prj_rel_path_str)
            logger.debug("Updated RASMapper projection reference")
            logger.debug("RASMapper projection reference: %s", prj_rel_path_str)

        # Write updated rasmap file
        # Use a custom write to preserve XML formatting
        tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)

        action = "Replaced" if existing_layer is not None else "Added"
        logger.info("%s terrain layer '%s' in .rasmap", action, layer_name)
        logger.debug("Terrain layer '%s' filename: %s", layer_name, rel_path_str)

    # ── Calculated Layers ───────────────────────────────────────────────

    @staticmethod
    @log_call
    def list_results_plans(ras_object=None) -> List[Dict[str, Any]]:
        """
        List all plan result layers in the RASMapper configuration file.

        Enumerates all ``<Layer Type="RASResults">`` entries under the ``<Results>``
        section of the ``.rasmap`` file. These are the valid host plans for
        calculated layers.

        Args:
            ras_object: Optional RasPrj object instance.

        Returns:
            List[Dict[str, Any]]: List of dicts with keys:
                - ``name`` (str): Plan result layer name (e.g., "Prop_10yr_Reg_BO")
                - ``filename`` (str): Relative path to the plan HDF file
                - ``checked`` (bool): Whether the layer is visible

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> plans = RasMap.list_results_plans()
            >>> for p in plans:
            ...     print(f"{p['name']} - {p['filename']}")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return []

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return []

        results = root.find("Results")
        if results is None:
            logger.debug("No Results section found in .rasmap")
            return []

        plans = []
        for layer in results.findall("Layer"):
            if layer.get("Type") == "RASResults":
                plans.append(
                    {
                        "name": layer.get("Name", ""),
                        "filename": layer.get("Filename", ""),
                        "checked": layer.get("Checked", "True").lower() == "true",
                    }
                )

        logger.debug("Found %d results plan(s) in .rasmap", len(plans))
        return plans

    @staticmethod
    @log_call
    def ensure_results_plan_layer(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        name: Optional[str] = None,
        checked: bool = True,
        expanded: bool = True,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Ensure a plan HDF is registered in the RASMapper ``Results`` tree.

        This is useful after cloning and computing a plan programmatically, when
        command-line execution creates ``<project>.p##.hdf`` but does not add a
        corresponding ``RASResults`` layer to the project ``.rasmap``.
        """
        plan_path = _resolve_plan_file_for_rasmap(
            plan_number_or_path,
            ras_object=ras_object,
        )
        project_folder = plan_path.parent
        project_name = _project_name_from_plan_path(plan_path)
        rasmap_path = project_folder / f"{project_name}.rasmap"
        hdf_path = Path(str(plan_path) + ".hdf")

        if not hdf_path.exists():
            raise FileNotFoundError(f"Plan results HDF not found: {hdf_path}")

        if rasmap_path.exists():
            try:
                tree = ET.parse(rasmap_path)
                root = tree.getroot()
            except ET.ParseError as e:
                raise ValueError(f"Error parsing .rasmap XML: {e}") from e
        else:
            root = ET.Element("RASMapper")
            tree = ET.ElementTree(root)

        results = root.find("Results")
        if results is None:
            results = ET.Element("Results", {"Checked": "True", "Expanded": "True"})
            root.append(results)
        else:
            results.set("Checked", results.get("Checked", "True"))
            results.set("Expanded", results.get("Expanded", "True"))

        rel_hdf = _rasmap_relative_path(project_folder, hdf_path)
        rel_hdf_norm = _normalize_rasmap_filename(rel_hdf)
        layer = None
        for candidate in results.findall("Layer"):
            if candidate.get("Type") != "RASResults":
                continue
            if _normalize_rasmap_filename(candidate.get("Filename")) == rel_hdf_norm:
                layer = candidate
                break

        if layer is None:
            layer = ET.SubElement(results, "Layer")

        layer_name = name or _plan_display_name_for_rasmap(plan_path)
        layer.set("Name", layer_name)
        layer.set("Type", "RASResults")
        layer.set("Checked", "True" if checked else "False")
        layer.set("Expanded", "True" if expanded else "False")
        layer.set("Filename", rel_hdf)

        tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
        record = {
            "name": layer_name,
            "filename": rel_hdf,
            "checked": checked,
            "expanded": expanded,
            "rasmap_path": rasmap_path,
        }
        logger.info("Ensured RASResults layer '%s'", layer_name)
        logger.debug("Updated RASMapper file: %s", rasmap_path)
        return record

    @staticmethod
    @log_call
    def ensure_2d_encroachment_plan_layers(
        plan_number_or_path: Union[str, int, float, Path],
        *,
        geom_hdf_path: Optional[Union[str, Path]] = None,
        checked: bool = True,
        ras_object=None,
    ) -> Path:
        """
        Register editable 2D encroachment plan layers in the RASMapper ``Plans`` tree.

        Adds or updates the plan-level ``RASEncroachments`` parent plus the
        ``RASEncroachmentZones`` and ``RASEncroachmentPolygons`` child layers
        used by RASMapper for 2D floodway authoring.
        """
        plan_path = _resolve_plan_file_for_rasmap(
            plan_number_or_path,
            ras_object=ras_object,
        )
        project_folder = plan_path.parent
        project_name = _project_name_from_plan_path(plan_path)
        rasmap_path = project_folder / f"{project_name}.rasmap"

        if rasmap_path.exists():
            try:
                tree = ET.parse(rasmap_path)
                root = tree.getroot()
            except ET.ParseError as e:
                raise ValueError(f"Error parsing .rasmap XML: {e}") from e
        else:
            root = ET.Element("RASMapper")
            tree = ET.ElementTree(root)

        plans = root.find("Plans")
        if plans is None:
            plans = ET.Element("Plans", {"Checked": "True", "Expanded": "True"})
            results = root.find("Results")
            if results is not None:
                root.insert(list(root).index(results), plans)
            else:
                root.append(plans)

        rel_plan = _rasmap_relative_path(project_folder, plan_path)
        geom_hdf = (
            Path(geom_hdf_path)
            if geom_hdf_path is not None
            else _infer_plan_geometry_hdf(plan_path)
        )
        rel_geom = (
            _rasmap_relative_path(project_folder, geom_hdf)
            if geom_hdf is not None
            else ""
        )

        plan_layer = None
        rel_plan_norm = _normalize_rasmap_filename(rel_plan)
        for layer in plans.findall("Layer"):
            if layer.get("Type") != "RASPlan":
                continue
            if _normalize_rasmap_filename(layer.get("Filename")) == rel_plan_norm:
                plan_layer = layer
                break

        if plan_layer is None:
            plan_layer = ET.SubElement(plans, "Layer")

        plan_layer.set("Name", _plan_display_name_for_rasmap(plan_path))
        plan_layer.set("Type", "RASPlan")
        plan_layer.set("Filename", rel_plan)
        plan_layer.set("Checked", "True" if checked else "False")
        if rel_geom:
            plan_layer.set("GeometryHDF", rel_geom)

        child_specs = [
            ("Encroachments", "RASEncroachments"),
            ("Zones", "RASEncroachmentZones"),
            ("Regions", "RASEncroachmentPolygons"),
        ]
        for name, layer_type in child_specs:
            child = None
            for existing in plan_layer.findall("Layer"):
                if existing.get("Type") == layer_type:
                    child = existing
                    break
            if child is None:
                child = ET.SubElement(plan_layer, "Layer")
            child.set("Name", name)
            child.set("Type", layer_type)
            child.set("Filename", rel_plan)

        tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
        logger.info("Ensured 2D encroachment plan layers")
        logger.debug("Updated RASMapper file: %s", rasmap_path)
        return rasmap_path

    @staticmethod
    @log_call
    def list_results_map_layers(ras_object=None) -> List[Dict[str, Any]]:
        """
        List ``RASResultsMap`` child layers under RASMapper result plans.

        Returns dictionaries with the parent result plan name, layer name,
        visibility, and raw ``MapParameters`` attributes.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return []

        try:
            root = ET.parse(rasmap_path).getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return []

        results = root.find("Results")
        if results is None:
            return []

        layers = []
        for results_layer in results.findall("Layer"):
            if results_layer.get("Type") != "RASResults":
                continue
            for child in results_layer.findall("Layer"):
                if child.get("Type") != "RASResultsMap":
                    continue
                map_parameters = child.find("MapParameters")
                layers.append(
                    {
                        "name": child.get("Name", ""),
                        "parent_plan": results_layer.get("Name", ""),
                        "checked": child.get("Checked", "False").lower() == "true",
                        "filename": child.get("Filename", ""),
                        "map_parameters": (
                            dict(map_parameters.attrib)
                            if map_parameters is not None
                            else {}
                        ),
                    }
                )

        logger.debug("Found %d result map layer(s) in .rasmap", len(layers))
        return layers

    @staticmethod
    @log_call
    def add_results_map_layer(
        host_plan_name: str,
        layer_name: str,
        map_type: str,
        *,
        terrain_name: Optional[str] = None,
        profile_index: int = 2147483647,
        profile_name: str = "Max",
        checked: bool = True,
        replace_existing: bool = True,
        ras_object=None,
    ) -> Dict[str, Any]:
        """
        Add a ``RASResultsMap`` child layer under an existing RASMapper result plan.

        This is useful for tutorial workflows that need first-class map layers
        such as ``Depth * Velocity`` before comparing floodway encroachment
        results.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"Error parsing .rasmap XML: {e}") from e

        results = root.find("Results")
        if results is None:
            raise ValueError("No Results section found in .rasmap")

        host_layer = None
        for layer in results.findall("Layer"):
            if (
                layer.get("Type") == "RASResults"
                and layer.get("Name") == host_plan_name
            ):
                host_layer = layer
                break

        if host_layer is None:
            raise ValueError(
                f"RASResults plan '{host_plan_name}' not found in .rasmap Results section"
            )

        if replace_existing:
            for child in list(host_layer.findall("Layer")):
                if (
                    child.get("Type") == "RASResultsMap"
                    and child.get("Name") == layer_name
                ):
                    host_layer.remove(child)

        result_map = ET.SubElement(
            host_layer,
            "Layer",
            {
                "Name": layer_name,
                "Type": "RASResultsMap",
                "Checked": "True" if checked else "False",
            },
        )
        map_parameters = ET.SubElement(result_map, "MapParameters")
        map_parameters.set("MapType", map_type)
        map_parameters.set("LayerName", layer_name)
        if terrain_name:
            map_parameters.set("Terrain", terrain_name)
        map_parameters.set("ProfileIndex", str(profile_index))
        map_parameters.set("ProfileName", profile_name)
        map_parameters.set("ArrivalDepth", "0")

        tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
        record = {
            "name": layer_name,
            "parent_plan": host_plan_name,
            "checked": checked,
            "map_parameters": dict(map_parameters.attrib),
        }
        logger.info(
            "Added result map layer '%s' to plan '%s'", layer_name, host_plan_name
        )
        return record

    @staticmethod
    @log_call
    def list_calculated_layers(ras_object=None) -> List[Dict[str, Any]]:
        """
        List all calculated layers across all plan results in the RASMapper configuration.

        Enumerates all ``<Layer Type="CalculatedLayer">`` entries nested within
        ``<Layer Type="RASResults">`` blocks.

        Args:
            ras_object: Optional RasPrj object instance.

        Returns:
            List[Dict[str, Any]]: List of dicts with keys:
                - ``name`` (str): Calculated layer name
                - ``parent_plan`` (str): Name of the host RASResults plan
                - ``filename`` (str): Relative path to the .rasscript file
                - ``checked`` (bool): Whether the layer is visible
                - ``profile_index`` (str): ProfileIndex attribute value
                - ``raster_maps`` (List[Dict]): Input raster maps, each with
                  ``result``, ``map_type``, ``profile_index``, ``animation_behavior``
                - ``terrains`` (List[str]): Input terrain layer names

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> layers = RasMap.list_calculated_layers()
            >>> for l in layers:
            ...     print(f"{l['name']} (under {l['parent_plan']})")
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return []

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return []

        results = root.find("Results")
        if results is None:
            return []

        calc_layers = []
        for results_layer in results.findall("Layer"):
            if results_layer.get("Type") != "RASResults":
                continue
            parent_plan = results_layer.get("Name", "")

            for child in results_layer.findall("Layer"):
                if child.get("Type") != "CalculatedLayer":
                    continue

                raster_maps = []
                for rm in child.findall("RasterMap"):
                    raster_maps.append(
                        {
                            "result": rm.get("Result", ""),
                            "map_type": rm.get("MapType", ""),
                            "profile_index": rm.get("ProfileIndex", ""),
                            "animation_behavior": rm.get("AnimationBehavior", ""),
                        }
                    )

                terrains = [t.get("Name", "") for t in child.findall("Terrain")]

                calc_layers.append(
                    {
                        "name": child.get("Name", ""),
                        "parent_plan": parent_plan,
                        "filename": child.get("Filename", ""),
                        "checked": child.get("Checked", "False").lower() == "true",
                        "profile_index": child.get("ProfileIndex", "0"),
                        "raster_maps": raster_maps,
                        "terrains": terrains,
                    }
                )

        logger.debug("Found %d calculated layer(s) in .rasmap", len(calc_layers))
        return calc_layers

    @staticmethod
    @log_call
    def add_calculated_layer(
        layer_name: str,
        host_plan_name: str,
        script_content: str,
        raster_maps: List[Dict[str, str]],
        terrain_names: List[str],
        checked: bool = True,
        profile_index: int = 0,
        ras_object=None,
    ) -> bool:
        """
        Add a calculated layer to the RASMapper configuration and write its .rasscript file.

        Creates a ``.rasscript`` file in the ``Calculated Layers/`` subdirectory and
        registers it as a ``<Layer Type="CalculatedLayer">`` under the specified host
        plan's ``<Layer Type="RASResults">`` block. Includes a default viewport-dynamic
        diverging color ramp (blue=benefit, red=adverse).

        If a calculated layer with the same name already exists in the host plan, it is
        replaced (matching the ``add_terrain_layer`` convention).

        Args:
            layer_name: Display name for the calculated layer.
            host_plan_name: Name of the RASResults plan to nest this layer under.
                Must match a ``<Layer Name="..." Type="RASResults">`` in the rasmap.
            script_content: Full VB.NET ``.rasscript`` content string.
            raster_maps: List of dicts defining input raster maps. Each dict should have:
                - ``result`` (str): Plan result name
                - ``map_type`` (str, optional): Default ``"elevation"``
                - ``animation_behavior`` (str, optional): Default ``"Fixed Profile"``
                - ``profile_index`` (str, optional): Default ``"2147483647"`` (Max)
            terrain_names: List of terrain layer names (order must match inputTiles
                indices in the script).
            checked: Whether the layer is visible in RASMapper. Default True.
            profile_index: ProfileIndex attribute for the calculated layer. Default 0.
            ras_object: Optional RasPrj object instance.

        Returns:
            bool: True if the layer was successfully added.

        Raises:
            FileNotFoundError: If the .rasmap file does not exist.
            ValueError: If ``host_plan_name`` is not found in the Results section.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> RasMap.add_calculated_layer(
            ...     layer_name="CompareWSE_10yr_Reg",
            ...     host_plan_name="Prop_10yr_Reg_BO",
            ...     script_content=script_text,
            ...     raster_maps=[
            ...         {"result": "Exist_10yr_Reg_BO"},
            ...         {"result": "Prop_10yr_Reg_BO"},
            ...     ],
            ...     terrain_names=["Bathy_QESDrone_", "Terrain_Proposed_20260313"],
            ... )

        Notes:
            - Creates the ``Calculated Layers`` directory if it doesn't exist.
            - Replaces any existing calculated layer with the same name in the host plan.
            - The .rasscript file is written with UTF-8 encoding.
            - inputTiles indices in the script must match the order of RasterMap
              then Terrain children in the XML.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            raise FileNotFoundError(f"RASMapper file not found: {rasmap_path}")

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return False

        # Find the Results section
        results = root.find("Results")
        if results is None:
            raise ValueError("No Results section found in .rasmap")

        # Find the host plan's RASResults layer
        host_layer = None
        for layer in results.findall("Layer"):
            if (
                layer.get("Type") == "RASResults"
                and layer.get("Name") == host_plan_name
            ):
                host_layer = layer
                break

        if host_layer is None:
            raise ValueError(
                f"RASResults plan '{host_plan_name}' not found in .rasmap Results section"
            )

        # Remove existing calculated layer with same name (replace-if-exists)
        for child in host_layer.findall("Layer"):
            if (
                child.get("Type") == "CalculatedLayer"
                and child.get("Name") == layer_name
            ):
                host_layer.remove(child)
                logger.info(f"Replacing existing calculated layer '{layer_name}'")

        # Create Calculated Layers directory
        calc_dir = ras_obj.project_folder / "Calculated Layers"
        calc_dir.mkdir(parents=True, exist_ok=True)

        # Write .rasscript file
        script_path = calc_dir / f"{layer_name}.rasscript"
        script_path.write_text(script_content, encoding="utf-8")
        logger.debug("Written script: %s", script_path.name)

        # Build relative path with .\ prefix and backslashes
        rel_path_str = f".\\Calculated Layers\\{layer_name}.rasscript"

        # Build XML element
        calc_elem = ET.SubElement(host_layer, "Layer")
        calc_elem.set("Name", layer_name)
        calc_elem.set("Type", "CalculatedLayer")
        calc_elem.set("Checked", "True" if checked else "False")
        calc_elem.set("Filename", rel_path_str)
        calc_elem.set("ProfileIndex", str(profile_index))

        resample = ET.SubElement(calc_elem, "ResampleMethod")
        resample.text = "near"

        # Symbology with viewport-dynamic diverging color ramp
        symbology = ET.SubElement(calc_elem, "Symbology")
        surface_fill = ET.SubElement(symbology, "SurfaceFill")
        surface_fill.set("Colors", _WSE_COMPARISON_DEFAULT_COLORS)
        surface_fill.set("Values", _WSE_COMPARISON_DEFAULT_VALUES)
        surface_fill.set("Stretched", "True")
        surface_fill.set("AlphaTag", "255")
        surface_fill.set("UseDatasetMinMax", "False")
        surface_fill.set("RegenerateForScreen", "True")

        surface = ET.SubElement(calc_elem, "Surface")
        surface.set("On", "True")

        # Add RasterMap inputs
        for rm in raster_maps:
            rm_elem = ET.SubElement(calc_elem, "RasterMap")
            rm_elem.set("Result", rm["result"])
            rm_elem.set("MapType", rm.get("map_type", "elevation"))
            rm_elem.set(
                "AnimationBehavior", rm.get("animation_behavior", "Fixed Profile")
            )
            rm_elem.set("ProfileIndex", rm.get("profile_index", "2147483647"))

        # Add Terrain inputs
        for terrain_name in terrain_names:
            t_elem = ET.SubElement(calc_elem, "Terrain")
            t_elem.set("Name", terrain_name)

        # Write updated rasmap
        tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
        logger.info(f"Added calculated layer '{layer_name}' to plan '{host_plan_name}'")
        return True

    @staticmethod
    @log_call
    def remove_calculated_layer(
        layer_name: str,
        host_plan_name: Optional[str] = None,
        delete_script: bool = False,
        ras_object=None,
    ) -> bool:
        """
        Remove a calculated layer from the RASMapper configuration.

        Args:
            layer_name: Name of the calculated layer to remove.
            host_plan_name: If provided, only search within that specific RASResults
                block. If None, searches all RASResults blocks and removes the first match.
            delete_script: If True, also delete the ``.rasscript`` file from disk.
            ras_object: Optional RasPrj object instance.

        Returns:
            bool: True if the layer was found and removed, False if not found.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> init_ras_project("/path/to/project", "7.0")
            >>> RasMap.remove_calculated_layer("CompareWSE_10yr_Reg", delete_script=True)
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        if not rasmap_path.exists():
            logger.warning(f"RASMapper file not found: {rasmap_path}")
            return False

        try:
            tree = ET.parse(rasmap_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error(f"Error parsing .rasmap XML: {e}")
            return False

        results = root.find("Results")
        if results is None:
            logger.warning("No Results section found in .rasmap")
            return False

        # Determine which RASResults layers to search
        search_layers = []
        for layer in results.findall("Layer"):
            if layer.get("Type") != "RASResults":
                continue
            if host_plan_name is None or layer.get("Name") == host_plan_name:
                search_layers.append(layer)

        # Find and remove
        for results_layer in search_layers:
            for child in results_layer.findall("Layer"):
                if (
                    child.get("Type") == "CalculatedLayer"
                    and child.get("Name") == layer_name
                ):
                    script_filename = child.get("Filename", "")
                    results_layer.remove(child)

                    tree.write(rasmap_path, encoding="utf-8", xml_declaration=False)
                    logger.info(
                        f"Removed calculated layer '{layer_name}' from "
                        f"'{results_layer.get('Name')}'"
                    )

                    if delete_script and script_filename:
                        # Resolve relative path from project folder
                        script_rel = script_filename.replace("\\", "/").lstrip("./")
                        script_path = ras_obj.project_folder / script_rel
                        script_path.unlink(missing_ok=True)
                        logger.debug("Deleted script file: %s", script_path.name)
                        logger.debug("Deleted script path: %s", script_path)

                    return True

        logger.warning(f"Calculated layer '{layer_name}' not found in .rasmap")
        return False

    @staticmethod
    @log_call
    def add_wse_comparison_layers(
        plan_pairs: List[Dict[str, str]],
        exist_terrain: str,
        prop_terrain: str,
        layer_name_template: str = "CompareWSE_{tag}",
        host_plan: str = "proposed",
        ras_object=None,
    ) -> List[str]:
        """
        Add WSE comparison calculated layers for multiple existing/proposed plan pairs.

        Generates ``.rasscript`` files and registers calculated layers for each pair.
        The formula is ``Proposed WSE - Existing WSE``:

        - **Positive values** = WSE raised by project (rise / adverse impact)
        - **Negative values** = WSE lowered by project (drop / benefit)

        When a cell is dry in one plan, the terrain elevation for that plan's scenario
        is used as the WSE fallback.

        Args:
            plan_pairs: List of dicts, each with keys:
                - ``exist_plan`` (str): Name of the existing conditions plan result
                - ``prop_plan`` (str): Name of the proposed conditions plan result
                - ``tag`` (str): Short identifier used in layer naming (e.g., "10yr_Reg")
            exist_terrain: Terrain layer name for existing conditions (dry-cell fallback).
            prop_terrain: Terrain layer name for proposed conditions (dry-cell fallback).
            layer_name_template: Format string for layer names. Must contain ``{tag}``.
                Default: ``"CompareWSE_{tag}"``.
            host_plan: Which plan to host the calculated layer under — ``"proposed"``
                (default) or ``"existing"``.
            ras_object: Optional RasPrj object instance.

        Returns:
            List[str]: Names of successfully created layers.

        Raises:
            ValueError: If a referenced plan name is not found in the Results section,
                or if a terrain name is not found in the Terrains section.

        Examples:
            >>> from ras_commander import init_ras_project, RasMap
            >>> ras = init_ras_project("/path/to/project", "7.0")
            >>> created = RasMap.add_wse_comparison_layers(
            ...     plan_pairs=[
            ...         {"exist_plan": "Exist_10yr_Reg_BO", "prop_plan": "Prop_10yr_Reg_BO", "tag": "10yr_Reg"},
            ...         {"exist_plan": "Exist_10yr_Loc_BO", "prop_plan": "Prop_10yr_Loc_BO", "tag": "10yr_Loc"},
            ...         {"exist_plan": "Exist_100yr_Reg_BO", "prop_plan": "Prop_100yr_Reg_BO", "tag": "100yr_Reg"},
            ...     ],
            ...     exist_terrain="Bathy_QESDrone_",
            ...     prop_terrain="Terrain_Proposed_20260313",
            ... )
            >>> print(f"Created {len(created)} comparison layers")

        Notes:
            - Each plan pair generates one ``.rasscript`` file and one rasmap XML entry.
            - Layers are hosted under the proposed plan by default (``host_plan="proposed"``).
            - Uses Max profile (ProfileIndex=2147483647) with Fixed Profile animation.
            - Includes a viewport-dynamic diverging color ramp by default.
        """
        ras_obj = ras_object or ras
        ras_obj.check_initialized()

        # Validate referenced plans exist
        existing_plans = RasMap.list_results_plans(ras_object=ras_obj)
        plan_names = {p["name"] for p in existing_plans}

        for pair in plan_pairs:
            for key in ("exist_plan", "prop_plan", "tag"):
                if key not in pair:
                    raise ValueError(
                        f"Missing required key '{key}' in plan_pairs entry: {pair}"
                    )
            if pair["exist_plan"] not in plan_names:
                raise ValueError(
                    f"Existing plan '{pair['exist_plan']}' not found in .rasmap Results. "
                    f"Available plans: {sorted(plan_names)}"
                )
            if pair["prop_plan"] not in plan_names:
                raise ValueError(
                    f"Proposed plan '{pair['prop_plan']}' not found in .rasmap Results. "
                    f"Available plans: {sorted(plan_names)}"
                )

        # Validate terrain names exist
        rasmap_path = ras_obj.project_folder / f"{ras_obj.project_name}.rasmap"
        terrain_names = RasMap.get_terrain_names(rasmap_path)
        for t_name in (exist_terrain, prop_terrain):
            if t_name not in terrain_names:
                raise ValueError(
                    f"Terrain '{t_name}' not found in .rasmap. "
                    f"Available terrains: {terrain_names}"
                )

        # Generate calculated layers
        exist_terrain_var = _sanitize_vbnet_identifier(exist_terrain)
        prop_terrain_var = _sanitize_vbnet_identifier(prop_terrain)

        created = []
        for pair in plan_pairs:
            layer_name = layer_name_template.format(tag=pair["tag"])
            host_plan_name = (
                pair["prop_plan"] if host_plan == "proposed" else pair["exist_plan"]
            )

            script_content = _WSE_COMPARISON_RASSCRIPT_TEMPLATE.format(
                layer_name=layer_name,
                exist_plan=pair["exist_plan"],
                prop_plan=pair["prop_plan"],
                exist_terrain_name=exist_terrain,
                prop_terrain_name=prop_terrain,
                exist_terrain_var=exist_terrain_var,
                prop_terrain_var=prop_terrain_var,
            )

            raster_maps = [
                {"result": pair["exist_plan"]},
                {"result": pair["prop_plan"]},
            ]

            success = RasMap.add_calculated_layer(
                layer_name=layer_name,
                host_plan_name=host_plan_name,
                script_content=script_content,
                raster_maps=raster_maps,
                terrain_names=[exist_terrain, prop_terrain],
                ras_object=ras_obj,
            )

            if success:
                created.append(layer_name)
                logger.debug("Created WSE comparison layer: %s", layer_name)
            else:
                logger.warning(f"Failed to create layer: {layer_name}")

        logger.info(
            f"Created {len(created)} of {len(plan_pairs)} WSE comparison layers"
        )
        return created
