//! Explicit mesh-local topology adaptation and caller-owned threshold-sweep state.
//!
//! No HDF sentinel or ghost semantics are inferred. The caller supplies physical
//! row masks and the exact supported negative boundary values for its schema.
use crate::fluvial::{
    self, CellKey, Classification, GraphError, PeakTimes, Thresholds, VerifiedGraph,
};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;

/// HDF face endpoints refer to rows of cell_ids, not application cell IDs.
pub struct MeshFaces<'a> {
    pub mesh_id: u32,
    pub cell_ids: &'a [u64],
    pub physical: &'a [bool],
    pub faces: &'a [[i64; 2]],
    pub boundary_sentinels: &'a [i64],
}

/// Rings use mesh-local vertex identities, without coordinate rounding. Rings
/// may be open or repeat the first vertex once to close. Ghost rings are ignored.
pub struct MeshRings<'a> {
    pub mesh_id: u32,
    pub cell_ids: &'a [u64],
    pub physical: &'a [bool],
    pub rings: &'a [Vec<u64>],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SourceRow {
    /// Index in the caller's mesh slice, independent of the mesh ID.
    pub mesh_index: usize,
    pub cell_row: usize,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TopologyDiagnostics {
    pub physical_cells: usize,
    pub ghost_cells: usize,
    pub source_faces: usize,
    /// At least one explicit boundary endpoint; counted before ghost filtering.
    pub boundary_faces: usize,
    /// Non-boundary faces incident to at least one explicitly nonphysical row.
    pub ghost_faces: usize,
    /// Physical interior faces, including repeated faces for one cell pair.
    pub interior_faces: usize,
    pub duplicate_edges: usize,
    pub unique_edges: usize,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TopologyError {
    DuplicateMesh(u32),
    DuplicateCell {
        mesh: u32,
        cell: u64,
    },
    Length {
        mesh: u32,
        field: &'static str,
        expected: usize,
        actual: usize,
    },
    NonnegativeSentinel {
        mesh: u32,
        value: i64,
    },
    UnknownNegativeEndpoint {
        mesh: u32,
        face: usize,
        value: i64,
    },
    EndpointOutOfRange {
        mesh: u32,
        face: usize,
        value: i64,
    },
    SelfFace {
        mesh: u32,
        face: usize,
        cell_row: usize,
    },
    InvalidRing {
        mesh: u32,
        cell_row: usize,
    },
    NonManifoldEdge {
        mesh: u32,
        vertices: (u64, u64),
    },
    CellFaceLayout {
        cell_row: usize,
    },
    FacePolyline {
        face: usize,
    },
    CellBoundary {
        cell_row: usize,
    },
    Graph(GraphError),
}
impl fmt::Display for TopologyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid fluvial topology: {self:?}")
    }
}
impl std::error::Error for TopologyError {}
impl From<GraphError> for TopologyError {
    fn from(error: GraphError) -> Self {
        Self::Graph(error)
    }
}

#[derive(Clone, Debug)]
pub struct BuiltTopology {
    pub graph: VerifiedGraph,
    /// Output graph vertex -> original mesh row, also used to align peak arrays.
    pub source_rows: Vec<SourceRow>,
    pub diagnostics: TopologyDiagnostics,
}

fn check_mesh(
    mesh: u32,
    ids: &[u64],
    physical: &[bool],
    seen: &mut BTreeSet<u32>,
) -> Result<(), TopologyError> {
    if !seen.insert(mesh) {
        return Err(TopologyError::DuplicateMesh(mesh));
    }
    if physical.len() != ids.len() {
        return Err(TopologyError::Length {
            mesh,
            field: "physical",
            expected: ids.len(),
            actual: physical.len(),
        });
    }
    let mut cells = BTreeSet::new();
    for &cell in ids {
        if !cells.insert(cell) {
            return Err(TopologyError::DuplicateCell { mesh, cell });
        }
    }
    Ok(())
}

