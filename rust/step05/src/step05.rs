//! Upstream ras2fim-2D Step05 raster-compatibility stages over prepared global inputs.
//!
//! Interface: `implementation-r2/stages/README.md` (`ras2fim-step05-request/1`).
//! Stage sequence (upstream `generate_depth_wsel_rasters_mp_05.py` @ 3146f647):
//! - 01: SciPy `griddata(linear)` at the exact captured `np.arange` axes (`scipy_interp`).
//! - 02/03: caller-supplied wet mask (rasterio.mask equivalent, Python adapter); f64.
//! - 05: native terrain at the raster-01 affine pixel centres (no GDAL); outside = nodata.
//! - 06 = f32(f64(03) - f64(05)); 07 = 06 with `< 0 -> NaN` after the cast (zero and -0 kept);
//!   08 = f32(f64(05) + f64(07)) where 07 is finite. The raw terrain sentinel is subtracted as a
//!   number, as upstream does.
//! - 09/10: terrio 0.4.2 native approximate warp (nearest) onto the explicit destination grid,
//!   either as full warps of 07/08 (`full_warp`) or through a native full-destination-grid
//!   source-pixel lookup and an AOI gather (`lookup`).
use crate::MapError;
use crate::model::{CrsIdentity, NodataPolicy, QueryConvention};
use crate::scipy_interp::{DelaunayParts, Located, ScipyDelaunay, WalkStats};
use crate::terrain::{Hit, NativeTerrain};
use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;

pub const REQUEST_SCHEMA: &str = "ras2fim-step05-request/1";
pub const INPUTS_SCHEMA: &str = "ras2fim-step05-inputs/1";
pub const METHOD: &str = "ras2fim-step05-stages/0.1.0 method-r2";
/// Largest index exactly representable in one f32 lookup pass.
const LOOKUP_PASS_BITS: u32 = 24;
const NONE: u32 = u32::MAX;

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub terrain: TerrainSpec,
    pub source_crs: SourceCrs,
    pub budgets: Budgets,
    pub interpolation: Interpolation,
    pub nudge: Nudge,
    #[serde(default)]
    pub stages: Vec<String>,
    pub profiles: Vec<Profile>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct TerrainSpec {
    pub path: String,
    pub epsg: u32,
    pub crs_identity: CrsIdentity,
}

#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SourceCrs {
    Terrain,
    Epsg { code: u32 },
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Budgets {
    pub threads: usize,
    pub max_cache_bytes: u64,
    pub max_profile_bytes: u64,
    pub max_inflight_profiles: usize,
    #[serde(default = "default_lookup_cache")]
    pub max_lookup_cache_bytes: u64,
}

