//! Deterministic streaming directory sink with failure-safe unit commits.
//!
//! Layout: `<out>/units/<profile>/<aoi>/<product>.bin` (row-major over the unit window, grid row
//! order) plus `unit.json`. Tiles are written with positioned writes, so file bytes do not depend
//! on completion order; per-tile records are sorted canonically before `unit.json` is written.
//! Only the tiles in flight are held in memory; no catalog-wide raster or JSON is materialized.
//!
//! Commit protocol (a `.bin` is trustworthy only when `unit.json` says `complete`):
//! 1. `begin_unit` atomically writes `unit.json` with `status: in_progress` *before* any data,
//!    then creates `<product>.bin.partial` files.
//! 2. `end_unit` on success: `fsync` every partial (errors propagate), rename to `.bin`, sync the
//!    directory, then atomically replace `unit.json` with the `complete` document.
//! 3. On any failure (including commit failures and `abort_all` after a session error), the
//!    unit's data files are removed and `unit.json` is replaced with `status: failed`.
//! 4. A crash that prevents cleanup leaves `in_progress` plus `.partial` names: explicit state.
//!
//! Every JSON document is written to `<name>.partial`, fsynced and renamed (`write_json`).
use crate::MapError;
use crate::model::Product;
use serde::Serialize;
use serde::ser::{SerializeMap, SerializeSeq};
use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

/// Suffix of files that are not (yet) committed.
pub const PARTIAL_SUFFIX: &str = ".partial";

/// Pixel rectangle on a profile grid: col, row, width, height.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, PartialOrd, Ord)]
pub struct Rect {
    pub col: usize,
    pub row: usize,
    pub width: usize,
    pub height: usize,
}

impl Rect {
    pub fn intersect(&self, o: &Rect) -> Option<Rect> {
        let c0 = self.col.max(o.col);
        let r0 = self.row.max(o.row);
        let c1 = (self.col + self.width).min(o.col + o.width);
        let r1 = (self.row + self.height).min(o.row + o.height);
        (c0 < c1 && r0 < r1).then(|| Rect {
            col: c0,
            row: r0,
            width: c1 - c0,
            height: r1 - r0,
        })
    }
    pub fn pixels(&self) -> usize {
        self.width * self.height
    }
}

/// One evaluated tile: buffers cover `rect` row-major. NaN / -1 mark nodata.
pub struct TileOut {
    pub profile: usize,
    pub tile: (usize, usize),
    pub rect: Rect,
    pub raw_wse: Vec<f64>,
    pub wse: Vec<f64>,
    pub depth: Vec<f64>,
    pub ground: Vec<f64>,
    pub simplex_id: Vec<i64>,
}

/// Compact retained per-tile record (fixed size; hashes indexed like `DirSink::products`).
#[derive(Clone)]
pub struct TileRecord {
    tile_row: usize,
    tile_col: usize,
    rect: Rect,
    fnv1a64: [u64; 5],
    raw_wse_valid: u64,
    wet: u64,
}

/// Bytes retained per tile record until its unit closes (exact element size).
pub const TILE_RECORD_BYTES: u64 = std::mem::size_of::<TileRecord>() as u64;

/// The r1 serialized shape of a tile record; built one at a time while streaming `unit.json`
/// so the document bytes equal r1's for complete units.
#[derive(Serialize)]
struct TileRecordJson {
    tile_row: usize,
    tile_col: usize,
    rect: Rect,
    fnv1a64: BTreeMap<&'static str, String>,
    raw_wse_valid: u64,
    wet: u64,
}

struct UnitState {
    dir: PathBuf,
    window: Rect,
    header: serde_json::Value,
    files: Vec<(Product, File)>,
    tiles: Vec<TileRecord>,
    bytes: u64,
}

pub struct DirSink {
    root: PathBuf,
    products: Vec<Product>,
    /// (profile slot, aoi index) -> state, for profiles currently in flight.
    units: BTreeMap<(usize, usize), UnitState>,
    pub bytes_written: u64,
    pub tiles_written: u64,
    pub unit_files_written: u64,
    /// Directory fsyncs the filesystem rejected as unsupported (data files are still synced).
    pub dir_sync_unsupported: u64,
}

