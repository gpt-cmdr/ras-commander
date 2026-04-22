"""
GeomMeshDataclasses - Dataclasses for headless mesh generation results.

These dataclasses are used by GeomMesh and are importable without
pythonnet or Windows dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


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
