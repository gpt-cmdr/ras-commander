use super::{block_rows, Accumulator};
use crate::reader::{checked_native, err, Native};
use crate::UnsupportedError;
use hdf5_reader::{Dataset, Hdf5File, SliceInfo, SliceInfoElem};
use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::time::Instant;

/// Storage chunk shape (`None` for contiguous/compact layouts).
fn chunk_shape(ds: &Dataset) -> Option<Vec<u64>> {
    ds.chunks().map(|c| c.into_iter().map(u64::from).collect())
}

fn read_rows(ds: &Dataset, kind: Native, rows: (u64, u64), cols: u64) -> Result<Vec<f32>, PyErr> {
    let selection = SliceInfo {
        selections: vec![
            SliceInfoElem::Slice {
                start: rows.0,
                end: rows.1,
                step: 1,
            },
            SliceInfoElem::Slice {
                start: 0,
                end: cols,
                step: 1,
            },
        ],
    };
    // Each block is decompressed in parallel inside the caller's pool.
    let owned = |array: ndarray::ArrayD<f32>| -> Result<Vec<f32>, PyErr> {
        if array.is_standard_layout() {
            Ok(array.into_raw_vec_and_offset().0)
        } else {
            Ok(array.iter().copied().collect())
        }
    };
    match kind {
        Native::F32 => owned(ds.read_slice_parallel::<f32>(&selection).map_err(err)?),
        // Same IEEE round-to-nearest-even narrowing as NumPy astype(float32).
        Native::F64 => owned(
            ds.read_slice_parallel::<f64>(&selection)
                .map_err(err)?
                .mapv(|v| v as f32),
        ),
        other => Err(UnsupportedError::new_err(format!(
            "temporal reductions support float32/float64 series, not {other:?}"
        ))),
    }
}

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
    path: &str,
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
    let pool = crate::pool(threads)?;
    let offset = offset.map(|o| o.as_array().to_vec());
    let opened = Instant::now();
    let file = py.detach(|| Hdf5File::open(path)).map_err(err)?;
    let ds = file.dataset(dataset_path).map_err(err)?;
    let shape = ds.shape().to_vec();
    if shape.len() != 2 {
        return Err(PyValueError::new_err(format!(
            "temporal reduction needs a 2-D (time, element) dataset; {dataset_path} has shape {shape:?}"
        )));
    }
    let kind = checked_native(&file, &ds)?;
    let item = match kind {
        Native::F32 => 4,
        Native::F64 => 8,
        other => {
            return Err(UnsupportedError::new_err(format!(
                "temporal reductions support float32/float64 series, not {other:?}"
            )))
        }
    };
    let (times, elements) = (shape[0], shape[1]);
    let n =
        usize::try_from(elements).map_err(|_| PyValueError::new_err("element count too large"))?;
    let chunk = chunk_shape(&ds);
    // f64 blocks are read as f64 before narrowing, so budget the stored width.
    let row_bytes = elements.saturating_mul(item);
    let chunk_rows = chunk.as_ref().and_then(|c| c.first().copied()).unwrap_or(1);
    let step = block_rows(chunk_rows, row_bytes, max_block_bytes);
    // Decompressed size of one storage chunk: HDF5 must inflate a whole chunk
    // to read any part of it, independently of the block budget.
    let storage_chunk_bytes = chunk
        .as_ref()
        .map(|c| c.iter().fold(item, |acc, &d| acc.saturating_mul(d)));
    let cache_bytes = ds.chunk_cache_stats().max_bytes;
    let setup_seconds = opened.elapsed().as_secs_f64();
    let (reduction, read_seconds, reduce_seconds, blocks) = py.detach(|| {
        pool.install(|| -> PyResult<_> {
            let mut acc = Accumulator::new(n, offset, threshold).map_err(PyValueError::new_err)?;
            let (mut read_s, mut reduce_s, mut blocks) = (0.0, 0.0, 0u64);
            let mut start = 0;
            while start < times && n > 0 {
                let end = times.min(start.saturating_add(step));
                let t = Instant::now();
                let values = read_rows(&ds, kind, (start, end), elements)?;
                read_s += t.elapsed().as_secs_f64();
                let expected = usize::try_from(end - start)
                    .ok()
                    .and_then(|r| r.checked_mul(n));
                if expected != Some(values.len()) {
                    return Err(PyValueError::new_err(
                        "native block read returned an unexpected size",
                    ));
                }
                let t = Instant::now();
                acc.update(&values, parallel)
                    .map_err(PyValueError::new_err)?;
                reduce_s += t.elapsed().as_secs_f64();
                blocks += 1;
                start = end;
            }
            let mut out = acc.finish();
            // Zero-element series still record their (unread) time length.
            out.rows = times;
            Ok((out, read_s, reduce_s, blocks))
        })
    })?;
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
    Ok(result)
}