pub fn fnv1a64(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in bytes {
        h ^= *b as u64;
        h = h.wrapping_mul(0x100000001b3);
    }
    h
}

#[cfg(unix)]
fn write_at(f: &File, buf: &[u8], off: u64) -> std::io::Result<()> {
    use std::os::unix::fs::FileExt;
    f.write_all_at(buf, off)
}

#[cfg(windows)]
fn write_at(f: &File, mut buf: &[u8], mut off: u64) -> std::io::Result<()> {
    use std::os::windows::fs::FileExt;
    while !buf.is_empty() {
        let n = f.seek_write(buf, off)?;
        if n == 0 {
            return Err(std::io::Error::other("short positioned write"));
        }
        buf = &buf[n..];
        off += n as u64;
    }
    Ok(())
}

fn io_at(path: &Path, e: std::io::Error) -> MapError {
    MapError::Io(format!("{}: {e}", path.display()))
}

fn partial(path: &Path) -> PathBuf {
    let mut s = path.as_os_str().to_os_string();
    s.push(PARTIAL_SUFFIX);
    PathBuf::from(s)
}

/// Syncs a directory so renames are durable. Returns Ok(false) when the filesystem does not
/// support directory fsync (EINVAL/unsupported); other errors propagate. No-op on Windows.
fn sync_dir(dir: &Path) -> Result<bool, MapError> {
    #[cfg(unix)]
    {
        let r = File::open(dir).and_then(|d| d.sync_all());
        match r {
            Ok(()) => Ok(true),
            Err(e)
                if e.kind() == std::io::ErrorKind::InvalidInput
                    || e.kind() == std::io::ErrorKind::Unsupported =>
            {
                Ok(false)
            }
            Err(e) => Err(io_at(dir, e)),
        }
    }
    #[cfg(not(unix))]
    {
        let _ = dir;
        Ok(false)
    }
}

/// Writes `<path>.partial`, fsyncs it (errors propagate) and renames it over `path`.
fn write_atomic(
    path: &Path,
    fill: impl FnOnce(&mut std::io::BufWriter<&File>) -> Result<(), MapError>,
) -> Result<(), MapError> {
    let tmp = partial(path);
    let result = (|| {
        let f = File::create(&tmp).map_err(|e| io_at(&tmp, e))?;
        {
            let mut w = std::io::BufWriter::new(&f);
            fill(&mut w)?;
            w.flush().map_err(|e| io_at(&tmp, e))?;
        }
        f.sync_all().map_err(|e| io_at(&tmp, e))?;
        drop(f);
        fs::rename(&tmp, path).map_err(|e| io_at(path, e))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&tmp);
    }
    result
}

/// Atomic pretty JSON write (temp file, fsync, rename).
pub fn write_json(path: &Path, v: &serde_json::Value) -> Result<(), MapError> {
    write_atomic(path, |w| {
        serde_json::to_writer_pretty(w, v)
            .map_err(|e| MapError::Io(format!("{}: {e}", path.display())))
    })
}

/// Streams a unit document: `doc`'s entries in their own order, with the `tiles` placeholder
/// replaced by the records (serialized one at a time). Equal bytes to `to_vec_pretty` of the
/// fully materialized r1 document, without holding a JSON tree of every record.
struct UnitDoc<'a> {
    doc: &'a serde_json::Map<String, serde_json::Value>,
    tiles: &'a [TileRecord],
    names: &'a [&'static str],
}

struct TilesSeq<'a> {
    tiles: &'a [TileRecord],
    names: &'a [&'static str],
}

impl Serialize for TilesSeq<'_> {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        let mut seq = s.serialize_seq(Some(self.tiles.len()))?;
        for t in self.tiles {
            let rec = TileRecordJson {
                tile_row: t.tile_row,
                tile_col: t.tile_col,
                rect: t.rect,
                fnv1a64: self
                    .names
                    .iter()
                    .zip(t.fnv1a64)
                    .map(|(n, h)| (*n, format!("{h:016x}")))
                    .collect(),
                raw_wse_valid: t.raw_wse_valid,
                wet: t.wet,
            };
            // r1 serialized `to_value(records)`; per-record values reproduce it exactly.
            let v = serde_json::to_value(&rec).map_err(serde::ser::Error::custom)?;
            seq.serialize_element(&v)?;
        }
        seq.end()
    }
}

