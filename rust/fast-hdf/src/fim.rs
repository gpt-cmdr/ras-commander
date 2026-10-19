//! FIM typed reads. Engine owns all schema and identity decisions.
use crate::domain::{attribute_type, capability, identity, typed_attribute_dict};
use numpy::IntoPyArray;
use pyo3::{
    exceptions::PyValueError,
    prelude::*,
    types::{PyBytes, PyDict},
};
use ras_commander_rust::hdf::lines::GEOMETRY_FAMILIES;
use ras_commander_rust::hdf::mesh_geometry::{ExactCompound, MESH_GEOMETRY_FIELDS};
use ras_commander_rust::hdf::mesh_results::{MeshResultInventory, MeshResultSelection};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, Slice};
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
const _: () = assert!(ras_commander_rust::hdf::DEFAULT_MAX_BYTES == 67108864);
pub(crate) fn slice(r: (u64, u64, u64)) -> Slice {
    Slice::new(r.0, r.1, r.2)
}
pub(crate) fn inventory<'py>(
    py: Python<'py>,
    i: MeshResultInventory,
) -> PyResult<Bound<'py, PyDict>> {
    let vars=i.variables.into_iter().map(|v| {
 let attrs=v.attributes.iter().map(|a|typed_attribute_dict(py,a)).collect::<PyResult<Vec<_>>>()?;
 Ok(dict!(py,"name"=>v.name,"path"=>v.path,"domain"=>v.domain.as_str(),"shape"=>v.shape,"kind"=>v.kind.map(crate::reader::numeric_kind_name),"dtype"=>v.kind.and_then(crate::reader::numpy),"chunks"=>v.chunks,"capability"=>capability(py,&v.capability)?,"attributes"=>attrs,"time_of_extreme_row"=>v.time_of_extreme_row))
 }).collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"group"=>i.group,"capability"=>capability(py,&i.capability)?,"variables"=>vars))
}
pub(crate) fn selection<'py>(
    py: Python<'py>,
    s: MeshResultSelection,
) -> PyResult<Bound<'py, PyDict>> {
    Ok(
        dict!(py,"identity"=>identity(py,&s.id)?,"elements"=>s.elements.into_pyarray(py),"rows"=>(s.rows.start,s.rows.end,s.rows.step),"values"=>crate::reader::array(py,s.values)?),
    )
}

#[pyfunction]
#[pyo3(signature=(path,area,max_bytes=67108864))]
fn mesh_summary_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let i = py
        .detach(|| ReadOnlyHdfSession::open(path)?.mesh_summary_inventory(area, max_bytes))
        .map_err(crate::reader::err)?;
    inventory(py, i)
}

#[pyfunction]
#[pyo3(signature=(path,area,max_bytes=67108864))]
fn mesh_series_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let i = py
        .detach(|| ReadOnlyHdfSession::open(path)?.mesh_series_inventory(area, max_bytes))
        .map_err(crate::reader::err)?;
    inventory(py, i)
}

#[pyfunction]
#[pyo3(signature=(path,area,max_bytes=67108864))]
fn mesh_boundary_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let i = py
        .detach(|| ReadOnlyHdfSession::open(path)?.mesh_boundary_inventory(area, max_bytes))
        .map_err(crate::reader::err)?;
    inventory(py, i)
}

#[pyfunction]
#[pyo3(signature=(path,area,variable,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
fn read_mesh_summary<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    variable: &str,
    elements: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_mesh_summary(
                area,
                variable,
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    selection(py, r)
}

#[pyfunction]
#[pyo3(signature=(path,area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
#[allow(clippy::too_many_arguments)]
fn read_mesh_series<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    variable: &str,
    rows: (u64, u64, u64),
    elements: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_mesh_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    selection(py, r)
}

#[pyfunction]
#[pyo3(signature=(path,area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
#[allow(clippy::too_many_arguments)]
fn read_mesh_boundary_series<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    variable: &str,
    rows: (u64, u64, u64),
    elements: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_mesh_boundary_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    selection(py, r)
}

#[pyfunction]
#[pyo3(signature=(path,area,variable,rows,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
#[allow(clippy::too_many_arguments)]
fn reduce_mesh_series<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    variable: &str,
    rows: (u64, u64, u64),
    elements: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.reduce_mesh_series(
                area,
                variable,
                slice(rows),
                elements.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    Ok(
        dict!(py,"identity"=>identity(py,&r.id)?,"elements"=>r.elements.into_pyarray(py),"values"=>crate::reader::array(py,r.values)?,"time_indices"=>r.time_indices.into_pyarray(py)),
    )
}

