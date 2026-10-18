//! PyO3 bindings for the lossless HEC-RAS text core ([`crate::ras_text`]).
//!
//! Inputs are byte buffers; the extension never opens, transcodes or writes
//! files. Identifiers (river, reach, station, node name, keys) are returned
//! as the original bytes so the Python adapter decodes them exactly like the
//! pure-Python readers. Edits are validated and applied as one batch: either
//! every edit applies or the call raises and no output is produced.
//!
//! Registration lives in the shared `lib.rs` (integrator patch):
//! `pub mod ras_text; mod text_bindings;` and `text_bindings::register(m)?`.

use std::ops::Range;

use ndarray::Array2;
use numpy::{IntoPyArray, PyReadonlyArray2};
use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList};

use crate::ras_text::{
    apply_batch, Diagnostic, EditBatch, GeometryIndex, Severity, TextDocument, TextError,
};

/// Version of the text binding contract, independent of `API_VERSION`.
pub const TEXT_API_VERSION: u32 = 1;

pyo3::create_exception!(ras_commander_fast_hdf, TextEditError, PyValueError);
pyo3::create_exception!(ras_commander_fast_hdf, TextNotFoundError, PyValueError);
pyo3::create_exception!(ras_commander_fast_hdf, TextParseError, PyValueError);

fn map_err(e: TextError) -> PyErr {
    let msg = e.to_string();
    match e {
        TextError::NotFound(_) => TextNotFoundError::new_err(msg),
        TextError::Io(_) => PyOSError::new_err(msg),
        _ => TextEditError::new_err(msg),
    }
}

/// Latin-1 strings from the core map one char to one byte; recover the bytes.
fn raw(text: &str) -> Vec<u8> {
    text.chars().map(|c| c as u32 as u8).collect()
}

fn diagnostics<'py>(py: Python<'py>, diags: &[Diagnostic]) -> PyResult<Bound<'py, PyList>> {
    let out = PyList::empty(py);
    for d in diags {
        let item = PyDict::new(py);
        item.set_item("severity", d.severity.as_str())?;
        item.set_item("code", d.code)?;
        item.set_item("line", d.line)?;
        item.set_item("start", d.span.start)?;
        item.set_item("end", d.span.end)?;
        item.set_item("message", PyBytes::new(py, &raw(&d.message)))?;
        out.append(item)?;
    }
    Ok(out)
}

fn index_array(rows: Vec<[i64; 5]>) -> Array2<i64> {
    let n = rows.len();
    Array2::from_shape_vec((n, 5), rows.into_iter().flatten().collect()).expect("shape")
}

/// Index a text buffer: line spans, key spans, encoding report and
/// document diagnostics. The input is copied once and parsed without the GIL.
#[pyfunction]
fn text_index<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyDict>> {
    let bytes = data.to_vec();
    let doc = py.detach(move || TextDocument::parse(bytes));
    let out = PyDict::new(py);
    let lines: Vec<i64> = doc
        .lines()
        .iter()
        .flat_map(|l| [l.start as i64, l.content_end as i64, l.end as i64])
        .collect();
    let n = doc.line_count();
    out.set_item("line_count", n)?;
    out.set_item(
        "lines",
        Array2::from_shape_vec((n, 3), lines)
            .expect("shape")
            .into_pyarray(py),
    )?;
    let mut keys = Vec::new();
    let mut free = Vec::with_capacity(n);
    for line in 0..n {
        free.push(doc.is_free_text(line));
        if let Some(k) = doc.key_line(line) {
            keys.push([
                line as i64,
                k.key.start as i64,
                k.key.end as i64,
                k.value.start as i64,
                k.value.end as i64,
            ]);
        }
    }
    out.set_item("keys", index_array(keys).into_pyarray(py))?;
    out.set_item("free_text", free.into_pyarray(py))?;
    let counts = PyList::empty(py);
    for (key, count) in doc.key_counts() {
        counts.append((PyBytes::new(py, &raw(&key)), count))?;
    }
    out.set_item("key_counts", counts)?;
    let e = doc.encoding();
    let enc = PyDict::new(py);
    enc.set_item("utf8_bom", e.utf8_bom)?;
    enc.set_item("valid_utf8", e.valid_utf8)?;
    enc.set_item("non_ascii_bytes", e.non_ascii_bytes)?;
    enc.set_item("nul_bytes", e.nul_bytes)?;
    enc.set_item("lf", e.lf)?;
    enc.set_item("crlf", e.crlf)?;
    enc.set_item("cr", e.cr)?;
    enc.set_item("final_newline", e.final_newline)?;
    out.set_item("encoding", enc)?;
    out.set_item("diagnostics", diagnostics(py, doc.diagnostics())?)?;
    Ok(out)
}