/// Default 0: no lookup retention across profiles (bounded memory for long catalogs).
fn default_lookup_cache() -> u64 {
    0
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Selection {
    Auto,
    ScipyWalkSerial,
    GuardedParallel,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Interpolation {
    pub selection: Selection,
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NudgeMethod {
    Lookup,
    FullWarp,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Nudge {
    pub dst_epsg: u32,
    pub error_threshold: f64,
    pub memory_limit_bytes: f64,
    pub method: NudgeMethod,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub id: String,
    pub inputs_dir: String,
    pub dest_grid: DestGrid,
    pub aois: Vec<Aoi>,
}

#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct DestGrid {
    pub geotransform: [f64; 6],
    pub width: usize,
    pub height: usize,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Aoi {
    pub id: String,
    #[serde(default)]
    pub window: Option<[i64; 4]>,
    #[serde(default)]
    pub bounds: Option<[f64; 4]>,
    #[serde(default)]
    pub mask_u8: Option<String>,
}

#[derive(Deserialize, Debug, Clone)]
pub struct InputsJson {
    pub schema: String,
    pub rows: usize,
    pub cols: usize,
    pub raster_affine: RasterAffine,
    pub delaunay: DelaunayScalars,
    pub files: HashMap<String, FileSpec>,
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy)]
pub struct RasterAffine {
    pub x0: f64,
    pub y0: f64,
    pub res_x: f64,
    pub res_y: f64,
}

#[derive(Deserialize, Debug, Clone)]
pub struct DelaunayScalars {
    pub paraboloid_scale: f64,
    pub paraboloid_shift: f64,
    pub min_bound: [f64; 2],
    pub max_bound: [f64; 2],
    pub nsimplex: usize,
}

#[derive(Deserialize, Debug, Clone)]
pub struct FileSpec {
    pub file: String,
    pub dtype: String,
    pub shape: Vec<usize>,
}

const STAGES: [&str; 5] = ["03", "05", "06", "07", "08"];

fn is_safe_id(s: &str) -> bool {
    // Lowercase-insensitive uniqueness is checked by the caller; reject Windows-reserved names.
    let reserved = ["con", "prn", "aux", "nul", "com1", "lpt1"];
    !s.is_empty()
        && s.len() <= 128
        && s.chars()
            .all(|c| c.is_ascii_alphanumeric() || "_-.".contains(c))
        && !s.starts_with('.')
        && !reserved.contains(&s.to_ascii_lowercase().as_str())
}

impl Request {
    pub fn load(path: &Path) -> Result<Self, MapError> {
        let text = fs::read_to_string(path)
            .map_err(|e| MapError::Io(format!("{}: {e}", path.display())))?;
        let r: Request =
            serde_json::from_str(&text).map_err(|e| MapError::Invalid(format!("request: {e}")))?;
        r.validate()?;
        Ok(r)
    }

    pub fn validate(&self) -> Result<(), MapError> {
        let inv = |s: String| Err(MapError::Invalid(s));
        if self.schema != REQUEST_SCHEMA {
            return inv(format!(
                "schema {:?}, expected {REQUEST_SCHEMA}",
                self.schema
            ));
        }
        let b = &self.budgets;
        if b.threads == 0 || b.threads > 256 || b.max_inflight_profiles == 0 {
            return inv("budgets: threads 1..=256 and max_inflight_profiles >= 1".into());
        }
        if b.max_cache_bytes == 0 || b.max_profile_bytes == 0 {
            return inv("budgets: byte limits must be positive".into());
        }
        let n = &self.nudge;
        if !(n.error_threshold.is_finite() && n.error_threshold >= 0.0) {
            return inv("nudge.error_threshold must be finite and >= 0".into());
        }
        if !(n.memory_limit_bytes.is_finite() && n.memory_limit_bytes > 0.0) {
            return inv("nudge.memory_limit_bytes must be positive".into());
        }
        for s in &self.stages {
            if !STAGES.contains(&s.as_str()) {
                return inv(format!("unknown stage {s:?}; allowed {STAGES:?}"));
            }
        }
        if self.profiles.is_empty() {
            return inv("no profiles".into());
        }
        let mut ids = std::collections::HashSet::new();
        for p in &self.profiles {
            if !is_safe_id(&p.id) || !ids.insert(p.id.to_ascii_lowercase()) {
                return inv(format!(
                    "profile id {:?} unsafe or duplicate (case-insensitive)",
                    p.id
                ));
            }
            let g = &p.dest_grid;
            if !g.geotransform.iter().all(|v| v.is_finite())
                || g.geotransform[2] != 0.0
                || g.geotransform[4] != 0.0
                || g.geotransform[1] <= 0.0
                || g.geotransform[5] >= 0.0
            {
                return Err(MapError::Unsupported(format!(
                    "profile {}: dest_grid must be north-up axis-aligned",
                    p.id
                )));
            }
            if g.width == 0
                || g.height == 0
                || g.width
                    .checked_mul(g.height)
                    .is_none_or(|v| v >= NONE as usize)
            {
                return inv(format!("profile {}: dest_grid size", p.id));
            }
            if p.aois.is_empty() {
                return inv(format!("profile {}: no aois", p.id));
            }
            let mut aids = std::collections::HashSet::new();
            for a in &p.aois {
                if !is_safe_id(&a.id) || !aids.insert(a.id.to_ascii_lowercase()) {
                    return inv(format!("aoi id {:?} unsafe or duplicate", a.id));
                }
                if a.window.is_some() && a.bounds.is_some() {
                    return inv(format!("aoi {}: window and bounds are exclusive", a.id));
                }
                if let Some(w) = a.window
                    && (w[2] <= 0 || w[3] <= 0)
                {
                    return inv(format!("aoi {}: window size must be positive", a.id));
                }
                if let Some(bd) = a.bounds
                    && !(bd.iter().all(|v| v.is_finite()) && bd[0] < bd[2] && bd[1] < bd[3])
                {
                    return inv(format!(
                        "aoi {}: bounds must be finite with min < max",
                        a.id
                    ));
                }
                if a.mask_u8.is_some() && a.window.is_none() && a.bounds.is_none() {
                    return inv(format!("aoi {}: mask_u8 needs window or bounds", a.id));
                }
            }
        }
        Ok(())
    }
}

/// Clipped `[col, row, w, h]` of an AOI on the destination grid; `None` = empty.
pub fn aoi_window(g: &DestGrid, a: &Aoi) -> Option<[usize; 4]> {
    let (c0, r0, c1, r1) = if let Some(w) = a.window {
        (
            w[0],
            w[1],
            w[0].saturating_add(w[2]),
            w[1].saturating_add(w[3]),
        )
    } else if let Some(b) = a.bounds {
        // Pixel centres in [min, max): col c selected iff xmin <= gt0 + (c+0.5)*gt1 < xmax.
        let gt = g.geotransform;
        let cols: Vec<i64> = (0..g.width as i64)
            .filter(|c| {
                let x = gt[0] + (*c as f64 + 0.5) * gt[1];
                b[0] <= x && x < b[2]
            })
            .collect();
        let rows: Vec<i64> = (0..g.height as i64)
            .filter(|r| {
                let y = gt[3] + (*r as f64 + 0.5) * gt[5];
                b[1] <= y && y < b[3]
            })
            .collect();
        if cols.is_empty() || rows.is_empty() {
            return None;
        }
        (
            cols[0],
            rows[0],
            cols[cols.len() - 1] + 1,
            rows[rows.len() - 1] + 1,
        )
    } else {
        (0, 0, g.width as i64, g.height as i64)
    };
    let c0 = c0.max(0);
    let r0 = r0.max(0);
    let c1 = c1.min(g.width as i64);
    let r1 = r1.min(g.height as i64);
    (c1 > c0 && r1 > r0).then(|| {
        [
            c0 as usize,
            r0 as usize,
            (c1 - c0) as usize,
            (r1 - r0) as usize,
        ]
    })
}

fn read_bin(
    dir: &Path,
    spec: &FileSpec,
    dtype: &str,
    elem: usize,
    shape: &[usize],
) -> Result<Vec<u8>, MapError> {
    // numpy spells byte-order-free dtypes with '|' (e.g. "|u1").
    if spec.dtype.trim_start_matches('|') != dtype {
        return Err(MapError::Invalid(format!(
            "{}: dtype {} expected {dtype}",
            spec.file, spec.dtype
        )));
    }
    if spec.shape != shape {
        return Err(MapError::Invalid(format!(
            "{}: shape {:?} expected {shape:?}",
            spec.file, spec.shape
        )));
    }
    if spec.file.contains('/') || spec.file.contains('\\') || spec.file.contains("..") {
        return Err(MapError::Invalid(format!(
            "{}: file must be a plain name",
            spec.file
        )));
    }
    let n = shape
        .iter()
        .try_fold(elem, |a, b| a.checked_mul(*b))
        .ok_or_else(|| MapError::Budget("shape overflow".into()))?;
    let path = dir.join(&spec.file);
    let len = fs::metadata(&path)
        .map_err(|e| MapError::Io(format!("{}: {e}", path.display())))?
        .len();
    if len != n as u64 {
        return Err(MapError::Invalid(format!(
            "{}: {len} bytes, expected {n}",
            path.display()
        )));
    }
    fs::read(&path).map_err(|e| MapError::Io(format!("{}: {e}", path.display())))
}

fn f64s(b: &[u8]) -> Vec<f64> {
    b.as_chunks::<8>()
        .0
        .iter()
        .map(|c| f64::from_le_bytes(*c))
        .collect()
}

/// Prepared per-profile inputs (validated).
pub struct Inputs {
    pub rows: usize,
    pub cols: usize,
    pub affine: RasterAffine,
    pub x_axis: Vec<f64>,
    pub y_axis: Vec<f64>,
    pub mask: Vec<u8>,
    pub delaunay: ScipyDelaunay,
}

impl Inputs {
    /// Bytes the inputs will occupy, computed from inputs.json before reading any array.
    pub fn planned_bytes(meta: &InputsJson) -> u64 {
        let get = |k: &str| {
            meta.files
                .get(k)
                .map_or(0u64, |f| f.shape.iter().product::<usize>() as u64)
        };
        get("samples") * 8
            + get("simplices") * 4
            + get("transform") * 8
            + get("neighbors") * 4
            + get("equations") * 8
            + get("x_axis") * 8
            + get("y_axis") * 8
            + get("wet_mask")
            + meta.delaunay.nsimplex as u64 * 72
    }

    pub fn load_meta(dir: &Path) -> Result<InputsJson, MapError> {
        let p = dir.join("inputs.json");
        let text =
            fs::read_to_string(&p).map_err(|e| MapError::Io(format!("{}: {e}", p.display())))?;
        let m: InputsJson = serde_json::from_str(&text)
            .map_err(|e| MapError::Invalid(format!("{}: {e}", p.display())))?;
        if m.schema != INPUTS_SCHEMA {
            return Err(MapError::Invalid(format!(
                "{}: schema {:?}",
                p.display(),
                m.schema
            )));
        }
        let a = m.raster_affine;
        if !([a.x0, a.y0, a.res_x, a.res_y].iter().all(|v| v.is_finite())
            && a.res_x > 0.0
            && a.res_y > 0.0)
        {
            return Err(MapError::Unsupported(
                "raster_affine must be finite with positive res (upstream positive-e)".into(),
            ));
        }
        if m.rows == 0
            || m.cols == 0
            || m.rows
                .checked_mul(m.cols)
                .is_none_or(|v| v >= NONE as usize)
        {
            return Err(MapError::Invalid("rows/cols".into()));
        }
        Ok(m)
    }

    pub fn load(dir: &Path, m: &InputsJson) -> Result<Self, MapError> {
        let f = |k: &str| {
            m.files
                .get(k)
                .ok_or_else(|| MapError::Invalid(format!("inputs.json: missing file {k}")))
        };
        let samples_spec = f("samples")?;
        let n = *samples_spec.shape.first().unwrap_or(&0);
        let ns = m.delaunay.nsimplex;
        let (rows, cols) = (m.rows, m.cols);
        let samples = f64s(&read_bin(dir, samples_spec, "<f8", 8, &[n, 3])?);
        let simplices: Vec<[u32; 3]> = read_bin(dir, f("simplices")?, "<u4", 4, &[ns, 3])?
            .as_chunks::<12>()
            .0
            .iter()
            .map(|c| [0, 1, 2].map(|k| u32::from_le_bytes(c[4 * k..4 * k + 4].try_into().unwrap())))
            .collect();
        let transform: Vec<[f64; 6]> =
            f64s(&read_bin(dir, f("transform")?, "<f8", 8, &[ns, 3, 2])?)
                .as_chunks::<6>()
                .0
                .to_vec();
        let neighbors: Vec<[i32; 3]> = read_bin(dir, f("neighbors")?, "<i4", 4, &[ns, 3])?
            .as_chunks::<12>()
            .0
            .iter()
            .map(|c| [0, 1, 2].map(|k| i32::from_le_bytes(c[4 * k..4 * k + 4].try_into().unwrap())))
            .collect();
        let equations: Vec<[f64; 4]> = f64s(&read_bin(dir, f("equations")?, "<f8", 8, &[ns, 4])?)
            .as_chunks::<4>()
            .0
            .to_vec();
        let x_axis = f64s(&read_bin(dir, f("x_axis")?, "<f8", 8, &[cols])?);
        let y_axis = f64s(&read_bin(dir, f("y_axis")?, "<f8", 8, &[rows])?);
        let mask = read_bin(dir, f("wet_mask")?, "u1", 1, &[rows, cols])?;
        if mask.iter().any(|v| *v > 1) {
            return Err(MapError::Invalid("wet_mask values must be 0/1".into()));
        }
        for (name, a) in [("x_axis", &x_axis), ("y_axis", &y_axis)] {
            if !a.iter().all(|v| v.is_finite()) || a.windows(2).any(|w| w[1] <= w[0]) {
                return Err(MapError::Invalid(format!(
                    "{name} must be finite and strictly increasing"
                )));
            }
        }
        let samples3: Vec<[f64; 3]> = samples.as_chunks::<3>().0.to_vec();
        let d = &m.delaunay;
        let delaunay = ScipyDelaunay::new(DelaunayParts {
            samples: samples3,
            simplices,
            transform,
            neighbors,
            equations,
            paraboloid_scale: d.paraboloid_scale,
            paraboloid_shift: d.paraboloid_shift,
            min_bound: d.min_bound,
            max_bound: d.max_bound,
        })?;
        Ok(Self {
            rows,
            cols,
            affine: m.raster_affine,
            x_axis,
            y_axis,
            mask,
            delaunay,
        })
    }

    /// Raster-01 affine in GDAL order (positive e).
    pub fn gt(&self) -> [f64; 6] {
        [
            self.affine.x0,
            self.affine.res_x,
            0.0,
            self.affine.y0,
            0.0,
            self.affine.res_y,
        ]
    }
}

/// Values of the float32 stages at one 01-grid pixel.
#[derive(Clone, Copy, Debug)]
pub struct PixelStages {
    pub raw03: f64,
    pub ground05: f32,
    pub d06: f32,
    pub d07: f32,
    pub w08: f32,
}

/// The upstream float32 sequence for one pixel.
#[inline]
pub fn float_stages(raw03: f64, ground05: f32) -> Result<PixelStages, MapError> {
    let wide = raw03 - ground05 as f64;
    let d06 = wide as f32;
    if wide.is_finite() && !d06.is_finite() {
        return Err(MapError::Unsupported(format!(
            "06 float32 cast overflow ({wide})"
        )));
    }
    let d07 = if d06 < 0.0 { f32::NAN } else { d06 };
    let w08 = if d07.is_nan() {
        f32::NAN
    } else {
        let s = ground05 as f64 + d07 as f64;
        let v = s as f32;
        if s.is_finite() && !v.is_finite() {
            return Err(MapError::Unsupported(format!(
                "08 float32 cast overflow ({s})"
            )));
        }
        v
    };
    Ok(PixelStages {
        raw03,
        ground05,
        d06,
        d07,
        w08,
    })
}

#[derive(Default, Debug, Clone, Serialize)]
pub struct TerrainCounters {
    pub sampled: u64,
    pub outside: u64,
    pub near_boundary: u64,
    pub raw_sentinel_under_wet: u64,
}

/// Terrain sample at raster-01 pixel centre: raw value, or declared nodata outside the extent.
fn ground_at(
    t: &NativeTerrain,
    inp: &Inputs,
    row: usize,
    col: usize,
    tc: &mut TerrainCounters,
) -> Result<f32, MapError> {
    let a = inp.affine;
    let x = a.x0 + (col as f64 + 0.5) * a.res_x;
    let y = a.y0 + (row as f64 + 0.5) * a.res_y;
    tc.sampled += 1;
    match t.hit(x, y) {
        Hit::Outside => {
            tc.outside += 1;
            Ok(t.nodata.map(|v| v as f32).unwrap_or(f32::NAN))
        }
        Hit::Pixel {
            col: c,
            row: r,
            near_boundary,
        } => {
            tc.near_boundary += near_boundary as u64;
            let (bw, bh) = t.block;
            let block = t.get_block(c / bw, r / bh)?;
            let w = t.block_window(c / bw, r / bh);
            Ok(block[(r - w.y) * w.width + (c - w.x)])
        }
    }
}

/// Native lookup: destination pixel -> source (01-grid) linear pixel index, or `NONE`.
pub struct Lookup {
    pub key: String,
    pub index: Vec<u32>,
    pub passes: u32,
    pub build_seconds: f64,
}

fn src_dataset(
    values: Vec<f32>,
    rows: usize,
    cols: usize,
    gt: [f64; 6],
) -> Result<terrio::RasterDataset, MapError> {
    let cfg = terrio::RasterConfig {
        cols,
        rows,
        bands: 1,
        nodata: f64::NAN,
        data_type: terrio::DataType::F32,
        ..Default::default()
    };
    let raster = terrio::Raster::from_data_native(cfg, terrio::raster::RasterData::F32(values))
        .map_err(|e| MapError::Invalid(format!("source raster: {e}")))?;
    let mut ds = terrio::RasterDataset::new(raster, true);
    ds.set_geo_transform(gt);
    Ok(ds)
}

pub struct WarpEnv {
    pub src_srs: terrio::crs::SpatialRef,
    pub dst_srs: terrio::crs::SpatialRef,
    pub src_srs_wkt: String,
    pub dst_srs_wkt: String,
}

fn warp_options(env: &WarpEnv, n: &Nudge, g: &DestGrid) -> terrio::ops::warp::WarpOptions {
    terrio::ops::warp::WarpOptions {
        src_srs: Some(env.src_srs.clone()),
        dst_srs: Some(env.dst_srs.clone()),
        dst_transform: Some(g.geotransform),
        size: Some((g.width, g.height)),
        resampling: terrio::ops::Resampling::Nearest,
        error_threshold: n.error_threshold,
        memory_limit: n.memory_limit_bytes,
        ..Default::default()
    }
}

/// Native warp of one f32 01-grid field with NaN nodata onto the destination grid.
pub fn warp_field(
    values: Vec<f32>,
    inp_rows: usize,
    inp_cols: usize,
    gt: [f64; 6],
    env: &WarpEnv,
    n: &Nudge,
    g: &DestGrid,
) -> Result<Vec<f32>, MapError> {
    let ds = src_dataset(values, inp_rows, inp_cols, gt)?;
    let out = terrio::ops::warp::warp(&[&ds], &warp_options(env, n, g))
        .map_err(|e| MapError::Terrain(format!("warp: {e}")))?;
    if out.geo_transform() != g.geotransform
        || out.raster.cols != g.width
        || out.raster.rows != g.height
    {
        return Err(MapError::Terrain(
            "warp output grid differs from dest_grid".into(),
        ));
    }
    match out.raster.data {
        terrio::raster::RasterData::F32(v) => Ok(v),
        _ => Err(MapError::Terrain("warp output not float32".into())),
    }
}

pub fn lookup_key(
    rows: usize,
    cols: usize,
    gt: [f64; 6],
    env: &WarpEnv,
    n: &Nudge,
    g: &DestGrid,
) -> String {
    let bits = |a: &[f64]| {
        a.iter()
            .map(|v| format!("{:016x}", v.to_bits()))
            .collect::<Vec<_>>()
            .join(",")
    };
    let h = |s: &str| format!("{:016x}", crate::sink::fnv1a64(s.as_bytes()));
    format!(
        "terrio=0.4.2;nearest;f32;src_nodata=nan;dst_nodata=auto;src={rows}x{cols}@{};src_srs={};dst_srs={};dst={}x{}@{};et={:016x};wm={:016x}",
        bits(&gt),
        h(&env.src_srs_wkt),
        h(&env.dst_srs_wkt),
        g.width,
        g.height,
        bits(&g.geotransform),
        n.error_threshold.to_bits(),
        n.memory_limit_bytes.to_bits()
    )
}

/// Number of f32 index passes needed for `total` source pixels at `pass_bits` bits per pass.
/// Every warped value must be an f32 integer below `2**pass_bits <= 2**24` (exact in f32), and
/// the combined index must stay below the `NONE` sentinel.
pub fn lookup_passes(total: usize, pass_bits: u32) -> Result<u32, MapError> {
    if !(1..=LOOKUP_PASS_BITS).contains(&pass_bits) {
        return Err(MapError::Invalid(format!(
            "lookup pass bits {pass_bits} outside 1..=24"
        )));
    }
    if total == 0 || total as u64 >= NONE as u64 {
        return Err(MapError::Budget(format!(
            "source grid of {total} pixels cannot be encoded below the u32 lookup sentinel"
        )));
    }
    let bits = 64 - (total as u64 - 1).max(1).leading_zeros();
    Ok(bits.div_ceil(pass_bits).max(1))
}

/// Builds the lookup with the same dtype, nodata declaration, grids and options as the product
/// warps, so chunking and approximation are identical. Indices are split in `pass_bits` passes
/// (24 in production) so every warped value is an exactly representable f32 integer; every pass
/// must agree on coverage and every value must be an exact in-range integer.
pub fn build_lookup_with(
    rows: usize,
    cols: usize,
    gt: [f64; 6],
    env: &WarpEnv,
    n: &Nudge,
    g: &DestGrid,
    pass_bits: u32,
) -> Result<Lookup, MapError> {
    let t0 = Instant::now();
    let total = rows * cols;
    let passes = lookup_passes(total, pass_bits)?;
    let digit = 1u64 << pass_bits;
    let mut index = vec![0u32; g.width * g.height];
    let mut covered: Option<Vec<bool>> = None;
    for pass in 0..passes {
        let shift = pass * pass_bits;
        let field: Vec<f32> = (0..total as u64)
            .map(|i| ((i >> shift) & (digit - 1)) as f32)
            .collect();
        let out = warp_field(field, rows, cols, gt, env, n, g)?;
        let cov = covered.get_or_insert_with(|| out.iter().map(|v| !v.is_nan()).collect());
        for ((slot, v), c) in index.iter_mut().zip(out).zip(cov.iter()) {
            if v.is_nan() == *c {
                return Err(MapError::Terrain(
                    "lookup passes disagree on coverage".into(),
                ));
            }
            if v.is_nan() {
                continue;
            }
            if !(v >= 0.0 && (v as f64) < digit as f64 && v.fract() == 0.0) {
                return Err(MapError::Terrain(format!(
                    "lookup value {v} is not an exact pass digit"
                )));
            }
            *slot |= (v as u32) << shift;
        }
    }
    let cov = covered.expect("at least one pass");
    for (slot, c) in index.iter_mut().zip(cov) {
        if !c {
            *slot = NONE;
        } else if *slot as usize >= total {
            return Err(MapError::Terrain("lookup index out of range".into()));
        }
    }
    Ok(Lookup {
        key: lookup_key(rows, cols, gt, env, n, g),
        index,
        passes,
        build_seconds: t0.elapsed().as_secs_f64(),
    })
}

pub fn build_lookup(
    rows: usize,
    cols: usize,
    gt: [f64; 6],
    env: &WarpEnv,
    n: &Nudge,
    g: &DestGrid,
) -> Result<Lookup, MapError> {
    build_lookup_with(rows, cols, gt, env, n, g, LOOKUP_PASS_BITS)
}

/// Lookup retention across profiles, bounded by an explicit resident byte budget (oldest evicted
/// first). Budget 0 (the default) retains nothing: each profile builds, uses and drops its lookup.
#[derive(Default)]
pub struct LookupCache {
    entries: Vec<Arc<Lookup>>,
    pub budget: u64,
    pub resident_bytes: u64,
    pub peak_resident_bytes: u64,
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
    pub not_retained: u64,
}

pub fn lookup_bytes(l: &Lookup) -> u64 {
    l.index.len() as u64 * 4 + l.key.len() as u64
}

impl LookupCache {
    pub fn with_budget(budget: u64) -> Self {
        Self {
            budget,
            ..Default::default()
        }
    }
    pub fn get(&mut self, key: &str) -> Option<Arc<Lookup>> {
        let hit = self.entries.iter().find(|e| e.key == key).cloned();
        if hit.is_some() {
            self.hits += 1;
        } else {
            self.misses += 1;
        }
        hit
    }
    pub fn insert(&mut self, l: Arc<Lookup>) {
        if self.entries.iter().any(|e| e.key == l.key) {
            return;
        }
        let b = lookup_bytes(&l);
        if b > self.budget {
            self.not_retained += 1;
            return;
        }
        while self.resident_bytes + b > self.budget && !self.entries.is_empty() {
            let old = self.entries.remove(0);
            self.resident_bytes -= lookup_bytes(&old);
            self.evictions += 1;
        }
        self.resident_bytes += b;
        self.peak_resident_bytes = self.peak_resident_bytes.max(self.resident_bytes);
        self.entries.push(l);
    }
}

/// Planned peak bytes of one profile, computed from metadata before any array is read or
/// allocated. Terms are explicit upper estimates of this implementation's own arrays. terrio's
/// internal warp staging is approximated by one chunk memory limit (`warp_chunk_allowance`) plus
/// its full output buffer (`lookup_transient` / `full_warp_transient`); it is not measured.
#[derive(Debug, Clone, Serialize)]
pub struct MemoryPlan {
    pub inputs: u64,
    pub guarded_index: u64,
    pub lookup_index: u64,
    pub lookup_transient: u64,
    pub needed_set: u64,
    pub per_pixel_stages: u64,
    pub full_grids: u64,
    pub full_warp_transient: u64,
    pub aoi_outputs: u64,
    pub warp_chunk_allowance: u64,
    pub total: u64,
}

pub fn plan_memory(
    meta: &InputsJson,
    g: &DestGrid,
    nudge: &Nudge,
    full: bool,
    max_aoi_px: u64,
    aoi_px_sum: u64,
) -> Result<MemoryPlan, MapError> {
    let src = (meta.rows * meta.cols) as u64;
    let dest = (g.width * g.height) as u64;
    let lookup = nudge.method == NudgeMethod::Lookup;
    if lookup {
        lookup_passes(meta.rows * meta.cols, LOOKUP_PASS_BITS)?;
    }
    // Pixels evaluated: the full grid, or at most one source pixel per AOI destination pixel.
    let evaluated = if full { src } else { src.min(aoi_px_sum) };
    let mut p = MemoryPlan {
        inputs: Inputs::planned_bytes(meta),
        guarded_index: meta.delaunay.nsimplex as u64 * 72,
        lookup_index: if lookup { dest * 4 } else { 0 },
        // One pass at a time: source index field f32 + warp output f32 + coverage flags.
        lookup_transient: if lookup { src * 4 + dest * 4 + dest } else { 0 },
        needed_set: if full {
            src * 4 * 2
        } else {
            src.div_ceil(64) * 8 + evaluated * 4 * 2
        },
        // raw f64 + PixelStages (24 B) + per-pixel result staging (<= 48 B).
        per_pixel_stages: evaluated * (8 + 24 + 48),
        // raw f64, ground/06/07/08 f32 on the full 01 grid.
        full_grids: if full { src * (8 + 4 * 4) } else { 0 },
        // Two destination f32 warp outputs held together plus one moved source field.
        full_warp_transient: if nudge.method == NudgeMethod::FullWarp {
            dest * 4 * 2 + src * 4
        } else {
            0
        },
        // depth/wse f32 + their byte copies + optional polygon mask, for the largest AOI.
        aoi_outputs: max_aoi_px * (4 * 2 + 4 * 2 + 1),
        warp_chunk_allowance: nudge.memory_limit_bytes.ceil() as u64,
        total: 0,
    };
    let terms = [
        p.inputs,
        p.guarded_index,
        p.lookup_index,
        p.lookup_transient,
        p.needed_set,
        p.per_pixel_stages,
        p.full_grids,
        p.full_warp_transient,
        p.aoi_outputs,
        p.warp_chunk_allowance,
    ];
    p.total = terms
        .iter()
        .try_fold(0u64, |a, b| a.checked_add(*b))
        .ok_or_else(|| MapError::Budget("memory plan overflow".into()))?;
    Ok(p)
}

pub struct Session<'a> {
    pub req: &'a Request,
    pub base: PathBuf,
    /// One shared terrain reader and decoded-block cache for every in-flight profile.
    pub terrain: NativeTerrain,
    pub env: WarpEnv,
    /// One lookup cache with one aggregate resident budget, shared by all in-flight profiles.
    pub lookups: Mutex<LookupCache>,
    pub inflight: InFlight,
}

/// Instrumentation of concurrent profiles: active count and planned bytes (not RSS).
#[derive(Default)]
pub struct InFlight {
    pub active: AtomicUsize,
    pub peak_active: AtomicUsize,
    pub planned: AtomicU64,
    pub peak_planned: AtomicU64,
}

/// Holds one profile's slot (and, once known, its planned bytes) while it runs.
struct ActiveGuard<'a> {
    f: &'a InFlight,
    planned: u64,
}

impl<'a> ActiveGuard<'a> {
    fn enter(f: &'a InFlight) -> Self {
        let now = f.active.fetch_add(1, Ordering::SeqCst) + 1;
        f.peak_active.fetch_max(now, Ordering::SeqCst);
        Self { f, planned: 0 }
    }
    fn plan(&mut self, bytes: u64) {
        self.planned = bytes;
        let now = self.f.planned.fetch_add(bytes, Ordering::SeqCst) + bytes;
        self.f.peak_planned.fetch_max(now, Ordering::SeqCst);
    }
}

impl Drop for ActiveGuard<'_> {
    fn drop(&mut self) {
        self.f.planned.fetch_sub(self.planned, Ordering::SeqCst);
        self.f.active.fetch_sub(1, Ordering::SeqCst);
    }
}

