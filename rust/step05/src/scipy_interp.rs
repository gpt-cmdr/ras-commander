//! Exact port of SciPy's 2-D `LinearNDInterpolator` evaluation over a caller-supplied `Delaunay`.
//!
//! Ported from `scipy/spatial/_qhull.pyx` (`_find_simplex`, `_find_simplex_directed`,
//! `_find_simplex_bruteforce`, `_barycentric_inside`, `_barycentric_coordinate_single`,
//! `_barycentric_coordinates`, `_lift_point`, `_distplane`, `_is_point_fully_outside`) and
//! `scipy/interpolate/_interpnd.pyx` (`LinearNDInterpolator._do_evaluate`): the same
//! operation order, `eps = 100*DBL_EPSILON`, `eps_broad = sqrt(DBL_EPSILON)`, the walk start
//! carried across query points in row-major order, and the value accumulation
//! `out = 0; out += c[k]*z[simplex[k]]` for k = 0..2. No fused multiply-add.
//!
//! The barycentric transforms are SciPy's own (`Delaunay.transform`, supplied): SciPy computes
//! them with LAPACK LU and no scalar 2x2 variant tested reproduced its bits. The transform's
//! origin is the simplex's LAST vertex, as in SciPy (r1 QA M1: the r1 kernel used the first).
//!
//! Two selection modes give identical values:
//! - [`ScipyDelaunay::evaluate_serial`]: the complete serial walk, bit-for-bit SciPy semantics.
//! - [`ScipyDelaunay::evaluate_guarded`]: order-independent per-pixel evaluation. It is exact
//!   only where the SciPy result cannot depend on the walk: the point lies inside some candidate
//!   simplex with every barycentric coordinate >= 0, and every simplex accepted by SciPy's
//!   `eps` test yields bitwise the same value. Any other pixel is reported as ambiguous and the
//!   caller must use the serial walk. Degenerate (NaN-transform) simplices disable guarded
//!   mode entirely, because SciPy's `eps_broad` brute-force branch is path dependent.
use crate::MapError;
use rstar::{AABB, RTree, RTreeObject};

pub const EPS: f64 = 100.0 * f64::EPSILON;

pub fn eps_broad() -> f64 {
    f64::EPSILON.sqrt()
}

/// One SciPy `Delaunay` object, as supplied by the Python adapter.
pub struct ScipyDelaunay {
    pub xy: Vec<[f64; 2]>,
    pub z: Vec<f64>,
    pub simplices: Vec<[u32; 3]>,
    /// `transform[s]` = rows 0-1: inverse matrix (row-major), row 2: origin (last vertex).
    pub transform: Vec<[f64; 6]>,
    pub neighbors: Vec<[i32; 3]>,
    pub equations: Vec<[f64; 4]>,
    pub paraboloid_scale: f64,
    pub paraboloid_shift: f64,
    pub min_bound: [f64; 2],
    pub max_bound: [f64; 2],
    pub degenerate: usize,
    tree: Option<RTree<Env>>,
}

#[derive(Clone)]
struct Env {
    id: u32,
    bounds: AABB<[f64; 2]>,
}

impl RTreeObject for Env {
    type Envelope = AABB<[f64; 2]>;
    fn envelope(&self) -> Self::Envelope {
        self.bounds
    }
}

/// Result of locating and interpolating one query point.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Located {
    Outside,
    Value {
        simplex: u32,
        value: f64,
    },
    /// Guarded mode only: the SciPy result may depend on the walk order.
    Ambiguous,
}

#[derive(Default, Debug, Clone, Copy, serde::Serialize)]
pub struct WalkStats {
    pub points: u64,
    pub outside_bbox: u64,
    pub bruteforce_calls: u64,
    pub directed_steps: u64,
}

pub struct DelaunayParts {
    pub samples: Vec<[f64; 3]>,
    pub simplices: Vec<[u32; 3]>,
    pub transform: Vec<[f64; 6]>,
    pub neighbors: Vec<[i32; 3]>,
    pub equations: Vec<[f64; 4]>,
    pub paraboloid_scale: f64,
    pub paraboloid_shift: f64,
    pub min_bound: [f64; 2],
    pub max_bound: [f64; 2],
}

