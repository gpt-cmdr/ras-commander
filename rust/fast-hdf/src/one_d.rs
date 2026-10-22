//! Wave 2 1D typed reads (engine API 7). Engine owns schema, identity and layout decisions;
//! this module only converts: stored kinds stay stored kinds, compounds keep raw bytes.
use crate::domain::{capability, dataset_units, identity, typed_attribute_dict};
use crate::fim::{compound, slice};
use pyo3::{exceptions::PyValueError, prelude::*, types::PyDict};
use ras_commander_rust::hdf::structures::ColumnLabel;
use ras_commander_rust::hdf::structures_1d::{
    GeometryGroupData, OneDGeometryGroup, OneDStructureKind, ONE_D_STRUCTURE_KINDS,
};
use ras_commander_rust::hdf::xs_geometry::{
    OneDLineFamily, OneDPointData, XsGeometryField, XsGeometryValues, ONE_D_LINE_FAMILIES,
    XS_GEOMETRY_FIELDS,
};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, ResultMode};
use ras_commander_rust::Reported;
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }

fn mode(name: &str) -> PyResult<ResultMode> {
    match name {
        "steady" => Ok(ResultMode::Steady),
        "unsteady" => Ok(ResultMode::Unsteady),
        _ => Err(PyValueError::new_err("mode must be steady or unsteady")),
    }
}
fn field(name: &str) -> PyResult<XsGeometryField> {
    XS_GEOMETRY_FIELDS
        .iter()
        .find(|f| f.as_str() == name)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown cross-section geometry field"))
}
fn line_family(name: &str) -> PyResult<OneDLineFamily> {
    ONE_D_LINE_FAMILIES
        .iter()
        .find(|f| f.as_str() == name)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown 1D line family"))
}
fn structure_kind(name: &str) -> PyResult<OneDStructureKind> {
    ONE_D_STRUCTURE_KINDS
        .iter()
        .find(|k| k.as_str() == name)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown 1D structure kind"))
}
fn geometry_group(name: &str) -> PyResult<OneDGeometryGroup> {
    [
        OneDGeometryGroup::Structures,
        OneDGeometryGroup::PumpStations,
        OneDGeometryGroup::StorageAreas,
    ]
    .into_iter()
    .find(|g| g.as_str() == name)
    .ok_or_else(|| PyValueError::new_err("unknown 1D geometry group"))
}
fn label_list<'py>(py: Python<'py>, l: &[ColumnLabel]) -> PyResult<Vec<Bound<'py, PyDict>>> {
    l.iter()
        .map(|l| Ok(dict!(py,"name"=>&l.name,"unit"=>&l.unit)))
        .collect()
}
fn labels<'py>(py: Python<'py>, r: &Reported<Vec<ColumnLabel>>) -> PyResult<Bound<'py, PyDict>> {
    let value = r.value().map(|v| label_list(py, v)).transpose()?;
    Ok(dict!(py,"capability"=>capability(py,r.capability())?,"value"=>value))
}
fn text<'py>(py: Python<'py>, r: &Reported<String>) -> PyResult<Bound<'py, PyDict>> {
    let d = crate::domain::evidence_dict(py, "text", r.raw_bytes(), r.capability())?;
    d.set_item("value", r.value())?;
    Ok(d)
}
fn attrs<'py>(
    py: Python<'py>,
    a: &[ras_commander_rust::hdf::metadata::TypedAttribute],
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    a.iter().map(|a| typed_attribute_dict(py, a)).collect()
}
/// Shared envelope for engine `Reported<T>` results: capability plus optional value.
fn reported<'py, T>(
    py: Python<'py>,
    r: Reported<T>,
    convert: impl FnOnce(T) -> PyResult<Bound<'py, PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let d = dict!(py,"capability"=>capability(py,r.capability())?,"value"=>py.None());
    if let Some(v) = r.into_value() {
        d.set_item("value", convert(v)?)?;
    }
    Ok(d)
}
fn points<'py>(py: Python<'py>, p: OneDPointData) -> PyResult<Bound<'py, PyAny>> {
    let ids = p
        .features
        .iter()
        .map(|i| identity(py, i))
        .collect::<PyResult<Vec<_>>>()?;
    let names = p
        .names
        .iter()
        .map(|n| text(py, n))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"group"=>&p.group,"attributes"=>compound(py,&p.attributes)?,"points"=>crate::reader::array(py,p.points)?,"features"=>ids,"names"=>names)
            .into_any(),
    )
}
fn group_data<'py>(py: Python<'py>, g: GeometryGroupData) -> PyResult<Bound<'py, PyDict>> {
    let tables = g
        .tables
        .iter()
        .map(|(n, t)| Ok((n, compound(py, t)?)))
        .collect::<PyResult<Vec<_>>>()?;
    let arrays = g
        .arrays
        .into_iter()
        .map(|(n, a)| Ok((n, crate::reader::array(py, a)?)))
        .collect::<PyResult<Vec<_>>>()?;
    let group_attributes = g
        .group_attributes
        .iter()
        .map(|(n, a)| Ok((n, attrs(py, a)?)))
        .collect::<PyResult<Vec<_>>>()?;
    let unsupported = g
        .unsupported
        .iter()
        .map(|(n, c)| Ok((n, capability(py, c)?)))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"group"=>&g.group,"tables"=>tables,"arrays"=>arrays,"group_attributes"=>group_attributes,"unsupported"=>unsupported),
    )
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn xs_geometry_inventory(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let i = py
            .detach(|| ReadOnlyHdfSession::open(path)?.xs_geometry_inventory(max_bytes))
            .map_err(crate::reader::err)?;
        let fields=i.fields.iter().map(|f| Ok(dict!(py,"field"=>f.field.as_str(),"info_path"=>&f.info_path,"values_path"=>&f.values_path,"info_shape"=>&f.info_shape,"values_shape"=>&f.values_shape,"info_kind"=>f.info_kind.map(crate::reader::numeric_kind_name),"info_dtype"=>f.info_kind.and_then(crate::reader::numpy),"values_kind"=>f.values_kind.map(crate::reader::numeric_kind_name),"values_dtype"=>f.values_kind.and_then(crate::reader::numpy),"compound"=>f.compound,"identity_table"=>&f.identity_table,"records_are_sections"=>f.records_are_sections,"section_records"=>f.section_records,"labels"=>labels(py,&f.labels)?,"info_attributes"=>attrs(py,&f.info_attributes)?,"values_attributes"=>attrs(py,&f.values_attributes)?,"capability"=>capability(py,&f.capability)?))).collect::<PyResult<Vec<_>>>()?;
        let unqualified = i
            .unqualified
            .iter()
            .map(|(n, c)| Ok((n, capability(py, c)?)))
            .collect::<PyResult<Vec<_>>>()?;
        let attributes = compound(py, &i.attributes)?;
        Ok(
            dict!(py,"geometry"=>crate::domain::cross_section_geometry(py,i.geometry)?,"attributes"=>attributes,"fields"=>fields,"unqualified"=>unqualified),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,field,records=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
fn read_xs_geometry<'py>(
    py: Python<'py>,
    path: PathBuf,
    field: &str,
    records: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let f = self::field(field)?;
        let r = py
            .detach(|| {
                ReadOnlyHdfSession::open(path)?.read_xs_geometry(
                    f,
                    records.as_deref(),
                    metadata_max_bytes,
                    max_bytes,
                )
            })
            .map_err(crate::reader::err)?;
        let recs=r.records.iter().map(|x| Ok(dict!(py,"identity"=>identity(py,&x.id)?,"stored_rows"=>(x.stored_rows.start,x.stored_rows.end),"offset"=>x.offset))).collect::<PyResult<Vec<_>>>()?;
        let (kind, values) = match r.values {
            XsGeometryValues::Numeric(a) => ("numeric", crate::reader::array(py, a)?),
            XsGeometryValues::Compound(c) => ("compound", compound(py, &c)?.into_any()),
            _ => {
                return Err(crate::UnsupportedError::new_err(
                    "unknown cross-section geometry value encoding",
                ))
            }
        };
        Ok(
            dict!(py,"field"=>r.field.as_str(),"info_path"=>&r.info_path,"values_path"=>&r.values_path,"info"=>crate::reader::array(py,r.info)?,"values_kind"=>kind,"values"=>values,"records"=>recs,"labels"=>labels(py,&r.labels)?),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,family,max_bytes=67108864))]
