//! Native same-CRS north-up GeoTIFF terrain through terrio 0.4.2 lazy reads.
//!
//! Serial decode guarantee: every terrio `read_window` call requests exactly one TIFF block
//! (tile or strip) clipped to the image. terrio's `decode_in_threads` spawns
//! `rayon::current_num_threads().min(chunks)` scoped threads; with one chunk that is one, so the
//! chunk is decoded on the calling worker thread and the outer pool is never multiplied. This
//! holds regardless of `RAYON_NUM_THREADS` or the calling pool size. Evidence is the pinned
//! terrio `=0.4.2` source guard (`decode_in_threads` spawns only when `workers > 1`); re-verify it
//! on any terrio upgrade. The `debug_assert` in `block_window` only checks this crate's own grid.
//!
//! Size arithmetic is checked: block bytes are computed once at open with checked
//! multiplication and absurd layouts fail with a typed `unsupported` error instead of panicking.
use crate::MapError;
use crate::cache::{CacheStats, TileCache};
use crate::model::{CrsIdentity, NodataPolicy, QueryConvention};
use serde::Serialize;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use terrio::{LazyRaster, Window, WindowOptions};

pub struct NativeTerrain {
    pub path: String,
    pub gt: [f64; 6],
    pub width: usize,
    pub height: usize,
    pub block: (usize, usize),
    pub nodata: Option<f64>,
    pub epsg: u32,
    pub crs_identity: &'static str,
    pub crs_wkt_fnv1a64: Option<String>,
    pub query: QueryConvention,
    pub policy: NodataPolicy,
    /// Bytes of one full decoded block (checked at open).
    block_bytes: u64,
    readers: Mutex<Vec<LazyRaster>>,
    readers_opened: AtomicU64,
    decode_nanos: AtomicU64,
    pub cache: TileCache,
}

#[derive(Serialize, Debug, Clone)]
pub struct TerrainInfo {
    pub path: String,
    pub geo_transform: [f64; 6],
    pub width: usize,
    pub height: usize,
    pub block: (usize, usize),
    pub blocks_x: usize,
    pub blocks_y: usize,
    pub nodata: Option<f64>,
    pub epsg: Option<u32>,
    pub data_type: String,
    pub band_count: usize,
    pub crs: terrio::crs::SpatialRef,
    pub crs_wkt_fnv1a64: Option<String>,
}

#[derive(Serialize, Debug, Clone)]
pub struct TerrainStats {
    /// Decoded *resident* tile accounting (the enforced cache bound).
    pub cache: CacheStats,
    pub readers_opened: u64,
    pub decode_seconds: f64,
    /// Estimate (not enforced, not measured) of decoder transients outside the cache budget:
    /// `peak_concurrent_loads x decoder_transient_bytes_per_load_estimate`.
    pub decoder_transient_bytes_per_load_estimate: u64,
    pub decoder_transient_peak_estimate_bytes: u64,
}

/// Index of a terrain pixel hit by a sample point.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Hit {
    Outside,
    Pixel {
        col: usize,
        row: usize,
        near_boundary: bool,
    },
}

pub fn inspect(path: &str) -> Result<TerrainInfo, MapError> {
    let r = open_lazy(path)?;
    let block = r.block_size().unwrap_or((0, 0));
    Ok(TerrainInfo {
        path: path.to_string(),
        geo_transform: r.geo_transform(),
        width: r.width(),
        height: r.height(),
        block,
        blocks_x: if block.0 > 0 {
            r.width().div_ceil(block.0)
        } else {
            0
        },
        blocks_y: if block.1 > 0 {
            r.height().div_ceil(block.1)
        } else {
            0
        },
        nodata: r.nodata(),
        epsg: r.crs().epsg,
        data_type: format!("{:?}", r.data_type()),
        band_count: r.band_count(),
        crs: r.crs(),
        crs_wkt_fnv1a64: wkt_fnv(&r.crs()),
    })
}

/// FNV-1a 64 of terrio's WKT for the terrain CRS (identity pin for caller-verified CRS).
pub fn wkt_fnv(crs: &terrio::crs::SpatialRef) -> Option<String> {
    crs.to_wkt()
        .map(|w| format!("{:016x}", crate::sink::fnv1a64(w.as_bytes())))
}

