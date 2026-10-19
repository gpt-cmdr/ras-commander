//! GIL/NumPy conversion only; engine owns bounded temporal reads and reductions.
use crate::reader::{err, threads as thread_count};
use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use ras_commander_rust::{hdf::ReadOnlyHdfSession, results::ReductionRequest};
use std::time::Instant;
/// Reduce a 2-D `(time, element)` dataset in bounded row blocks.
///
/// See the module documentation for the missing-value, offset, tie,
/// threshold and memory semantics. Returns arrays, the read plan
/// (`block_rows`, `blocks`, `block_bytes`, `chunk_shape`,
/// `storage_chunk_bytes`, `chunk_cache_bytes`) and per-stage timings.
#[pyfunction]
#[pyo3(signature=(path, dataset_path, offset=None, threshold=None,
                  max_block_bytes=16 << 20, threads=None, parallel=true))]
#[allow(clippy::too_many_arguments)]
pub fn temporal_reduce<'py>(
    py: Python<'py>,
    path: std::path::PathBuf,
    dataset_path: &str,
    offset: Option<PyReadonlyArray1<'py, f32>>,
    threshold: Option<f32>,
    max_block_bytes: u64,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyDict>> {
    if max_block_bytes == 0 {
        return Err(PyValueError::new_err("max_block_bytes must be positive"));
    }
    let threads = thread_count(threads)?;
    let offset = offset.map(|o| o.as_array().to_vec());
    let opened = Instant::now();
    let session = py
        .detach(|| ReadOnlyHdfSession::with_options(&path, threads, parallel))
        .map_err(err)?;
    let cap = py
        .detach(|| session.numeric_capability(dataset_path))
        .map_err(err)?;
    let setup_seconds = opened.elapsed().as_secs_f64();
    let started = Instant::now();
    let output = py
        .detach(|| {
            session.reduce_temporal(
                dataset_path,
                ReductionRequest::new()
                    .with_offset(offset)
                    .with_threshold(threshold)
                    .with_max_block_bytes(max_block_bytes)
                    .with_parallel(parallel),
            )
        })
        .map_err(err)?;
    let engine_seconds = started.elapsed().as_secs_f64();
    let (Some(&times), Some(&elements)) = (cap.shape.first(), cap.shape.get(1)) else {
        return Err(err(ras_commander_rust::Error::new(
            ras_commander_rust::ErrorKind::Corrupt,
            "reduction capability is missing time/element dimensions",
        )));
    };
    let n = elements;
    let item = output.stored_item_bytes;
    let row_bytes = elements.saturating_mul(item);
    let step = output.block_rows;
    let blocks = output.blocks;
    let storage_chunk_bytes = output.storage_chunk_bytes;
    let cache_bytes = output.chunk_cache_bytes;
    let chunk = cap
        .chunks
        .map(|c| c.into_iter().map(u64::from).collect::<Vec<_>>());
    let reduction = output.values;
    // The fixed engine API reports a combined operation, never an invented split.
    let read_seconds = f64::NAN;
    let reduce_seconds = f64::NAN;
    let result = PyDict::new(py);
    result.set_item("maximum", reduction.maximum.into_pyarray(py))?;
    result.set_item("peak_index", reduction.peak_index.into_pyarray(py))?;
    result.set_item("finite_count", reduction.finite_count.into_pyarray(py))?;
    result.set_item(
        "exceed_count",
        reduction.exceed_count.map(|v| v.into_pyarray(py)),
    )?;
    result.set_item(
        "first_exceed_index",
        reduction.first_exceed_index.map(|v| v.into_pyarray(py)),
    )?;
    result.set_item("rows", reduction.rows)?;
    result.set_item("elements", elements)?;
    result.set_item(
        "stored_dtype",
        if item == 4 { "float32" } else { "float64" },
    )?;
    result.set_item("block_rows", step)?;
    result.set_item(
        "block_bytes",
        if times == 0 || n == 0 {
            0
        } else {
            step.min(times).saturating_mul(row_bytes)
        },
    )?;
    result.set_item("max_block_bytes", max_block_bytes)?;
    result.set_item("chunk_shape", chunk)?;
    result.set_item("storage_chunk_bytes", storage_chunk_bytes)?;
    result.set_item("chunk_cache_bytes", cache_bytes)?;
    result.set_item("blocks", blocks)?;
    result.set_item("setup_seconds", setup_seconds)?;
    result.set_item("read_seconds", read_seconds)?;
    result.set_item("reduce_seconds", reduce_seconds)?;
    result.set_item("engine_seconds", engine_seconds)?;
    result.set_item(
        "timing_scope",
        "engine read+reduce combined; split unavailable",
    )?;
    Ok(result)
}
