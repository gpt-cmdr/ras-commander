"""
GeomMeshDataclasses - Dataclasses for headless mesh generation results.

These dataclasses are used by GeomMesh and are importable without
pythonnet or Windows dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


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
    """Result of a headless mesh generation attempt."""

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