fn open_lazy(path: &str) -> Result<LazyRaster, MapError> {
    let r = LazyRaster::open_tiff(path)
        .map_err(|e| MapError::Terrain(format!("{path}: {e}")))?
        .ok_or_else(|| {
            MapError::Unsupported(format!(
                "{path}: not a TIFF (VRT/HDF/other terrain unsupported)"
            ))
        })?;
    if !r.is_lazy() {
        return Err(MapError::Unsupported(format!(
            "{path}: terrio did not open a lazy GeoTIFF"
        )));
    }
    Ok(r)
}

impl NativeTerrain {
    pub fn open(
        path: &str,
        expected_epsg: u32,
        identity: &CrsIdentity,
        query: QueryConvention,
        policy: NodataPolicy,
        cache_budget: u64,
    ) -> Result<Self, MapError> {
        let r = open_lazy(path)?;
        if r.band_count() != 1 {
            return Err(MapError::Unsupported(format!(
                "{path}: {} bands; single-band required",
                r.band_count()
            )));
        }
        if r.data_type() != terrio::DataType::F32 {
            return Err(MapError::Unsupported(format!(
                "{path}: data type {:?}; float32 required",
                r.data_type()
            )));
        }
        let gt = r.geo_transform();
        if !gt.iter().all(|v| v.is_finite())
            || gt[2] != 0.0
            || gt[4] != 0.0
            || gt[1] <= 0.0
            || gt[5] >= 0.0
        {
            return Err(MapError::Unsupported(format!(
                "{path}: geotransform {gt:?} is not north-up axis-aligned (rotated/south-up unsupported)"
            )));
        }
        let crs = r.crs();
        let crs_identity = match (crs.epsg, identity) {
            (Some(e), _) if e != expected_epsg => {
                return Err(MapError::Unsupported(format!(
                    "{path}: terrain EPSG:{e} differs from session EPSG:{expected_epsg}; no reprojection is performed"
                )));
            }
            (Some(_), CrsIdentity::Epsg) => "terrio_identified_epsg",
            // A supplied WKT pin is always verified, even when terrio also identifies the EPSG.
            (Some(_), CrsIdentity::CallerVerifiedWkt { fnv1a64 }) => {
                check_wkt_pin(path, &crs, fnv1a64)?;
                "terrio_identified_epsg_and_caller_verified_wkt_fnv1a64"
            }
            (None, CrsIdentity::Epsg) => {
                return Err(MapError::Unsupported(format!(
                    "{path}: terrio does not identify an EPSG code for this terrain; use crs_identity caller_verified_wkt after independent verification"
                )));
            }
            (None, CrsIdentity::CallerVerifiedWkt { fnv1a64 }) => {
                check_wkt_pin(path, &crs, fnv1a64)?;
                "caller_verified_wkt_fnv1a64"
            }
        };
        let block = r
            .block_size()
            .filter(|b| b.0 > 0 && b.1 > 0)
            .ok_or_else(|| MapError::Unsupported(format!("{path}: no block layout")))?;
        let (width, height) = (r.width(), r.height());
        if width == 0 || height == 0 || width > u32::MAX as usize || height > u32::MAX as usize {
            return Err(MapError::Unsupported(format!(
                "{path}: unsupported size {width}x{height}"
            )));
        }
        let block_bytes = checked_block_bytes(block)
            .filter(|b| *b <= MAX_BLOCK_BYTES)
            .ok_or_else(|| {
                MapError::Unsupported(format!(
                    "{path}: block {}x{} float32 exceeds {MAX_BLOCK_BYTES} bytes or overflows",
                    block.0, block.1
                ))
            })?;
        let nodata = r.nodata();
        Ok(Self {
            path: path.to_string(),
            gt,
            width,
            height,
            block,
            nodata,
            epsg: expected_epsg,
            crs_identity,
            crs_wkt_fnv1a64: wkt_fnv(&crs),
            query,
            policy,
            block_bytes,
            readers: Mutex::new(vec![r]),
            readers_opened: AtomicU64::new(1),
            decode_nanos: AtomicU64::new(0),
            cache: TileCache::new(cache_budget),
        })
    }

