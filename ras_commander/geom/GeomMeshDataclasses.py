"""
GeomMeshDataclasses - Dataclasses for headless mesh generation results.

These dataclasses are used by GeomMesh and are importable without
pythonnet or Windows dependencies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class GridAnchor:
    """One point of a 2D area's regular computation-point lattice.

    RAS Mapper lays the regular (base) grid of a 2D flow area from the
    area's own bounding box: the first point is half a cell inside the
    minimum x and the maximum y, then one point every ``spacing_dx`` /
    ``spacing_dy``. A child area cut from a parent therefore gets a grid
    that is offset from the parent's by a sub-cell vector. A ``GridAnchor``
    names a lattice point (and the spacing) that the regenerated grid must
    pass through instead, so a child or ensemble member re-meshes on the
    parent's lattice.

    Coordinates and spacing are in the geometry's projected CRS and
    horizontal units. Only the phase ``(x mod spacing_dx, y mod spacing_dy)``
    matters; any lattice point of the parent gives the same grid.

    Attributes:
        x: X coordinate of a lattice point.
        y: Y coordinate of a lattice point.
        spacing_dx: Lattice spacing in x (the base cell size).
        spacing_dy: Lattice spacing in y.
        source: Free-text provenance, such as the parent HDF and area name.
    """

    x: float
    y: float
    spacing_dx: float
    spacing_dy: float
    source: str = ""

    def __post_init__(self) -> None:
        for name in ("x", "y", "spacing_dx", "spacing_dy"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"GridAnchor.{name} must be a number")
            if not math.isfinite(float(value)):
                raise ValueError(f"GridAnchor.{name} must be finite")
        if self.spacing_dx <= 0 or self.spacing_dy <= 0:
            raise ValueError("GridAnchor spacing must be positive")

    @property
    def phase(self) -> Tuple[float, float]:
        """Lattice phase ``(x mod spacing_dx, y mod spacing_dy)``."""
        return (
            float(self.x) % float(self.spacing_dx),
            float(self.y) % float(self.spacing_dy),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return machine-readable anchor evidence."""
        return {
            "x": float(self.x),
            "y": float(self.y),
            "spacing_dx": float(self.spacing_dx),
            "spacing_dy": float(self.spacing_dy),
            "phase": list(self.phase),
            "source": self.source,
        }


@dataclass(frozen=True)
class DomainContainmentViolation:
    """One mesh-owned feature that is not inside the eroded 2D domain."""

    feature_type: str
    feature_name: str
    feature_index: int
    geometry_type: str
    reason: str
    outside_length: float = 0.0
    outside_area: float = 0.0
    structure_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return machine-readable violation evidence."""
        return {
            "feature_type": self.feature_type,
            "feature_name": self.feature_name,
            "feature_index": self.feature_index,
            "geometry_type": self.geometry_type,
            "reason": self.reason,
            "outside_length": self.outside_length,
            "outside_area": self.outside_area,
            "structure_type": self.structure_type,
        }


@dataclass(frozen=True)
class DomainContainmentResult:
    """Pre-mesh containment evidence for one 2D flow area."""

    mesh_name: str
    geom_hdf_path: str
    base_cell_spacing: float
    inward_buffer_distance: float
    admissible_geometry_type: str
    checked_counts: Dict[str, int]
    violations: List[DomainContainmentViolation]

    @property
    def ok(self) -> bool:
        return not self.violations

    def __bool__(self) -> bool:
        return self.ok

    def to_dict(self) -> Dict[str, Any]:
        """Return machine-readable audit evidence without geometry payloads."""
        return {
            "mesh_name": self.mesh_name,
            "geom_hdf_path": self.geom_hdf_path,
            "base_cell_spacing": self.base_cell_spacing,
            "inward_buffer_distance": self.inward_buffer_distance,
            "admissible_geometry_type": self.admissible_geometry_type,
            "checked_counts": dict(self.checked_counts),
            "violation_count": len(self.violations),
            "ok": self.ok,
            "violations": [item.to_dict() for item in self.violations],
        }


@dataclass
class MeshResult:
    """Result of a mesh operation, including computation-point bootstrap.

    ``status="complete"``, ``ok`` and truthiness mean the requested operation
    succeeded. ``operation`` identifies computation-point generation versus
    mesh generation. Completion does not establish hydraulic acceptance.
    """

    mesh_name: str
    status: str  # "complete", "error", "exception"
    mesh_state: str = ""
    cell_count: int = 0
    face_count: int = 0
    iterations: int = 0
    fixes_applied: List[str] = field(default_factory=list)
    error_message: str = ""
    geom_text_path: str = ""
    geom_hdf_path: str = ""
    domain_containment: Optional[DomainContainmentResult] = None
    perimeter_repairs: list[dict[str, Any]] = field(default_factory=list)

    # Empty when disabled; otherwise records rounds, convergence, timing and errors.
    robustness_screening: Dict[str, Any] = field(default_factory=dict)

    # Empty unless generate(grid_anchor=...) was used; then the anchor and
    # lattice/seed counts of each anchored point generation.
    grid_anchor: Dict[str, Any] = field(default_factory=dict)

    # Appended to preserve the positional constructor contract. For point
    # generation, cell_count counts points and no compiled HDF is produced.
    operation: str = "mesh_generation"  # or "computation_points"

    @property
    def ok(self) -> bool:
        return self.status == "complete"

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class BCConflict:
    """A perimeter face covered by 2+ BC lines."""

    face_id: int
    bc_names: List[str]
    flow_area_name: str = ""
    bc_types: List[str] = field(default_factory=list)
    normal_depth_bc: Optional[str] = None


@dataclass
class BCFixResult:
    """Result of BC conflict detection and repair."""

    conflicts_found: int = 0
    conflicts_fixed: int = 0
    trims: List[tuple] = field(default_factory=list)
    unresolvable: List[BCConflict] = field(default_factory=list)
    modified_hdf: bool = False

    @property
    def ok(self) -> bool:
        return len(self.unresolvable) == 0

    def __bool__(self) -> bool:
        return self.ok
