//! Request schema, validation and profile-source loading.
use crate::MapError;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::fs;
use std::io::BufReader;
use std::path::{Path, PathBuf};

pub const SESSION_SCHEMA: &str = "ras2fim-batch-session/1";
pub const MAX_JSON_BYTES: u64 = 512 * 1024 * 1024;
pub const MAX_BINARY_BYTES: u64 = 8 * 1024 * 1024 * 1024;
pub const MAX_PROFILE_PIXELS: u64 = 1 << 31;
pub const MAX_THREADS: usize = 64;

#[derive(Deserialize, Debug)]
#[serde(deny_unknown_fields)]
pub struct SessionRequest {
    pub schema: String,
    /// Declared CRS of every grid, sample and AOI bound. No reprojection is ever performed.
    pub crs_epsg: u32,
    pub terrain: TerrainSpec,
    pub budgets: Budgets,
    pub products: Vec<Product>,
    pub profiles: Vec<ProfileSpec>,
    pub aois: Vec<AoiSpec>,
    pub error_policy: ErrorPolicy,
}

#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum TerrainSpec {
    /// Per-profile pre-aligned terrain buffers (old oracle parity).
    CallerBuffer,
    /// Native same-CRS north-up GeoTIFF sampled with an explicit convention.
    NativeGeotiff {
        path: String,
        query: QueryConvention,
        nodata_policy: NodataPolicy,
        crs_identity: CrsIdentity,
    },
}

/// How the terrain CRS is established equal to the session EPSG. Never inferred silently.
#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CrsIdentity {
    /// terrio must identify the terrain EPSG code itself and it must equal `crs_epsg`.
    Epsg,
    /// The caller independently verified the CRS (e.g. rasterio/PROJ identification) and pins
    /// terrio's exact WKT by FNV-1a 64 hash (printed by `terrain-info`). A terrio-identified EPSG
    /// that differs still fails.
    CallerVerifiedWkt { fnv1a64: String },
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum QueryConvention {
    PixelCenter,
    QueryPoint,
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NodataPolicy {
    Dry,
    RawValue,
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ErrorPolicy {
    /// A failing profile marks only its own units failed (explicit, never an empty raster).
    IsolateProfile,
    /// Any profile failure aborts the session after recording it.
    FailFast,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct Budgets {
    pub threads: usize,
    /// Decoded terrain-tile cache budget (bytes), shared by all profiles and AOIs.
    pub max_cache_bytes: u64,
    /// Prepared profiles alive at once.
    pub max_inflight_profiles: usize,
    /// Upper bound per prepared profile (interpolator + mask + caller terrain), bytes.
    pub max_profile_bytes: u64,
    /// Output tile edge in pixels (tiles anchored at each profile grid's pixel 0,0).
    pub output_tile: usize,
    /// Evaluated tiles held in memory at once (bounded queue between workers and sink).
    /// 1 selects the serial (non-pipelined) evaluate-then-write branch.
    pub max_tiles_in_flight: usize,
    /// Optional ceiling on the session's *accounted* memory estimate (see `memory_estimate` in
    /// the report). Checked before any profile is read; profiles are packed into batches so the
    /// estimate fits. It is an admission check over accounted terms, not an OS-enforced limit:
    /// unaccounted allocations (listed in the report) remain.
    #[serde(default)]
    pub max_session_bytes: Option<u64>,
}

#[derive(Deserialize, Serialize, Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
#[serde(rename_all = "snake_case")]
pub enum Product {
    RawWse,
    Wse,
    Depth,
    SimplexId,
    Ground,
}

impl Product {
    pub fn name(self) -> &'static str {
        match self {
            Product::RawWse => "raw_wse",
            Product::Wse => "wse",
            Product::Depth => "depth",
            Product::SimplexId => "simplex_id",
            Product::Ground => "ground",
        }
    }
    pub fn dtype(self) -> &'static str {
        match self {
            Product::SimplexId => "<i8",
            _ => "<f8",
        }
    }
}

#[derive(Deserialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct ProfileSpec {
    pub id: String,
    pub source: ProfileSource,
}