fn one_d_line_family<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let f = line_family(family)?;
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.one_d_line_family(f, max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |g| {
            let features=g.features.iter().map(|x| Ok(dict!(py,"identity"=>identity(py,&x.id)?,"point_range"=>(x.point_range.start,x.point_range.end),"parts"=>x.parts.iter().map(|p|(p.start,p.end)).collect::<Vec<_>>()))).collect::<PyResult<Vec<_>>>()?;
            let attributes = g.attributes.as_ref().map(|a| compound(py, a)).transpose()?;
            Ok(dict!(py,"family"=>g.family.as_str(),"group_path"=>g.family.group_path(),"prefix"=>g.family.prefix(),"attributes"=>attributes,"info"=>crate::reader::array(py,g.info)?,"parts"=>crate::reader::array(py,g.parts)?,"points"=>crate::reader::array(py,g.points)?,"features"=>features,"points_attributes"=>attrs(py,&g.points_attributes)?).into_any())
        })
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn river_reaches(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.river_reaches(max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |v| {
            let rows=v.iter().map(|x| Ok(dict!(py,"identity"=>identity(py,&x.id)?,"river"=>&x.river,"reach"=>&x.reach,"upstream_type"=>text(py,&x.upstream_type)?,"upstream_name"=>text(py,&x.upstream_name)?,"downstream_type"=>text(py,&x.downstream_type)?,"downstream_name"=>text(py,&x.downstream_name)?))).collect::<PyResult<Vec<_>>>()?;
            Ok(pyo3::types::PyList::new(py, rows)?.into_any())
        })
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn river_junctions(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.river_junctions(max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |p| points(py, p))
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn pump_stations(py: Python<'_>, path: PathBuf, max_bytes: usize) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.pump_stations(max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |p| points(py, p))
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn xs_interpolation_surfaces(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.xs_interpolation_surfaces(max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |s| {
            let surfaces=s.surfaces.iter().map(|x| Ok(dict!(py,"identity"=>identity(py,&x.id)?,"point_range"=>(x.point_range.start,x.point_range.end),"triangle_range"=>(x.triangle_range.start,x.triangle_range.end)))).collect::<PyResult<Vec<_>>>()?;
            let per_surface = s
                .per_surface
                .into_iter()
                .map(|(n, a)| Ok((n, crate::reader::array(py, a)?)))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(dict!(py,"info"=>crate::reader::array(py,s.info)?,"points"=>crate::reader::array(py,s.points)?,"triangles"=>crate::reader::array(py,s.triangles)?,"per_surface"=>per_surface,"surfaces"=>surfaces).into_any())
        })
    })
}

#[pyfunction]
#[pyo3(signature=(path,mode,max_bytes=67108864))]
fn xs_result_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    mode: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let m = self::mode(mode)?;
        let i = py
            .detach(|| ReadOnlyHdfSession::open(path)?.xs_result_inventory(m, max_bytes))
            .map_err(crate::reader::err)?;
        let vars=i.variables.iter().map(|v| Ok(dict!(py,"name"=>&v.name,"path"=>&v.path,"domain"=>v.domain.as_str(),"shape"=>&v.shape,"kind"=>v.kind.map(crate::reader::numeric_kind_name),"dtype"=>v.kind.and_then(crate::reader::numpy),"chunks"=>&v.chunks,"capability"=>capability(py,&v.capability)?,"attributes"=>attrs(py,&v.attributes)?,"units"=>dataset_units(py,&v.units.units,&v.units.source,&v.units.quantity_name)?,"labels"=>labels(py,&v.labels)?))).collect::<PyResult<Vec<_>>>()?;
        let sections = i
            .sections
            .iter()
            .map(|s| identity(py, s))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(
            dict!(py,"mode"=>i.mode.as_str(),"group"=>&i.group,"capability"=>capability(py,&i.capability)?,"rows"=>i.rows,"sections"=>sections,"variables"=>vars),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,mode,variable,rows,sections=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
#[allow(clippy::too_many_arguments)]
fn read_xs_result<'py>(
    py: Python<'py>,
    path: PathBuf,
    mode: &str,
    variable: &str,
    rows: (u64, u64, u64),
    sections: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let m = self::mode(mode)?;
        let r = py
            .detach(|| {
                ReadOnlyHdfSession::open(path)?.read_xs_result(
                    m,
                    variable,
                    slice(rows),
                    sections.as_deref(),
                    metadata_max_bytes,
                    max_bytes,
                )
            })
            .map_err(crate::reader::err)?;
        let ids = r
            .section_ids
            .iter()
            .map(|s| identity(py, s))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(
            dict!(py,"identity"=>identity(py,&r.id)?,"mode"=>r.mode.as_str(),"variable"=>&r.variable,"rows"=>(r.rows.start,r.rows.end,r.rows.step),"sections"=>&r.sections,"section_ids"=>ids,"values"=>crate::reader::array(py,r.values)?),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,start_ms,end_ms,max_bytes=67108864))]
