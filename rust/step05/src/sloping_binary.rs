//! Typed geometry handoff; JSON contains only small array descriptors.
use crate::{
    MapError,
    sloping_session::{Geometry, InputCell, InputFace, InputVertex},
};
use serde::Deserialize;
use std::{collections::HashMap, fs, path::Path};

const SCHEMA: &str = "ras-commander-sloping-mesh/1";
const FIELDS: [(&str, usize); 12] = [
    ("centers", 16),
    ("cell_info", 8),
    ("cell_faces", 8),
    ("cell_minimum", 4),
    ("face_vertices", 8),
    ("face_cells", 8),
    ("face_info", 8),
    ("face_points", 16),
    ("face_minimum", 4),
    ("vertices", 16),
    ("vertex_info", 8),
    ("vertex_faces", 8),
];
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Array {
    path: String,
    rows: usize,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Header {
    schema: String,
    arrays: HashMap<String, Array>,
}
fn invalid(message: &str) -> MapError {
    MapError::Invalid(message.into())
}
fn header(path: &Path) -> Result<Header, MapError> {
    if fs::metadata(path)?.len() > 65536 {
        return Err(invalid("sloping binary header too large"));
    }
    let value: Header = serde_json::from_slice(&fs::read(path)?)
        .map_err(|e| invalid(&format!("sloping binary header: {e}")))?;
    if value.schema != SCHEMA
        || value
            .arrays
            .keys()
            .any(|key| key != "vertex_elevations" && !FIELDS.iter().any(|(name, _)| name == key))
        || FIELDS
            .iter()
            .any(|(key, _)| !value.arrays.contains_key(*key))
    {
        return Err(invalid("invalid sloping binary schema or array fields"));
    }
    Ok(value)
}
fn check(h: &Header, base: &Path) -> Result<u64, MapError> {
    let mut total = 0_u64;
    for (key, width) in FIELDS.into_iter().chain(
        h.arrays
            .contains_key("vertex_elevations")
            .then_some(("vertex_elevations", 4)),
    ) {
        let array = &h.arrays[key];
        let bytes = array
            .rows
            .checked_mul(width)
            .filter(|&n| n <= 16_usize << 30)
            .ok_or_else(|| invalid("sloping binary array too large"))? as u64;
        if fs::metadata(base.join(&array.path))?.len() != bytes {
            return Err(invalid("sloping binary array length mismatch"));
        }
        total = total
            .checked_add(bytes)
            .ok_or_else(|| invalid("sloping binary size overflow"))?;
    }
    Ok(total)
}
pub fn input_bytes(path: &Path) -> Result<u64, MapError> {
    let h = header(path)?;
    check(
        &h,
        path.parent()
            .ok_or_else(|| invalid("sloping mesh has no parent"))?,
    )
}
pub fn load(path: &Path) -> Result<Geometry, MapError> {
    let h = header(path)?;
    let base = path
        .parent()
        .ok_or_else(|| invalid("sloping mesh has no parent"))?;
    check(&h, base)?;
    let raw = |key: &str| -> Result<Vec<u8>, MapError> {
        let value = fs::read(base.join(&h.arrays[key].path))?;
        let width = if key == "vertex_elevations" {
            4
        } else {
            FIELDS.iter().find(|(name, _)| *name == key).unwrap().1
        };
        if value.len() != h.arrays[key].rows * width {
            return Err(invalid("sloping binary array changed size"));
        }
        Ok(value)
    };
    let pairs = |key: &str| -> Result<Vec<[f64; 2]>, MapError> {
        Ok(raw(key)?
            .as_chunks::<16>()
            .0
            .iter()
            .map(|p| {
                [
                    f64::from_le_bytes(p[..8].try_into().unwrap()),
                    f64::from_le_bytes(p[8..].try_into().unwrap()),
                ]
            })
            .collect())
    };
    let integers = |key: &str| -> Result<Vec<[usize; 2]>, MapError> {
        raw(key)?
            .as_chunks::<8>()
            .0
            .iter()
            .map(|p| {
                let a = i32::from_le_bytes(p[..4].try_into().unwrap());
                let b = i32::from_le_bytes(p[4..].try_into().unwrap());
                // Orientation columns may be negative. Incidence uses only column0;
                // offsets/counts and face address pairs require nonnegative values below.
                Ok([a as usize, b as usize])
            })
            .collect()
    };
    let floats = |key: &str| -> Result<Vec<f32>, MapError> {
        Ok(raw(key)?
            .as_chunks::<4>()
            .0
            .iter()
            .map(|p| f32::from_le_bytes(*p))
            .collect())
    };
    let incidence =
        |info: Vec<[usize; 2]>, values: Vec<[usize; 2]>| -> Result<Vec<Vec<usize>>, MapError> {
            let mut expected = 0_usize;
            let mut result = Vec::with_capacity(info.len());
            for [start, count] in info {
                if start != expected || start.checked_add(count).is_none_or(|v| v > values.len()) {
                    return Err(invalid("invalid ordered sloping incidence"));
                }
                result.push(values[start..start + count].iter().map(|v| v[0]).collect());
                expected += count;
            }
            if expected != values.len() {
                return Err(invalid("unreferenced sloping incidence"));
            }
            Ok(result)
        };
    let centers = pairs("centers")?;
    let cell_faces = incidence(integers("cell_info")?, integers("cell_faces")?)?;
    let minima = floats("cell_minimum")?;
    if centers.len() != cell_faces.len()
        || ![
            centers.len(),
            cell_faces.iter().filter(|v| v.len() > 1).count(),
        ]
        .contains(&minima.len())
    {
        return Err(invalid("sloping binary cell dimensions mismatch"));
    }
    let mut physical_minima = minima.into_iter();
    let cells = centers
        .into_iter()
        .zip(cell_faces)
        .map(|(point, faces)| {
            let minimum_elevation = if faces.len() > 1 {
                physical_minima.next().unwrap()
            } else {
                0.0
            };
            InputCell {
                point,
                minimum_elevation,
                virtual_cell: faces.len() == 1,
                faces,
            }
        })
        .collect::<Vec<_>>();
    let coordinates = pairs("vertices")?;
    let vertex_faces = incidence(integers("vertex_info")?, integers("vertex_faces")?)?;
    if coordinates.len() != vertex_faces.len() {
        return Err(invalid("sloping vertex dimensions mismatch"));
    }
    let vertices = coordinates
        .into_iter()
        .zip(vertex_faces)
        .map(|(point, faces)| {
            let n = faces.len();
            InputVertex {
                point,
                ccw: (0..n).map(|i| (i + 1) % n).collect(),
                cw: (0..n).map(|i| (i + n - 1) % n).collect(),
                faces,
            }
        })
        .collect::<Vec<_>>();
    let face_cells = integers("face_cells")?;
    let face_vertices = integers("face_vertices")?;
    let face_info = integers("face_info")?;
    let face_minima = floats("face_minimum")?;
    let interior = pairs("face_points")?;
    let count = face_cells.len();
    if [face_vertices.len(), face_info.len(), face_minima.len()]
        .iter()
        .any(|&n| n != count)
    {
        return Err(invalid("sloping face dimensions mismatch"));
    }
    let mut faces = Vec::with_capacity(count);
    for (((pair, ends), [start, length]), minimum_elevation) in face_cells
        .into_iter()
        .zip(face_vertices)
        .zip(face_info)
        .zip(face_minima)
    {
        if pair.iter().any(|&v| v >= cells.len())
            || ends.iter().any(|&v| v >= vertices.len())
            || start.checked_add(length).is_none_or(|v| v > interior.len())
        {
            return Err(invalid(
                "sloping face index or polyline range out of bounds",
            ));
        }
        let mut polyline = Vec::with_capacity(length + 2);
        polyline.push(vertices[ends[0]].point);
        polyline.extend_from_slice(&interior[start..start + length]);
        polyline.push(vertices[ends[1]].point);
        faces.push(InputFace {
            cells: pair,
            vertices: ends,
            minimum_elevation,
            perimeter: cells[pair[1]].virtual_cell,
            polyline,
        });
    }
    let vertex_elevations = if h.arrays.contains_key("vertex_elevations") {
        Some(floats("vertex_elevations")?)
    } else {
        None
    };
    Ok(Geometry {
        vertex_elevations,
        cells,
        faces,
        vertices,
    })
}
