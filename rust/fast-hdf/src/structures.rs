//! Typed structure conversion; all identity/layout decisions remain in the engine.
use pyo3::{
    exceptions::PyValueError,
    prelude::*,
    types::{PyBytes, PyDict},
};
use ras_commander_rust::hdf::structures::{
    ColumnLabelSource as S, ColumnLabels as C, NodePointer, StructureFamilyKind as K,
    StructureSeries,
};
use ras_commander_rust::hdf::{ReadOnlyHdfSession, Slice};
use ras_commander_rust::Capability;
use std::path::PathBuf;
macro_rules! dict { ($py:expr, $($k:expr => $v:expr),* $(,)?) => {{ let d=PyDict::new($py); $(d.set_item($k,$v)?;)* d }}; }
pub(crate) fn family_name(k: K) -> &'static str {
    match k {
        K::Sa2dAreaConnection => "sa2d_area_connection",
        K::LateralStructure => "lateral_structure",
        K::StorageArea => "storage_area",
        _ => "unknown",
    }
}
fn family(name: &str) -> PyResult<K> {
    match name {
        "sa2d_area_connection" => Ok(K::Sa2dAreaConnection),
        "lateral_structure" => Ok(K::LateralStructure),
        "storage_area" => Ok(K::StorageArea),
        _ => Err(PyValueError::new_err(
            "family must be sa2d_area_connection, lateral_structure, or storage_area",
        )),
    }
}
fn columns<'py>(py: Python<'py>, c: &C) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    match c {
        C::Absent => {
            d.set_item("status", "absent")?;
        }
        C::Declared {
            source,
            labels,
            raw_bytes,
        } => {
            d.set_item("status", "declared")?;
            d.set_item(
                "source_attribute",
                match source {
                    S::VariableUnit => "Variable_Unit",
                    S::Connections => "Connections",
                    _ => "unknown",
                },
            )?;
            d.set_item("raw_bytes", PyBytes::new(py, raw_bytes))?;
            d.set_item(
                "labels",
                labels
                    .iter()
                    .map(|l| Ok(dict!(py,"name"=>&l.name,"unit"=>&l.unit)))
                    .collect::<PyResult<Vec<_>>>()?,
            )?;
        }
        C::Unsupported {
            capability,
            raw_bytes,
        }
        | C::Corrupt {
            capability,
            raw_bytes,
        } => {
            d.set_item(
                "status",
                if matches!(c, C::Corrupt { .. }) {
                    "corrupt"
                } else {
                    "unsupported"
                },
            )?;
            d.set_item("capability", crate::domain::capability(py, capability)?)?;
            d.set_item("raw_bytes", PyBytes::new(py, raw_bytes))?;
        }
        _ => {
            d.set_item("status", "unknown")?;
        }
    };
    if let Some(value) = d.get_item("source_attribute")? {
        d.set_item("source", value)?;
    }
    Ok(d)
}
fn series<'py>(py: Python<'py>, s: &StructureSeries) -> PyResult<Bound<'py, PyDict>> {
    Ok(
        dict!(py,"path"=>&s.path,"dataset_path"=>&s.path,"relative"=>&s.relative,"shape"=>&s.shape,"kind"=>s.kind.map(crate::reader::numeric_kind_name),"dtype"=>s.kind.and_then(crate::reader::numpy),"capability"=>crate::domain::capability(py,&s.capability)?,"columns"=>columns(py,&s.columns)?,"units"=>crate::domain::dataset_units(py,&s.units.units,&s.units.source,&s.units.quantity_name)?),
    )
}
#[pyfunction]
#[pyo3(signature=(path,family,max_bytes=67108864))]
fn structure_inventory<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    max_bytes: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let k = self::family(family)?;
    let inv = py
        .detach(|| ReadOnlyHdfSession::open(path)?.structure_inventory(k, max_bytes))
        .map_err(crate::reader::err)?;
    let structures=inv.structures.iter().map(|s| {
        let pointer=match &s.node_pointer {NodePointer::Declared(v)=>dict!(py,"status"=>"declared","value"=>v),NodePointer::Absent=>dict!(py,"status"=>"absent"),NodePointer::Unsupported(c)=>dict!(py,"status"=>"unsupported","capability"=>crate::domain::capability(py,c)?),_=>dict!(py,"status"=>"unknown")};
        let i=&s.identity;
        Ok(dict!(py,"name"=>&s.name,"group"=>&s.group,"node_pointer"=>pointer,"identity"=>dict!(py,"row"=>i.row,"river"=>&i.river,"reach"=>&i.reach,"station"=>&i.station,"connection"=>&i.connection,"upstream"=>&i.upstream,"downstream"=>&i.downstream,"name"=>&i.name),"series"=>s.series.iter().map(|s|series(py,s)).collect::<PyResult<Vec<_>>>()?,"static_datasets"=>&s.static_datasets))
    }).collect::<PyResult<Vec<_>>>()?;
    // Preserve series label evidence as diagnostics without changing the successful inventory status.
    let diagnostics = inv
        .structures
        .iter()
        .flat_map(|s| s.series.iter())
        .chain(inv.family_series.iter())
        .filter_map(|s| match &s.columns {
            C::Unsupported { capability, .. } | C::Corrupt { capability, .. } => {
                Some((s, capability))
            }
            _ => None,
        })
        .map(|(s, c)| {
            let d = crate::domain::diagnostic(py, Some(&s.path), None, Some(c))?;
            d.set_item("path", &s.path)?;
            Ok(d)
        })
        .collect::<PyResult<Vec<_>>>()?;
    Ok(
        dict!(py,"family"=>family_name(inv.kind),"group"=>inv.group,"time_rows"=>inv.time_rows,"capability"=>crate::domain::capability(py,&Capability::Supported)?,"structures"=>structures,"family_series"=>inv.family_series.iter().map(|s|series(py,s)).collect::<PyResult<Vec<_>>>()?,"diagnostics"=>diagnostics),
    )
}
#[pyfunction]
#[pyo3(signature=(path,family,structure,relative,rows,columns,max_bytes=67108864,threads=None,parallel=true))]
#[allow(clippy::too_many_arguments)]
fn read_structure_series<'py>(
    py: Python<'py>,
    path: PathBuf,
    family: &str,
    structure: Option<&str>,
    relative: &str,
    rows: (u64, u64, u64),
    columns: (u64, u64, u64),
    max_bytes: usize,
    threads: Option<usize>,
    parallel: bool,
) -> PyResult<Bound<'py, pyo3::types::PyAny>> {
    let k = self::family(family)?;
    let threads = crate::reader::threads(threads)?;
    let out = py
        .detach(|| {
            ReadOnlyHdfSession::with_options(path, threads, parallel)?.read_structure_series(
                k,
                structure,
                relative,
                Slice::new(rows.0, rows.1, rows.2),
                Slice::new(columns.0, columns.1, columns.2),
                max_bytes,
            )
        })
        .map_err(crate::reader::err)?;
    crate::reader::array(py, out)
}
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(structure_inventory, m)?)?;
    m.add_function(wrap_pyfunction!(read_structure_series, m)?)?;
    Ok(())
}
