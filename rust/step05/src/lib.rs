//! Prepared raster mapping engines for the ras2fim-2D catalog method.
//!
//! Extends the immutable baseline prototype `prototype/kernel` (RasMapper_Stored_Maps_Rust,
//! 2026-10-22, CLB Engineering): the barycentric evaluation, the `100 * DBL_EPSILON` inclusion
//! test and the lowest-simplex-id tie rule are copied from that kernel. Upstream algorithm:
//! Andy Carter, PE / University of Texas at Austin, ras2fim-2d `3146f647`, Step05 (BSD-3-Clause).
//!
//! The application uses [`step05`], which preserves the upstream float32 sequence
//! and native approximate reprojection over supplied SciPy transforms and axes.
//! The older [`session`] diagnostic retains its distinct f64 arithmetic.
//! Shared scope boundaries:
//! - Interpolation topology is always caller-supplied global SciPy/Qhull simplices. There is no
//!   native triangulation and never a per-AOI or per-tile retriangulation.
//! - Wet masks and sample preparation are caller-supplied (upstream/Python adapters).
//! - Native terrain is same-CRS, north-up, single-band float32 GeoTIFF read through terrio with
//!   an explicit sampling formula. Other terrain types require separate qualification.
//! - The diagnostic session's f64 arithmetic does not replace the Step05 float32 sequence.
#![forbid(unsafe_code)]

pub mod cache;
pub mod horizontal;
pub mod interp;
pub mod model;
pub mod ownership;
pub mod scipy_interp;
pub mod session;
pub mod sink;
pub mod step05;
pub mod terrain;

use std::fmt;

/// Identifies the method semantics. Changing any recorded convention must change this string.
pub const METHOD_VERSION: &str = "ras2fim-batch-prototype/0.1.0 method-r1";

/// Identifies the output/failure/budget contract (not the numerical method, which is unchanged).
pub const CONTRACT_VERSION: &str = "ras2fim-batch-prototype contract-r2-hardening";

/// Errors are typed so callers can distinguish invalid input, budgets and unsupported cases.
#[derive(Debug, Clone, PartialEq)]
pub enum MapError {
    Invalid(String),
    Budget(String),
    Unsupported(String),
    Io(String),
    Terrain(String),
    /// A caught panic or broken internal invariant (never a silent partial result).
    Internal(String),
}

impl fmt::Display for MapError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MapError::Invalid(s) => write!(f, "invalid input: {s}"),
            MapError::Budget(s) => write!(f, "budget exceeded: {s}"),
            MapError::Unsupported(s) => write!(f, "unsupported: {s}"),
            MapError::Io(s) => write!(f, "io error: {s}"),
            MapError::Terrain(s) => write!(f, "terrain error: {s}"),
            MapError::Internal(s) => write!(f, "internal error: {s}"),
        }
    }
}

impl std::error::Error for MapError {}

impl From<std::io::Error> for MapError {
    fn from(e: std::io::Error) -> Self {
        MapError::Io(e.to_string())
    }
}

impl MapError {
    pub fn kind(&self) -> &'static str {
        match self {
            MapError::Invalid(_) => "invalid",
            MapError::Budget(_) => "budget",
            MapError::Unsupported(_) => "unsupported",
            MapError::Io(_) => "io",
            MapError::Terrain(_) => "terrain",
            MapError::Internal(_) => "internal",
        }
    }
}