impl ScipyDelaunay {
    pub fn new(p: DelaunayParts) -> Result<Self, MapError> {
        let n = p.samples.len();
        let m = p.simplices.len();
        if m == 0 {
            return Err(MapError::Invalid("Delaunay has no simplices".into()));
        }
        if p.transform.len() != m || p.neighbors.len() != m || p.equations.len() != m {
            return Err(MapError::Invalid(
                "transform/neighbors/equations length differs from simplices".into(),
            ));
        }
        if m > i32::MAX as usize {
            return Err(MapError::Budget("too many simplices".into()));
        }
        if let Some(i) = p
            .samples
            .iter()
            .position(|s| !s.iter().all(|v| v.is_finite()))
        {
            return Err(MapError::Invalid(format!("sample {i} is not finite")));
        }
        for (s, t) in p.simplices.iter().enumerate() {
            if t.iter().any(|v| *v as usize >= n) {
                return Err(MapError::Invalid(format!(
                    "simplex {s} vertex out of range"
                )));
            }
            if p.neighbors[s].iter().any(|v| *v < -1 || *v >= m as i32) {
                return Err(MapError::Invalid(format!(
                    "simplex {s} neighbor out of range"
                )));
            }
            if !p.equations[s].iter().all(|v| v.is_finite()) {
                return Err(MapError::Invalid(format!(
                    "simplex {s} equation not finite"
                )));
            }
        }
        let degenerate = p.transform.iter().filter(|t| t[0].is_nan()).count();
        for (s, t) in p.transform.iter().enumerate() {
            let nan = t.iter().filter(|v| v.is_nan()).count();
            if !(nan == 0 || nan == 6) || t.iter().any(|v| v.is_infinite()) {
                return Err(MapError::Invalid(format!(
                    "simplex {s} transform is partially NaN or infinite"
                )));
            }
        }
        if !(p.paraboloid_scale.is_finite() && p.paraboloid_shift.is_finite())
            || !p
                .min_bound
                .iter()
                .chain(p.max_bound.iter())
                .all(|v| v.is_finite())
        {
            return Err(MapError::Invalid("Delaunay scalars not finite".into()));
        }
        let xy = p.samples.iter().map(|s| [s[0], s[1]]).collect();
        let z = p.samples.iter().map(|s| s[2]).collect();
        Ok(Self {
            xy,
            z,
            simplices: p.simplices,
            transform: p.transform,
            neighbors: p.neighbors,
            equations: p.equations,
            paraboloid_scale: p.paraboloid_scale,
            paraboloid_shift: p.paraboloid_shift,
            min_bound: p.min_bound,
            max_bound: p.max_bound,
            degenerate,
            tree: None,
        })
    }

    pub fn nsimplex(&self) -> usize {
        self.simplices.len()
    }

    /// Builds the candidate index used by guarded mode (simplex envelopes with a margin).
    pub fn build_index(&mut self) {
        let envs = self
            .simplices
            .iter()
            .enumerate()
            .map(|(id, t)| {
                let p = t.map(|v| self.xy[v as usize]);
                let lo = [
                    p[0][0].min(p[1][0]).min(p[2][0]),
                    p[0][1].min(p[1][1]).min(p[2][1]),
                ];
                let hi = [
                    p[0][0].max(p[1][0]).max(p[2][0]),
                    p[0][1].max(p[1][1]).max(p[2][1]),
                ];
                // Generous margin: SciPy's eps test admits points marginally outside a simplex.
                let span = (hi[0] - lo[0]).max(hi[1] - lo[1]);
                let scale = lo[0]
                    .abs()
                    .max(lo[1].abs())
                    .max(hi[0].abs())
                    .max(hi[1].abs());
                let margin = span * 1e-9 + scale * 1e-12 + 1e-9;
                Env {
                    id: id as u32,
                    bounds: AABB::from_corners(
                        [lo[0] - margin, lo[1] - margin],
                        [hi[0] + margin, hi[1] + margin],
                    ),
                }
            })
            .collect();
        self.tree = Some(RTree::bulk_load(envs));
    }