impl Serialize for UnitDoc<'_> {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        let mut m = s.serialize_map(Some(self.doc.len()))?;
        for (k, v) in self.doc {
            if k == "tiles" {
                m.serialize_entry(
                    k,
                    &TilesSeq {
                        tiles: self.tiles,
                        names: self.names,
                    },
                )?;
            } else {
                m.serialize_entry(k, v)?;
            }
        }
        m.end()
    }
}

impl DirSink {
    /// `out` must not exist; it is created (parent must exist).
    pub fn create(out: &Path, products: &[Product]) -> Result<Self, MapError> {
        fs::create_dir(out).map_err(|e| {
            MapError::Io(format!(
                "{}: {e} (output directory must be new)",
                out.display()
            ))
        })?;
        fs::create_dir(out.join("units")).map_err(|e| io_at(&out.join("units"), e))?;
        let mut products = products.to_vec();
        products.sort();
        if products.len() > 5 {
            return Err(MapError::Internal("more than five products".into()));
        }
        Ok(Self {
            root: out.to_path_buf(),
            products,
            units: BTreeMap::new(),
            bytes_written: 0,
            tiles_written: 0,
            unit_files_written: 0,
            dir_sync_unsupported: 0,
        })
    }

    pub fn unit_dir(&self, profile_id: &str, aoi_id: &str) -> PathBuf {
        self.root.join("units").join(profile_id).join(aoi_id)
    }

    fn data_path(dir: &Path, p: Product) -> PathBuf {
        dir.join(format!("{}.bin", p.name()))
    }

    /// Opens a unit; `window` None writes an `empty` unit immediately. `expected_tiles` (exact
    /// count of tiles intersecting the window) reserves the record vector once.
    pub fn begin_unit(
        &mut self,
        key: (usize, usize),
        profile_id: &str,
        aoi_id: &str,
        window: Option<Rect>,
        header: &serde_json::Value,
        expected_tiles: usize,
    ) -> Result<(), MapError> {
        let dir = self.unit_dir(profile_id, aoi_id);
        fs::create_dir_all(&dir).map_err(|e| io_at(&dir, e))?;
        let Some(window) = window else {
            let mut doc = header.clone();
            doc["status"] = "empty_window".into();
            return write_json(&dir.join("unit.json"), &doc);
        };
        // Explicit state before any data byte exists.
        let mut marker = header.clone();
        marker["status"] = "in_progress".into();
        write_json(&dir.join("unit.json"), &marker)?;
        let mut tiles = Vec::new();
        tiles
            .try_reserve_exact(expected_tiles)
            .map_err(|e| MapError::Budget(format!("tile records for {}: {e}", dir.display())))?;
        // Registered before files are created, so a failure below is cleaned up by `abort_all`.
        self.units.insert(
            key,
            UnitState {
                dir: dir.clone(),
                window,
                header: header.clone(),
                files: Vec::new(),
                tiles,
                bytes: 0,
            },
        );
        let u = self.units.get_mut(&key).expect("just inserted");
        for p in &self.products {
            let path = partial(&Self::data_path(&dir, *p));
            let f = OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(|e| io_at(&path, e))?;
            u.files.push((*p, f));
            let (_, f) = u.files.last().expect("just pushed");
            f.set_len(window.pixels() as u64 * 8)
                .map_err(|e| io_at(&path, e))?;
        }
        Ok(())
    }

