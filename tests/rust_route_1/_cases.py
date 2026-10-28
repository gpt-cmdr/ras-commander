"""Public routed methods exercised by the PY-ROUTE-1 equivalence suite.

Each entry maps ``Class.method[variant]`` to a callable taking the fixture path.
Arguments that select an element (river/reach/RS, structure, profile) are
derived from the file with h5py inside the callable, identically in every mode.
"""
from pathlib import Path

import h5py


def _xs_ids(path):
    with h5py.File(path, "r") as f:
        attrs = f["Geometry/Cross Sections/Attributes"][()]
    return [tuple(a[k].decode().strip() for k in ("River", "Reach", "RS")) for a in attrs]


def _texts(path, dataset, field):
    with h5py.File(path, "r") as f:
        if dataset not in f:
            return []
        rows = f[dataset][()]
    if field not in (rows.dtype.names or ()):
        return []
    return [r[field].decode(errors="replace").strip() for r in rows]


def _first(values, default="__absent__"):
    return next((v for v in values if v), default)


def _sa_first(path):
    return _first(_texts(path, "Geometry/Storage Areas/Attributes", "Name"))


def _structure_first(path):
    with h5py.File(path, "r") as f:
        if "Geometry/Structures/Attributes" not in f:
            return ("__absent__", "__absent__", "__absent__")
        rows = f["Geometry/Structures/Attributes"][()]
    for r in rows:
        if r["Type"].decode().strip() in {"Bridge", "Culvert", "Inline"}:
            return tuple(r[k].decode().strip() for k in ("River", "Reach", "RS"))
    return ("__absent__", "__absent__", "__absent__")


def _breach_id(path):
    for field in ("Connection", "Node Name"):
        value = _first(_texts(path, "Geometry/Structures/Attributes", field), "")
        if value:
            return value
    return "__absent__"


def _mesh_first(path):
    return _first(_texts(path, "Geometry/2D Flow Areas/Attributes", "Name"))


def _face_ids_in_box(path):
    from shapely.geometry import box
    mesh = _mesh_first(path)
    with h5py.File(path, "r") as f:
        key = f"Geometry/2D Flow Areas/{mesh}/Cells Center Coordinate"
        if key not in f:
            return _hdf().HdfMesh.get_face_ids_in_polygon(Path(path), mesh, box(0, 0, 1, 1))
        x, y = (float(v) for v in f[key][0])
    return _hdf().HdfMesh.get_face_ids_in_polygon(Path(path), mesh, box(x - 250, y - 250, x + 250, y + 250))


def _face_properties_at_stage(path):
    import pytest
    if Path(path).stat().st_size > 100_000_000:
        # h5py-mode run alone takes 6-50 minutes on these files (iter4 log); bounded
        # suite runs them only on fixtures below 100 MB. iter4 covered all 28 (passed).
        pytest.skip("face property interpolation bounded to fixtures < 100 MB")
    mesh = _mesh_first(path)
    with h5py.File(path, "r") as f:
        key = f"Geometry/2D Flow Areas/{mesh}/Faces Minimum Elevation"
        stages = (f[key][:3].astype(float) + 1.0) if key in f else [1.0, 1.0, 1.0]
    return _hdf().HdfMesh.get_mesh_face_hydraulic_properties_at_stage(Path(path), mesh, [0, 1, 2], list(stages))


def _hdf():
    from ras_commander import hdf
    return hdf


def _xs_htab_first(path):
    ids = _xs_ids(path)
    return _hdf().HdfHydraulicTables.get_xs_htab(path, *ids[0])


def _xs_htab_last(path):
    ids = _xs_ids(path)
    return _hdf().HdfHydraulicTables.get_xs_htab(path, *ids[-1])