    pub fn approx_bytes(&self) -> u64 {
        let m = self.simplices.len() as u64;
        let n = self.xy.len() as u64;
        n * 24 + m * (12 + 48 + 12 + 32) + if self.tree.is_some() { m * 72 } else { 0 }
    }

    #[inline]
    fn fully_outside(&self, x: [f64; 2]) -> bool {
        (0..2).any(|i| x[i] < self.min_bound[i] - EPS || x[i] > self.max_bound[i] + EPS)
    }

    /// `_barycentric_coordinate_single` for i < ndim.
    #[inline]
    fn coord(t: &[f64; 6], x: [f64; 2], i: usize) -> f64 {
        let mut c = 0.0;
        c += t[2 * i] * (x[0] - t[4]);
        c += t[2 * i + 1] * (x[1] - t[5]);
        c
    }

    /// `_barycentric_coordinates`.
    #[inline]
    fn coords(t: &[f64; 6], x: [f64; 2]) -> [f64; 3] {
        let c0 = Self::coord(t, x, 0);
        let c1 = Self::coord(t, x, 1);
        let mut c2 = 1.0;
        c2 -= c0;
        c2 -= c1;
        [c0, c1, c2]
    }

    #[inline]
    fn in_range(v: f64, lo: f64) -> bool {
        lo <= v && v <= 1.0 + EPS
    }

    /// `_barycentric_inside`.
    #[inline]
    fn inside(t: &[f64; 6], x: [f64; 2], c: &mut [f64; 3]) -> bool {
        c[2] = 1.0;
        for i in 0..2 {
            c[i] = Self::coord(t, x, i);
            c[2] -= c[i];
            if !Self::in_range(c[i], -EPS) {
                return false;
            }
        }
        Self::in_range(c[2], -EPS)
    }

    #[inline]
    fn value(&self, s: usize, c: &[f64; 3]) -> f64 {
        let v = self.simplices[s];
        let mut out = 0.0;
        for k in 0..3 {
            out += c[k] * self.z[v[k] as usize];
        }
        out
    }

    fn bruteforce(&self, c: &mut [f64; 3], x: [f64; 2], st: &mut WalkStats) -> i32 {
        st.bruteforce_calls += 1;
        if self.fully_outside(x) {
            return -1;
        }
        let eb = eps_broad();
        for s in 0..self.nsimplex() {
            let t = &self.transform[s];
            if !t[0].is_nan() {
                if Self::inside(t, x, c) {
                    return s as i32;
                }
            } else {
                for k in 0..3 {
                    let nb = self.neighbors[s][k];
                    if nb == -1 {
                        continue;
                    }
                    let tn = &self.transform[nb as usize];
                    if tn[0].is_nan() {
                        continue;
                    }
                    *c = Self::coords(tn, x);
                    let mut ok = true;
                    for (cm, nm) in c.iter().zip(self.neighbors[nb as usize]) {
                        let lo = if nm == s as i32 { -eb } else { -EPS };
                        if !Self::in_range(*cm, lo) {
                            ok = false;
                            break;
                        }
                    }
                    if ok {
                        return nb;
                    }
                }
            }
        }
        -1
    }

    fn directed(&self, c: &mut [f64; 3], x: [f64; 2], start: &mut i32, st: &mut WalkStats) -> i32 {
        let m = self.nsimplex() as i32;
        let mut s = *start;
        if s < 0 || s >= m {
            s = 0;
        }
        let cycles = 1 + self.nsimplex() / 4;
        let mut converged = false;
        for _ in 0..cycles {
            if s == -1 {
                converged = true;
                break;
            }
            st.directed_steps += 1;
            let t = &self.transform[s as usize];
            let mut inside = 1i32;
            for k in 0..3 {
                if k < 2 {
                    c[k] = Self::coord(t, x, k);
                } else {
                    c[2] = 1.0;
                    c[2] -= c[0];
                    c[2] -= c[1];
                }
                if c[k] < -EPS {
                    let nb = self.neighbors[s as usize][k];
                    if nb == -1 {
                        *start = s;
                        return -1;
                    }
                    s = nb;
                    inside = -1;
                    break;
                } else if c[k] <= 1.0 + EPS {
                } else {
                    inside = 0;
                }
            }
            if inside == -1 {
                continue;
            } else if inside == 1 {
                converged = true;
                break;
            } else {
                s = self.bruteforce(c, x, st);
                converged = true;
                break;
            }
        }
        if !converged {
            s = self.bruteforce(c, x, st);
        }
        *start = s;
        s
    }