fn add_cells(
    mesh_index: usize,
    mesh_id: u32,
    ids: &[u64],
    physical: &[bool],
    keys: &mut Vec<CellKey>,
    sources: &mut Vec<SourceRow>,
    diagnostics: &mut TopologyDiagnostics,
) -> Vec<Option<usize>> {
    ids.iter()
        .zip(physical)
        .enumerate()
        .map(|(cell_row, (&cell_id, &is_physical))| {
            if is_physical {
                let vertex = keys.len();
                keys.push(CellKey { mesh_id, cell_id });
                sources.push(SourceRow {
                    mesh_index,
                    cell_row,
                });
                diagnostics.physical_cells += 1;
                Some(vertex)
            } else {
                diagnostics.ghost_cells += 1;
                None
            }
        })
        .collect()
}

fn finish(
    keys: Vec<CellKey>,
    source_rows: Vec<SourceRow>,
    edges: BTreeSet<(usize, usize)>,
    mut diagnostics: TopologyDiagnostics,
) -> Result<BuiltTopology, TopologyError> {
    diagnostics.unique_edges = edges.len();
    let mut rows = vec![Vec::new(); keys.len()];
    for (a, b) in edges {
        rows[a].push(b);
        rows[b].push(a);
    }
    let mut offsets = vec![0];
    let mut neighbors = Vec::new();
    for row in rows {
        neighbors.extend(row);
        offsets.push(neighbors.len());
    }
    Ok(BuiltTopology {
        graph: VerifiedGraph::new(keys, offsets, neighbors)?,
        source_rows,
        diagnostics,
    })
}

