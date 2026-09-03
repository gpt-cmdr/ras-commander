"""Prepare contained, pure-2D breakout geometries without authoring boundaries.

The workflow is deliberately split into four auditable stages:

1. qualify a proposed child polygon against an existing pure-2D plan;
2. clone the plan, geometry, and unsteady file inside an isolated project;
3. trim mesh-owned geometry and regenerate the cloned mesh; and
4. review parent-face flux locations without changing the cloned boundaries.

Boundary-condition interpretation is intentionally out of scope.  The cloned
unsteady file is byte-identical to its source, existing geometry BC lines are
left untouched, and the flux review returns evidence rather than authored
``Flow Hydrograph``, ``Stage Hydrograph``, or ``Normal Depth`` records.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import geopandas as gpd
import h5py
import numpy as np
import pandas as pd
from pyproj import CRS
from shapely import contains_xy, intersects_xy, make_valid
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Polygon,
)
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import linemerge, unary_union

from .Decorators import log_call
from .LoggingConfig import get_logger
from .RasGeo import RasGeo
from .RasMap import RasMap
from .RasPlan import RasPlan
from .RasPrj import RasPrj
from .RasUtils import RasUtils
from .geom.GeomMesh import GeomMesh
from .geom.GeomReferenceFeatures import GeomReferenceFeatures
from .geom.GeomStorage import GeomStorage
from .hdf.HdfBase import HdfBase
from .hdf.HdfBndry import HdfBndry
from .hdf.HdfMesh import HdfMesh
from .hdf.HdfUtils import HdfUtils


logger = get_logger(__name__)

BoundaryInput = Union[
    str,
    Path,
    BaseGeometry,
    gpd.GeoSeries,
    gpd.GeoDataFrame,
]

FEATURE_ACTION_COLUMNS = [
    "feature_type",
    "feature_id",
    "name",
    "action",
    "reason",
    "source_measure",
    "retained_measure",
    "retained_fraction",
    "geometry",
]

BOUNDARY_FACE_COLUMNS = [
    "mesh_name",
    "face_id",
    "cell_0",
    "cell_1",
    "inside_cell",
    "outside_cell",
    "normal_x",
    "normal_y",
    "face_length",
    "orientation_multiplier",
    "boundary_station",
    "geometry",
]

_UNSUPPORTED_STRUCTURE_COLUMNS = (
    "num_cross_sections",
    "num_inline_structures",
    "num_bridges",
    "num_culverts",
    "num_weirs",
    "num_gates",
    "num_lateral_structures",
    "num_sa_2d_connections",
)


@dataclass(frozen=True)
class Breakout2DSpec:
    """Inputs for a contained pure-2D breakout preparation."""

    source_plan: Union[str, int]
    source_2d_area: str
    child_boundary: BoundaryInput
    breakout_id: str
    child_boundary_crs: Optional[Any] = None
    containment_tolerance: float = 0.0
    boundary_match_tolerance: Optional[float] = None
    allow_multipart: bool = False
    allow_holes: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_plan",
            RasUtils.normalize_ras_number(self.source_plan),
        )
        if not str(self.source_2d_area).strip():
            raise ValueError("source_2d_area must not be empty")
        if not str(self.breakout_id).strip():
            raise ValueError("breakout_id must not be empty")
        for name in ("containment_tolerance", "boundary_match_tolerance"):
            value = getattr(self, name)
            if value is None:
                continue
            numeric = float(value)
            if not math.isfinite(numeric) or numeric < 0:
                raise ValueError(f"{name} must be finite and non-negative")


@dataclass
class Breakout2DPreflight:
    """Read-only source inventory and spatial decisions for one child domain."""

    spec: Breakout2DSpec
    source_plan_path: Path
    source_plan_hdf: Optional[Path]
    source_geometry_number: str
    source_geometry_path: Path
    source_geometry_hdf: Path
    source_unsteady_number: str
    source_unsteady_path: Path
    base_cell_size: float
    parent_boundary: gpd.GeoDataFrame
    child_boundary: gpd.GeoDataFrame
    boundary_segments: gpd.GeoDataFrame
    feature_actions: gpd.GeoDataFrame
    existing_boundaries: pd.DataFrame
    checks: pd.DataFrame
    source_features: dict[str, gpd.GeoDataFrame]

    @property
    def is_ready(self) -> bool:
        """Return whether every blocking preflight check passed."""
        if self.checks.empty:
            return False
        failed = self.checks[
            self.checks["blocking"].astype(bool)
            & ~self.checks["passed"].astype(bool)
        ]
        return failed.empty

    @property
    def blocking_issues(self) -> list[str]:
        """Return human-readable failed blocking checks."""
        if self.checks.empty:
            return ["No checks were produced"]
        failed = self.checks[
            self.checks["blocking"].astype(bool)
            & ~self.checks["passed"].astype(bool)
        ]
        return failed["message"].astype(str).tolist()

    @log_call
    def to_manifest(self) -> dict[str, Any]:
        """Return compact JSON-serializable review evidence."""
        actions = (
            self.feature_actions.groupby(["feature_type", "action"])
            .size()
            .reset_index(name="count")
            .to_dict(orient="records")
        )
        child = self.child_boundary.geometry.iloc[0]
        return {
            "schema": "ras-commander/breakout-2d-preflight/1.0",
            "breakout_id": self.spec.breakout_id,
            "ready": self.is_ready,
            "source": {
                "plan": self.spec.source_plan,
                "plan_file": str(self.source_plan_path),
                "geometry": self.source_geometry_number,
                "geometry_file": str(self.source_geometry_path),
                "unsteady": self.source_unsteady_number,
                "unsteady_file": str(self.source_unsteady_path),
                "flow_area": self.spec.source_2d_area,
                "base_cell_size": self.base_cell_size,
            },
            "child": {
                "crs": str(self.child_boundary.crs),
                "area": float(child.area),
                "bounds": [float(value) for value in child.bounds],
                "geometry_sha256": _geometry_hash(child),
            },
            "checks": self.checks.to_dict(orient="records"),
            "feature_action_summary": actions,
            "existing_boundary_count": int(len(self.existing_boundaries)),
        }


@dataclass(frozen=True)
class Breakout2DCloneResult:
    """Plan-component clones and verified associations."""

    source_plan: str
    source_geometry: str
    source_unsteady: str
    plan_number: str
    geometry_number: str
    unsteady_number: str
    plan_path: Path
    geometry_path: Path
    geometry_hdf: Path
    unsteady_path: Path
    source_unsteady_sha256: str
    cloned_unsteady_sha256: str

    @property
    def boundaries_unchanged(self) -> bool:
        """Return whether the complete unsteady control file is byte-identical."""
        return self.source_unsteady_sha256 == self.cloned_unsteady_sha256


@dataclass
class Breakout2DPreparationResult:
    """Artifacts and checks from trimming and remeshing a cloned geometry."""

    clone: Breakout2DCloneResult
    feature_actions: gpd.GeoDataFrame
    refresh_result: Any
    mesh_result: Any
    containment_result: Any
    property_tables_computed: bool
    retained_breakline_count: int
    retained_reference_line_count: int
    retained_refinement_region_count: int
    unsteady_sha256_after: str

    @property
    def boundaries_unchanged(self) -> bool:
        """Return whether preparation left the cloned unsteady file untouched."""
        return self.unsteady_sha256_after == self.clone.cloned_unsteady_sha256


@dataclass
class Breakout2DFluxReview:
    """Read-only parent-face flux evidence at the proposed child perimeter."""

    faces: gpd.GeoDataFrame
    zones: gpd.GeoDataFrame
    face_flow_outward: pd.DataFrame
    source: str
    units: str


class RasBreakout2D:
    """Static entry points for contained, pure-2D breakout preparation."""

    @staticmethod
    @log_call
    def normalize_child_boundary(
        child_boundary: BoundaryInput,
        parent_crs: Any,
        *,
        child_boundary_crs: Optional[Any] = None,
        breakout_id: str = "breakout",
        allow_multipart: bool = False,
        allow_holes: bool = False,
    ) -> gpd.GeoDataFrame:
        """Normalize one child polygon into the parent geometry CRS."""
        frame = _boundary_frame(child_boundary, child_boundary_crs)
        if frame.crs is None:
            raise ValueError(
                "Child boundary CRS is required; set it on the spatial input "
                "or pass child_boundary_crs"
            )
        if parent_crs is None:
            raise ValueError("Parent 2D flow-area CRS is unavailable")
        frame = frame.to_crs(parent_crs)
        geometry = _union_geometry(frame)
        if geometry.is_empty or geometry.geom_type not in {
            "Polygon",
            "MultiPolygon",
        }:
            raise ValueError("child_boundary must resolve to polygon geometry")
        repaired = not geometry.is_valid
        geometry = _polygonal_geometry(make_valid(geometry))
        geometry = _orient_polygonal(geometry)
        if isinstance(geometry, MultiPolygon) and not allow_multipart:
            raise ValueError("Multipart child boundaries are not qualified")
        hole_count = _hole_count(geometry)
        if hole_count and not allow_holes:
            raise ValueError("Child boundaries with interior holes are not qualified")
        return gpd.GeoDataFrame(
            {
                "breakout_id": [str(breakout_id)],
                "topology_repaired": [bool(repaired)],
                "hole_count": [int(hole_count)],
                "geometry": [geometry],
            },
            geometry="geometry",
            crs=parent_crs,
        )

    @staticmethod
    @log_call
    def classify_boundary_segments(
        parent_boundary: Union[BaseGeometry, gpd.GeoSeries, gpd.GeoDataFrame],
        child_boundary: Union[BaseGeometry, gpd.GeoSeries, gpd.GeoDataFrame],
        *,
        tolerance: float = 0.0,
        crs: Optional[Any] = None,
    ) -> gpd.GeoDataFrame:
        """Partition the child perimeter into inherited and artificial cuts."""
        tolerance = float(tolerance)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("tolerance must be finite and non-negative")
        parent = _single_geometry(parent_boundary)
        child = _single_geometry(child_boundary)
        if not isinstance(child, Polygon):
            raise ValueError("Boundary partition currently requires one child Polygon")
        boundary_zone = (
            parent.boundary
            if tolerance == 0
            else parent.boundary.buffer(
                tolerance,
                cap_style="flat",
                join_style="mitre",
            )
        )
        records: list[dict[str, Any]] = []
        for segment_type, geometry in (
            ("inherited", child.boundary.intersection(boundary_zone)),
            ("artificial_cut", child.boundary.difference(boundary_zone)),
        ):
            for part in _line_parts(geometry):
                if part.length <= 0:
                    continue
                midpoint = part.interpolate(0.5, normalized=True)
                records.append(
                    {
                        "segment_type": segment_type,
                        "station": float(child.exterior.project(midpoint)),
                        "length": float(part.length),
                        "geometry": part,
                    }
                )
        records.sort(key=lambda item: (item["station"], item["segment_type"]))
        counters = {"inherited": 0, "artificial_cut": 0}
        for record in records:
            counters[record["segment_type"]] += 1
            prefix = "INHERITED" if record["segment_type"] == "inherited" else "CUT"
            record["segment_id"] = f"{prefix}-{counters[record['segment_type']]:03d}"
        return gpd.GeoDataFrame(records, geometry="geometry", crs=crs)

    @staticmethod
    @log_call
    def preflight(
        spec: Breakout2DSpec,
        *,
        ras_object: RasPrj,
    ) -> Breakout2DPreflight:
        """Inventory and spatially qualify a breakout without modifying files."""
        if not isinstance(spec, Breakout2DSpec):
            raise TypeError("spec must be a Breakout2DSpec")
        ras_object.check_initialized()
        plan = _select_plan_row(ras_object, str(spec.source_plan))
        geometry_number = str(plan["geometry_number"]).zfill(2)
        unsteady_number = str(plan["unsteady_number"]).zfill(2)
        geometry = _select_geometry_row(ras_object, geometry_number)
        source_geometry_path = Path(geometry["full_path"])
        source_geometry_hdf = Path(geometry["hdf_path"])
        if not source_geometry_hdf.is_file():
            raise FileNotFoundError(
                f"Geometry HDF is required: {source_geometry_hdf}"
            )
        source_unsteady_path = Path(
            RasPlan.get_unsteady_path(unsteady_number, ras_object=ras_object)
        )
        source_plan_path = Path(plan["full_path"])
        source_plan_hdf = _optional_path(plan.get("HDF_Results_Path"))

        mesh_areas = HdfMesh.get_mesh_areas(source_geometry_hdf)
        selected = mesh_areas[
            mesh_areas["mesh_name"].astype(str) == str(spec.source_2d_area)
        ]
        if len(selected) != 1:
            available = sorted(mesh_areas.get("mesh_name", pd.Series(dtype=str)).astype(str))
            raise ValueError(
                f"2D flow area {spec.source_2d_area!r} is not unique; "
                f"available={available}"
            )
        parent = _polygonal_geometry(make_valid(selected.geometry.iloc[0]))
        parent_boundary = gpd.GeoDataFrame(
            {"mesh_name": [spec.source_2d_area], "geometry": [parent]},
            geometry="geometry",
            crs=selected.crs,
        )
        child_boundary = RasBreakout2D.normalize_child_boundary(
            spec.child_boundary,
            parent_boundary.crs,
            child_boundary_crs=spec.child_boundary_crs,
            breakout_id=spec.breakout_id,
            allow_multipart=spec.allow_multipart,
            allow_holes=spec.allow_holes,
        )
        child = child_boundary.geometry.iloc[0]
        base_cell_size = _base_cell_size(
            source_geometry_path,
            spec.source_2d_area,
        )
        # Leave a tiny numeric guard beyond the required one-cell offset.
        # HEC-RAS serializes geometry through text and HDF representations;
        # endpoint roundoff at the exact buffer boundary can otherwise make a
        # correctly clipped line fail the strict HDF ``covers`` predicate.
        mesh_trim_distance = base_cell_size + max(1e-6, base_cell_size * 1e-8)
        mesh_trim_boundary = child.buffer(-mesh_trim_distance)
        if mesh_trim_boundary.is_empty:
            raise ValueError(
                f"One-cell inward trim ({mesh_trim_distance:g}) empties the child domain"
            )
        match_tolerance = (
            spec.containment_tolerance
            if spec.boundary_match_tolerance is None
            else spec.boundary_match_tolerance
        )
        boundary_segments = RasBreakout2D.classify_boundary_segments(
            parent,
            child,
            tolerance=float(match_tolerance),
            crs=parent_boundary.crs,
        )
        source_features = _read_spatial_features(
            source_geometry_hdf,
            spec.source_2d_area,
        )
        existing_boundaries = _selected_boundaries(
            ras_object,
            unsteady_number,
        )
        feature_actions = _build_feature_actions(
            parent_boundary,
            child,
            source_features,
            existing_boundaries,
            mesh_trim_boundary,
        )
        checks = _build_checks(
            spec,
            plan,
            geometry,
            parent,
            child,
            boundary_segments,
            feature_actions,
            mesh_area_count=len(mesh_areas),
        )
        result = Breakout2DPreflight(
            spec=spec,
            source_plan_path=source_plan_path,
            source_plan_hdf=source_plan_hdf,
            source_geometry_number=geometry_number,
            source_geometry_path=source_geometry_path,
            source_geometry_hdf=source_geometry_hdf,
            source_unsteady_number=unsteady_number,
            source_unsteady_path=source_unsteady_path,
            base_cell_size=base_cell_size,
            parent_boundary=parent_boundary,
            child_boundary=child_boundary,
            boundary_segments=boundary_segments,
            feature_actions=feature_actions,
            existing_boundaries=existing_boundaries,
            checks=checks,
            source_features=source_features,
        )
        logger.info(
            "2D breakout preflight %s: ready=%s, features=%d",
            spec.breakout_id,
            result.is_ready,
            len(feature_actions),
        )
        return result

    @staticmethod
    @log_call
    def clone_plan_components(
        preflight: Breakout2DPreflight,
        *,
        ras_object: RasPrj,
        plan_title: Optional[str] = None,
        plan_short_id: Optional[str] = None,
        geometry_title: Optional[str] = None,
        set_current_plan: bool = True,
    ) -> Breakout2DCloneResult:
        """Clone and associate the plan, geometry, and unsteady control file.

        The caller must initialize ``ras_object`` on an isolated task-local
        project.  The complete unsteady file is copied without a title rewrite
        and verified byte-for-byte before this method returns.
        """
        if not preflight.is_ready:
            raise ValueError(
                "Breakout preflight failed: " + "; ".join(preflight.blocking_issues)
            )
        ras_object.check_initialized()
        _verify_working_source_snapshot(preflight, ras_object)
        source_unsteady_hash = _sha256_file(preflight.source_unsteady_path)

        geometry_number = RasGeo.clone_geom(
            preflight.source_geometry_number,
            new_title=geometry_title,
            ras_object=ras_object,
        )
        RasMap.clone_geometry_layer(
            preflight.source_geometry_number,
            geometry_number,
            name=geometry_title,
            ras_object=ras_object,
        )
        unsteady_number = RasPlan.clone_unsteady(
            preflight.source_unsteady_number,
            new_title=None,
            ras_object=ras_object,
        )
        unsteady_path = Path(
            RasPlan.get_unsteady_path(unsteady_number, ras_object=ras_object)
        )
        cloned_unsteady_hash = _sha256_file(unsteady_path)
        if cloned_unsteady_hash != source_unsteady_hash:
            raise RuntimeError(
                "Cloned unsteady file is not byte-identical to the source; "
                "boundary preservation cannot be proved"
            )

        plan_number = RasPlan.clone_plan(
            preflight.spec.source_plan,
            new_plan_shortid=plan_short_id,
            new_title=plan_title,
            geometry=geometry_number,
            unsteady_flow=unsteady_number,
            ras_object=ras_object,
        )
        plan = _select_plan_row(ras_object, plan_number)
        observed_geometry = str(plan["geometry_number"]).zfill(2)
        observed_unsteady = str(plan["unsteady_number"]).zfill(2)
        if observed_geometry != str(geometry_number).zfill(2):
            raise RuntimeError("Cloned plan geometry association failed readback")
        if observed_unsteady != str(unsteady_number).zfill(2):
            raise RuntimeError("Cloned plan unsteady association failed readback")
        if set_current_plan:
            ras_object.set_current_plan(plan_number)

        geometry_path = Path(
            RasPlan.get_geom_path(geometry_number, ras_object=ras_object)
        )
        return Breakout2DCloneResult(
            source_plan=str(preflight.spec.source_plan),
            source_geometry=preflight.source_geometry_number,
            source_unsteady=preflight.source_unsteady_number,
            plan_number=str(plan_number).zfill(2),
            geometry_number=str(geometry_number).zfill(2),
            unsteady_number=str(unsteady_number).zfill(2),
            plan_path=Path(plan["full_path"]),
            geometry_path=geometry_path,
            geometry_hdf=geometry_path.with_suffix(geometry_path.suffix + ".hdf"),
            unsteady_path=unsteady_path,
            source_unsteady_sha256=source_unsteady_hash,
            cloned_unsteady_sha256=cloned_unsteady_hash,
        )

    @staticmethod
    @log_call
    def prepare_cloned_geometry(
        preflight: Breakout2DPreflight,
        clone: Breakout2DCloneResult,
        *,
        ras_object: RasPrj,
        refresh_hdf: bool = True,
        remesh: bool = True,
        compute_property_tables: bool = False,
        timeout: int = 600,
        max_mesh_iterations: int = 8,
    ) -> Breakout2DPreparationResult:
        """Trim mesh-owned features and remesh only the cloned geometry.

        Geometry BC lines and the cloned unsteady file are intentionally not
        edited.  ``refresh_hdf`` performs the exact text-to-HDF import through
        the owned RAS Mapper workflow.  ``remesh`` then regenerates computation
        cells through :class:`GeomMesh`; neither option launches a hydraulic
        simulation.
        """
        if not preflight.is_ready:
            raise ValueError("preflight must pass before geometry preparation")
        if not clone.boundaries_unchanged:
            raise ValueError("clone does not prove byte-identical unsteady inputs")
        if _sha256_file(clone.unsteady_path) != clone.cloned_unsteady_sha256:
            raise RuntimeError("Cloned unsteady file changed before preparation")

        unsupported_points = preflight.feature_actions[
            (preflight.feature_actions["feature_type"] == "reference_point")
            & (preflight.feature_actions["action"] != "keep")
        ]
        if not unsupported_points.empty:
            raise NotImplementedError(
                "Reference-point trimming is not yet implemented; remove or "
                "relocate those features in a separate reviewed change"
            )

        child = preflight.child_boundary.geometry.iloc[0]
        breakline_specs = _retained_breakline_specs(preflight)
        reference_line_specs = _retained_reference_line_specs(preflight)
        refinement_specs = _retained_refinement_specs(preflight)

        GeomStorage.set_2d_flow_area_perimeter(
            clone.geometry_path,
            preflight.spec.source_2d_area,
            geometry=child,
        )
        source_breakline_names = _source_names(
            preflight.source_features.get("breakline"),
            "Name",
        )
        GeomStorage.replace_breaklines(
            clone.geometry_path,
            preflight.spec.source_2d_area,
            breakline_specs,
            expected_existing_names=source_breakline_names,
        )
        source_reference_lines = GeomReferenceFeatures.get_reference_lines(
            clone.geometry_path
        )
        source_reference_names = [
            row["name"]
            for row in source_reference_lines
            if row.get("storage_area") == preflight.spec.source_2d_area
        ]
        GeomReferenceFeatures.replace_reference_lines(
            clone.geometry_path,
            preflight.spec.source_2d_area,
            reference_line_specs,
            expected_existing_names=source_reference_names,
        )

        refresh_result = None
        if refresh_hdf:
            from .gui.workflows import MeshRegenerationWorkflow

            refresh_result = MeshRegenerationWorkflow.refresh_geometry_hdf_from_text(
                geom_number=clone.geometry_number,
                flow_area_name=preflight.spec.source_2d_area,
                ras_object=ras_object,
                timeout=timeout,
            )
            if not refresh_result.success:
                raise RuntimeError(
                    f"Exact geometry HDF refresh failed: {refresh_result.error}"
                )

        source_refinement_names = [
            item["name"]
            for item in GeomMesh.get_refinement_regions(
                clone.geometry_number,
                ras_object=ras_object,
            )
        ]
        GeomMesh.replace_refinement_regions(
            clone.geometry_number,
            refinement_specs,
            expected_existing_names=source_refinement_names,
            ras_object=ras_object,
        )

        containment_result = None
        mesh_result = None
        if remesh:
            mesh_result = GeomMesh.generate(
                clone.geometry_number,
                mesh_name=preflight.spec.source_2d_area,
                ras_object=ras_object,
                max_iterations=max_mesh_iterations,
            )
            if not mesh_result.ok:
                raise RuntimeError(
                    f"2D mesh regeneration failed: {mesh_result.error_message}"
                )
            containment_result = GeomMesh.audit_domain_containment(
                clone.geometry_number,
                mesh_name=preflight.spec.source_2d_area,
                ras_object=ras_object,
            )
            if not containment_result.ok:
                raise ValueError(
                    "Trimmed mesh-owned features failed containment: "
                    f"{containment_result.violations}"
                )

        property_tables = False
        if compute_property_tables:
            property_tables = GeomMesh.compute_property_tables(
                clone.geometry_number,
                mesh_name=preflight.spec.source_2d_area,
                ras_object=ras_object,
            )
            if not property_tables:
                raise RuntimeError("2D property-table computation returned False")

        final_unsteady_hash = _sha256_file(clone.unsteady_path)
        if final_unsteady_hash != clone.cloned_unsteady_sha256:
            raise RuntimeError("Geometry preparation modified the cloned unsteady file")
        return Breakout2DPreparationResult(
            clone=clone,
            feature_actions=preflight.feature_actions.copy(),
            refresh_result=refresh_result,
            mesh_result=mesh_result,
            containment_result=containment_result,
            property_tables_computed=bool(property_tables),
            retained_breakline_count=len(breakline_specs),
            retained_reference_line_count=len(reference_line_specs),
            retained_refinement_region_count=len(refinement_specs),
            unsteady_sha256_after=final_unsteady_hash,
        )

    @staticmethod
    @log_call
    def select_parent_boundary_faces(
        geometry_hdf: Union[str, Path],
        mesh_name: str,
        child_boundary: Union[BaseGeometry, gpd.GeoSeries, gpd.GeoDataFrame],
    ) -> gpd.GeoDataFrame:
        """Select parent faces separating retained and discarded cell centers."""
        geometry_path = Path(geometry_hdf)
        if not geometry_path.is_file():
            raise FileNotFoundError(f"Geometry HDF not found: {geometry_path}")
        child = _single_geometry(child_boundary)
        if not isinstance(child, Polygon):
            raise ValueError("Boundary-face review requires one child Polygon")
        child = orient(child, sign=1.0)

        faces = HdfMesh.get_mesh_cell_faces(geometry_path)
        cells = HdfMesh.get_mesh_cell_points(geometry_path)
        faces = faces[faces["mesh_name"].astype(str) == str(mesh_name)].copy()
        cells = cells[cells["mesh_name"].astype(str) == str(mesh_name)].copy()
        if faces.empty or cells.empty:
            raise ValueError(f"Mesh faces/cells are unavailable for {mesh_name!r}")
        faces = faces.sort_values("face_id").set_index("face_id", drop=False)
        cells = cells.sort_values("cell_id").set_index("cell_id", drop=False)

        max_cell_id = int(cells.index.max())
        inside = np.zeros(max_cell_id + 1, dtype=bool)
        cell_ids = cells.index.to_numpy(dtype=int)
        x_values = cells.geometry.x.to_numpy(dtype=float)
        y_values = cells.geometry.y.to_numpy(dtype=float)
        inside[cell_ids] = contains_xy(child, x_values, y_values) | intersects_xy(
            child,
            x_values,
            y_values,
        )

        base = f"Geometry/2D Flow Areas/{mesh_name}"
        with h5py.File(geometry_path, "r") as hdf:
            face_cells = np.asarray(hdf[f"{base}/Faces Cell Indexes"][()], dtype=int)
            normals = np.asarray(
                hdf[f"{base}/Faces NormalUnitVector and Length"][()],
                dtype=float,
            )
        valid = (
            (face_cells[:, 0] >= 0)
            & (face_cells[:, 1] >= 0)
            & (face_cells[:, 0] <= max_cell_id)
            & (face_cells[:, 1] <= max_cell_id)
        )
        retained_0 = np.zeros(len(face_cells), dtype=bool)
        retained_1 = np.zeros(len(face_cells), dtype=bool)
        retained_0[valid] = inside[face_cells[valid, 0]]
        retained_1[valid] = inside[face_cells[valid, 1]]
        selected_ids = np.flatnonzero(valid & (retained_0 ^ retained_1))
        selected_ids = np.intersect1d(selected_ids, faces.index.to_numpy(dtype=int))
        if selected_ids.size == 0:
            raise ValueError("No parent faces cross the proposed child partition")

        records: list[dict[str, Any]] = []
        for face_id in selected_ids.tolist():
            cell_0, cell_1 = face_cells[face_id, :2].astype(int).tolist()
            inside_cell, outside_cell = (
                (cell_0, cell_1) if retained_0[face_id] else (cell_1, cell_0)
            )
            inside_point = cells.loc[inside_cell].geometry
            outside_point = cells.loc[outside_cell].geometry
            outward_x = float(outside_point.x - inside_point.x)
            outward_y = float(outside_point.y - inside_point.y)
            normal_x = float(normals[face_id, 0])
            normal_y = float(normals[face_id, 1])
            dot = normal_x * outward_x + normal_y * outward_y
            if not math.isfinite(dot) or math.isclose(dot, 0.0, abs_tol=1e-12):
                raise ValueError(f"Face {face_id} normal cannot be oriented")
            geometry = faces.loc[face_id].geometry
            records.append(
                {
                    "mesh_name": str(mesh_name),
                    "face_id": int(face_id),
                    "cell_0": int(cell_0),
                    "cell_1": int(cell_1),
                    "inside_cell": int(inside_cell),
                    "outside_cell": int(outside_cell),
                    "normal_x": normal_x,
                    "normal_y": normal_y,
                    "face_length": (
                        float(normals[face_id, 2])
                        if normals.shape[1] >= 3 and normals[face_id, 2] > 0
                        else float(geometry.length)
                    ),
                    "orientation_multiplier": 1.0 if dot > 0 else -1.0,
                    "boundary_station": float(
                        child.exterior.project(
                            geometry.interpolate(0.5, normalized=True)
                        )
                    ),
                    "geometry": geometry,
                }
            )
        records.sort(key=lambda item: (item["boundary_station"], item["face_id"]))
        return gpd.GeoDataFrame(
            records,
            columns=BOUNDARY_FACE_COLUMNS,
            geometry="geometry",
            crs=faces.crs,
        )

    @staticmethod
    @log_call
    def review_parent_boundary_flux(
        preflight: Breakout2DPreflight,
        *,
        minimum_peak_flow: float = 100.0,
        minimum_volume_fraction: float = 0.001,
        gap_multiplier: float = 3.0,
        prefer_native: bool = True,
    ) -> Breakout2DFluxReview:
        """Summarize parent flux locations without assigning child BC types."""
        if preflight.source_plan_hdf is None or not preflight.source_plan_hdf.is_file():
            raise FileNotFoundError("A completed parent plan HDF is required")
        if minimum_peak_flow < 0:
            raise ValueError("minimum_peak_flow must be non-negative")
        if not 0 <= minimum_volume_fraction <= 1:
            raise ValueError("minimum_volume_fraction must be between zero and one")
        if gap_multiplier <= 0:
            raise ValueError("gap_multiplier must be positive")
        faces = RasBreakout2D.select_parent_boundary_faces(
            preflight.source_geometry_hdf,
            preflight.spec.source_2d_area,
            preflight.child_boundary,
        )
        native, source, units = _read_boundary_face_flow(
            preflight.source_plan_hdf,
            preflight.source_geometry_hdf,
            preflight.spec.source_2d_area,
            faces,
            prefer_native=prefer_native,
        )
        multipliers = (
            faces.set_index("face_id")
            .loc[native.columns, "orientation_multiplier"]
            .to_numpy(dtype=float)
        )
        outward = native.multiply(multipliers, axis="columns")
        outward.attrs.update(native.attrs)
        outward.attrs["sign_convention"] = "positive leaves child; negative enters"
        reviewed_faces = _summarize_face_flux(
            faces,
            outward,
            minimum_peak_flow=float(minimum_peak_flow),
            minimum_volume_fraction=float(minimum_volume_fraction),
        )
        zones = _combine_flux_locations(
            reviewed_faces,
            outward,
            gap_multiplier=float(gap_multiplier),
        )
        return Breakout2DFluxReview(
            faces=reviewed_faces,
            zones=zones,
            face_flow_outward=outward,
            source=source,
            units=units,
        )


def _boundary_frame(value: BoundaryInput, explicit_crs: Optional[Any]) -> gpd.GeoDataFrame:
    if isinstance(value, gpd.GeoDataFrame):
        frame = value.copy()
    elif isinstance(value, gpd.GeoSeries):
        frame = gpd.GeoDataFrame(geometry=value.copy(), crs=value.crs)
    elif isinstance(value, BaseGeometry):
        frame = gpd.GeoDataFrame(geometry=[value], crs=explicit_crs)
    elif isinstance(value, (str, Path)):
        path = Path(value)
        if not path.is_file():
            raise FileNotFoundError(f"Child boundary file not found: {path}")
        frame = gpd.read_file(path)
    else:
        raise TypeError("Unsupported child boundary input")
    if frame.empty:
        raise ValueError("Child boundary contains no features")
    if explicit_crs is not None:
        if frame.crs is None:
            frame = frame.set_crs(explicit_crs)
        elif CRS.from_user_input(frame.crs) != CRS.from_user_input(explicit_crs):
            raise ValueError("child_boundary_crs conflicts with the input CRS")
    return frame


def _union_geometry(frame: gpd.GeoDataFrame) -> BaseGeometry:
    nonempty = frame.geometry[frame.geometry.notna() & ~frame.geometry.is_empty]
    if nonempty.empty:
        return GeometryCollection()
    return nonempty.union_all() if hasattr(nonempty, "union_all") else nonempty.unary_union


def _single_geometry(
    value: Union[BaseGeometry, gpd.GeoSeries, gpd.GeoDataFrame],
) -> BaseGeometry:
    if isinstance(value, BaseGeometry):
        return value
    if isinstance(value, gpd.GeoSeries):
        return _union_geometry(gpd.GeoDataFrame(geometry=value, crs=value.crs))
    if isinstance(value, gpd.GeoDataFrame):
        return _union_geometry(value)
    raise TypeError("Expected a Shapely geometry, GeoSeries, or GeoDataFrame")


def _polygonal_geometry(geometry: BaseGeometry) -> Union[Polygon, MultiPolygon]:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        polygons: list[Polygon] = []
        for part in geometry.geoms:
            if isinstance(part, Polygon):
                polygons.append(part)
            elif isinstance(part, MultiPolygon):
                polygons.extend(part.geoms)
        if len(polygons) == 1:
            return polygons[0]
        if polygons:
            return MultiPolygon(polygons)
    raise ValueError(f"Expected polygonal geometry; got {geometry.geom_type}")


def _orient_polygonal(geometry: Union[Polygon, MultiPolygon]):
    if isinstance(geometry, Polygon):
        return orient(geometry, sign=1.0)
    return MultiPolygon([orient(part, sign=1.0) for part in geometry.geoms])


def _hole_count(geometry: Union[Polygon, MultiPolygon]) -> int:
    if isinstance(geometry, Polygon):
        return len(geometry.interiors)
    return sum(len(part.interiors) for part in geometry.geoms)


def _line_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, (MultiLineString, GeometryCollection)):
        parts: list[LineString] = []
        for part in geometry.geoms:
            parts.extend(_line_parts(part))
        return parts
    return []


def _optional_path(value: Any) -> Optional[Path]:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return Path(text) if text else None


def _select_plan_row(ras_object: RasPrj, plan_number: str) -> pd.Series:
    ras_object.plan_df = ras_object.get_plan_entries()
    rows = ras_object.plan_df[
        ras_object.plan_df["plan_number"].astype(str).str.zfill(2)
        == str(plan_number).zfill(2)
    ]
    if len(rows) != 1:
        raise ValueError(f"Plan {plan_number} is not uniquely registered")
    return rows.iloc[0]


def _select_geometry_row(ras_object: RasPrj, geometry_number: str) -> pd.Series:
    ras_object.geom_df = ras_object.get_geom_entries()
    rows = ras_object.geom_df[
        ras_object.geom_df["geom_number"].astype(str).str.zfill(2)
        == str(geometry_number).zfill(2)
    ]
    if len(rows) != 1:
        raise ValueError(f"Geometry {geometry_number} is not uniquely registered")
    return rows.iloc[0]


def _verify_working_source_snapshot(
    preflight: Breakout2DPreflight,
    ras_object: RasPrj,
) -> None:
    """Require an isolated working copy of the exact qualified source files."""
    working_root = Path(ras_object.project_folder)
    source_root = preflight.source_plan_path.parent
    if working_root.resolve() == source_root.resolve():
        raise ValueError(
            "clone_plan_components requires an isolated working project copy"
        )
    project_name = str(ras_object.project_name)
    pairs = [
        (
            working_root / f"{project_name}.p{preflight.spec.source_plan}",
            preflight.source_plan_path,
            "plan",
        ),
        (
            working_root / f"{project_name}.g{preflight.source_geometry_number}",
            preflight.source_geometry_path,
            "geometry",
        ),
        (
            working_root
            / f"{project_name}.g{preflight.source_geometry_number}.hdf",
            preflight.source_geometry_hdf,
            "geometry HDF",
        ),
        (
            working_root / f"{project_name}.u{preflight.source_unsteady_number}",
            preflight.source_unsteady_path,
            "unsteady",
        ),
    ]
    for working_path, qualified_path, label in pairs:
        if not working_path.is_file():
            raise FileNotFoundError(
                f"Working {label} source is missing: {working_path}"
            )
        if _sha256_file(working_path) != _sha256_file(qualified_path):
            raise ValueError(
                f"Working {label} source does not match the qualified source: "
                f"{working_path.name}"
            )


def _selected_boundaries(ras_object: RasPrj, unsteady_number: str) -> pd.DataFrame:
    boundaries = getattr(ras_object, "boundaries_df", pd.DataFrame())
    if boundaries is None or boundaries.empty:
        return pd.DataFrame()
    if "unsteady_number" not in boundaries.columns:
        return boundaries.copy()
    selected = boundaries[
        boundaries["unsteady_number"].astype(str).str.zfill(2)
        == str(unsteady_number).zfill(2)
    ].copy()
    sort_columns = [
        column
        for column in ("boundary_condition_number", "bc_line_name")
        if column in selected.columns
    ]
    return selected.sort_values(sort_columns).reset_index(drop=True)


def _read_spatial_features(
    geometry_hdf: Path,
    mesh_name: str,
) -> dict[str, gpd.GeoDataFrame]:
    return {
        "bc_line": HdfBndry.get_bc_lines(geometry_hdf),
        "breakline": HdfBndry.get_breaklines(geometry_hdf),
        "refinement_region": HdfBndry.get_refinement_regions(geometry_hdf),
        "reference_line": HdfBndry.get_reference_lines(
            geometry_hdf,
            mesh_name=mesh_name,
        ),
        "reference_point": HdfBndry.get_reference_points(
            geometry_hdf,
            mesh_name=mesh_name,
        ),
    }


def _build_feature_actions(
    parent_boundary: gpd.GeoDataFrame,
    child: BaseGeometry,
    source_features: dict[str, gpd.GeoDataFrame],
    existing_boundaries: pd.DataFrame,
    mesh_trim_boundary: BaseGeometry,
) -> gpd.GeoDataFrame:
    records = [
        _action_record(
            "mesh_area",
            "0",
            str(parent_boundary.iloc[0]["mesh_name"]),
            "replace",
            "replace_parent_perimeter_and_regenerate_mesh",
            parent_boundary.geometry.iloc[0],
            child,
        )
    ]
    id_columns = {
        "bc_line": "bc_line_id",
        "breakline": "bl_id",
        "refinement_region": "rr_id",
        "reference_line": "refline_id",
        "reference_point": "refpoint_id",
    }
    for feature_type, frame in source_features.items():
        if frame is None or frame.empty:
            continue
        if frame.crs is not None and parent_boundary.crs is not None:
            frame = frame.to_crs(parent_boundary.crs)
        for index, row in frame.iterrows():
            geometry = row.geometry
            feature_id = str(row.get(id_columns[feature_type], index))
            name = str(row.get("Name", f"{feature_type}_{feature_id}"))
            if feature_type == "bc_line":
                retained, action, reason = (
                    geometry,
                    "preserve",
                    "boundary_condition_scope_deferred",
                )
            elif feature_type in {"breakline", "refinement_region"}:
                retained, action, reason = _clip_action(
                    geometry,
                    mesh_trim_boundary,
                )
                if action == "clip":
                    reason = "trimmed_to_one_cell_inward_buffer"
            else:
                retained, action, reason = _clip_action(geometry, child)
            records.append(
                _action_record(
                    feature_type,
                    feature_id,
                    name,
                    action,
                    reason,
                    geometry,
                    retained,
                )
            )
    for index, row in existing_boundaries.iterrows():
        name = str(row.get("bc_line_name", f"boundary_{index + 1}"))
        records.append(
            _action_record(
                "unsteady_boundary",
                str(row.get("boundary_condition_number", index + 1)),
                name,
                "preserve",
                "cloned_byte_identical_boundary_scope_deferred",
                None,
                None,
            )
        )
    records.sort(
        key=lambda item: (
            item["feature_type"],
            item["feature_id"],
            item["name"],
        )
    )
    return gpd.GeoDataFrame(
        records,
        columns=FEATURE_ACTION_COLUMNS,
        geometry="geometry",
        crs=parent_boundary.crs,
    )


def _clip_action(
    geometry: Optional[BaseGeometry],
    child: BaseGeometry,
) -> tuple[Optional[BaseGeometry], str, str]:
    if geometry is None or geometry.is_empty:
        return None, "drop", "empty_source_geometry"
    if child.covers(geometry):
        return geometry, "keep", "fully_within_child_boundary"
    retained = geometry.intersection(child)
    if retained.is_empty or _geometry_measure(retained) <= 0:
        return None, "drop", "outside_child_boundary"
    return retained, "clip", "partially_intersects_child_boundary"


def _geometry_measure(geometry: Optional[BaseGeometry]) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        return float(geometry.area)
    if geometry.geom_type in {"Point", "MultiPoint"}:
        return 1.0
    return float(geometry.length)


def _action_record(
    feature_type: str,
    feature_id: str,
    name: str,
    action: str,
    reason: str,
    source_geometry: Optional[BaseGeometry],
    retained_geometry: Optional[BaseGeometry],
) -> dict[str, Any]:
    source_measure = _geometry_measure(source_geometry)
    retained_measure = _geometry_measure(retained_geometry)
    return {
        "feature_type": feature_type,
        "feature_id": feature_id,
        "name": name,
        "action": action,
        "reason": reason,
        "source_measure": source_measure,
        "retained_measure": retained_measure,
        "retained_fraction": (
            retained_measure / source_measure if source_measure > 0 else 0.0
        ),
        "geometry": retained_geometry,
    }


def _build_checks(
    spec: Breakout2DSpec,
    plan: pd.Series,
    geometry: pd.Series,
    parent: BaseGeometry,
    child: BaseGeometry,
    boundary_segments: gpd.GeoDataFrame,
    feature_actions: gpd.GeoDataFrame,
    *,
    mesh_area_count: int,
) -> pd.DataFrame:
    unsupported = {
        column: _int_or_zero(geometry.get(column))
        for column in _UNSUPPORTED_STRUCTURE_COLUMNS
    }
    pure_2d = bool(
        plan.get("geometry_type") == "2D"
        and plan.get("plan_type") == "unsteady_2d"
        and _bool_value(plan.get("plan_classification_valid"))
    )
    buffered_parent = parent.buffer(float(spec.containment_tolerance))
    partition_length = float(boundary_segments.get("length", pd.Series(dtype=float)).sum())
    perimeter_length = float(child.boundary.length)
    reference_points_need_trim = feature_actions[
        (feature_actions["feature_type"] == "reference_point")
        & (feature_actions["action"] != "keep")
    ]
    rows = [
        _check(
            "pure_2d_plan",
            pure_2d,
            "Source plan must be classified as valid unsteady pure 2D",
        ),
        _check(
            "single_2d_flow_area",
            int(mesh_area_count) == 1,
            "Initial breakout preparation requires exactly one 2D flow area",
            details={"mesh_area_count": int(mesh_area_count)},
        ),
        _check(
            "unsupported_structures_absent",
            sum(unsupported.values()) == 0,
            "Initial 2D breakout preparation does not support 1D or structure elements",
            details=unsupported,
        ),
        _check(
            "child_within_parent",
            bool(buffered_parent.covers(child)),
            "Child boundary must be contained by the parent 2D area",
            details={
                "outside_parent_area": float(child.difference(parent).area),
                "tolerance": float(spec.containment_tolerance),
            },
        ),
        _check(
            "boundary_partition_closes",
            abs(partition_length - perimeter_length)
            <= max(perimeter_length, 1.0) * 1e-9,
            "Inherited and artificial segments must close the child perimeter",
            details={
                "partition_length": partition_length,
                "perimeter_length": perimeter_length,
            },
        ),
        _check(
            "reference_points_do_not_require_trim",
            reference_points_need_trim.empty,
            "Reference points requiring trim are outside the initial implementation",
        ),
    ]
    return pd.DataFrame(rows)


def _check(
    check_id: str,
    passed: bool,
    message: str,
    *,
    blocking: bool = True,
    details: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "blocking": bool(blocking),
        "message": message,
        "details": details or {},
    }


def _int_or_zero(value: Any) -> int:
    try:
        return 0 if pd.isna(value) else int(value)
    except (TypeError, ValueError):
        return 0


def _bool_value(value: Any) -> bool:
    try:
        return False if pd.isna(value) else bool(value)
    except (TypeError, ValueError):
        return False


def _source_names(frame: Optional[gpd.GeoDataFrame], column: str) -> list[str]:
    if frame is None or frame.empty or column not in frame.columns:
        return []
    return frame[column].astype(str).tolist()


def _base_cell_size(geometry_path: Path, mesh_name: str) -> float:
    settings = GeomStorage.get_2d_flow_area_settings(geometry_path)
    selected = settings[settings["name"].astype(str) == str(mesh_name)]
    if len(selected) != 1:
        raise ValueError(f"Base cell size is unavailable for {mesh_name!r}")
    raw = selected.iloc[0]["point_generation_data"]
    parts = str(raw).split(",")
    if len(parts) < 3:
        raise ValueError(f"Malformed point-generation data for {mesh_name!r}: {raw!r}")
    try:
        spacing = float(parts[2])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Base cell size is unavailable for {mesh_name!r}: {raw!r}"
        ) from exc
    if not math.isfinite(spacing) or spacing <= 0:
        raise ValueError(f"Base cell size must be positive for {mesh_name!r}")
    return spacing


def _action_lookup(preflight: Breakout2DPreflight, feature_type: str) -> pd.DataFrame:
    return preflight.feature_actions[
        preflight.feature_actions["feature_type"] == feature_type
    ].set_index("feature_id", drop=False)


def _unique_part_name(base: str, part_index: int, part_count: int) -> str:
    if part_count == 1:
        return base[:32]
    suffix = f"_BRK{part_index:02d}"
    return f"{base[: 32 - len(suffix)]}{suffix}"


def _deduplicate_ras_name(candidate: str, used: set[str]) -> str:
    """Return a deterministic unique HEC-RAS name of at most 32 characters."""
    normalized = candidate[:32]
    if normalized.casefold() not in used:
        used.add(normalized.casefold())
        return normalized
    sequence = 2
    while True:
        suffix = f"_{sequence:02d}"
        revised = f"{normalized[: 32 - len(suffix)]}{suffix}"
        if revised.casefold() not in used:
            used.add(revised.casefold())
            return revised
        sequence += 1


def _retained_breakline_specs(preflight: Breakout2DPreflight) -> list[dict[str, Any]]:
    frame = preflight.source_features.get("breakline")
    if frame is None or frame.empty:
        return []
    actions = _action_lookup(preflight, "breakline")
    specs: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, row in frame.iterrows():
        feature_id = str(row.get("bl_id", index))
        if feature_id not in actions.index:
            continue
        geometry = actions.loc[feature_id, "geometry"]
        if geometry is None or geometry.is_empty:
            continue
        parts = sorted(_line_parts(geometry), key=lambda part: (-part.length, part.wkt))
        for part_index, part in enumerate(parts, start=1):
            name = _deduplicate_ras_name(
                _unique_part_name(
                    str(row.get("Name", "")),
                    part_index,
                    len(parts),
                ),
                used,
            )
            specs.append(
                {
                    "name": name,
                    "coords": list(part.coords),
                    "cell_size_near": _optional_positive(row.get("cell_spacing_near")),
                    "cell_size_far": _optional_positive(row.get("cell_spacing_far")),
                    "near_repeats": _int_or_zero(row.get("near_repeats")),
                    "protection_radius": _int_or_zero(row.get("protection_radius")),
                }
            )
    return specs


def _optional_positive(value: Any) -> Optional[float]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) and numeric > 0 else None


def _retained_reference_line_specs(
    preflight: Breakout2DPreflight,
) -> list[dict[str, Any]]:
    actions = _action_lookup(preflight, "reference_line")
    specs: list[dict[str, Any]] = []
    used: set[str] = set()
    for row in actions.itertuples(index=False):
        if row.action not in {"keep", "clip"} or row.geometry is None:
            continue
        parts = _line_parts(row.geometry)
        for part_index, part in enumerate(parts, start=1):
            name = _deduplicate_ras_name(
                _unique_part_name(str(row.name), part_index, len(parts)),
                used,
            )
            specs.append({"name": name, "coordinates": list(part.coords)})
    return specs


def _retained_refinement_specs(preflight: Breakout2DPreflight) -> list[dict[str, Any]]:
    frame = preflight.source_features.get("refinement_region")
    if frame is None or frame.empty:
        return []
    controls = {
        int(item["fid"]): item
        for item in GeomMesh.get_refinement_regions(preflight.source_geometry_path)
    }
    actions = _action_lookup(preflight, "refinement_region")
    specs: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, row in frame.iterrows():
        fid = int(row.get("rr_id", index))
        feature_id = str(fid)
        if feature_id not in actions.index:
            continue
        geometry = actions.loc[feature_id, "geometry"]
        if geometry is None or geometry.is_empty:
            continue
        control = controls.get(fid)
        if control is None:
            raise ValueError(f"Refinement-region controls are unavailable for FID {fid}")
        polygons = [geometry] if isinstance(geometry, Polygon) else list(geometry.geoms)
        for part_index, polygon in enumerate(polygons, start=1):
            name = _deduplicate_ras_name(
                _unique_part_name(
                    str(row.get("Name", "")),
                    part_index,
                    len(polygons),
                ),
                used,
            )
            specs.append(
                {
                    "name": name,
                    "polygon": polygon,
                    "spacing_dx": float(control["spacing_dx"]),
                    "spacing_dy": float(control["spacing_dy"]),
                }
            )
    return specs


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _geometry_hash(geometry: BaseGeometry) -> str:
    return hashlib.sha256(geometry.wkb).hexdigest()


def _decode_hdf_text(value: Any) -> str:
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, np.ndarray) and value.size == 1:
        return _decode_hdf_text(value.reshape(-1)[0])
    return str(value).strip()


def _result_time_index(hdf: h5py.File) -> pd.Index:
    base = "Results/Unsteady/Output/Output Blocks/Base Output/Unsteady Time Series"
    values = np.asarray(hdf[f"{base}/Time"][()], dtype=float)
    try:
        start = HdfBase.get_simulation_start_time(hdf)
        return HdfUtils.convert_timesteps_to_datetimes(values, start)
    except (ValueError, TypeError, KeyError):
        return pd.Index(pd.to_timedelta(values, unit="D"), name="time")


def _read_hdf_columns(dataset: h5py.Dataset, ids: np.ndarray) -> np.ndarray:
    requested = np.asarray(ids, dtype=int)
    order = np.argsort(requested)
    sorted_values = np.asarray(dataset[:, requested[order]], dtype=float)
    return sorted_values[:, np.argsort(order)]


def _read_boundary_face_flow(
    plan_hdf: Path,
    geometry_hdf: Path,
    mesh_name: str,
    faces: gpd.GeoDataFrame,
    *,
    prefer_native: bool,
) -> tuple[pd.DataFrame, str, str]:
    face_ids = faces["face_id"].to_numpy(dtype=int)
    result_base = (
        "Results/Unsteady/Output/Output Blocks/Base Output/"
        f"Unsteady Time Series/2D Flow Areas/{mesh_name}"
    )
    native_path = f"{result_base}/Face Flow"
    velocity_path = f"{result_base}/Face Velocity"
    water_surface_path = f"{result_base}/Water Surface"
    with h5py.File(plan_hdf, "r") as result_hdf:
        index = _result_time_index(result_hdf)
        if prefer_native and native_path in result_hdf:
            values = _read_hdf_columns(result_hdf[native_path], face_ids)
            units = _decode_hdf_text(result_hdf[native_path].attrs.get("Units", ""))
            return (
                pd.DataFrame(values, index=index, columns=face_ids),
                "native_face_flow",
                units,
            )
        for required in (velocity_path, water_surface_path):
            if required not in result_hdf:
                raise ValueError(
                    "Face Flow is absent and reconstruction inputs are incomplete: "
                    f"missing {required}"
                )
        velocity = _read_hdf_columns(result_hdf[velocity_path], face_ids)
        cell_ids = np.unique(faces[["cell_0", "cell_1"]].to_numpy(dtype=int).ravel())
        cell_wse = _read_hdf_columns(result_hdf[water_surface_path], cell_ids)
        position = {int(cell_id): index for index, cell_id in enumerate(cell_ids)}
        stage = np.empty_like(velocity)
        for column, row in enumerate(faces.itertuples(index=False)):
            stage[:, column] = np.fmax(
                cell_wse[:, position[int(row.cell_0)]],
                cell_wse[:, position[int(row.cell_1)]],
            )
        velocity_units = _decode_hdf_text(
            result_hdf[velocity_path].attrs.get("Units", "")
        )

    geometry_base = f"Geometry/2D Flow Areas/{mesh_name}"
    with h5py.File(geometry_hdf, "r") as geometry:
        info = geometry[f"{geometry_base}/Faces Area Elevation Info"]
        tables = geometry[f"{geometry_base}/Faces Area Elevation Values"]
        area = np.zeros_like(stage)
        for column, row in enumerate(faces.itertuples(index=False)):
            start, count = np.asarray(info[int(row.face_id), :2], dtype=int)
            table = np.asarray(tables[start : start + count], dtype=float)
            elevations = table[:, 0]
            areas = table[:, 1]
            interpolated = np.interp(
                stage[:, column],
                elevations,
                areas,
                left=0.0,
                right=float(areas[-1]),
            )
            above = np.isfinite(stage[:, column]) & (stage[:, column] > elevations[-1])
            interpolated[above] += (
                stage[above, column] - elevations[-1]
            ) * float(row.face_length)
            interpolated[~np.isfinite(stage[:, column])] = 0.0
            area[:, column] = interpolated
    units = "m3/s" if "m/s" in velocity_units.lower() else "ft3/s"
    return (
        pd.DataFrame(velocity * area, index=index, columns=face_ids),
        "reconstructed_face_velocity_stage_area",
        units,
    )


def _time_seconds(index: pd.Index) -> np.ndarray:
    if isinstance(index, (pd.DatetimeIndex, pd.TimedeltaIndex)):
        return np.asarray((index - index[0]).total_seconds(), dtype=float)
    return np.arange(len(index), dtype=float)


def _summarize_face_flux(
    faces: gpd.GeoDataFrame,
    outward: pd.DataFrame,
    *,
    minimum_peak_flow: float,
    minimum_volume_fraction: float,
) -> gpd.GeoDataFrame:
    seconds = _time_seconds(outward.index)
    records: list[dict[str, Any]] = []
    volumes: dict[int, float] = {}
    for face_id in outward.columns:
        values = np.nan_to_num(outward[face_id].to_numpy(dtype=float), nan=0.0)
        volumes[int(face_id)] = float(np.trapezoid(np.abs(values), x=seconds))
    total = sum(volumes.values())
    indexed = faces.set_index("face_id", drop=False)
    for face_id in outward.columns:
        values = np.nan_to_num(outward[face_id].to_numpy(dtype=float), nan=0.0)
        row = indexed.loc[int(face_id)].to_dict()
        outward_volume = float(np.trapezoid(np.maximum(values, 0), x=seconds))
        inward_volume = float(np.trapezoid(np.maximum(-values, 0), x=seconds))
        fraction = volumes[int(face_id)] / total if total > 0 else 0.0
        peak_index = int(np.argmax(np.abs(values)))
        peak_flow = float(values[peak_index])
        direction = "outflow" if outward_volume >= inward_volume else "inflow"
        arrow_sign = 1.0 if direction == "outflow" else -1.0
        multiplier = float(row["orientation_multiplier"]) * arrow_sign
        row.update(
            peak_flow=peak_flow,
            peak_abs_flow=float(abs(peak_flow)),
            peak_inflow=float(abs(min(values.min(), 0.0))),
            peak_outflow=float(max(values.max(), 0.0)),
            absolute_volume=volumes[int(face_id)],
            absolute_volume_fraction=fraction,
            dominant_direction=direction,
            significant=bool(
                abs(peak_flow) >= minimum_peak_flow
                and fraction >= minimum_volume_fraction
            ),
            arrow_dx=float(row["normal_x"]) * multiplier,
            arrow_dy=float(row["normal_y"]) * multiplier,
        )
        records.append(row)
    return gpd.GeoDataFrame(records, geometry="geometry", crs=faces.crs)


def _combine_flux_locations(
    faces: gpd.GeoDataFrame,
    outward: pd.DataFrame,
    *,
    gap_multiplier: float,
) -> gpd.GeoDataFrame:
    significant = faces[faces["significant"].astype(bool)].sort_values(
        ["boundary_station", "face_id"]
    )
    columns = [
        "zone_id",
        "dominant_direction",
        "face_count",
        "face_ids",
        "peak_flow",
        "peak_abs_flow",
        "absolute_volume_fraction",
        "arrow_dx",
        "arrow_dy",
        "geometry",
    ]
    if significant.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs=faces.crs)
    characteristic = float(np.median(significant["face_length"].to_numpy(dtype=float)))
    gap_limit = max(characteristic * gap_multiplier, 1e-9)
    groups: list[list[int]] = []
    current: list[int] = []
    previous_station: Optional[float] = None
    previous_direction: Optional[str] = None
    for row in significant.itertuples(index=False):
        station = float(row.boundary_station)
        if current and (
            station - float(previous_station) > gap_limit
            or row.dominant_direction != previous_direction
        ):
            groups.append(current)
            current = []
        current.append(int(row.face_id))
        previous_station = station
        previous_direction = str(row.dominant_direction)
    if current:
        groups.append(current)

    seconds = _time_seconds(outward.index)
    total_volume = float(faces["absolute_volume"].sum())
    indexed = faces.set_index("face_id", drop=False)
    records: list[dict[str, Any]] = []
    for zone_index, face_ids in enumerate(groups, start=1):
        values = outward[face_ids].sum(axis=1).to_numpy(dtype=float)
        peak_index = int(np.argmax(np.abs(values)))
        peak_flow = float(values[peak_index])
        outward_volume = float(np.trapezoid(np.maximum(values, 0), x=seconds))
        inward_volume = float(np.trapezoid(np.maximum(-values, 0), x=seconds))
        direction = "outflow" if outward_volume >= inward_volume else "inflow"
        zone_faces = indexed.loc[face_ids]
        sign = 1.0 if direction == "outflow" else -1.0
        dx = float(
            np.mean(
                zone_faces["normal_x"].to_numpy(dtype=float)
                * zone_faces["orientation_multiplier"].to_numpy(dtype=float)
                * sign
            )
        )
        dy = float(
            np.mean(
                zone_faces["normal_y"].to_numpy(dtype=float)
                * zone_faces["orientation_multiplier"].to_numpy(dtype=float)
                * sign
            )
        )
        magnitude = math.hypot(dx, dy) or 1.0
        unioned = unary_union(zone_faces.geometry.tolist())
        merged = unioned if isinstance(unioned, LineString) else linemerge(unioned)
        records.append(
            {
                "zone_id": f"FLUX-{zone_index:03d}",
                "dominant_direction": direction,
                "face_count": len(face_ids),
                "face_ids": json.dumps(face_ids),
                "peak_flow": peak_flow,
                "peak_abs_flow": abs(peak_flow),
                "absolute_volume_fraction": (
                    float(np.trapezoid(np.abs(values), x=seconds)) / total_volume
                    if total_volume > 0
                    else 0.0
                ),
                "arrow_dx": dx / magnitude,
                "arrow_dy": dy / magnitude,
                "geometry": merged,
            }
        )
    return gpd.GeoDataFrame(
        records,
        columns=columns,
        geometry="geometry",
        crs=faces.crs,
    )
