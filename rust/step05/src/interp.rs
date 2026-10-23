//! Prepared, reusable interpolator over caller-supplied global simplices.
//!
//! The triangle evaluation, inclusion tolerance and tie rule are copied from the baseline
//! prototype kernel (`prototype/kernel/src/lib.rs`). Differences: degenerate simplices are
//! skipped (counted) instead of aborting, and the structure is built once and shared read-only by
//! all tiles and AOIs of a profile.
use crate::MapError;
use rstar::{AABB, RTree, RTreeObject};

pub const MAX_SAMPLES: usize = 50_000_000;
pub const MAX_SIMPLICES: usize = 100_000_000;
/// Reciprocal-condition threshold below which a supplied simplex is treated as singular.
pub const RCOND_LIMIT: f64 = 1000.0 * f64::EPSILON;

#[derive(Clone)]
struct Triangle {
    id: u32,
    bounds: AABB<[f64; 2]>,
    a: [f64; 2],
    u: [f64; 2],
    v: [f64; 2],
    determinant: f64,
    z: [f64; 3],
}

impl RTreeObject for Triangle {
    type Envelope = AABB<[f64; 2]>;
    fn envelope(&self) -> Self::Envelope {
        self.bounds
    }
}

impl Triangle {
    /// Baseline kernel formula, unchanged.
    #[inline]
    fn at(&self, p: [f64; 2]) -> Option<f64> {
        let x = p[0] - self.a[0];
        let y = p[1] - self.a[1];
        let b = (x * self.v[1] - y * self.v[0]) / self.determinant;
        let c = (self.u[0] * y - self.u[1] * x) / self.determinant;
        let a = 1.0 - b - c;
        let eps = 100.0 * f64::EPSILON;
        if a >= -eps && b >= -eps && c >= -eps {
            Some(a * self.z[0] + b * self.z[1] + c * self.z[2])
        } else {
            None
        }
    }
}

/// Exact 1-norm reciprocal condition number of the 2x2 transform [u v].
fn rcond(u: [f64; 2], v: [f64; 2], det: f64) -> f64 {
    let norm = (u[0].abs() + u[1].abs()).max(v[0].abs() + v[1].abs());
    let inv = (v[1].abs() + u[1].abs()).max(v[0].abs() + u[0].abs()) / det.abs();
    1.0 / (norm * inv)
}

pub struct PreparedInterpolator {
    tree: RTree<Triangle>,
    pub samples: usize,
    pub simplices_supplied: usize,
    pub triangles_valid: usize,
    pub degenerate_skipped: usize,
}

impl PreparedInterpolator {
    pub fn new(samples: &[[f64; 3]], simplices: &[[usize; 3]]) -> Result<Self, MapError> {
        if samples.len() > MAX_SAMPLES || simplices.len() > MAX_SIMPLICES {
            return Err(MapError::Budget(format!(
                "samples {} / simplices {} exceed limits {MAX_SAMPLES} / {MAX_SIMPLICES}",
                samples.len(),
                simplices.len()
            )));
        }
        if let Some(i) = samples
            .iter()
            .position(|s| !s.iter().all(|x| x.is_finite()))
        {
            return Err(MapError::Invalid(format!("sample {i} is not finite")));
        }
        let mut triangles = Vec::with_capacity(simplices.len());
        let mut degenerate = 0usize;
        for (id, t) in simplices.iter().enumerate() {
            if let Some(bad) = t.iter().find(|i| **i >= samples.len()) {
                return Err(MapError::Invalid(format!(
                    "simplex {id} index {bad} out of bounds for {} samples",
                    samples.len()
                )));
            }
            let (a, b, c) = (samples[t[0]], samples[t[1]], samples[t[2]]);
            let u = [b[0] - a[0], b[1] - a[1]];
            let v = [c[0] - a[0], c[1] - a[1]];
            if !u.iter().chain(v.iter()).all(|x| x.is_finite()) {
                return Err(MapError::Invalid(format!(
                    "simplex {id} edge vector overflows"
                )));
            }
            let determinant = u[0] * v[1] - u[1] * v[0];
            if !determinant.is_finite() {
                return Err(MapError::Invalid(format!(
                    "simplex {id} determinant overflows"
                )));
            }
            if determinant == 0.0 || rcond(u, v, determinant) < RCOND_LIMIT {
                degenerate += 1;
                continue;
            }
            triangles.push(Triangle {
                id: id as u32,
                a: [a[0], a[1]],
                u,
                v,
                determinant,
                z: [a[2], b[2], c[2]],
                bounds: AABB::from_corners(
                    [a[0].min(b[0]).min(c[0]), a[1].min(b[1]).min(c[1])],
                    [a[0].max(b[0]).max(c[0]), a[1].max(b[1]).max(c[1])],
                ),
            });
        }
        let valid = triangles.len();
        Ok(Self {
            tree: RTree::bulk_load(triangles),
            samples: samples.len(),
            simplices_supplied: simplices.len(),
            triangles_valid: valid,
            degenerate_skipped: degenerate,
        })
    }