    pub fn blocks(&self) -> (usize, usize) {
        (
            self.width.div_ceil(self.block.0),
            self.height.div_ceil(self.block.1),
        )
    }

    /// Pixel window of block (bx, by), clipped to the image. Always within one TIFF chunk.
    pub fn block_window(&self, bx: usize, by: usize) -> Window {
        let (bw, bh) = self.block;
        let x = bx * bw;
        let y = by * bh;
        let w = bw.min(self.width - x);
        let h = bh.min(self.height - y);
        debug_assert!(x / bw == (x + w - 1) / bw && y / bh == (y + h - 1) / bh);
        Window::new(x, y, w, h)
    }

    pub fn max_block_bytes(&self) -> u64 {
        self.block_bytes
    }

    /// Estimated transient bytes of one concurrent block decode, outside the cache budget:
    /// terrio window buffer, tiff decoded chunk, compressed chunk (assumed <= decoded size) and
    /// the `Arc<[f32]>` copy (4 x block bytes), plus terrio's per-read copies of the full chunk
    /// offset and byte-count tables (16 bytes per chunk). From source reading; not measured.
    pub fn decoder_transient_bytes_per_load(&self) -> u64 {
        let (bx, by) = self.blocks();
        let tables = (bx as u64).saturating_mul(by as u64).saturating_mul(16);
        self.block_bytes.saturating_mul(4).saturating_add(tables)
    }

    /// Shared decoded block through the cache.
    pub fn get_block(&self, bx: usize, by: usize) -> Result<Arc<[f32]>, MapError> {
        let w = self.block_window(bx, by);
        // At most block_bytes, which was checked at open.
        let bytes = (w.width * w.height * 4) as u64;
        self.cache
            .get_or_load((bx as u32, by as u32), bytes, || self.decode(w))
    }

    fn decode(&self, w: Window) -> Result<Vec<f32>, MapError> {
        let reader = self.readers.lock().unwrap_or_else(|p| p.into_inner()).pop();
        let mut reader = match reader {
            Some(r) => r,
            None => {
                self.readers_opened.fetch_add(1, Ordering::Relaxed);
                open_lazy(&self.path)?
            }
        };
        let start = Instant::now();
        let options = WindowOptions {
            bands: vec![1],
            overview: None,
        };
        let ds = reader.read_window(w, &options).map_err(|e| {
            MapError::Terrain(format!("{}: block read {:?}: {e}", self.path, (w.x, w.y)))
        })?;
        self.decode_nanos
            .fetch_add(start.elapsed().as_nanos() as u64, Ordering::Relaxed);
        // Return the reader only after a successful read.
        self.readers
            .lock()
            .unwrap_or_else(|p| p.into_inner())
            .push(reader);
        let terrio::raster::RasterData::F32(values) = ds.raster.data else {
            return Err(MapError::Unsupported(
                "terrio returned non-float32 block".into(),
            ));
        };
        if values.len() != w.width * w.height {
            return Err(MapError::Terrain(format!(
                "block has {} values, expected {}",
                values.len(),
                w.width * w.height
            )));
        }
        Ok(values)
    }

    /// Explicit sampling formula: col = floor((xs - gt0)/gt1), row = floor((ys - gt3)/gt5).
    #[inline]
    pub fn hit(&self, xs: f64, ys: f64) -> Hit {
        let fc = (xs - self.gt[0]) / self.gt[1];
        let fr = (ys - self.gt[3]) / self.gt[5];
        if !(fc.is_finite() && fr.is_finite()) {
            return Hit::Outside;
        }
        let (c, r) = (fc.floor(), fr.floor());
        if c < 0.0 || r < 0.0 || c >= self.width as f64 || r >= self.height as f64 {
            return Hit::Outside;
        }
        let tol = 1e-9;
        let near = (fc - c) < tol || (c + 1.0 - fc) < tol || (fr - r) < tol || (r + 1.0 - fr) < tol;
        Hit::Pixel {
            col: c as usize,
            row: r as usize,
            near_boundary: near,
        }
    }

