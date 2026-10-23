//! Prepared multi-profile / multi-AOI session.
//!
//! Execution model:
//! 1. Profiles are processed in batches of `max_inflight_profiles`. Each batch is loaded and
//!    prepared (interpolator from supplied global simplices) in the single session pool.
//! 2. AOIs resolve to pixel windows on each profile's own grid. Work items are grid tiles of
//!    `output_tile` pixels anchored at grid pixel (0, 0); a tile is evaluated once for the union
//!    of AOI windows and every AOI receives its sub-rectangle. AOI output therefore equals the
//!    crop of the full-grid output by construction.
//! 3. Native terrain blocks are shared through one byte-bounded cache across all profiles,
//!    batches and AOIs of the session. Items are ordered by terrain-block locality.
//! 4. At most `max_tiles_in_flight` evaluated tiles are alive between the pool and the sink
//!    (`max_tiles_in_flight == 1` runs a serial evaluate-then-write branch).
//! 5. Admission: per-profile load+prepare estimates come from request content and file lengths
//!    before anything is read; plan sizes are bounded before plans are allocated; the report's
//!    `memory_estimate` separates enforced bounds, estimates and unaccounted allocations.
//! 6. Failure safety: errors and caught panics after the output directory exists fail every
//!    open unit and still write an `aborted` report (best effort; see `run`).
use crate::interp::PreparedInterpolator;
use crate::model::{
    AoiSpec, ErrorPolicy, GridSpec, MaskData, Product, ProfileEstimate, ProfileSpec,
    QueryConvention, SessionRequest, TerrainSpec, resolve,
};
use crate::sink::{DirSink, Rect, TileOut, write_json};
use crate::terrain::{Hit, NativeTerrain};
use crate::{MapError, method_record};
use rayon::prelude::*;
use serde::Serialize;
use std::collections::BTreeSet;
use std::panic::{AssertUnwindSafe, catch_unwind};
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

#[derive(Clone, Debug, PartialEq)]
pub enum Grid {
    Explicit {
        width: usize,
        height: usize,
        x0: f64,
        y0: f64,
        dx: f64,
        dy: f64,
    },
    Aligned {
        width: usize,
        height: usize,
        col0: usize,
        row0: usize,
        gt: [f64; 6],
    },
}

impl Grid {
    pub fn dims(&self) -> (usize, usize) {
        match *self {
            Grid::Explicit { width, height, .. } | Grid::Aligned { width, height, .. } => {
                (width, height)
            }
        }
    }

    /// Interpolation query point of pixel (row, col).
    #[inline]
    pub fn query(&self, row: usize, col: usize) -> [f64; 2] {
        match *self {
            Grid::Explicit { x0, y0, dx, dy, .. } => [x0 + col as f64 * dx, y0 + row as f64 * dy],
            Grid::Aligned { col0, row0, gt, .. } => [
                gt[0] + ((col0 + col) as f64 + 0.5) * gt[1],
                gt[3] + ((row0 + row) as f64 + 0.5) * gt[5],
            ],
        }
    }

    /// Pixel-center coordinate along x (col) or y (row); used for bounds selection.
    #[inline]
    fn center_x(&self, col: usize) -> f64 {
        match *self {
            Grid::Explicit { x0, dx, .. } => x0 + (col as f64 + 0.5) * dx,
            Grid::Aligned { col0, gt, .. } => gt[0] + ((col0 + col) as f64 + 0.5) * gt[1],
        }
    }
    #[inline]
    fn center_y(&self, row: usize) -> f64 {
        match *self {
            Grid::Explicit { y0, dy, .. } => y0 + (row as f64 + 0.5) * dy,
            Grid::Aligned { row0, gt, .. } => gt[3] + ((row0 + row) as f64 + 0.5) * gt[5],
        }
    }

    /// Terrain sample point for an explicit grid under the session convention.
    #[inline]
    fn terrain_point(&self, row: usize, col: usize, q: QueryConvention) -> [f64; 2] {
        match q {
            QueryConvention::QueryPoint => self.query(row, col),
            QueryConvention::PixelCenter => [self.center_x(col), self.center_y(row)],
        }
    }

    pub fn spec_json(&self) -> serde_json::Value {
        match *self {
            Grid::Explicit {
                width,
                height,
                x0,
                y0,
                dx,
                dy,
            } => serde_json::json!({
                "kind": "explicit", "width": width, "height": height, "x0": x0, "y0": y0, "dx": dx, "dy": dy}),
            Grid::Aligned {
                width,
                height,
                col0,
                row0,
                gt,
            } => serde_json::json!({
                "kind": "terrain_aligned", "width": width, "height": height, "col": col0, "row": row0,
                "terrain_geo_transform": gt}),
        }
    }
}

/// Half-open selection of indices whose monotone center lies in [lo, hi).
fn select_axis(n: usize, center: impl Fn(usize) -> f64, lo: f64, hi: f64) -> (usize, usize) {
    if n == 0 {
        return (0, 0);
    }
    let increasing = center(n - 1) >= center(0);
    let pp = |pred: &dyn Fn(usize) -> bool| -> usize {
        let (mut a, mut b) = (0usize, n);
        while a < b {
            let m = a + (b - a) / 2;
            if pred(m) { a = m + 1 } else { b = m }
        }
        a
    };
    if increasing {
        (pp(&|i| center(i) < lo), pp(&|i| center(i) < hi))
    } else {
        (pp(&|i| center(i) >= hi), pp(&|i| center(i) >= lo))
    }
}

pub fn aoi_window(aoi: &AoiSpec, grid: &Grid) -> Option<Rect> {
    let (w, h) = grid.dims();
    let full = Rect {
        col: 0,
        row: 0,
        width: w,
        height: h,
    };
    if let Some(win) = aoi.window {
        if win[0] >= w as u64 || win[1] >= h as u64 {
            return None;
        }
        let cw = win[2].min(w as u64 - win[0]) as usize;
        let ch = win[3].min(h as u64 - win[1]) as usize;
        return Some(Rect {
            col: win[0] as usize,
            row: win[1] as usize,
            width: cw,
            height: ch,
        });
    }
    if let Some(b) = aoi.bounds {
        let (c0, c1) = select_axis(w, |c| grid.center_x(c), b[0], b[2]);
        let (r0, r1) = select_axis(h, |r| grid.center_y(r), b[1], b[3]);
        return (c0 < c1 && r0 < r1).then(|| Rect {
            col: c0,
            row: r0,
            width: c1 - c0,
            height: r1 - r0,
        });
    }
    Some(full)
}

