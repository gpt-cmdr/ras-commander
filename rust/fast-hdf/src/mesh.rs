use crate::TopologyError;
use freestiler_core::geo::{
    kernels::{Kernel, Orientation, RobustKernel},
    line_intersection::{line_intersection, LineIntersection},
    Line,
};
use ndarray::Array2;
use numpy::{IntoPyArray, PyReadonlyArray2};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashMap;

type Point = [f64; 2];

/// Validate source geometry without normalizing/removing any output vertices.
/// Zero-length edges are ignored only in this validation view: repeated adjacent
/// coordinates and forward collinear perimeter vertices remain in packed output.
pub(crate) fn validate_ring(points: impl IntoIterator<Item = Point>) -> Result<(), String> {
    let mut points = points.into_iter();
    let first = points.next().ok_or("empty cell ring")?;
    if !first.iter().all(|v| v.is_finite()) {
        return Err("nonfinite cell ring coordinate".into());
    }
    let mut previous = first;
    let mut edges = Vec::new();
    for point in points {
        if !point.iter().all(|v| v.is_finite()) {
            return Err("nonfinite cell ring coordinate".into());
        }
        if point != previous {
            edges.push(Line::new(previous, point));
        }
        previous = point;
    }
    if previous != first {
        return Err("unclosed cell ring".into());
    }
    if edges.len() < 3 {
        return Err("zero-area cell ring (fewer than three nonzero edges)".into());
    }
    // Avoid a shoelace sum: cancellation at large projected coordinate origins
    // can misclassify a valid narrow cell. A simple non-collinear closed ring
    // has nonzero area; robust orientation plus intersection checks proves it.
    if edges.iter().skip(1).all(|edge| {
        RobustKernel::orient2d(edges[0].start, edges[0].end, edge.end) == Orientation::Collinear
    }) {
        return Err("zero-area (collinear) cell ring".into());
    }
    for i in 0..edges.len() {
        for j in i + 1..edges.len() {
            // geo rejects disjoint bounding boxes before robust orientation.
            let Some(intersection) = line_intersection(edges[i], edges[j]) else {
                continue;
            };
            let adjacent = j == i + 1 || (i == 0 && j + 1 == edges.len());
            if !adjacent {
                return Err("cell ring self-intersection or nonadjacent touch".into());
            }
            if matches!(intersection, LineIntersection::Collinear { .. }) {
                return Err("cell ring backtracks over an adjacent edge".into());
            }
        }
    }
    Ok(())
}
// Only a proven geometric invalidity is eligible for quarantine. Bounds,
// connectivity, layout and arithmetic failures never enter that policy.
#[derive(Debug)]
enum CellError {
    Structural(String),
    Geometry(String),
}
impl From<String> for CellError {
    fn from(value: String) -> Self {
        Self::Structural(value)
    }
}
impl From<&str> for CellError {
    fn from(value: &str) -> Self {
        Self::Structural(value.into())
    }
}
impl std::fmt::Display for CellError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Structural(s) | Self::Geometry(s) => f.write_str(s),
        }
    }
}

fn index(n: i64, bound: usize, label: &str) -> Result<usize, String> {
    let n = usize::try_from(n).map_err(|_| format!("negative {label}"))?;
    if n >= bound {
        return Err(format!("{label} {n} out of range {bound}"));
    }
    Ok(n)
}
fn span(
    start: i64,
    count: i64,
    bound: usize,
    label: &str,
) -> Result<std::ops::Range<usize>, String> {
    let start = usize::try_from(start).map_err(|_| format!("negative {label} offset"))?;
    let count = usize::try_from(count).map_err(|_| format!("negative {label} count"))?;
    let end = start
        .checked_add(count)
        .ok_or_else(|| format!("overflow in {label}"))?;
    if end > bound {
        return Err(format!("{label} range {start}..{end} exceeds {bound}"));
    }
    Ok(start..end)
}