/// Builds a simple symmetric graph without crossing meshes. Unknown endpoints
/// are errors even on a face whose other endpoint is boundary or ghost.
pub fn build_face_graph(meshes: &[MeshFaces<'_>]) -> Result<BuiltTopology, TopologyError> {
    let mut seen = BTreeSet::new();
    let mut keys = Vec::new();
    let mut sources = Vec::new();
    let mut diagnostics = TopologyDiagnostics::default();
    let mut edges = BTreeSet::new();
    for (mesh_index, mesh) in meshes.iter().enumerate() {
        check_mesh(mesh.mesh_id, mesh.cell_ids, mesh.physical, &mut seen)?;
        for &value in mesh.boundary_sentinels {
            if value >= 0 {
                return Err(TopologyError::NonnegativeSentinel {
                    mesh: mesh.mesh_id,
                    value,
                });
            }
        }
        let map = add_cells(
            mesh_index,
            mesh.mesh_id,
            mesh.cell_ids,
            mesh.physical,
            &mut keys,
            &mut sources,
            &mut diagnostics,
        );
        for (face, endpoints) in mesh.faces.iter().enumerate() {
            diagnostics.source_faces += 1;
            let mut rows = [None; 2];
            for (side, &value) in endpoints.iter().enumerate() {
                if value < 0 {
                    if !mesh.boundary_sentinels.contains(&value) {
                        return Err(TopologyError::UnknownNegativeEndpoint {
                            mesh: mesh.mesh_id,
                            face,
                            value,
                        });
                    }
                } else {
                    let row = usize::try_from(value)
                        .ok()
                        .filter(|&row| row < map.len())
                        .ok_or(TopologyError::EndpointOutOfRange {
                            mesh: mesh.mesh_id,
                            face,
                            value,
                        })?;
                    rows[side] = Some(row);
                }
            }
            let (Some(a), Some(b)) = (rows[0], rows[1]) else {
                diagnostics.boundary_faces += 1;
                continue;
            };
            if a == b {
                return Err(TopologyError::SelfFace {
                    mesh: mesh.mesh_id,
                    face,
                    cell_row: a,
                });
            }
            let (Some(a), Some(b)) = (map[a], map[b]) else {
                diagnostics.ghost_faces += 1;
                continue;
            };
            diagnostics.interior_faces += 1;
            if !edges.insert((a.min(b), a.max(b))) {
                diagnostics.duplicate_edges += 1;
            }
        }
    }
    finish(keys, sources, edges, diagnostics)
}

/// Adjacency fallback from exact mesh-local vertex IDs. Rejects malformed rings
/// and edges incident to >2 physical cells instead of guessing their meaning.
pub fn build_ring_graph(meshes: &[MeshRings<'_>]) -> Result<BuiltTopology, TopologyError> {
    let mut seen = BTreeSet::new();
    let mut keys = Vec::new();
    let mut sources = Vec::new();
    let mut diagnostics = TopologyDiagnostics::default();
    let mut edges = BTreeSet::new();
    for (mesh_index, mesh) in meshes.iter().enumerate() {
        check_mesh(mesh.mesh_id, mesh.cell_ids, mesh.physical, &mut seen)?;
        if mesh.rings.len() != mesh.cell_ids.len() {
            return Err(TopologyError::Length {
                mesh: mesh.mesh_id,
                field: "rings",
                expected: mesh.cell_ids.len(),
                actual: mesh.rings.len(),
            });
        }
        let map = add_cells(
            mesh_index,
            mesh.mesh_id,
            mesh.cell_ids,
            mesh.physical,
            &mut keys,
            &mut sources,
            &mut diagnostics,
        );
        let mut owners: BTreeMap<(u64, u64), Vec<usize>> = BTreeMap::new();
        for (cell_row, ring) in mesh.rings.iter().enumerate() {
            let Some(vertex) = map[cell_row] else {
                continue;
            };
            let ring = if ring.len() > 1 && ring.first() == ring.last() {
                &ring[..ring.len() - 1]
            } else {
                ring
            };
            if ring.len() < 3 || ring.iter().copied().collect::<BTreeSet<_>>().len() != ring.len() {
                return Err(TopologyError::InvalidRing {
                    mesh: mesh.mesh_id,
                    cell_row,
                });
            }
            for i in 0..ring.len() {
                let (a, b) = (ring[i], ring[(i + 1) % ring.len()]);
                let vertices = (a.min(b), a.max(b));
                let row = owners.entry(vertices).or_default();
                row.push(vertex);
                if row.len() > 2 {
                    return Err(TopologyError::NonManifoldEdge {
                        mesh: mesh.mesh_id,
                        vertices,
                    });
                }
            }
        }
        for row in owners.values() {
            diagnostics.source_faces += 1;
            if row.len() == 1 {
                diagnostics.boundary_faces += 1;
            } else {
                diagnostics.interior_faces += 1;
                if !edges.insert((row[0].min(row[1]), row[0].max(row[1]))) {
                    diagnostics.duplicate_edges += 1;
                }
            }
        }
    }
    finish(keys, sources, edges, diagnostics)
}

/// Assemble polygon rings from physical face polylines, preserving intermediate
/// vertices. Results retain raw row order, with empty rings for nonphysical rows.
/// Input face references are [face index, unused orientation]; no interpretation
/// or constraint is applied to the second column. The cycle determines winding
/// independently. Each physical cell must have exactly one simple cycle.
/// Multiple cycles, repeated edges, dangling branches and repeated vertices fail.
/// Coordinates and coordinate-level self-intersection checks belong to geometry.
pub fn assemble_cell_rings(
    cell_face_info: &[[i64; 2]],
    cell_face_values: &[[i64; 2]],
    face_rings: &[Vec<usize>],
    physical: &[bool],
) -> Result<Vec<Vec<usize>>, TopologyError> {
    if cell_face_info.len() != physical.len() {
        return Err(TopologyError::Length {
            mesh: 0,
            field: "cell_face_info",
            expected: physical.len(),
            actual: cell_face_info.len(),
        });
    }
    let mut output = Vec::with_capacity(physical.len());
    for (cell_row, (&[start, count], &is_physical)) in
        cell_face_info.iter().zip(physical).enumerate()
    {
        if !is_physical {
            output.push(Vec::new());
            continue;
        }
        let layout_error = || TopologyError::CellFaceLayout { cell_row };
        let start = usize::try_from(start).map_err(|_| layout_error())?;
        let count = usize::try_from(count).map_err(|_| layout_error())?;
        let end = start
            .checked_add(count)
            .filter(|&end| end <= cell_face_values.len())
            .ok_or_else(layout_error)?;
        let mut edges = BTreeSet::new();
        let mut neighbors: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
        for &[face, _orientation] in &cell_face_values[start..end] {
            let face = usize::try_from(face)
                .ok()
                .filter(|&face| face < face_rings.len())
                .ok_or_else(layout_error)?;
            let points = &face_rings[face];
            if points.len() < 2
                || points.iter().copied().collect::<BTreeSet<_>>().len() != points.len()
            {
                return Err(TopologyError::FacePolyline { face });
            }
            for points in points.windows(2) {
                let (a, b) = (points[0], points[1]);
                if !edges.insert((a.min(b), a.max(b))) {
                    return Err(TopologyError::CellBoundary { cell_row });
                }
                neighbors.entry(a).or_default().push(b);
                neighbors.entry(b).or_default().push(a);
            }
        }
        if neighbors.len() < 3 || neighbors.values().any(|row| row.len() != 2) {
            return Err(TopologyError::CellBoundary { cell_row });
        }
        for row in neighbors.values_mut() {
            row.sort_unstable();
        }
        let start = *neighbors.keys().next().unwrap();
        let mut ring = vec![start];
        let mut visited = BTreeSet::from([start]);
        let mut previous = start;
        let mut current = neighbors[&start][0];
        while current != start {
            if !visited.insert(current) {
                return Err(TopologyError::CellBoundary { cell_row });
            }
            ring.push(current);
            let row = &neighbors[&current];
            let next = if row[0] == previous { row[1] } else { row[0] };
            previous = current;
            current = next;
        }
        if visited.len() != neighbors.len() {
            return Err(TopologyError::CellBoundary { cell_row });
        }
        output.push(ring);
    }
    Ok(output)
}

/// Immutable analysis snapshot. Rebuild explicitly when source geometry or peaks
/// change. Owns all arrays and never keys a process-global cache by file path.
#[derive(Clone, Debug)]
pub struct AnalysisState {
    graph: VerifiedGraph,
    milliseconds: Vec<i64>,
    valid: Vec<bool>,
    wet: Vec<bool>,
    time_valid: Vec<bool>,
}
impl AnalysisState {
    pub fn new(
        graph: VerifiedGraph,
        milliseconds: Vec<i64>,
        valid: Vec<bool>,
        wet: Vec<bool>,
        time_valid: Vec<bool>,
    ) -> Result<Self, GraphError> {
        let expected = graph.keys().len();
        for (field, actual) in [
            ("milliseconds", milliseconds.len()),
            ("valid", valid.len()),
            ("wet", wet.len()),
            ("time_valid", time_valid.len()),
        ] {
            if actual != expected {
                return Err(GraphError::Length {
                    field,
                    expected,
                    actual,
                });
            }
        }
        Ok(Self {
            graph,
            milliseconds,
            valid,
            wet,
            time_valid,
        })
    }
    pub fn graph(&self) -> &VerifiedGraph {
        &self.graph
    }
    pub fn peak_times(&self) -> PeakTimes<'_> {
        PeakTimes {
            milliseconds: &self.milliseconds,
            valid: &self.valid,
            wet: &self.wet,
            time_valid: &self.time_valid,
        }
    }
    pub fn classify(&self, thresholds: Thresholds) -> Result<Classification, GraphError> {
        fluvial::classify(&self.graph, self.peak_times(), thresholds)
    }
}
