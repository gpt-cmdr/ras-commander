//! Compare Rust reconstruction with a private, reflected native component receipt.
//! Run with: cargo run --release --example sloping_components -- receipt.json 4
//! This checks component equality, not complete raster qualification.

use ras2fim_stages_r2::sloping::{
    Cell, Corner, Face, Mesh, PolygonStencil, WeightScratch, paint_corner_values,
};
use serde::Deserialize;
use std::{error::Error, fs::File, io::BufReader, time::Instant};

#[derive(Deserialize)]
struct Receipt {
    cells: Vec<CellRecord>,
    faces: Vec<FaceRecord>,
    vertices: Vec<VertexRecord>,
    min_ws_plot_tolerance: f32,
    #[serde(default)]
    pixel_samples: Vec<PixelSample>,
}
#[derive(Deserialize)]
struct CellRecord {
    minimum_elevation: f32,
    wse: f32,
    #[serde(rename = "virtual")]
    virtual_cell: bool,
    faces: Vec<usize>,
    corner_values: Vec<f32>,
}
#[derive(Deserialize)]
struct FaceRecord {
    cells: [usize; 2],
    vertices: [usize; 2],
    minimum_elevation: f32,
    perimeter: bool,
    application: [f64; 2],
    values: [f32; 2],
    connection: String,
    prev_a: usize,
    next_a: usize,
}
#[derive(Deserialize)]
struct VertexRecord {
    point: [f64; 2],
    faces: Vec<usize>,
    ccw: Vec<usize>,
    cw: Vec<usize>,
    values: Vec<f32>,
}
#[derive(Deserialize)]
struct PixelSample {
    cell: usize,
    point: [f64; 2],
    weights: Vec<f32>,
    wse: f32,
}

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    let path = args
        .get(1)
        .ok_or("Expected a native component JSON receipt")?;
    let threads: usize = args.get(2).map_or(Ok(1), |v| v.parse())?;
    if !(1..=64).contains(&threads) {
        return Err("threads must be 1..64".into());
    }
    let input: Receipt = serde_json::from_reader(BufReader::new(File::open(path)?))?;
    let mesh = Mesh {
        cells: input
            .cells
            .iter()
            .map(|c| Cell {
                minimum: c.minimum_elevation,
                virtual_cell: c.virtual_cell,
            })
            .collect(),
        faces: input
            .faces
            .iter()
            .map(|f| Face {
                cells: f.cells,
                vertices: f.vertices,
                minimum: f.minimum_elevation,
                perimeter: f.perimeter,
                application: f.application,
            })
            .collect(),
        corners: input
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
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build()?;
    let values: Vec<_> = input.cells.iter().map(|c| c.wse).collect();
    let started = Instant::now();
    let output = mesh.reconstruct(&values, input.min_ws_plot_tolerance, &pool)?;
    let seconds = started.elapsed().as_secs_f64();
    let mut face_mismatches = 0;
    let mut connection_mismatches = 0;
    let mut corner_mismatches = 0;
    let mut local_mismatches = 0;
    let mut weight_mismatches = 0;
    let mut paint_mismatches = 0;
    let mut first = Vec::new();
    for (i, (actual, expected)) in output.faces.iter().zip(&input.faces).enumerate() {
        for side in 0..2 {
            if actual.values[side].to_bits() != expected.values[side].to_bits() {
                face_mismatches += 1;
                if first.len() < 10 {
                    first.push(format!(
                        "face {i} side {side}: {} != {}",
                        actual.values[side], expected.values[side]
                    ));
                }
            }
        }
        if format!("{:?}", actual.connection) != expected.connection {
            connection_mismatches += 1;
        }
    }
    for (i, (actual, expected)) in output.corners.iter().zip(&input.vertices).enumerate() {
        if actual.len() != expected.values.len() {
            return Err("native corner dimension mismatch".into());
        }
        for (j, (&a, &b)) in actual.iter().zip(&expected.values).enumerate() {
            if a.to_bits() != b.to_bits() {
                corner_mismatches += 1;
                if first.len() < 10 {
                    first.push(format!("corner {i} slot {j}: {a} != {b}"));
                }
            }
        }
    }
    for (i, cell) in input.cells.iter().enumerate() {
        for (slot, &face_id) in cell.faces.iter().enumerate() {
            let face = &input.faces[face_id];
            let vertex = if face.cells[0] == i {
                face.prev_a
            } else {
                face.next_a
            };
            let incident = input.vertices[vertex]
                .faces
                .iter()
                .position(|&f| f == face_id)
                .ok_or("local face not incident to vertex")?;
            if output.corners[vertex][incident].to_bits() != cell.corner_values[slot].to_bits() {
                local_mismatches += 1;
            }
        }
    }
    for sample in &input.pixel_samples {
        let cell = &input.cells[sample.cell];
        let vertices: Vec<_> = cell
            .faces
            .iter()
            .map(|&f| {
                let face = &input.faces[f];
                if face.cells[0] == sample.cell {
                    face.prev_a
                } else {
                    face.next_a
                }
            })
            .collect();
        let points = vertices.iter().map(|&v| input.vertices[v].point).collect();
        let stencil = PolygonStencil::new(points)?;
        let mut scratch = WeightScratch::new(vertices.len());
        let weights = stencil.weights(sample.point, &mut scratch)?;
        for (&a, &b) in weights.iter().zip(&sample.weights) {
            if a.to_bits() != b.to_bits() {
                weight_mismatches += 1;
            }
        }
        let local: Vec<_> = vertices
            .iter()
            .zip(&cell.faces)
            .map(|(&vertex, &face)| {
                let incident = input.vertices[vertex]
                    .faces
                    .iter()
                    .position(|&f| f == face)
                    .unwrap();
                output.corners[vertex][incident]
            })
            .collect();
        let value = paint_corner_values(weights, &local)?;
        if value.to_bits() != sample.wse.to_bits() {
            paint_mismatches += 1;
            if first.len() < 10 {
                first.push(format!(
                    "pixel cell {}: {value} != {}",
                    sample.cell, sample.wse
                ));
            }
        }
    }
    println!(
        "{}",
        serde_json::json!({
            "threads": threads, "cells": input.cells.len(), "faces": input.faces.len(),
            "corners": input.vertices.len(), "seconds": seconds,
            "face_value_mismatches": face_mismatches, "connection_mismatches": connection_mismatches,
            "corner_value_mismatches": corner_mismatches, "cell_corner_mismatches": local_mismatches,
            "pixel_samples": input.pixel_samples.len(), "weight_mismatches": weight_mismatches,
            "paint_mismatches": paint_mismatches,
            "first_mismatches": first,
            "scope": "native Max-profile face and corner reconstruction, not raster qualification",
        })
    );
    if face_mismatches
        + connection_mismatches
        + corner_mismatches
        + local_mismatches
        + weight_mismatches
        + paint_mismatches
        != 0
    {
        return Err("sloping component parity failed".into());
    }
    Ok(())
}
