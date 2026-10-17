use freestiler_core::{
    geo_types::{Coord, LineString, Polygon},
    tiler::{Feature, Geometry, LayerData, PropertyValue},
};
use numpy::{PyReadonlyArray1, PyReadonlyArray2};
use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyBool, PyDict, PyInt, PyList};
use std::collections::HashSet;

fn required<'py>(d: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    d.get_item(key)?
        .ok_or_else(|| PyValueError::new_err(format!("missing layer key: {key}")))
}
fn property(value: &Bound<'_, PyAny>) -> PyResult<PropertyValue> {
    if value.is_none() {
        return Ok(PropertyValue::Null);
    }
    if value.is_instance_of::<PyBool>() {
        return Ok(PropertyValue::Bool(value.extract()?));
    }
    if value.is_instance_of::<PyInt>() {
        return Ok(PropertyValue::Int(value.extract::<i64>()?));
    }
    if let Ok(v) = value.extract::<String>() {
        return Ok(PropertyValue::String(v));
    }
    if let Ok(v) = value.extract::<f64>() {
        return Ok(if v.is_finite() {
            PropertyValue::Double(v)
        } else {
            PropertyValue::Null
        });
    }
    Err(PyValueError::new_err(
        "properties must be strings, signed 64-bit integers, floats, bools or None",
    ))
}

/// Write MVT PMTiles directly from packed WGS84 polygon buffers.
/// Caller stages the destination for atomic publication.
#[pyfunction]
#[pyo3(signature=(layers,output,min_zoom,max_zoom,threads=None))]
pub fn write_pmtiles(
    py: Python<'_>,
    layers: &Bound<'_, PyList>,
    output: &str,
    min_zoom: u8,
    max_zoom: u8,
    threads: Option<usize>,
) -> PyResult<()> {
    if min_zoom > max_zoom || max_zoom > 22 {
        return Err(PyValueError::new_err(
            "zoom range must satisfy 0 <= min_zoom <= max_zoom <= 22",
        ));
    }
    let mut names = HashSet::new();
    let mut parsed = Vec::new();
    for obj in layers.iter() {
        let d = obj.cast::<PyDict>()?;
        let name: String = required(d, "name")?.extract()?;
        if name.is_empty() || !names.insert(name.clone()) {
            return Err(PyValueError::new_err(
                "layer names must be nonempty and unique",
            ));
        }
        let coords_obj = required(d, "coordinates")?;
        let offsets_obj = required(d, "offsets")?;
        let ids_obj = required(d, "cell_ids")?;
        let coords: PyReadonlyArray2<f64> = coords_obj.extract()?;
        let offsets: PyReadonlyArray1<i64> = offsets_obj.extract()?;
        let ids: PyReadonlyArray1<i64> = ids_obj.extract()?;
        let coords = coords.as_array();
        let offsets = offsets.as_array();
        let ids = ids.as_array();
        if coords.ncols() != 2
            || offsets.len() != ids.len() + 1
            || offsets[0] != 0
            || offsets[offsets.len() - 1] != coords.nrows() as i64
        {
            return Err(PyValueError::new_err(format!(
                "{name}: invalid packed polygon dimensions"
            )));
        }
        if coords.rows().into_iter().any(|p| {
            !p[0].is_finite()
                || !p[1].is_finite()
                || p[0].abs() > 180.
                || p[1].abs() > 85.0511287798066
        }) {
            return Err(PyValueError::new_err(format!("{name}: coordinates must be finite WGS84 lon/lat within Web Mercator latitude limits")));
        }
        let properties = required(d, "properties")?;
        let properties = properties.cast::<PyDict>()?;
        let mut prop_names = Vec::new();
        let mut columns = Vec::new();
        let mut prop_types = Vec::new();
        for (key, values) in properties.iter() {
            prop_names.push(key.extract::<String>()?);
            let values = values.cast::<PyList>()?;
            if values.len() != ids.len() {
                return Err(PyValueError::new_err(format!(
                    "{name}: property length differs from polygon count"
                )));
            }
            let values: Vec<_> = values
                .iter()
                .map(|v| property(&v))
                .collect::<PyResult<_>>()?;
            let kind = values
                .iter()
                .find_map(|v| match v {
                    PropertyValue::String(_) => Some("String"),
                    PropertyValue::Bool(_) => Some("Boolean"),
                    PropertyValue::Null => None,
                    _ => Some("Number"),
                })
                .unwrap_or("String");
            prop_types.push(kind.to_string());
            columns.push(values);
        }
        let mut features = Vec::with_capacity(ids.len());
        let mut seen = HashSet::new();
        for i in 0..ids.len() {
            let id = u64::try_from(ids[i])
                .map_err(|_| PyValueError::new_err("cell IDs must be nonnegative"))?;
            if !seen.insert(id) {
                return Err(PyValueError::new_err(format!(
                    "{name}: duplicate feature ID {id}"
                )));
            }
            let start = usize::try_from(offsets[i])
                .map_err(|_| PyValueError::new_err("negative ring offset"))?;
            let end = usize::try_from(offsets[i + 1])
                .map_err(|_| PyValueError::new_err("negative ring offset"))?;
            if end > coords.nrows() || start > end || end - start < 4 {
                return Err(PyValueError::new_err(format!(
                    "{name}: invalid ring span at feature {id}"
                )));
            }
            if coords.row(start) != coords.row(end - 1) {
                return Err(PyValueError::new_err(format!(
                    "{name}: unclosed ring at feature {id}"
                )));
            }
            let ring = LineString::new(
                (start..end)
                    .map(|r| Coord {
                        x: coords[[r, 0]],
                        y: coords[[r, 1]],
                    })
                    .collect(),
            );
            crate::mesh::validate_ring(ring.0.iter().map(|c| [c.x, c.y])).map_err(|error| {
                crate::TopologyError::new_err(format!("{name}: feature {id}: {error}"))
            })?;
            features.push(Feature {
                id: Some(id),
                geometry: Geometry::Polygon(Polygon::new(ring, vec![])),
                properties: columns.iter().map(|c| c[i].clone()).collect(),
            });
        }
        if !features.is_empty() {
            parsed.push(LayerData {
                name,
                features,
                prop_names,
                prop_types,
                min_zoom,
                max_zoom,
            });
        }
    }
    if parsed.is_empty() {
        return Err(PyValueError::new_err(
            "at least one nonempty layer is required",
        ));
    }
    let pool = crate::pool(threads)?;
    py.detach(|| pool.install(|| crate::tile_engine::write(&parsed, output, min_zoom, max_zoom)))
        .map_err(PyOSError::new_err)
}
