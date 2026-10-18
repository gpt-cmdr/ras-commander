use freestiler_core::{
    geo_types::{Coord, LineString, MultiPolygon, Polygon},
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

/// Every level is a CSR-style offset array, including a terminal sentinel.
/// Reject empty components before indexing; an entirely empty layer uses [0].
fn spans(d: &Bound<'_, PyDict>, key: &str, children: usize) -> PyResult<Vec<usize>> {
    let obj = required(d, key)?;
    let values: PyReadonlyArray1<i64> = obj.extract()?;
    let values = values.as_array();
    let offsets = values
        .iter()
        .map(|&v| {
            usize::try_from(v).map_err(|_| PyValueError::new_err(format!("{key}: negative offset")))
        })
        .collect::<PyResult<Vec<_>>>()?;
    if offsets.first() != Some(&0)
        || offsets.last() != Some(&children)
        || offsets.windows(2).any(|w| w[0] >= w[1])
    {
        return Err(PyValueError::new_err(format!(
            "{key}: offsets must span all children strictly monotonically from zero"
        )));
    }
    Ok(offsets)
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
/// Legacy `offsets` spans one exterior ring per feature. Alternatively supply
/// all three arrays: `ring_offsets` spans coordinates, `polygon_offsets` spans
/// rings (exterior first, then holes), and `feature_offsets` spans polygons.
/// IDs and property columns are aligned with features, never rings or parts.
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
        let ids_obj = required(d, "cell_ids")?;
        let coords: PyReadonlyArray2<f64> = coords_obj.extract()?;
        let ids: PyReadonlyArray1<i64> = ids_obj.extract()?;
        let coords = coords.as_array();
        let ids = ids.as_array();
        if coords.ncols() != 2 {
            return Err(PyValueError::new_err(format!(
                "{name}: invalid packed polygon dimensions"
            )));
        }
        let nested = d.contains("ring_offsets")?
            || d.contains("polygon_offsets")?
            || d.contains("feature_offsets")?;
        let (ring_offsets, polygon_offsets, feature_offsets) = if nested {
            if d.contains("offsets")? {
                return Err(PyValueError::new_err(
                    "use either offsets or the three nested offset arrays, not both",
                ));
            }
            let rings = spans(d, "ring_offsets", coords.nrows())?;
            let polygons = spans(d, "polygon_offsets", rings.len() - 1)?;
            let features = spans(d, "feature_offsets", polygons.len() - 1)?;
            (rings, polygons, features)
        } else {
            let rings = spans(d, "offsets", coords.nrows())?;
            let identity: Vec<_> = (0..rings.len()).collect();
            (rings, identity.clone(), identity)
        };
        if feature_offsets.len() != ids.len() + 1 {
            return Err(PyValueError::new_err(format!(
                "{name}: feature offsets differ from ID count"
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
            // freestiler expects its input type names, not TileJSON's output
            // labels. Mixed scalar columns have no TileJSON union type.
            let mut kind = None;
            for value in &values {
                let next = match value {
                    PropertyValue::String(_) => "string",
                    PropertyValue::Bool(_) => "boolean",
                    PropertyValue::Null => continue,
                    _ => "numeric",
                };
                kind = Some(match kind {
                    Some(previous) if previous != next => "mixed",
                    _ => next,
                });
            }
            let kind = kind.unwrap_or("string");
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
            let mut polygons = Vec::new();
            for p in feature_offsets[i]..feature_offsets[i + 1] {
                let mut rings = Vec::new();
                for r in polygon_offsets[p]..polygon_offsets[p + 1] {
                    let start = ring_offsets[r];
                    let end = ring_offsets[r + 1];
                    if end - start < 4 {
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
                    crate::mesh::validate_ring(ring.0.iter().map(|c| [c.x, c.y])).map_err(
                        |error| {
                            crate::TopologyError::new_err(format!("{name}: feature {id}: {error}"))
                        },
                    )?;
                    rings.push(ring);
                }
                let exterior = rings.remove(0);
                polygons.push(Polygon::new(exterior, rings));
            }
            let geometry = if polygons.len() == 1 {
                Geometry::Polygon(polygons.remove(0))
            } else {
                Geometry::MultiPolygon(MultiPolygon::new(polygons))
            };
            features.push(Feature {
                id: Some(id),
                geometry,
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