    /// Writes the part of `t` inside every open unit of its profile.
    pub fn write_tile(&mut self, t: &TileOut, aoi_count: usize) -> Result<(), MapError> {
        let mut row_buf: Vec<u8> = Vec::with_capacity(t.rect.width * 8);
        for aoi in 0..aoi_count {
            let Some(u) = self.units.get_mut(&(t.profile, aoi)) else {
                continue;
            };
            let Some(ix) = u.window.intersect(&t.rect) else {
                continue;
            };
            let mut rec = TileRecord {
                tile_row: t.tile.0,
                tile_col: t.tile.1,
                rect: ix,
                fnv1a64: [0; 5],
                raw_wse_valid: 0,
                wet: 0,
            };
            for r in ix.row..ix.row + ix.height {
                let src = (r - t.rect.row) * t.rect.width + (ix.col - t.rect.col);
                for c in 0..ix.width {
                    rec.raw_wse_valid +=
                        (!t.raw_wse.is_empty() && !t.raw_wse[src + c].is_nan()) as u64;
                    rec.wet += (!t.wse.is_empty() && !t.wse[src + c].is_nan()) as u64;
                }
            }
            for (pi, (p, f)) in u.files.iter().enumerate() {
                let mut hash: u64 = 0xcbf29ce484222325;
                for r in ix.row..ix.row + ix.height {
                    let src = (r - t.rect.row) * t.rect.width + (ix.col - t.rect.col);
                    row_buf.clear();
                    match p {
                        Product::SimplexId => {
                            for v in &t.simplex_id[src..src + ix.width] {
                                row_buf.extend_from_slice(&v.to_le_bytes());
                            }
                        }
                        _ => {
                            let s = match p {
                                Product::RawWse => &t.raw_wse,
                                Product::Wse => &t.wse,
                                Product::Depth => &t.depth,
                                _ => &t.ground,
                            };
                            for v in &s[src..src + ix.width] {
                                row_buf.extend_from_slice(&v.to_le_bytes());
                            }
                        }
                    }
                    for b in &row_buf {
                        hash ^= *b as u64;
                        hash = hash.wrapping_mul(0x100000001b3);
                    }
                    let off = (((r - u.window.row) * u.window.width + (ix.col - u.window.col)) * 8)
                        as u64;
                    write_at(f, &row_buf, off)
                        .map_err(|e| io_at(&partial(&Self::data_path(&u.dir, *p)), e))?;
                    u.bytes += row_buf.len() as u64;
                    self.bytes_written += row_buf.len() as u64;
                }
                rec.fnv1a64[pi] = hash;
            }
            u.tiles.push(rec);
        }
        self.tiles_written += 1;
        Ok(())
    }

    /// Removes a unit's data files (both names) and records `failed`. Returns cleanup problems.
    fn fail_unit(u: UnitState, e: &MapError, products: &[Product]) -> Vec<String> {
        let mut problems = Vec::new();
        drop(u.files);
        for p in products {
            let fin = Self::data_path(&u.dir, *p);
            for path in [partial(&fin), fin] {
                match fs::remove_file(&path) {
                    Ok(()) => {}
                    Err(x) if x.kind() == std::io::ErrorKind::NotFound => {}
                    Err(x) => problems.push(format!("remove {}: {x}", path.display())),
                }
            }
        }
        let mut doc = u.header;
        doc["status"] = "failed".into();
        doc["error"] = serde_json::json!({"kind": e.kind(), "message": e.to_string()});
        if let Err(x) = write_json(&u.dir.join("unit.json"), &doc) {
            problems.push(format!("failed-status unit.json: {x}"));
        }
        problems
    }

    /// Closes a unit: success commits it (see module docs); failure removes partial data.
    /// A commit failure marks the unit failed and returns the error.
    pub fn end_unit(
        &mut self,
        key: (usize, usize),
        header: &serde_json::Value,
        error: Option<&MapError>,
    ) -> Result<(), MapError> {
        let Some(mut u) = self.units.remove(&key) else {
            return Ok(());
        };
        u.header = header.clone();
        if let Some(e) = error {
            let problems = Self::fail_unit(u, e, &self.products);
            return match problems.is_empty() {
                true => Ok(()),
                false => Err(MapError::Io(format!(
                    "cleanup of failed unit: {}",
                    problems.join("; ")
                ))),
            };
        }
        match self.commit(&mut u) {
            Ok(()) => {
                self.unit_files_written += self.products.len() as u64;
                Ok(())
            }
            Err(e) => {
                let problems = Self::fail_unit(u, &e, &self.products);
                Err(match problems.is_empty() {
                    true => e,
                    false => MapError::Io(format!("{e}; cleanup: {}", problems.join("; "))),
                })
            }
        }
    }