fn lock<T>(m: &Mutex<T>) -> std::sync::MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|e| e.into_inner())
}

fn resolve(base: &Path, p: &str) -> PathBuf {
    let p = PathBuf::from(p);
    if p.is_absolute() { p } else { base.join(p) }
}

impl<'a> Session<'a> {
    pub fn open(req: &'a Request, base: &Path) -> Result<Self, MapError> {
        let tpath = resolve(base, &req.terrain.path);
        let tstr = tpath
            .to_str()
            .ok_or_else(|| MapError::Invalid("terrain path not UTF-8".into()))?;
        let terrain = NativeTerrain::open(
            tstr,
            req.terrain.epsg,
            &req.terrain.crs_identity,
            QueryConvention::PixelCenter,
            NodataPolicy::RawValue,
            req.budgets.max_cache_bytes,
        )?;
        if (req.budgets.threads as u64) * terrain.max_block_bytes() > req.budgets.max_cache_bytes {
            return Err(MapError::Budget(
                "max_cache_bytes below threads x one terrain block".into(),
            ));
        }
        let src_srs = match &req.source_crs {
            SourceCrs::Terrain => terrio::LazyRaster::open_tiff(tstr)
                .map_err(|e| MapError::Terrain(e.to_string()))?
                .ok_or_else(|| MapError::Unsupported("terrain not a TIFF".into()))?
                .crs(),
            SourceCrs::Epsg { code } => terrio::crs::SpatialRef::parse(&format!("EPSG:{code}"))
                .map_err(|e| MapError::Invalid(format!("source_crs: {e}")))?,
        };
        let dst_srs = terrio::crs::SpatialRef::parse(&format!("EPSG:{}", req.nudge.dst_epsg))
            .map_err(|e| MapError::Invalid(format!("dst_epsg: {e}")))?;
        let env = WarpEnv {
            src_srs_wkt: src_srs.to_wkt().unwrap_or_default(),
            dst_srs_wkt: dst_srs.to_wkt().unwrap_or_default(),
            src_srs,
            dst_srs,
        };
        Ok(Self {
            req,
            base: base.to_path_buf(),
            terrain,
            env,
            lookups: Mutex::new(LookupCache::with_budget(req.budgets.max_lookup_cache_bytes)),
            inflight: InFlight::default(),
        })
    }
}

