//! Wave 3 stored read families (engine API 8): pipes, reference lines/points, breach,
//! plan metadata, land cover/infiltration sidecars, terrain, sediment, encroachments,
//! Event Conditions, steady output and non-Base output blocks. The engine owns family
//! membership, Location-domain qualification and refusals; this module only converts.
//! Numeric values keep their stored dtype, compounds keep exact raw bytes, bitfields
//! keep exact bytes, and strings are the engine's decoded fixed text.
use crate::domain::{capability, identity, typed_attribute_dict};
use crate::fim::{compound, slice};
use pyo3::{
    exceptions::PyValueError,
    prelude::*,
    types::{PyBytes, PyDict},
};
use ras_commander_rust::hdf::environment::{ClassId, ClassificationCatalogue};
use ras_commander_rust::hdf::families::{
    FamilyDataset, FamilyInventory, OutputBlock, ReadFamily, READ_FAMILIES,
};
use ras_commander_rust::hdf::reference_points::ReferencePointGeometry;
use ras_commander_rust::hdf::stored::{StoredDataset, StoredValues};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, Slice};
use ras_commander_rust::Reported;
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }

const DEFAULT: usize = 67108864;

fn family(name: &str) -> PyResult<ReadFamily> {
    READ_FAMILIES
        .iter()
        .find(|f| f.as_str() == name)
        .copied()
        .ok_or_else(|| PyValueError::new_err("unknown read family"))
}
fn slices(s: Option<Vec<(u64, u64, u64)>>) -> Option<Vec<Slice>> {
    s.map(|v| v.into_iter().map(slice).collect())
}
fn stored_dict<'py>(py: Python<'py>, d: &StoredDataset) -> PyResult<Bound<'py, PyDict>> {
    let attrs = d
        .attributes
        .iter()
        .map(|a| typed_attribute_dict(py, a))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,
        "path"=>&d.path,"identity"=>identity(py,&d.id)?,"shape"=>&d.shape,"dataspace"=>d.dataspace.as_str(),
        "kind"=>d.kind.map(crate::reader::numeric_kind_name),
        "dtype"=>d.kind.and_then(crate::reader::numpy),
        "storage"=>&d.storage,"capability"=>capability(py,&d.capability)?,"attributes"=>attrs))
}
fn family_dataset<'py>(py: Python<'py>, d: FamilyDataset) -> PyResult<Bound<'py, PyDict>> {
    let out = stored_dict(py, &d.stored)?;
    let ids = |v: &[ras_commander_rust::hdf::Identity]| {
        v.iter()
            .map(|i| identity(py, i))
            .collect::<PyResult<Vec<_>>>()
    };
    out.set_item("role", &d.role)?;
    out.set_item("domain", &d.domain)?;
    out.set_item("time_group", &d.time_group)?;
    out.set_item("identity_table", &d.identity_table)?;
    out.set_item("locations", ids(&d.locations)?)?;
    out.set_item("names", &d.names)?;
    out.set_item("geometry_locations", ids(&d.geometry_locations)?)?;
    out.set_item(
        "stored_location_ids",
        d.stored_location_ids
            .map(|a| crate::reader::array(py, a))
            .transpose()?,
    )?;
    out.set_item("time_of_extreme_row", d.time_of_extreme_row)?;
    Ok(out)
}
fn inventory<'py>(py: Python<'py>, i: FamilyInventory) -> PyResult<Bound<'py, PyDict>> {
    let groups = i
        .groups
        .iter()
        .map(|g| {
            let attrs = g
                .attributes
                .iter()
                .map(|a| typed_attribute_dict(py, a))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(dict!(py,"path"=>&g.path,"identity"=>identity(py,&g.id)?,"attributes"=>attrs))
        })
        .collect::<PyResult<Vec<_>>>()?;
    let cap = capability(py, &i.capability)?;
    let datasets = i
        .datasets
        .into_iter()
        .map(|d| family_dataset(py, d))
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"family"=>i.family.as_str(),"capability"=>cap,"datasets"=>datasets,"groups"=>groups),
    )
}
/// `{"storage": numeric|strings|compound|bitfield_bytes, ...}`; numeric values keep
/// the stored dtype, compounds/bitfields keep exact stored bytes.
fn values<'py>(py: Python<'py>, v: StoredValues) -> PyResult<Bound<'py, PyDict>> {
    Ok(match v {
        StoredValues::Numeric(a) => {
            dict!(py,"storage"=>"numeric","values"=>crate::reader::array(py,a)?)
        }
        StoredValues::Strings { shape, values } => {
            dict!(py,"storage"=>"strings","shape"=>shape,"values"=>values)
        }
        StoredValues::Compound(c) => {
            dict!(py,"storage"=>"compound","values"=>compound(py,&c)?)
        }
        StoredValues::Bitfield { shape, raw_bytes } => {
            dict!(py,"storage"=>"bitfield_bytes","shape"=>shape,"raw_bytes"=>PyBytes::new(py,&raw_bytes))
        }
        _ => return Err(PyValueError::new_err("unrecognized stored value storage")),
    })
}
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