pub struct Prepared {
    pub slot: usize,
    pub id: String,
    pub grid: Grid,
    pub interp: PreparedInterpolator,
    pub mask: MaskData,
    pub terrain: Option<Vec<f64>>,
    pub bytes: u64,
    pub report: ProfileReport,
}

#[derive(Serialize, Clone, Debug, Default)]
pub struct ProfileReport {
    pub id: String,
    pub status: String,
    pub error: Option<serde_json::Value>,
    pub batch: usize,
    pub load_seconds: f64,
    pub prepare_seconds: f64,
    pub samples: usize,
    pub simplices_supplied: usize,
    pub triangles_valid: usize,
    pub degenerate_simplices_skipped: usize,
    pub prepared_bytes: u64,
    pub source_bytes: u64,
    pub grid_pixels: u64,
    pub legacy_terrain_ignored: bool,
    pub tiles_evaluated: u64,
    pub pixels_evaluated: u64,
    pub masked_pixels: u64,
    pub raw_valid_pixels: u64,
    pub wet_pixels: u64,
    pub terrain_dry_pixels: u64,
    pub terrain_raw_sentinel_pixels: u64,
    pub terrain_near_boundary_samples: u64,
    pub eval_seconds: f64,
    pub max_terrain_blocks_per_tile: usize,
    /// Pre-read load + prepare estimate (bytes) checked against `max_profile_bytes`.
    pub load_peak_estimate_bytes: u64,
    pub estimate_basis: String,
}

fn mask_at(m: &MaskData, i: usize) -> bool {
    match m {
        MaskData::AllWet => true,
        MaskData::Bits(b) => b[i],
    }
}

fn prepare(
    slot: usize,
    spec: &ProfileSpec,
    base: &Path,
    terrain: Option<&NativeTerrain>,
    max_bytes: u64,
) -> Result<Prepared, MapError> {
    let t0 = Instant::now();
    let data = spec.source.load(base, terrain.is_some())?;
    let load_seconds = t0.elapsed().as_secs_f64();
    let t1 = Instant::now();
    let n = data.grid.pixels()? as usize;
    let grid = match data.grid {
        GridSpec::Explicit {
            width,
            height,
            x0,
            y0,
            dx,
            dy,
        } => {
            if ![x0, y0, dx, dy].iter().all(|v| v.is_finite()) || dx == 0.0 || dy == 0.0 {
                return Err(MapError::Invalid(
                    "grid origin/spacing must be finite, spacing nonzero".into(),
                ));
            }
            let ends = [
                x0 + (width as f64 + 0.5) * dx,
                y0 + (height as f64 + 0.5) * dy,
            ];
            if !ends.iter().all(|v| v.is_finite()) {
                return Err(MapError::Invalid("grid extent overflows".into()));
            }
            Grid::Explicit {
                width,
                height,
                x0,
                y0,
                dx,
                dy,
            }
        }
        GridSpec::TerrainAligned {
            col,
            row,
            width,
            height,
        } => {
            let t = terrain.ok_or_else(|| {
                MapError::Unsupported("terrain_aligned grid requires native_geotiff terrain".into())
            })?;
            if col.checked_add(width).is_none_or(|e| e > t.width)
                || row.checked_add(height).is_none_or(|e| e > t.height)
            {
                return Err(MapError::Invalid(
                    "terrain_aligned window exceeds terrain extent".into(),
                ));
            }
            Grid::Aligned {
                width,
                height,
                col0: col,
                row0: row,
                gt: t.gt,
            }
        }
    };
    if let MaskData::Bits(b) = &data.mask
        && b.len() != n
    {
        return Err(MapError::Invalid(format!(
            "mask has {} values, grid has {n}",
            b.len()
        )));
    }
    match (&data.terrain, terrain.is_some()) {
        (Some(t), false) => {
            if t.len() != n {
                return Err(MapError::Invalid(format!(
                    "terrain buffer has {} values, grid has {n}",
                    t.len()
                )));
            }
            if t.iter().any(|v| v.is_infinite()) {
                return Err(MapError::Invalid(
                    "terrain buffer contains infinite values".into(),
                ));
            }
        }
        (None, false) => {
            return Err(MapError::Invalid(
                "caller_buffer terrain mode requires a per-profile terrain buffer".into(),
            ));
        }
        (Some(_), true) => {
            return Err(MapError::Invalid(
                "native terrain mode forbids a caller terrain buffer (ambiguous source)".into(),
            ));
        }
        (None, true) => {}
    }
    let interp = PreparedInterpolator::new(&data.samples, &data.simplices)?;
    let any_wet = match &data.mask {
        MaskData::AllWet => true,
        MaskData::Bits(b) => b.iter().any(|v| *v),
    };
    if any_wet && interp.triangles_valid == 0 {
        return Err(MapError::Invalid(
            "wet mask but no numerically valid supplied simplices".into(),
        ));
    }
    let mask_bytes = match &data.mask {
        MaskData::AllWet => 0,
        MaskData::Bits(b) => b.len() as u64,
    };
    let bytes = interp.approx_bytes()
        + mask_bytes
        + data.terrain.as_ref().map_or(0, |t| t.len() as u64 * 8);
    if bytes > max_bytes {
        return Err(MapError::Budget(format!(
            "prepared profile needs {bytes} bytes > max_profile_bytes {max_bytes}"
        )));
    }
    let report = ProfileReport {
        id: spec.id.clone(),
        status: "prepared".into(),
        load_seconds,
        prepare_seconds: t1.elapsed().as_secs_f64(),
        samples: interp.samples,
        simplices_supplied: interp.simplices_supplied,
        triangles_valid: interp.triangles_valid,
        degenerate_simplices_skipped: interp.degenerate_skipped,
        prepared_bytes: bytes,
        source_bytes: data.source_bytes,
        grid_pixels: n as u64,
        legacy_terrain_ignored: data.legacy_terrain_ignored,
        ..Default::default()
    };
    Ok(Prepared {
        slot,
        id: spec.id.clone(),
        grid,
        interp,
        mask: data.mask,
        terrain: data.terrain,
        bytes,
        report,
    })
}

struct Item {
    slot: usize,
    tile: (usize, usize),
    rect: Rect,
    needs_terrain: bool,
    /// Terrain block ranges [bx0, bx1) x [by0, by1).
    blocks: Option<(usize, usize, usize, usize)>,
}

type Evaluated = Vec<(usize, Result<(TileOut, ItemStats), MapError>)>;

#[derive(Default)]
struct ItemStats {
    masked: u64,
    raw_valid: u64,
    wet: u64,
    terrain_dry: u64,
    sentinel: u64,
    near_boundary: u64,
    seconds: f64,
}