/// Per-pixel interpolation result for a sorted set of 01-grid linear indices.
struct Interpolated {
    raw: Vec<f64>,
    selection_used: &'static str,
    ambiguous: u64,
    walk: Option<WalkStats>,
}

fn interpolate(
    inp: &Inputs,
    needed: &[u32],
    selection: Selection,
) -> Result<Interpolated, MapError> {
    let d = &inp.delaunay;
    let serial = |reason: &'static str, ambiguous: u64| {
        let mut raw = vec![f64::NAN; needed.len()];
        let mut k = 0usize;
        let cols = inp.cols;
        let st = d.evaluate_serial(&inp.x_axis, &inp.y_axis, |r, c, v| {
            let lin = (r * cols + c) as u32;
            if k < needed.len() && needed[k] == lin {
                raw[k] = v.map_or(f64::NAN, |(_, z)| z);
                k += 1;
            }
        });
        Interpolated {
            raw,
            selection_used: reason,
            ambiguous,
            walk: Some(st),
        }
    };
    let guarded_ok = d.guarded_allowed();
    match selection {
        Selection::ScipyWalkSerial => return Ok(serial("scipy_walk_serial", 0)),
        Selection::GuardedParallel if !guarded_ok => {
            return Err(MapError::Unsupported(
                "guarded_parallel: degenerate simplices present".into(),
            ));
        }
        Selection::Auto if !guarded_ok => {
            return Ok(serial("scipy_walk_serial (auto: degenerate simplices)", 0));
        }
        _ => {}
    }
    let located: Vec<Located> = needed
        .par_iter()
        .map(|lin| {
            let (r, c) = (*lin as usize / inp.cols, *lin as usize % inp.cols);
            d.locate_guarded([inp.x_axis[c], inp.y_axis[r]])
        })
        .collect();
    let ambiguous = located
        .iter()
        .filter(|l| matches!(l, Located::Ambiguous))
        .count() as u64;
    if ambiguous > 0 {
        if selection == Selection::GuardedParallel {
            return Err(MapError::Unsupported(format!(
                "guarded_parallel: {ambiguous} order-dependent pixels"
            )));
        }
        return Ok(serial(
            "scipy_walk_serial (auto: ambiguous pixels)",
            ambiguous,
        ));
    }
    let raw = located
        .into_iter()
        .map(|l| match l {
            Located::Value { value, .. } => value,
            _ => f64::NAN,
        })
        .collect();
    Ok(Interpolated {
        raw,
        selection_used: "guarded_parallel",
        ambiguous: 0,
        walk: None,
    })
}