    /// Floor index along one axis, unclamped (used for footprint planning).
    pub fn floor_index(&self, xs: f64, ys: f64) -> Option<(f64, f64)> {
        let fc = ((xs - self.gt[0]) / self.gt[1]).floor();
        let fr = ((ys - self.gt[3]) / self.gt[5]).floor();
        (fc.is_finite() && fr.is_finite()).then_some((fc, fr))
    }

    /// Applies the explicit nodata policy to a raw terrain value. NaN is dry. An infinite value
    /// that is not a dry sentinel is returned as is; the session rejects it with a typed terrain
    /// error (matching the caller_buffer rejection of infinite terrain).
    #[inline]
    pub fn classify(&self, v: f32) -> Option<f64> {
        if v.is_nan() {
            return None;
        }
        let sentinel = self.nodata.is_some_and(|nd| v == nd as f32);
        match (sentinel, self.policy) {
            (true, NodataPolicy::Dry) => None,
            _ => Some(v as f64),
        }
    }

    pub fn is_sentinel(&self, v: f32) -> bool {
        self.nodata
            .is_some_and(|nd| v == nd as f32 || (nd.is_nan() && v.is_nan()))
    }

    pub fn stats(&self) -> TerrainStats {
        let cache = self.cache.stats();
        let per = self.decoder_transient_bytes_per_load();
        TerrainStats {
            decoder_transient_peak_estimate_bytes: per.saturating_mul(cache.peak_concurrent_loads),
            decoder_transient_bytes_per_load_estimate: per,
            cache,
            readers_opened: self.readers_opened.load(Ordering::Relaxed),
            decode_seconds: self.decode_nanos.load(Ordering::Relaxed) as f64 * 1e-9,
        }
    }
}

/// Largest single decoded block accepted (1 GiB of float32).
pub const MAX_BLOCK_BYTES: u64 = 1 << 30;

/// `bw * bh * 4` with overflow detection.
pub fn checked_block_bytes(block: (usize, usize)) -> Option<u64> {
    (block.0 as u64)
        .checked_mul(block.1 as u64)
        .and_then(|v| v.checked_mul(4))
}

fn check_wkt_pin(path: &str, crs: &terrio::crs::SpatialRef, fnv1a64: &str) -> Result<(), MapError> {
    let got =
        wkt_fnv(crs).ok_or_else(|| MapError::Unsupported(format!("{path}: terrain has no CRS")))?;
    if got.eq_ignore_ascii_case(fnv1a64) {
        Ok(())
    } else {
        Err(MapError::Unsupported(format!(
            "{path}: terrain WKT hash {got} differs from caller-verified {fnv1a64}"
        )))
    }
}

/// Every declared nodata is accepted, including NaN and +/-inf (GDAL-like: a pixel is the
/// sentinel iff `v == nodata as f32`). Whether that cast is exact is reported, not guessed.
pub fn nodata_f32_exact(nodata: Option<f64>) -> Option<bool> {
    nodata.map(|nd| nd.is_nan() || (nd as f32) as f64 == nd)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn absurd_block_sizes_are_detected_not_panics() {
        assert_eq!(checked_block_bytes((256, 256)), Some(262_144));
        assert_eq!(checked_block_bytes((usize::MAX, 2)), None);
        assert_eq!(
            checked_block_bytes((u32::MAX as usize, u32::MAX as usize)),
            None
        );
        assert!(checked_block_bytes((65_536, 65_536)).unwrap() > MAX_BLOCK_BYTES);
    }

    #[test]
    fn nodata_cast_exactness_is_reported() {
        assert_eq!(nodata_f32_exact(None), None);
        assert_eq!(nodata_f32_exact(Some(-9999.0)), Some(true));
        assert_eq!(nodata_f32_exact(Some(f64::NAN)), Some(true));
        assert_eq!(nodata_f32_exact(Some(f64::NEG_INFINITY)), Some(true));
        assert_eq!(nodata_f32_exact(Some(-3.4028234663852886e38)), Some(true));
        assert_eq!(nodata_f32_exact(Some(-3.40282e38)), Some(false));
    }
}