impl ItemStats {
    fn add(&mut self, o: &ItemStats) {
        self.masked += o.masked;
        self.raw_valid += o.raw_valid;
        self.wet += o.wet;
        self.terrain_dry += o.terrain_dry;
        self.sentinel += o.sentinel;
        self.near_boundary += o.near_boundary;
        self.seconds += o.seconds;
    }
}

fn plan_blocks(
    p: &Prepared,
    rect: &Rect,
    t: &NativeTerrain,
) -> Option<(usize, usize, usize, usize)> {
    let (c_lo, c_hi, r_lo, r_hi) = match p.grid {
        Grid::Aligned { col0, row0, .. } => (
            (col0 + rect.col) as f64,
            (col0 + rect.col + rect.width - 1) as f64,
            (row0 + rect.row) as f64,
            (row0 + rect.row + rect.height - 1) as f64,
        ),
        Grid::Explicit { .. } => {
            // Sample coordinates are monotone in row/col, so corner floors bound every pixel.
            let mut cs = Vec::with_capacity(4);
            let mut rs = Vec::with_capacity(4);
            for (r, c) in [
                (rect.row, rect.col),
                (rect.row, rect.col + rect.width - 1),
                (rect.row + rect.height - 1, rect.col),
                (rect.row + rect.height - 1, rect.col + rect.width - 1),
            ] {
                let [x, y] = p.grid.terrain_point(r, c, t.query);
                let (fc, fr) = t.floor_index(x, y)?;
                cs.push(fc);
                rs.push(fr);
            }
            let f = |v: &[f64]| {
                (
                    v.iter().cloned().fold(f64::INFINITY, f64::min),
                    v.iter().cloned().fold(f64::NEG_INFINITY, f64::max),
                )
            };
            let (c_lo, c_hi) = f(&cs);
            let (r_lo, r_hi) = f(&rs);
            (c_lo, c_hi, r_lo, r_hi)
        }
    };
    let (w, h) = (t.width as f64, t.height as f64);
    if c_hi < 0.0 || r_hi < 0.0 || c_lo >= w || r_lo >= h {
        return None;
    }
    let c0 = c_lo.max(0.0) as usize;
    let c1 = c_hi.min(w - 1.0) as usize;
    let r0 = r_lo.max(0.0) as usize;
    let r1 = r_hi.min(h - 1.0) as usize;
    Some((
        c0 / t.block.0,
        c1 / t.block.0 + 1,
        r0 / t.block.1,
        r1 / t.block.1 + 1,
    ))
}

fn evaluate(
    item: &Item,
    p: &Prepared,
    terrain: Option<&NativeTerrain>,
    want_ground: bool,
) -> Result<(TileOut, ItemStats), MapError> {
    let start = Instant::now();
    let rect = item.rect;
    let n = rect.pixels();
    let mut out = TileOut {
        profile: item.slot,
        tile: item.tile,
        rect,
        raw_wse: vec![f64::NAN; n],
        wse: vec![f64::NAN; n],
        depth: vec![f64::NAN; n],
        ground: vec![f64::NAN; n],
        simplex_id: vec![-1; n],
    };
    let mut st = ItemStats::default();
    // Acquire (pin) the tile's terrain blocks once; the cache shares them across items.
    let (blocks, bx0, by0, nbx) = match (terrain, item.blocks, item.needs_terrain) {
        (Some(t), Some((bx0, bx1, by0, by1)), true) => {
            let mut v = Vec::with_capacity((bx1 - bx0) * (by1 - by0));
            for by in by0..by1 {
                for bx in bx0..bx1 {
                    v.push(t.get_block(bx, by)?);
                }
            }
            (v, bx0, by0, bx1 - bx0)
        }
        _ => (Vec::new(), 0, 0, 0),
    };
    let (gw, _) = p.grid.dims();
    for r in 0..rect.height {
        let gr = rect.row + r;
        for c in 0..rect.width {
            let gc = rect.col + c;
            let gi = gr * gw + gc;
            let o = r * rect.width + c;
            let masked = mask_at(&p.mask, gi);
            if !masked && !want_ground {
                continue;
            }
            let ground = match terrain {
                None => p.terrain.as_ref().map(|b| b[gi]).filter(|v| !v.is_nan()),
                Some(t) => {
                    let hit = match p.grid {
                        Grid::Aligned { col0, row0, .. } => Hit::Pixel {
                            col: col0 + gc,
                            row: row0 + gr,
                            near_boundary: false,
                        },
                        Grid::Explicit { .. } => {
                            let [x, y] = p.grid.terrain_point(gr, gc, t.query);
                            t.hit(x, y)
                        }
                    };
                    match hit {
                        Hit::Outside => None,
                        Hit::Pixel {
                            col,
                            row,
                            near_boundary,
                        } => {
                            st.near_boundary += (masked && near_boundary) as u64;
                            let (bx, by) = (col / t.block.0, row / t.block.1);
                            let k = (by - by0) * nbx + (bx - bx0);
                            let block = &blocks[k];
                            let bw = t.block.0.min(t.width - bx * t.block.0);
                            let v = block[(row - by * t.block.1) * bw + (col - bx * t.block.0)];
                            st.sentinel += (masked && t.is_sentinel(v)) as u64;
                            let g = t.classify(v);
                            if g.is_some_and(f64::is_infinite) {
                                // Same policy as caller buffers: infinite terrain is rejected.
                                return Err(MapError::Terrain(format!(
                                    "{}: infinite terrain value {v} at pixel (col {col}, row {row})",
                                    t.path
                                )));
                            }
                            g
                        }
                    }
                }
            };
            if want_ground {
                out.ground[o] = ground.unwrap_or(f64::NAN);
            }
            if !masked {
                continue;
            }
            st.masked += 1;
            // Interpolation and terrain subtraction: baseline kernel semantics.
            if let Some((id, z)) = p.interp.locate(p.grid.query(gr, gc)) {
                out.raw_wse[o] = z;
                out.simplex_id[o] = id as i64;
                st.raw_valid += 1;
                match ground {
                    Some(g) => {
                        let d = z - g;
                        if d >= 0.0 {
                            out.wse[o] = z;
                            out.depth[o] = d;
                            st.wet += 1;
                        }
                    }
                    None => st.terrain_dry += 1,
                }
            }
        }
    }
    st.seconds = start.elapsed().as_secs_f64();
    Ok((out, st))
}