    #[inline]
    fn distplane(&self, s: usize, z: &[f64; 3]) -> f64 {
        let e = &self.equations[s];
        let mut d = e[3];
        for k in 0..3 {
            d += e[k] * z[k];
        }
        d
    }

    /// `_find_simplex`, mutating the carried `start` exactly as SciPy does.
    pub fn find_simplex(
        &self,
        c: &mut [f64; 3],
        x: [f64; 2],
        start: &mut i32,
        st: &mut WalkStats,
    ) -> i32 {
        st.points += 1;
        if self.fully_outside(x) {
            st.outside_bbox += 1;
            return -1;
        }
        let m = self.nsimplex() as i32;
        let mut s = *start;
        if s < 0 || s >= m {
            s = 0;
        }
        let mut z = [x[0], x[1], 0.0];
        z[2] += x[0] * x[0];
        z[2] += x[1] * x[1];
        z[2] *= self.paraboloid_scale;
        z[2] += self.paraboloid_shift;
        let mut best = self.distplane(s as usize, &z);
        let mut changed = true;
        while changed {
            if best > 0.0 {
                break;
            }
            changed = false;
            for k in 0..3 {
                let nb = self.neighbors[s as usize][k];
                if nb == -1 {
                    continue;
                }
                let d = self.distplane(nb as usize, &z);
                if d > best + EPS * (1.0 + best.abs()) {
                    s = nb;
                    best = d;
                    changed = true;
                }
            }
        }
        *start = s;
        self.directed(c, x, start, st)
    }

    /// SciPy-exact serial evaluation over the full grid, in row-major order (start carried).
    /// `keep(row, col)` false sets the output to NaN but the walk still visits the point,
    /// because skipping points would change the carried start.
    pub fn evaluate_serial(
        &self,
        xs: &[f64],
        ys: &[f64],
        mut sink: impl FnMut(usize, usize, Option<(u32, f64)>),
    ) -> WalkStats {
        let mut st = WalkStats::default();
        let mut start = 0i32;
        let mut c = [0.0; 3];
        for (r, &y) in ys.iter().enumerate() {
            for (col, &x) in xs.iter().enumerate() {
                let s = self.find_simplex(&mut c, [x, y], &mut start, &mut st);
                if s < 0 {
                    sink(r, col, None);
                } else {
                    sink(r, col, Some((s as u32, self.value(s as usize, &c))));
                }
            }
        }
        st
    }

    /// Order-independent evaluation of one point (see module docs). Needs [`Self::build_index`].
    pub fn locate_guarded(&self, x: [f64; 2]) -> Located {
        if self.fully_outside(x) {
            return Located::Outside;
        }
        let tree = self
            .tree
            .as_ref()
            .expect("build_index before guarded evaluation");
        let mut first: Option<(u32, f64)> = None;
        let mut any = false;
        let mut strictly_inside = false;
        let mut differ = false;
        let mut c = [0.0; 3];
        for e in tree.locate_in_envelope_intersecting(AABB::from_point(x)) {
            let s = e.id as usize;
            let t = &self.transform[s];
            if Self::inside(t, x, &mut c) {
                any = true;
                if c.iter().all(|v| *v >= 0.0) {
                    strictly_inside = true;
                }
                let v = self.value(s, &c);
                match first {
                    None => first = Some((e.id, v)),
                    Some((id, fv)) => {
                        if fv.to_bits() != v.to_bits() {
                            differ = true;
                        }
                        if e.id < id {
                            first = Some((e.id, fv));
                        }
                    }
                }
            }
        }
        match (any, strictly_inside, differ) {
            (false, _, _) => Located::Outside,
            (true, true, false) => {
                let (s, v) = first.expect("candidate");
                Located::Value {
                    simplex: s,
                    value: v,
                }
            }
            _ => Located::Ambiguous,
        }
    }

