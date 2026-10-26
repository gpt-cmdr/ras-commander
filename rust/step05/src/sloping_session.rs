//! Explicit plain-sloping batch path. Geometry, terrain and ownership are shared
//! across profiles; hydraulic connectivity is reconstructed for every profile.
use crate::{
    MapError,
    model::{self, CrsIdentity, NodataPolicy, QueryConvention},
    sink,
    sloping::{self, Cell, Corner, Face, Mesh},
    terrain::NativeTerrain,
};
use rayon::prelude::*;
use serde::Deserialize;
use serde_json::{Value, json};
use std::{collections::HashSet, fs, io::Write, path::Path, time::Instant};

pub const SCHEMA: &str = "ras-commander-sloping-request/1";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub schema: String,
    pub terrain: String,
    pub epsg: u32,
    pub crs_identity: CrsIdentity,
    pub terrain_transform: [f64; 6],
    pub window: [usize; 4],
    pub geometry_file: String,
    #[serde(default)]
    pub aoi_file: Option<String>,
    pub mesh_files: Vec<String>,
    pub owner_cells: Vec<[usize; 2]>,
    pub profiles: Vec<Profile>,
    pub threads: usize,
    pub max_working_bytes: u64,
    #[serde(default)]
    pub stream_outputs: bool,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    pub id: String,
    pub values_files: Vec<String>,
}

#[derive(Deserialize)]
pub struct Geometry {
    pub cells: Vec<InputCell>,
    pub faces: Vec<InputFace>,
    pub vertices: Vec<InputVertex>,
}
#[derive(Deserialize)]
pub struct InputCell {
    pub point: [f64; 2],
    pub minimum_elevation: f32,
    #[serde(rename = "virtual")]
    pub virtual_cell: bool,
    pub faces: Vec<usize>,
}
#[derive(Deserialize)]
pub struct InputFace {
    pub cells: [usize; 2],
    pub vertices: [usize; 2],
    pub minimum_elevation: f32,
    pub perimeter: bool,
    pub polyline: Vec<[f64; 2]>,
}
#[derive(Deserialize)]
pub struct InputVertex {
    pub point: [f64; 2],
    pub faces: Vec<usize>,
    pub ccw: Vec<usize>,
    pub cw: Vec<usize>,
}

impl Geometry {
    pub fn prepare(&self) -> Result<(Mesh, Vec<Option<sloping::CellStencil>>), MapError> {
        if self
            .cells
            .iter()
            .any(|c| c.virtual_cell != (c.faces.len() == 1))
        {
            return Err(MapError::Invalid(
                "sloping virtual-cell flag contradicts topology".into(),
            ));
        }
        let faces =
            self.faces
                .iter()
                .map(|f| {
                    let a = self.cells.get(f.cells[0]).ok_or_else(|| {
                        MapError::Invalid("sloping cell address out of range".into())
                    })?;
                    let b = self.cells.get(f.cells[1]).ok_or_else(|| {
                        MapError::Invalid("sloping cell address out of range".into())
                    })?;
                    Ok(Face {
                        cells: f.cells,
                        vertices: f.vertices,
                        minimum: f.minimum_elevation,
                        perimeter: f.perimeter,
                        application: sloping::face_application(&f.polyline, [a.point, b.point])?,
                    })
                })
                .collect::<Result<Vec<_>, MapError>>()?;
        let mesh = Mesh {
            cells: self
                .cells
                .iter()
                .map(|c| Cell {
                    minimum: c.minimum_elevation,
                    virtual_cell: c.virtual_cell,
                })
                .collect(),
            faces,
            corners: self
                .vertices
                .iter()
                .map(|v| Corner {
                    point: v.point,
                    faces: v.faces.clone(),
                    ccw: v.ccw.clone(),
                    cw: v.cw.clone(),
                })
                .collect(),
        };
        let cell_faces = self
            .cells
            .iter()
            .map(|c| c.faces.clone())
            .collect::<Vec<_>>();
        let stencils = sloping::prepare_stencils(&mesh, &cell_faces)?;
        Ok((mesh, stencils))
    }
}