#[pyfunction]
fn read_families() -> Vec<&'static str> {
    READ_FAMILIES.iter().map(|f| f.as_str()).collect()
}
#[pyfunction]
#[pyo3(signature=(path,family,metadata_max_bytes=DEFAULT))]
fn read_family_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    metadata_max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let f = self::family(family)?;
    let inv = py
        .detach(|| ReadOnlyHdfSession::open(path)?.read_family_inventory(f, metadata_max_bytes))
        .map_err(crate::reader::err)?;
    inventory(py, inv)
}
#[pyfunction]
#[pyo3(signature=(path,family,dataset,slices=None,metadata_max_bytes=DEFAULT,max_bytes=DEFAULT))]
fn read_family_dataset<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    dataset: &str,
    slices: Option<Vec<(u64, u64, u64)>>,
    metadata_max_bytes: usize,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let f = self::family(family)?;
    let s = self::slices(slices);
    let v = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_family_dataset(
                f,
                dataset,
                s.as_deref(),
                metadata_max_bytes,
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    values(py, v)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=DEFAULT))]
fn output_block_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let blocks: Vec<OutputBlock> = py
        .detach(|| ReadOnlyHdfSession::open(path)?.output_block_inventory(max_bytes))
        .map_err(crate::reader::err)?;
    blocks
        .iter()
        .map(|b| {
            let datasets = b
                .datasets
                .iter()
                .map(|d| stored_dict(py, d))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(dict!(py,"name"=>&b.name,"path"=>&b.path,"datasets"=>datasets))
        })
        .collect()
}
#[pyfunction]
#[pyo3(signature=(path,block,relative,slices=None,max_bytes=DEFAULT))]
fn read_output_block<'py>(
    py: Python<'py>,
    path: PathBuf,
    block: &str,
    relative: &str,
    slices: Option<Vec<(u64, u64, u64)>>,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let s = self::slices(slices);
    let v = py
        .detach(|| {
            ReadOnlyHdfSession::open(path)?.read_output_block(
                block,
                relative,
                s.as_deref(),
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    values(py, v)
}
#[pyfunction]
#[pyo3(signature=(path,max_bytes=DEFAULT))]
fn reference_point_geometry<'py>(
    py: Python<'py>,
    path: PathBuf,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let r: Reported<ReferencePointGeometry> = py
        .detach(|| ReadOnlyHdfSession::open(path)?.reference_point_geometry(max_bytes))
        .map_err(crate::reader::err)?;
    reported(py, r, |g| {
        let features = g
            .features
            .iter()
            .map(|f| {
                Ok(
                    dict!(py,"identity"=>identity(py,&f.id)?,"name"=>&f.name,"area"=>&f.area,
                    "cell_index"=>f.cell_index,"point_row"=>f.point_row),
                )
            })
            .collect::<PyResult<Vec<_>>>()?;
        Ok(dict!(py,"attributes"=>compound(py,&g.attributes)?,
            "points"=>crate::reader::array(py,g.points)?,"features"=>features)
        .into_any())
    })
}
#[pyfunction]
#[pyo3(signature=(path,family,max_bytes=DEFAULT))]
fn classification_catalogue<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let f = self::family(family)?;
    let r: Reported<ClassificationCatalogue> = py
        .detach(|| ReadOnlyHdfSession::open(path)?.classification_catalogue(f, max_bytes))
        .map_err(crate::reader::err)?;
    reported(py, r, |c| {
        let entries = c
            .entries
            .iter()
            .map(|e| {
                let pixel: Option<Bound<'py, PyAny>> = match &e.pixel_id {
                    Some(ClassId::Signed(v)) => Some(v.into_pyobject(py)?.into_any()),
                    Some(ClassId::Unsigned(v)) => Some(v.into_pyobject(py)?.into_any()),
                    _ => None,
                };
                let rows = e
                    .variable_rows
                    .iter()
                    .map(|i| identity(py, i))
                    .collect::<PyResult<Vec<_>>>()?;
                Ok(
                    dict!(py,"identity"=>identity(py,&e.id)?,"pixel_id"=>pixel,"name"=>&e.name,
                    "variable_rows"=>rows,"capability"=>capability(py,&e.capability)?),
                )
            })
            .collect::<PyResult<Vec<_>>>()?;
        let unmatched = c
            .unmatched_variables
            .iter()
            .map(|i| identity(py, i))
            .collect::<PyResult<Vec<_>>>()?;
        Ok(
            dict!(py,"layout"=>&c.layout,"entries"=>entries,"unmatched_variables"=>unmatched)
                .into_any(),
        )
    })
}
/// Compact membership index for routing: every dataset of every read family and of
/// every non-Base output block, with storage, shape, dtype and capability only (no
/// attributes). Family-level failures are reported per family, never hidden.
#[pyfunction]
#[pyo3(signature=(path,metadata_max_bytes=DEFAULT))]
fn stored_family_index<'py>(
    py: Python<'py>,
    path: PathBuf,
    metadata_max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    type Row = (
        String,
        String,
        String,
        Vec<u64>,
        Option<&'static str>,
        String,
        Option<String>,
    );
    let (rows, failures, blocks) = py
        .detach(|| -> ras_commander_rust::Result<_> {
            let s = ReadOnlyHdfSession::open(path)?;
            let mut rows: Vec<Row> = Vec::new();
            let mut failures = Vec::new();
            let row = |owner: &str, d: &StoredDataset| -> Row {
                (
                    owner.to_owned(),
                    d.path.clone(),
                    d.storage.clone(),
                    d.shape.clone(),
                    d.kind.and_then(crate::reader::numpy),
                    d.capability.as_str().to_owned(),
                    d.capability.code().map(|c| c.as_str().to_owned()),
                )
            };
            for &f in READ_FAMILIES {
                match s.read_family_inventory(f, metadata_max_bytes) {
                    Ok(inv) => {
                        for d in &inv.datasets {
                            rows.push(row(f.as_str(), &d.stored));
                        }
                    }
                    Err(e) => failures.push((
                        f.as_str(),
                        e.kind.as_str(),
                        e.code.map(|c| c.as_str()),
                        e.to_string(),
                    )),
                }
            }
            let mut blocks = Vec::new();
            match s.output_block_inventory(metadata_max_bytes) {
                Ok(b) => {
                    for block in b {
                        for d in &block.datasets {
                            rows.push(row(&format!("output_block:{}", block.name), d));
                        }
                        blocks.push(block.name);
                    }
                }
                Err(e) => failures.push((
                    "output_blocks",
                    e.kind.as_str(),
                    e.code.map(|c| c.as_str()),
                    e.to_string(),
                )),
            }
            Ok((rows, failures, blocks))
        })
        .map_err(crate::reader::err)?;
    let rows = rows
        .into_iter()
        .map(|(owner, path, storage, shape, dtype, status, code)| {
            Ok(
                dict!(py,"owner"=>owner,"path"=>path,"storage"=>storage,"shape"=>shape,
                "dtype"=>dtype,"status"=>status,"code"=>code),
            )
        })
        .collect::<PyResult<Vec<_>>>()?;
    let failures = failures
        .into_iter()
        .map(|(owner, kind, code, message)| {
            Ok(dict!(py,"owner"=>owner,"kind"=>kind,"code"=>code,"message"=>message))
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(dict!(py,"datasets"=>rows,"failures"=>failures,"output_blocks"=>blocks))
}

pub(crate) fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(read_families, m)?)?;
    m.add_function(wrap_pyfunction!(read_family_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_family_dataset, m)?)?;
    m.add_function(wrap_pyfunction!(output_block_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_output_block, m)?)?;
    m.add_function(wrap_pyfunction!(reference_point_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(classification_catalogue, m)?)?;
    m.add_function(wrap_pyfunction!(stored_family_index, m)?)?;
    Ok(())
}
