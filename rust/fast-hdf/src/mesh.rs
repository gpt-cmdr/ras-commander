//! Owned NumPy conversion and error policy around the engine topology API.
use ndarray::Array2;
use numpy::{IntoPyArray, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use ras_commander_rust::mesh::{GeometryPolicy, OmissionKind, Topology};
/// Assemble simple cell boundary rings, retaining every face perimeter vertex.
#[pyfunction]
#[pyo3(signature=(face_points,face_endpoints,face_perimeter_info,face_perimeter_values,cell_face_info,cell_face_values,threads=None,*,strict=true,return_diagnostics=false))]
#[allow(clippy::too_many_arguments)] // Six independent HDF arrays form the binding contract.
pub fn assemble_cells<'py>(
    py: Python<'py>,
    face_points: PyReadonlyArray2<'py, f64>,
    face_endpoints: PyReadonlyArray2<'py, i64>,
    face_perimeter_info: PyReadonlyArray2<'py, i64>,
    face_perimeter_values: PyReadonlyArray2<'py, f64>,
    cell_face_info: PyReadonlyArray2<'py, i64>,
    cell_face_values: PyReadonlyArray2<'py, i64>,
    threads: Option<usize>,
    strict: bool,
    return_diagnostics: bool,
) -> PyResult<Bound<'py, PyAny>> {
    crate::panic_guard::guard(|| {
        // Own buffers before releasing Python: callers may mutate original arrays
        // from another thread while this operation runs.
        let top = Topology::new(
            face_points.as_array().to_owned(),
            face_endpoints.as_array().to_owned(),
            face_perimeter_info.as_array().to_owned(),
            face_perimeter_values.as_array().to_owned(),
            cell_face_info.as_array().to_owned(),
            cell_face_values.as_array().to_owned(),
        );
        let threads = crate::reader::threads(threads)?;
        let policy = if strict {
            GeometryPolicy::Strict
        } else {
            GeometryPolicy::QuarantineInvalid
        };
        let packed = py
            .detach(|| top.assemble(policy, threads))
            .map_err(crate::reader::err)?;
        let coords = packed.coordinates.into_iter().flatten().collect::<Vec<_>>();
        let offsets = packed
            .offsets
            .into_iter()
            .map(|n| {
                i64::try_from(n).map_err(|_| PyValueError::new_err("coordinate count overflow"))
            })
            .collect::<PyResult<Vec<_>>>()?;
        let ids = packed.cell_ids;
        // The Python adapter owns canonical no_polygon/boundary_only records.
        // Preserve this API's historical invalid-geometry-only diagnostics.
        let diagnostics = packed
            .diagnostics
            .into_iter()
            .filter(|d| d.kind == OmissionKind::InvalidGeometry)
            .map(|d| (d.cell_id, "invalid_geometry", d.reason))
            .collect::<Vec<_>>();
        let coords = Array2::from_shape_vec((coords.len() / 2, 2), coords)
            .map_err(|e| PyValueError::new_err(e.to_string()))?;
        let arrays = (
            coords.into_pyarray(py),
            offsets.into_pyarray(py),
            ids.into_pyarray(py),
        );
        if return_diagnostics {
            let diagnostics = diagnostic_records(py, diagnostics)?;
            Ok((arrays.0, arrays.1, arrays.2, diagnostics)
                .into_pyobject(py)?
                .into_any())
        } else {
            Ok(arrays.into_pyobject(py)?.into_any())
        }
    })
}

pub(crate) fn diagnostic_records<'py>(
    py: Python<'py>,
    records: Vec<(i64, &str, String)>,
) -> PyResult<Vec<Bound<'py, pyo3::types::PyDict>>> {
    records
        .into_iter()
        .map(|(cell, kind, reason)| {
            let c = ras_commander_rust::Capability::corrupt(&reason);
            let d =
                crate::domain::diagnostic(py, Some(&cell.to_string()), Some(&reason), Some(&c))?;
            d.set_item("cell_id", cell)?;
            d.set_item("kind", kind)?;
            Ok(d)
        })
        .collect()
}