#[derive(Deserialize, Debug, Clone)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProfileSource {
    /// Existing baseline prepared request (`prototype/evidence-*/**/*.request.json`). Its
    /// samples, simplices, grid, mask and terrain are used; threads/repeats are ignored. In
    /// native terrain mode its caller terrain buffer is ignored (reported).
    LegacyRequest { path: String },
    Inline {
        samples: Vec<[f64; 3]>,
        simplices: Vec<[usize; 3]>,
        grid: GridSpec,
        #[serde(default)]
        mask: Option<Vec<bool>>,
        #[serde(default)]
        mask_all_wet: bool,
        #[serde(default)]
        terrain: Option<Vec<Option<f64>>>,
    },
    /// Raw little-endian arrays: samples n*3 f64, simplices m*3 u32, mask u8 (0/1) per pixel,
    /// terrain f64 per pixel (NaN = nodata).
    Binary {
        samples_f64: String,
        simplices_u32: String,
        grid: GridSpec,
        #[serde(default)]
        mask_u8: Option<String>,
        #[serde(default)]
        mask_all_wet: bool,
        #[serde(default)]
        terrain_f64: Option<String>,
    },
}

#[derive(Deserialize, Serialize, Debug, Clone, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum GridSpec {
    /// Query point of pixel (row, col) is (x0 + col*dx, y0 + row*dy).
    Explicit {
        width: usize,
        height: usize,
        x0: f64,
        y0: f64,
        dx: f64,
        dy: f64,
    },
    /// Query points are exactly the native terrain pixel centers of a terrain window; terrain is
    /// sampled by integer index (native mode only).
    TerrainAligned {
        col: usize,
        row: usize,
        width: usize,
        height: usize,
    },
}

#[derive(Deserialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct LegacyGrid {
    pub width: usize,
    pub height: usize,
    pub x0: f64,
    pub y0: f64,
    pub dx: f64,
    pub dy: f64,
}

#[derive(Deserialize, Debug)]
#[serde(deny_unknown_fields)]
struct LegacyRequest {
    samples: Vec<[f64; 3]>,
    grid: LegacyGrid,
    mask: Vec<bool>,
    terrain: Vec<Option<f64>>,
    simplices: Option<Vec<[usize; 3]>>,
    #[serde(default)]
    allow_native_triangulation: bool,
    #[allow(dead_code)]
    threads: usize,
    #[allow(dead_code)]
    repeats: usize,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
#[serde(deny_unknown_fields)]
pub struct AoiSpec {
    pub id: String,
    /// [col, row, width, height] on each profile's own grid.
    #[serde(default)]
    pub window: Option<[u64; 4]>,
    /// [xmin, ymin, xmax, ymax]; selects pixels whose center lies in [min, max).
    #[serde(default)]
    pub bounds: Option<[f64; 4]>,
    #[serde(default)]
    pub crs_epsg: Option<u32>,
}

/// Loaded profile data, before interpolator preparation.
pub struct ProfileData {
    pub samples: Vec<[f64; 3]>,
    pub simplices: Vec<[usize; 3]>,
    pub grid: GridSpec,
    pub mask: MaskData,
    pub terrain: Option<Vec<f64>>,
    pub legacy_terrain_ignored: bool,
    pub source_bytes: u64,
}

pub enum MaskData {
    AllWet,
    Bits(Vec<bool>),
}

/// Windows device names; reserved with any extension (`NUL.txt`) and in any case.
const WINDOWS_RESERVED: [&str; 4] = ["CON", "PRN", "AUX", "NUL"];

fn windows_reserved(id: &str) -> bool {
    let stem = id.split('.').next().unwrap_or(id).to_ascii_uppercase();
    WINDOWS_RESERVED.contains(&stem.as_str())
        || (stem.len() == 4
            && (stem.starts_with("COM") || stem.starts_with("LPT"))
            && stem.as_bytes()[3].is_ascii_digit())
}

/// Ids name output directories, so they must be path-safe on Linux and Windows/NTFS (including
/// drvfs/SMB): `[A-Za-z0-9_.-]{1,64}`, not `.`/`..`, no trailing `.`, no Windows device name.
/// Uniqueness is checked case-insensitively by the caller (`id_key`).
pub fn validate_id(id: &str) -> Result<(), MapError> {
    let charset = !id.is_empty()
        && id.len() <= 64
        && id
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.');
    if !charset {
        return Err(MapError::Invalid(format!(
            "id {id:?} must match [A-Za-z0-9_.-]{{1,64}}"
        )));
    }
    if id.ends_with('.') {
        return Err(MapError::Invalid(format!(
            "id {id:?} must not end with '.' (Windows strips it; also rejects . and ..)"
        )));
    }
    if windows_reserved(id) {
        return Err(MapError::Invalid(format!(
            "id {id:?} is a reserved Windows device name"
        )));
    }
    Ok(())
}

/// Case-insensitive identity of an id (two ids with equal keys collide on NTFS).
pub fn id_key(id: &str) -> String {
    id.to_ascii_lowercase()
}

impl SessionRequest {
    pub fn load(path: &Path) -> Result<Self, MapError> {
        let r: SessionRequest = read_json(path)?;
        r.validate()?;
        Ok(r)
    }