    fn commit(&mut self, u: &mut UnitState) -> Result<(), MapError> {
        let expected: usize = u.tiles.iter().map(|t| t.rect.pixels()).sum();
        if expected != u.window.pixels() {
            return Err(MapError::Internal(format!(
                "unit {:?} tiles cover {expected} of {} pixels",
                u.dir,
                u.window.pixels()
            )));
        }
        for (p, f) in u.files.drain(..) {
            let tmp = partial(&Self::data_path(&u.dir, p));
            f.sync_all().map_err(|e| io_at(&tmp, e))?;
            drop(f);
            fs::rename(&tmp, Self::data_path(&u.dir, p)).map_err(|e| io_at(&tmp, e))?;
        }
        if !sync_dir(&u.dir)? {
            self.dir_sync_unsupported += 1;
        }
        u.tiles.sort_by_key(|t| (t.tile_row, t.tile_col));
        let mut doc = u.header.clone();
        doc["status"] = "complete".into();
        doc["raw_wse_valid"] = u.tiles.iter().map(|t| t.raw_wse_valid).sum::<u64>().into();
        doc["wet"] = u.tiles.iter().map(|t| t.wet).sum::<u64>().into();
        doc["data_bytes"] = u.bytes.into();
        doc["tiles"] = serde_json::Value::Null; // placeholder: streamed below
        let names: Vec<&'static str> = self.products.iter().map(|p| p.name()).collect();
        let map = doc
            .as_object()
            .ok_or_else(|| MapError::Internal("unit header is not an object".into()))?;
        let path = u.dir.join("unit.json");
        write_atomic(&path, |w| {
            serde_json::to_writer_pretty(
                w,
                &UnitDoc {
                    doc: map,
                    tiles: &u.tiles,
                    names: &names,
                },
            )
            .map_err(|e| io_at(&path, std::io::Error::other(e)))
        })
    }

    /// After a session-level error: fails every open unit (removing its data) and returns the
    /// cleanup problems that could not be resolved (empty when every unit is cleanly failed).
    pub fn abort_all(&mut self, e: &MapError) -> Vec<String> {
        let units = std::mem::take(&mut self.units);
        let mut problems = Vec::new();
        for (_, u) in units {
            problems.extend(Self::fail_unit(u, e, &self.products));
        }
        problems
    }