pub fn method_record() -> Value {
    json!({"method_id":"rasmapper-plain-sloping/1", "backend":"rust", "experimental":true,
        "native_version_qualified":"7.0.1", "stream_outputs":true, "native_ownership":true,
        "options":{"CellRenderMode":"Sloping","CellStencilMode":"JustFacepoints",
            "FacepointAdjustmentMode":"None","ShallowBehaviorMode":"None",
            "UseDepthWeightedFaces":false,"FaceWSMode":"Adjusted"},
        "native_plot_tolerance":0.001_f32,"extra_depth_cutoff":null,
        "scope":"2D cells; plain cell-corner sloping; no 1D, slopingPretty or additional rendering options",
        "reuse":"geometry, terrio ownership and terrain prepared once; bounded Rayon pixel and reconstruction workers"})
}

fn values(path: &Path, count: usize) -> Result<Vec<f32>, MapError> {
    let expected = count
        .checked_mul(4)
        .ok_or_else(|| MapError::Budget("sloping values size overflow".into()))?;
    if fs::metadata(path)?.len() != expected as u64 {
        return Err(MapError::Invalid("sloping profile length mismatch".into()));
    }
    let raw = fs::read(path)?;
    if raw.len() != expected {
        return Err(MapError::Invalid("sloping profile changed size".into()));
    }
    let values: Vec<_> = raw
        .as_chunks::<4>()
        .0
        .iter()
        .map(|v| f32::from_le_bytes(*v))
        .collect();
    if values.iter().any(|v| !v.is_finite()) {
        return Err(MapError::Invalid(
            "sloping profiles require finite cell WSE including virtual cells".into(),
        ));
    }
    Ok(values)
}

