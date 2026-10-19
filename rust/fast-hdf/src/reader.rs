//! Thin Python conversion layer over the pinned native engine.
use crate::{CorruptDataError, TopologyError, UnsupportedError};
use numpy::IntoPyArray;
use pyo3::exceptions::{PyFileNotFoundError, PyKeyError, PyOSError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use ras_commander_rust::hdf::{
    ByteOrder, NumericArray, NumericKind as Native, NumericValues, ReadOnlyHdfSession, Slice,
};
use ras_commander_rust::{Error, ErrorKind};
const CAPABILITY_SCHEMA_VERSION: u32 = 1;
pub(crate) fn err(e: Error) -> PyErr {
    let message = e.to_string();
    let exception = match e.kind {
        ErrorKind::NotFound => PyKeyError::new_err(message),
        ErrorKind::FileNotFound => PyFileNotFoundError::new_err((
            2,
            message,
            e.path.as_ref().map(|p| p.to_string_lossy().into_owned()),
        )),
        ErrorKind::Io => PyOSError::new_err(message),
        ErrorKind::Unsupported => UnsupportedError::new_err(message),
        ErrorKind::InvalidRequest => PyValueError::new_err(message),
        ErrorKind::Corrupt => CorruptDataError::new_err(message),
        ErrorKind::StructuralTopology | ErrorKind::InvalidGeometry => {
            TopologyError::new_err(message)
        }
        ErrorKind::Internal => PyRuntimeError::new_err(message),
        _ => PyRuntimeError::new_err(message),
    };
    let _annotation_result = Python::attach(|py| {
        let value = exception.value(py);
        value.setattr("engine_kind", format!("{:?}", e.kind))?;
        value.setattr("subject", e.subject)?;
        value.setattr(
            "source_path",
            e.path.map(|p| p.to_string_lossy().into_owned()),
        )?;
        if matches!(
            e.kind,
            ErrorKind::StructuralTopology | ErrorKind::InvalidGeometry
        ) {
            value.setattr(
                "mesh_structure_error",
                e.kind == ErrorKind::StructuralTopology,
            )?;
        }
        Ok::<_, PyErr>(())
    });
    // Annotation failure must never replace the engine failure category.
    exception
}

pub(crate) fn threads(value: Option<usize>) -> PyResult<usize> {
    let count =
        value.unwrap_or_else(|| std::thread::available_parallelism().map_or(1, |n| n.get().min(8)));
    if !(1..=1024).contains(&count) {
        return Err(PyValueError::new_err("threads must be between 1 and 1024"));
    }
    Ok(count)
}
pub(crate) fn array<'py>(py: Python<'py>, output: NumericArray) -> PyResult<Bound<'py, PyAny>> {
    let shape = output
        .shape
        .into_iter()
        .map(|n| usize::try_from(n).map_err(|_| PyValueError::new_err("shape overflow")))
        .collect::<PyResult<Vec<_>>>()?;
    macro_rules! convert {
        ($v:expr) => {{
            let a = ndarray::ArrayD::from_shape_vec(ndarray::IxDyn(&shape), $v)
                .map_err(|e| PyValueError::new_err(e.to_string()))?;
            Ok(a.into_pyarray(py).into_any())
        }};
    }
    match output.values {
        NumericValues::I8(v) => convert!(v),
        NumericValues::I16(v) => convert!(v),
        NumericValues::I32(v) => convert!(v),
        NumericValues::I64(v) => convert!(v),
        NumericValues::U8(v) => convert!(v),
        NumericValues::U16(v) => convert!(v),
        NumericValues::U32(v) => convert!(v),
        NumericValues::U64(v) => convert!(v),
        NumericValues::F32(v) => convert!(v),
        NumericValues::F64(v) => convert!(v),
        _ => Err(crate::UnsupportedError::new_err(
            "future numeric value type",
        )),
    }
}
fn numpy(kind: Native) -> Option<&'static str> {
    let little = cfg!(target_endian = "little");
    Some(match (kind, little) {
        (Native::I8, _) => "|i1",
        (Native::U8, _) => "|u1",
        (Native::I16, true) => "<i2",
        (Native::I32, true) => "<i4",
        (Native::I64, true) => "<i8",
        (Native::U16, true) => "<u2",
        (Native::U32, true) => "<u4",
        (Native::U64, true) => "<u8",
        (Native::F32, true) => "<f4",
        (Native::F64, true) => "<f8",
        (Native::I16, false) => ">i2",
        (Native::I32, false) => ">i4",
        (Native::I64, false) => ">i8",
        (Native::U16, false) => ">u2",
        (Native::U32, false) => ">u4",
        (Native::U64, false) => ">u8",
        (Native::F32, false) => ">f4",
        (Native::F64, false) => ">f8",
        _ => return None,
    })
}

