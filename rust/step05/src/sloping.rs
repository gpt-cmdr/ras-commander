//! Experimental sloping reconstruction. Native qualification is stage-specific.
//!
//! Topology is immutable; hydraulic connectivity and corner arcs are rebuilt for each
//! profile. A supplied Rayon pool bounds parallel work without changing summation order.
//! Raster ownership, polygon weights and final depth delivery are separate stages.

use crate::MapError;
use rayon::prelude::*;
use std::sync::atomic::{AtomicBool, Ordering};

/// User-visible RAS Mapper sloping controls. Internal experimental modes are excluded.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    #[serde(default)]
    pub render_mode: RenderMode,
    #[serde(default)]
    pub reduce_shallow_to_horizontal: bool,
    #[serde(default)]
    pub use_depth_weighted_faces: bool,
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub enum RenderMode {
    #[default]
    #[serde(rename = "sloping")]
    Corners,
    #[serde(rename = "slopingPretty")]
    WithFaces,
}
impl Options {
    pub fn validate(self) -> Result<(), MapError> {
        if self.render_mode == RenderMode::Corners
            && (self.reduce_shallow_to_horizontal || self.use_depth_weighted_faces)
        {
            return Err(MapError::Invalid(
                "shallow and depth-weighted controls require slopingPretty".into(),
            ));
        }
        Ok(())
    }
}

pub const NODATA: f32 = -9999.0;