    pub fn validate(&self) -> Result<(), MapError> {
        if self.schema != SESSION_SCHEMA {
            return Err(MapError::Invalid(format!(
                "schema must be {SESSION_SCHEMA:?}"
            )));
        }
        let b = &self.budgets;
        if b.threads == 0 || b.threads > MAX_THREADS {
            return Err(MapError::Invalid(format!(
                "threads must be 1..={MAX_THREADS}"
            )));
        }
        if !(16..=4096).contains(&b.output_tile) {
            return Err(MapError::Invalid("output_tile must be 16..=4096".into()));
        }
        if b.max_tiles_in_flight == 0 || b.max_tiles_in_flight > 65_536 {
            return Err(MapError::Invalid(
                "max_tiles_in_flight must be 1..=65536".into(),
            ));
        }
        if b.max_inflight_profiles == 0 || b.max_inflight_profiles > 4096 {
            return Err(MapError::Invalid(
                "max_inflight_profiles must be 1..=4096".into(),
            ));
        }
        if b.max_profile_bytes == 0 {
            return Err(MapError::Invalid(
                "max_profile_bytes must be positive".into(),
            ));
        }
        if b.max_session_bytes == Some(0) {
            return Err(MapError::Invalid(
                "max_session_bytes must be positive when given".into(),
            ));
        }
        let out_bytes = self.output_buffer_bound()?;
        if out_bytes > 16 * 1024 * 1024 * 1024 {
            return Err(MapError::Budget(format!(
                "tile queue bound {out_bytes} bytes exceeds 16 GiB"
            )));
        }
        if self.products.is_empty() {
            return Err(MapError::Invalid("at least one product required".into()));
        }
        let unique: HashSet<_> = self.products.iter().collect();
        if unique.len() != self.products.len() {
            return Err(MapError::Invalid("duplicate product".into()));
        }
        if self.profiles.is_empty() || self.aois.is_empty() {
            return Err(MapError::Invalid(
                "at least one profile and one AOI required".into(),
            ));
        }
        let mut ids = HashSet::new();
        for p in &self.profiles {
            validate_id(&p.id)?;
            if !ids.insert(id_key(&p.id)) {
                return Err(MapError::Invalid(format!(
                    "duplicate profile id {} (ids are compared case-insensitively)",
                    p.id
                )));
            }
        }
        let mut ids = HashSet::new();
        for a in &self.aois {
            validate_id(&a.id)?;
            if !ids.insert(id_key(&a.id)) {
                return Err(MapError::Invalid(format!(
                    "duplicate AOI id {} (ids are compared case-insensitively)",
                    a.id
                )));
            }
            if a.window.is_some() && a.bounds.is_some() {
                return Err(MapError::Invalid(format!(
                    "AOI {}: window and bounds are exclusive",
                    a.id
                )));
            }
            if let Some(w) = a.window
                && (w[2] == 0
                    || w[3] == 0
                    || w[0].checked_add(w[2]).is_none()
                    || w[1].checked_add(w[3]).is_none())
            {
                return Err(MapError::Invalid(format!("AOI {}: invalid window", a.id)));
            }
            if let Some(bd) = a.bounds
                && (!bd.iter().all(|v| v.is_finite()) || bd[0] >= bd[2] || bd[1] >= bd[3])
            {
                return Err(MapError::Invalid(format!(
                    "AOI {}: bounds must be finite, min < max",
                    a.id
                )));
            }
            if a.crs_epsg.is_some_and(|e| e != self.crs_epsg) {
                return Err(MapError::Unsupported(format!(
                    "AOI {} CRS EPSG:{} differs from session EPSG:{}; no reprojection",
                    a.id,
                    a.crs_epsg.unwrap_or_default(),
                    self.crs_epsg
                )));
            }
        }
        Ok(())
    }

