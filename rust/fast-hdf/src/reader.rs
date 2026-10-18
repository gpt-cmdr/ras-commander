use crate::UnsupportedError;
use hdf5_reader::error::Error;
use hdf5_reader::storage::Storage;
use hdf5_reader::{ByteOrder, Dataset, Datatype, Hdf5File, SliceInfo, SliceInfoElem};
use numpy::IntoPyArray;
use pyo3::exceptions::{PyKeyError, PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

/// Version of the dictionary returned by `numeric_capability`.
const CAPABILITY_SCHEMA_VERSION: u32 = 1;

fn classify(e: &Error) -> u8 {
    match e {
        Error::Context { source, .. } => classify(source),
        Error::DatasetNotFound(_) | Error::GroupNotFound(_) => 1,
        Error::Io(_) => 2,
        Error::UnsupportedSuperblockVersion(_)
        | Error::UnsupportedObjectHeaderVersion(_)
        | Error::UnsupportedBTreeVersion(_)
        | Error::UnsupportedSymbolTableNodeVersion(_)
        | Error::UnsupportedLocalHeapVersion(_)
        | Error::UnsupportedGlobalHeapVersion(_)
        | Error::UnsupportedFractalHeapVersion(_)
        | Error::UnsupportedDataspaceVersion(_)
        | Error::UnsupportedDatatypeClass(_)
        | Error::UnsupportedLayoutClass(_)
        | Error::UnsupportedLayoutVersion(_)
        | Error::UnsupportedFilterPipelineVersion(_)
        | Error::UnsupportedFillValueVersion(_)
        | Error::UnsupportedLinkVersion(_)
        | Error::UnsupportedLinkType(_)
        | Error::UnsupportedAttributeVersion(_)
        | Error::UnsupportedBTreeV2RecordType(_)
        | Error::UnsupportedChunkIndexType(_)
        | Error::UnsupportedOffsetSize(_)
        | Error::UnsupportedLengthSize(_)
        | Error::UnsupportedFilter(_) => 3,
        // The pinned parser rejects valid committed-datatype references
        // (shared message v2 type 2); report a limitation, not corruption.
        Error::InvalidData(m) if m == "unknown shared message v2 type: 2" => 3,
        // Unknown/reserved location types are corruption, not an invitation
        // for the adapter's optional-backend fallback to hide damaged input.
        Error::InvalidData(m)
            if m.starts_with("unknown shared message")
                || m.starts_with("unsupported shared message v3 type:") =>
        {
            0
        }
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

/// Element types the native reader decodes bit-exactly into NumPy.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Native {
    I8,
    I16,
    I32,
    I64,
    U8,
    U16,
    U32,
    U64,
    F32,
    F64,
}

impl Native {
    fn numpy(self) -> &'static str {
        let little = cfg!(target_endian = "little");
        match (self, little) {
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
        }
    }
}

/// Raw datatype message fields. The pinned hdf5-reader parses but discards
/// bit offset/precision and the floating-point layout, so they are read here
/// directly from the object header instead of inferring them from `Datatype`.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Encoding {
    class: u8,
    version: u8,
    flags: u32,
    size: u32,
    bit_offset: Option<u16>,
    bit_precision: Option<u16>,
    float: Option<FloatLayout>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct FloatLayout {
    exponent_location: u8,
    exponent_size: u8,
    mantissa_location: u8,
    mantissa_size: u8,
    exponent_bias: u32,
}

const MSG_DATATYPE: u16 = 0x0003;
const MSG_CONTINUATION: u16 = 0x0010;

fn le(bytes: &[u8], at: usize, width: usize) -> Result<u64, String> {
    let field = bytes
        .get(at..at + width)
        .ok_or_else(|| "truncated object header".to_string())?;
    Ok(field
        .iter()
        .rev()
        .fold(0u64, |value, &byte| (value << 8) | u64::from(byte)))
}

fn read_range(storage: &dyn Storage, address: u64, len: u64) -> Result<Vec<u8>, String> {
    let len = usize::try_from(len).map_err(|_| "object header chunk too large".to_string())?;
    if len > 1 << 24 {
        return Err("object header chunk exceeds 16 MiB".into());
    }
    let buffer = storage
        .read_range(address, len)
        .map_err(|e| e.to_string())?;
    Ok(buffer.as_ref().to_vec())
}

/// Message located in an object header: (type, flags, payload).
type Message = (u16, u8, Vec<u8>);

fn header_messages(
    storage: &dyn Storage,
    address: u64,
    offset_size: usize,
    length_size: usize,
) -> Result<Vec<Message>, String> {
    let prefix = read_range(storage, address, 4)?;
    let mut messages = Vec::new();
    let v2 = prefix == b"OHDR";
    let mut creation_order = false;
    if v2 {
        let fixed = read_range(storage, address, 6)?;
        if fixed[4] != 2 {
            return Err(format!("object header version {}", fixed[4]));
        }
        let flags = fixed[5];
        creation_order = flags & 0x04 != 0;
        let width = 1usize << (flags & 0x03);
        let mut start = 6 + if flags & 0x20 != 0 { 16 } else { 0 };
        start += if flags & 0x10 != 0 { 4 } else { 0 };
        let size = le(
            &read_range(storage, address, (start + width) as u64)?,
            start,
            width,
        )?;
        start += width;
        let chunk = read_range(storage, address, start as u64 + size)?;
        v2_messages(&chunk[start..], creation_order, &mut messages)?;
    } else {
        let fixed = read_range(storage, address, 16)?;
        if fixed[0] != 1 {
            return Err(format!("object header version {}", fixed[0]));
        }
        let size = le(&fixed, 8, 4)?;
        let chunk = read_range(storage, address + 16, size)?;
        v1_messages(&chunk, &mut messages)?;
    }
    // Follow continuation messages breadth-first; each block is read once.
    let mut visited = std::collections::HashSet::new();
    let mut scanned = 0;
    while scanned < messages.len() {
        let (kind, _, payload) = &messages[scanned];
        scanned += 1;
        if *kind != MSG_CONTINUATION {
            continue;
        }
        let at = le(payload, 0, offset_size)?;
        let len = le(payload, offset_size, length_size)?;
        if !visited.insert(at) || visited.len() > 1024 {
            return Err("cyclic or excessive object header continuations".into());
        }
        let chunk = read_range(storage, at, len)?;
        if v2 {
            if chunk.len() < 8 || &chunk[..4] != b"OCHK" {
                return Err("invalid continuation signature".into());
            }
            v2_messages(&chunk[4..chunk.len() - 4], creation_order, &mut messages)?;
        } else {
            v1_messages(&chunk, &mut messages)?;
        }
    }
    Ok(messages)
}

fn v1_messages(chunk: &[u8], out: &mut Vec<Message>) -> Result<(), String> {
    let mut at = 0;
    while at + 8 <= chunk.len() {
        let kind = le(chunk, at, 2)? as u16;
        let size = le(chunk, at + 2, 2)? as usize;
        let flags = chunk[at + 4];
        let payload = chunk
            .get(at + 8..at + 8 + size)
            .ok_or_else(|| "message extends past header chunk".to_string())?;
        out.push((kind, flags, payload.to_vec()));
        at += 8 + size;
    }
    Ok(())
}

fn v2_messages(chunk: &[u8], creation_order: bool, out: &mut Vec<Message>) -> Result<(), String> {
    let envelope = if creation_order { 6 } else { 4 };
    let mut at = 0;
    while at + envelope <= chunk.len() {
        let kind = u16::from(chunk[at]);
        let size = le(chunk, at + 1, 2)? as usize;
        let flags = chunk[at + 3];
        let payload = chunk
            .get(at + envelope..at + envelope + size)
            .ok_or_else(|| "message extends past header chunk".to_string())?;
        out.push((kind, flags, payload.to_vec()));
        at += envelope + size;
    }
    Ok(())
}

fn datatype_payload(file: &Hdf5File, address: u64, depth: u8) -> Result<Vec<u8>, String> {
    let sb = file.superblock();
    if sb.base_address != 0 {
        return Err("non-zero superblock base address".into());
    }
    let (offset_size, length_size) = (sb.offset_size as usize, sb.length_size as usize);
    let messages = header_messages(file.storage(), address, offset_size, length_size)?;
    let mut found = messages
        .into_iter()
        .filter(|(kind, _, _)| *kind == MSG_DATATYPE);
    let (_, flags, payload) = found
        .next()
        .ok_or_else(|| "object header has no datatype message".to_string())?;
    if found.next().is_some() {
        return Err("object header has several datatype messages".into());
    }
    if flags & 0x02 == 0 {
        return Ok(payload);
    }
    // Shared (committed) datatype: follow its object-header address once.
    if depth > 0 {
        return Err("nested shared datatype".into());
    }
    let target = match (payload.first(), payload.get(1)) {
        (Some(1), _) => le(&payload, 8, offset_size)?,
        (Some(2), _) => le(&payload, 2, offset_size)?,
        (Some(3), Some(2)) => le(&payload, 2, offset_size)?,
        (Some(3), Some(1)) => return Err("datatype stored in shared-message heap".into()),
        _ => return Err("unknown shared datatype message".into()),
    };
    datatype_payload(file, target, depth + 1)
}

fn encoding(file: &Hdf5File, ds: &Dataset) -> Result<Encoding, String> {
    let payload = datatype_payload(file, ds.address(), 0)?;
    let head = le(&payload, 0, 4)? as u32;
    let class = (head & 0x0f) as u8;
    let mut enc = Encoding {
        class,
        version: ((head >> 4) & 0x0f) as u8,
        flags: head >> 8,
        size: le(&payload, 4, 4)? as u32,
        bit_offset: None,
        bit_precision: None,
        float: None,
    };
    if class == 0 || class == 1 {
        enc.bit_offset = Some(le(&payload, 8, 2)? as u16);
        enc.bit_precision = Some(le(&payload, 10, 2)? as u16);
    }
    if class == 1 {
        enc.float = Some(FloatLayout {
            exponent_location: le(&payload, 12, 1)? as u8,
            exponent_size: le(&payload, 13, 1)? as u8,
            mantissa_location: le(&payload, 14, 1)? as u8,
            mantissa_size: le(&payload, 15, 1)? as u8,
            exponent_bias: le(&payload, 16, 4)? as u32,
        });
    }
    Ok(enc)
}

/// Accept only encodings whose stored bytes equal the NumPy element bytes.
fn native(dtype: &Datatype, enc: &Encoding) -> Result<Native, String> {
    let full =
        |bits: u32| enc.bit_offset == Some(0) && enc.bit_precision.map(u32::from) == Some(bits);
    match dtype {
        Datatype::FixedPoint {
            size,
            signed,
            byte_order,
        } => {
            if enc.class != 0 || enc.size != u32::from(*size) {
                return Err("datatype message disagrees with parsed integer type".into());
            }
            if *size > 1 && !native_order(byte_order) {
                return Err("non-native byte order".into());
            }
            if !full(u32::from(*size) * 8) {
                return Err(format!(
                    "integer bit offset {:?} / precision {:?} differs from {} storage bits",
                    enc.bit_offset,
                    enc.bit_precision,
                    u32::from(*size) * 8
                ));
            }
            // Bits 1-2 are low/high padding; with full precision there is none.
            Ok(match (*size, *signed) {
                (1, true) => Native::I8,
                (2, true) => Native::I16,
                (4, true) => Native::I32,
                (8, true) => Native::I64,
                (1, false) => Native::U8,
                (2, false) => Native::U16,
                (4, false) => Native::U32,
                (8, false) => Native::U64,
                _ => return Err("unsupported integer width".into()),
            })
        }
        Datatype::FloatingPoint { size, byte_order } => {
            if enc.class != 1 || enc.size != u32::from(*size) {
                return Err("datatype message disagrees with parsed float type".into());
            }
            if enc.flags & 0x40 != 0 {
                return Err("VAX floating-point byte order".into());
            }
            if !native_order(byte_order) {
                return Err("non-native byte order".into());
            }
            let (bits, ieee, native) = match *size {
                4 => (32, (31, 23, 8, 0, 23, 127), Native::F32),
                8 => (64, (63, 52, 11, 0, 52, 1023), Native::F64),
                _ => return Err("unsupported float width".into()),
            };
            let layout = enc.float.ok_or("missing float layout")?;
            let sign_location = (enc.flags >> 8) & 0xff;
            let normalization = (enc.flags >> 4) & 0x03;
            let padding = (enc.flags >> 1) & 0x07;
            let actual = (
                sign_location,
                u32::from(layout.exponent_location),
                u32::from(layout.exponent_size),
                u32::from(layout.mantissa_location),
                u32::from(layout.mantissa_size),
                layout.exponent_bias,
            );
            if !full(bits) || actual != ieee || normalization != 2 || padding != 0 {
                return Err(format!(
                    "non-IEEE float encoding: sign/exponent/mantissa/bias {actual:?}, \
                     normalization {normalization}, padding {padding:#b}, \
                     offset {:?}, precision {:?}",
                    enc.bit_offset, enc.bit_precision
                ));
            }
            Ok(native)
        }
        other => Err(format!("unsupported numeric dtype: {other:?}")),
    }
}

fn checked_native(file: &Hdf5File, ds: &Dataset) -> PyResult<Native> {
    let enc = encoding(file, ds)
        .map_err(|e| UnsupportedError::new_err(format!("cannot verify datatype encoding: {e}")))?;
    native(ds.dtype(), &enc).map_err(UnsupportedError::new_err)
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
    // Validate the stored encoding before decoding any element. Native arrays
    // must not silently change byte order; the adapter uses h5py otherwise.
    let kind = checked_native(file, &ds)?;
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
    match kind {
        Native::I8 => read_as!(i8),
        Native::I16 => read_as!(i16),
        Native::I32 => read_as!(i32),
        Native::I64 => read_as!(i64),
        Native::U8 => read_as!(u8),
        Native::U16 => read_as!(u16),
        Native::U32 => read_as!(u32),
        Native::U64 => read_as!(u64),
        Native::F32 => read_as!(f32),
        Native::F64 => read_as!(f64),
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

/// Describe whether `read_numeric` would decode a dataset, without reading data.
///
/// Missing datasets and unreadable files raise as in `read_numeric`; an
/// unsupported type is reported with `supported=False` and a `reason`.
#[pyfunction]
pub fn numeric_capability<'py>(
    py: Python<'py>,
    path: &str,
    dataset_path: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let file = py.detach(|| Hdf5File::open(path)).map_err(err)?;
    let ds = file.dataset(dataset_path).map_err(err)?;
    let out = PyDict::new(py);
    out.set_item("schema_version", CAPABILITY_SCHEMA_VERSION)?;
    out.set_item("dataset", dataset_path)?;
    out.set_item("shape", ds.shape().to_vec())?;
    out.set_item("max_shape", ds.max_dims().map(<[u64]>::to_vec))?;
    out.set_item("chunks", ds.chunks())?;
    let (byte_order, signed) = match ds.dtype() {
        Datatype::FixedPoint {
            signed, byte_order, ..
        } => (Some(byte_order), Some(*signed)),
        Datatype::FloatingPoint { byte_order, .. } | Datatype::Bitfield { byte_order, .. } => {
            (Some(byte_order), None)
        }
        _ => (None, None),
    };
    out.set_item(
        "byte_order",
        byte_order.map(|o| {
            if matches!(o, ByteOrder::LittleEndian) {
                "little"
            } else {
                "big"
            }
        }),
    )?;
    out.set_item("signed", signed)?;
    let verdict = match encoding(&file, &ds) {
        Ok(enc) => {
            let class = match enc.class {
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
                float.set_item("sign_location", (enc.flags >> 8) & 0xff)?;
                float.set_item("exponent_location", layout.exponent_location)?;
                float.set_item("exponent_size", layout.exponent_size)?;
                float.set_item("mantissa_location", layout.mantissa_location)?;
                float.set_item("mantissa_size", layout.mantissa_size)?;
                float.set_item("exponent_bias", layout.exponent_bias)?;
                float.set_item("mantissa_normalization", (enc.flags >> 4) & 0x03)?;
                float.set_item("vax_order", enc.flags & 0x40 != 0)?;
                out.set_item("float_layout", float)?;
            }
            native(ds.dtype(), &enc)
        }
        Err(e) => Err(format!("cannot verify datatype encoding: {e}")),
    };
    match verdict {
        Ok(kind) => {
            out.set_item("supported", true)?;
            out.set_item("numpy_dtype", kind.numpy())?;
            out.set_item("reason", py.None())?;
        }
        Err(reason) => {
            out.set_item("supported", false)?;
            out.set_item("numpy_dtype", py.None())?;
            out.set_item("reason", reason)?;
        }
    }
    Ok(out)
}

#[cfg(test)]
mod capability_error_tests {
    use super::*;

    #[test]
    fn committed_type_limitation_is_distinct_from_reserved_location_corruption() {
        assert_eq!(
            classify(&Error::InvalidData(
                "unknown shared message v2 type: 2".into()
            )),
            3
        );
        for message in [
            "unknown shared message v2 type: 255",
            "unsupported shared message v3 type: 255",
            "unknown shared message v2 type: 20",
        ] {
            assert_eq!(
                classify(&Error::InvalidData(message.into())),
                0,
                "{message}"
            );
        }
    }
}