/// Static description of the implemented semantics, emitted in every report.
pub fn method_record() -> serde_json::Value {
    serde_json::json!({
        "method_version": METHOD_VERSION,
        "interpolation": {
            "topology": "caller-supplied global SciPy/Qhull simplices only; no native or per-AOI triangulation",
            "evaluation": "f64 barycentric linear interpolation (baseline prototype kernel)",
            "inclusion_tolerance": "all barycentric coordinates >= -100*DBL_EPSILON",
            "tie_rule": "lowest supplied simplex index among containing simplices (order independent)",
            "degenerate_simplices": "skipped when determinant == 0 or exact 1-norm reciprocal condition < 1000*DBL_EPSILON; modeled on SciPy's singular-transform skip, not verified bit-identical to SciPy's LAPACK estimate",
            "scipy_eps_broad_fallback": "not implemented; no claim of SciPy find_simplex walk parity",
            "query_point": "x = x0 + col*dx, y = y0 + row*dy in f64 (explicit grid); terrain-aligned grid: x = gt0 + (abs_col + 0.5)*gt1, y = gt3 + (abs_row + 0.5)*gt5"
        },
        "mask": "caller-supplied rasterized wet union on the profile grid (upstream/Python adapter); unmasked pixels are nodata",
        "depth_wse": "depth = raw_wse - ground (f64); wet iff ground present and depth >= 0; wse = raw_wse where wet. Baseline prototype semantics; upstream float32 writes, '<0 -> NaN' sequencing and the Step05 nudge are NOT replicated",
        "terrain_modes": {
            "caller_buffer": "per-profile pre-aligned f64 terrain buffer, null/NaN = nodata (old oracle parity mode)",
            "native_geotiff": {
                "format": "same-CRS, north-up (gt2 == gt4 == 0, gt1 > 0, gt5 < 0), single-band float32 GeoTIFF/BigTIFF via terrio 0.4.2 lazy tile reads",
                "sample_formula": "col = floor((xs - gt0) / gt1), row = floor((ys - gt3) / gt5) in f64",
                "query_convention": "explicit per session: pixel_center (xs = x0 + (col + 0.5)*dx, ys = y0 + (row + 0.5)*dy) or query_point (xs, ys = query point)",
                "nodata_policy": "explicit per session: dry (declared-nodata sentinel -> dry) or raw_value (sentinel subtracted as a number, upstream-like raw subtraction; not qualified)",
                "outside_extent": "dry",
                "nan_value": "dry",
                "reprojection": "never; terrain EPSG must equal the declared session EPSG",
                "not_qualified": "GDAL Warp nearest-neighbour, Step05 inverted-bounds lattice, nudge, upstream raw-sentinel behaviour; rasterio rowcol uses a linear solve and may differ at exact pixel-boundary ties (counted as terrain_near_boundary_samples)"
            }
        },
        "nonfinite_terrain": "NaN terrain is dry; declared NaN or +/-inf nodata is accepted (a pixel is the sentinel iff v == nodata as f32, GDAL-like; report states whether that cast is exact); any other infinite terrain value that is sampled is rejected (native: typed terrain error failing the profile; caller_buffer: invalid request)",
        "aoi": "pixel windows on each profile's own grid; AOI output equals the crop of the full-grid output by construction (same tiles, same per-pixel formula); bounds select pixels whose center lies in [min, max)",
        "outputs": "per (profile, AOI) unit: little-endian f64 rasters with NaN nodata, simplex_id as i64 with -1 nodata, row-major in grid row order",
        "output_contract": {
            "contract_version": CONTRACT_VERSION,
            "commit": "unit.json status in_progress is written before any data; data is written as <product>.bin.partial, fsynced (errors propagate), renamed to .bin, directory synced where supported, then unit.json is atomically replaced with status complete. A .bin is valid only when unit.json says complete",
            "failure": "a failed unit, or every open unit after a session error or caught panic, has its data removed and unit.json status failed; report.json is still written with status aborted when possible (otherwise stderr says so and in_progress/.partial names remain)",
            "json_writes": "<name>.partial, fsync, rename",
            "ids": "[A-Za-z0-9_.-]{1,64}, unique case-insensitively, no trailing '.', no Windows device names (CON, PRN, AUX, NUL, COM0-9, LPT0-9, with any extension)"
        },
        "bounds": {
            "enforced": "decoded resident terrain tiles <= max_cache_bytes; evaluated tile buffers <= effective_tiles_in_flight x output_tile^2 x 40 bytes; plan tiles per profile <= 4194304",
            "admission_estimates": "per-profile load+prepare peak from request content / file lengths before any read (binary/inline: buffer sizes plus an assumed one-copy R-tree bulk-load; legacy JSON: 64 x file length heuristic) checked against max_profile_bytes; optional max_session_bytes packs batches over accounted static terms + batch load peaks + plan metadata",
            "not_bounded": "decoder transients (estimated only), allocator fragmentation, thread stacks, codec state, JSON transients; no hard total memory bound is claimed"
        }
    })
}