fn unsteady_row_window(
    py: Python<'_>,
    path: PathBuf,
    start_ms: i64,
    end_ms: i64,
    max_bytes: usize,
) -> PyResult<(u64, u64, u64)> {
    crate::panic_guard::guard(|| {
        let s = py
            .detach(|| {
                ReadOnlyHdfSession::open(path)?.unsteady_row_window(start_ms, end_ms, max_bytes)
            })
            .map_err(crate::reader::err)?;
        Ok((s.start, s.end, s.step))
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn one_d_summary_inventory(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let i = py
            .detach(|| ReadOnlyHdfSession::open(path)?.one_d_summary_inventory(max_bytes))
            .map_err(crate::reader::err)?;
        let vars=i.variables.iter().map(|v| Ok(dict!(py,"family"=>&v.family,"name"=>&v.name,"path"=>&v.path,"shape"=>&v.shape,"kind"=>v.kind.map(crate::reader::numeric_kind_name),"dtype"=>v.kind.and_then(crate::reader::numpy),"chunks"=>&v.chunks,"domain"=>v.domain.as_str(),"element_axis"=>v.element_axis,"capability"=>capability(py,&v.capability)?,"attributes"=>attrs(py,&v.attributes)?,"labels"=>labels(py,&v.labels)?,"row_labels"=>v.row_labels.as_ref().map(|l|label_list(py,l)).transpose()?,"time_of_extreme_rows"=>&v.time_of_extreme_rows))).collect::<PyResult<Vec<_>>>()?;
        Ok(
            dict!(py,"group"=>&i.group,"capability"=>capability(py,&i.capability)?,"variables"=>vars),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,family,name,elements=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
fn read_one_d_summary<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    name: &str,
    elements: Option<Vec<u64>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| {
                ReadOnlyHdfSession::open(path)?.read_one_d_summary(
                    family,
                    name,
                    elements.as_deref(),
                    metadata_max_bytes,
                    max_bytes,
                )
            })
            .map_err(crate::reader::err)?;
        let ids = r
            .element_ids
            .as_ref()
            .map(|v| {
                v.iter()
                    .map(|i| identity(py, i))
                    .collect::<PyResult<Vec<_>>>()
            })
            .transpose()?;
        Ok(
            dict!(py,"identity"=>identity(py,&r.id)?,"family"=>&r.family,"name"=>&r.name,"elements"=>&r.elements,"element_ids"=>ids,"values"=>crate::reader::array(py,r.values)?),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn structure_geometry(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'_, PyDict>> {
    crate::panic_guard::guard(|| {
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.structure_geometry(max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |g| {
            let records=g.records.iter().map(|x| Ok(dict!(py,"identity"=>identity(py,&x.id)?,"structure_type"=>text(py,&x.structure_type)?,"river"=>text(py,&x.river)?,"reach"=>text(py,&x.reach)?,"station"=>text(py,&x.station)?,"connection"=>text(py,&x.connection)?,"node_name"=>text(py,&x.node_name)?,"profile_ranges"=>x.profile_ranges.iter().map(|(n,r)|(n.clone(),(r.start,r.end))).collect::<Vec<_>>()))).collect::<PyResult<Vec<_>>>()?;
            let attributes = compound(py, &g.attributes)?;
            Ok(
            dict!(py,"attributes"=>attributes,"records"=>records,"group"=>group_data(py,g.group)?)
                .into_any(),
        )
        })
    })
}

#[pyfunction]
#[pyo3(signature=(path,group,max_bytes=67108864))]
fn one_d_geometry_group<'py>(
    py: Python<'py>,
    path: PathBuf,
    group: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let g = geometry_group(group)?;
        let r = py
            .detach(|| ReadOnlyHdfSession::open(path)?.one_d_geometry_group(g, max_bytes))
            .map_err(crate::reader::err)?;
        reported(py, r, |d| Ok(group_data(py, d)?.into_any()))
    })
}

#[pyfunction]
#[pyo3(signature=(path,kind,mode,max_bytes=67108864))]
fn one_d_structure_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    kind: &str,
    mode: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    crate::panic_guard::guard(|| {
        let (k, m) = (structure_kind(kind)?, self::mode(mode)?);
        let i = py
            .detach(|| ReadOnlyHdfSession::open(path)?.one_d_structure_inventory(k, m, max_bytes))
            .map_err(crate::reader::err)?;
        let structures = i
            .structures
            .iter()
            .map(|s| crate::structures::descriptor(py, s))
            .collect::<PyResult<Vec<_>>>()?;
        let family = i
            .family_series
            .iter()
            .map(|s| crate::structures::series(py, s))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(
            dict!(py,"kind"=>i.kind.as_str(),"mode"=>i.mode.as_str(),"group"=>&i.group,"rows"=>i.rows,"qualified"=>i.kind.qualified(i.mode),"structures"=>structures,"family_series"=>family),
        )
    })
}

#[pyfunction]
#[pyo3(signature=(path,max_bytes=67108864))]
fn one_d_structure_capabilities(
    py: Python<'_>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Vec<Bound<'_, PyDict>>> {
    crate::panic_guard::guard(|| {
        let c = py
            .detach(|| ReadOnlyHdfSession::open(path)?.one_d_structure_capabilities(max_bytes))
            .map_err(crate::reader::err)?;
        c.iter().map(|c| Ok(dict!(py,"kind"=>c.kind.as_str(),"mode"=>c.mode.as_str(),"group"=>&c.group,"qualified"=>c.kind.qualified(c.mode),"capability"=>capability(py,&c.status)?))).collect()
    })
}

#[pyfunction]
#[pyo3(signature=(path,kind,mode,structure,relative,rows,columns=None,*,metadata_max_bytes=67108864,max_bytes=67108864))]
#[allow(clippy::too_many_arguments)]
fn read_one_d_structure_series<'py>(
    py: Python<'py>,
    path: PathBuf,
    kind: &str,
    mode: &str,
    structure: Option<&str>,
    relative: &str,
    rows: (u64, u64, u64),
    columns: Option<(u64, u64, u64)>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyAny>> {
    crate::panic_guard::guard(|| {
        let (k, m) = (structure_kind(kind)?, self::mode(mode)?);
        let a = py
            .detach(|| {
                ReadOnlyHdfSession::open(path)?.read_one_d_structure_series(
                    k,
                    m,
                    structure,
                    relative,
                    slice(rows),
                    columns.map(slice),
                    metadata_max_bytes,
                    max_bytes,
                )
            })
            .map_err(crate::reader::err)?;
        crate::reader::array(py, a)
    })
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(xs_geometry_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_xs_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(one_d_line_family, m)?)?;
    m.add_function(wrap_pyfunction!(river_reaches, m)?)?;
    m.add_function(wrap_pyfunction!(river_junctions, m)?)?;
    m.add_function(wrap_pyfunction!(xs_interpolation_surfaces, m)?)?;
    m.add_function(wrap_pyfunction!(xs_result_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_xs_result, m)?)?;
    m.add_function(wrap_pyfunction!(unsteady_row_window, m)?)?;
    m.add_function(wrap_pyfunction!(one_d_summary_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_one_d_summary, m)?)?;
    m.add_function(wrap_pyfunction!(structure_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(one_d_geometry_group, m)?)?;
    m.add_function(wrap_pyfunction!(pump_stations, m)?)?;
    m.add_function(wrap_pyfunction!(one_d_structure_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(one_d_structure_capabilities, m)?)?;
    m.add_function(wrap_pyfunction!(read_one_d_structure_series, m)?)?;
    Ok(())
}