fn unit_header(
    req: &SessionRequest,
    p: &Prepared,
    aoi: &AoiSpec,
    window: Option<Rect>,
    products: &[Product],
) -> serde_json::Value {
    let mut prods: Vec<_> = products.to_vec();
    prods.sort();
    serde_json::json!({
        "schema": "ras2fim-batch-unit/1",
        "method_version": crate::METHOD_VERSION,
        "profile": p.id,
        "aoi": aoi.id,
        "aoi_spec": aoi,
        "crs_epsg": req.crs_epsg,
        "profile_grid": p.grid.spec_json(),
        "window": window,
        "products": prods.iter().map(|p| serde_json::json!({"name": p.name(), "file": format!("{}.bin", p.name()), "dtype": p.dtype(), "nodata": if *p == Product::SimplexId {serde_json::json!(-1)} else {serde_json::json!("NaN")}})).collect::<Vec<_>>(),
        "layout": "row-major over window, grid row order (row index increases with y0 + row*dy for explicit grids)",
        "terrain": match &req.terrain { TerrainSpec::CallerBuffer => serde_json::json!("caller_buffer"), t => serde_json::to_value(t).unwrap_or_default() },
    })
}

/// Work items above this count in one profile plan are rejected before the plan is allocated
/// (raise `output_tile`). Bounds plan metadata: items, tile set and per-unit tile records.
pub const MAX_PLAN_TILES_PER_PROFILE: u64 = 1 << 22;
/// Estimated bytes per planned work item (item, tile-set entry and evaluated result slot).
const PLAN_BYTES_PER_ITEM: u64 = std::mem::size_of::<Item>() as u64 + 48 + 16;

/// Tiles of edge `t` (anchored at grid 0,0) that intersect `w`.
fn tiles_in(w: &Rect, t: usize) -> u64 {
    let rows = (w.row + w.height - 1) / t - w.row / t + 1;
    let cols = (w.col + w.width - 1) / t - w.col / t + 1;
    rows as u64 * cols as u64
}

/// Session-wide accounted memory terms (bytes) that do not depend on the batch.
#[derive(Serialize, Clone, Debug, Default)]
struct StaticTerms {
    /// Enforced: decoded resident terrain tiles (`max_cache_bytes`; 0 for caller buffers).
    cache_resident_bound: u64,
    /// Estimate, not enforced: `threads x decoder_transient_bytes_per_load` (native terrain).
    decoder_transient_estimate: u64,
    /// Enforced by construction: evaluated tile buffers alive at once.
    output_tile_buffers_bound: u64,
    /// Exact: inline profile payloads held by the parsed request.
    request_inline_payload: u64,
}

impl StaticTerms {
    fn total(&self) -> u64 {
        self.cache_resident_bound
            .saturating_add(self.decoder_transient_estimate)
            .saturating_add(self.output_tile_buffers_bound)
            .saturating_add(self.request_inline_payload)
    }
}

/// Per-run mutable state. Owned outside the inner run so the abort path can read it after an
/// error or a caught panic.
#[derive(Default)]
struct RunState {
    sink: Option<DirSink>,
    reports: Vec<ProfileReport>,
    terrain: Option<Arc<NativeTerrain>>,
    statics: StaticTerms,
    batches: Vec<serde_json::Value>,
    prepare_wall: f64,
    eval_wall: f64,
    sink_seconds: f64,
    items_total: u64,
    peak_tiles_in_flight: usize,
    max_blocks_any: usize,
}

fn err_json(stage: &str, e: &MapError) -> serde_json::Value {
    serde_json::json!({"stage": stage, "kind": e.kind(), "message": e.to_string()})
}

/// Writes a `failed` unit.json for every AOI of a profile that never opened units.
fn write_failed_units(
    sink: &DirSink,
    req: &SessionRequest,
    s: usize,
    stage: &str,
    e: &MapError,
) -> Result<(), MapError> {
    for a in &req.aois {
        let dir = sink.unit_dir(&req.profiles[s].id, &a.id);
        std::fs::create_dir_all(&dir)?;
        write_json(
            &dir.join("unit.json"),
            &serde_json::json!({
            "schema": "ras2fim-batch-unit/1", "profile": req.profiles[s].id, "aoi": a.id,
            "status": "failed", "error": err_json(stage, e)}),
        )?;
    }
    Ok(())
}

/// Peak accounted bytes of loading a set of profiles together in a pool of `threads` workers:
/// all residents plus the `threads` largest load transients.
fn batch_load_peak(est: &[&ProfileEstimate], threads: usize) -> u64 {
    let mut tr: Vec<u64> = est.iter().map(|e| e.transient_bytes).collect();
    tr.sort_unstable_by(|a, b| b.cmp(a));
    let resident: u64 = est.iter().map(|e| e.resident_bytes).sum();
    resident.saturating_add(tr.iter().take(threads).sum())
}

