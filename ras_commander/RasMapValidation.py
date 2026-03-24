"""
RasMapValidation - Validation methods for HEC-RAS map layers

Extracted from RasMap.py to reduce module size. All methods are accessible via
both RasMapValidation.method_name() and RasMap.method_name() (backward compat).

Classes:
    RasMapValidation: Static class with layer validation methods.
"""

from pathlib import Path
from typing import Union, Optional, List

from .LoggingConfig import get_logger
from .Decorators import log_call

logger = get_logger(__name__)


class RasMapValidation:
    """
    Validation methods for HEC-RAS map layers.

    Validates layer formats (GeoJSON, Shapefile, GeoTIFF, HDF),
    CRS/projections, raster metadata, spatial extents, and
    terrain/land cover layer configurations.

    All methods are static and designed to be used without instantiation.
    """

    @staticmethod
    @log_call
    def check_layer_format(layer_file: Union[str, Path]) -> 'ValidationResult':
        """
        Check layer file format validity.

        Validates:
        - File exists
        - Format is supported (GeoJSON, Shapefile, GeoTIFF, HDF)
        - File can be opened and read

        Args:
            layer_file: Path to layer file

        Returns:
            ValidationResult with format validation

        Example:
            >>> from ras_commander import RasMapValidation
            >>> result = RasMapValidation.check_layer_format("terrain.tif")
            >>> if result.is_valid:
            ...     print(f"Format valid: {result.context.get('format')}")
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity

        layer_file = Path(layer_file)

        if not layer_file.exists():
            return ValidationResult(
                check_name="file_existence",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"File not found: {layer_file}"
            )

        try:
            with open(layer_file, 'rb') as f:
                _ = f.read(1)
        except PermissionError:
            return ValidationResult(
                check_name="file_accessibility",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Permission denied reading file: {layer_file}"
            )
        except Exception as e:
            return ValidationResult(
                check_name="file_accessibility",
                severity=ValidationSeverity.ERROR,
                passed=False,
                message=f"Cannot read file: {e}"
            )

        suffix = layer_file.suffix.lower()
        format_map = {
            '.geojson': 'geojson', '.json': 'geojson',
            '.shp': 'shapefile',
            '.tif': 'geotiff', '.tiff': 'geotiff',
            '.hdf': 'hdf', '.h5': 'hdf'
        }

        detected_format = format_map.get(suffix)

        if detected_format is None:
            return ValidationResult(
                check_name="format_detection",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message=f"Unrecognized file extension: {suffix}",
                details={"extension": suffix}
            )

        try:
            if detected_format == 'geojson':
                return RasMapValidation._validate_geojson_format(layer_file)
            elif detected_format == 'shapefile':
                return RasMapValidation._validate_shapefile_format(layer_file)
            elif detected_format == 'geotiff':
                return RasMapValidation._validate_geotiff_format(layer_file)
            elif detected_format == 'hdf':
                return RasMapValidation._validate_hdf_format(layer_file)
        except ImportError:
            return ValidationResult(
                check_name="format_validation",
                severity=ValidationSeverity.WARNING,
                passed=True,
                message=f"File format appears valid ({detected_format}), but validation library not available",
                details={"format": detected_format}
            )

        return ValidationResult(
            check_name="format_validation",
            severity=ValidationSeverity.INFO,
            passed=True,
            message=f"File format appears valid: {detected_format}",
            details={"format": detected_format}
        )

    @staticmethod
    def _validate_geojson_format(layer_file: Path) -> 'ValidationResult':
        """Validate GeoJSON file format and structure."""
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity
        try:
            import geopandas as gpd
            gdf = gpd.read_file(layer_file)
            return ValidationResult(
                check_name="geojson_format", severity=ValidationSeverity.INFO, passed=True,
                message=f"GeoJSON format valid ({len(gdf)} features)",
                details={"feature_count": len(gdf), "geometry_types": gdf.geom_type.unique().tolist(),
                         "crs": str(gdf.crs) if gdf.crs else None}
            )
        except ImportError:
            return ValidationResult(check_name="geojson_format", severity=ValidationSeverity.WARNING,
                                    passed=True, message="geopandas not available, cannot validate GeoJSON structure")
        except Exception as e:
            return ValidationResult(check_name="geojson_format", severity=ValidationSeverity.ERROR,
                                    passed=False, message=f"Failed to read GeoJSON: {e}")

    @staticmethod
    def _validate_shapefile_format(layer_file: Path) -> 'ValidationResult':
        """Validate Shapefile format and structure."""
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity
        try:
            import geopandas as gpd
            gdf = gpd.read_file(layer_file)
            return ValidationResult(
                check_name="shapefile_format", severity=ValidationSeverity.INFO, passed=True,
                message=f"Shapefile format valid ({len(gdf)} features)",
                details={"feature_count": len(gdf), "geometry_types": gdf.geom_type.unique().tolist(),
                         "crs": str(gdf.crs) if gdf.crs else None}
            )
        except ImportError:
            return ValidationResult(check_name="shapefile_format", severity=ValidationSeverity.WARNING,
                                    passed=True, message="geopandas not available, cannot validate Shapefile structure")
        except Exception as e:
            return ValidationResult(check_name="shapefile_format", severity=ValidationSeverity.ERROR,
                                    passed=False, message=f"Failed to read Shapefile: {e}")

    @staticmethod
    def _validate_geotiff_format(layer_file: Path) -> 'ValidationResult':
        """Validate GeoTIFF raster format and metadata."""
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity
        try:
            import rasterio
            with rasterio.open(layer_file) as src:
                details = {"width": src.width, "height": src.height, "bands": src.count,
                           "dtype": str(src.dtypes[0]),
                           "crs": src.crs.to_string() if src.crs else None,
                           "resolution": (src.res[0], src.res[1]), "bounds": src.bounds}
                return ValidationResult(
                    check_name="geotiff_format", severity=ValidationSeverity.INFO, passed=True,
                    message=f"GeoTIFF format valid ({details['width']}x{details['height']}, {details['bands']} bands)",
                    details=details)
        except ImportError:
            return ValidationResult(check_name="geotiff_format", severity=ValidationSeverity.WARNING,
                                    passed=True, message="rasterio not available, cannot validate GeoTIFF structure")
        except Exception as e:
            return ValidationResult(check_name="geotiff_format", severity=ValidationSeverity.ERROR,
                                    passed=False, message=f"Failed to read GeoTIFF: {e}")

    @staticmethod
    def _validate_hdf_format(layer_file: Path) -> 'ValidationResult':
        """Validate HDF file format."""
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity
        try:
            import h5py
            with h5py.File(layer_file, 'r') as hdf:
                groups = list(hdf.keys())
                return ValidationResult(
                    check_name="hdf_format", severity=ValidationSeverity.INFO, passed=True,
                    message=f"HDF format valid ({len(groups)} root groups)",
                    details={"groups": groups})
        except ImportError:
            return ValidationResult(check_name="hdf_format", severity=ValidationSeverity.WARNING,
                                    passed=True, message="h5py not available, cannot validate HDF structure")
        except Exception as e:
            return ValidationResult(check_name="hdf_format", severity=ValidationSeverity.ERROR,
                                    passed=False, message=f"Failed to read HDF: {e}")

    @staticmethod
    @log_call
    def check_layer_crs(
        layer_file: Union[str, Path],
        expected_epsg: Optional[int] = None
    ) -> 'ValidationResult':
        """
        Check layer CRS/projection validity.

        For GeoJSON files, enforces WGS84 (EPSG:4326) requirement.
        For other formats, checks against expected CRS if provided.

        Args:
            layer_file: Path to layer file
            expected_epsg: Optional expected EPSG code (e.g., 4326 for WGS84)

        Returns:
            ValidationResult with CRS validation
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity

        layer_file = Path(layer_file)
        suffix = layer_file.suffix.lower()
        expected_crs = f"EPSG:{expected_epsg}" if expected_epsg else None

        try:
            if suffix in ['.geojson', '.json', '.shp']:
                import geopandas as gpd
                gdf = gpd.read_file(layer_file)

                if gdf.crs is None:
                    return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                            passed=True, message="Layer has no CRS defined (assuming WGS84)",
                                            details={"crs": None})

                crs_string = gdf.crs.to_string()

                if suffix in ['.geojson', '.json'] and crs_string != "EPSG:4326":
                    return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.ERROR,
                                            passed=False,
                                            message=f"GeoJSON must be in WGS84 (EPSG:4326), got {crs_string}",
                                            details={"actual_crs": crs_string, "required_crs": "EPSG:4326"})

                if expected_crs and crs_string != expected_crs:
                    return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                            passed=True,
                                            message=f"CRS mismatch: expected {expected_crs}, got {crs_string}",
                                            details={"expected_crs": expected_crs, "actual_crs": crs_string})

                return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.INFO,
                                        passed=True, message=f"CRS valid: {crs_string}",
                                        details={"crs": crs_string})

            elif suffix in ['.tif', '.tiff']:
                import rasterio
                with rasterio.open(layer_file) as src:
                    if src.crs is None:
                        return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                                passed=True, message="Raster has no CRS defined",
                                                details={"crs": None})

                    crs_string = src.crs.to_string()
                    if expected_crs and crs_string != expected_crs:
                        return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                                passed=True,
                                                message=f"CRS mismatch: expected {expected_crs}, got {crs_string}",
                                                details={"expected_crs": expected_crs, "actual_crs": crs_string})

                    return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.INFO,
                                            passed=True, message=f"CRS valid: {crs_string}",
                                            details={"crs": crs_string})

        except ImportError as e:
            return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                    passed=True, message=f"Required library not available: {e}")
        except Exception as e:
            return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.WARNING,
                                    passed=True, message=f"Could not check CRS: {e}")

        return ValidationResult(check_name="crs_validation", severity=ValidationSeverity.INFO,
                                passed=True, message="CRS check not applicable for this file type")

    @staticmethod
    @log_call
    def check_raster_metadata(
        layer_file: Union[str, Path],
        max_resolution: Optional[float] = 100.0,
        check_nodata: bool = True
    ) -> List['ValidationResult']:
        """
        Check raster metadata (resolution, extent, nodata).

        Args:
            layer_file: Path to raster file
            max_resolution: Maximum acceptable resolution in meters (warn if coarser)
            check_nodata: If True, check nodata percentage

        Returns:
            List[ValidationResult]: Raster metadata validation results
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity

        layer_file = Path(layer_file)
        results = []

        try:
            import rasterio
            import numpy as np

            with rasterio.open(layer_file) as src:
                resolution = max(abs(src.res[0]), abs(src.res[1]))

                if max_resolution and resolution > max_resolution:
                    results.append(ValidationResult(
                        check_name="resolution_check", severity=ValidationSeverity.WARNING, passed=True,
                        message=f"Raster resolution is coarse: {resolution:.2f} meters (limit: {max_resolution} m)",
                        details={"resolution": resolution, "max_resolution": max_resolution}))
                else:
                    results.append(ValidationResult(
                        check_name="resolution_check", severity=ValidationSeverity.INFO, passed=True,
                        message=f"Raster resolution acceptable: {resolution:.2f} meters",
                        details={"resolution": resolution}))

                if check_nodata:
                    try:
                        data = src.read(1, masked=True)
                        if hasattr(data, 'mask'):
                            nodata_pct = (data.mask.sum() / data.size) * 100
                            severity = ValidationSeverity.WARNING if nodata_pct > 50 else ValidationSeverity.INFO
                            results.append(ValidationResult(
                                check_name="nodata_check", severity=severity, passed=True,
                                message=f"Raster nodata: {nodata_pct:.1f}%",
                                details={"nodata_percent": nodata_pct}))
                        else:
                            results.append(ValidationResult(
                                check_name="nodata_check", severity=ValidationSeverity.INFO, passed=True,
                                message="Raster has no masked/nodata values"))
                    except Exception as e:
                        results.append(ValidationResult(
                            check_name="nodata_check", severity=ValidationSeverity.WARNING, passed=True,
                            message=f"Could not check nodata: {e}"))

                bounds = src.bounds
                results.append(ValidationResult(
                    check_name="extent_info", severity=ValidationSeverity.INFO, passed=True,
                    message=f"Raster extent: ({bounds.left:.2f}, {bounds.bottom:.2f}, {bounds.right:.2f}, {bounds.top:.2f})",
                    details={"bounds": (bounds.left, bounds.bottom, bounds.right, bounds.top)}))

        except ImportError:
            results.append(ValidationResult(check_name="raster_metadata", severity=ValidationSeverity.WARNING,
                                            passed=True, message="rasterio not available, cannot validate raster metadata"))
        except Exception as e:
            results.append(ValidationResult(check_name="raster_metadata", severity=ValidationSeverity.ERROR,
                                            passed=False, message=f"Failed to read raster metadata: {e}"))
        return results

    @staticmethod
    @log_call
    def check_spatial_extent(
        layer_file: Union[str, Path],
        model_extent: tuple,
        min_coverage_pct: float = 50.0
    ) -> 'ValidationResult':
        """
        Check layer spatial extent vs model domain.

        Args:
            layer_file: Path to layer file
            model_extent: Model bounding box (minx, miny, maxx, maxy)
            min_coverage_pct: Minimum coverage percentage (warn if below)

        Returns:
            ValidationResult: Spatial extent validation result
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity

        layer_file = Path(layer_file)
        suffix = layer_file.suffix.lower()

        try:
            from shapely.geometry import box
            model_box = box(*model_extent)

            if suffix in ['.tif', '.tiff']:
                import rasterio
                with rasterio.open(layer_file) as src:
                    layer_box = box(*src.bounds)
            elif suffix in ['.geojson', '.json', '.shp']:
                import geopandas as gpd
                gdf = gpd.read_file(layer_file)
                layer_box = box(*gdf.total_bounds)
            else:
                return ValidationResult(check_name="spatial_coverage", severity=ValidationSeverity.INFO,
                                        passed=True, message="Spatial coverage check not applicable for this file type")

            if not model_box.intersects(layer_box):
                return ValidationResult(
                    check_name="spatial_coverage", severity=ValidationSeverity.ERROR, passed=False,
                    message="Layer does not overlap with model domain",
                    details={"model_extent": model_extent, "layer_extent": layer_box.bounds})

            intersection = model_box.intersection(layer_box)
            coverage_pct = (intersection.area / model_box.area) * 100

            if coverage_pct < min_coverage_pct:
                return ValidationResult(
                    check_name="spatial_coverage", severity=ValidationSeverity.WARNING, passed=True,
                    message=f"Layer only covers {coverage_pct:.1f}% of model domain (minimum: {min_coverage_pct:.1f}%)",
                    details={"coverage_percent": coverage_pct, "min_coverage_pct": min_coverage_pct})

            return ValidationResult(
                check_name="spatial_coverage", severity=ValidationSeverity.INFO, passed=True,
                message=f"Layer covers {coverage_pct:.1f}% of model domain",
                details={"coverage_percent": coverage_pct})

        except ImportError as e:
            return ValidationResult(check_name="spatial_coverage", severity=ValidationSeverity.WARNING,
                                    passed=True, message=f"Required library not available: {e}")
        except Exception as e:
            return ValidationResult(check_name="spatial_coverage", severity=ValidationSeverity.WARNING,
                                    passed=True, message=f"Could not check spatial coverage: {e}")

    @staticmethod
    @log_call
    def check_terrain_layer(
        rasmap_path: Union[str, Path],
        layer_name: str
    ) -> 'ValidationResult':
        """
        Check terrain layer configuration in rasmap file.

        Args:
            rasmap_path: Path to .rasmap file
            layer_name: Name of terrain layer

        Returns:
            ValidationResult: Terrain validation result
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity
        from .RasMap import RasMap

        rasmap_path = Path(rasmap_path)
        try:
            terrain_names = RasMap.get_terrain_names(rasmap_path)
            if layer_name not in terrain_names:
                return ValidationResult(
                    check_name="terrain_layer_exists", severity=ValidationSeverity.ERROR, passed=False,
                    message=f"Terrain layer '{layer_name}' not found in rasmap",
                    details={"layer_name": layer_name, "available": terrain_names})
        except Exception as e:
            return ValidationResult(
                check_name="terrain_layer_exists", severity=ValidationSeverity.ERROR, passed=False,
                message=f"Failed to read rasmap file: {e}")

        return ValidationResult(
            check_name="terrain_layer_validation", severity=ValidationSeverity.INFO, passed=True,
            message=f"Terrain layer '{layer_name}' found in rasmap",
            details={"layer_name": layer_name})

    @staticmethod
    @log_call
    def check_land_cover_layer(
        rasmap_path: Union[str, Path],
        layer_name: str
    ) -> 'ValidationResult':
        """
        Check land cover layer configuration in rasmap file.

        Args:
            rasmap_path: Path to .rasmap file
            layer_name: Name of land cover layer

        Returns:
            ValidationResult: Land cover validation result
        """
        from ras_commander.RasValidation import ValidationResult, ValidationSeverity

        return ValidationResult(
            check_name="land_cover_validation", severity=ValidationSeverity.INFO, passed=True,
            message=f"Land cover validation for '{layer_name}' not yet implemented",
            details={"layer_name": layer_name})

    @staticmethod
    @log_call
    def check_layer(
        rasmap_path: Union[str, Path],
        layer_name: str,
        layer_type: Optional[str] = None
    ) -> 'ValidationReport':
        """
        Comprehensive layer validation.

        Args:
            rasmap_path: Path to .rasmap file
            layer_name: Name of layer to validate
            layer_type: Optional layer type ('Terrain', 'Land Cover', etc.)

        Returns:
            ValidationReport with all validation results
        """
        from ras_commander.RasValidation import ValidationReport
        from datetime import datetime

        rasmap_path = Path(rasmap_path)
        results = []

        if layer_type == "Terrain":
            results.append(RasMapValidation.check_terrain_layer(rasmap_path, layer_name))
        elif layer_type == "Land Cover":
            results.append(RasMapValidation.check_land_cover_layer(rasmap_path, layer_name))
        else:
            from ras_commander.RasValidation import ValidationResult, ValidationSeverity
            results.append(ValidationResult(
                check_name="layer_type", severity=ValidationSeverity.INFO, passed=True,
                message=f"Layer type '{layer_type}' validation not specialized",
                details={"layer_name": layer_name, "layer_type": layer_type}))

        return ValidationReport(target=f"{rasmap_path} - {layer_name}",
                                timestamp=datetime.now(), results=results)

    @staticmethod
    def is_valid_layer(
        rasmap_path: Union[str, Path],
        layer_name: str,
        layer_type: Optional[str] = None
    ) -> bool:
        """
        Quick boolean check for layer validity.

        Args:
            rasmap_path: Path to .rasmap file
            layer_name: Name of layer to validate
            layer_type: Optional layer type

        Returns:
            True if layer is valid
        """
        report = RasMapValidation.check_layer(rasmap_path, layer_name, layer_type)
        return all(result.passed for result in report.results)