#[pyfunction]
#[pyo3(signature=(path,dataset_path,selection=None,threads=None,parallel=true))]
pub fn read_numeric<'py>(
    py: Python<'py>,
    path: std::path::PathBuf,
    dataset_path: &str,
    selection: Option<Vec<(u64, u64, u64)>>,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let threads = self::threads(threads)?;
    let selection = selection.map(|s| {
        s.into_iter()
            .map(|(start, end, step)| Slice::new(start, end, step))
            .collect::<Vec<_>>()
    });
    let output = py
        .detach(|| {
            ReadOnlyHdfSession::with_options(&path, threads, parallel)?
                .read_numeric(dataset_path, selection.as_deref())
        })
        .map_err(err)?;
    array(py, output)
}
#[pyfunction]
#[pyo3(signature=(path,dataset_paths,threads=None,parallel=true))]
pub fn read_numeric_batch<'py>(
    py: Python<'py>,
    path: std::path::PathBuf,
    dataset_paths: Vec<String>,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let threads = self::threads(threads)?;
    let output = py
        .detach(|| {
            let session = ReadOnlyHdfSession::with_options(&path, threads, parallel)?;
            let paths = dataset_paths.iter().map(String::as_str).collect::<Vec<_>>();
            session.read_numeric_batch(&paths)
        })
        .map_err(err)?;
    let result = PyDict::new(py);
    for (name, output) in output {
        result.set_item(name, array(py, output)?)?;
    }
    Ok(result)
}
#[pyfunction]
pub fn numeric_capability<'py>(
    py: Python<'py>,
    path: std::path::PathBuf,
    dataset_path: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let cap = py
        .detach(|| ReadOnlyHdfSession::open(&path)?.numeric_capability(dataset_path))
        .map_err(err)?;
    let out = PyDict::new(py);
    out.set_item("schema_version", CAPABILITY_SCHEMA_VERSION)?;
    out.set_item(
        "capability",
        crate::domain::capability(py, &cap.capability)?,
    )?;
    out.set_item("dataset", dataset_path)?;
    out.set_item("shape", cap.shape)?;
    out.set_item("max_shape", cap.max_shape)?;
    out.set_item("chunks", cap.chunks)?;
    let (byte_order, signed) = (cap.byte_order, cap.signed);
    out.set_item(
        "byte_order",
        byte_order.map(|o| {
            if matches!(o, ByteOrder::Little) {
                "little"
            } else {
                "big"
            }
        }),
    )?;
    out.set_item("signed", signed)?;
    if let Some(enc) = cap.encoding {
        let class = match enc.class.code() {
            0 => "integer",
            1 => "float",
            2 => "time",
            3 => "string",
            4 => "bitfield",
            5 => "opaque",
            6 => "compound",
            7 => "reference",
            8 => "enum",
            9 => "vlen",
            10 => "array",
            _ => "unknown",
        };
        out.set_item("type_class", class)?;
        out.set_item("datatype_version", enc.version)?;
        out.set_item("class_flags", enc.flags)?;
        out.set_item("element_size", enc.size)?;
        out.set_item("bit_offset", enc.bit_offset)?;
        out.set_item("bit_precision", enc.bit_precision)?;
        if let Some(layout) = enc.float {
            let float = PyDict::new(py);
            float.set_item("sign_location", layout.sign_location)?;
            float.set_item("exponent_location", layout.exponent_location)?;
            float.set_item("exponent_size", layout.exponent_size)?;
            float.set_item("mantissa_location", layout.mantissa_location)?;
            float.set_item("mantissa_size", layout.mantissa_size)?;
            float.set_item("exponent_bias", layout.exponent_bias)?;
            float.set_item("mantissa_normalization", layout.normalization)?;
            float.set_item("vax_order", enc.flags & 0x40 != 0)?;
            out.set_item("float_layout", float)?;
        }
    }
    match cap.kind.and_then(numpy) {
        Some(dtype) => {
            out.set_item("supported", true)?;
            out.set_item("numpy_dtype", dtype)?;
            out.set_item("reason", py.None())?;
        }
        None => {
            out.set_item("supported", false)?;
            out.set_item("numpy_dtype", py.None())?;
            let reason = cap
                .capability
                .reason()
                .unwrap_or("numeric kind has no supported NumPy conversion");
            out.set_item("reason", reason)?;
            if cap.kind.is_some() {
                out.set_item(
                    "capability",
                    crate::domain::capability(
                        py,
                        &ras_commander_rust::Capability::unsupported(
                            ras_commander_rust::UnsupportedCode::NotImplemented,
                            reason.into(),
                        ),
                    )?,
                )?;
            }
        }
    }
    Ok(out)
}
#[cfg(test)]
mod error_mapping_tests {
    use super::*;
    #[test]
    fn every_engine_error_kind_has_a_distinct_policy() {
        pyo3::Python::initialize();
        Python::attach(|py| {
            for kind in [
                ErrorKind::NotFound,
                ErrorKind::FileNotFound,
                ErrorKind::Io,
                ErrorKind::Unsupported,
                ErrorKind::InvalidRequest,
                ErrorKind::Corrupt,
                ErrorKind::StructuralTopology,
                ErrorKind::InvalidGeometry,
                ErrorKind::Internal,
            ] {
                let e = err(Error::new(kind, "test")
                    .with_path("missing.h5")
                    .with_subject("/values"));
                let valid = match kind {
                    ErrorKind::NotFound => e.is_instance_of::<PyKeyError>(py),
                    ErrorKind::FileNotFound => e.is_instance_of::<PyFileNotFoundError>(py),
                    ErrorKind::Io => e.is_instance_of::<PyOSError>(py),
                    ErrorKind::Unsupported => e.is_instance_of::<UnsupportedError>(py),
                    ErrorKind::InvalidRequest => e.is_instance_of::<PyValueError>(py),
                    ErrorKind::Corrupt => e.is_instance_of::<CorruptDataError>(py),
                    ErrorKind::StructuralTopology | ErrorKind::InvalidGeometry => {
                        e.is_instance_of::<TopologyError>(py)
                    }
                    _ => e.is_instance_of::<PyRuntimeError>(py),
                };
                assert!(valid, "{kind:?}");
                assert_eq!(
                    e.value(py)
                        .getattr("engine_kind")
                        .unwrap()
                        .extract::<String>()
                        .unwrap(),
                    format!("{kind:?}")
                );
                if kind == ErrorKind::FileNotFound {
                    assert_eq!(
                        e.value(py)
                            .getattr("filename")
                            .unwrap()
                            .extract::<String>()
                            .unwrap(),
                        "missing.h5"
                    );
                }
                if matches!(
                    kind,
                    ErrorKind::StructuralTopology | ErrorKind::InvalidGeometry
                ) {
                    assert_eq!(
                        e.value(py)
                            .getattr("mesh_structure_error")
                            .unwrap()
                            .extract::<bool>()
                            .unwrap(),
                        kind == ErrorKind::StructuralTopology
                    );
                }
            }
        });
    }
}