struct Topology {
    points: Array2<f64>,
    ends: Array2<i64>,
    perim_info: Array2<i64>,
    perim: Array2<f64>,
    cell_info: Array2<i64>,
    cell_faces: Array2<i64>,
}
impl Topology {
    fn validate(&self) -> Result<(), String> {
        for (label, array) in [
            ("face points", &self.points),
            ("perimeter coordinates", &self.perim),
        ] {
            if array.ncols() != 2 {
                return Err(format!("{label} must have two columns"));
            }
            if array.iter().any(|v| !v.is_finite()) {
                return Err(format!("nonfinite {label}"));
            }
        }
        for (label, array, min) in [
            ("face endpoints", &self.ends, 2),
            ("perimeter info", &self.perim_info, 2),
            ("cell info", &self.cell_info, 2),
            ("cell faces", &self.cell_faces, 1),
        ] {
            if array.ncols() < min {
                return Err(format!("{label} needs at least {min} columns"));
            }
        }
        if self.ends.nrows() != self.perim_info.nrows() {
            return Err("face/perimeter row mismatch".into());
        }
        for f in 0..self.ends.nrows() {
            index(self.ends[[f, 0]], self.points.nrows(), "face endpoint")?;
            index(self.ends[[f, 1]], self.points.nrows(), "face endpoint")?;
            span(
                self.perim_info[[f, 0]],
                self.perim_info[[f, 1]],
                self.perim.nrows(),
                "face perimeter",
            )?;
        }
        // Preflight every cell before geometry work, including cells following
        // an invalid ring. Corruption cannot be hidden by strict early failure.
        for cell in 0..self.cell_info.nrows() {
            let range = span(
                self.cell_info[[cell, 0]],
                self.cell_info[[cell, 1]],
                self.cell_faces.nrows(),
                "cell faces",
            )
            .map_err(|e| format!("cell {cell}: {e}"))?;
            for row in range {
                index(self.cell_faces[[row, 0]], self.ends.nrows(), "cell face")
                    .map_err(|e| format!("cell {cell}: {e}"))?;
            }
        }
        Ok(())
    }
    fn ring(&self, cell: usize) -> Result<Option<Vec<Point>>, CellError> {
        let slice = span(
            self.cell_info[[cell, 0]],
            self.cell_info[[cell, 1]],
            self.cell_faces.nrows(),
            "cell faces",
        )?;
        if slice.is_empty() {
            return Ok(None);
        }
        let faces: Vec<usize> = slice
            .map(|row| index(self.cell_faces[[row, 0]], self.ends.nrows(), "cell face"))
            .collect::<Result<_, _>>()?;
        // HEC-RAS includes boundary ghost rows with a single open face. GEOS
        // polygonize produces no polygon for these; preserve that behavior
        // without guessing a cutoff from the real-cell count or renumbering.
        if faces.len() == 1 && self.ends[[faces[0], 0]] != self.ends[[faces[0], 1]] {
            return Ok(None);
        }
        if faces
            .iter()
            .enumerate()
            .any(|(i, face)| faces[..i].contains(face))
        {
            return Err("duplicate face in cell boundary".into());
        }
        let mut adjacency: HashMap<i64, Vec<usize>> = HashMap::with_capacity(faces.len());
        for (i, &f) in faces.iter().enumerate() {
            let a = self.ends[[f, 0]];
            let b = self.ends[[f, 1]];
            if a == b {
                return Err("self-loop face".into());
            }
            adjacency.entry(a).or_default().push(i);
            adjacency.entry(b).or_default().push(i);
        }
        if adjacency.values().any(|v| v.len() != 2) {
            return Err("cell boundary is not a degree-two closed chain".into());
        }
        let first = self.ends[[faces[0], 0]];
        let mut point = first;
        let mut visited = vec![false; faces.len()];
        let mut ring = vec![[
            self.points[[first as usize, 0]],
            self.points[[first as usize, 1]],
        ]];
        for _ in 0..faces.len() {
            let local = *adjacency
                .get(&point)
                .and_then(|v| v.iter().find(|&&i| !visited[i]))
                .ok_or("disconnected or repeated cell boundary")?;
            visited[local] = true;
            let face = faces[local];
            let reverse = self.ends[[face, 1]] == point;
            let range = span(
                self.perim_info[[face, 0]],
                self.perim_info[[face, 1]],
                self.perim.nrows(),
                "face perimeter",
            )?;
            if reverse {
                for row in range.rev() {
                    ring.push([self.perim[[row, 0]], self.perim[[row, 1]]]);
                }
            } else {
                for row in range {
                    ring.push([self.perim[[row, 0]], self.perim[[row, 1]]]);
                }
            }
            point = self.ends[[face, if reverse { 0 } else { 1 }]];
            ring.push([
                self.points[[point as usize, 0]],
                self.points[[point as usize, 1]],
            ]);
        }
        if point != first {
            return Err("unclosed cell boundary".into());
        }
        if ring.len() < 4 {
            return Err("cell ring has fewer than four coordinates".into());
        }
        validate_ring(ring.iter().copied()).map_err(CellError::Geometry)?;
        Ok(Some(ring))
    }
}

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
    // Own buffers before releasing Python: callers may mutate original arrays
    // from another thread while this operation runs.
    let top = Topology {
        points: face_points.as_array().to_owned(),
        ends: face_endpoints.as_array().to_owned(),
        perim_info: face_perimeter_info.as_array().to_owned(),
        perim: face_perimeter_values.as_array().to_owned(),
        cell_info: cell_face_info.as_array().to_owned(),
        cell_faces: cell_face_values.as_array().to_owned(),
    };
    let pool = crate::pool(threads)?;
    let packed = py
        .detach(|| -> Result<_, CellError> {
            top.validate()?;
            let rings: Vec<_> = pool.install(|| {
                (0..top.cell_info.nrows())
                    .into_par_iter()
                    .map(|cell| top.ring(cell))
                    .collect()
            });
            let mut coords = Vec::new();
            let mut offsets = vec![0i64];
            let mut ids = Vec::new();
            let mut diagnostics = Vec::new();
            for (cell, result) in rings.into_iter().enumerate() {
                let ring = match result {
                    Ok(ring) => ring,
                    Err(CellError::Geometry(reason)) if !strict => {
                        diagnostics.push((
                            i64::try_from(cell).map_err(|_| "cell ID overflow")?,
                            "invalid_geometry",
                            reason,
                        ));
                        continue;
                    }
                    Err(CellError::Structural(reason)) => {
                        return Err(CellError::Structural(format!("cell {cell}: {reason}")))
                    }
                    Err(CellError::Geometry(reason)) => {
                        return Err(CellError::Geometry(format!("cell {cell}: {reason}")))
                    }
                };
                if let Some(ring) = ring {
                    coords.extend(ring.into_iter().flatten());
                    offsets.push(
                        i64::try_from(coords.len() / 2).map_err(|_| "coordinate count overflow")?,
                    );
                    ids.push(i64::try_from(cell).map_err(|_| "cell ID overflow")?);
                }
            }
            Ok((coords, offsets, ids, diagnostics))
        })
        .map_err(|error| {
            let structural = matches!(&error, CellError::Structural(_));
            let exception = TopologyError::new_err(error.to_string());
            // Preserve the public exception class while exposing the typed
            // distinction to the adapter; no message parsing or fallback on
            // structural corruption.
            if let Err(error) = exception
                .value(py)
                .setattr("mesh_structure_error", structural)
            {
                return error;
            }
            exception
        })?;
    let (coords, offsets, ids, diagnostics) = packed;
    let coords = Array2::from_shape_vec((coords.len() / 2, 2), coords)
        .map_err(|e| PyValueError::new_err(e.to_string()))?;
    let arrays = (
        coords.into_pyarray(py),
        offsets.into_pyarray(py),
        ids.into_pyarray(py),
    );
    if return_diagnostics {
        Ok((arrays.0, arrays.1, arrays.2, diagnostics)
            .into_pyobject(py)?
            .into_any())
    } else {
        Ok(arrays.into_pyobject(py)?.into_any())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ndarray::array;

    fn four_face_cell(points: Array2<f64>) -> Topology {
        Topology {
            points,
            ends: array![[0, 1], [1, 2], [2, 3], [3, 0]],
            perim_info: Array2::zeros((4, 2)),
            perim: Array2::zeros((0, 2)),
            cell_info: array![[0, 4]],
            cell_faces: array![[0], [1], [2], [3]],
        }
    }

    #[test]
    fn four_face_bowtie_is_not_a_valid_source_polygon() {
        let top = four_face_cell(array![[0., 0.], [2., 2.], [0., 2.], [2., 0.]]);
        top.validate().unwrap();
        assert!(top
            .ring(0)
            .unwrap_err()
            .to_string()
            .contains("self-intersection"));
    }

    #[test]
    fn four_face_collinear_closed_chain_has_zero_area() {
        let top = four_face_cell(array![[0., 0.], [1., 0.], [2., 0.], [3., 0.]]);
        top.validate().unwrap();
        assert!(top.ring(0).unwrap_err().to_string().contains("zero-area"));
    }

    #[test]
    fn nonadjacent_touch_and_backtracking_are_rejected() {
        assert!(validate_ring([
            [0., 0.],
            [2., 0.],
            [1., 1.],
            [2., 2.],
            [0., 2.],
            [1., 1.],
            [0., 0.]
        ])
        .is_err());
        assert!(
            validate_ring([[0., 0.], [2., 0.], [1., 0.], [1., 2.], [0., 2.], [0., 0.]]).is_err()
        );
    }

    #[test]
    fn validation_preserves_collinear_and_repeated_perimeter_vertices() {
        let mut top = four_face_cell(array![[0., 0.], [2., 0.], [2., 2.], [0., 2.]]);
        top.perim_info = array![[0, 3], [3, 0], [3, 0], [3, 0]];
        top.perim = array![[0., 0.], [1., 0.], [1., 0.]];
        top.validate().unwrap();
        let ring = top.ring(0).unwrap().unwrap();
        assert_eq!(
            ring,
            vec![
                [0., 0.],
                [0., 0.],
                [1., 0.],
                [1., 0.],
                [2., 0.],
                [2., 2.],
                [0., 2.],
                [0., 0.]
            ]
        );
    }

    #[test]
    fn narrow_cell_at_large_projected_origin_is_valid() {
        let top = four_face_cell(array![
            [1e9, 1e9],
            [1e9 + 1., 1e9],
            [1e9 + 1., 1e9 + 1e-6],
            [1e9, 1e9 + 1e-6]
        ]);
        assert!(top.ring(0).unwrap().is_some());
    }
    #[test]
    fn curved_reversed_face_is_preserved() {
        let top = Topology {
            points: array![[0., 0.], [2., 0.], [2., 2.], [0., 2.]],
            ends: array![[0, 1], [2, 1], [2, 3], [3, 0]],
            perim_info: array![[0, 0], [0, 1], [1, 0], [1, 0]],
            perim: array![[3., 1.]],
            cell_info: array![[0, 4]],
            cell_faces: array![[2, 0], [0, 0], [3, 0], [1, 0]],
        };
        top.validate().unwrap();
        let ring = top.ring(0).unwrap().unwrap();
        assert_eq!(ring.first(), ring.last());
        assert_eq!(ring.len(), 6);
        assert!(ring.contains(&[3., 1.]));
    }

    #[test]
    fn disconnected_cycles_are_rejected() {
        let top = Topology {
            points: array![[0., 0.], [1., 0.], [0., 1.], [3., 0.], [4., 0.], [3., 1.]],
            ends: array![[0, 1], [1, 2], [2, 0], [3, 4], [4, 5], [5, 3]],
            perim_info: Array2::zeros((6, 2)),
            perim: Array2::zeros((0, 2)),
            cell_info: array![[0, 6]],
            cell_faces: array![[0], [1], [2], [3], [4], [5]],
        };
        top.validate().unwrap();
        assert!(top
            .ring(0)
            .unwrap_err()
            .to_string()
            .contains("disconnected"));
    }

    #[test]
    fn invalid_offsets_fail_without_indexing() {
        assert!(span(i64::MAX, i64::MAX, 2, "test").is_err());
        assert!(span(-1, 1, 2, "test").is_err());
        assert!(index(-1, 2, "test").is_err());
        assert!(index(2, 2, "test").is_err());
    }

    #[test]
    fn single_open_face_ghost_is_omitted() {
        let top = Topology {
            points: array![[0., 0.], [1., 0.]],
            ends: array![[0, 1]],
            perim_info: array![[0, 0]],
            perim: Array2::zeros((0, 2)),
            cell_info: array![[0, 1]],
            cell_faces: array![[0, -1]],
        };
        top.validate().unwrap();
        assert!(top.ring(0).unwrap().is_none());
    }

    #[test]
    fn duplicated_curved_face_cannot_fabricate_a_polygon() {
        let top = Topology {
            points: array![[0., 0.], [1., 0.]],
            ends: array![[0, 1]],
            perim_info: array![[0, 1]],
            perim: array![[0.5, 1.]],
            cell_info: array![[0, 2]],
            cell_faces: array![[0, 1], [0, -1]],
        };
        top.validate().unwrap();
        assert!(top
            .ring(0)
            .unwrap_err()
            .to_string()
            .contains("duplicate face"));
    }
}
