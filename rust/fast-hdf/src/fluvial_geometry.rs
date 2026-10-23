//! Exact-ID cell union without Python, coordinate snapping, or geometry dependencies.
//!
//! Input must be a conforming planar mesh: distinct point IDs are never welded and
//! unrelated cells must not geometrically overlap. Each cell is checked for a
//! simple, nondegenerate ring; exact shared edges are checked for manifoldness.
//! Global overlap detection between cells without shared edges is not performed.
//! Output rings are closed, canonicalized, and retain the supplied point IDs.
//! Shells are counterclockwise, holes clockwise. Corner contacts stay separate.
//! Minimum area removes complete polygons, including their holes, in square metres.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fmt;
use std::time::Instant;

#[derive(Debug, Clone, PartialEq)]
pub enum GeometryError {
    Length {
        field: &'static str,
        expected: usize,
        actual: usize,
    },
    InvalidLinearUnit,
    InvalidMinimumArea,
    NonFinitePoint(usize),
    PointOutOfRange {
        cell: usize,
        point: usize,
    },
    InvalidRing {
        cell: usize,
        reason: &'static str,
    },
    NonManifoldEdge {
        mesh_id: u32,
        a: usize,
        b: usize,
    },
    SameSideEdge {
        mesh_id: u32,
        a: usize,
        b: usize,
    },
    BoundaryTopology,
    OrphanHole {
        mesh_id: u32,
        label: u8,
    },
    AreaMismatch {
        mesh_id: u32,
        label: u8,
    },
}
impl fmt::Display for GeometryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid fluvial geometry input: {self:?}")
    }
}
impl std::error::Error for GeometryError {}

