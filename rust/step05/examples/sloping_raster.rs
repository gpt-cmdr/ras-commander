//! Development raster differential runner over independently captured native geometry.
//! Native expected face/corner/pixel values are not read or used for rendering.
//! Geometry capture remains an oracle dependency; this is not the production HDF adapter.

use ras2fim_stages_r2::sloping::{self, Cell, Corner, Face, Mesh, RasterWindow};
use serde::Deserialize;
use std::{
    error::Error,
    fs::{self, File},
    io::{BufReader, BufWriter, Read, Write},
    path::Path,
    time::Instant,
};

#[derive(Deserialize)]
struct Request {
    width: usize,
    height: usize,
    transform: [f64; 6],
    owner_file: String,
    terrain_file: String,
    mesh_files: Vec<String>,
    owner_cells: Vec<[usize; 2]>,
    threads: usize,
}
#[derive(Deserialize)]
struct MeshInput {
    cells: Vec<InputCell>,
    faces: Vec<InputFace>,
    vertices: Vec<InputVertex>,
    min_ws_plot_tolerance: f32,
}
#[derive(Deserialize)]
struct InputCell {
    point: [f64; 2],
    minimum_elevation: f32,
    wse: f32,
    #[serde(rename = "virtual")]
    virtual_cell: bool,
    faces: Vec<usize>,
}
#[derive(Deserialize)]
struct InputFace {
    cells: [usize; 2],
    vertices: [usize; 2],
    minimum_elevation: f32,
    perimeter: bool,
    application: Option<[f64; 2]>,
    #[serde(default)]
    polyline: Vec<[f64; 2]>,
}
#[derive(Deserialize)]
struct InputVertex {
    point: [f64; 2],
    faces: Vec<usize>,
    ccw: Vec<usize>,
    cw: Vec<usize>,
}

fn words(path: &Path, count: usize) -> Result<Vec<[u8; 4]>, Box<dyn Error>> {
    let expected = count.checked_mul(4).ok_or("raster byte count overflow")?;
    if fs::metadata(path)?.len() != expected as u64 {
        return Err("raster input length mismatch".into());
    }
    let mut raw = vec![0; expected];
    BufReader::new(File::open(path)?).read_exact(&mut raw)?;
    Ok(raw.as_chunks::<4>().0.to_vec())
}

fn write(path: &Path, values: &[f32]) -> Result<(), Box<dyn Error>> {
    let mut writer = BufWriter::with_capacity(1 << 20, File::create(path)?);
    for value in values {
        writer.write_all(&value.to_le_bytes())?;
    }
    writer.flush()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    let path = Path::new(
        args.get(1)
            .ok_or("Expected request.json and a new output directory")?,
    );
    let out = Path::new(args.get(2).ok_or("Expected a new output directory")?);
    if out.exists() {
        return Err("output directory already exists".into());
    }
    let request: Request = serde_json::from_reader(BufReader::new(File::open(path)?))?;
    if !(1..=64).contains(&request.threads) {
        return Err("threads must be 1..64".into());
    }
    let count = request
        .width
        .checked_mul(request.height)
        .ok_or("raster dimensions overflow")?;
    // This diagnostic is deliberately bounded; production admission belongs to the engine adapter.
    if count == 0 || count > 40_000_000 {
        return Err("diagnostic raster must contain 1..40 million pixels".into());
    }
    let base = path.parent().ok_or("request has no parent")?;
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(request.threads)
        .build()?;
    let mut stencils = Vec::new();
    let mut profiles = Vec::new();
    let mut tolerance = None;
    let mut application_audit = Vec::new();
    let started = Instant::now();
    for filename in &request.mesh_files {
        let source: MeshInput =
            serde_json::from_reader(BufReader::new(File::open(base.join(filename))?))?;
        if tolerance.is_some_and(|v| v != source.min_ws_plot_tolerance) {
            return Err("mesh tolerances differ".into());
        }
        tolerance = Some(source.min_ws_plot_tolerance);
        let faces = source
            .faces
            .iter()
            .map(|v| {
                let application = match v.application {
                    Some(point) => point,
                    None => sloping::face_application(
                        &v.polyline,
                        [
                            source
                                .cells
                                .get(v.cells[0])
                                .ok_or("face cell out of range")?
                                .point,
                            source
                                .cells
                                .get(v.cells[1])
                                .ok_or("face cell out of range")?
                                .point,
                        ],
                    )?,
                };
                Ok(Face {
                    cells: v.cells,
                    vertices: v.vertices,
                    minimum: v.minimum_elevation,
                    perimeter: v.perimeter,
                    application,
                })
            })
            .collect::<Result<Vec<_>, Box<dyn Error>>>()?;
        let mesh = Mesh {
            cells: source
                .cells
                .iter()
                .map(|v| Cell {
                    minimum: v.minimum_elevation,
                    virtual_cell: v.virtual_cell,
                })
                .collect(),
            faces,
            corners: source
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
        application_audit.push(mesh.faces.iter().map(|f| f.application).collect::<Vec<_>>());
        let faces: Vec<_> = source.cells.iter().map(|v| v.faces.clone()).collect();
        let prepared = sloping::prepare_stencils(&mesh, &faces)?;
        let values: Vec<_> = source.cells.iter().map(|v| v.wse).collect();
        profiles.push(sloping::prepare_profile(
            &mesh,
            &prepared,
            &values,
            source.min_ws_plot_tolerance,
            &pool,
        )?);
        stencils.push(prepared);
    }
    let terrain = words(&base.join(&request.terrain_file), count)?
        .into_iter()
        .map(f32::from_le_bytes)
        .collect::<Vec<_>>();
    let owner = words(&base.join(&request.owner_file), count)?
        .into_iter()
        .map(u32::from_le_bytes)
        .collect::<Vec<_>>();
    let prepared_seconds = started.elapsed().as_secs_f64();
    let window = RasterWindow {
        source_transform: request.transform,
        source_tile: [256, 256],
        width: request.width,
        height: request.height,
        transform: request.transform,
        owner: &owner,
        terrain: &terrain,
        owner_cells: &request.owner_cells,
    };
    let started = Instant::now();
    let (depth, wse) = sloping::render_profile(
        &stencils,
        &profiles,
        &window,
        tolerance.ok_or("no meshes")?,
        &pool,
    )?;
    let seconds = started.elapsed().as_secs_f64();
    fs::create_dir(out)?;
    fs::write(
        out.join("application-points.json"),
        serde_json::to_vec(&application_audit)?,
    )?;
    write(&out.join("depth.bin"), &depth)?;
    write(&out.join("wse.bin"), &wse)?;
    let report = serde_json::json!({"status":"complete","method":"experimental native plain-sloping reconstruction",
        "prepared_seconds":prepared_seconds,"render_seconds":seconds,"threads":request.threads,
        "pixels":count,"native_plot_tolerance":tolerance,"extra_depth_cutoff":null,
        "qualification_scope":"independently captured native geometry; supplied ownership and terrain"});
    fs::write(out.join("report.json"), serde_json::to_vec_pretty(&report)?)?;
    println!("{report}");
    Ok(())
}