    pub fn guarded_allowed(&self) -> bool {
        self.degenerate == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Unit square split on the diagonal; transforms as SciPy would give (origin = last vertex).
    fn square() -> ScipyDelaunay {
        let samples = vec![[0., 0., 0.], [1., 0., 1.], [0., 1., 1.], [1., 1., 2.]];
        // simplex 0: (1,3,2) last=2 (0,1): T = [[p1-p2],[p3-p2]]^T columns
        // Build inverse transforms numerically for the test.
        let simplices = vec![[1u32, 3, 2], [0u32, 1, 2]];
        let mut transform = Vec::new();
        for s in &simplices {
            let p = s.map(|v| samples[v as usize]);
            let r = [p[2][0], p[2][1]];
            let t = [
                [p[0][0] - r[0], p[1][0] - r[0]],
                [p[0][1] - r[1], p[1][1] - r[1]],
            ];
            let det = t[0][0] * t[1][1] - t[0][1] * t[1][0];
            transform.push([
                t[1][1] / det,
                -t[0][1] / det,
                -t[1][0] / det,
                t[0][0] / det,
                r[0],
                r[1],
            ]);
        }
        let mut d = ScipyDelaunay::new(DelaunayParts {
            samples,
            simplices,
            transform,
            neighbors: vec![[-1, 1, -1], [0, -1, -1]],
            equations: vec![[0., 0., -1., 1.], [0., 0., -1., 1.]],
            paraboloid_scale: 1.0,
            paraboloid_shift: 0.0,
            min_bound: [0., 0.],
            max_bound: [1., 1.],
        })
        .unwrap();
        d.build_index();
        d
    }

    #[test]
    fn plane_values_and_outside() {
        let d = square();
        let mut c = [0.0; 3];
        let mut start = 0;
        let mut st = WalkStats::default();
        let s = d.find_simplex(&mut c, [0.25, 0.25], &mut start, &mut st);
        assert_eq!(s, 1);
        assert_eq!(d.value(1, &c), 0.5);
        assert_eq!(d.find_simplex(&mut c, [2.0, 2.0], &mut start, &mut st), -1);
        match d.locate_guarded([0.75, 0.75]) {
            Located::Value { simplex, value } => {
                assert_eq!(simplex, 0);
                assert!((value - 1.5).abs() < 1e-15);
            }
            other => panic!("{other:?}"),
        }
        assert_eq!(d.locate_guarded([3.0, 0.5]), Located::Outside);
    }

    #[test]
    fn serial_and_guarded_agree_on_grid() {
        let d = square();
        let xs: Vec<f64> = (0..11).map(|i| i as f64 / 10.0).collect();
        let mut serial = vec![f64::NAN; 121];
        d.evaluate_serial(&xs, &xs, |r, c, v| {
            serial[r * 11 + c] = v.map_or(f64::NAN, |(_, z)| z)
        });
        for r in 0..11 {
            for c in 0..11 {
                if let Located::Value { value, .. } = d.locate_guarded([xs[c], xs[r]]) {
                    assert_eq!(value.to_bits(), serial[r * 11 + c].to_bits());
                }
            }
        }
    }

    #[test]
    fn rejects_bad_inputs() {
        let base = || DelaunayParts {
            samples: vec![[0., 0., 0.], [1., 0., 1.], [0., 1., 1.]],
            simplices: vec![[0, 1, 2]],
            transform: vec![[1., 0., 0., 1., 0., 1.]],
            neighbors: vec![[-1, -1, -1]],
            equations: vec![[0., 0., -1., 1.]],
            paraboloid_scale: 1.0,
            paraboloid_shift: 0.0,
            min_bound: [0., 0.],
            max_bound: [1., 1.],
        };
        let mut p = base();
        p.simplices = vec![[0, 1, 3]];
        assert!(ScipyDelaunay::new(p).is_err());
        let mut p = base();
        p.neighbors = vec![[5, -1, -1]];
        assert!(ScipyDelaunay::new(p).is_err());
        let mut p = base();
        p.transform = vec![[f64::NAN, 0., 0., 1., 0., 1.]];
        assert!(ScipyDelaunay::new(p).is_err());
        let mut p = base();
        p.transform = vec![[f64::NAN; 6]];
        assert_eq!(ScipyDelaunay::new(p).unwrap().degenerate, 1);
    }
}