    /// Evaluated tiles that can actually be alive at once: 1 in the serial branch
    /// (`max_tiles_in_flight == 1`), otherwise two pipelined chunks of `max_tiles_in_flight / 2`.
    pub fn effective_tiles_in_flight(&self) -> usize {
        match self.budgets.max_tiles_in_flight {
            1 => 1,
            m => 2 * (m / 2),
        }
    }

    /// Bytes of evaluated tile buffers that can be alive between workers and sink
    /// (`effective_tiles_in_flight x output_tile^2 x 40`; five 8-byte buffers per pixel).
    pub fn output_buffer_bound(&self) -> Result<u64, MapError> {
        let px = (self.budgets.output_tile as u64).pow(2);
        (self.effective_tiles_in_flight() as u64)
            .checked_mul(px)
            .and_then(|v| v.checked_mul(8 * 5))
            .ok_or_else(|| MapError::Budget("tile queue bound overflows".into()))
    }

    /// Exact bytes of profile payloads held inside the parsed request (inline sources), which
    /// stay resident for the whole session.
    pub fn inline_payload_bytes(&self) -> u64 {
        self.profiles
            .iter()
            .map(|p| match &p.source {
                ProfileSource::Inline {
                    samples,
                    simplices,
                    mask,
                    terrain,
                    ..
                } => {
                    24 * samples.len() as u64
                        + 8 * 3 * simplices.len() as u64
                        + mask.as_ref().map_or(0, |m| m.len() as u64)
                        + 16 * terrain.as_ref().map_or(0, |t| t.len() as u64)
                }
                _ => 0,
            })
            .sum()
    }
}

/// Pre-read memory estimate for loading and preparing one profile.
#[derive(Serialize, Clone, Debug, Default, PartialEq)]
pub struct ProfileEstimate {
    /// How the numbers were obtained.
    pub basis: &'static str,
    /// Bytes kept while the profile is alive (prepared interpolator, mask, caller terrain).
    /// For `binary`/`inline` this mirrors the post-prepare self-accounting with every supplied
    /// simplex assumed valid.
    pub resident_bytes: u64,
    /// Extra bytes alive only during load + prepare (decoded samples and simplices, triangle
    /// vector and an assumed equal-size `RTree::bulk_load` working copy, read buffer).
    pub transient_bytes: u64,
    /// Source bytes on disk (files) or 0 (inline).
    pub source_bytes: u64,
}

impl ProfileEstimate {
    pub fn peak_bytes(&self) -> u64 {
        self.resident_bytes.saturating_add(self.transient_bytes)
    }
}

/// Bytes per JSON byte assumed for a fully parsed legacy request plus its preparation. Derived
/// from the worst-case textual densities (e.g. `0,` -> 16-byte `Option<f64>`, `[1,2,3],` -> 24-byte
/// simplex plus prepared triangle and bulk-load copy) with 2x `Vec` growth slack. A conservative
/// heuristic, not a proof: use `binary` sources where a tight pre-read estimate matters.
pub const LEGACY_JSON_PEAK_FACTOR: u64 = 64;
/// Chunk size of the streaming binary decoder.
pub const READ_CHUNK_BYTES: u64 = 1 << 20;

fn file_len(path: &Path) -> Result<u64, MapError> {
    Ok(fs::metadata(path)
        .map_err(|e| MapError::Io(format!("{}: {e}", path.display())))?
        .len())
}

/// Length of a little-endian record file after limit and multiple checks (no read).
fn binary_len(path: &Path, item: u64) -> Result<u64, MapError> {
    let len = file_len(path)?;
    if len > MAX_BINARY_BYTES {
        return Err(MapError::Budget(format!(
            "{} exceeds binary limit",
            path.display()
        )));
    }
    if len % item != 0 {
        return Err(MapError::Invalid(format!(
            "{}: length {len} is not a multiple of {item}",
            path.display()
        )));
    }
    Ok(len)
}

/// Streams `N`-byte little-endian records straight into their final vector (no whole-file
/// buffer). `len` comes from `binary_len`; a file that changes size meanwhile is an error.
fn read_records<const N: usize, T>(
    path: &Path,
    len: u64,
    mut decode: impl FnMut(&[u8; N]) -> Result<T, MapError>,
) -> Result<Vec<T>, MapError> {
    use std::io::Read;
    let io = |e: std::io::Error| MapError::Io(format!("{}: {e}", path.display()));
    let count = (len / N as u64) as usize;
    let mut f = fs::File::open(path).map_err(io)?;
    let mut out = Vec::with_capacity(count);
    let per_chunk = (READ_CHUNK_BYTES as usize / N).max(1);
    let mut buf = vec![0u8; per_chunk * N];
    while out.len() < count {
        let n = (count - out.len()).min(per_chunk) * N;
        f.read_exact(&mut buf[..n]).map_err(io)?;
        for c in buf[..n].as_chunks::<N>().0 {
            out.push(decode(c)?);
        }
    }
    if f.read(&mut [0u8; 1]).map_err(io)? != 0 {
        return Err(MapError::Invalid(format!(
            "{}: file grew while reading",
            path.display()
        )));
    }
    Ok(out)
}

pub fn read_json<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, MapError> {
    let len = fs::metadata(path)
        .map_err(|e| MapError::Io(format!("{}: {e}", path.display())))?
        .len();
    if len > MAX_JSON_BYTES {
        return Err(MapError::Budget(format!(
            "{} exceeds 512 MiB JSON limit",
            path.display()
        )));
    }
    let f = fs::File::open(path).map_err(|e| MapError::Io(format!("{}: {e}", path.display())))?;
    serde_json::from_reader(BufReader::new(f))
        .map_err(|e| MapError::Invalid(format!("{}: {e}", path.display())))
}

pub fn resolve(base: &Path, p: &str) -> PathBuf {
    let p = Path::new(p);
    if p.is_absolute() {
        p.to_path_buf()
    } else {
        base.join(p)
    }
}

impl GridSpec {
    pub fn dims(&self) -> (usize, usize) {
        match *self {
            GridSpec::Explicit { width, height, .. }
            | GridSpec::TerrainAligned { width, height, .. } => (width, height),
        }
    }
    pub fn pixels(&self) -> Result<u64, MapError> {
        let (w, h) = self.dims();
        let n = (w as u64)
            .checked_mul(h as u64)
            .ok_or_else(|| MapError::Invalid("grid dimensions overflow".into()))?;
        if n == 0 || n > MAX_PROFILE_PIXELS {
            return Err(MapError::Budget(format!(
                "grid must contain 1..={MAX_PROFILE_PIXELS} pixels"
            )));
        }
        Ok(n)
    }
}

impl ProfileSource {
    /// Loads the source into memory. `native` controls the legacy terrain handling.
    pub fn load(&self, base: &Path, native: bool) -> Result<ProfileData, MapError> {
        match self {
            ProfileSource::LegacyRequest { path } => {
                let path = resolve(base, path);
                let bytes = fs::metadata(&path)?.len();
                let r: LegacyRequest = read_json(&path)?;
                let simplices = r.simplices.ok_or_else(|| {
                    MapError::Unsupported(
                        "legacy request has no supplied simplices; native triangulation is not available in this prototype".into(),
                    )
                })?;
                let _ = r.allow_native_triangulation;
                let g = r.grid;
                let terrain = if native {
                    None
                } else {
                    Some(r.terrain.iter().map(|v| v.unwrap_or(f64::NAN)).collect())
                };
                Ok(ProfileData {
                    samples: r.samples,
                    simplices,
                    grid: GridSpec::Explicit {
                        width: g.width,
                        height: g.height,
                        x0: g.x0,
                        y0: g.y0,
                        dx: g.dx,
                        dy: g.dy,
                    },
                    mask: MaskData::Bits(r.mask),
                    terrain,
                    legacy_terrain_ignored: native,
                    source_bytes: bytes,
                })
            }
            ProfileSource::Inline {
                samples,
                simplices,
                grid,
                mask,
                mask_all_wet,
                terrain,
            } => Ok(ProfileData {
                samples: samples.clone(),
                simplices: simplices.clone(),
                grid: grid.clone(),
                mask: mask_data(mask.clone(), *mask_all_wet)?,
                terrain: terrain
                    .as_ref()
                    .map(|t| t.iter().map(|v| v.unwrap_or(f64::NAN)).collect()),
                legacy_terrain_ignored: false,
                source_bytes: 0,
            }),
            ProfileSource::Binary {
                samples_f64,
                simplices_u32,
                grid,
                mask_u8,
                mask_all_wet,
                terrain_f64,
            } => {
                // Lengths are re-checked here (the estimate may be stale) before any read.
                let lens = binary_lens(self, base)?;
                let f64_at = |c: &[u8], i: usize| {
                    let mut b = [0u8; 8];
                    b.copy_from_slice(&c[i * 8..i * 8 + 8]);
                    f64::from_le_bytes(b)
                };
                let samples = read_records::<24, _>(&resolve(base, samples_f64), lens[0], |c| {
                    Ok([f64_at(c, 0), f64_at(c, 1), f64_at(c, 2)])
                })?;
                let simplices =
                    read_records::<12, _>(&resolve(base, simplices_u32), lens[1], |c| {
                        let u = |i: usize| {
                            let mut b = [0u8; 4];
                            b.copy_from_slice(&c[i * 4..i * 4 + 4]);
                            u32::from_le_bytes(b) as usize
                        };
                        Ok([u(0), u(1), u(2)])
                    })?;
                let mask = match mask_u8 {
                    Some(p) => Some(read_records::<1, _>(
                        &resolve(base, p),
                        lens[2],
                        |c| match c[0] {
                            0 => Ok(false),
                            1 => Ok(true),
                            v => Err(MapError::Invalid(format!("mask byte {v} is not 0/1"))),
                        },
                    )?),
                    None => None,
                };
                let terrain = match terrain_f64 {
                    Some(p) => Some(read_records::<8, _>(&resolve(base, p), lens[3], |c| {
                        Ok(f64::from_le_bytes(*c))
                    })?),
                    None => None,
                };
                Ok(ProfileData {
                    samples,
                    simplices,
                    grid: grid.clone(),
                    mask: mask_data(mask, *mask_all_wet)?,
                    terrain,
                    legacy_terrain_ignored: false,
                    source_bytes: lens.iter().sum(),
                })
            }
        }
    }

