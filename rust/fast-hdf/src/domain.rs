//! Explicit conversion only; engine retains schema and capability decisions.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};
use ras_commander_rust::crs::{CrsEvidence, EvidenceStatus};
use ras_commander_rust::hdf::metadata::MetadataValue;
use ras_commander_rust::hdf::xs1d::{PlanResultMode, XsVariable};
use ras_commander_rust::hdf::{AttributeType, ByteOrder, ReadOnlyHdfSession, ResultMode, Slice};
use ras_commander_rust::{Capability, UnsupportedCode};
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
pub(crate) fn capability<'py>(py: Python<'py>, c: &Capability) -> PyResult<Bound<'py, PyDict>> {
    Ok(dict!(py,"status"=>c.as_str(),"code"=>c.code().map(|v|v.as_str()),"reason"=>c.reason()))
}
fn order(o: ByteOrder) -> &'static str {
    o.as_str()
}
pub(crate) fn evidence_dict<'py>(
    py: Python<'py>,
    kind: &str,
    raw: Option<&[u8]>,
    c: &Capability,
) -> PyResult<Bound<'py, PyDict>> {
    Ok(
        dict!(py,"kind"=>kind,"value"=>py.None(),"raw_bytes"=>raw.map(|b|PyBytes::new(py,b)),"capability"=>capability(py,c)?),
    )
}
pub(crate) fn identity<'py>(
    py: Python<'py>,
    id: &ras_commander_rust::hdf::Identity,
) -> PyResult<Bound<'py, PyDict>> {
    Ok(dict!(py,"source"=>&id.source,"table"=>&id.table,"row"=>id.row))
}
const _: () = assert!(ras_commander_rust::API_VERSION == 7);
const _: () = assert!(ras_commander_rust::hdf::DEFAULT_MAX_BYTES == 67108864);
pub(crate) fn attribute_type<'py>(
    py: Python<'py>,
    t: &AttributeType,
) -> PyResult<Bound<'py, PyDict>> {
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
        AttributeType::Unsupported { .. } => {
            d.set_item("kind", "unsupported")?;
            d.set_item("capability", capability(py, &t.capability())?)?;
        }
        _ => d.set_item("kind", "unknown")?,
    }
    Ok(d)
}
fn evidence<'py>(py: Python<'py>, e: &CrsEvidence) -> PyResult<Bound<'py, PyDict>> {
    let d = evidence_dict(py, status(&e.status), Some(&e.raw_bytes), &e.capability())?;
    d.set_item("value", &e.exact_wkt)?;
    d.set_item("source", &e.source)?;
    d.set_item("exact_wkt", &e.exact_wkt)?;
    d.set_item("unit_clauses", &e.unit_clauses)?;
    d.set_item("axis_clauses", &e.axis_clauses)?;
    Ok(d)
}
fn status(s: &EvidenceStatus) -> &'static str {
    match s {
        EvidenceStatus::Unknown => "unknown",
        EvidenceStatus::Unvalidated => "unvalidated",
        EvidenceStatus::Invalid => "invalid",
        EvidenceStatus::Conflict => "conflict",
        EvidenceStatus::Unsupported { .. } => "unsupported",
        EvidenceStatus::Corrupt { .. } => "corrupt",
        _ => "unknown",
    }
}
fn mode(m: PlanResultMode) -> &'static str {
    m.as_str()
}
#[pyfunction]
fn capabilities(py: Python<'_>) -> PyResult<Bound<'_, PyDict>> {
    let engine = ras_commander_rust::capabilities();
    let entrypoints = engine
        .entrypoints
        .iter()
        .map(|e| Ok(dict!(py,"owner"=>e.owner,"name"=>e.name,"feature"=>e.feature)))
        .collect::<PyResult<Vec<_>>>()?;
    let engine_capabilities = dict!(py,"api_version"=>engine.api_version,"features"=>engine.features,"entrypoints"=>entrypoints);
    Ok(
        dict!(py,"engine_api_version"=>ras_commander_rust::API_VERSION,"engine_capabilities"=>engine_capabilities,"default_max_bytes"=>ras_commander_rust::hdf::DEFAULT_MAX_BYTES,"api_version"=>crate::API_VERSION,"engine_commit"=>env!("RAS_ENGINE_COMMIT"),"engine_features"=>env!("RAS_ENGINE_FEATURES").split(',').collect::<Vec<_>>(),"bindings"=>crate::REGISTERED_BINDINGS.get().ok_or_else(||pyo3::exceptions::PyRuntimeError::new_err("module registration incomplete"))?),
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
        dict!(py,"kind"=>status(&r.status),"capability"=>capability(py,&r.capability())?,"evidence"=>ev,"hydraulic_units"=>r.hydraulic_units,"hydraulic_units_evidence"=>units),
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
    attrs.iter().map(|a| typed_attribute_dict(py, a)).collect()
}
pub(crate) fn typed_attribute_dict<'py>(
    py: Python<'py>,
    a: &ras_commander_rust::hdf::metadata::TypedAttribute,
) -> PyResult<Bound<'py, PyDict>> {
    let d = dict!(py,"name"=>&a.name,"kind"=>"attribute","shape"=>&a.shape,"attribute_type"=>attribute_type(py,&a.attribute_type)?,"datatype_label"=>&a.datatype_label,"raw_bytes"=>PyBytes::new(py,&a.raw_bytes));
    let c = a.value.capability();
    match &a.value {
        MetadataValue::Signed(v) => {
            d.set_item("value", v)?;
        }
        MetadataValue::Unsigned(v) => {
            d.set_item("value", v)?;
        }
        MetadataValue::Float(v) => {
            d.set_item("value", v)?;
        }
        MetadataValue::Strings(v) => {
            d.set_item("value", v)?;
        }
        MetadataValue::Unsupported { .. } | MetadataValue::Corrupt { .. } => {
            d.set_item("value", py.None())?;
        }
        _ => {
            d.set_item("value", py.None())?;
        }
    };
    d.set_item("capability", capability(py, &c)?)?;
    Ok(d)
}
fn result_availability<'py>(
    py: Python<'py>,
    r: &ras_commander_rust::schema::ResultAvailability,
) -> PyResult<Bound<'py, PyDict>> {
    let vars=r.variables.iter().map(|v|Ok(dict!(py,"dataset"=>&v.dataset,"dataset_path"=>&v.dataset,"shape"=>&v.shape,"capability"=>capability(py,&v.capability)?))).collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"capability"=>capability(py,&r.capability)?,"variables"=>vars))
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn mesh_inventory(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Vec<Bound<'_, PyDict>>> {
    let meshes = py
        .detach(|| ReadOnlyHdfSession::open(path)?.mesh_inventory(max_bytes))
        .map_err(crate::reader::err)?;
    meshes.into_iter().map(|m| {
        let blocks=m.output_blocks.iter().map(|b| Ok(dict!(py,"mode"=>b.mode.as_str(),"block_name"=>&b.block_name,"dataset_root"=>&b.dataset_root,"results"=>result_availability(py,&b.results)?))).collect::<PyResult<Vec<_>>>()?;
        Ok(dict!(py,"source"=>&m.id.source,"identity"=>identity(py,&m.id)?,"mesh_name"=>m.mesh_name,"physical_cells"=>m.physical_cells,"stored_cells"=>m.stored_cells,"ghost_cells"=>m.ghost_cells,"results"=>result_availability(py,&m.results)?,"output_blocks"=>blocks))
    }).collect()
}
#[pyfunction]
fn plan_result_mode(py: Python<'_>, path: PathBuf) -> PyResult<&'static str> {
    py.detach(|| ReadOnlyHdfSession::open(path)?.plan_result_mode())
        .map(mode)
        .map_err(crate::reader::err)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn steady_profile_names(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Vec<String>> {
    py.detach(|| ReadOnlyHdfSession::open(path)?.steady_profile_names(max_bytes))
        .map_err(crate::reader::err)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn cross_sections(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    let g = py
        .detach(|| ReadOnlyHdfSession::open(path)?.cross_sections(max_bytes))
        .map_err(crate::reader::err)?;
    cross_section_geometry(py, g)
}
pub(crate) fn cross_section_geometry(
    py: Python<'_>,
    g: ras_commander_rust::hdf::xs1d::CrossSectionGeometry,
) -> PyResult<Bound<'_, PyDict>> {
    let sections = g
        .sections
        .into_iter()
        .map(|s| {
            let d =
                dict!(py,"index"=>s.id.row,"identity"=>identity(py,&s.id)?,"river"=>s.river,"reach"=>s.reach,"station"=>s.station);
            macro_rules! field {
                ($name:expr,$v:expr) => {{
                    let f=evidence_dict(py,$name,$v.raw_bytes(),$v.capability())?;
                    f.set_item("value",$v.value())?;
                    d.set_item($name, f)?;
                }};
            }
            field!("name", s.name);
            field!("left_bank", s.left_bank);
            field!("right_bank", s.right_bank);
            Ok(d)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"source"=>g.source,"dataset_path"=>&g.dataset,"dataset"=>g.dataset,"sections"=>sections),
    )
}
#[pyfunction]
#[pyo3(signature=(path,kind,variable,rows,sections,max_bytes=67108864,threads=None,parallel=true,*,metadata_max_bytes=67108864))]
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
    metadata_max_bytes: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let k = match kind {
        "steady" => ResultMode::Steady,
        "unsteady" => ResultMode::Unsteady,
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
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    crate::reader::array(py, out)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn plan_capabilities(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    let c = py
        .detach(|| ReadOnlyHdfSession::open(path)?.plan_capabilities(max_bytes))
        .map_err(crate::reader::err)?;
    let families=c.families.iter().map(|f| {
        let family=f.family.as_str();
        Ok(dict!(py,"family"=>family,"capability"=>capability(py,&f.status)?,"datasets"=>&f.datasets))
    }).collect::<PyResult<Vec<_>>>()?;
    let structures=c.structures.iter().map(|s| Ok(dict!(py,"family"=>crate::structures::family_name(s.kind),"capability"=>capability(py,&s.status)?,"datasets"=>&s.datasets,"diagnostics"=>s.diagnostics.iter().map(|m|diagnostic(py,None,Some(m),None)).collect::<PyResult<Vec<_>>>()?))).collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"mode"=>mode(c.mode),"families"=>families,"structures"=>structures))
}

fn axis_capability(a: &ras_commander_rust::hdf::time::TimeAxis) -> Capability {
    if a.timestamps.is_some() {
        Capability::Supported
    } else {
        a.integer_ms.clone().unwrap_or_else(|| {
            Capability::unsupported(
                UnsupportedCode::Schema,
                "numeric time axis has no proven civil epoch",
            )
        })
    }
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn unsteady_time_axis(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    use ras_commander_rust::hdf::time::{MillisecondSource, TimeEpoch};
    let a = py
        .detach(|| ReadOnlyHdfSession::open(path)?.unsteady_time_axis(max_bytes))
        .map_err(crate::reader::err)?;
    let timestamps = a
        .timestamps
        .as_ref()
        .map(|v| v.iter().map(ToString::to_string).collect::<Vec<_>>());
    let epoch = match a.epoch {
        TimeEpoch::CivilUnix1970 => "civil_unix_1970",
        _ => "unknown",
    };
    let source = a.ms_source.map(|v| match v {
        MillisecondSource::StoredStringDataset => "stored_string_dataset",
        MillisecondSource::DerivedFromStrings => "derived_from_strings",
        _ => "unknown",
    });
    Ok(
        dict!(py,"group"=>&a.group,"rows"=>a.rows,"days"=>&a.days,"raw_strings"=>&a.raw_strings,"raw_ms"=>&a.raw_ms,"raw_ms_strings"=>&a.raw_ms_strings,"ms_since_epoch"=>&a.ms_since_epoch,"timestamps"=>timestamps,"hour_2400_rows"=>&a.hour_2400_rows,"epoch"=>epoch,"ms_source"=>source,"timezone"=>py.None(),"capability"=>capability(py,&axis_capability(&a))?,"integer_ms"=>a.integer_ms.as_ref().map(|c|capability(py,c)).transpose()?),
    )
}
#[pyfunction]
#[pyo3(signature=(path,rows,max_bytes=67108864))]
fn unsteady_row_times(
    py: Python<'_>,
    path: PathBuf,
    rows: (u64, u64, u64),
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    let (a, r) = py
        .detach(|| {
            let a = ReadOnlyHdfSession::open(path)?.unsteady_time_axis(max_bytes)?;
            let r = a.select(Slice::new(rows.0, rows.1, rows.2))?;
            Ok::<_, ras_commander_rust::Error>((a, r))
        })
        .map_err(crate::reader::err)?;
    let timestamps = r
        .timestamps
        .as_ref()
        .map(|v| v.iter().map(ToString::to_string).collect::<Vec<_>>());
    let hours = a
        .hour_2400_rows
        .iter()
        .copied()
        .filter(|row| r.row_indices.binary_search(row).is_ok())
        .collect::<Vec<_>>();
    Ok(
        dict!(py,"row_indices"=>&r.row_indices,"days"=>&r.days,"raw_strings"=>&r.raw_strings,"raw_ms"=>&r.raw_ms,"raw_ms_strings"=>&r.raw_ms_strings,"ms_since_epoch"=>&r.ms_since_epoch,"timestamps"=>timestamps,"hour_2400_rows"=>hours,"epoch"=>match a.epoch {ras_commander_rust::hdf::time::TimeEpoch::CivilUnix1970=>"civil_unix_1970",_=>"unknown"},"integer_ms"=>a.integer_ms.as_ref().map(|c|capability(py,c)).transpose()?,"capability"=>capability(py,&axis_capability(&a))?,"timezone"=>py.None()),
    )
}
fn unit_evidence<'py>(
    py: Python<'py>,
    e: &ras_commander_rust::hdf::units::UnitsEvidence,
) -> PyResult<Bound<'py, PyDict>> {
    let d = evidence_dict(py, "units", e.raw_bytes(), e.capability())?;
    d.set_item("value", e.value())?;
    Ok(d)
}
pub(crate) fn dataset_units<'py>(
    py: Python<'py>,
    e: &ras_commander_rust::hdf::units::UnitsEvidence,
    source: &ras_commander_rust::hdf::units::UnitsSource,
    quantity: &Option<String>,
) -> PyResult<Bound<'py, PyDict>> {
    use ras_commander_rust::hdf::units::UnitsSource as S;
    let attribute = match source {
        S::UnitsAttribute => Some("Units"),
        S::VariableUnits => Some("Variable Units"),
        S::VariablePair => Some("Variable"),
        S::QuantityLabel { attribute } => Some(attribute.as_str()),
        _ => None,
    };
    let d = unit_evidence(py, e)?;
    d.set_item("source_attribute", attribute)?;
    d.set_item("quantity_name", quantity)?;
    Ok(d)
}
#[pyfunction]
fn dataset_unit_evidence<'py>(
    py: Python<'py>,
    path: PathBuf,
    dataset: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let u = py
        .detach(|| ReadOnlyHdfSession::open(path)?.dataset_units(dataset))
        .map_err(crate::reader::err)?;
    dataset_units(py, &u.units, &u.source, &u.quantity_name)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn result_units(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    let u = py
        .detach(|| ReadOnlyHdfSession::open(path)?.result_units(max_bytes))
        .map_err(crate::reader::err)?;
    let variables=u.variables.iter().map(|v|Ok(dict!(py,"family"=>v.family.as_str(),"area"=>&v.area,"variable"=>&v.variable,"dataset"=>&v.dataset,"dataset_path"=>&v.dataset,"units"=>dataset_units(py,&v.units,&v.source,&v.quantity_name)?))).collect::<PyResult<Vec<_>>>()?;
    let systems = u
        .unit_system
        .iter()
        .map(|e| {
            let d = unit_evidence(py, &e.value)?;
            d.set_item("kind", "unit_system")?;
            d.set_item("source", &e.source)?;
            d.set_item("source_attribute", "Units System")?;
            d.set_item("unit_system_kind", e.kind.map(|k| k.as_str()))?;
            Ok(d)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"variables"=>variables,"unit_system"=>systems))
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn mesh_name_diagnostics(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Vec<Bound<'_, PyDict>>> {
    use ras_commander_rust::schema::MeshNameIssue as I;
    let d = py
        .detach(|| ReadOnlyHdfSession::open(path)?.mesh_name_diagnostics(max_bytes))
        .map_err(crate::reader::err)?;
    d.iter().map(|v|Ok(dict!(py,"subject"=>Some(&v.mesh_name),"message"=>None::<String>,"capability"=>None::<String>,"mesh_name"=>&v.mesh_name,"issue"=>match v.issue {I::MissingGroup=>"missing_group",I::ExtraGroup=>"extra_group",I::DuplicateAttributeName=>"duplicate_attribute_name",I::InvalidName=>"invalid_name",_=>"unknown"}))).collect()
}
pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(unsteady_time_axis, m)?)?;
    m.add_function(wrap_pyfunction!(unsteady_row_times, m)?)?;
    m.add_function(wrap_pyfunction!(result_units, m)?)?;
    m.add_function(wrap_pyfunction!(dataset_unit_evidence, m)?)?;
    m.add_function(wrap_pyfunction!(mesh_name_diagnostics, m)?)?;

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

/// Shared envelope; None means the engine did not provide that evidence.
pub(crate) fn diagnostic<'py>(
    py: Python<'py>,
    subject: Option<&str>,
    message: Option<&str>,
    c: Option<&Capability>,
) -> PyResult<Bound<'py, PyDict>> {
    Ok(
        dict!(py,"subject"=>subject,"message"=>message,"capability"=>capability(py,c.unwrap_or(&Capability::unavailable("engine diagnostic carries no capability")))?),
    )
}
