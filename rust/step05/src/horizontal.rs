//! Horizontal cell-constant mapping. Caller supplies deterministic pixel ownership;
//! native terrain is decoded once for the constrained window and reused across profiles.
//! No triangulation, resampling, per-pixel cache lock, or GDAL dependency.
use crate::{
    MapError,
    model::{self, CrsIdentity, NodataPolicy, QueryConvention},
    sink,
    terrain::NativeTerrain,
};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{
    collections::HashSet,
    fs::{self, File},
    io::{BufWriter, Write},
    path::Path,
    time::Instant,
};

pub const SCHEMA: &str = "ras2fim-horizontal-request/1";
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub terrain: String,
    pub epsg: u32,
    pub crs_identity: CrsIdentity,
    pub terrain_transform: [f64; 6],
    pub window: [usize; 4], // col, row, width, height
    pub owner_file: String, // u32 little endian, 0=dry, i+1=cell table position
    pub cell_count: usize,
    pub profiles: Vec<Profile>,
    pub min_depth: f64,
    pub threads: usize,
    pub max_working_bytes: u64,
    #[serde(default)]
    pub stream_outputs: bool,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub id: String,
    pub values_file: String,
}

pub fn method_record() -> Value {
    json!({"method_id":"horizontal-cell-constant/1", "backend":"rust", "stream_outputs":true,
        "arithmetic":"float32 cell WSE minus float32 terrain; strict float32 depth threshold",
        "ownership":"caller-supplied centre-based u32 labels; 0 dry; cell position + 1",
        "terrain":"same-CRS north-up square float32 GeoTIFF; native terrio block reads once per window",
        "reuse":"terrain and ownership shared across all profiles; pixel parallelism inside bounded Rayon pool",
        "scope":"2D horizontal cells only; no native sloping, 1D or structure renderer"})
}
fn bytes(count: usize, width: usize) -> Result<u64, MapError> {
    count
        .checked_mul(width)
        .and_then(|v| u64::try_from(v).ok())
        .ok_or_else(|| MapError::Budget("horizontal size overflow".into()))
}
fn read_bytes(path: &Path, expected: u64) -> Result<Vec<u8>, MapError> {
    if fs::metadata(path)?.len() != expected {
        return Err(MapError::Invalid(format!(
            "{}: expected {expected} bytes",
            path.display()
        )));
    }
    let data = fs::read(path)?;
    if data.len() as u64 != expected {
        return Err(MapError::Invalid("input size changed".into()));
    }
    Ok(data)
}
fn read_values(path: &Path, count: usize) -> Result<Vec<f32>, MapError> {
    let raw = read_bytes(path, bytes(count, 4)?)?;
    let values: Vec<_> = raw
        .chunks_exact(4)
        .map(|v| f32::from_le_bytes(v.try_into().unwrap()))
        .collect();
    if values.iter().any(|v| v.is_infinite()) {
        return Err(MapError::Invalid(
            "horizontal WSE must be finite or NaN".into(),
        ));
    }
    Ok(values)
}
fn write_f32(writer: &mut impl Write, values: &[f32]) -> Result<(), MapError> {
    let mut buffer = vec![0_u8; 65536];
    for chunk in values.chunks(16384) {
        for (value, bytes) in chunk.iter().zip(buffer.chunks_exact_mut(4)) {
            bytes.copy_from_slice(&value.to_le_bytes());
        }
        writer.write_all(&buffer[..chunk.len() * 4])?;
    }
    Ok(())
}
fn write_values(path: &Path, values: &[f32]) -> Result<(), MapError> {
    let partial = path.with_extension("bin.partial");
    let mut writer = BufWriter::new(File::create(&partial)?);
    write_f32(&mut writer, values)?;
    writer.flush()?;
    writer.get_ref().sync_all()?;
    fs::rename(partial, path)?;
    Ok(())
}
/// Pure float32 kernel; each pixel is independent and never uses fused operations.
fn evaluate(
    owner: &[u32],
    ground: &[f32],
    values: &[f32],
    threshold: f32,
    depth: &mut [f32],
    wse: &mut [f32],
) -> Result<(), MapError> {
    depth
        .par_iter_mut()
        .zip(wse.par_iter_mut())
        .enumerate()
        .try_for_each(|(i, (d, w))| {
            let label = owner[i] as usize;
            if label == 0 || !ground[i].is_finite() {
                return Ok(());
            }
            let value = values[label - 1];
            if value.is_nan() {
                return Ok(());
            }
            let delta = value - ground[i];
            if delta.is_infinite() {
                return Err(MapError::Invalid("float32 depth overflow".into()));
            }
            if delta > threshold {
                *d = delta;
                *w = value;
            }
            Ok(())
        })
}
pub fn run(req: &Request, base: &Path, out: &Path) -> Result<Value, MapError> {
    let started = Instant::now();
    if req.schema != SCHEMA
        || !(1..=64).contains(&req.threads)
        || req.profiles.is_empty()
        || req.epsg == 0
        || req.cell_count == 0
        || req.cell_count >= u32::MAX as usize
        || !req.min_depth.is_finite()
        || req.min_depth < 0.0
    {
        return Err(MapError::Invalid(
            "invalid horizontal schema, profiles, cells, threshold or thread count".into(),
        ));
    }
    let [col, row, width, height] = req.window;
    let count = width
        .checked_mul(height)
        .filter(|n| *n > 0 && *n <= model::MAX_PROFILE_PIXELS as usize)
        .ok_or_else(|| MapError::Budget("horizontal window empty or too large".into()))?;
    let mut ids = HashSet::new();
    for p in &req.profiles {
        model::validate_id(&p.id)?;
        if !ids.insert(model::id_key(&p.id)) {
            return Err(MapError::Invalid("duplicate profile id".into()));
        }
    }
    // Fixed resident cache plus conservative array/IO-copy admission. Decoder transients are
    // included separately after inspecting the terrain layout; this is not an OS RSS cap.
    let cache = 64_u64 << 20;
    let planned = bytes(count, 40)?
        .checked_add(bytes(req.cell_count, 12)?)
        .and_then(|v| v.checked_add(cache))
        .ok_or_else(|| MapError::Budget("size overflow".into()))?;
    if planned > req.max_working_bytes {
        return Err(MapError::Budget(
            "horizontal array plan exceeds budget".into(),
        ));
    }
    let terrain_path = model::resolve(base, &req.terrain);
    let terrain = NativeTerrain::open(
        terrain_path
            .to_str()
            .ok_or_else(|| MapError::Invalid("terrain path not UTF-8".into()))?,
        req.epsg,
        &req.crs_identity,
        QueryConvention::PixelCenter,
        NodataPolicy::Dry,
        cache,
    )?;
    if terrain.nodata.is_none()
        || terrain.gt != req.terrain_transform
        || (terrain.gt[1] + terrain.gt[5]).abs() > terrain.gt[1].abs() * 1e-12
        || col.checked_add(width).is_none_or(|v| v > terrain.width)
        || row.checked_add(height).is_none_or(|v| v > terrain.height)
    {
        return Err(MapError::Unsupported(
            "horizontal terrain identity, nodata, square grid or window mismatch".into(),
        ));
    }
    if terrain.max_block_bytes() > cache {
        return Err(MapError::Unsupported(
            "terrain block exceeds 64 MiB; export tiled terrain".into(),
        ));
    }
    let admitted = planned
        .checked_add(terrain.decoder_transient_bytes_per_load())
        .ok_or_else(|| MapError::Budget("terrain transient size overflow".into()))?;
    if admitted > req.max_working_bytes {
        return Err(MapError::Budget(
            "terrain decode plan exceeds budget".into(),
        ));
    }
    // Check all lengths before reading pixel arrays.
    let owner_path = model::resolve(base, &req.owner_file);
    if fs::metadata(&owner_path)?.len() != bytes(count, 4)? {
        return Err(MapError::Invalid("owner length mismatch".into()));
    }
    for p in &req.profiles {
        if fs::metadata(model::resolve(base, &p.values_file))?.len() != bytes(req.cell_count, 4)? {
            return Err(MapError::Invalid(format!(
                "{}: values length mismatch",
                p.id
            )));
        }
    }
    fs::create_dir(out)?;
    let mut report = json!({"schema":"ras2fim-horizontal-report/1", "status":"in_progress",
        "method":method_record(), "window":req.window, "planned_bytes":admitted,
        "threads":req.threads, "profiles":[]});
    sink::write_json(&out.join("report.json"), &report)?;
    let execution = std::panic::catch_unwind(std::panic::AssertUnwindSafe(
        || -> Result<(), MapError> {
            let raw = read_bytes(&owner_path, bytes(count, 4)?)?;
            let owner: Vec<_> = raw
                .chunks_exact(4)
                .map(|v| u32::from_le_bytes(v.try_into().unwrap()))
                .collect();
            drop(raw);
            if owner.iter().any(|v| *v as usize > req.cell_count) {
                return Err(MapError::Invalid("owner index exceeds cell table".into()));
            }
            let mut ground = vec![f32::NAN; count];
            let (bw, bh) = terrain.block;
            for by in row / bh..=(row + height - 1) / bh {
                for bx in col / bw..=(col + width - 1) / bw {
                    let block = terrain.get_block(bx, by)?;
                    let win = terrain.block_window(bx, by);
                    for r in row.max(win.y)..(row + height).min(win.y + win.height) {
                        for c in col.max(win.x)..(col + width).min(win.x + win.width) {
                            let v = block[(r - win.y) * win.width + c - win.x];
                            if let Some(value) = terrain.classify(v) {
                                if !value.is_finite() {
                                    return Err(MapError::Terrain(
                                        "unmasked infinite terrain".into(),
                                    ));
                                }
                                ground[(r - row) * width + c - col] = value as f32;
                            }
                        }
                    }
                }
            }
            report["terrain_prepare_seconds"] = started.elapsed().as_secs_f64().into();
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(req.threads)
                .build()
                .map_err(|e| MapError::Internal(e.to_string()))?;
            for p in &req.profiles {
                let tick = Instant::now();
                let dir = out.join(&p.id);
                fs::create_dir(&dir)?;
                let result = (|| -> Result<(), MapError> {
                    let values =
                        read_values(&model::resolve(base, &p.values_file), req.cell_count)?;
                    let mut depth = vec![f32::NAN; count];
                    let mut wse = vec![f32::NAN; count];
                    pool.install(|| {
                        evaluate(
                            &owner,
                            &ground,
                            &values,
                            req.min_depth as f32,
                            &mut depth,
                            &mut wse,
                        )
                    })?;
                    if req.stream_outputs {
                        let stdout = std::io::stdout();
                        let mut stream = BufWriter::with_capacity(65536, stdout.lock());
                        writeln!(
                            stream,
                            "{}",
                            json!({"id":p.id,"status":"complete","pixels":count})
                        )?;
                        write_f32(&mut stream, &depth)?;
                        write_f32(&mut stream, &wse)?;
                        stream.flush()?;
                    } else {
                        write_values(&dir.join("depth.bin"), &depth)?;
                        write_values(&dir.join("wse.bin"), &wse)?;
                    }
                    Ok(())
                })();
                let unit = match result {
                    Ok(()) => {
                        json!({"id":p.id,"status":"complete","seconds":tick.elapsed().as_secs_f64()})
                    }
                    Err(e) => {
                        for name in [
                            "depth.bin",
                            "wse.bin",
                            "depth.bin.partial",
                            "wse.bin.partial",
                        ] {
                            let _ = fs::remove_file(dir.join(name));
                        }
                        json!({"id":p.id,"status":"failed","error":e.to_string()})
                    }
                };
                if req.stream_outputs && unit["status"] == "failed" {
                    let stdout = std::io::stdout();
                    let mut stream = stdout.lock();
                    writeln!(stream, "{}", unit)?;
                    stream.flush()?;
                }
                sink::write_json(&dir.join("unit.json"), &unit)?;
                report["profiles"].as_array_mut().unwrap().push(unit);
                sink::write_json(&out.join("report.json"), &report)?;
            }
            Ok(())
        },
    ));
    match execution {
        Ok(Ok(())) => {
            report["status"] = if report["profiles"]
                .as_array()
                .unwrap()
                .iter()
                .all(|p| p["status"] == "complete")
            {
                "complete".into()
            } else {
                "failed".into()
            };
        }
        other => {
            let message = match other {
                Ok(Err(e)) => e.to_string(),
                _ => "horizontal internal panic".into(),
            };
            report["status"] = "aborted".into();
            report["error"] = message.into();
            // Mark all earlier outputs invalid after a session failure.
            for p in &req.profiles {
                let dir = out.join(&p.id);
                if dir.is_dir() {
                    for name in [
                        "depth.bin",
                        "wse.bin",
                        "depth.bin.partial",
                        "wse.bin.partial",
                    ] {
                        let _ = fs::remove_file(dir.join(name));
                    }
                    sink::write_json(
                        &dir.join("unit.json"),
                        &json!({"id":p.id,"status":"failed","error":"session aborted"}),
                    )?;
                }
            }
            report["profiles"] = req
                .profiles
                .iter()
                .map(|p| json!({"id":p.id,"status":"failed","error":"session aborted"}))
                .collect::<Vec<_>>()
                .into();
        }
    }
    report["total_seconds"] = started.elapsed().as_secs_f64().into();
    sink::write_json(&out.join("report.json"), &report)?;
    Ok(report)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn strict_float32_threshold_and_dry() {
        let mut d = vec![f32::NAN; 5];
        let mut w = d.clone();
        evaluate(
            &[1, 2, 0, 1, 3],
            &[100., 100., 100., f32::NAN, 100.],
            &[100.5, 101., f32::NAN],
            0.5,
            &mut d,
            &mut w,
        )
        .unwrap();
        assert!(d[0].is_nan() && d[2].is_nan() && d[3].is_nan() && d[4].is_nan());
        assert_eq!(d[1], 1.);
        assert_eq!(w[1], 101.);
    }
}