    /// Memory estimate computed from request content and file lengths only (nothing is read).
    /// Binary sources also fail here, before any allocation, when mask/terrain lengths do not
    /// match the declared grid.
    pub fn estimate(&self, base: &Path) -> Result<ProfileEstimate, MapError> {
        let per_simplex = crate::interp::prepared_bytes_per_simplex();
        let tri = crate::interp::triangle_bytes();
        // Prepared structure + inputs alive during preparation (samples, simplices, triangle
        // vector, and an assumed equal-size bulk-load working copy).
        let shape = |n: u64, m: u64, mask: u64, terrain_px: u64| {
            let resident = m
                .saturating_mul(per_simplex)
                .saturating_add(mask)
                .saturating_add(terrain_px.saturating_mul(8));
            let transient = n
                .saturating_mul(24)
                .saturating_add(m.saturating_mul(24))
                .saturating_add(m.saturating_mul(tri).saturating_mul(2));
            (resident, transient)
        };
        match self {
            ProfileSource::LegacyRequest { path } => {
                let len = file_len(&resolve(base, path))?;
                if len > MAX_JSON_BYTES {
                    return Err(MapError::Budget(format!(
                        "{path} exceeds 512 MiB JSON limit"
                    )));
                }
                let peak = len.saturating_mul(LEGACY_JSON_PEAK_FACTOR);
                Ok(ProfileEstimate {
                    basis: "legacy_json_length_x64_heuristic",
                    resident_bytes: peak / 2,
                    transient_bytes: peak - peak / 2,
                    source_bytes: len,
                })
            }
            ProfileSource::Inline {
                samples,
                simplices,
                mask,
                terrain,
                ..
            } => {
                let (resident, transient) = shape(
                    samples.len() as u64,
                    simplices.len() as u64,
                    mask.as_ref().map_or(0, |m| m.len() as u64),
                    terrain.as_ref().map_or(0, |t| t.len() as u64),
                );
                Ok(ProfileEstimate {
                    basis: "inline_exact_lengths",
                    resident_bytes: resident,
                    transient_bytes: transient,
                    source_bytes: 0,
                })
            }
            ProfileSource::Binary { .. } => {
                let lens = binary_lens(self, base)?;
                let (resident, transient) = shape(lens[0] / 24, lens[1] / 12, lens[2], lens[3] / 8);
                Ok(ProfileEstimate {
                    basis: "binary_file_lengths",
                    resident_bytes: resident,
                    transient_bytes: transient.saturating_add(READ_CHUNK_BYTES),
                    source_bytes: lens.iter().sum(),
                })
            }
        }
    }
}

/// [samples, simplices, mask, terrain] byte lengths of a binary source, validated against the
/// declared grid without reading the files.
fn binary_lens(src: &ProfileSource, base: &Path) -> Result<[u64; 4], MapError> {
    let ProfileSource::Binary {
        samples_f64,
        simplices_u32,
        grid,
        mask_u8,
        terrain_f64,
        ..
    } = src
    else {
        return Err(MapError::Internal(
            "binary_lens on a non-binary source".into(),
        ));
    };
    let px = grid.pixels()?;
    let s = binary_len(&resolve(base, samples_f64), 24)?;
    let t = binary_len(&resolve(base, simplices_u32), 12)?;
    let m = match mask_u8 {
        Some(p) => {
            let len = binary_len(&resolve(base, p), 1)?;
            if len != px {
                return Err(MapError::Invalid(format!(
                    "mask has {len} values, grid has {px}"
                )));
            }
            len
        }
        None => 0,
    };
    let g = match terrain_f64 {
        Some(p) => {
            let len = binary_len(&resolve(base, p), 8)?;
            if len / 8 != px {
                return Err(MapError::Invalid(format!(
                    "terrain buffer has {} values, grid has {px}",
                    len / 8
                )));
            }
            len
        }
        None => 0,
    };
    Ok([s, t, m, g])
}

fn mask_data(mask: Option<Vec<bool>>, all: bool) -> Result<MaskData, MapError> {
    match (mask, all) {
        (Some(m), false) => Ok(MaskData::Bits(m)),
        (None, true) => Ok(MaskData::AllWet),
        _ => Err(MapError::Invalid(
            "exactly one of mask / mask_all_wet must be given".into(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_are_path_safe() {
        assert!(validate_id("wsel_max_1").is_ok());
        assert!(validate_id("..").is_err());
        assert!(validate_id("a/b").is_err());
        assert!(validate_id("").is_err());
    }

    #[test]
    fn ids_are_windows_safe() {
        for bad in [
            ".", "..", "a.", "reach.", "CON", "con", "Nul", "aux.txt", "PRN.x.y", "COM1", "com9",
            "LPT1", "lpt3.bin", "COM0",
        ] {
            assert!(validate_id(bad).is_err(), "{bad}");
        }
        for ok in [
            "CONX",
            "console",
            "COM10",
            "LPT",
            "nul_x",
            "a.b",
            ".hidden",
            "wsel_max_10",
            "COMA",
        ] {
            assert!(validate_id(ok).is_ok(), "{ok}");
        }
        assert_eq!(id_key("Reach_A"), id_key("reach_a"));
    }

    fn tiny(id: &str) -> serde_json::Value {
        serde_json::json!({"id": id, "source": {"kind": "inline", "samples": [[0,0,1],[1,0,1],[0,1,1]],
            "simplices": [[0,1,2]], "grid": {"kind": "explicit", "width": 2, "height": 2, "x0": 0, "y0": 0, "dx": 0.4, "dy": 0.4},
            "mask_all_wet": true, "terrain": [0, 0, 0, 0]}})
    }

    fn session(profiles: Vec<serde_json::Value>, aois: serde_json::Value) -> SessionRequest {
        serde_json::from_value(serde_json::json!({"schema": SESSION_SCHEMA, "crs_epsg": 2277,
            "terrain": {"mode": "caller_buffer"},
            "budgets": {"threads": 1, "max_cache_bytes": 0, "max_inflight_profiles": 1, "max_profile_bytes": 1 << 20,
                        "output_tile": 16, "max_tiles_in_flight": 1},
            "products": ["depth"], "profiles": profiles, "aois": aois, "error_policy": "isolate_profile"}))
        .unwrap()
    }

    #[test]
    fn case_colliding_ids_are_rejected() {
        let s = session(
            vec![tiny("A"), tiny("a")],
            serde_json::json!([{"id": "full"}]),
        );
        assert!(
            s.validate()
                .unwrap_err()
                .to_string()
                .contains("case-insensitive")
        );
        let s = session(
            vec![tiny("A")],
            serde_json::json!([{"id": "R"}, {"id": "r"}]),
        );
        assert!(s.validate().is_err());
        let s = session(vec![tiny("A")], serde_json::json!([{"id": "NUL"}]));
        assert!(s.validate().is_err());
        let s = session(
            vec![tiny("A"), tiny("B")],
            serde_json::json!([{"id": "full"}]),
        );
        assert!(s.validate().is_ok());
        assert_eq!(s.effective_tiles_in_flight(), 1);
        assert_eq!(s.output_buffer_bound().unwrap(), 16 * 16 * 40);
    }

    #[test]
    fn effective_in_flight_matches_pipeline() {
        let mut s = session(vec![tiny("A")], serde_json::json!([{"id": "full"}]));
        for (m, e) in [(1, 1), (2, 2), (3, 2), (5, 4), (16, 16)] {
            s.budgets.max_tiles_in_flight = m;
            assert_eq!(s.effective_tiles_in_flight(), e, "{m}");
        }
    }

    #[test]
    fn binary_estimate_needs_no_read_and_checks_lengths() {
        let d = std::env::temp_dir().join(format!("ras2fim-model-est-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        // 1000 samples, 2000 simplices; a 4-pixel grid and a mask of the wrong length.
        fs::write(d.join("s.f64"), vec![0u8; 24_000]).unwrap();
        fs::write(d.join("t.u32"), vec![0u8; 24_000]).unwrap();
        fs::write(d.join("m.u8"), vec![1u8; 5]).unwrap();
        let src = |mask: bool| -> ProfileSource {
            serde_json::from_value(serde_json::json!({"kind": "binary", "samples_f64": "s.f64",
                "simplices_u32": "t.u32", "grid": {"kind": "explicit", "width": 2, "height": 2,
                "x0": 0, "y0": 0, "dx": 1, "dy": 1}, "mask_u8": if mask {Some("m.u8")} else {None},
                "mask_all_wet": !mask}))
            .unwrap()
        };
        let e = src(false).estimate(&d).unwrap();
        let tri = crate::interp::triangle_bytes();
        assert_eq!(
            e.resident_bytes,
            2000 * crate::interp::prepared_bytes_per_simplex()
        );
        assert_eq!(
            e.transient_bytes,
            1000 * 24 + 2000 * 24 + 2 * 2000 * tri + READ_CHUNK_BYTES
        );
        assert_eq!(e.source_bytes, 48_000);
        let err = src(true).estimate(&d).unwrap_err();
        assert!(
            err.to_string().contains("mask has 5 values, grid has 4"),
            "{err}"
        );
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn grid_pixel_limits() {
        let g = GridSpec::Explicit {
            width: usize::MAX,
            height: 2,
            x0: 0.,
            y0: 0.,
            dx: 1.,
            dy: 1.,
        };
        assert!(g.pixels().is_err());
        let g = GridSpec::TerrainAligned {
            col: 0,
            row: 0,
            width: 0,
            height: 2,
        };
        assert!(g.pixels().is_err());
    }

    #[test]
    fn mask_exclusive() {
        assert!(mask_data(None, false).is_err());
        assert!(mask_data(Some(vec![true]), true).is_err());
    }
}