#[pyfunction]
#[pyo3(signature=(path,area,field,rows=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
fn read_mesh_geometry<'py>(
    py: Python<'py>,
    path: PathBuf,
    area: &str,
    field: &str,
    rows: Option<(u64, u64, u64)>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let field = MESH_GEOMETRY_FIELDS
        .iter()
        .find(|f| f.as_str() == field)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown mesh geometry field"))?;
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_mesh_geometry(
                area,
                field,
                rows.map(slice),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    crate::reader::array(py, r)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn run_summary(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    let r = py
        .detach(|| ReadOnlyHdfSession::open(path)?.run_summary(max_bytes))
        .map_err(crate::reader::err)?;
    let d = dict!(py,"capability"=>capability(py,r.capability())?,"value"=>py.None());
    if let Some(groups) = r.value() {
        let values=groups.iter().map(|g|Ok(dict!(py,"path"=>&g.path,"attributes"=>g.attributes.iter().map(|a|typed_attribute_dict(py,a)).collect::<PyResult<Vec<_>>>()?))).collect::<PyResult<Vec<_>>>()?;
        d.set_item("value", values)?;
    }
    Ok(d)
}
fn compound<'py>(py: Python<'py>, t: &ExactCompound) -> PyResult<Bound<'py, PyDict>> {
    let columns=t.table.columns.iter().map(|c| {
 let d=dict!(py,"name"=>&c.name,"byte_offset"=>c.byte_offset,"attribute_type"=>attribute_type(py,&c.attribute_type)?,"datatype_label"=>&c.datatype_label,"capability"=>capability(py,&c.value.capability())?);
 use ras_commander_rust::hdf::metadata::MetadataValue as V;
 match &c.value { V::Signed(v)=>d.set_item("value",v)?,V::Unsigned(v)=>d.set_item("value",v)?,V::Float(v)=>d.set_item("value",v)?,V::Strings(v)=>d.set_item("value",v)?,_=>d.set_item("value",py.None())? };Ok(d)
 }).collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"shape"=>&t.table.shape,"raw_bytes"=>PyBytes::new(py,&t.raw_bytes),"columns"=>columns),
    )
}
#[pyfunction]
#[pyo3(signature=(path,family,max_bytes=67108864))]
fn geometry_family<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let family = GEOMETRY_FAMILIES
        .iter()
        .find(|f| f.as_str() == family)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown geometry family"))?;
    let r = py
        .detach(|| ReadOnlyHdfSession::open(path)?.geometry_family(family, max_bytes))
        .map_err(crate::reader::err)?;
    let d = dict!(py,"capability"=>capability(py,r.capability())?,"value"=>py.None());
    let v = r.into_value();
    if let Some(g) = v {
        let features=g.features.iter().map(|f|Ok(dict!(py,"identity"=>identity(py,&f.id)?,"name"=>&f.name,"name_capability"=>capability(py,&f.name_capability)?,"point_range"=>(f.point_range.start,f.point_range.end),"parts"=>f.parts.iter().map(|p|(p.start,p.end)).collect::<Vec<_>>()))).collect::<PyResult<Vec<_>>>()?;
        let tables = g
            .tables
            .iter()
            .map(|(n, t)| Ok((n, compound(py, t)?)))
            .collect::<PyResult<Vec<_>>>()?;
        let profiles = g
            .terrain_profiles
            .into_iter()
            .map(|(n, a)| Ok((n, crate::reader::array(py, a)?)))
            .collect::<PyResult<Vec<_>>>()?;
        d.set_item("value",dict!(py,"family"=>g.family.as_str(),"attributes"=>compound(py,&g.attributes)?,"info"=>crate::reader::array(py,g.info)?,"parts"=>crate::reader::array(py,g.parts)?,"points"=>crate::reader::array(py,g.points)?,"features"=>features,"tables"=>tables,"terrain_profiles"=>profiles))?;
    }
    Ok(d)
}
#[pyfunction]
#[pyo3(signature=(path,other,area,*,metadata_max_bytes=67108864,max_bytes=67108864))]
fn compare_mesh_identity<'py>(
    py: Python<'py>,
    path: PathBuf,
    other: PathBuf,
    area: &str,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.compare_mesh_identity(
                &ReadOnlyHdfSession::open(other)?,
                area,
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    let mismatch = r
        .first_mismatch
        .map(|m| {
            Ok::<_, PyErr>(
                dict!(py,"field"=>m.field.as_str(),"kind"=>m.kind.as_str(),"element"=>m.element),
            )
        })
        .transpose()?;
    Ok(
        dict!(py,"left"=>identity(py,&r.left)?,"right"=>identity(py,&r.right)?,"first_mismatch"=>mismatch),
    )
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn layer_inventory(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Vec<Bound<'_, PyDict>>> {
    let r = py
        .detach(|| ReadOnlyHdfSession::open(path)?.layer_inventory(max_bytes))
        .map_err(crate::reader::err)?;
    r.into_iter().map(|l| {
 let fields=l.fields.iter().map(|f|Ok(dict!(py,"name"=>&f.name,"dataset"=>&f.dataset,"numeric_kind"=>f.numeric_kind.map(crate::reader::numeric_kind_name),"row_count"=>f.row_count,"capability"=>capability(py,&f.capability)?))).collect::<PyResult<Vec<_>>>()?;
 Ok(dict!(py,"family"=>l.family,"area"=>l.area,"name"=>l.name,"identity"=>l.identity.as_ref().map(|i|identity(py,i)).transpose()?,"element_domain"=>l.element_domain,"geometry_type"=>l.geometry_type,"row_count"=>l.row_count,"fields"=>fields,"capability"=>capability(py,&l.capability)?))
 }).collect()
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(mesh_summary_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(mesh_series_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(mesh_boundary_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_mesh_summary, m)?)?;
    m.add_function(wrap_pyfunction!(read_mesh_series, m)?)?;
    m.add_function(wrap_pyfunction!(read_mesh_boundary_series, m)?)?;
    m.add_function(wrap_pyfunction!(reduce_mesh_series, m)?)?;
    m.add_function(wrap_pyfunction!(read_mesh_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(run_summary, m)?)?;
    m.add_function(wrap_pyfunction!(geometry_family, m)?)?;
    m.add_function(wrap_pyfunction!(compare_mesh_identity, m)?)?;
    m.add_function(wrap_pyfunction!(layer_inventory, m)?)?;
    Ok(())
}
