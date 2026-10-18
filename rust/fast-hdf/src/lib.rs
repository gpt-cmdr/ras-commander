mod mesh;
mod reader;
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

#[pymodule]
fn ras_commander_fast_hdf(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("API_VERSION", 1)?;
    #[cfg(feature = "exports-arrow")]
    m.add_function(wrap_pyfunction!(export_ipc_file, m)?)?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("UnsupportedError", m.py().get_type::<UnsupportedError>())?;
    m.add("TopologyError", m.py().get_type::<TopologyError>())?;
    m.add_function(wrap_pyfunction!(reader::read_numeric, m)?)?;
    m.add_function(wrap_pyfunction!(reader::read_numeric_batch, m)?)?;
    m.add_function(wrap_pyfunction!(mesh::assemble_cells, m)?)?;
    m.add_function(wrap_pyfunction!(tiles::write_pmtiles, m)?)?;
    Ok(())
}