/// Native uncached face application point: the first centre-line intersection
/// is accepted only within the middle 90% of the full face polyline.
pub fn face_application(points: &[[f64; 2]], centers: [[f64; 2]; 2]) -> Result<[f64; 2], MapError> {
    if points.len() < 2
        || points
            .iter()
            .flatten()
            .chain(centers.iter().flatten())
            .any(|v| !v.is_finite())
    {
        return Err(MapError::Invalid(
            "invalid sloping face polyline or centres".into(),
        ));
    }
    let [c, d] = centers;
    let cx = d[0] - c[0];
    let cy = d[1] - c[1];
    let length = |a: [f64; 2], b: [f64; 2]| {
        let x = b[0] - a[0];
        let y = b[1] - a[1];
        (x * x + y * y).sqrt()
    };
    let total = points.windows(2).map(|p| length(p[0], p[1])).sum::<f64>();
    let mut preceding = 0.0;
    for segment in points.windows(2) {
        let [a, b] = [segment[0], segment[1]];
        let before = preceding;
        let segment_length = length(a, b);
        preceding += segment_length;
        if (0..2).any(|axis| {
            a[axis].max(b[axis]) + 1e-6 < c[axis].min(d[axis])
                || c[axis].max(d[axis]) + 1e-6 < a[axis].min(b[axis])
        }) {
            continue;
        }
        let ax = b[0] - a[0];
        let ay = b[1] - a[1];
        let determinant = cy * ax - cx * ay;
        if determinant == 0.0 {
            continue;
        }
        let dy = a[1] - c[1];
        let dx = a[0] - c[0];
        let t = (cx * dy - cy * dx) / determinant;
        let u = (ax * dy - ay * dx) / determinant;
        if t > -1e-6 && t < 1.0 + 1e-6 && u > -1e-6 && u < 1.0 + 1e-6 {
            let fraction = (before + t.clamp(0.0, 1.0) * segment_length) / total;
            if fraction > 0.05 && fraction < 0.95 {
                // Native returns XY computed before clamping the segment fractions.
                return Ok([a[0] + t * ax, a[1] + t * ay]);
            }
            break;
        }
    }
    let half = total * 0.5;
    let mut running = 0.0;
    for segment in points.windows(2) {
        let before = running;
        let segment_length = length(segment[0], segment[1]);
        running += segment_length;
        if running >= half && segment_length > 0.0 {
            let t = (half - before) / segment_length;
            return Ok([
                segment[0][0] + t * (segment[1][0] - segment[0][0]),
                segment[0][1] + t * (segment[1][1] - segment[0][1]),
            ]);
        }
    }
    Ok(*points.last().unwrap())
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Connection {
    None,
    Levee,
    Backfill,
    DownhillDeep,
    DownhillIntermediate,
    DownhillShallow,
}

impl Connection {
    pub fn connected(self) -> bool {
        !matches!(self, Self::None | Self::Levee)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Cell {
    pub minimum: f32,
    pub virtual_cell: bool,
}

#[derive(Clone, Debug)]
pub struct Face {
    pub cells: [usize; 2],
    pub vertices: [usize; 2],
    pub minimum: f32,
    pub perimeter: bool,
    pub application: [f64; 2],
}

#[derive(Clone, Debug)]
pub struct Corner {
    pub point: [f64; 2],
    pub faces: Vec<usize>,
    pub ccw: Vec<usize>,
    pub cw: Vec<usize>,
}

#[derive(Clone, Copy, Debug)]
pub struct FaceWater {
    pub values: [f32; 2],
    pub connection: Connection,
}

/// Oriented native mesh incidence. Face endpoint order is not a spatial sort key.
pub struct Mesh {
    pub cells: Vec<Cell>,
    pub faces: Vec<Face>,
    pub corners: Vec<Corner>,
}

pub struct Reconstruction {
    pub faces: Vec<FaceWater>,
    pub corners: Vec<Vec<f32>>,
}

impl Mesh {
    pub fn validate(&self) -> Result<(), MapError> {
        if self.cells.is_empty()
            || self.faces.is_empty()
            || self.corners.is_empty()
            || self.cells.iter().any(|c| !c.minimum.is_finite())
        {
            return Err(MapError::Invalid(
                "empty sloping mesh or nonfinite cell minimum".into(),
            ));
        }
        for face in &self.faces {
            if face.cells.iter().any(|&i| i >= self.cells.len())
                || face.vertices.iter().any(|&i| i >= self.corners.len())
                || !face.minimum.is_finite()
                || face.application.iter().any(|v| !v.is_finite())
            {
                return Err(MapError::Invalid(
                    "sloping face incidence out of range".into(),
                ));
            }
        }
        for (vertex, corner) in self.corners.iter().enumerate() {
            let n = corner.faces.len();
            if corner.ccw.len() != n
                || corner.cw.len() != n
                || corner.point.iter().any(|v| !v.is_finite())
            {
                return Err(MapError::Invalid(
                    "sloping corner ring length mismatch".into(),
                ));
            }
            for j in 0..n {
                let face = self
                    .faces
                    .get(corner.faces[j])
                    .ok_or_else(|| MapError::Invalid("sloping corner face out of range".into()))?;
                if !face.vertices.contains(&vertex)
                    || corner.ccw[j] >= n
                    || corner.cw[j] >= n
                    || corner.cw[corner.ccw[j]] != j
                {
                    return Err(MapError::Invalid(
                        "invalid sloping corner orientation".into(),
                    ));
                }
            }
            if n > 0 {
                let mut j = 0;
                for step in 0..n {
                    j = corner.ccw[j];
                    if (j == 0) != (step + 1 == n) {
                        return Err(MapError::Invalid(
                            "sloping incidence is not one ring".into(),
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    pub fn reconstruct(
        &self,
        wse: &[f32],
        plot_tolerance: f32,
        pool: &rayon::ThreadPool,
    ) -> Result<Reconstruction, MapError> {
        self.validate()?;
        if wse.len() != self.cells.len()
            || wse.iter().any(|v| !v.is_finite())
            || !plot_tolerance.is_finite()
            || plot_tolerance < 0.0
        {
            return Err(MapError::Invalid(
                "invalid sloping profile or native plot tolerance".into(),
            ));
        }
        pool.install(|| {
            let faces: Vec<_> = self
                .faces
                .par_iter()
                .map(|face| reconstruct_face(face, &self.cells, wse, plot_tolerance))
                .collect();
            let corners = self
                .corners
                .par_iter()
                .enumerate()
                .map(|(i, corner)| reconstruct_corner(i, corner, &self.faces, &faces))
                .collect();
            Ok(Reconstruction { faces, corners })
        })
    }
}

/// Preserve binary32 intermediate rounding and native face classification.
fn reconstruct_face(face: &Face, cells: &[Cell], wse: &[f32], tolerance: f32) -> FaceWater {
    let [a, b] = face.cells;
    let [wa, wb] = [wse[a], wse[b]];
    let [za, zb] = [cells[a].minimum, cells[b].minimum];
    let dry_a = wa <= za + tolerance;
    let dry_b = wb <= zb + tolerance;
    if dry_a || dry_b || face.perimeter {
        return FaceWater {
            values: [
                if dry_a || cells[a].virtual_cell {
                    NODATA
                } else {
                    wa
                },
                if dry_b || cells[b].virtual_cell {
                    NODATA
                } else {
                    wb
                },
            ],
            connection: Connection::None,
        };
    }
    if wa <= face.minimum && wb <= face.minimum {
        return FaceWater {
            values: [wa, wb],
            connection: Connection::None,
        };
    }
    let (upstream, high, low) = if wa > wb { (a, wa, wb) } else { (b, wb, wa) };
    let floor = cells[upstream].minimum;
    let elevation_delta = zb - za;
    let backfill = (wb - wa) * elevation_delta <= 0.0;
    let relief = elevation_delta.abs();
    let depth = high - floor;
    let downstream = face.minimum.max(low);
    let submerged = downstream - floor;
    let head = high - face.minimum;
    let average = (wa + wb) * 0.5;
    let critical = head * (2.0_f32 / 3.0_f32) + face.minimum;
    let critical_cap = average.partial_cmp(&critical) != Some(std::cmp::Ordering::Greater);
    let levee = critical_cap && depth / head > 2.0;
    // The current adjusted native method retains the upstream WSE here;
    // the critical computation classifies connectivity, not an averaged level.
    if levee {
        return FaceWater {
            values: if upstream == a {
                [high, wb]
            } else {
                [wa, high]
            },
            connection: Connection::Levee,
        };
    }
    if backfill {
        return FaceWater {
            values: [high; 2],
            connection: Connection::Backfill,
        };
    }
    if depth >= 2.0 * relief {
        return FaceWater {
            values: [high; 2],
            connection: Connection::DownhillDeep,
        };
    }
    let mut value = downstream + (depth * depth - submerged * submerged) / (2.0 * relief);
    let connection = if depth > relief {
        value = ((2.0 * relief - depth) * value + (depth - relief) * high) / relief;
        Connection::DownhillIntermediate
    } else {
        Connection::DownhillShallow
    };
    FaceWater {
        values: [value; 2],
        connection,
    }
}

#[derive(Default)]
struct Regression {
    xx: f64,
    x: f64,
    yy: f64,
    y: f64,
    z: f64,
    xy: f64,
    yz: f64,
    xz: f64,
    n: usize,
}

impl Regression {
    fn add(&mut self, origin: [f64; 2], point: [f64; 2], value: f32) {
        let x = point[0] - origin[0];
        let y = point[1] - origin[1];
        let z = f64::from(value);
        self.xx += x * x;
        self.x += x;
        self.yy += y * y;
        self.y += y;
        self.z += z;
        self.xy += x * y;
        self.yz += y * z;
        self.xz += x * z;
        self.n += 1;
    }

    fn solve(&self) -> f32 {
        if self.n == 1 {
            return self.z as f32;
        }
        if self.n == 2 {
            return (self.z * 0.5) as f32;
        }
        let n = self.n as f64;
        let determinant = self.xx * (self.yy * n - self.y * self.y)
            - self.xy * (self.xy * n - self.y * self.x)
            + self.x * (self.xy * self.y - self.yy * self.x);
        if determinant == 0.0 {
            return (self.z / n) as f32;
        }
        ((self.xx * (self.yy * self.z - self.yz * self.y)
            - self.xy * (self.xy * self.z - self.yz * self.x)
            + self.xz * (self.xy * self.y - self.yy * self.x))
            / determinant) as f32
    }
}

fn reconstruct_corner(
    vertex: usize,
    corner: &Corner,
    faces: &[Face],
    values: &[FaceWater],
) -> Vec<f32> {
    let mut output = vec![NODATA; corner.faces.len()];
    if corner
        .faces
        .iter()
        .all(|&f| values[f].values == [NODATA; 2])
    {
        return output;
    }
    for j in 0..corner.faces.len() {
        if output[j] != NODATA {
            continue;
        }
        let mut stop = corner.ccw[j];
        while values[corner.faces[stop]].connection.connected() && stop != j {
            stop = corner.ccw[stop];
        }
        let mut first = j;
        if first != stop {
            while values[corner.faces[first]].connection.connected() {
                first = corner.cw[first];
            }
        }
        let mut regression = Regression::default();
        let mut current = first;
        loop {
            let f = corner.faces[current];
            let side = usize::from(faces[f].vertices[0] != vertex);
            let value = values[f].values[side];
            if value != NODATA {
                regression.add(corner.point, faces[f].application, value);
            }
            output[current] = value;
            current = corner.ccw[current];
            if current == stop {
                break;
            }
        }
        let boundary = corner.faces[stop];
        if !values[boundary].connection.connected() {
            let side = usize::from(faces[boundary].vertices[0] == vertex);
            let value = values[boundary].values[side];
            if value != NODATA {
                regression.add(corner.point, faces[boundary].application, value);
            }
        }
        if regression.n > 0 {
            let value = regression.solve();
            current = first;
            loop {
                output[current] = value;
                current = corner.ccw[current];
                if current == stop {
                    break;
                }
            }
        }
        if first == stop {
            break;
        }
    }
    output
}

/// Immutable coefficients for oriented face endpoints, not a centre-point TIN.
pub struct PolygonStencil {
    points: Vec<[f64; 2]>,
    corner_products: Vec<f64>,
}

/// Reuse one scratch buffer per worker; no per-pixel allocation is necessary.
pub struct WeightScratch {
    clipped: bool,
    cross: Vec<f32>,
    products: Vec<f64>,
    weights: Vec<f32>,
    donated: Vec<f32>,
    clockwise: Vec<f32>,
    counterclockwise: Vec<f32>,
}

fn cross(a: [f64; 2], b: [f64; 2], c: [f64; 2]) -> f64 {
    let x1 = b[0] - a[0];
    let y1 = b[1] - a[1];
    let x2 = c[0] - a[0];
    let y2 = c[1] - a[1];
    x1 * y2 - y1 * x2
}

impl WeightScratch {
    pub fn new(vertices: usize) -> Self {
        Self {
            clipped: false,
            cross: vec![0.0; vertices],
            products: vec![0.0; vertices],
            weights: vec![0.0; vertices],
            donated: vec![0.0; 2 * vertices],
            clockwise: vec![0.0; vertices],
            counterclockwise: vec![0.0; vertices],
        }
    }

    fn resize(&mut self, vertices: usize) {
        self.cross.resize(vertices, 0.0);
        self.products.resize(vertices, 0.0);
        self.weights.resize(vertices, 0.0);
        self.donated.resize(2 * vertices, 0.0);
        self.clockwise.resize(vertices, 0.0);
        self.counterclockwise.resize(vertices, 0.0);
    }
}

impl PolygonStencil {
    // The native square test intentionally rounds translated coordinates to f32.
    fn square_bounds(&self) -> Option<[f64; 4]> {
        if self.points.len() != 4 {
            return None;
        }
        let min_x = self
            .points
            .iter()
            .map(|p| p[0])
            .fold(f64::INFINITY, f64::min);
        let min_y = self
            .points
            .iter()
            .map(|p| p[1])
            .fold(f64::INFINITY, f64::min);
        let x: Vec<f32> = self.points.iter().map(|p| (p[0] - min_x) as f32).collect();
        let y: Vec<f32> = self.points.iter().map(|p| (p[1] - min_y) as f32).collect();
        let cx = (x[0] + x[1] + x[2] + x[3]) / 4.0;
        let cy = (y[0] + y[1] + y[2] + y[3]) / 4.0;
        let radius = (x[0] - cx).abs();
        if radius == 0.0
            || (0..4).any(|i| {
                ((x[i] - cx).abs() - radius).abs() > 0.001
                    || ((y[i] - cy).abs() - radius).abs() > 0.001
            })
        {
            return None;
        }
        Some([
            self.points[0][0].min(self.points[2][0]),
            self.points[0][1].min(self.points[2][1]),
            self.points[0][0].max(self.points[2][0]),
            self.points[0][1].max(self.points[2][1]),
        ])
    }

    fn square_weights<'a>(
        &self,
        bounds: [f64; 4],
        point: [f64; 2],
        scratch: &'a mut WeightScratch,
    ) -> &'a [f32] {
        let [left, bottom, right, top] = bounds;
        let mut x = (point[0] - left) / (right - left);
        let mut y = (point[1] - bottom) / (top - bottom);
        if x <= 0.0 {
            x = 0.00001;
        }
        if x >= 1.0 {
            x = 0.99999;
        }
        if y <= 0.0 {
            y = 0.00001;
        }
        if y >= 1.0 {
            y = 0.99999;
        }
        for (i, p) in self.points.iter().enumerate() {
            let wx = if p[0] <= (left + right) * 0.5 {
                1.0 - x
            } else {
                x
            };
            let wy = if p[1] <= (bottom + top) * 0.5 {
                1.0 - y
            } else {
                y
            };
            scratch.weights[i] = (wx * wy) as f32;
        }
        &scratch.weights
    }

    pub fn new(points: Vec<[f64; 2]>) -> Result<Self, MapError> {
        let n = points.len();
        if n < 3 || points.iter().flatten().any(|v| !v.is_finite()) {
            return Err(MapError::Invalid(
                "sloping polygon requires at least three finite endpoints".into(),
            ));
        }
        let corner_products = (0..n)
            .map(|j| cross(points[j], points[(j + 1) % n], points[(j + n - 1) % n]))
            .collect();
        Ok(Self {
            points,
            corner_products,
        })
    }

    pub fn weights<'a>(
        &self,
        point: [f64; 2],
        scratch: &'a mut WeightScratch,
    ) -> Result<&'a [f32], MapError> {
        let n = self.points.len();
        scratch.clipped = false;
        if scratch.weights.len() != n || point.iter().any(|v| !v.is_finite()) {
            return Err(MapError::Invalid(
                "sloping weight scratch dimension or query is invalid".into(),
            ));
        }
        for i in 0..n {
            let value = cross(point, self.points[i], self.points[(i + 1) % n]) as f32;
            scratch.cross[i] = if value == 0.0 { 0.00001_f32 } else { value };
        }
        let mut total = 0.0_f64;
        for j in 0..n {
            let previous = (j + n - 1) % n;
            let mut product = 1.0_f64;
            for k in 0..n {
                if k != j && k != previous {
                    product *= f64::from(scratch.cross[k]);
                }
            }
            scratch.products[j] = product * self.corner_products[j];
            total += scratch.products[j];
        }
        let mut has_negative_product = false;
        for j in 0..n {
            if scratch.products[j] < 0.0 {
                has_negative_product = true;
            }
            scratch.weights[j] = (scratch.products[j] / total) as f32;
            if scratch.weights[j] == 0.0 && scratch.products[j] != 0.0 {
                scratch.clipped = true;
            }
        }
        if has_negative_product {
            let mut total = 0.0_f32;
            for value in &mut scratch.weights {
                if *value < 0.0 {
                    scratch.clipped = true;
                    *value = 0.0;
                } else {
                    total += *value;
                }
            }
            if total != 0.0 {
                for value in &mut scratch.weights {
                    *value /= total;
                }
            }
        }
        Ok(&scratch.weights)
    }
}

/// Match native binary32 offset accumulation, including its nodata convention.
pub fn paint_corner_values(weights: &[f32], values: &[f32]) -> Result<f32, MapError> {
    if weights.len() != values.len() || values.is_empty() {
        return Err(MapError::Invalid(
            "sloping paint dimensions do not match".into(),
        ));
    }
    let anchor = values[0];
    let mut delta = 0.0_f32;
    let mut count = 0;
    for (&weight, &value) in weights.iter().zip(values) {
        let difference = value - anchor;
        if difference != NODATA {
            count += 1;
            delta += weight * difference;
        }
    }
    Ok(if count > 0 { delta + anchor } else { NODATA })
}

/// Native plot tolerance is part of the method; there is no extra depth cutoff.
pub fn deliver_pixel(wse: f32, terrain: f32, native_tolerance: f32) -> Option<[f32; 2]> {
    if !wse.is_finite()
        || !terrain.is_finite()
        || wse == NODATA
        || terrain == NODATA
        || wse < terrain + native_tolerance
    {
        None
    } else {
        Some([wse - terrain, wse])
    }
}

pub struct CellStencil {
    pub physical_ring: Vec<[f64; 2]>,
    polygon: PolygonStencil,
    square: Option<[f64; 4]>,
    corners: Vec<[usize; 2]>, // vertex, incident-face slot
    faces: Vec<[usize; 2]>,   // face, cell side
    elevations: Option<Vec<f32>>,
}

/// Prepare immutable geometry once. Profiles never determine ring ordering.
pub fn prepare_stencils(
    mesh: &Mesh,
    cell_faces: &[Vec<usize>],
) -> Result<Vec<Option<CellStencil>>, MapError> {
    mesh.validate()?;
    if cell_faces.len() != mesh.cells.len() {
        return Err(MapError::Invalid(
            "sloping cell-face table length mismatch".into(),
        ));
    }
    cell_faces
        .iter()
        .enumerate()
        .map(|(cell, faces)| {
            if mesh.cells[cell].virtual_cell {
                return Ok(None);
            }
            let mut points = Vec::with_capacity(faces.len());
            let mut corners = Vec::with_capacity(faces.len());
            for &id in faces {
                let face = mesh
                    .faces
                    .get(id)
                    .ok_or_else(|| MapError::Invalid("cell face out of range".into()))?;
                let vertex = if face.cells[0] == cell {
                    face.vertices[0]
                } else if face.cells[1] == cell {
                    face.vertices[1]
                } else {
                    return Err(MapError::Invalid("cell not incident to face".into()));
                };
                let corner = &mesh.corners[vertex];
                let slot =
                    corner.faces.iter().position(|&f| f == id).ok_or_else(|| {
                        MapError::Invalid("cell face not incident to corner".into())
                    })?;
                points.push(corner.point);
                corners.push([vertex, slot]);
            }
            let polygon = PolygonStencil::new(points)?;
            let square = polygon.square_bounds();
            Ok(Some(CellStencil {
                physical_ring: Vec::new(),
                polygon,
                square,
                corners,
                faces: faces
                    .iter()
                    .map(|&id| [id, usize::from(mesh.faces[id].cells[0] != cell)])
                    .collect(),
                elevations: None,
            }))
        })
        .collect()
}

/// Optional native stored corner elevations, required only for depth weighting.
pub fn set_vertex_elevations(
    stencils: &mut [Option<CellStencil>],
    elevations: &[f32],
    vertex_count: usize,
) -> Result<(), MapError> {
    if elevations.len() != vertex_count || elevations.iter().any(|x| !x.is_finite()) {
        return Err(MapError::Invalid(
            "sloping corner elevation dimensions or values invalid".into(),
        ));
    }
    for stencil in stencils.iter_mut().flatten() {
        stencil.elevations = Some(
            stencil
                .corners
                .iter()
                .map(|&[vertex, _]| elevations[vertex])
                .collect(),
        );
    }
    Ok(())
}

pub struct PreparedProfile {
    local_values: Vec<Vec<f32>>,
    face_values: Vec<Vec<f32>>,
    depth_weights: Vec<Vec<f32>>,
    horizontal: Vec<Option<f32>>,
    wet: Vec<bool>,
    options: Options,
}

pub fn prepare_profile(
    mesh: &Mesh,
    stencils: &[Option<CellStencil>],
    values: &[f32],
    tolerance: f32,
    pool: &rayon::ThreadPool,
) -> Result<PreparedProfile, MapError> {
    prepare_profile_with_options(mesh, stencils, values, tolerance, pool, Options::default())
}

pub fn prepare_profile_with_options(
    mesh: &Mesh,
    stencils: &[Option<CellStencil>],
    values: &[f32],
    tolerance: f32,
    pool: &rayon::ThreadPool,
    options: Options,
) -> Result<PreparedProfile, MapError> {
    options.validate()?;
    if stencils.len() != mesh.cells.len() {
        return Err(MapError::Invalid("sloping stencil count mismatch".into()));
    }
    if options.use_depth_weighted_faces && stencils.iter().flatten().any(|s| s.elevations.is_none())
    {
        return Err(MapError::Unsupported(
            "depth weighting requires stored native FacePoints Elevation".into(),
        ));
    }
    let reconstructed = mesh.reconstruct(values, tolerance, pool)?;
    let local_values: Vec<Vec<f32>> = pool.install(|| {
        stencils
            .par_iter()
            .map(|s| match s {
                Some(s) => s
                    .corners
                    .iter()
                    .map(|&[vertex, slot]| reconstructed.corners[vertex][slot])
                    .collect(),
                None => Vec::new(),
            })
            .collect()
    });
    let face_values: Vec<Vec<f32>> = if options.render_mode == RenderMode::WithFaces {
        pool.install(|| {
            stencils
                .par_iter()
                .map(|s| match s {
                    Some(s) => s
                        .faces
                        .iter()
                        .map(|&[face, side]| reconstructed.faces[face].values[side])
                        .collect(),
                    None => Vec::new(),
                })
                .collect()
        })
    } else {
        Vec::new()
    };
    let depth_weights = if options.use_depth_weighted_faces {
        pool.install(|| {
            stencils
                .par_iter()
                .enumerate()
                .map(|(cell, s)| match s {
                    Some(s) => {
                        let mut result: Vec<_> = local_values[cell]
                            .iter()
                            .zip(s.elevations.as_ref().unwrap())
                            .map(|(&w, &z)| depth_weight(w, z))
                            .collect();
                        result.extend(
                            s.faces
                                .iter()
                                .zip(&face_values[cell])
                                .map(|(&[face, _], &w)| depth_weight(w, mesh.faces[face].minimum)),
                        );
                        result
                    }
                    None => Vec::new(),
                })
                .collect()
        })
    } else {
        Vec::new()
    };
    let horizontal = stencils
        .iter()
        .enumerate()
        .map(|(cell, s)| {
            s.as_ref().and_then(|s| {
                (options.reduce_shallow_to_horizontal
                    && s.faces.iter().all(|&[face, _]| {
                        let c = reconstructed.faces[face].connection;
                        !c.connected() || c == Connection::DownhillShallow
                    }))
                .then_some(values[cell])
            })
        })
        .collect();
    let wet = mesh
        .cells
        .iter()
        .zip(values)
        .map(|(cell, &value)| !cell.virtual_cell && value > cell.minimum + tolerance)
        .collect();
    Ok(PreparedProfile {
        local_values,
        face_values,
        depth_weights,
        horizontal,
        wet,
        options,
    })
}

fn depth_weight(wse: f32, elevation: f32) -> f32 {
    if wse == NODATA || elevation == NODATA || wse <= elevation {
        0.01_f32
    } else {
        f64::from(wse - elevation).max(0.01_f64) as f32
    }
}

impl WeightScratch {
    /// Native node donation: all arithmetic remains binary32 and in ring order.
    fn paint_with_faces(&mut self, corners: &[f32], faces: &[f32], depths: Option<&[f32]>) -> f32 {
        self.paint_with_face_history(corners, faces, depths, false)
    }

    fn paint_with_face_history(
        &mut self,
        corners: &[f32],
        faces: &[f32],
        depths: Option<&[f32]>,
        retain: bool,
    ) -> f32 {
        let n = corners.len();
        for i in 0..n {
            let previous = (i + n - 1) % n;
            let next = (i + 1) % n;
            let adjacent = self.weights[previous] + self.weights[next];
            // The independent pass starts fresh; affected cells are replayed
            // below with native scratch retention inside each geometry batch.
            if !retain {
                self.clockwise[i] = 0.0;
                self.counterclockwise[i] = 0.0;
            }
            if adjacent != 0.0 {
                let fraction = self.weights[i] / adjacent;
                self.clockwise[i] = fraction * self.weights[previous];
                self.counterclockwise[i] = fraction * self.weights[next];
            }
            self.donated[i] = self.weights[i];
        }
        for i in 0..n {
            let next = (i + 1) % n;
            let donation = self.counterclockwise[i].min(self.clockwise[next]);
            self.donated[i] -= donation;
            self.donated[next] -= donation;
            self.donated[n + i] = donation * 2.0;
        }
        let mut total = 0.0_f64;
        if let Some(depths) = depths {
            for (weight, &depth) in self.donated.iter_mut().zip(depths) {
                *weight *= depth;
                total += f64::from(*weight);
            }
        }
        let anchor = faces[0];
        let mut delta = 0.0_f32;
        for (i, &corner) in corners.iter().enumerate() {
            delta += (corner - anchor) * self.donated[i];
        }
        for (i, &face) in faces.iter().enumerate() {
            delta += (face - anchor) * self.donated[n + i];
        }
        if depths.is_some() {
            (f64::from(delta) / total) as f32 + anchor
        } else {
            delta + anchor
        }
    }
}

/// Geometry and terrain belong to the caller and can be reused across timesteps.
/// Labels index `owner_cells` plus one; zero is outside the physical 2D footprint.
pub struct RasterWindow<'a> {
    pub source_transform: [f64; 6],
    pub source_tile: [usize; 2],
    pub width: usize,
    pub height: usize,
    pub transform: [f64; 6],
    pub owner: &'a [u32],
    pub terrain: &'a [f32],
    pub owner_cells: &'a [[usize; 2]], // mesh, local cell
}

pub fn render_profile(
    stencils: &[Vec<Option<CellStencil>>],
    profiles: &[PreparedProfile],
    window: &RasterWindow<'_>,
    tolerance: f32,
    pool: &rayon::ThreadPool,
) -> Result<(Vec<f32>, Vec<f32>), MapError> {
    let count = window
        .width
        .checked_mul(window.height)
        .filter(|&n| n > 0)
        .ok_or_else(|| MapError::Invalid("empty sloping raster window".into()))?;
    if window.owner.len() != count
        || window.terrain.len() != count
        || stencils.len() != profiles.len()
        || window.transform[2] != 0.0
        || window.transform[4] != 0.0
        || window.transform.iter().any(|v| !v.is_finite())
        || !tolerance.is_finite()
        || tolerance < 0.0
    {
        return Err(MapError::Invalid(
            "sloping raster inputs do not match".into(),
        ));
    }
    for &[mesh, cell] in window.owner_cells {
        if mesh >= stencils.len()
            || cell >= stencils[mesh].len()
            || cell >= profiles[mesh].local_values.len()
        {
            return Err(MapError::Invalid(
                "sloping raster owner-cell address out of range".into(),
            ));
        }
    }
    if window
        .owner
        .iter()
        .any(|&i| i as usize > window.owner_cells.len())
    {
        return Err(MapError::Invalid("sloping owner label out of range".into()));
    }
    let mut depth = vec![NODATA; count];
    let mut wse = vec![NODATA; count];
    let repair: Vec<_> = window
        .owner_cells
        .iter()
        .map(|_| AtomicBool::new(false))
        .collect();
    pool.install(|| {
        depth
            .par_chunks_mut(4096)
            .zip(wse.par_chunks_mut(4096))
            .enumerate()
            .try_for_each_init(
                || WeightScratch::new(0),
                |scratch, (chunk, (d, w))| {
                    for j in 0..d.len() {
                        let i = chunk * 4096 + j;
                        let label = window.owner[i] as usize;
                        if label == 0 {
                            continue;
                        }
                        let [mesh, cell] = window.owner_cells[label - 1];
                        if !profiles[mesh].wet[cell] {
                            continue;
                        }
                        if let Some(value) = profiles[mesh].horizontal[cell] {
                            if let Some([delta, value]) =
                                deliver_pixel(value, window.terrain[i], tolerance)
                            {
                                d[j] = delta;
                                w[j] = value;
                            }
                            continue;
                        }
                        let Some(stencil) = &stencils[mesh][cell] else {
                            continue;
                        };
                        let values = &profiles[mesh].local_values[cell];
                        scratch.resize(values.len());
                        let col = i % window.width;
                        let row = i / window.width;
                        let point = [
                            window.transform[0] + (col as f64 + 0.5) * window.transform[1],
                            window.transform[3] + (row as f64 + 0.5) * window.transform[5],
                        ];
                        let weights = if let Some(bounds) = stencil.square {
                            stencil.polygon.square_weights(bounds, point, scratch)
                        } else {
                            stencil.polygon.weights(point, scratch)?
                        };
                        let value = if profiles[mesh].options.render_mode == RenderMode::WithFaces {
                            // End the borrowed weights view before mutating scratch.
                            let _ = weights;
                            if scratch.clipped
                                && (0..values.len()).any(|k| {
                                    scratch.weights[(k + values.len() - 1) % values.len()]
                                        + scratch.weights[(k + 1) % values.len()]
                                        == 0.0
                                })
                            {
                                repair[label - 1].store(true, Ordering::Relaxed);
                            }
                            scratch.paint_with_faces(
                                values,
                                &profiles[mesh].face_values[cell],
                                profiles[mesh]
                                    .options
                                    .use_depth_weighted_faces
                                    .then(|| profiles[mesh].depth_weights[cell].as_slice()),
                            )
                        } else {
                            paint_corner_values(weights, values)?
                        };
                        if let Some([delta, value]) =
                            deliver_pixel(value, window.terrain[i], tolerance)
                        {
                            d[j] = delta;
                            w[j] = value;
                        }
                    }
                    Ok::<_, MapError>(())
                },
            )
    })?;
    // Native geometry donation retains scratch inside fixed 256-point ranges.
    // Replay only cells where clipped weights can expose that state. Replaying
    // complete source tiles keeps bbox/polygon outputs equal to full-map crops.
    let repaired = pool.install(|| {
        window
            .owner_cells
            .par_iter()
            .enumerate()
            .filter_map(|(label, &[mesh, cell])| {
                repair[label]
                    .load(Ordering::Relaxed)
                    .then_some((label + 1, mesh, cell))
            })
            .map(
                |(label, mesh, cell)| -> Result<Vec<(usize, [f32; 2])>, MapError> {
                    let stencil = stencils[mesh][cell].as_ref().unwrap();
                    if stencil.physical_ring.is_empty() {
                        return Err(MapError::Unsupported(
                            "native face donation replay needs full cell perimeter geometry".into(),
                        ));
                    }
                    let [tw, th] = window.source_tile;
                    if tw == 0 || th == 0 || tw.checked_mul(th).is_none_or(|n| n > 16_777_216) {
                        return Err(MapError::Unsupported(
                            "unsupported native donation tile size".into(),
                        ));
                    }
                    let gt = window.source_transform;
                    let xoff = ((window.transform[0] - gt[0]) / gt[1]).round() as i64;
                    let yoff = ((window.transform[3] - gt[3]) / gt[5]).round() as i64;
                    let minx = stencil
                        .physical_ring
                        .iter()
                        .map(|p| p[0])
                        .fold(f64::INFINITY, f64::min);
                    let maxx = stencil
                        .physical_ring
                        .iter()
                        .map(|p| p[0])
                        .fold(f64::NEG_INFINITY, f64::max);
                    let miny = stencil
                        .physical_ring
                        .iter()
                        .map(|p| p[1])
                        .fold(f64::INFINITY, f64::min);
                    let maxy = stencil
                        .physical_ring
                        .iter()
                        .map(|p| p[1])
                        .fold(f64::NEG_INFINITY, f64::max);
                    let c0 = (((minx - gt[0]) / gt[1]).floor() as i64).max(xoff).max(0);
                    let c1 =
                        (((maxx - gt[0]) / gt[1]).ceil() as i64).min(xoff + window.width as i64);
                    let r0 = (((maxy - gt[3]) / gt[5]).floor() as i64).max(yoff).max(0);
                    let r1 =
                        (((miny - gt[3]) / gt[5]).ceil() as i64).min(yoff + window.height as i64);
                    let mut output = Vec::new();
                    if c0 >= c1 || r0 >= r1 {
                        return Ok(output);
                    }
                    for ty in r0 as usize / th..=(r1 as usize - 1) / th {
                        for tx in c0 as usize / tw..=(c1 as usize - 1) / tw {
                            let tile_gt = [
                                gt[0] + (tx * tw) as f64 * gt[1],
                                gt[1],
                                0.,
                                gt[3] + (ty * th) as f64 * gt[5],
                                0.,
                                gt[5],
                            ];
                            let owned = crate::ownership::burn_ring(
                                &stencil.physical_ring,
                                terrio::ops::rasterize::Grid {
                                    geo_transform: tile_gt,
                                    cols: tw,
                                    rows: th,
                                    crs: Default::default(),
                                },
                            )?;
                            let values = &profiles[mesh].local_values[cell];
                            let faces = &profiles[mesh].face_values[cell];
                            let depths = profiles[mesh]
                                .options
                                .use_depth_weighted_faces
                                .then(|| profiles[mesh].depth_weights[cell].as_slice());
                            let mut scratch = WeightScratch::new(values.len());
                            let mut native_index = 0;
                            for (i, &inside) in owned.iter().enumerate() {
                                if inside == 0 {
                                    continue;
                                }
                                if native_index % 256 == 0 {
                                    scratch.clockwise.fill(0.);
                                    scratch.counterclockwise.fill(0.);
                                }
                                native_index += 1;
                                let point = [
                                    tile_gt[0] + (i % tw) as f64 * gt[1] + 0.5 * gt[1],
                                    tile_gt[3] + (i / tw) as f64 * gt[5] + 0.5 * gt[5],
                                ];
                                stencil.polygon.weights(point, &mut scratch)?;
                                let value =
                                    scratch.paint_with_face_history(values, faces, depths, true);
                                let col = (tx * tw + i % tw) as i64 - xoff;
                                let row = (ty * th + i / tw) as i64 - yoff;
                                if col < 0
                                    || row < 0
                                    || col >= window.width as i64
                                    || row >= window.height as i64
                                {
                                    continue;
                                }
                                let index = row as usize * window.width + col as usize;
                                if window.owner[index] as usize != label {
                                    continue;
                                }
                                output.push((
                                    index,
                                    deliver_pixel(value, window.terrain[index], tolerance)
                                        .unwrap_or([NODATA, NODATA]),
                                ));
                            }
                        }
                    }
                    Ok(output)
                },
            )
            .collect::<Result<Vec<_>, MapError>>()
    })?;
    for cell in repaired {
        for (index, [d, w]) in cell {
            depth[index] = d;
            wse[index] = w;
        }
    }
    Ok((depth, wse))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn zero_adjacent_donation_keeps_native_batch_history() {
        let corners = [1., 2., 3., 4., 5., 6.];
        let faces = [2., 3., 4., 5., 6., 7.];
        let mut carried = WeightScratch::new(6);
        carried
            .weights
            .copy_from_slice(&[0.1, 0.2, 0.1, 0.2, 0.1, 0.3]);
        carried.paint_with_face_history(&corners, &faces, None, true);
        let previous = carried.clockwise[3];
        assert_ne!(previous, 0.);
        carried.weights.copy_from_slice(&[1., 0., 0., 0., 0., 0.]);
        let value = carried.paint_with_face_history(&corners, &faces, None, true);
        assert_eq!(carried.clockwise[3].to_bits(), previous.to_bits());
        let mut fresh = WeightScratch::new(6);
        fresh.weights.copy_from_slice(&[1., 0., 0., 0., 0., 0.]);
        assert_ne!(
            value.to_bits(),
            fresh.paint_with_faces(&corners, &faces, None).to_bits()
        );
    }

    #[test]
    fn native_davis_donated_and_depth_rebalanced_scalar_bits() {
        // Independent reflection of native 7.0.1 private scalar painters on
        // public Davis corner/face values. Supplied depth coefficients isolate
        // normalization; tiny negative donated weights must not be clamped.
        let weights = [0x3e648a40, 0x3eda93c1, 0x3e74091d, 0x3de48a40].map(f32::from_bits);
        let corners = [0x42452a70, 0x4244fae3, 0x4242a6f2, 0x424466fa].map(f32::from_bits);
        let faces = [0x4244fae3, 0x4244fae3, 0x4243c5bf, 0x42453384].map(f32::from_bits);
        let depths = [
            0x3c23d70a, 0x3fa00000, 0x418b0000, 0x40490fd0, 0x3c23d70a, 0x3fa00000, 0x418b0000,
            0x40490fd0,
        ]
        .map(f32::from_bits);
        let mut scratch = WeightScratch::new(4);
        scratch.weights.copy_from_slice(&weights);
        assert_eq!(
            scratch.paint_with_faces(&corners, &faces, None).to_bits(),
            1111809851
        );
        let expected_donated = [
            0xb2000000, 0x3d7a0954, 0xb2800000, 0x3c82b774, 0x3eb52e2d, 0x3ec17700, 0x3dca4878,
            0x3dbd704e,
        ];
        assert_eq!(
            scratch
                .donated
                .iter()
                .map(|v| v.to_bits())
                .collect::<Vec<_>>(),
            expected_donated
        );
        assert_eq!(
            scratch
                .paint_with_faces(&corners, &faces, Some(&depths))
                .to_bits(),
            1111765762
        );
    }

    #[test]
    fn davis_square_pixel_preserves_native_rounding() {
        // Real Davis p02 cell146 and a pixel that differed with general weights.
        let polygon = PolygonStencil::new(vec![
            [6630441.54307014, 1966773.76305611],
            [6630441.54307014, 1966623.76305611],
            [6630591.54307014, 1966623.76305611],
            [6630591.54307014, 1966773.76305611],
        ])
        .unwrap();
        let mut scratch = WeightScratch::new(4);
        let point = [6630507.763170041, 1966711.399494069];
        let values = [0x423e156c, 0x423b1da6, 0x423a9ca2, 0x423dcb4e].map(f32::from_bits);
        let weights = polygon.square_weights(polygon.square_bounds().unwrap(), point, &mut scratch);
        assert_eq!(
            paint_corner_values(weights, &values).unwrap().to_bits(),
            0x423caebe
        );
        let general = polygon.weights(point, &mut scratch).unwrap();
        assert_ne!(
            paint_corner_values(general, &values).unwrap().to_bits(),
            0x423caebe
        );
    }

    #[test]
    fn davis_endpoint_intersection_uses_polyline_midpoint() {
        let point = face_application(
            &[
                [6628997.072593668, 1968668.2335325822],
                [6629091.54307014, 1968573.76305611],
            ],
            [
                [6629166.54307014, 1968648.76305611],
                [6629016.54307014, 1968498.76305611],
            ],
        )
        .unwrap();
        assert_eq!(point, [6629044.307831904, 1968620.998294346]);
    }

    #[test]
    fn native_plot_tolerance_is_not_an_extra_depth_cutoff() {
        assert!(deliver_pixel(10.0005, 10.0, 0.001).is_none());
        assert!(deliver_pixel(10.01, 10.0, 0.001).is_some());
        // Native f32 terrain+tolerance may round to terrain at large elevations.
        assert_eq!(
            deliver_pixel(100000.0, 100000.0, 0.001),
            Some([0.0, 100000.0])
        );
        assert!(deliver_pixel(NODATA, 10.0, 0.001).is_none());
    }

    #[test]
    fn invalid_face_geometry_is_rejected() {
        assert!(face_application(&[[0.0, f64::NAN], [1.0, 1.0]], [[0.0; 2]; 2]).is_err());
        assert!(face_application(&[[0.0; 2]], [[0.0; 2]; 2]).is_err());
    }
}