#[derive(Debug, Clone, PartialEq)]
pub struct Polygon {
    pub shell: Vec<usize>,
    pub holes: Vec<Vec<usize>>,
    pub area_m2: f64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct RegionGeometry {
    pub mesh_id: u32,
    pub label: u8,
    pub polygons: Vec<Polygon>,
}
#[derive(Debug, Clone, Default, PartialEq)]
pub struct GeometryDiagnostics {
    pub cells: usize,
    pub boundary_edges: usize,
    pub rings: usize,
    pub removed_polygons: usize,
    pub removed_area_m2: f64,
    /// Validation plus shared-edge indexing and boundary extraction.
    pub boundary_seconds: f64,
    /// Tracing, hole assignment, canonicalization, and area filtering.
    pub polygonization_seconds: f64,
}
#[derive(Debug, Clone, PartialEq)]
pub struct Geometry {
    pub regions: Vec<RegionGeometry>,
    pub diagnostics: GeometryDiagnostics,
}

#[derive(Clone, Copy)]
struct Edge {
    cell: usize,
    a: usize,
    b: usize,
    next: usize,
}

fn cross(a: [f64; 2], b: [f64; 2], c: [f64; 2]) -> f64 {
    (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
}
fn signed_area(ring: &[usize], points: &[[f64; 2]]) -> f64 {
    let origin = points[ring[0]];
    // Translate to a ring-local origin to avoid cancellation at projected CRS offsets.
    ring.windows(2)
        .map(|e| cross(origin, points[e[0]], points[e[1]]))
        .sum::<f64>()
        * 0.5
}
fn on_segment(p: [f64; 2], a: [f64; 2], b: [f64; 2]) -> bool {
    cross(a, b, p) == 0.0
        && p[0] >= a[0].min(b[0])
        && p[0] <= a[0].max(b[0])
        && p[1] >= a[1].min(b[1])
        && p[1] <= a[1].max(b[1])
}
fn intersects(a: [f64; 2], b: [f64; 2], c: [f64; 2], d: [f64; 2]) -> bool {
    let (ab_c, ab_d, cd_a, cd_b) = (
        cross(a, b, c),
        cross(a, b, d),
        cross(c, d, a),
        cross(c, d, b),
    );
    (ab_c.signum() != ab_d.signum()
        && ab_c != 0.0
        && ab_d != 0.0
        && cd_a.signum() != cd_b.signum()
        && cd_a != 0.0
        && cd_b != 0.0)
        || on_segment(c, a, b)
        || on_segment(d, a, b)
        || on_segment(a, c, d)
        || on_segment(b, c, d)
}
// 1 = strictly inside, 0 = boundary, -1 = outside. No epsilon or snapping.
fn point_in_ring(p: [f64; 2], ring: &[usize], points: &[[f64; 2]]) -> i8 {
    let mut inside = false;
    for edge in ring.windows(2) {
        let (a, b) = (points[edge[0]], points[edge[1]]);
        if on_segment(p, a, b) {
            return 0;
        }
        if (a[1] > p[1]) != (b[1] > p[1]) {
            let x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
            if x > p[0] {
                inside = !inside;
            }
        }
    }
    if inside {
        1
    } else {
        -1
    }
}
fn canonicalize(ring: &mut Vec<usize>) {
    ring.pop();
    let first = ring.iter().enumerate().min_by_key(|(_, p)| *p).unwrap().0;
    ring.rotate_left(first);
    ring.push(ring[0]);
}
// Split a pinched walk at repeated vertices; this preserves each directed edge.
fn split_walk(walk: Vec<usize>) -> Result<Vec<Vec<usize>>, GeometryError> {
    let mut pending = vec![walk];
    let mut result = Vec::new();
    while let Some(walk) = pending.pop() {
        let mut seen = HashMap::new();
        let mut split = None;
        for (j, &p) in walk[..walk.len() - 1].iter().enumerate() {
            if let Some(&i) = seen.get(&p) {
                split = Some((i, j));
                break;
            }
            seen.insert(p, j);
        }
        if let Some((i, j)) = split {
            let a = walk[i..=j].to_vec();
            let mut b = walk[..=i].to_vec();
            b.extend_from_slice(&walk[j + 1..]);
            if a.len() < 4 || b.len() < 4 {
                return Err(GeometryError::BoundaryTopology);
            }
            pending.push(a);
            pending.push(b);
        } else {
            result.push(walk);
        }
    }
    Ok(result)
}

fn validate_points(points: &[[f64; 2]]) -> Result<(), GeometryError> {
    for (i, p) in points.iter().enumerate() {
        if !p[0].is_finite() || !p[1].is_finite() {
            return Err(GeometryError::NonFinitePoint(i));
        }
    }
    Ok(())
}

// One shared implementation for diagnostics and strict polygon construction.
// Global coordinate finiteness must be checked before calling this helper.
fn checked_ring(
    points: &[[f64; 2]],
    source: &[usize],
    cell: usize,
) -> Result<(Vec<usize>, f64), GeometryError> {
    let mut ring = source.to_vec();
    if ring.len() > 1 && ring.first() == ring.last() {
        ring.pop();
    }
    if ring.len() < 3 {
        return Err(GeometryError::InvalidRing {
            cell,
            reason: "fewer than three points",
        });
    }
    let mut seen = HashSet::new();
    for &p in &ring {
        if p >= points.len() {
            return Err(GeometryError::PointOutOfRange { cell, point: p });
        }
        if !seen.insert(p) {
            return Err(GeometryError::InvalidRing {
                cell,
                reason: "repeated point ID",
            });
        }
    }
    ring.push(ring[0]);
    for e in ring.windows(2) {
        if points[e[0]] == points[e[1]] {
            return Err(GeometryError::InvalidRing {
                cell,
                reason: "zero-length edge",
            });
        }
    }
    let len = ring.len() - 1;
    for i in 0..len {
        // Adjacent edges may not double back along the same segment.
        let (a, b, c) = (
            points[ring[i]],
            points[ring[(i + 1) % len]],
            points[ring[(i + 2) % len]],
        );
        if cross(a, b, c) == 0.0
            && ((a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1])) > 0.0
        {
            return Err(GeometryError::InvalidRing {
                cell,
                reason: "overlapping adjacent edges",
            });
        }
        for j in i + 1..len {
            if j == i + 1 || (i == 0 && j == len - 1) {
                continue;
            }
            if intersects(
                points[ring[i]],
                points[ring[i + 1]],
                points[ring[j]],
                points[ring[j + 1]],
            ) {
                return Err(GeometryError::InvalidRing {
                    cell,
                    reason: "self-intersection",
                });
            }
        }
    }
    let area = signed_area(&ring, points);
    if !area.is_finite() || area == 0.0 {
        return Err(GeometryError::InvalidRing {
            cell,
            reason: "nonfinite or zero area",
        });
    }
    if area < 0.0 {
        ring.reverse();
    }
    Ok((ring, area.abs()))
}

/// Identify malformed cell rings in deterministic input-index order.
///
/// Empty reports mean every supplied ring is individually valid; this does not
/// establish global mesh manifoldness or detect overlap between different cells.
/// No geometry is repaired. Invalid rings are reported as `(cell_index, reason)`.
/// Nonfinite global coordinates and out-of-range point references are structural
/// errors and abort validation rather than becoming quarantine candidates.
pub fn validate_cells(
    points: &[[f64; 2]],
    cell_rings: &[Vec<usize>],
) -> Result<Vec<(usize, String)>, GeometryError> {
    validate_points(points)?;
    let mut invalid = Vec::new();
    for (cell, ring) in cell_rings.iter().enumerate() {
        match checked_ring(points, ring, cell) {
            Ok(_) => {}
            Err(GeometryError::InvalidRing { reason, .. }) => {
                invalid.push((cell, reason.to_string()))
            }
            Err(error) => return Err(error),
        }
    }
    Ok(invalid)
}

/// Polygonize all supplied labels independently within each mesh.
///
/// Rings may be open or closed, clockwise or counterclockwise. Input array order
/// affects neither output ring order nor winding. Unit factor is metres per
/// coordinate unit (1 for metres; 0.3048 for international feet).
pub fn polygonize(
    points: &[[f64; 2]],
    cell_rings: &[Vec<usize>],
    mesh_ids: &[u32],
    labels: &[u8],
    linear_unit_to_m: f64,
    min_area_m2: f64,
) -> Result<Geometry, GeometryError> {
    let start = Instant::now();
    let n = cell_rings.len();
    for (field, actual) in [("mesh_ids", mesh_ids.len()), ("labels", labels.len())] {
        if actual != n {
            return Err(GeometryError::Length {
                field,
                expected: n,
                actual,
            });
        }
    }
    let factor = linear_unit_to_m * linear_unit_to_m;
    if !linear_unit_to_m.is_finite()
        || linear_unit_to_m <= 0.0
        || !factor.is_finite()
        || factor == 0.0
    {
        return Err(GeometryError::InvalidLinearUnit);
    }
    if !min_area_m2.is_finite() || min_area_m2 < 0.0 {
        return Err(GeometryError::InvalidMinimumArea);
    }
    validate_points(points)?;
    let mut edges = Vec::<Edge>::new();
    let mut edge_map: HashMap<(u32, usize, usize), Vec<usize>> = HashMap::new();
    let mut expected_area = BTreeMap::<(u32, u8), f64>::new();
    for (cell, source) in cell_rings.iter().enumerate() {
        let (ring, area) = checked_ring(points, source, cell)?;
        if !(area * factor).is_finite() {
            return Err(GeometryError::InvalidRing {
                cell,
                reason: "nonfinite or zero area",
            });
        }
        let len = ring.len() - 1;
        *expected_area
            .entry((mesh_ids[cell], labels[cell]))
            .or_default() += area.abs();
        let offset = edges.len();
        for i in 0..len {
            let (a, b) = (ring[i], ring[i + 1]);
            let key = (mesh_ids[cell], a.min(b), a.max(b));
            let row = edge_map.entry(key).or_default();
            row.push(edges.len());
            if row.len() > 2 {
                return Err(GeometryError::NonManifoldEdge {
                    mesh_id: key.0,
                    a: key.1,
                    b: key.2,
                });
            }
            edges.push(Edge {
                cell,
                a,
                b,
                next: offset + (i + 1) % len,
            });
        }
    }
    let mut twins = vec![None; edges.len()];
    for (&(mesh_id, a, b), row) in &edge_map {
        if row.len() == 2 {
            let (i, j) = (row[0], row[1]);
            if edges[i].a != edges[j].b || edges[i].b != edges[j].a {
                return Err(GeometryError::SameSideEdge { mesh_id, a, b });
            }
            twins[i] = Some(j);
            twins[j] = Some(i);
        }
    }
    let boundary: Vec<bool> = edges
        .iter()
        .enumerate()
        .map(|(i, e)| twins[i].is_none_or(|j| labels[edges[j].cell] != labels[e.cell]))
        .collect();
    let mut diagnostics = GeometryDiagnostics {
        cells: n,
        boundary_edges: boundary.iter().filter(|&&v| v).count(),
        ..Default::default()
    };
    diagnostics.boundary_seconds = start.elapsed().as_secs_f64();
    let start = Instant::now();
    let mut seen = vec![false; edges.len()];
    let mut region_rings = BTreeMap::<(u32, u8), Vec<Vec<usize>>>::new();
    for initial in 0..edges.len() {
        if !boundary[initial] || seen[initial] {
            continue;
        }
        let cell = edges[initial].cell;
        let key = (mesh_ids[cell], labels[cell]);
        let mut walk = vec![edges[initial].a];
        let mut current = initial;
        loop {
            if seen[current] {
                return Err(GeometryError::BoundaryTopology);
            }
            seen[current] = true;
            walk.push(edges[current].b);
            let mut next = edges[current].next;
            let mut steps = 0;
            while !boundary[next] {
                next = edges[twins[next].ok_or(GeometryError::BoundaryTopology)?].next;
                steps += 1;
                if steps > edges.len() {
                    return Err(GeometryError::BoundaryTopology);
                }
            }
            if next == initial {
                break;
            }
            current = next;
        }
        if walk.first() != walk.last() {
            return Err(GeometryError::BoundaryTopology);
        }
        for mut ring in split_walk(walk)? {
            if ring.len() < 4 || signed_area(&ring, points) == 0.0 {
                return Err(GeometryError::BoundaryTopology);
            }
            canonicalize(&mut ring);
            region_rings.entry(key).or_default().push(ring);
            diagnostics.rings += 1;
        }
    }
    let mut regions = Vec::new();
    for ((mesh_id, label), mut rings) in region_rings {
        // Fix arithmetic order as well as final ring order: successive floating
        // hole-area subtractions must not depend on source cell enumeration.
        rings.sort();
        let mut polygons = Vec::<Polygon>::new();
        let mut holes = Vec::new();
        for ring in rings {
            let area = signed_area(&ring, points);
            if area > 0.0 {
                polygons.push(Polygon {
                    shell: ring,
                    holes: Vec::new(),
                    area_m2: area * factor,
                });
            } else {
                holes.push((ring, -area * factor));
            }
        }
        for (hole, area) in holes {
            let mut containers = Vec::new();
            for (i, polygon) in polygons.iter().enumerate() {
                let relation = hole[..hole.len() - 1]
                    .iter()
                    .map(|&p| point_in_ring(points[p], &polygon.shell, points))
                    .find(|&r| r != 0);
                if relation == Some(1) {
                    containers.push(i);
                }
            }
            let owner = containers
                .into_iter()
                .min_by(|&a, &b| {
                    // Use shell area, before subtraction of other holes.
                    signed_area(&polygons[a].shell, points)
                        .total_cmp(&signed_area(&polygons[b].shell, points))
                })
                .ok_or(GeometryError::OrphanHole { mesh_id, label })?;
            polygons[owner].area_m2 -= area;
            polygons[owner].holes.push(hole);
        }
        let actual: f64 = polygons.iter().map(|p| p.area_m2).sum();
        let expected = expected_area[&(mesh_id, label)] * factor;
        if !actual.is_finite()
            || !expected.is_finite()
            || (actual - expected).abs() > expected.abs().max(1.0) * 1e-9
            || polygons.iter().any(|p| p.area_m2 <= 0.0)
        {
            return Err(GeometryError::AreaMismatch { mesh_id, label });
        }
        for polygon in &mut polygons {
            polygon.holes.sort();
        }
        polygons.sort_by(|a, b| a.shell.cmp(&b.shell));
        polygons.retain(|p| {
            if p.area_m2 < min_area_m2 {
                diagnostics.removed_polygons += 1;
                diagnostics.removed_area_m2 += p.area_m2;
                false
            } else {
                true
            }
        });
        regions.push(RegionGeometry {
            mesh_id,
            label,
            polygons,
        });
    }
    diagnostics.polygonization_seconds = start.elapsed().as_secs_f64();
    Ok(Geometry {
        regions,
        diagnostics,
    })
}