fn write_atomic_unit(dir: &Path, files: &[(&str, Vec<u8>)], unit: &Value) -> Result<(), MapError> {
    let tmp = dir.with_extension("partial");
    fs::create_dir_all(&tmp)?;
    for (name, bytes) in files {
        fs::write(tmp.join(name), bytes)?;
    }
    crate::sink::write_json(&tmp.join("unit.json"), unit)?;
    fs::rename(&tmp, dir)?;
    Ok(())
}

fn f32_bytes(v: &[f32]) -> Vec<u8> {
    v.iter().flat_map(|x| x.to_le_bytes()).collect()
}

/// Runs one profile. Writes its units and stages; returns the profile report.
pub fn run_profile(s: &Session, p: &Profile, out: &Path) -> Result<Value, MapError> {
    let mut slot = ActiveGuard::enter(&s.inflight);
    let t_all = Instant::now();
    let req = s.req;
    let dir = resolve(&s.base, &p.inputs_dir);
    let meta = Inputs::load_meta(&dir)?;
    let (rows, cols) = (meta.rows, meta.cols);
    let total = rows * cols;
    let g = &p.dest_grid;
    let full = req.nudge.method == NudgeMethod::FullWarp || !req.stages.is_empty();
    // Budget before any array allocation (r1 QA M2), including lookup and warp transients.
    let windows: Vec<Option<[usize; 4]>> = p.aois.iter().map(|a| aoi_window(g, a)).collect();
    let aoi_px: u64 = windows
        .iter()
        .flatten()
        .map(|w| (w[2] * w[3]) as u64)
        .max()
        .unwrap_or(0);
    let aoi_sum: u64 = windows.iter().flatten().map(|w| (w[2] * w[3]) as u64).sum();
    let plan = plan_memory(&meta, g, &req.nudge, full, aoi_px, aoi_sum)?;
    let planned = plan.total;
    slot.plan(planned);
    if planned > req.budgets.max_profile_bytes {
        return Err(MapError::Budget(format!(
            "profile {}: planned {planned} bytes > max_profile_bytes {} (plan {:?})",
            p.id, req.budgets.max_profile_bytes, plan
        )));
    }
    let t0 = Instant::now();
    let mut inp = Inputs::load(&dir, &meta)?;
    // Upstream's 03 crop to terrain bounds must be a no-op.
    let gt = inp.gt();
    let tg = s.terrain.gt;
    let (tx0, tx1) = (tg[0], tg[0] + tg[1] * s.terrain.width as f64);
    let (ty1, ty0) = (tg[3], tg[3] + tg[5] * s.terrain.height as f64);
    let (gx1, gy1) = (gt[0] + gt[1] * cols as f64, gt[3] + gt[5] * rows as f64);
    if gt[0] < tx0 || gx1 > tx1 || gt[3] < ty0 || gy1 > ty1 {
        return Err(MapError::Unsupported(format!(
            "profile {}: 01 grid extends beyond the terrain (upstream 03 crop would change it)",
            p.id
        )));
    }
    if inp.delaunay.guarded_allowed() && req.interpolation.selection != Selection::ScipyWalkSerial {
        inp.delaunay.build_index();
    }
    let load_s = t0.elapsed().as_secs_f64();

    // Needed 01-grid pixels.
    let t1 = Instant::now();
    let mut lookup_info = json!(null);
    let lookup: Option<Arc<Lookup>> = if req.nudge.method == NudgeMethod::Lookup {
        let key = lookup_key(rows, cols, gt, &s.env, &req.nudge, g);
        // The lock is held only for lookup/insert; builds run unlocked (a concurrent duplicate
        // build of the same key is possible and harmless: `insert` keeps one copy).
        let found = lock(&s.lookups).get(&key);
        let (l, cached) = match found {
            Some(l) => (l, true),
            None => {
                let l = Arc::new(build_lookup(rows, cols, gt, &s.env, &req.nudge, g)?);
                lock(&s.lookups).insert(l.clone());
                (l, false)
            }
        };
        // Full-grid preparation cost: independent of the AOI size (recorded, not hidden).
        lookup_info = json!({"key_fnv1a64": format!("{:016x}", crate::sink::fnv1a64(l.key.as_bytes())), "passes": l.passes,
            "reused_from_cache": cached, "build_seconds_diagnostic": if cached { 0.0 } else { l.build_seconds },
            "full_grid_prep": {"source_pixels_encoded": total, "dest_pixels_warped_per_pass": g.width * g.height,
                               "passes": l.passes, "lookup_bytes": lookup_bytes(&l),
                               "note": "geometry-only native warp of the full source/destination grids; required even for a small AOI"},
            "covered_dest_pixels": l.index.iter().filter(|i| **i != NONE).count()});
        Some(l)
    } else {
        None
    };
    let lookup_s = t1.elapsed().as_secs_f64();
    let needed: Vec<u32> = if full {
        (0..total as u32).collect()
    } else {
        let l = lookup.as_ref().expect("lookup");
        let mut bits = vec![0u64; total.div_ceil(64)];
        for w in windows.iter().flatten() {
            for r in w[1]..w[1] + w[3] {
                for c in w[0]..w[0] + w[2] {
                    let i = l.index[r * g.width + c];
                    if i != NONE {
                        bits[i as usize / 64] |= 1 << (i % 64);
                    }
                }
            }
        }
        // Only wet pixels need interpolation: dry ones are NaN in 03 and every later stage.
        (0..total as u32)
            .filter(|i| bits[*i as usize / 64] >> (i % 64) & 1 == 1 && inp.mask[*i as usize] == 1)
            .collect()
    };

    // Interpolation (01) on needed wet pixels, then 03 mask.
    let t2 = Instant::now();
    let interp_set: Vec<u32> = if full {
        needed
            .iter()
            .copied()
            .filter(|i| inp.mask[*i as usize] == 1)
            .collect()
    } else {
        needed.clone()
    };
    let it = interpolate(&inp, &interp_set, req.interpolation.selection)?;
    let interp_s = t2.elapsed().as_secs_f64();

    // 05 + 06/07/08 at the interpolated pixels (and 05 everywhere when the stage is requested).
    let t3 = Instant::now();
    let terrain = &s.terrain;
    let staged: Vec<Result<(PixelStages, TerrainCounters), MapError>> = interp_set
        .par_iter()
        .zip(it.raw.par_iter())
        .map(|(lin, raw)| {
            let mut tc = TerrainCounters::default();
            let (r, c) = (*lin as usize / cols, *lin as usize % cols);
            let raw03 = if raw.is_finite() { *raw } else { f64::NAN };
            if raw03.is_nan() {
                return Ok((
                    PixelStages {
                        raw03,
                        ground05: f32::NAN,
                        d06: f32::NAN,
                        d07: f32::NAN,
                        w08: f32::NAN,
                    },
                    tc,
                ));
            }
            let g05 = ground_at(terrain, &inp, r, c, &mut tc)?;
            if g05.is_nan() {
                return Err(MapError::Unsupported(format!(
                    "terrain NaN under wet pixel (row {r}, col {c}); no oracle"
                )));
            }
            if terrain.is_sentinel(g05) {
                tc.raw_sentinel_under_wet += 1;
            }
            Ok((float_stages(raw03, g05)?, tc))
        })
        .collect();
    let mut tc = TerrainCounters::default();
    let mut px: Vec<PixelStages> = Vec::with_capacity(staged.len());
    for r in staged {
        let (p5, c) = r?;
        tc.sampled += c.sampled;
        tc.outside += c.outside;
        tc.near_boundary += c.near_boundary;
        tc.raw_sentinel_under_wet += c.raw_sentinel_under_wet;
        px.push(p5);
    }
    let stage_s = t3.elapsed().as_secs_f64();

    // Optional full-grid stage products.
    let t4 = Instant::now();
    let mut d07_full: Option<Vec<f32>> = None;
    let mut w08_full: Option<Vec<f32>> = None;
    if full {
        let mut raw = vec![f64::NAN; total];
        let mut g05 = vec![f32::NAN; total];
        let (mut d6, mut d7, mut w8) = (
            vec![f32::NAN; total],
            vec![f32::NAN; total],
            vec![f32::NAN; total],
        );
        for (lin, v) in interp_set.iter().zip(&px) {
            let i = *lin as usize;
            raw[i] = v.raw03;
            g05[i] = v.ground05;
            d6[i] = v.d06;
            d7[i] = v.d07;
            w8[i] = v.w08;
        }
        if req.stages.iter().any(|x| x == "05") {
            // 05 is the whole terrain-aligned field, wet or not.
            let filled: Vec<Result<f32, MapError>> = (0..total)
                .into_par_iter()
                .map(|i| {
                    if g05[i].is_nan() {
                        ground_at(
                            terrain,
                            &inp,
                            i / cols,
                            i % cols,
                            &mut TerrainCounters::default(),
                        )
                    } else {
                        Ok(g05[i])
                    }
                })
                .collect();
            for (i, v) in filled.into_iter().enumerate() {
                g05[i] = v?;
            }
            // Dry 06 = f32(NaN - g) = NaN, consistent with upstream.
        }
        if !req.stages.is_empty() {
            let sd = out.join("stages").join(&p.id);
            let tmp = sd.with_extension("partial");
            fs::create_dir_all(&tmp)?;
            for st in &req.stages {
                let bytes = match st.as_str() {
                    "03" => raw.iter().flat_map(|x| x.to_le_bytes()).collect(),
                    "05" => f32_bytes(&g05),
                    "06" => f32_bytes(&d6),
                    "07" => f32_bytes(&d7),
                    _ => f32_bytes(&w8),
                };
                fs::write(tmp.join(format!("{st}.bin")), bytes)?;
            }
            crate::sink::write_json(
                &tmp.join("stages.json"),
                &json!({"schema": "ras2fim-step05-stages/1", "profile": p.id,
                "rows": rows, "cols": cols, "raster_geotransform": gt, "dtypes": {"03": "<f8", "05": "<f4", "06": "<f4", "07": "<f4", "08": "<f4"},
                "written": req.stages}),
            )?;
            if let Some(parent) = sd.parent() {
                fs::create_dir_all(parent)?;
            }
            fs::rename(&tmp, &sd)?;
        }
        d07_full = Some(d7);
        w08_full = Some(w8);
    }
    let stages_write_s = t4.elapsed().as_secs_f64();

    // 09/10 on the destination grid.
    let t5 = Instant::now();
    let (dest_depth, dest_wse): (Option<Vec<f32>>, Option<Vec<f32>>) =
        if req.nudge.method == NudgeMethod::FullWarp {
            let d7 = d07_full.take().expect("full");
            let w8 = w08_full.take().expect("full");
            (
                Some(warp_field(d7, rows, cols, gt, &s.env, &req.nudge, g)?),
                Some(warp_field(w8, rows, cols, gt, &s.env, &req.nudge, g)?),
            )
        } else {
            (None, None)
        };
    let warp_s = t5.elapsed().as_secs_f64();

    let t6 = Instant::now();
    let mut units = Vec::new();
    let pos = |lin: u32| interp_set.binary_search(&lin).ok();
    for (a, win) in p.aois.iter().zip(&windows) {
        let udir = out.join("units").join(&p.id).join(&a.id);
        fs::create_dir_all(udir.parent().expect("parent"))?;
        let Some(w) = *win else {
            write_atomic_unit(
                &udir,
                &[],
                &json!({"schema": "ras2fim-step05-unit/1", "profile": p.id, "aoi": a.id, "status": "empty_window"}),
            )?;
            units.push(json!({"aoi": a.id, "status": "empty_window"}));
            continue;
        };
        let n = w[2] * w[3];
        let mask: Option<Vec<u8>> = match &a.mask_u8 {
            Some(m) => {
                let mp = resolve(&s.base, m);
                let b =
                    fs::read(&mp).map_err(|e| MapError::Io(format!("{}: {e}", mp.display())))?;
                if b.len() != n || b.iter().any(|v| *v > 1) {
                    return Err(MapError::Invalid(format!(
                        "aoi {}: mask_u8 must be {}x{} bytes of 0/1",
                        a.id, w[3], w[2]
                    )));
                }
                Some(b)
            }
            None => None,
        };
        let mut depth = vec![f32::NAN; n];
        let mut wse = vec![f32::NAN; n];
        for rr in 0..w[3] {
            for cc in 0..w[2] {
                let k = rr * w[2] + cc;
                if mask.as_ref().is_some_and(|m| m[k] == 0) {
                    continue;
                }
                let di = (w[1] + rr) * g.width + w[0] + cc;
                if let (Some(dd), Some(ww)) = (&dest_depth, &dest_wse) {
                    depth[k] = dd[di];
                    wse[k] = ww[di];
                } else if let Some(l) = &lookup {
                    let src = l.index[di];
                    if src != NONE
                        && let Some(j) = pos(src)
                    {
                        depth[k] = px[j].d07;
                        wse[k] = px[j].w08;
                    }
                }
            }
        }
        let wgt = [
            g.geotransform[0] + w[0] as f64 * g.geotransform[1],
            g.geotransform[1],
            0.0,
            g.geotransform[3] + w[1] as f64 * g.geotransform[5],
            0.0,
            g.geotransform[5],
        ];
        let (db, wb) = (f32_bytes(&depth), f32_bytes(&wse));
        let unit = json!({"schema": "ras2fim-step05-unit/1", "profile": p.id, "aoi": a.id, "status": "complete",
            "window": w, "window_geotransform": wgt, "crs_epsg": req.nudge.dst_epsg, "dtype": "<f4", "nodata": "nan",
            "width": w[2], "height": w[3], "polygon_mask_applied": mask.is_some(),
            "finite_counts": {"depth": depth.iter().filter(|v| v.is_finite()).count(), "wse": wse.iter().filter(|v| v.is_finite()).count()},
            "fnv1a64": {"depth.f32": format!("{:016x}", crate::sink::fnv1a64(&db)), "wse.f32": format!("{:016x}", crate::sink::fnv1a64(&wb))}});
        write_atomic_unit(&udir, &[("depth.f32", db), ("wse.f32", wb)], &unit)?;
        units.push(json!({"aoi": a.id, "status": "complete", "window": w}));
    }
    let gather_s = t6.elapsed().as_secs_f64();
    Ok(json!({
        "id": p.id, "status": "complete", "rows": rows, "cols": cols, "dest_grid": g,
        "selection_requested": req.interpolation.selection, "selection_used": it.selection_used,
        "ambiguous_pixels": it.ambiguous, "degenerate_simplices": inp.delaunay.degenerate,
        "walk": it.walk, "source_pixels_needed": needed.len(), "source_pixels_interpolated": interp_set.len(),
        "source_pixels_total": total, "terrain": tc, "lookup": lookup_info, "memory_plan": plan,
        "units": units,
        "timings_diagnostic_seconds": {"load": load_s, "lookup": lookup_s, "interpolate": interp_s, "terrain_and_float32": stage_s,
            "stage_writes": stages_write_s, "warp": warp_s, "gather_and_write": gather_s, "total": t_all.elapsed().as_secs_f64()}
    }))
}

