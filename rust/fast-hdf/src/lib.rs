mod analysis;
mod mesh;
pub mod ras_text;
mod reader;
mod text_bindings;
mod tile_engine;
mod tiles;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

pyo3::create_exception!(ras_commander_fast_hdf, UnsupportedError, PyValueError);
pyo3::create_exception!(ras_commander_fast_hdf, TopologyError, PyValueError);

pub(crate) fn pool(threads: Option<usize>) -> PyResult<Arc<rayon::ThreadPool>> {
    if threads == Some(0) || threads.is_some_and(|n| n > 1024) {
        return Err(PyValueError::new_err("threads must be between 1 and 1024"));
    }
    static POOLS: OnceLock<Mutex<HashMap<usize, Arc<rayon::ThreadPool>>>> = OnceLock::new();
    // Bound implicit concurrency; caller-level archive workers also consume CPUs.
    let count = threads
        .unwrap_or_else(|| std::thread::available_parallelism().map_or(1, |n| n.get().min(8)));
    let mut cache = POOLS
        .get_or_init(|| Mutex::new(HashMap::new()))
        .lock()
        .map_err(|_| PyValueError::new_err("thread pool cache poisoned"))?;
    if let Some(pool) = cache.get(&count) {
        return Ok(pool.clone());
    }
    let pool = Arc::new(
        rayon::ThreadPoolBuilder::new()
            .num_threads(count)
            .build()
            .map_err(|e| PyValueError::new_err(e.to_string()))?,
    );
    // Bound retained pools even when applications vary worker counts repeatedly.
    if cache.len() >= 8 {
        if let Some(key) = cache.keys().next().copied() {
            cache.remove(&key);
        }
    }
    cache.insert(count, pool.clone());
    Ok(pool)
}

#[cfg(feature = "exports-arrow")]
#[pyfunction]
#[pyo3(signature = (input, output, format, max_batch_rows=65536))]
fn export_ipc_file(
    py: Python<'_>,
    input: std::path::PathBuf,
    output: std::path::PathBuf,
    format: &str,
    max_batch_rows: usize,
) -> PyResult<String> {
    let format = format
        .parse::<ras_export::Format>()
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    py.detach(move || {
        let metrics = ras_export::export_ipc(&input, &output, format, max_batch_rows)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        serde_json::to_string(&metrics).map_err(|e| PyValueError::new_err(e.to_string()))
    })
}

#[cfg(feature = "exports-pmtiles")]
#[pyfunction]
#[pyo3(signature = (input, output, options, threads=None))]
fn export_pmtiles_ipc_file(
    py: Python<'_>,
    input: std::path::PathBuf,
    output: std::path::PathBuf,
    options: &str,
    threads: Option<usize>,
) -> PyResult<String> {
    let options: ras_export::pmtiles_bridge::Options =
        serde_json::from_str(options).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let pool = pool(threads)?;
    py.detach(move || {
        pool.install(|| {
            let metrics = ras_export::pmtiles_bridge::export_ipc(&input, &output, &options)
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
            serde_json::to_string(&metrics).map_err(|e| PyValueError::new_err(e.to_string()))
        })
    })
}

// Validate original Arrow WKB buffers before a reprojection library can
// normalize away unsupported encodings or trailing bytes. Arrays borrow Arrow
// storage; no per-feature Python objects or geometry copies are needed.
#[cfg(feature = "exports-arrow")]
#[pyfunction]
fn validate_export_wkb(
    offsets: numpy::PyReadonlyArray1<'_, i32>,
    data: numpy::PyReadonlyArray1<'_, u8>,
    validity: Option<numpy::PyReadonlyArray1<'_, u8>>,
    array_offset: usize,
    count: usize,
) -> PyResult<()> {
    let offsets = offsets.as_slice()?;
    let data = data.as_slice()?;
    let validity = validity.as_ref().map(|v| v.as_slice()).transpose()?;
    let end = array_offset
        .checked_add(count)
        .ok_or_else(|| PyValueError::new_err("WKB array offset overflow"))?;
    if end >= offsets.len() {
        return Err(PyValueError::new_err("WKB offsets outside buffer"));
    }
    if let Some(bits) = validity {
        if count > 0 && (end - 1) / 8 >= bits.len() {
            return Err(PyValueError::new_err("WKB validity outside buffer"));
        }
    }
    for i in array_offset..end {
        let start = usize::try_from(offsets[i])
            .map_err(|_| PyValueError::new_err("negative WKB offset"))?;
        let stop = usize::try_from(offsets[i + 1])
            .map_err(|_| PyValueError::new_err("negative WKB offset"))?;
        let bytes = data
            .get(start..stop)
            .ok_or_else(|| PyValueError::new_err("WKB offsets outside data"))?;
        if validity.is_none_or(|bits| bits[i / 8] & (1 << (i % 8)) != 0) {
            ras_export::contract::validate_wkb(bytes, false)
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
        }
    }
    Ok(())
}

#[pymodule]
fn ras_commander_fast_hdf(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("API_VERSION", 1)?;
    #[cfg(feature = "exports-arrow")]
    {
        m.add_function(wrap_pyfunction!(export_ipc_file, m)?)?;
        m.add_function(wrap_pyfunction!(validate_export_wkb, m)?)?;
    }
    #[cfg(feature = "exports-pmtiles")]
    m.add_function(wrap_pyfunction!(export_pmtiles_ipc_file, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("UnsupportedError", m.py().get_type::<UnsupportedError>())?;
    m.add("TopologyError", m.py().get_type::<TopologyError>())?;
    m.add_function(wrap_pyfunction!(reader::read_numeric, m)?)?;
    m.add_function(wrap_pyfunction!(reader::read_numeric_batch, m)?)?;
    m.add_function(wrap_pyfunction!(reader::numeric_capability, m)?)?;
    m.add_function(wrap_pyfunction!(mesh::assemble_cells, m)?)?;
    m.add_function(wrap_pyfunction!(analysis::bindings::temporal_reduce, m)?)?;
    m.add_function(wrap_pyfunction!(tiles::write_pmtiles, m)?)?;
    text_bindings::register(m)?;
    Ok(())
}