fn spans_list<'py>(
    py: Python<'py>,
    spans: &[crate::ras_text::AppliedSpan],
) -> PyResult<Bound<'py, PyList>> {
    let out = PyList::empty(py);
    for s in spans {
        out.append((
            s.label.as_str(),
            s.original.start,
            s.original.end,
            s.updated.start,
            s.updated.end,
        ))?;
    }
    Ok(out)
}

/// Apply raw byte-span replacements `(start, end, replacement, label)` as one
/// atomic batch. Out-of-range, reversed, overlapping or ambiguous edits
/// reject the whole batch with `TextEditError`.
#[pyfunction]
fn text_apply_edits<'py>(
    py: Python<'py>,
    data: &[u8],
    edits: Vec<(usize, usize, Vec<u8>, String)>,
) -> PyResult<(Bound<'py, PyBytes>, Bound<'py, PyList>)> {
    let mut batch = EditBatch::new();
    for (start, end, replacement, label) in edits {
        batch.replace(start..end, replacement, label);
    }
    let result = apply_batch(data, &batch).map_err(map_err)?;
    Ok((
        PyBytes::new(py, &result.bytes),
        spans_list(py, &result.spans)?,
    ))
}

/// Error diagnostics whose line falls inside `lines` (header included).
fn has_error(diags: &[Diagnostic], lines: Range<usize>) -> bool {
    diags
        .iter()
        .any(|d| d.severity == Severity::Error && lines.contains(&d.line))
}

fn block_lines(block: &crate::ras_text::CountedBlock) -> Range<usize> {
    block.header_line..block.data_lines.end.max(block.header_line + 1)
}

/// Per-node table of `key` items: (status, offsets, values). Status is
/// 0 = absent, 1 = valid, 2 = malformed (count/slot/field diagnostics).
/// Malformed blocks contribute no values: nothing is repaired or guessed.
fn node_table(index: &GeometryIndex, key: &str, width: usize) -> (Vec<u8>, Vec<i64>, Vec<f64>) {
    let mut status = Vec::with_capacity(index.nodes.len());
    let mut offsets = Vec::with_capacity(index.nodes.len() + 1);
    let mut values = Vec::new();
    offsets.push(0i64);
    for node in 0..index.nodes.len() {
        match index.node_block(node, key) {
            None => status.push(0),
            Some(b) if has_error(&index.diagnostics, block_lines(b)) => status.push(2),
            Some(b) if b.values.len() != b.count * width => status.push(2),
            Some(b) => {
                status.push(1);
                values.extend_from_slice(&b.values);
            }
        }
        offsets.push((values.len() / width) as i64);
    }
    (status, offsets, values)
}

