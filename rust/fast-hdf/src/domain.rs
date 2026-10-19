//! Explicit conversion only; engine retains schema and capability decisions.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use ras_commander_rust::crs::{CrsEvidence, EvidenceStatus};
use ras_commander_rust::hdf::metadata::MetadataValue;
use ras_commander_rust::hdf::xs1d::{
    PlanResultMode, ResultFamily, XsField, XsResultKind, XsVariable,
};
use ras_commander_rust::hdf::{AttributeType, ByteOrder, ReadOnlyHdfSession, Slice};
use ras_commander_rust::{Capability, UnsupportedCode};
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
fn code(c: &UnsupportedCode) -> &'static str {
    match c {
        UnsupportedCode::Encoding => "encoding",
        UnsupportedCode::Schema => "schema",
        UnsupportedCode::IdentityLayout => "identity_layout",
        UnsupportedCode::ResourceLimit => "resource_limit",
        UnsupportedCode::NotImplemented => "not_implemented",
        _ => "unknown",
    }
}
pub(crate) fn capability<'py>(py: Python<'py>, c: &Capability) -> PyResult<Bound<'py, PyDict>> {
    let (status, reason, code) = match c {
        Capability::Supported => ("supported", None, None),
        Capability::Unavailable { reason } => ("unavailable", Some(reason.as_str()), None),
        Capability::Unsupported { code: c, reason } => {
            ("unsupported", Some(reason.as_str()), Some(code(c)))
        }
        Capability::Corrupt { reason } => ("corrupt", Some(reason.as_str()), None),
        Capability::Delegated { reason } => ("delegated", Some(reason.as_str()), None),
        _ => ("unknown", None, None),
    };
    Ok(dict!(py,"status"=>status,"reason"=>reason,"code"=>code))
}
fn order(o: ByteOrder) -> &'static str {
    match o {
        ByteOrder::Little => "little",
        ByteOrder::Big => "big",
        _ => "unknown",
    }
}
fn attribute_type<'py>(py: Python<'py>, t: &AttributeType) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match t {
        AttributeType::Int {
            signed,
            bytes,
            order: o,
        } => {
            d.set_item("kind", "integer")?;
            d.set_item("signed", signed)?;
            d.set_item("bytes", bytes)?;
            d.set_item("byte_order", order(*o))?;
        }
        AttributeType::Float { bytes, order: o } => {
            d.set_item("kind", "float")?;
            d.set_item("bytes", bytes)?;
            d.set_item("byte_order", order(*o))?;
        }
        AttributeType::FixedString {
            charset,
            padding,
            width,
        } => {
            use ras_commander_rust::hdf::{StringCharset as C, StringPadding as P};
            d.set_item("kind", "fixed_string")?;
            d.set_item("width", width)?;
            d.set_item(
                "charset",
                match charset {
                    C::Ascii => "ascii",
                    C::Utf8 => "utf8",
                    _ => "unknown",
                },
            )?;
            d.set_item(
                "padding",
                match padding {
                    P::NullTerminate => "null_terminate",
                    P::NullPad => "null_pad",
                    P::SpacePad => "space_pad",
                    _ => "unknown",
                },
            )?;
        }
        AttributeType::Compound => d.set_item("kind", "compound")?,
        AttributeType::Unsupported { capability: c } => {
            d.set_item("kind", "unsupported")?;
            d.set_item("capability", capability(py, c)?)?;
        }
        _ => d.set_item("kind", "unknown")?,
    }
    Ok(d)
}
fn evidence<'py>(py: Python<'py>, e: &CrsEvidence) -> PyResult<Bound<'py, PyDict>> {
    let (status, c) = match &e.status {
        EvidenceStatus::Unknown => ("unknown", None),
        EvidenceStatus::Unvalidated => ("unvalidated", None),
        EvidenceStatus::Invalid => ("invalid", None),
        EvidenceStatus::Conflict => ("conflict", None),
        EvidenceStatus::Unsupported(c) => ("unsupported", Some(c)),
        EvidenceStatus::Corrupt(c) => ("corrupt", Some(c)),
        _ => ("unknown", None),
    };
    let d = dict!(py,"source"=>&e.source,"exact_wkt"=>&e.exact_wkt,"raw_bytes"=>PyBytes::new(py,&e.raw_bytes),"unit_clauses"=>&e.unit_clauses,"axis_clauses"=>&e.axis_clauses,"status"=>status);
    d.set_item("capability", c.map(|c| capability(py, c)).transpose()?)?;
    Ok(d)
}
fn status(s: &EvidenceStatus) -> &'static str {
    match s {
        EvidenceStatus::Unknown => "unknown",
        EvidenceStatus::Unvalidated => "unvalidated",
        EvidenceStatus::Invalid => "invalid",
        EvidenceStatus::Conflict => "conflict",
        EvidenceStatus::Unsupported(_) => "unsupported",
        EvidenceStatus::Corrupt(_) => "corrupt",
        _ => "unknown",
    }
}
fn mode(m: PlanResultMode) -> &'static str {
    match m {
        PlanResultMode::Steady => "steady",
        PlanResultMode::Unsteady => "unsteady",
        PlanResultMode::Mixed => "mixed",
        PlanResultMode::Unavailable => "unavailable",
        _ => "unknown",
    }
}
#[pyfunction]
fn capabilities(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    Ok(
        dict!(py,"api_version"=>2,"engine_commit"=>env!("RAS_ENGINE_COMMIT"),"engine_features"=>env!("RAS_ENGINE_FEATURES").split(',').collect::<Vec<_>>(),"bindings"=>["numeric_capability","read_numeric","read_numeric_batch","temporal_reduce","assemble_cells","raw_crs_evidence","typed_group_attributes","mesh_inventory","cross_sections","plan_result_mode","steady_profile_names","read_cross_section_result","plan_capabilities"]),
    )
}
#[pyfunction]
fn raw_crs_evidence(py: Python<'_>, path: PathBuf) -> PyResult<Bound<'_, PyDict>> {
    let r = py
        .detach(|| ReadOnlyHdfSession::open(path)?.raw_crs_evidence())
        .map_err(crate::reader::err)?;
    let ev = r
        .evidence
        .iter()
        .map(|e| evidence(py, e))
        .collect::<PyResult<Vec<_>>>()?;
    let units = r
        .hydraulic_units_evidence
        .iter()
        .map(|e| evidence(py, e))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"status"=>status(&r.status),"evidence"=>ev,"hydraulic_units"=>r.hydraulic_units,"hydraulic_units_evidence"=>units),
    )
}
#[pyfunction]
#[pyo3(signature=(path,group="/"))]
fn typed_group_attributes<'py>(
    py: Python<'py>,
    path: PathBuf,
    group: &str,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let attrs = py
        .detach(|| ReadOnlyHdfSession::open(path)?.typed_group_attributes(group))
        .map_err(crate::reader::err)?;
    attrs.into_iter().map(|a| {
        let d=dict!(py,"name"=>a.name,"shape"=>a.shape,"attribute_type"=>attribute_type(py,&a.attribute_type)?,"datatype_label"=>a.datatype_label,"raw_bytes"=>PyBytes::new(py,&a.raw_bytes));
        let c=match a.value {
            MetadataValue::Signed(v)=>{d.set_item("value",v)?;Capability::Supported},MetadataValue::Unsigned(v)=>{d.set_item("value",v)?;Capability::Supported},MetadataValue::Float(v)=>{d.set_item("value",v)?;Capability::Supported},MetadataValue::Strings(v)=>{d.set_item("value",v)?;Capability::Supported},MetadataValue::Unsupported(c)|MetadataValue::Corrupt(c)=>{d.set_item("value",py.None())?;c},_=>{d.set_item("value",py.None())?;Capability::unsupported(UnsupportedCode::NotImplemented,"future metadata value".into())}
        };d.set_item("capability",capability(py,&c)?)?;Ok(d)
    }).collect()
}
#[pyfunction]
fn mesh_inventory(py: Python<'_>, path: PathBuf) -> PyResult<Vec<Bound<'_, PyDict>>> {
    let meshes = py
        .detach(|| ReadOnlyHdfSession::open(path)?.initial_2d_inventory())
        .map_err(crate::reader::err)?;
    meshes.into_iter().map(|m| {
        let vars=m.results.variables.iter().map(|v|Ok(dict!(py,"dataset"=>&v.dataset,"shape"=>&v.shape,"capability"=>capability(py,&v.capability)?))).collect::<PyResult<Vec<_>>>()?;
        Ok(dict!(py,"source"=>m.source,"mesh_name"=>m.mesh_name,"physical_cells"=>m.physical_cells,"stored_cells"=>m.stored_cells,"ghost_cells"=>m.ghost_cells,"results"=>dict!(py,"capability"=>capability(py,&m.results.capability)?,"variables"=>vars)))
    }).collect()
}
#[pyfunction]
fn plan_result_mode(py: Python<'_>, path: PathBuf) -> PyResult<&'static str> {
    py.detach(|| ReadOnlyHdfSession::open(path)?.plan_result_mode())
        .map(mode)
        .map_err(crate::reader::err)
}
#[pyfunction]
fn steady_profile_names(py: Python<'_>, path: PathBuf) -> PyResult<Vec<String>> {
    py.detach(|| ReadOnlyHdfSession::open(path)?.steady_profile_names())
        .map_err(crate::reader::err)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn cross_sections(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    let g = py
        .detach(|| ReadOnlyHdfSession::open(path)?.cross_sections(max_bytes))
        .map_err(crate::reader::err)?;
    let sections = g
        .sections
        .into_iter()
        .map(|s| {
            let d =
                dict!(py,"index"=>s.index,"river"=>s.river,"reach"=>s.reach,"station"=>s.station);
            macro_rules! field {
                ($name:expr,$v:expr) => {{
                    let f = PyDict::new(py);
                    match $v {
                        XsField::Available(v) => {
                            f.set_item("status", "available")?;
                            f.set_item("value", v)?;
                        }
                        XsField::Unavailable(r) => {
                            f.set_item("status", "unavailable")?;
                            f.set_item("reason", r)?;
                        }
                        XsField::Unsupported(r) => {
                            f.set_item("status", "unsupported")?;
                            f.set_item("reason", r)?;
                        }
                        _ => f.set_item("status", "unknown")?,
                    };
                    d.set_item($name, f)?;
                }};
            }
            field!("name", s.name);
            field!("left_bank", s.left_bank);
            field!("right_bank", s.right_bank);
            Ok(d)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"source"=>g.source,"dataset"=>g.dataset,"sections"=>sections))
}
#[pyfunction]
#[pyo3(signature=(path,kind,variable,rows,sections,max_bytes=67108864,threads=None,parallel=true))]
#[allow(clippy::too_many_arguments)]
fn read_cross_section_result<'py>(
    py: Python<'py>,
    path: PathBuf,
    kind: &str,
    variable: &str,
    rows: (u64, u64, u64),
    sections: (u64, u64, u64),
    max_bytes: usize,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let k = match kind {
        "steady" => XsResultKind::Steady,
        "unsteady" => XsResultKind::Unsteady,
        _ => return Err(PyValueError::new_err("kind must be steady or unsteady")),
    };
    let v = match variable {
        "Water Surface" => XsVariable::WaterSurface,
        "Flow" => XsVariable::Flow,
        _ => {
            return Err(PyValueError::new_err(
                "variable must be Water Surface or Flow",
            ))
        }
    };
    let threads = crate::reader::threads(threads)?;
    let out = py
        .detach(|| {
            ReadOnlyHdfSession::with_options(path, threads, parallel)?.read_cross_section_result(
                k,
                v,
                Slice::new(rows.0, rows.1, rows.2),
                Slice::new(sections.0, sections.1, sections.2),
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    crate::reader::array(py, out)
}
#[pyfunction]
fn plan_capabilities(py: Python<'_>, path: PathBuf) -> PyResult<Bound<'_, PyDict>> {
    let c = py
        .detach(|| ReadOnlyHdfSession::open(path)?.plan_capabilities())
        .map_err(crate::reader::err)?;
    let families=c.families.iter().map(|f| {
        let family=match f.family {ResultFamily::Mesh2D=>"mesh_2d",ResultFamily::CrossSectionsUnsteady=>"cross_sections_unsteady",ResultFamily::SteadyProfiles=>"steady_profiles",ResultFamily::Structures=>"structures",ResultFamily::Pipes=>"pipes",ResultFamily::ReferenceLines=>"reference_lines",ResultFamily::ReferencePoints=>"reference_points",_=>"unknown"};
        Ok(dict!(py,"family"=>family,"capability"=>capability(py,&f.status)?,"datasets"=>&f.datasets))
    }).collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"mode"=>mode(c.mode),"families"=>families))
}
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(capabilities, m)?)?;
    m.add_function(wrap_pyfunction!(raw_crs_evidence, m)?)?;
    m.add_function(wrap_pyfunction!(typed_group_attributes, m)?)?;
    m.add_function(wrap_pyfunction!(mesh_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(cross_sections, m)?)?;
    m.add_function(wrap_pyfunction!(plan_result_mode, m)?)?;
    m.add_function(wrap_pyfunction!(steady_profile_names, m)?)?;
    m.add_function(wrap_pyfunction!(read_cross_section_result, m)?)?;
    m.add_function(wrap_pyfunction!(plan_capabilities, m)?)?;
    Ok(())
}
