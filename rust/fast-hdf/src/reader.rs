use crate::UnsupportedError;
use hdf5_reader::error::Error;
use hdf5_reader::{ByteOrder, Datatype, Hdf5File, SliceInfo, SliceInfoElem};
use numpy::IntoPyArray;
use pyo3::exceptions::{PyKeyError, PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn classify(e: &Error) -> u8 {
    match e {
        Error::Context { source, .. } => classify(source),
        Error::DatasetNotFound(_) | Error::GroupNotFound(_) => 1,
        Error::Io(_) => 2,
        _ if format!("{e}").starts_with("unsupported ") => 3,
        _ => 0,
    }
}
fn err(e: Error) -> PyErr {
    let message = e.to_string();
    match classify(&e) {
        1 => PyKeyError::new_err(message),
        2 => PyOSError::new_err(message),
        3 => UnsupportedError::new_err(message),
        _ => PyValueError::new_err(message),
    }
}

fn read<'py>(
    py: Python<'py>,
    file: &Hdf5File,
    path: &str,
    selection: Option<&[(u64, u64, u64)]>,
    parallel: bool,
    pool: &rayon::ThreadPool,
) -> PyResult<Bound<'py, PyAny>> {
    let ds = file.dataset(path).map_err(err)?;
    let selection = selection
        .map(|sel| -> PyResult<SliceInfo> {
            if sel.len() != ds.ndim() {
                return Err(PyValueError::new_err(
                    "selection must have one slice per dimension",
                ));
            }
            let mut selections = Vec::with_capacity(sel.len());
            for (i, &(start, end, step)) in sel.iter().enumerate() {
                if step == 0 || start > end || end > ds.shape()[i] {
                    return Err(PyValueError::new_err(format!(
                        "invalid slice on dimension {i}"
                    )));
                }
                selections.push(SliceInfoElem::Slice { start, end, step });
            }
            Ok(SliceInfo { selections })
        })
        .transpose()?;
    macro_rules! read_as {
        ($t:ty) => {{
            let array = py
                .detach(|| {
                    pool.install(|| match (&selection, parallel) {
                        (Some(s), true) => ds.read_slice_parallel::<$t>(s),
                        (Some(s), false) => ds.read_slice::<$t>(s),
                        (None, true) => ds.read_array_parallel::<$t>(),
                        (None, false) => ds.read_array::<$t>(),
                    })
                })
                .map_err(err)?;
            Ok(array.into_pyarray(py).into_any())
        }};
    }
    // Native arrays must not silently change byte order; the adapter uses h5py
    // for non-native-endian datasets until a preserving binding is supplied.
    match ds.dtype() {
        Datatype::FixedPoint {
            size,
            signed,
            byte_order,
        } => {
            if *size > 1 && !native_order(byte_order) {
                return Err(UnsupportedError::new_err("non-native byte order"));
            }
            match (*size, *signed) {
                (1, true) => read_as!(i8),
                (2, true) => read_as!(i16),
                (4, true) => read_as!(i32),
                (8, true) => read_as!(i64),
                (1, false) => read_as!(u8),
                (2, false) => read_as!(u16),
                (4, false) => read_as!(u32),
                (8, false) => read_as!(u64),
                _ => Err(UnsupportedError::new_err("unsupported integer width")),
            }
        }
        Datatype::FloatingPoint { size, byte_order } => {
            if !native_order(byte_order) {
                return Err(UnsupportedError::new_err("non-native byte order"));
            }
            match *size {
                4 => read_as!(f32),
                8 => read_as!(f64),
                _ => Err(UnsupportedError::new_err("unsupported float width")),
            }
        }
        _ => Err(UnsupportedError::new_err(format!(
            "unsupported numeric dtype: {:?}",
            ds.dtype()
        ))),
    }
}
fn native_order(order: &ByteOrder) -> bool {
    matches!(
        (cfg!(target_endian = "little"), order),
        (true, ByteOrder::LittleEndian) | (false, ByteOrder::BigEndian)
    )
}

#[pyfunction]
#[pyo3(signature=(path,dataset_path,selection=None,threads=None,parallel=true))]
pub fn read_numeric<'py>(
    py: Python<'py>,
    path: &str,
    dataset_path: &str,
    selection: Option<Vec<(u64, u64, u64)>>,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let pool = crate::pool(threads)?;
    let file = py.detach(|| Hdf5File::open(path)).map_err(err)?;
    read(
        py,
        &file,
        dataset_path,
        selection.as_deref(),
        parallel,
        &pool,
    )
}

#[pyfunction]
#[pyo3(signature=(path,dataset_paths,threads=None,parallel=true))]
pub fn read_numeric_batch<'py>(
    py: Python<'py>,
    path: &str,
    dataset_paths: Vec<String>,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let pool = crate::pool(threads)?;
    let file = py.detach(|| Hdf5File::open(path)).map_err(err)?;
    let output = PyDict::new(py);
    for path in dataset_paths {
        output.set_item(&path, read(py, &file, &path, None, parallel, &pool)?)?;
    }
    Ok(output)
}