pub fn method_record() -> Value {
    json!({
        "method_version": METHOD,
        "upstream": "andycarter-pe/ras2fim-2d @3146f647 generate_depth_wsel_rasters_mp_05.py",
        "axes": "exact caller-supplied np.arange query axes; never x0 + i*res; raster affine separate",
        "interpolation": "exact SciPy LinearNDInterpolator port over caller-supplied Delaunay (transform, neighbors, equations, paraboloid, bounds); serial walk or guarded order-independent evaluation with automatic serial fallback",
        "mask": "caller-supplied wet mask (rasterio.mask equivalent, Python adapter)",
        "terrain_05": "native terrio GeoTIFF; raster-01 pixel centres x0+(c+0.5)*res; floor((x-gt0)/gt1); outside = declared nodata; raw sentinel kept",
        "float32": "06=f32(f64(03)-f64(05)); 07=06<0->NaN after cast; 08=f32(f64(05)+f64(07)) where 07 finite",
        "nudge": "terrio 0.4.2 native warp, nearest, explicit dest grid, approximate transformer (error_threshold), GDAL-style chunks (memory_limit); lookup = same-config f32 index warp in 24-bit passes",
        "aoi": "selects destination pixels only; global inputs, grid and chunks unchanged; output = crop(full) by construction; optional caller polygon mask",
        "not_in_engine": ["sample preparation", "Qhull/SciPy Delaunay", "wet union rasterization", "dest grid derivation", "product 11"]
    })
}

