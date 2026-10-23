"""Frozen pre-vectorization method body for PERF-3 contract comparisons.

Source commit: 804d90767d993256ded9b6e983d851c41485a16b
Source: ras_commander/hdf/HdfMesh.py::get_mesh_cell_points
Original dedented method SHA256: b6dc32c8dfc13ceae500f4c65be796ec750bfbb0daff45972dd5372c3c05edb9
Only the function name and class binding/decorators differ; the method body is unchanged.
ras-commander MIT license applies (see repository LICENSE).
"""
from pathlib import Path
import h5py
from ras_commander import HdfMesh, HdfBase, get_logger
from ras_commander.fast_hdf import read_dataset
from ras_commander.Decorators import log_call, standardize_input
logger = get_logger(__name__)

@log_call
@standardize_input(file_type='geom_hdf')
def previous_cell_points(
        hdf_path: Path,
        include_ghost_cells: bool = True,
    ) -> 'GeoDataFrame':
        """
        Return 2D flow mesh cell center points.

        Parameters
        ----------
        hdf_path : Path
            Path to the HEC-RAS geometry HDF file.
        include_ghost_cells : bool, optional
            ``Cells Center Coordinate`` lists the physical cells followed by
            ghost cells outside the perimeter (IDs at or above the area's
            ``Attributes`` ``Cell Count``). Default True returns every entry.
            Pass False to return physical cells only, matching mesh polygons
            and the default ghost-free ``HdfResultsMesh`` cell results. A mesh
            whose ``Cell Count`` is not recorded keeps every entry.

        Returns
        -------
        GeoDataFrame
            A GeoDataFrame containing the 2D flow mesh cell center points with columns:
            - mesh_name: str - Name of the 2D flow area
            - cell_id: int - Unique cell identifier (0-indexed)
            - geometry: Point - Cell center point geometry
        """
        # Lazy imports for heavy dependencies
        from geopandas import GeoDataFrame
        from shapely.geometry import Point

        try:
            with h5py.File(hdf_path, 'r') as hdf_file:
                mesh_area_names = HdfMesh.get_mesh_area_names(hdf_path)
                if not mesh_area_names:
                    return GeoDataFrame()

                # Pre-allocate lists
                all_mesh_names = []
                all_cell_ids = []
                all_points = []
                physical_counts = (
                    {} if include_ghost_cells else HdfMesh._physical_cell_counts(hdf_file)
                )

                for mesh_name in mesh_area_names:
                    # Get all cell centers in one read
                    cell_centers = read_dataset(hdf_file[f"Geometry/2D Flow Areas/{mesh_name}/Cells Center Coordinate"])
                    if mesh_name in physical_counts:
                        cell_centers = cell_centers[:physical_counts[mesh_name]]
                    cell_count = len(cell_centers)

                    # Extend lists efficiently
                    all_mesh_names.extend([mesh_name] * cell_count)
                    all_cell_ids.extend(range(cell_count))
                    all_points.extend(Point(coords) for coords in cell_centers)

                # Create GeoDataFrame in one go
                return GeoDataFrame(
                    {
                        "mesh_name": all_mesh_names,
                        "cell_id": all_cell_ids,
                        "geometry": all_points
                    },
                    geometry="geometry",
                    crs=HdfBase.get_projection(hdf_file)
                )

        except Exception as e:
            logger.error(f"Error reading mesh cell points from {hdf_path}: {str(e)}")
            return GeoDataFrame()