    /// Lowest containing simplex id and interpolated value (baseline tie rule).
    #[inline]
    pub fn locate(&self, p: [f64; 2]) -> Option<(u32, f64)> {
        let mut best: Option<(u32, f64)> = None;
        for t in self
            .tree
            .locate_in_envelope_intersecting(AABB::from_point(p))
        {
            if let Some(z) = t.at(p)
                && best.is_none_or(|(id, _)| t.id < id)
            {
                best = Some((t.id, z));
            }
        }
        best
    }

    /// Self-accounted bytes of the prepared structure (triangles plus R-tree node overhead).
    pub fn approx_bytes(&self) -> u64 {
        (self.triangles_valid as u64) * prepared_bytes_per_simplex()
    }
}

/// In-memory size of one prepared triangle (the `Vec` element handed to `RTree::bulk_load`).
pub fn triangle_bytes() -> u64 {
    std::mem::size_of::<Triangle>() as u64
}

/// Self-accounted resident bytes per valid simplex (triangle plus estimated R-tree overhead).
pub fn prepared_bytes_per_simplex() -> u64 {
    triangle_bytes() + 48
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plane_and_lowest_id_tie() {
        let s = [[0., 0., 0.], [1., 0., 1.], [0., 1., 1.], [1., 1., 2.]];
        // Two triangles sharing the diagonal (1,0)-(0,1); the plane z = x + y.
        let p = PreparedInterpolator::new(&s, &[[1, 2, 3], [0, 1, 2]]).unwrap();
        let (id, z) = p.locate([0.5, 0.5]).unwrap();
        assert_eq!(id, 0);
        assert!((z - 1.0).abs() < 1e-15);
        assert!(p.locate([2.0, 2.0]).is_none());
    }

    #[test]
    fn degenerate_skipped_and_counted() {
        let s = [[0., 0., 0.], [1., 0., 1.], [2., 0., 2.], [0., 1., 1.]];
        let p = PreparedInterpolator::new(&s, &[[0, 1, 2], [0, 1, 3], [0, 0, 3]]).unwrap();
        assert_eq!(p.degenerate_skipped, 2);
        assert_eq!(p.triangles_valid, 1);
        // Remaining valid simplex keeps its original id.
        assert_eq!(p.locate([0.25, 0.25]).unwrap().0, 1);
    }

    #[test]
    fn near_degenerate_sliver_skipped() {
        let s = [[0., 0., 0.], [1., 0., 1.], [0.5, 1e-14, 1.]];
        let p = PreparedInterpolator::new(&s, &[[0, 1, 2]]).unwrap();
        assert_eq!(p.degenerate_skipped, 1);
    }

    #[test]
    fn invalid_inputs_fail() {
        let s = [[0., 0., 0.], [1., 0., 1.], [0., 1., f64::NAN]];
        assert!(PreparedInterpolator::new(&s, &[[0, 1, 2]]).is_err());
        let s = [[0., 0., 0.], [1., 0., 1.], [0., 1., 1.]];
        assert!(PreparedInterpolator::new(&s, &[[0, 1, 3]]).is_err());
        let s = [[-1e308, 0., 0.], [1e308, 0., 1.], [0., 1e308, 1.]];
        assert!(PreparedInterpolator::new(&s, &[[0, 1, 2]]).is_err());
    }
}