/// Profiles per batch: chunks of `max_inflight_profiles` (r1 behaviour) or, with
/// `max_session_bytes`, greedy packing so each batch's accounted load peak fits the allowance.
/// Profiles whose estimate failed or cannot fit alone ride along at zero cost and fail at
/// preflight.
fn plan_batches(
    req: &SessionRequest,
    est: &[Result<ProfileEstimate, MapError>],
    allowance: Option<u64>,
) -> Vec<Vec<usize>> {
    let b = &req.budgets;
    let Some(allow) = allowance else {
        let slots: Vec<usize> = (0..req.profiles.len()).collect();
        return slots
            .chunks(b.max_inflight_profiles)
            .map(<[usize]>::to_vec)
            .collect();
    };
    let mut out: Vec<Vec<usize>> = Vec::new();
    let mut cur: Vec<usize> = Vec::new();
    for (s, e) in est.iter().enumerate() {
        let fits_alone = e.as_ref().is_ok_and(|e| {
            e.peak_bytes() <= b.max_profile_bytes && batch_load_peak(&[e], b.threads) <= allow
        });
        if fits_alone {
            let mut members: Vec<&ProfileEstimate> =
                cur.iter().filter_map(|&k| est[k].as_ref().ok()).collect();
            members.push(e.as_ref().expect("fits_alone implies Ok"));
            if cur.len() >= b.max_inflight_profiles || batch_load_peak(&members, b.threads) > allow
            {
                out.push(std::mem::take(&mut cur));
            }
        } else if cur.len() >= b.max_inflight_profiles {
            out.push(std::mem::take(&mut cur));
        }
        cur.push(s);
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// Runs a session and writes outputs plus `report.json` into the new directory `out`.
///
/// Failure contract: once `out` has been created by this call, every exit — error or caught
/// panic — fails each open unit (data removed, `unit.json` `failed`) and writes `report.json`
/// with `status: "aborted"` and the error, best effort. If even that is impossible (e.g. the
/// disk is full) the reason is printed to stderr and the in-progress markers / `.partial` names
/// stay as explicit evidence. The error is still returned.
pub fn run(req: &SessionRequest, base: &Path, out: &Path) -> Result<serde_json::Value, MapError> {
    let started = Instant::now();
    req.validate()?;
    let existed = out.exists();
    let mut st = RunState {
        reports: req
            .profiles
            .iter()
            .map(|p| ProfileReport {
                id: p.id.clone(),
                status: "not_started".into(),
                ..Default::default()
            })
            .collect(),
        ..Default::default()
    };
    let result = catch_unwind(AssertUnwindSafe(|| {
        run_inner(req, base, out, &mut st, started)
    }));
    let err = match result {
        Ok(Ok(report)) => return Ok(report),
        Ok(Err(e)) => e,
        Err(p) => MapError::Internal(format!(
            "session panicked: {}",
            p.downcast_ref::<&str>()
                .map(|s| s.to_string())
                .or_else(|| p.downcast_ref::<String>().cloned())
                .unwrap_or_else(|| "non-string panic payload".into())
        )),
    };
    // Only write into a directory this call created.
    if !existed && out.is_dir() {
        let problems = st
            .sink
            .as_mut()
            .map(|s| s.abort_all(&err))
            .unwrap_or_default();
        for r in st.reports.iter_mut() {
            if r.status != "complete" && r.status != "failed" {
                r.status = "aborted".into();
                r.error = Some(err_json("session", &err));
            }
        }
        let written = build_report(req, &st, "aborted", started).and_then(|mut rep| {
            rep["error"] = err_json("session", &err);
            rep["cleanup_problems"] = problems.clone().into();
            write_json(&out.join("report.json"), &rep)
        });
        if let Err(w) = written {
            eprintln!(
                "session error: {err}; report.json could NOT be written ({w}); units still marked in_progress (if any) are not valid outputs"
            );
        }
        if !problems.is_empty() {
            eprintln!("cleanup problems: {}", problems.join("; "));
        }
    }
    Err(err)
}

fn build_report(
    req: &SessionRequest,
    st: &RunState,
    status: &str,
    started: Instant,
) -> Result<serde_json::Value, MapError> {
    let b = &req.budgets;
    let pipelined = b.max_tiles_in_flight > 1;
    let peak_batch = st
        .batches
        .iter()
        .filter_map(|v| v["accounted_peak_estimate_bytes"].as_u64())
        .max()
        .unwrap_or(0);
    let tstats = st.terrain.as_ref().map(|t| t.stats());
    Ok(serde_json::json!({
        "schema": "ras2fim-batch-report/1",
        "method": method_record(),
        "status": status,
        "crs_epsg": req.crs_epsg,
        "terrain_spec": req.terrain,
        "terrain": st.terrain.as_ref().map(|t| serde_json::json!({
            "path": t.path, "geo_transform": t.gt, "width": t.width, "height": t.height,
            "block": t.block, "blocks": t.blocks(), "nodata": t.nodata, "epsg": t.epsg,
            "nodata_f32_exact": crate::terrain::nodata_f32_exact(t.nodata),
            "crs_identity": t.crs_identity, "crs_wkt_fnv1a64": t.crs_wkt_fnv1a64,
            "decode_policy": "one TIFF block per terrio read_window call (serial decode on the calling worker)",
            "stats": tstats,
        })),
        "budgets": b,
        "output_buffer_bound_bytes": req.output_buffer_bound()?,
        "products": req.products,
        "aois": req.aois,
        "error_policy": req.error_policy,
        "profiles": st.reports,
        "counters": {
            "profiles": req.profiles.len(),
            "aois": req.aois.len(),
            "work_items": st.items_total,
            "tiles_written": st.sink.as_ref().map_or(0, |s| s.tiles_written),
            "output_bytes": st.sink.as_ref().map_or(0, |s| s.bytes_written),
            "unit_files_written": st.sink.as_ref().map_or(0, |s| s.unit_files_written),
            "peak_tiles_in_flight": st.peak_tiles_in_flight,
            "effective_tiles_in_flight_limit": req.effective_tiles_in_flight(),
            "max_terrain_blocks_per_tile": st.max_blocks_any,
            "dir_fsync_unsupported": st.sink.as_ref().map_or(0, |s| s.dir_sync_unsupported),
        },
        "contract_version": crate::CONTRACT_VERSION,
        "cpu_threads": {
            "pool_workers": b.threads,
            "pipelined": pipelined,
            "cpu_active_max": b.threads + pipelined as usize,
            "note": "in the pipelined branch the calling thread writes outputs and hashes while the pool evaluates, so up to threads + 1 threads are CPU-active; `threads` is the evaluation pool size, not a total CPU budget",
        },
        "memory_estimate": {
            "is_hard_bound": false,
            "summary": "admission estimate over accounted terms; the decoded terrain cache and evaluated tile buffers are enforced bounds, the rest are estimates; unaccounted allocations remain",
            "static_terms_bytes": st.statics,
            "static_total_bytes": st.statics.total(),
            "batches": st.batches,
            "accounted_peak_estimate_bytes": peak_batch,
            "max_session_bytes": b.max_session_bytes,
            "measured": {
                "cache_peak_resident_bytes": tstats.as_ref().map(|s| s.cache.peak_bytes),
                "decoder_transient_peak_estimate_bytes": tstats.as_ref().map(|s| s.decoder_transient_peak_estimate_bytes),
                "peak_tile_buffer_bytes": (st.peak_tiles_in_flight as u64) * (b.output_tile as u64).pow(2) * 40,
            },
            "unaccounted": [
                "allocator fragmentation / RSS retained after frees",
                "thread stacks (threads + 2 OS threads)",
                "terrio readers, TIFF directory state, file buffers and codec (flate/zstd/lzw) internal state",
                "R-tree node overhead beyond the 48 B/simplex estimate and bulk-load working memory beyond one triangle-vector copy",
                "serde/JSON transients for the request, unit headers and this report",
                "legacy_request JSON parse (heuristic 64 x file length; not a proof)",
                "OS page cache"
            ],
        },
        "timings": {
            "total_wall_seconds": started.elapsed().as_secs_f64(),
            "prepare_wall_seconds": st.prepare_wall,
            "evaluate_and_sink_wall_seconds": st.eval_wall,
            "sink_seconds": st.sink_seconds,
        },
    }))
}

/// Writes evaluated tiles of one chunk; returns (first sink error, seconds).
#[allow(clippy::too_many_arguments)]
fn write_chunk(
    to_write: Option<Evaluated>,
    items: &[Item],
    failed: &mut [Option<MapError>],
    acc: &mut [(u64, u64, ItemStats)],
    sink: &mut DirSink,
    aoi_count: usize,
) -> (Result<(), MapError>, f64) {
    let ts = Instant::now();
    let mut wr: Result<(), MapError> = Ok(());
    for (k, res) in to_write.into_iter().flatten() {
        let it = &items[k];
        match res {
            Ok((tile, st)) => {
                if failed[it.slot].is_some() {
                    continue;
                }
                let a = &mut acc[it.slot];
                a.0 += 1;
                a.1 += it.rect.pixels() as u64;
                a.2.add(&st);
                if let Err(e) = sink.write_tile(&tile, aoi_count) {
                    wr = Err(e);
                    break;
                }
            }
            Err(e) => {
                if failed[it.slot].is_none() {
                    failed[it.slot] = Some(e);
                }
            }
        }
    }
    (wr, ts.elapsed().as_secs_f64())
}

fn run_inner(
    req: &SessionRequest,
    base: &Path,
    out: &Path,
    st: &mut RunState,
    started: Instant,
) -> Result<serde_json::Value, MapError> {
    let b = &req.budgets;
    let terrain: Option<Arc<NativeTerrain>> = match &req.terrain {
        TerrainSpec::CallerBuffer => None,
        TerrainSpec::NativeGeotiff {
            path,
            query,
            nodata_policy,
            crs_identity,
        } => {
            let p = resolve(base, path);
            let p = p
                .to_str()
                .ok_or_else(|| MapError::Invalid("terrain path is not UTF-8".into()))?;
            Some(Arc::new(NativeTerrain::open(
                p,
                req.crs_epsg,
                crs_identity,
                *query,
                *nodata_policy,
                b.max_cache_bytes,
            )?))
        }
    };
    st.terrain = terrain.clone();
    // Pre-read admission: accounted session terms and per-profile estimates from metadata only.
    st.statics = StaticTerms {
        cache_resident_bound: terrain.as_ref().map_or(0, |_| b.max_cache_bytes),
        decoder_transient_estimate: terrain.as_ref().map_or(0, |t| {
            (b.threads as u64).saturating_mul(t.decoder_transient_bytes_per_load())
        }),
        output_tile_buffers_bound: req.output_buffer_bound()?,
        request_inline_payload: req.inline_payload_bytes(),
    };
    let allowance = match b.max_session_bytes {
        Some(max) => Some(max.checked_sub(st.statics.total()).ok_or_else(|| {
            MapError::Budget(format!(
                "max_session_bytes {max} < static accounted terms {} ({:?})",
                st.statics.total(),
                st.statics
            ))
        })?),
        None => None,
    };
    let estimates: Vec<Result<ProfileEstimate, MapError>> = req
        .profiles
        .iter()
        .map(|p| p.source.estimate(base))
        .collect();
    let batches = plan_batches(req, &estimates, allowance);
    let want_ground = req.products.contains(&Product::Ground);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(b.threads)
        .thread_name(|i| format!("ras2fim-batch-{i}"))
        .build()
        .map_err(|e| MapError::Invalid(format!("thread pool: {e}")))?;
    st.sink = Some(DirSink::create(out, &req.products)?);
    let mut aborted = false;
    for (batch_no, batch) in batches.iter().enumerate() {
        if aborted {
            break;
        }
        // 0. Preflight (no reads): estimate errors and over-budget profiles fail here.
        let mut admitted: Vec<usize> = Vec::new();
        for &s in batch {
            let pre = estimates[s].as_ref().map_err(Clone::clone).and_then(|e| {
                st.reports[s].load_peak_estimate_bytes = e.peak_bytes();
                st.reports[s].estimate_basis = e.basis.into();
                if e.peak_bytes() > b.max_profile_bytes {
                    Err(MapError::Budget(format!(
                        "profile load+prepare estimate {} bytes ({}) > max_profile_bytes {}",
                        e.peak_bytes(),
                        e.basis,
                        b.max_profile_bytes
                    )))
                } else if let Some(allow) = allowance
                    && batch_load_peak(&[e], b.threads) > allow
                {
                    Err(MapError::Budget(format!(
                        "profile load+prepare estimate {} bytes does not fit max_session_bytes after static terms ({allow} bytes left)",
                        batch_load_peak(&[e], b.threads)
                    )))
                } else {
                    Ok(())
                }
            });
            match pre {
                Ok(()) => admitted.push(s),
                Err(e) => {
                    st.reports[s].status = "failed".into();
                    st.reports[s].batch = batch_no;
                    st.reports[s].error = Some(err_json("preflight", &e));
                    write_failed_units(st.sink.as_ref().expect("sink"), req, s, "preflight", &e)?;
                    if req.error_policy == ErrorPolicy::FailFast {
                        aborted = true;
                    }
                }
            }
        }
        if aborted {
            break;
        }
        let admitted_est: Vec<&ProfileEstimate> = admitted
            .iter()
            .filter_map(|&s| estimates[s].as_ref().ok())
            .collect();
        let load_peak = batch_load_peak(&admitted_est, b.threads);
        // 1. Load + prepare the batch in the session pool.
        let t0 = Instant::now();
        let prepared: Vec<Result<Prepared, MapError>> = pool.install(|| {
            admitted
                .par_iter()
                .map(|&s| {
                    prepare(
                        s,
                        &req.profiles[s],
                        base,
                        terrain.as_deref(),
                        b.max_profile_bytes,
                    )
                })
                .collect()
        });
        st.prepare_wall += t0.elapsed().as_secs_f64();
        let mut live: Vec<Prepared> = Vec::new();
        for (&s, r) in admitted.iter().zip(prepared) {
            match r {
                Ok(mut p) => {
                    p.report.batch = batch_no;
                    p.report.load_peak_estimate_bytes = st.reports[s].load_peak_estimate_bytes;
                    p.report.estimate_basis = st.reports[s].estimate_basis.clone();
                    st.reports[s].status = "prepared".into();
                    live.push(p);
                }
                Err(e) => {
                    st.reports[s].status = "failed".into();
                    st.reports[s].batch = batch_no;
                    st.reports[s].error = Some(err_json("prepare", &e));
                    write_failed_units(st.sink.as_ref().expect("sink"), req, s, "prepare", &e)?;
                    if req.error_policy == ErrorPolicy::FailFast {
                        aborted = true;
                    }
                }
            }
        }
        if aborted {
            break;
        }
        let resident: u64 = live.iter().map(|p| p.bytes).sum();
        // 2. Units and work items. Plan size is bounded before anything is allocated.
        let mut items: Vec<Item> = Vec::new();
        let mut failed: Vec<Option<MapError>> = vec![None; live.len()];
        let mut opened: Vec<bool> = vec![false; live.len()];
        let mut headers: Vec<Vec<serde_json::Value>> = Vec::new();
        let mut plan_bytes_batch = 0u64;
        for (li, p) in live.iter().enumerate() {
            let t = b.output_tile;
            let windows_all: Vec<Option<Rect>> =
                req.aois.iter().map(|a| aoi_window(a, &p.grid)).collect();
            let unit_tiles: Vec<u64> = windows_all
                .iter()
                .map(|w| w.as_ref().map_or(0, |w| tiles_in(w, t)))
                .collect();
            let tile_bound: u64 = unit_tiles.iter().sum();
            let plan_bytes = tile_bound
                .saturating_mul(PLAN_BYTES_PER_ITEM)
                .saturating_add(tile_bound.saturating_mul(crate::sink::TILE_RECORD_BYTES));
            let plan_err = if tile_bound > MAX_PLAN_TILES_PER_PROFILE {
                Some(MapError::Budget(format!(
                    "plan has up to {tile_bound} tiles > {MAX_PLAN_TILES_PER_PROFILE}; raise output_tile"
                )))
            } else if let Some(allow) = allowance
                && resident
                    .saturating_add(plan_bytes_batch)
                    .saturating_add(plan_bytes)
                    > allow
            {
                Some(MapError::Budget(format!(
                    "plan metadata {plan_bytes} bytes does not fit max_session_bytes with {resident} resident profile bytes"
                )))
            } else {
                None
            };
            if let Some(e) = plan_err {
                write_failed_units(st.sink.as_ref().expect("sink"), req, p.slot, "plan", &e)?;
                failed[li] = Some(e);
                headers.push(Vec::new());
                continue;
            }
            plan_bytes_batch += plan_bytes;
            opened[li] = true;
            let mut windows = Vec::new();
            let mut hs = Vec::new();
            for (ai, a) in req.aois.iter().enumerate() {
                let w = windows_all[ai];
                let h = unit_header(req, p, a, w, &req.products);
                st.sink.as_mut().expect("sink").begin_unit(
                    (li, ai),
                    &p.id,
                    &a.id,
                    w,
                    &h,
                    unit_tiles[ai] as usize,
                )?;
                hs.push(h);
                if let Some(w) = w {
                    windows.push(w);
                }
            }
            headers.push(hs);
            let mut tiles = BTreeSet::new();
            for w in &windows {
                for tr in w.row / t..=(w.row + w.height - 1) / t {
                    for tc in w.col / t..=(w.col + w.width - 1) / t {
                        tiles.insert((tr, tc));
                    }
                }
            }
            let (gw, gh) = p.grid.dims();
            let mut kmax = 0;
            for (tr, tc) in tiles {
                let tile_rect = Rect {
                    col: tc * t,
                    row: tr * t,
                    width: t.min(gw - tc * t),
                    height: t.min(gh - tr * t),
                };
                let parts: Vec<Rect> = windows
                    .iter()
                    .filter_map(|w| w.intersect(&tile_rect))
                    .collect();
                let c0 = parts.iter().map(|r| r.col).min().unwrap_or(0);
                let r0 = parts.iter().map(|r| r.row).min().unwrap_or(0);
                let c1 = parts.iter().map(|r| r.col + r.width).max().unwrap_or(0);
                let r1 = parts.iter().map(|r| r.row + r.height).max().unwrap_or(0);
                let rect = Rect {
                    col: c0,
                    row: r0,
                    width: c1 - c0,
                    height: r1 - r0,
                };
                let any_mask = match &p.mask {
                    MaskData::AllWet => true,
                    MaskData::Bits(bits) => (rect.row..rect.row + rect.height).any(|r| {
                        bits[r * gw + rect.col..r * gw + rect.col + rect.width]
                            .iter()
                            .any(|v| *v)
                    }),
                };
                let needs_terrain = terrain.is_some() && (any_mask || want_ground);
                let blocks = match (&terrain, needs_terrain) {
                    (Some(tt), true) => plan_blocks(p, &rect, tt),
                    _ => None,
                };
                if let Some((bx0, bx1, by0, by1)) = blocks {
                    kmax = kmax.max((bx1 - bx0) * (by1 - by0));
                }
                items.push(Item {
                    slot: li,
                    tile: (tr, tc),
                    rect,
                    needs_terrain,
                    blocks,
                });
            }
            st.max_blocks_any = st.max_blocks_any.max(kmax);
            if let Some(tt) = &terrain {
                let need = (b.threads as u64)
                    .saturating_mul(kmax as u64)
                    .saturating_mul(tt.max_block_bytes());
                if need > b.max_cache_bytes {
                    failed[li] = Some(MapError::Budget(format!(
                        "terrain cache budget {} < threads {} x {} blocks/tile x {} bytes = {need}; raise max_cache_bytes or lower output_tile/threads",
                        b.max_cache_bytes,
                        b.threads,
                        kmax,
                        tt.max_block_bytes()
                    )));
                }
            }
        }
        st.batches.push(serde_json::json!({
            "batch": batch_no,
            "profiles": admitted.iter().map(|&s| req.profiles[s].id.as_str()).collect::<Vec<_>>(),
            "load_peak_estimate_bytes": load_peak,
            "prepared_resident_bytes": resident,
            "plan_metadata_estimate_bytes": plan_bytes_batch,
            "accounted_peak_estimate_bytes": st.statics.total().saturating_add(load_peak.max(resident.saturating_add(plan_bytes_batch))),
        }));
        for (li, p) in live.iter_mut().enumerate() {
            p.report.max_terrain_blocks_per_tile = items
                .iter()
                .filter(|it| it.slot == li)
                .filter_map(|it| it.blocks.map(|(a, b2, c, d)| (b2 - a) * (d - c)))
                .max()
                .unwrap_or(0);
        }
        // 3. Locality order: shared terrain blocks consecutively across profiles.
        items.retain(|it| failed[it.slot].is_none());
        items.sort_by_key(|it| {
            (
                it.blocks
                    .map_or((usize::MAX, usize::MAX), |(bx0, _, by0, _)| (by0, bx0)),
                it.slot,
                it.tile,
            )
        });
        st.items_total += items.len() as u64;
        // 4. Bounded evaluation. Pipelined (max_tiles_in_flight >= 2): the pool evaluates chunk
        //    k+1 while this thread writes chunk k; two chunks of max_tiles_in_flight/2 keep at
        //    most 2*(max_tiles_in_flight/2) tiles alive. Serial (== 1): evaluate one tile, write
        //    it, repeat; never more than one alive.
        let t1 = Instant::now();
        let serial = b.max_tiles_in_flight == 1;
        let chunk_len = if serial { 1 } else { b.max_tiles_in_flight / 2 };
        let order: Vec<usize> = (0..items.len()).collect();
        let mut chunks = order.chunks(chunk_len);
        let mut acc: Vec<(u64, u64, ItemStats)> = (0..live.len())
            .map(|_| (0, 0, ItemStats::default()))
            .collect();
        let mut pending: Option<Evaluated> = None;
        let sink = st.sink.as_mut().expect("sink");
        loop {
            let next: Option<Vec<usize>> = chunks.next().map(|c| {
                c.iter()
                    .copied()
                    .filter(|&k| failed[items[k].slot].is_none())
                    .collect()
            });
            if next.is_none() && pending.is_none() {
                break;
            }
            let (items_ref, live_ref, terrain_ref) = (&items, &live, terrain.as_deref());
            let eval = |idx: Vec<usize>| -> Evaluated {
                idx.par_iter()
                    .map(|&k| {
                        let it = &items_ref[k];
                        let p = &live_ref[it.slot];
                        (k, evaluate(it, p, terrain_ref, want_ground))
                    })
                    .collect()
            };
            if serial {
                let evaluated = next.map(|idx| pool.install(|| eval(idx)));
                st.peak_tiles_in_flight = st
                    .peak_tiles_in_flight
                    .max(evaluated.as_ref().map_or(0, Vec::len));
                let (write_result, write_secs) = write_chunk(
                    evaluated,
                    items_ref,
                    &mut failed,
                    &mut acc,
                    sink,
                    req.aois.len(),
                );
                st.sink_seconds += write_secs;
                write_result?;
            } else {
                let in_flight =
                    next.as_ref().map_or(0, Vec::len) + pending.as_ref().map_or(0, Vec::len);
                st.peak_tiles_in_flight = st.peak_tiles_in_flight.max(in_flight);
                let to_write = pending.take();
                let mut evaluated: Option<Evaluated> = None;
                // `in_place_scope` keeps this thread (the writer) outside the pool; the chunk job
                // runs on pool workers. No additional OS threads are created.
                let (write_result, write_secs) = pool.in_place_scope(|s| {
                    if let Some(idx) = next {
                        let slot = &mut evaluated;
                        s.spawn(move |_| *slot = Some(eval(idx)));
                    }
                    write_chunk(
                        to_write,
                        items_ref,
                        &mut failed,
                        &mut acc,
                        sink,
                        req.aois.len(),
                    )
                });
                st.sink_seconds += write_secs;
                write_result?;
                pending = evaluated;
            }
            if req.error_policy == ErrorPolicy::FailFast && failed.iter().any(Option::is_some) {
                aborted = true;
                break;
            }
        }
        for (p, (tiles, pixels, s)) in live.iter_mut().zip(acc) {
            let rep = &mut p.report;
            rep.tiles_evaluated = tiles;
            rep.pixels_evaluated = pixels;
            rep.masked_pixels = s.masked;
            rep.raw_valid_pixels = s.raw_valid;
            rep.wet_pixels = s.wet;
            rep.terrain_dry_pixels = s.terrain_dry;
            rep.terrain_raw_sentinel_pixels = s.sentinel;
            rep.terrain_near_boundary_samples = s.near_boundary;
            rep.eval_seconds = s.seconds;
        }
        st.eval_wall += t1.elapsed().as_secs_f64();
        // 5. Close units; drop prepared profiles of this batch.
        let abort_err =
            MapError::Invalid("session aborted by fail_fast before this profile completed".into());
        for (li, p) in live.into_iter().enumerate() {
            let err = failed[li]
                .as_ref()
                .or(if aborted { Some(&abort_err) } else { None });
            if opened[li] {
                for (ai, header) in headers[li].iter().enumerate() {
                    sink.end_unit((li, ai), header, err)?;
                }
            }
            let mut rep = p.report;
            match err {
                Some(e) => {
                    rep.status = if failed[li].is_some() {
                        "failed"
                    } else {
                        "aborted"
                    }
                    .into();
                    let stage = if opened[li] { "evaluate" } else { "plan" };
                    rep.error = Some(err_json(stage, e));
                }
                None => rep.status = "complete".into(),
            }
            st.reports[p.slot] = rep;
        }
        if sink.open_units() != 0 {
            return Err(MapError::Internal(format!(
                "{} units left open after batch {batch_no}",
                sink.open_units()
            )));
        }
    }
    let any_failed = st.reports.iter().any(|r| r.status != "complete");
    let report = build_report(
        req,
        st,
        if any_failed { "incomplete" } else { "complete" },
        started,
    )?;
    write_json(&out.join("report.json"), &report)?;
    Ok(report)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounds_select_by_pixel_center_both_orientations() {
        let g = Grid::Explicit {
            width: 10,
            height: 10,
            x0: 0.,
            y0: 0.,
            dx: 1.,
            dy: 1.,
        };
        let a = AoiSpec {
            id: "a".into(),
            window: None,
            bounds: Some([2.0, 3.0, 5.5, 3.6]),
            crs_epsg: None,
        };
        assert_eq!(
            aoi_window(&a, &g),
            Some(Rect {
                col: 2,
                row: 3,
                width: 3,
                height: 1
            })
        );
        let g = Grid::Explicit {
            width: 10,
            height: 10,
            x0: 0.,
            y0: 10.,
            dx: 1.,
            dy: -1.,
        };
        // Row r center y = 10 - (r + 0.5); [3, 6) contains centers 5.5, 4.5, 3.5 -> rows 4, 5, 6.
        let a = AoiSpec {
            id: "a".into(),
            window: None,
            bounds: Some([0.0, 3.0, 1.0, 6.0]),
            crs_epsg: None,
        };
        assert_eq!(
            aoi_window(&a, &g),
            Some(Rect {
                col: 0,
                row: 4,
                width: 1,
                height: 3
            })
        );
        let a = AoiSpec {
            id: "a".into(),
            window: None,
            bounds: Some([20.0, 3.0, 21.0, 6.0]),
            crs_epsg: None,
        };
        assert_eq!(aoi_window(&a, &g), None);
    }

    #[test]
    fn windows_clip() {
        let g = Grid::Explicit {
            width: 10,
            height: 8,
            x0: 0.,
            y0: 0.,
            dx: 1.,
            dy: 1.,
        };
        let a = AoiSpec {
            id: "a".into(),
            window: Some([8, 6, 5, 5]),
            bounds: None,
            crs_epsg: None,
        };
        assert_eq!(
            aoi_window(&a, &g),
            Some(Rect {
                col: 8,
                row: 6,
                width: 2,
                height: 2
            })
        );
        let a = AoiSpec {
            id: "a".into(),
            window: Some([10, 0, 1, 1]),
            bounds: None,
            crs_epsg: None,
        };
        assert_eq!(aoi_window(&a, &g), None);
    }
}
