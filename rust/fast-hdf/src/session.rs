//! Explicit read-only session. Closing waits for in-flight reads and drops mappings.
use crate::domain::identity;
use crate::fim::{inventory, selection, slice};
use numpy::IntoPyArray;
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, Slice};
use std::{
    path::PathBuf,
    sync::{Mutex, MutexGuard, PoisonError},
};
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
#[pyclass]
pub(crate) struct HdfSession {
    inner: Mutex<Option<ReadOnlyHdfSession>>,
}
impl HdfSession {
    /// The session slot. Engine calls are panic-contained while the lock is
    /// held, so it is not poisoned in practice; a poisoned lock (a panic
    /// elsewhere) is still recovered, because the session is read-only and
    /// stays consistent, so later reads and `close()` keep working.
    fn slot(&self) -> MutexGuard<'_, Option<ReadOnlyHdfSession>> {
        self.inner.lock().unwrap_or_else(PoisonError::into_inner)
    }
    fn with<T: Send>(
        &self,
        py: Python<'_>,
        f: impl FnOnce(&ReadOnlyHdfSession) -> ras_commander_rust::Result<T> + Send,
    ) -> PyResult<T> {
        let outcome = py.detach(|| {
            let guard = self.slot();
            let s = guard.as_ref()?;
            // Catch a panic before the lock guard unwinds; build the Python
            // error after the lock is released and the GIL is re-acquired.
            Some(crate::panic_guard::contain(|| f(s)))
        });
        match outcome {
            None => Err(PyValueError::new_err("HDF session is closed")),
            Some(Ok(result)) => result.map_err(crate::reader::err),
            Some(Err(message)) => Err(crate::panic_guard::panic_error_from(message)),
        }
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
        crate::panic_guard::guard(|| {
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
        })
    }
    fn cache_stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        crate::panic_guard::guard(|| {
            let c = self.with(py, |s| Ok(s.chunk_cache_stats()))?;
            Ok(
                dict!(py,"hits"=>c.hits,"misses"=>c.misses,"inserts"=>c.inserts,"evictions"=>c.evictions,"retained_bytes"=>c.retained_bytes,"entries"=>c.entries,"max_bytes"=>c.max_bytes,"max_slots"=>c.max_slots),
            )
        })
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
        crate::panic_guard::guard(|| {
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
        })
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
        crate::panic_guard::guard(|| {
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
        })
    }
    /// Test hook: panic inside an engine call while the session lock is held.
    fn _panic_for_test(&self, py: Python<'_>) -> PyResult<()> {
        crate::panic_guard::guard(|| {
            self.with(py, |_| -> ras_commander_rust::Result<()> {
                panic!("injected panic while the session lock is held")
            })
        })
    }
    fn close(&self, py: Python<'_>) -> PyResult<()> {
        crate::panic_guard::guard(|| {
            py.detach(|| {
                self.slot().take();
                Ok(())
            })
        })
    }
    #[getter]
    fn closed(&self) -> PyResult<bool> {
        crate::panic_guard::guard(|| Ok(self.slot().is_none()))
    }
    fn __enter__(slf: PyRef<'_, Self>) -> PyResult<PyRef<'_, Self>> {
        crate::panic_guard::guard(|| {
            if slf.closed()? {
                return Err(PyValueError::new_err("HDF session is closed"));
            }
            Ok(slf)
        })
    }
    fn __exit__(
        &self,
        py: Python<'_>,
        _ty: &Bound<'_, PyAny>,
        _value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        crate::panic_guard::guard(|| self.close(py))
    }
    #[pyo3(signature=(dataset_path,selection=None))]
    fn read_numeric<'py>(
        &self,
        py: Python<'py>,
        dataset_path: &str,
        selection: Option<Vec<(u64, u64, u64)>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        crate::panic_guard::guard(|| {
            let sel = selection.map(|s| {
                s.into_iter()
                    .map(|(a, b, c)| Slice::new(a, b, c))
                    .collect::<Vec<_>>()
            });
            let a = self.with(py, |s| s.read_numeric(dataset_path, sel.as_deref()))?;
            crate::reader::array(py, a)
        })
    }
    fn read_numeric_batch<'py>(
        &self,
        py: Python<'py>,
        dataset_paths: Vec<String>,
    ) -> PyResult<Bound<'py, PyDict>> {
        crate::panic_guard::guard(|| {
            let names = dataset_paths.iter().map(String::as_str).collect::<Vec<_>>();
            let arrays = self.with(py, |s| s.read_numeric_batch(&names))?;
            let d = PyDict::new(py);
            for (n, a) in arrays {
                d.set_item(n, crate::reader::array(py, a)?)?;
            }
            Ok(d)
        })
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_summary_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        crate::panic_guard::guard(|| {
            let i = self.with(py, |session| {
                session.mesh_summary_inventory(area, max_bytes)
            })?;
            inventory(py, i)
        })
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_series_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        crate::panic_guard::guard(|| {
            let i = self.with(py, |session| session.mesh_series_inventory(area, max_bytes))?;
            inventory(py, i)
        })
    }
    #[pyo3(signature=(area,max_bytes=67108864))]
    fn mesh_boundary_inventory<'py>(
        &self,
        py: Python<'py>,
        area: &str,
        max_bytes: usize,
    ) -> PyResult<Bound<'py, PyDict>> {
        crate::panic_guard::guard(|| {
            let i = self.with(py, |session| {
                session.mesh_boundary_inventory(area, max_bytes)
            })?;
            inventory(py, i)
        })
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
        crate::panic_guard::guard(|| {
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
        })
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
        crate::panic_guard::guard(|| {
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
        })
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
        crate::panic_guard::guard(|| {
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
        })
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
        crate::panic_guard::guard(|| {
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
        })
    }
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<HdfSession>()?;
    Ok(())
}