pub fn run(req: &Request, base: &Path, out: &Path) -> Result<Value, MapError> {
    let started = Instant::now();
    let [col, row, width, height] = req.window;
    let count = width
        .checked_mul(height)
        .filter(|&n| n > 0 && n <= model::MAX_PROFILE_PIXELS as usize)
        .ok_or_else(|| MapError::Budget("sloping window empty or too large".into()))?;
    if req.schema != SCHEMA
        || !(1..=64).contains(&req.threads)
        || req.epsg == 0
        || req.mesh_files.is_empty()
        || req.owner_cells.is_empty()
        || req.owner_cells.len() >= u32::MAX as usize
        || req.profiles.is_empty()
    {
        return Err(MapError::Invalid("invalid sloping request".into()));
    }
    let mut ids = HashSet::new();
    for profile in &req.profiles {
        model::validate_id(&profile.id)?;
        if !ids.insert(model::id_key(&profile.id))
            || profile.values_files.len() != req.mesh_files.len()
        {
            return Err(MapError::Invalid(
                "duplicate sloping profile id or mesh value count mismatch".into(),
            ));
        }
    }
    let geometry_bytes = req
        .mesh_files
        .iter()
        .chain(std::iter::once(&req.geometry_file))
        .chain(req.aoi_file.iter())
        .try_fold(0_u64, |sum, p| {
            sum.checked_add(fs::metadata(model::resolve(base, p))?.len())
                .ok_or_else(|| MapError::Budget("sloping geometry size overflow".into()))
        })?;
    let binary_bytes = req.mesh_files.iter().try_fold(0_u64, |sum, name| {
        sum.checked_add(crate::sloping_binary::input_bytes(&model::resolve(
            base, name,
        ))?)
        .ok_or_else(|| MapError::Budget("sloping binary geometry size overflow".into()))
    })?;
    let geometry_bytes = geometry_bytes
        .checked_add(binary_bytes)
        .ok_or_else(|| MapError::Budget("sloping geometry size overflow".into()))?;
    let cache = 64_u64 << 20;
    // JSON parsing, topology, stencils, one hydraulic profile and IO copies are
    // conservatively admitted, rather than claiming an OS-enforced RSS limit.
    let planned = (count as u64)
        .checked_mul(40)
        .and_then(|v| {
            geometry_bytes
                .checked_mul(16)
                .and_then(|g| v.checked_add(g))
        })
        .and_then(|v| v.checked_add(cache))
        .ok_or_else(|| MapError::Budget("sloping array plan overflow".into()))?;
    if planned > req.max_working_bytes {
        return Err(MapError::Budget("sloping array plan exceeds budget".into()));
    }
    let terrain = NativeTerrain::open(
        model::resolve(base, &req.terrain)
            .to_str()
            .ok_or_else(|| MapError::Invalid("terrain path is not UTF8".into()))?,
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
        || terrain.max_block_bytes() > cache
    {
        return Err(MapError::Unsupported(
            "sloping terrain identity, square grid, block or window mismatch".into(),
        ));
    }
    let admitted = planned
        .checked_add(
            terrain
                .decoder_transient_bytes_per_load()
                .checked_mul(req.threads as u64)
                .ok_or_else(|| MapError::Budget("sloping parallel decoder plan overflow".into()))?,
        )
        .ok_or_else(|| MapError::Budget("sloping decoder plan overflow".into()))?;
    if admitted > req.max_working_bytes {
        return Err(MapError::Budget(
            "sloping decoder plan exceeds budget".into(),
        ));
    }
    fs::create_dir(out)?;
    let mut report = json!({"schema":"ras-commander-sloping-report/1","status":"in_progress", "method":method_record(),
        "threads":req.threads,"window":req.window,"planned_bytes":admitted,"profiles":[]});
    sink::write_json(&out.join("report.json"), &report)?;
    let execution = std::panic::catch_unwind(std::panic::AssertUnwindSafe(
        || -> Result<(), MapError> {
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(req.threads)
                .build()
                .map_err(|e| MapError::Internal(e.to_string()))?;
            let tick = Instant::now();
            let mut meshes = Vec::new();
            let mut stencils = Vec::new();
            for filename in &req.mesh_files {
                let source = crate::sloping_binary::load(&model::resolve(base, filename))?;
                let (mesh, stencil) = source.prepare()?;
                meshes.push(mesh);
                stencils.push(stencil);
            }
            for &[mesh, cell] in &req.owner_cells {
                if mesh >= meshes.len()
                    || cell >= meshes[mesh].cells.len()
                    || meshes[mesh].cells[cell].virtual_cell
                {
                    return Err(MapError::Invalid(
                        "sloping ownership requires physical mesh cells".into(),
                    ));
                }
            }
            report["geometry_prepare_seconds"] = tick.elapsed().as_secs_f64().into();
            let transform = [
                terrain.gt[0] + col as f64 * terrain.gt[1],
                terrain.gt[1],
                0.,
                terrain.gt[3] + row as f64 * terrain.gt[5],
                0.,
                terrain.gt[5],
            ];
            let grid = terrio::ops::rasterize::Grid {
                geo_transform: transform,
                cols: width,
                rows: height,
                crs: Default::default(),
            };
            let tick = Instant::now();
            let cells = crate::ownership::load(
                &model::resolve(base, &req.geometry_file),
                req.owner_cells.len(),
                false,
            )?;
            let mut owner = pool.install(|| crate::ownership::burn(cells, grid.clone()))?;
            if let Some(filename) = &req.aoi_file {
                let aoi = crate::ownership::load(&model::resolve(base, filename), 1, true)?;
                let mask = pool.install(|| crate::ownership::burn(aoi, grid))?;
                pool.install(|| {
                    owner
                        .par_iter_mut()
                        .zip(mask.par_iter())
                        .for_each(|(label, &m)| {
                            if m == 0 {
                                *label = 0;
                            }
                        })
                });
            }
            report["ownership_prepare_seconds"] = tick.elapsed().as_secs_f64().into();
            let tick = Instant::now();
            let mut ground = vec![sloping::NODATA; count];
            let (bw, bh) = terrain.block;
            // Row stripes own disjoint output slices. Decodes run inside the same
            // bounded pool, and the shared single-flight cache handles boundary
            // blocks seen by adjacent stripes. Skip blocks outside ownership/AOI.
            let stripe_pixels = width
                .checked_mul(bh)
                .ok_or_else(|| MapError::Budget("sloping terrain stripe overflow".into()))?;
            pool.install(|| {
                ground
                    .par_chunks_mut(stripe_pixels)
                    .enumerate()
                    .try_for_each(|(stripe, destination)| -> Result<(), MapError> {
                        let first = row + stripe * bh;
                        let last = first + destination.len() / width;
                        for by in first / bh..=(last - 1) / bh {
                            for bx in col / bw..=(col + width - 1) / bw {
                                let win = terrain.block_window(bx, by);
                                let r0 = first.max(win.y);
                                let r1 = last.min(win.y + win.height);
                                let c0 = col.max(win.x);
                                let c1 = (col + width).min(win.x + win.width);
                                if !(r0..r1).any(|r| {
                                    owner
                                        [(r - row) * width + c0 - col..(r - row) * width + c1 - col]
                                        .iter()
                                        .any(|&label| label != 0)
                                }) {
                                    continue;
                                }
                                let block = terrain.get_block(bx, by)?;
                                for r in r0..r1 {
                                    for c in c0..c1 {
                                        if owner[(r - row) * width + c - col] == 0 {
                                            continue;
                                        }
                                        if let Some(value) = terrain
                                            .classify(block[(r - win.y) * win.width + c - win.x])
                                        {
                                            if !value.is_finite() {
                                                return Err(MapError::Terrain(
                                                    "nonfinite sloping terrain".into(),
                                                ));
                                            }
                                            destination[(r - first) * width + c - col] =
                                                value as f32;
                                        }
                                    }
                                }
                            }
                        }
                        Ok(())
                    })
            })?;
            report["terrain_prepare_seconds"] = tick.elapsed().as_secs_f64().into();
            let window = sloping::RasterWindow {
                width,
                height,
                transform,
                owner: &owner,
                terrain: &ground,
                owner_cells: &req.owner_cells,
            };
            for profile in &req.profiles {
                let tick = Instant::now();
                let mut prepared = Vec::new();
                for ((mesh, stencil), filename) in
                    meshes.iter().zip(&stencils).zip(&profile.values_files)
                {
                    prepared.push(sloping::prepare_profile(
                        mesh,
                        stencil,
                        &values(&model::resolve(base, filename), mesh.cells.len())?,
                        0.001,
                        &pool,
                    )?);
                }
                let hydraulic_seconds = tick.elapsed().as_secs_f64();
                let tick = Instant::now();
                let (mut depth, mut wse) =
                    sloping::render_profile(&stencils, &prepared, &window, 0.001, &pool)?;
                let render_seconds = tick.elapsed().as_secs_f64();
                pool.install(|| {
                    depth
                        .par_iter_mut()
                        .zip(wse.par_iter_mut())
                        .for_each(|(d, w)| {
                            if *d == sloping::NODATA {
                                *d = f32::NAN;
                                *w = f32::NAN;
                            }
                        })
                });
                let dir = out.join(&profile.id);
                fs::create_dir(&dir)?;
                if req.stream_outputs {
                    let mut stream =
                        std::io::BufWriter::with_capacity(65536, std::io::stdout().lock());
                    writeln!(
                        stream,
                        "{}",
                        json!({"id":profile.id,"status":"complete","pixels":count})
                    )?;
                    crate::horizontal::write_f32(&mut stream, &depth)?;
                    crate::horizontal::write_f32(&mut stream, &wse)?;
                    stream.flush()?;
                } else {
                    crate::horizontal::write_values(&dir.join("depth.bin"), &depth)?;
                    crate::horizontal::write_values(&dir.join("wse.bin"), &wse)?;
                }
                let unit = json!({"id":profile.id,"status":"complete","hydraulic_seconds":hydraulic_seconds,"render_seconds":render_seconds});
                sink::write_json(&dir.join("unit.json"), &unit)?;
                report["profiles"].as_array_mut().unwrap().push(unit);
                sink::write_json(&out.join("report.json"), &report)?;
            }
            Ok(())
        },
    ));
    match execution {
        Ok(Ok(())) => report["status"] = "complete".into(),
        other => {
            report["status"] = "aborted".into();
            report["error"] = match other {
                Ok(Err(e)) => e.to_string(),
                _ => "sloping internal panic".into(),
            }
            .into();
            for profile in &req.profiles {
                let dir = out.join(&profile.id);
                for filename in [
                    "depth.bin",
                    "wse.bin",
                    "depth.bin.partial",
                    "wse.bin.partial",
                ] {
                    let _ = fs::remove_file(dir.join(filename));
                }
                if dir.is_dir() {
                    sink::write_json(
                        &dir.join("unit.json"),
                        &json!({"id":profile.id,"status":"failed","error":"session aborted"}),
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