/// Parse a geometry buffer into nodes, reaches, sections, counted blocks,
/// diagnostics and (optionally) per-node station/elevation, Manning's n and
/// bank-station tables.
#[pyfunction]
#[pyo3(signature = (data, tables=true))]
fn text_geometry_index<'py>(
    py: Python<'py>,
    data: &[u8],
    tables: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let bytes = data.to_vec();
    let (doc, index) = py.detach(move || {
        let doc = TextDocument::parse(bytes);
        let index = GeometryIndex::parse(&doc);
        (doc, index)
    });
    let out = PyDict::new(py);
    let opt = |v: &Option<String>| v.as_deref().map(|s| PyBytes::new(py, &raw(s)));
    out.set_item("title", opt(&index.title))?;
    out.set_item("program_version", opt(&index.program_version))?;
    out.set_item("line_count", doc.line_count())?;

    let n = index.nodes.len();
    let nodes = PyDict::new(py);
    let rivers = PyList::empty(py);
    let reaches = PyList::empty(py);
    let stations = PyList::empty(py);
    let names = PyList::empty(py);
    let mut types = Vec::with_capacity(n);
    let mut lengths = Vec::with_capacity(n * 3);
    let mut header_lines = Vec::with_capacity(n);
    for rec in &index.nodes {
        rivers.append(opt(&rec.river))?;
        reaches.append(opt(&rec.reach))?;
        stations.append(PyBytes::new(py, &raw(&rec.station)))?;
        names.append(PyBytes::new(py, &raw(&rec.node_name)))?;
        types.push(rec.node_type);
        lengths.extend_from_slice(&rec.lengths);
        header_lines.push(index.sections[rec.section].lines.start as i64);
    }
    nodes.set_item("river", rivers)?;
    nodes.set_item("reach", reaches)?;
    nodes.set_item("station", stations)?;
    nodes.set_item("node_name", names)?;
    nodes.set_item("type", types.into_pyarray(py))?;
    nodes.set_item(
        "lengths",
        Array2::from_shape_vec((n, 3), lengths)
            .expect("shape")
            .into_pyarray(py),
    )?;
    nodes.set_item("header_line", header_lines.into_pyarray(py))?;
    out.set_item("nodes", nodes)?;

    let reach_list = PyList::empty(py);
    for r in &index.reaches {
        reach_list.append((
            PyBytes::new(py, &raw(&r.river)),
            PyBytes::new(py, &raw(&r.reach)),
            r.legacy,
        ))?;
    }
    out.set_item("reaches", reach_list)?;

    let sections = PyList::empty(py);
    for s in &index.sections {
        sections.append((
            s.kind.as_str(),
            PyBytes::new(py, &raw(&s.key)),
            PyBytes::new(py, &raw(&s.name)),
            s.lines.start,
            s.lines.end,
        ))?;
    }
    out.set_item("sections", sections)?;

    let blocks = PyList::empty(py);
    for b in &index.blocks {
        blocks.append((
            b.key,
            b.header_line,
            b.count,
            b.values.len(),
            b.section,
            has_error(&index.diagnostics, block_lines(b)),
        ))?;
    }
    out.set_item("blocks", blocks)?;
    out.set_item("diagnostics", diagnostics(py, &index.diagnostics)?)?;
    out.set_item("document_diagnostics", diagnostics(py, doc.diagnostics())?)?;
    out.set_item("error_count", index.error_count())?;

    if tables {
        for (name, key, width) in [
            ("station_elevation", "#Sta/Elev", 2usize),
            ("mannings_n", "#Mann", 3usize),
        ] {
            let (status, offsets, values) = node_table(&index, key, width);
            let rows = values.len() / width;
            let table = PyDict::new(py);
            table.set_item("status", status.into_pyarray(py))?;
            table.set_item("offsets", offsets.into_pyarray(py))?;
            table.set_item(
                "values",
                Array2::from_shape_vec((rows, width), values)
                    .expect("shape")
                    .into_pyarray(py),
            )?;
            out.set_item(name, table)?;
        }
        let mut status = Vec::with_capacity(n);
        let mut banks = Vec::with_capacity(n * 2);
        for node in 0..n {
            match (
                index.nodes[node].bank_sta_line,
                index.bank_stations(&doc, node),
            ) {
                (None, _) => {
                    status.push(0u8);
                    banks.extend_from_slice(&[f64::NAN, f64::NAN]);
                }
                (Some(_), None) => {
                    status.push(2);
                    banks.extend_from_slice(&[f64::NAN, f64::NAN]);
                }
                (Some(_), Some((l, r))) => {
                    status.push(1);
                    banks.extend_from_slice(&[l, r]);
                }
            }
        }
        let table = PyDict::new(py);
        table.set_item("status", status.into_pyarray(py))?;
        table.set_item(
            "values",
            Array2::from_shape_vec((n, 2), banks)
                .expect("shape")
                .into_pyarray(py),
        )?;
        out.set_item("bank_stations", table)?;
    }
    Ok(out)
}

fn required<'py>(op: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    op.get_item(key)?
        .ok_or_else(|| TextEditError::new_err(format!("edit operation is missing '{key}'")))
}