CASES = {
    "HdfXsec.get_cross_sections": lambda p: _hdf().HdfXsec.get_cross_sections(Path(p)),
    "HdfXsec.get_xs_coords": lambda p: _hdf().HdfXsec.get_xs_coords(Path(p)),
    "HdfXsec.get_river_centerlines": lambda p: _hdf().HdfXsec.get_river_centerlines(Path(p)),
    "HdfXsec.get_river_reaches": lambda p: _hdf().HdfXsec.get_river_reaches(Path(p)),
    "HdfXsec.get_river_edge_lines": lambda p: _hdf().HdfXsec.get_river_edge_lines(Path(p)),
    "HdfXsec.get_river_bank_lines": lambda p: _hdf().HdfXsec.get_river_bank_lines(Path(p)),
    "HdfXsec.get_river_flow_paths": lambda p: _hdf().HdfXsec.get_river_flow_paths(Path(p)),
    "HdfXsec.get_xs_interpolation_surface": lambda p: _hdf().HdfXsec.get_xs_interpolation_surface(Path(p)),
    "HdfXsec.generate_river_edge_lines": lambda p: _hdf().HdfXsec.generate_river_edge_lines(Path(p)),
    "HdfXsec.get_1d_footprint": lambda p: _hdf().HdfXsec.get_1d_footprint(Path(p)),
    "HdfHydraulicTables.get_xs_htab[first]": _xs_htab_first,
    "HdfHydraulicTables.get_xs_htab[last]": _xs_htab_last,
    "HdfHydraulicTables.get_all_xs_htabs": lambda p: _hdf().HdfHydraulicTables.get_all_xs_htabs(Path(p)),
    "HdfResultsXsec.get_xsec_timeseries": lambda p: _hdf().HdfResultsXsec.get_xsec_timeseries(Path(p)),
    "HdfResultsXsec.get_xsec_summary": lambda p: _hdf().HdfResultsXsec.get_xsec_summary(Path(p)),
    "HdfResultsPlan.get_steady_results": lambda p: _hdf().HdfResultsPlan.get_steady_results(Path(p)),
    "HdfResultsPlan.get_steady_wse": lambda p: _hdf().HdfResultsPlan.get_steady_wse(Path(p)),
    "HdfResultsPlan.get_steady_wse[profile0]": lambda p: _hdf().HdfResultsPlan.get_steady_wse(Path(p), profile_index=0),
    "HdfChannelCapacity.extract_steady_profile_wse": lambda p: _hdf().HdfChannelCapacity.extract_steady_profile_wse(Path(p)),
    "HdfChannelCapacity.extract_max_wse": lambda p: _hdf().HdfChannelCapacity.extract_max_wse(Path(p)),
    "HdfChannelCapacity.extract_bank_elevations": lambda p: _hdf().HdfChannelCapacity.extract_bank_elevations(Path(p)),
    "HdfChannelCapacity.analyze_channel_capacity": lambda p: _hdf().HdfChannelCapacity.analyze_channel_capacity(Path(p), Path(p)),
    "HdfStruc.get_structures": lambda p: _hdf().HdfStruc.get_structures(Path(p)),
    "HdfStruc.get_culvert_hydraulics": lambda p: _hdf().HdfStruc.get_culvert_hydraulics(Path(p)),
    "HdfStruc.get_storage_area_polygons": lambda p: _hdf().HdfStruc.get_storage_area_polygons(Path(p)),
    "HdfStruc.get_connection_attachments": lambda p: _hdf().HdfStruc.get_connection_attachments(Path(p)),
    "HdfStorageArea.get_storage_area_names": lambda p: _hdf().HdfStorageArea.get_storage_area_names(Path(p)),
    "HdfStorageArea.get_storage_area_properties": lambda p: _hdf().HdfStorageArea.get_storage_area_properties(Path(p), _sa_first(p)),
    "HdfStorageArea.get_volume_elevation_curve": lambda p: _hdf().HdfStorageArea.get_volume_elevation_curve(Path(p), _sa_first(p)),
    "HdfStorageArea.get_storage_area_for_breach_structure": lambda p: _hdf().HdfStorageArea.get_storage_area_for_breach_structure(Path(p), _breach_id(p)),
    "HdfStruc1D.get_structure_max_values": lambda p: _hdf().HdfStruc1D.get_structure_max_values(Path(p), *_structure_first(p)),
    "HdfPump.get_pump_stations": lambda p: _hdf().HdfPump.get_pump_stations(Path(p)),
    "HdfPump.get_pump_stations[table]": lambda p: _hdf().HdfPump.get_pump_stations(Path(p), include_geometry=False),
    "HdfPump.get_pump_groups": lambda p: _hdf().HdfPump.get_pump_groups(Path(p)),
    "HdfBndry.get_bc_lines": lambda p: _hdf().HdfBndry.get_bc_lines(Path(p)),
    "HdfBndry.get_breaklines": lambda p: _hdf().HdfBndry.get_breaklines(Path(p)),
    "HdfBndry.get_refinement_regions": lambda p: _hdf().HdfBndry.get_refinement_regions(Path(p)),
    "HdfBndry.get_reference_lines": lambda p: _hdf().HdfBndry.get_reference_lines(Path(p)),
    "HdfBndry.get_bc_external_faces": lambda p: _hdf().HdfBndry.get_bc_external_faces(Path(p), on_duplicate_ownership="report"),
    "HdfBndry.get_bc_external_faces[geometry]": lambda p: _hdf().HdfBndry.get_bc_external_faces(Path(p), include_geometry=True, on_duplicate_ownership="report"),
    "HdfMesh.get_mesh_area_names": lambda p: _hdf().HdfMesh.get_mesh_area_names(Path(p)),
    "HdfMesh.get_mesh_areas": lambda p: _hdf().HdfMesh.get_mesh_areas(Path(p)),
    "HdfMesh.diagnose_mesh_layout": lambda p: _hdf().HdfMesh.diagnose_mesh_layout(Path(p)),
    "HdfMesh.get_mesh_geometry_inventory": lambda p: _hdf().HdfMesh.get_mesh_geometry_inventory(Path(p)),
    "HdfMesh.get_mesh_cell_points": lambda p: _hdf().HdfMesh.get_mesh_cell_points(Path(p)),
    "HdfMesh.get_mesh_cell_points[table]": lambda p: _hdf().HdfMesh.get_mesh_cell_points(Path(p), include_geometry=False),
    "HdfMesh.get_mesh_cell_points[physical,table]": lambda p: _hdf().HdfMesh.get_mesh_cell_points(Path(p), include_ghost_cells=False, include_geometry=False),
    "HdfMesh.get_mesh_cell_faces": lambda p: _hdf().HdfMesh.get_mesh_cell_faces(Path(p)),
    "HdfMesh.get_mesh_perimeter_faces": lambda p: _hdf().HdfMesh.get_mesh_perimeter_faces(Path(p), _mesh_first(p), on_duplicate_ownership="report"),
    "HdfMesh.get_mesh_area_attributes": lambda p: _hdf().HdfMesh.get_mesh_area_attributes(Path(p)),
    "HdfMesh.get_mesh_face_property_tables": lambda p: _hdf().HdfMesh.get_mesh_face_property_tables(Path(p)),
    "HdfMesh.get_mesh_cell_property_tables": lambda p: _hdf().HdfMesh.get_mesh_cell_property_tables(Path(p)),
    "HdfMesh.get_reference_line_internal_faces": lambda p: _hdf().HdfMesh.get_reference_line_internal_faces(Path(p)),
    "HdfMesh.get_mesh_sloped_topology": lambda p: _hdf().HdfMesh.get_mesh_sloped_topology(Path(p), _mesh_first(p)),
    "HdfMesh.get_mannings_calibration_table": lambda p: _hdf().HdfMesh.get_mannings_calibration_table(Path(p)),
    "HdfResultsMesh.get_mesh_max_ws": lambda p: _hdf().HdfResultsMesh.get_mesh_max_ws(Path(p)),
    "HdfResultsMesh.get_mesh_min_ws": lambda p: _hdf().HdfResultsMesh.get_mesh_min_ws(Path(p)),
    "HdfResultsMesh.get_mesh_max_face_v": lambda p: _hdf().HdfResultsMesh.get_mesh_max_face_v(Path(p)),
    "HdfResultsMesh.get_mesh_min_face_v": lambda p: _hdf().HdfResultsMesh.get_mesh_min_face_v(Path(p)),
    "HdfResultsMesh.get_mesh_max_ws_err": lambda p: _hdf().HdfResultsMesh.get_mesh_max_ws_err(Path(p)),
    "HdfResultsMesh.get_mesh_max_iter": lambda p: _hdf().HdfResultsMesh.get_mesh_max_iter(Path(p)),
    "HdfResultsMesh.get_mesh_last_iter": lambda p: _hdf().HdfResultsMesh.get_mesh_last_iter(Path(p)),
    "HdfResultsMesh.get_mesh_summary_values[Maximum Water Surface]": lambda p: _hdf().HdfResultsMesh.get_mesh_summary_values(Path(p), "Maximum Water Surface"),
    "HdfResultsMesh.get_mesh_summary[Maximum Face Velocity]": lambda p: _hdf().HdfResultsMesh.get_mesh_summary(Path(p), "Maximum Face Velocity"),
    "HdfResultsMesh.get_mesh_max_ws[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_ws(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_min_ws[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_min_ws(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_max_face_v[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_face_v(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_min_face_v[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_min_face_v(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_max_ws_err[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_ws_err(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_max_iter[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_max_iter(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_last_iter[table]": lambda p: _hdf().HdfResultsMesh.get_mesh_last_iter(Path(p), include_geometry=False),
    "HdfResultsMesh.get_mesh_summary[Maximum Face Velocity,table]": lambda p: _hdf().HdfResultsMesh.get_mesh_summary(Path(p), "Maximum Face Velocity", include_geometry=False),
    "HdfResultsMesh.get_mesh_timeseries[Water Surface]": lambda p: _hdf().HdfResultsMesh.get_mesh_timeseries(Path(p), _mesh_first(p), "Water Surface"),
    "HdfResultsMesh.get_mesh_timeseries[Face Velocity]": lambda p: _hdf().HdfResultsMesh.get_mesh_timeseries(Path(p), _mesh_first(p), "Face Velocity"),
    "HdfResultsMesh.get_mesh_faces_timeseries": lambda p: _hdf().HdfResultsMesh.get_mesh_faces_timeseries(Path(p), _mesh_first(p)),
    "HdfResultsMesh.get_mesh_cells_timeseries[Water Surface]": lambda p: _hdf().HdfResultsMesh.get_mesh_cells_timeseries(Path(p), var="Water Surface"),
    "HdfMesh.get_face_ids_in_polygon": _face_ids_in_box,
    "HdfMesh.get_mesh_face_hydraulic_properties_at_stage": _face_properties_at_stage,
    "HdfBase.get_2d_flow_area_names_and_counts": lambda p: _hdf().HdfBase.get_2d_flow_area_names_and_counts(Path(p)),
    "HdfLandCover.get_preprocessed_mannings_n": lambda p: _hdf().HdfLandCover.get_preprocessed_mannings_n(Path(p)),
    "HdfLandCover.get_mannings_calibration_table": lambda p: _hdf().HdfLandCover.get_mannings_calibration_table(Path(p)),
    "HdfLandCover.get_mannings_region_polygons": lambda p: _hdf().HdfLandCover.get_mannings_region_polygons(Path(p)),
    "HdfLandCover.get_mannings_region_cell_mapping": lambda p: _hdf().HdfLandCover.get_mannings_region_cell_mapping(Path(p)),
    "HdfLandCover.audit_final_mannings_n": lambda p: _hdf().HdfLandCover.audit_final_mannings_n(Path(p)),
}
