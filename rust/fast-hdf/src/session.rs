//! Explicit read-only session. Closing waits for in-flight reads and drops mappings.
use crate::domain::identity;
use crate::fim::{inventory, selection, slice};
use numpy::IntoPyArray;
use pyo3::{
    exceptions::{PyRuntimeError, PyValueError},
    prelude::*,
    types::PyDict,
};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, Slice};
use std::{path::PathBuf, sync::Mutex};
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
#[pyclass]
pub(crate) struct HdfSession {
    inner: Mutex<Option<ReadOnlyHdfSession>>,
}
impl HdfSession {
    fn with<T: Send>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&ReadOnlyHdfSession) -> ras_commander_rust::Result<T> + Send,
    ) -> PyResult<T> {
        py.detach(|| {
            let guard = self
                .inner
                .lock()
                .map_err(|_| PyRuntimeError::new_err("session lock poisoned"))?;
            let s = guard
                .as_ref()
                .ok_or_else(|| PyValueError::new_err("HDF session is closed"))?;
            f(s).map_err(crate::reader::err)
        })
    }
}
#[pymethods]
impl HdfSession {
    #[new]
    #[pyo3(signature=(path,threads=None,parallel=true,*,cache_bytes=None,cache_slots=None))]
    fn new(
        py: Python<'_>,
        path: PathBuf,
        threads: Option<usize>,
        parallel: bool,
        cache_bytes: Option<usize>,
        cache_slots: Option<usize>,
    ) -> PyResult<Self> {
        let count = crate::reader::threads(threads)?;
        let s = py
            .detach(|| {
                ReadOnlyHdfSession::with_cache_options(
                    path,
                    count,
                    parallel,
                    cache_bytes.unwrap_or(ras_commander_rust::hdf::DEFAULT_CHUNK_CACHE_BYTES),
                    cache_slots.unwrap_or(ras_commander_rust::hdf::DEFAULT_CHUNK_CACHE_SLOTS),
                )
            })
            .map_err(crate::reader::err)?;
        Ok(Self {
            inner: Mutex::new(Some(s)),
        })
    }
    fn cache_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let c = self.with(py, |s| Ok(s.chunk_cache_stats()))?;
        Ok(
            dict!(py,"hits"=>c.hits,"misses"=>c.misses,"inserts"=>c.inserts,"evictions"=>c.evictions,"retained_bytes"=>c.retained_bytes,"entries"=>c.entries,"max_bytes"=>c.max_bytes,"max_slots"=>c.max_slots),
        )
    }
    #[pyo3(signature=(area,variable,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    fn read_mesh_summary_values<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        variable: &str,
        elements: Option<numpy::PyReadonlyArray1<'_, u64>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyAny>> {
        let elements = elements
            .map(|a| a.as_slice().map(|s| s.to_vec()))
            .transpose()?;
        let a = self.with(py, |s| {
            s.read_mesh_summary_values(
                area,
                variable,
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        crate::reader::array(py, a)
    }
    #[pyo3(signature=(area,rows,names=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    fn read_mesh_boundary_batch<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        rows: (u64, u64, u64),
        names: Option<Vec<String>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let names = names
            .as_ref()
            .map(|n| n.iter().map(String::as_str).collect::<Vec<_>>());
        let result = self.with(py, |s| {
            s.read_mesh_boundary_batch(
                area,
                names.as_deref(),
                slice(rows),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        let d = PyDict::new(py);
        for (name, r) in result {
            d.set_item(name, selection(py, r)?)?;
        }
        Ok(d)
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        py.detach(|| {
            self.inner
                .lock()
                .map_err(|_| PyRuntimeError::new_err("session lock poisoned"))?
                .take();
            Ok(())
        })
    }
    #[getter]
    fn closed(&self) -> PyResult<bool> {
        Ok(self
            .inner
            .lock()
            .map_err(|_| PyRuntimeError::new_err("session lock poisoned"))?
            .is_none())
    }
    fn __enter__(slf: PyRef<'_, Self>) -> PyResult<PyRef<'_, Self>> {
        if slf.closed()? {
            return Err(PyValueError::new_err("HDF session is closed"));
        }
        Ok(slf)
    }
    fn __exit__(
        &self,
        py: Python<'_>,
        _ty: &Bound<'_, PyAny>,
        _value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.close(py)
    }
    #[pyo3(signature=(dataset_path,selection=None))]
    fn read_numeric<'py>(
        &self,
        py: Python<'py>,
        dataset_path: &str,
        selection: Option<Vec<(u64, u64, u64)>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let sel = selection.map(|s| {
            s.into_iter()
                .map(|(a, b, c)| Slice::new(a, b, c))
                .collect::<Vec<_>>()
        });
        let a = self.with(py, |s| s.read_numeric(dataset_path, sel.as_deref()))?;
        crate::reader::array(py, a)
    }
    fn read_numeric_batch<'py>(
        &self,
        py: Python<'py>,
        dataset_paths: Vec<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let names = dataset_paths.iter().map(String::as_str).collect::<Vec<_>>();
        let arrays = self.with(py, |s| s.read_numeric_batch(&names))?;
        let d = PyDict::new(py);
        for (n, a) in arrays {
            d.set_item(n, crate::reader::array(py, a)?)?;
        }
        Ok(d)
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_summary_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let i = self.with(py, |session| {
            session.mesh_summary_inventory(area, max_bytes)
        })?;
        inventory(py, i)
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_series_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let i = self.with(py, |session| session.mesh_series_inventory(area, max_bytes))?;
        inventory(py, i)
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_boundary_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let i = self.with(py, |session| {
            session.mesh_boundary_inventory(area, max_bytes)
        })?;
        inventory(py, i)
    }
    #[pyo3(signature=(area,variable,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    fn read_mesh_summary<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        variable: &str,
        elements: Option<numpy::PyReadonlyArray1<'_, u64>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let elements = elements
            .map(|a| a.as_slice().map(|s| s.to_vec()))
            .transpose()?;
        let r = self.with(py, |session| {
            session.read_mesh_summary(
                area,
                variable,
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        selection(py, r)
    }
    #[pyo3(signature=(area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    #[allow(clippy::too_many_arguments)]
    fn read_mesh_series<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        variable: &str,
        rows: (u64, u64, u64),
        elements: Option<numpy::PyReadonlyArray1<'_, u64>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let elements = elements
            .map(|a| a.as_slice().map(|s| s.to_vec()))
            .transpose()?;
        let r = self.with(py, |session| {
            session.read_mesh_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        selection(py, r)
    }
    #[pyo3(signature=(area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    #[allow(clippy::too_many_arguments)]
    fn read_mesh_boundary_series<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        variable: &str,
        rows: (u64, u64, u64),
        elements: Option<numpy::PyReadonlyArray1<'_, u64>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let elements = elements
            .map(|a| a.as_slice().map(|s| s.to_vec()))
            .transpose()?;
        let r = self.with(py, |session| {
            session.read_mesh_boundary_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        selection(py, r)
    }
    #[pyo3(signature=(area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
    #[allow(clippy::too_many_arguments)]
    fn reduce_mesh_series<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        variable: &str,
        rows: (u64, u64, u64),
        elements: Option<numpy::PyReadonlyArray1<'_, u64>>,
        metadata_max_bytes: usize,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        let elements = elements
            .map(|a| a.as_slice().map(|s| s.to_vec()))
            .transpose()?;
        let r = self.with(py, |session| {
            session.reduce_mesh_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })?;
        Ok(
            dict!(py,"identity"=>identity(py,&r.id)?,"elements"=>r.elements.into_pyarray(py),"values"=>crate::reader::array(py,r.values)?,"time_indices"=>r.time_indices.into_pyarray(py)),
        )
    }
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HdfSession>()?;
    Ok(())
}