    pub fn open_units(&self) -> usize {
        self.units.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rect_intersection() {
        let a = Rect {
            col: 0,
            row: 0,
            width: 10,
            height: 10,
        };
        let b = Rect {
            col: 5,
            row: 8,
            width: 10,
            height: 10,
        };
        assert_eq!(
            a.intersect(&b),
            Some(Rect {
                col: 5,
                row: 8,
                width: 5,
                height: 2
            })
        );
        let c = Rect {
            col: 10,
            row: 0,
            width: 1,
            height: 1,
        };
        assert_eq!(a.intersect(&c), None);
    }

    #[test]
    fn fnv_reference() {
        assert_eq!(fnv1a64(b""), 0xcbf29ce484222325);
        assert_eq!(fnv1a64(b"a"), 0xaf63dc4c8601ec8c);
    }

    fn scratch(name: &str) -> PathBuf {
        let d =
            std::env::temp_dir().join(format!("ras2fim-sink-unit-{}-{name}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        d
    }

    fn tile(profile: usize, rect: Rect) -> TileOut {
        let n = rect.pixels();
        TileOut {
            profile,
            tile: (0, 0),
            rect,
            raw_wse: vec![1.5; n],
            wse: vec![1.5; n],
            depth: vec![0.5; n],
            ground: vec![1.0; n],
            simplex_id: vec![3; n],
        }
    }

    fn names(dir: &Path) -> Vec<String> {
        let mut v: Vec<String> = fs::read_dir(dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        v.sort();
        v
    }

    const R: Rect = Rect {
        col: 0,
        row: 0,
        width: 4,
        height: 2,
    };

    #[test]
    fn commit_renames_partials_and_streams_unit_json() {
        let d = scratch("commit");
        let mut s = DirSink::create(&d, &[Product::Wse, Product::Depth]).unwrap();
        let h = serde_json::json!({"schema": "x", "profile": "p"});
        s.begin_unit((0, 0), "p", "a", Some(R), &h, 1).unwrap();
        let u = d.join("units/p/a");
        assert_eq!(
            names(&u),
            ["depth.bin.partial", "unit.json", "wse.bin.partial"]
        );
        let marker: serde_json::Value =
            serde_json::from_slice(&fs::read(u.join("unit.json")).unwrap()).unwrap();
        assert_eq!(marker["status"], "in_progress");
        s.write_tile(&tile(0, R), 1).unwrap();
        s.end_unit((0, 0), &h, None).unwrap();
        assert_eq!(names(&u), ["depth.bin", "unit.json", "wse.bin"]);
        let doc: serde_json::Value =
            serde_json::from_slice(&fs::read(u.join("unit.json")).unwrap()).unwrap();
        assert_eq!(doc["status"], "complete");
        assert_eq!(
            doc["tiles"][0]["fnv1a64"]["wse"].as_str().unwrap().len(),
            16
        );
        // Streamed bytes equal the r1 materialized document.
        let mut r1 = h.clone();
        r1["status"] = "complete".into();
        r1["raw_wse_valid"] = 8.into();
        r1["wet"] = 8.into();
        r1["data_bytes"] = 128.into();
        r1["tiles"] = doc["tiles"].clone();
        assert_eq!(
            fs::read(u.join("unit.json")).unwrap(),
            serde_json::to_vec_pretty(&r1).unwrap()
        );
        assert_eq!(fs::read(u.join("wse.bin")).unwrap().len(), 64);
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn failed_and_aborted_units_leave_no_data() {
        let d = scratch("abort");
        let mut s = DirSink::create(&d, &[Product::Wse]).unwrap();
        let h = serde_json::json!({"schema": "x"});
        s.begin_unit((0, 0), "p", "a", Some(R), &h, 1).unwrap();
        s.begin_unit((0, 1), "p", "b", Some(R), &h, 1).unwrap();
        s.write_tile(&tile(0, R), 2).unwrap();
        s.end_unit((0, 0), &h, Some(&MapError::Terrain("bad block".into())))
            .unwrap();
        assert!(s.abort_all(&MapError::Io("disk full".into())).is_empty());
        assert_eq!(s.open_units(), 0);
        for (aoi, msg) in [("a", "bad block"), ("b", "disk full")] {
            let u = d.join("units/p").join(aoi);
            assert_eq!(names(&u), ["unit.json"], "{aoi}");
            let doc: serde_json::Value =
                serde_json::from_slice(&fs::read(u.join("unit.json")).unwrap()).unwrap();
            assert_eq!(doc["status"], "failed");
            assert!(doc["error"]["message"].as_str().unwrap().contains(msg));
        }
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn incomplete_coverage_fails_the_unit() {
        let d = scratch("cover");
        let mut s = DirSink::create(&d, &[Product::Wse]).unwrap();
        let h = serde_json::json!({"schema": "x"});
        s.begin_unit((0, 0), "p", "a", Some(R), &h, 1).unwrap();
        let e = s.end_unit((0, 0), &h, None).unwrap_err();
        assert_eq!(e.kind(), "internal");
        let u = d.join("units/p/a");
        assert_eq!(names(&u), ["unit.json"]);
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn write_json_is_atomic_replace() {
        let d = scratch("json");
        fs::create_dir_all(&d).unwrap();
        let p = d.join("r.json");
        write_json(&p, &serde_json::json!({"a": 1})).unwrap();
        write_json(&p, &serde_json::json!({"a": 2})).unwrap();
        assert_eq!(names(&d), ["r.json"]);
        assert_eq!(
            fs::read(&p).unwrap(),
            serde_json::to_vec_pretty(&serde_json::json!({"a": 2})).unwrap()
        );
        let _ = fs::remove_dir_all(&d);
    }
}