fn profile_result(r: Result<Value, MapError>, p: &Profile) -> Value {
    r.unwrap_or_else(
        |e| json!({"id": p.id, "status": "failed", "error_kind": e.kind(), "error": e.to_string()}),
    )
}

/// Runs the profiles: one at a time by default, or up to `max_inflight_profiles` concurrently.
///
/// Concurrency is a sliding window of `k` tasks spawned in the session's single Rayon pool; each
/// claims the next profile index in request order. Every profile's inner parallel work runs in the
/// same pool (work-stealing), so concurrent profiles never add OS threads beyond
/// `budgets.threads`. All profiles share one `NativeTerrain` (one decoded-block cache under
/// `max_cache_bytes`) and one lookup cache under `max_lookup_cache_bytes`. Results are reported in
/// request order; a failing profile writes no units and does not stop the others.
pub fn run(req: &Request, base: &Path, out: &Path) -> Result<Value, MapError> {
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(req.budgets.threads)
        .thread_name(|i| format!("ras2fim-step05-{i}"))
        .build()
        .map_err(|e| MapError::Invalid(e.to_string()))?;
    fs::create_dir(out).map_err(|e| MapError::Io(format!("{}: {e}", out.display())))?;
    let t0 = Instant::now();
    let k = req
        .budgets
        .max_inflight_profiles
        .min(req.profiles.len())
        .max(1);
    // Planned (not measured) per-profile peaks, for the aggregate estimate of k in flight.
    let mut plans: Vec<u64> = req
        .profiles
        .iter()
        .map(|p| {
            let dir = resolve(base, &p.inputs_dir);
            Inputs::load_meta(&dir)
                .and_then(|m| {
                    let ws: Vec<[usize; 4]> = p
                        .aois
                        .iter()
                        .filter_map(|a| aoi_window(&p.dest_grid, a))
                        .collect();
                    let mx = ws.iter().map(|w| (w[2] * w[3]) as u64).max().unwrap_or(0);
                    let sum = ws.iter().map(|w| (w[2] * w[3]) as u64).sum();
                    let full = req.nudge.method == NudgeMethod::FullWarp || !req.stages.is_empty();
                    plan_memory(&m, &p.dest_grid, &req.nudge, full, mx, sum)
                })
                .map(|pl| pl.total.min(req.budgets.max_profile_bytes))
                .unwrap_or(0)
        })
        .collect();
    plans.sort_unstable_by(|a, b| b.cmp(a));
    let top_k: u64 = plans.iter().take(k).sum();
    pool.install(|| {
        let s = Session::open(req, base)?;
        let profiles: Vec<Value> = if k == 1 {
            req.profiles.iter().map(|p| profile_result(run_profile(&s, p, out), p)).collect()
        } else {
            let next = AtomicUsize::new(0);
            let slots: Vec<Mutex<Option<Value>>> = req.profiles.iter().map(|_| Mutex::new(None)).collect();
            rayon::scope(|sc| {
                for _ in 0..k {
                    sc.spawn(|_| {
                        loop {
                            let i = next.fetch_add(1, Ordering::SeqCst);
                            let Some(p) = req.profiles.get(i) else { break };
                            let r = profile_result(run_profile(&s, p, out), p);
                            *lock(&slots[i]) = Some(r);
                        }
                    });
                }
            });
            slots
                .into_iter()
                .zip(&req.profiles)
                .map(|(m, p)| {
                    m.into_inner()
                        .unwrap_or_else(|e| e.into_inner())
                        .unwrap_or_else(|| json!({"id": p.id, "status": "failed", "error_kind": "internal", "error": "profile not run"}))
                })
                .collect()
        };
        let failed = profiles.iter().filter(|v| v["status"] != "complete").count();
        let peak_active = s.inflight.peak_active.load(Ordering::SeqCst);
        let lc = lock(&s.lookups);
        Ok(json!({
            "schema": "ras2fim-step05-report/1",
            "status": if failed == 0 { "complete" } else { "failed" },
            "method": method_record(),
            "request": req,
            "concurrency": {
                "requested_max_inflight_profiles": req.budgets.max_inflight_profiles,
                "effective_max_inflight_profiles": k,
                "peak_active_profiles": peak_active,
                "active_bound_respected": peak_active <= k,
                "scheduler": if k == 1 { "sequential, request order" } else { "sliding window of k tasks in the single Rayon pool; profiles claimed in request order; report in request order" },
                "threads": req.budgets.threads,
                "shared": "one NativeTerrain decoded-block cache; one lookup cache (aggregate budget); one thread pool"
            },
            "memory_bounds": {
                "per_profile_limit_bytes": req.budgets.max_profile_bytes,
                "estimated_aggregate_planned_bytes_k_largest": top_k,
                "observed_peak_inflight_planned_bytes": s.inflight.peak_planned.load(Ordering::SeqCst),
                "terrain_cache_budget_bytes": req.budgets.max_cache_bytes,
                "lookup_cache_budget_bytes": req.budgets.max_lookup_cache_bytes,
                "estimated_aggregate_bound_bytes": top_k + req.budgets.max_cache_bytes + req.budgets.max_lookup_cache_bytes,
                "note": "planned estimates of this implementation's arrays plus configured cache budgets; not a measured or enforced RSS cap"
            },
            "terrain": {"path": s.terrain.path, "stats": s.terrain.stats(), "crs_identity": s.terrain.crs_identity},
            "warp_env": {"src_srs_wkt_fnv1a64": format!("{:016x}", crate::sink::fnv1a64(s.env.src_srs_wkt.as_bytes())),
                         "dst_srs_wkt_fnv1a64": format!("{:016x}", crate::sink::fnv1a64(s.env.dst_srs_wkt.as_bytes()))},
            "lookup_cache": {"budget_bytes": lc.budget, "resident_bytes": lc.resident_bytes,
                "peak_resident_bytes": lc.peak_resident_bytes, "hits": lc.hits, "misses": lc.misses,
                "evictions": lc.evictions, "not_retained": lc.not_retained},
            "profiles": profiles,
            "total_wall_seconds_diagnostic": t0.elapsed().as_secs_f64(),
        }))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn float_stage_policy() {
        let p = float_stages(10.0, 9.5).unwrap();
        assert_eq!(p.d06, 0.5);
        assert_eq!(p.w08, 10.0);
        let n = float_stages(9.0, 9.5).unwrap();
        assert!(n.d07.is_nan() && n.w08.is_nan() && n.d06 == -0.5);
        let z = float_stages(9.5, 9.5).unwrap();
        assert_eq!(z.d07.to_bits(), 0.0f32.to_bits());
        // Tiny positive f64 difference rounds to a positive f32 and stays wet.
        let t = float_stages(554.5000000000001, 554.5).unwrap();
        assert!(t.d07 > 0.0);
        // Negative tiny difference: cast first, then the sign test.
        let u = float_stages(554.4999999999999, 554.5).unwrap();
        assert!(u.d07.is_nan());
        // Raw sentinel subtracted as a number (upstream).
        let s = float_stages(500.0, -9999.0).unwrap();
        assert_eq!(s.d07, 10499.0);
        assert!(float_stages(1e300, 0.0).is_err());
    }

    #[test]
    fn aoi_windows() {
        let g = DestGrid {
            geotransform: [0.0, 1.0, 0.0, 10.0, 0.0, -1.0],
            width: 10,
            height: 10,
        };
        let a = |w: Option<[i64; 4]>, b: Option<[f64; 4]>| Aoi {
            id: "a".into(),
            window: w,
            bounds: b,
            mask_u8: None,
        };
        assert_eq!(aoi_window(&g, &a(None, None)), Some([0, 0, 10, 10]));
        assert_eq!(
            aoi_window(&g, &a(Some([8, 8, 5, 5]), None)),
            Some([8, 8, 2, 2])
        );
        assert_eq!(aoi_window(&g, &a(Some([20, 0, 5, 5]), None)), None);
        // centres 2.5..4.5 in [2,5) -> cols 2..=4; y centres 9.5-r in [6,8) -> rows 2,3
        assert_eq!(
            aoi_window(&g, &a(None, Some([2.0, 6.0, 5.0, 8.0]))),
            Some([2, 2, 3, 2])
        );
    }

    #[test]
    fn lookup_pass_counts_and_limits() {
        assert_eq!(lookup_passes(1, 24).unwrap(), 1);
        assert_eq!(lookup_passes(1 << 24, 24).unwrap(), 1); // max index 2**24 - 1
        assert_eq!(lookup_passes((1 << 24) + 1, 24).unwrap(), 2);
        assert_eq!(lookup_passes(17, 4).unwrap(), 2);
        assert_eq!(lookup_passes(16, 4).unwrap(), 1);
        assert!(lookup_passes(u32::MAX as usize, 24).is_err());
        assert!(lookup_passes(0, 24).is_err());
        assert!(lookup_passes(10, 25).is_err());
        // Every 24-bit digit is an exact f32 integer.
        let top = ((1u32 << 24) - 1) as f32;
        assert_eq!(top as u32, (1 << 24) - 1);
    }

    fn test_env() -> WarpEnv {
        let src = terrio::crs::SpatialRef::parse("EPSG:2277").unwrap();
        let dst = terrio::crs::SpatialRef::parse("EPSG:3857").unwrap();
        WarpEnv {
            src_srs_wkt: src.to_wkt().unwrap_or_default(),
            dst_srs_wkt: dst.to_wkt().unwrap_or_default(),
            src_srs: src,
            dst_srs: dst,
        }
    }

    /// Multi-pass encoding (forced with 4-bit digits) equals the single-pass lookup, and the lookup
    /// gather equals a direct native warp of a value field with NaN holes.
    #[test]
    fn multipass_lookup_equals_single_pass_and_direct_warp() {
        let (rows, cols) = (37usize, 53usize);
        let gt = [3215352.0, 8.48, 0.0, 10113648.0, 0.0, 8.48];
        let env = test_env();
        let n = Nudge {
            dst_epsg: 3857,
            error_threshold: 0.125,
            memory_limit_bytes: 64.0 * 1024.0 * 1024.0,
            method: NudgeMethod::Lookup,
        };
        // Destination grid: default suggestion snapped to 3 m (Python computes this in production).
        let (sg, w, h) =
            terrio::ops::warp::suggested_grid(cols, rows, gt, &env.src_srs, &env.dst_srs).unwrap();
        let g = DestGrid {
            geotransform: [
                (sg[0] / 3.0).round() * 3.0,
                3.0,
                0.0,
                (sg[3] / 3.0).round() * 3.0,
                0.0,
                -3.0,
            ],
            width: w,
            height: h,
        };
        let one = build_lookup_with(rows, cols, gt, &env, &n, &g, 24).unwrap();
        let many = build_lookup_with(rows, cols, gt, &env, &n, &g, 4).unwrap();
        assert_eq!(one.passes, 1);
        assert_eq!(many.passes, 3);
        assert_eq!(one.index, many.index);
        assert!(one.index.iter().any(|i| *i != NONE));
        let values: Vec<f32> = (0..rows * cols)
            .map(|i| {
                if i % 7 == 0 {
                    f32::NAN
                } else {
                    i as f32 * 0.25 - 3.0
                }
            })
            .collect();
        let direct = warp_field(values.clone(), rows, cols, gt, &env, &n, &g).unwrap();
        for (d, i) in direct.iter().zip(&one.index) {
            let gathered = if *i == NONE {
                f32::NAN
            } else {
                values[*i as usize]
            };
            assert!(d.to_bits() == gathered.to_bits() || (d.is_nan() && gathered.is_nan()));
        }
    }

    #[test]
    fn lookup_cache_budget_and_no_retention_default() {
        let l = |k: &str, n: usize| {
            Arc::new(Lookup {
                key: k.into(),
                index: vec![0; n],
                passes: 1,
                build_seconds: 0.0,
            })
        };
        let mut none = LookupCache::with_budget(default_lookup_cache());
        none.insert(l("a", 10));
        assert_eq!(none.resident_bytes, 0);
        assert_eq!(none.not_retained, 1);
        assert!(none.get("a").is_none());
        let mut c = LookupCache::with_budget(100);
        c.insert(l("a", 10));
        c.insert(l("b", 10));
        c.insert(l("c", 10)); // 3 x 41 > 100: evicts "a"
        assert_eq!(c.evictions, 1);
        assert!(c.resident_bytes <= 100 && c.peak_resident_bytes <= 100);
        assert!(c.get("a").is_none() && c.get("c").is_some());
    }

    #[test]
    fn memory_plan_counts_lookup_and_full_transients() {
        let meta: InputsJson = serde_json::from_value(json!({"schema": INPUTS_SCHEMA, "rows": 1000, "cols": 2000,
            "raster_affine": {"x0": 0.0, "y0": 0.0, "res_x": 1.0, "res_y": 1.0},
            "delaunay": {"paraboloid_scale": 1.0, "paraboloid_shift": 0.0, "min_bound": [0.0, 0.0], "max_bound": [1.0, 1.0], "nsimplex": 10},
            "files": {}})).unwrap();
        let g = DestGrid {
            geotransform: [0.0, 3.0, 0.0, 0.0, 0.0, -3.0],
            width: 3000,
            height: 1000,
        };
        let mut n = Nudge {
            dst_epsg: 3857,
            error_threshold: 0.125,
            memory_limit_bytes: 1.0,
            method: NudgeMethod::Lookup,
        };
        let small = plan_memory(&meta, &g, &n, false, 100, 100).unwrap();
        assert_eq!(small.lookup_index, 3000 * 1000 * 4);
        assert_eq!(small.lookup_transient, 2_000_000 * 4 + 3_000_000 * 5);
        n.method = NudgeMethod::FullWarp;
        let full = plan_memory(&meta, &g, &n, true, 3_000_000, 3_000_000).unwrap();
        assert!(full.total > small.total && full.full_grids == 2_000_000 * 24);
    }

    #[test]
    fn inflight_guard_counts_active_and_planned_and_releases_on_error_paths() {
        let f = InFlight::default();
        {
            let mut a = ActiveGuard::enter(&f);
            a.plan(100);
            {
                let mut b = ActiveGuard::enter(&f);
                b.plan(50);
                assert_eq!(f.active.load(Ordering::SeqCst), 2);
            } // dropped as on an early `?` return
            let _c = ActiveGuard::enter(&f); // failed before planning
            assert_eq!(f.planned.load(Ordering::SeqCst), 100);
        }
        assert_eq!(f.active.load(Ordering::SeqCst), 0);
        assert_eq!(f.planned.load(Ordering::SeqCst), 0);
        assert_eq!(f.peak_active.load(Ordering::SeqCst), 2);
        assert_eq!(f.peak_planned.load(Ordering::SeqCst), 150);
        // Duplicate concurrent builds of one key keep a single resident copy.
        let mut c = LookupCache::with_budget(1000);
        let l = Arc::new(Lookup {
            key: "k".into(),
            index: vec![0; 10],
            passes: 1,
            build_seconds: 0.0,
        });
        c.insert(l.clone());
        c.insert(l);
        assert_eq!(c.resident_bytes, 41);
    }

    #[test]
    fn ids_and_schema_validation() {
        assert!(is_safe_id("wsel_max_10"));
        assert!(!is_safe_id("CON"));
        assert!(!is_safe_id("../x"));
        assert!(!is_safe_id(""));
    }
}