fn rows(op: &Bound<'_, PyDict>, width: usize) -> PyResult<Vec<f64>> {
    let values: PyReadonlyArray2<'_, f64> = required(op, "values")?.extract()?;
    let view = values.as_array();
    if view.ncols() != width {
        return Err(TextEditError::new_err(format!(
            "edit values need {width} columns, got {}",
            view.ncols()
        )));
    }
    let flat: Vec<f64> = view.iter().copied().collect();
    if let Some(v) = flat.iter().find(|v| !v.is_finite()) {
        return Err(TextEditError::new_err(format!("value {v} is not finite")));
    }
    Ok(flat)
}

/// Apply typed geometry edits as one atomic batch. Each operation is a dict
/// with `op` in {"station_elevation", "mannings_n", "bank_stations"}, `node`
/// (index from `text_geometry_index` of the same bytes) and `values`
/// (float64 arrays of shape (n, 2), (n, 3) and (1, 2) respectively).
/// Edits targeting a malformed block are rejected rather than repaired.
#[pyfunction]
fn text_geometry_edit<'py>(
    py: Python<'py>,
    data: &[u8],
    ops: &Bound<'py, PyList>,
) -> PyResult<(Bound<'py, PyBytes>, Bound<'py, PyList>)> {
    let doc = TextDocument::parse(data.to_vec());
    let index = GeometryIndex::parse(&doc);
    let mut batch = EditBatch::new();
    for item in ops.iter() {
        let op = item.cast::<PyDict>()?;
        let kind: String = required(op, "op")?.extract()?;
        let node: usize = required(op, "node")?.extract()?;
        if node >= index.nodes.len() {
            return Err(TextNotFoundError::new_err(format!(
                "node {node} outside {} geometry nodes",
                index.nodes.len()
            )));
        }
        let key = match kind.as_str() {
            "station_elevation" => Some("#Sta/Elev"),
            "mannings_n" => Some("#Mann"),
            "bank_stations" => None,
            other => {
                return Err(TextEditError::new_err(format!(
                    "unsupported edit operation '{other}'"
                )))
            }
        };
        if let Some(block) = key.and_then(|k| index.node_block(node, k)) {
            if has_error(&index.diagnostics, block_lines(block)) {
                return Err(TextParseError::new_err(format!(
                    "refusing to edit malformed {} block at line {}",
                    block.key,
                    block.header_line + 1
                )));
            }
        }
        let part = match kind.as_str() {
            "station_elevation" => {
                let v = rows(op, 2)?;
                let pts: Vec<(f64, f64)> = v.chunks_exact(2).map(|c| (c[0], c[1])).collect();
                index.edit_station_elevation(&doc, node, &pts)
            }
            "mannings_n" => {
                let v = rows(op, 3)?;
                let trip: Vec<(f64, f64, f64)> =
                    v.chunks_exact(3).map(|c| (c[0], c[1], c[2])).collect();
                index.edit_mannings_n(&doc, node, &trip)
            }
            _ => {
                let v = rows(op, 2)?;
                if v.len() != 2 {
                    return Err(TextEditError::new_err(
                        "bank_stations values must have shape (1, 2)",
                    ));
                }
                index.edit_bank_stations(&doc, node, v[0], v[1])
            }
        }
        .map_err(map_err)?;
        batch.extend(part);
    }
    let result = apply_batch(doc.as_bytes(), &batch).map_err(map_err)?;
    Ok((
        PyBytes::new(py, &result.bytes),
        spans_list(py, &result.spans)?,
    ))
}

/// Register the text bindings on the extension module.
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("TEXT_API_VERSION", TEXT_API_VERSION)?;
    m.add("TextEditError", m.py().get_type::<TextEditError>())?;
    m.add("TextNotFoundError", m.py().get_type::<TextNotFoundError>())?;
    m.add("TextParseError", m.py().get_type::<TextParseError>())?;
    m.add_function(wrap_pyfunction!(text_index, m)?)?;
    m.add_function(wrap_pyfunction!(text_apply_edits, m)?)?;
    m.add_function(wrap_pyfunction!(text_geometry_index, m)?)?;
    m.add_function(wrap_pyfunction!(text_geometry_edit, m)?)?;
    Ok(())
}
