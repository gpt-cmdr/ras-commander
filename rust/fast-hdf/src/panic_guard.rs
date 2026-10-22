//! Panic containment at the Python boundary.
//!
//! Every `#[pyfunction]` and `#[pymethods]` body runs inside [`guard`]. A Rust
//! panic (a bug, never a property of the input) becomes an ordinary
//! `Exception` instead of PyO3's `PanicException`, which derives from
//! `BaseException` and so escapes the `except Exception` h5py fallback.
//!
//! When `ras_commander.fast_hdf` is loaded, the error is its
//! `FastHdfPanicError`, a `FastHdfError` subclass, so required-native mode
//! reports it like any other native refusal. Standalone use of the extension
//! gets [`NativePanicError`], a `RuntimeError` subclass.
//!
//! Aborts (stack overflow, allocation failure) cannot be caught here; the
//! engine prevents those on file input by bounding resolution depth and
//! allocations before they happen.
use std::any::Any;
use std::panic::{catch_unwind, AssertUnwindSafe};

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

pyo3::create_exception!(
    ras_commander_fast_hdf,
    NativePanicError,
    PyRuntimeError,
    "A Rust panic inside the native extension, contained at the Python boundary."
);

/// Run `f`, converting a panic into a Python exception.
pub(crate) fn guard<T>(f: impl FnOnce() -> PyResult<T>) -> PyResult<T> {
    match catch_unwind(AssertUnwindSafe(f)) {
        Ok(result) => result,
        Err(payload) => Err(panic_error(payload.as_ref())),
    }
}

/// Run `f` without the GIL, returning a panic as its message. Use it where a
/// lock is held, so the panic is caught before the lock guard unwinds (no
/// poisoning); build the Python error later with [`panic_error_from`].
pub(crate) fn contain<T>(f: impl FnOnce() -> T) -> Result<T, String> {
    catch_unwind(AssertUnwindSafe(f)).map_err(|payload| panic_message(payload.as_ref()))
}

/// The Python error for a panic message captured by [`contain`].
pub(crate) fn panic_error_from(message: String) -> PyErr {
    Python::attach(|py| python_panic_error(py, &message))
        .unwrap_or_else(|| NativePanicError::new_err(message))
}

pub(crate) fn panic_message(payload: &(dyn Any + Send)) -> String {
    let detail = payload
        .downcast_ref::<&str>()
        .map(|s| (*s).to_owned())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "non-string panic payload".to_owned());
    format!("native extension panicked: {detail}")
}

fn panic_error(payload: &(dyn Any + Send)) -> PyErr {
    panic_error_from(panic_message(payload))
}

/// `ras_commander.fast_hdf.FastHdfPanicError(message)` when that module is
/// already imported. It is never imported from here.
fn python_panic_error(py: Python<'_>, message: &str) -> Option<PyErr> {
    let modules = py.import("sys").ok()?.getattr("modules").ok()?;
    let module = modules
        .call_method1("get", ("ras_commander.fast_hdf",))
        .ok()?;
    if module.is_none() {
        return None;
    }
    let class = module.getattr("FastHdfPanicError").ok()?;
    let instance = class.call1((message,)).ok()?;
    instance
        .is_instance_of::<pyo3::exceptions::PyException>()
        .then(|| PyErr::from_value(instance))
}

/// Test hook: panic inside the guard, as an engine bug would.
#[pyfunction]
pub(crate) fn _panic_for_test(message: &str) -> PyResult<()> {
    guard(|| panic!("{message}"))
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("NativePanicError", m.py().get_type::<NativePanicError>())?;
    m.add_function(wrap_pyfunction!(_panic_for_test, m)?)?;
    Ok(())
}
