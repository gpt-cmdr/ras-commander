//! Native fluvial registration, separate from existing module ownership.
use crate::fluvial::{CellKey, PeakTimes, Thresholds, VerifiedGraph};
use crate::{fluvial, fluvial_geometry, fluvial_topology};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;
use std::time::Instant;

fn error(e: impl std::fmt::Display) -> PyErr {
    PyValueError::new_err(e.to_string())
}

#[pyclass(frozen)]
struct NativeAnalysis {
    graph: VerifiedGraph,
    times: Vec<i64>,
    valid: Vec<bool>,
    wet: Vec<bool>,
    time_valid: Vec<bool>,
    points: Vec<[f64; 2]>,
    rings: Vec<Vec<usize>>,
    mesh_ids: Vec<u32>,
}

type PolygonIds = (Vec<usize>, Vec<Vec<usize>>, f64);
type Regions = Vec<(u32, u8, Vec<PolygonIds>)>;
type GraphOutput = (
    Vec<(u32, u64)>,
    Vec<usize>,
    Vec<usize>,
    Vec<(usize, usize)>,
    String,
);

#[pymethods]
impl NativeAnalysis {
    #[new]
    #[allow(clippy::too_many_arguments)]
    fn new(
        keys: Vec<(u32, u64)>,
        offsets: Vec<usize>,
        neighbors: Vec<usize>,
        times: Vec<i64>,
        valid: Vec<bool>,
        wet: Vec<bool>,
        time_valid: Vec<bool>,
        points: Vec<[f64; 2]>,
        rings: Vec<Vec<usize>>,
    ) -> PyResult<Self> {
        crate::panic_guard::guard(|| {
            let mesh_ids = keys.iter().map(|k| k.0).collect();
            let graph = VerifiedGraph::new(
                keys.into_iter()
                    .map(|(mesh_id, cell_id)| CellKey { mesh_id, cell_id })
                    .collect(),
                offsets,
                neighbors,
            )
            .map_err(error)?;
            let n = graph.keys().len();
            for (name, len) in [
                ("times", times.len()),
                ("valid", valid.len()),
                ("wet", wet.len()),
                ("time_valid", time_valid.len()),
                ("rings", rings.len()),
            ] {
                if len != n {
                    return Err(error(format!("{name} length {len}, expected {n}")));
                }
            }
            Ok(Self {
                graph,
                times,
                valid,
                wet,
                time_valid,
                points,
                rings,
                mesh_ids,
            })
        })
    }

    #[pyo3(signature=(delta_t_ms, tolerance_ms, seed_overrides=Vec::new()))]
    fn classify(
        &self,
        py: Python<'_>,
        delta_t_ms: u64,
        tolerance_ms: u64,
        seed_overrides: Vec<(usize, u8)>,
    ) -> PyResult<(Vec<u8>, HashMap<String, usize>, f64)> {
        crate::panic_guard::guard(|| {
            let overrides = seed_overrides
                .into_iter()
                .map(|(i, label)| match label {
                    1 => Ok((i, fluvial::Label::Fluvial)),
                    2 => Ok((i, fluvial::Label::Pluvial)),
                    _ => Err(error(format!("seed override label {label} must be 1 or 2"))),
                })
                .collect::<PyResult<Vec<_>>>()?;
            py.detach(|| {
                let start = Instant::now();
                let result = fluvial::classify_with_seed_overrides(
                    &self.graph,
                    PeakTimes {
                        milliseconds: &self.times,
                        valid: &self.valid,
                        wet: &self.wet,
                        time_valid: &self.time_valid,
                    },
                    Thresholds {
                        delta_t_ms,
                        tolerance_ms,
                    },
                    &overrides,
                )
                .map_err(error)?;
                let elapsed = start.elapsed().as_secs_f64();
                let d = result.diagnostics;
                let mut counts = HashMap::from([
                    ("qualifying_edges".into(), d.qualifying_edges),
                    ("seeded_cells".into(), d.seeded_cells),
                    ("conflicting_seeds".into(), d.conflicting_seeds),
                    ("growth_conflicts".into(), d.growth_conflicts),
                    ("waves".into(), d.waves),
                ]);
                for (i, count) in d.label_counts.iter().enumerate() {
                    counts.insert(format!("label_{i}"), *count);
                }
                Ok((
                    result.labels.into_iter().map(|l| l as u8).collect(),
                    counts,
                    elapsed,
                ))
            })
        })
    }

    /// Undirected edges (i < j) whose endpoints are valid, wet and timed and
    /// differ by >= delta_t_ms: the same seed predicate used by `classify`.
    fn qualifying_edges(&self, py: Python<'_>, delta_t_ms: u64) -> PyResult<Vec<(usize, usize)>> {
        crate::panic_guard::guard(|| {
            let value = {
                py.detach(|| {
                    let usable = |i: usize| self.valid[i] && self.wet[i] && self.time_valid[i];
                    let mut edges = Vec::new();
                    for i in 0..self.graph.keys().len() {
                        if !usable(i) {
                            continue;
                        }
                        for &j in self.graph.neighbors(i).unwrap_or(&[]) {
                            if j > i
                                && usable(j)
                                && self.times[i].abs_diff(self.times[j]) >= delta_t_ms
                            {
                                edges.push((i, j));
                            }
                        }
                    }
                    edges
                })
            };
            Ok(value)
        })
    }

    #[pyo3(signature=(labels, linear_unit_to_m, min_area_m2=0.0, *, exclude_invalid=false))]
    fn polygons(
        &self,
        py: Python<'_>,
        labels: Vec<u8>,
        linear_unit_to_m: f64,
        min_area_m2: f64,
        exclude_invalid: bool,
    ) -> PyResult<(Regions, HashMap<String, f64>)> {
        crate::panic_guard::guard(|| {
            if labels.len() != self.graph.keys().len() || labels.iter().any(|&l| l > 6) {
                return Err(error("invalid labels"));
            }
            py.detach(|| {
                let selected: Vec<_> = (0..self.rings.len())
                    .filter(|&i| !exclude_invalid || self.valid[i])
                    .collect();
                let filtered_rings;
                let filtered_meshes;
                let filtered_labels;
                let (rings, meshes, region_labels) = if selected.len() == self.rings.len() {
                    (&self.rings, &self.mesh_ids, &labels)
                } else {
                    filtered_rings = selected.iter().map(|&i| self.rings[i].clone()).collect();
                    filtered_meshes = selected.iter().map(|&i| self.mesh_ids[i]).collect();
                    filtered_labels = selected.iter().map(|&i| labels[i]).collect();
                    (&filtered_rings, &filtered_meshes, &filtered_labels)
                };
                let g = fluvial_geometry::polygonize(
                    &self.points,
                    rings,
                    meshes,
                    region_labels,
                    linear_unit_to_m,
                    min_area_m2,
                )
                .map_err(error)?;
                let d = g.diagnostics;
                let timings = HashMap::from([
                    ("boundary_seconds".into(), d.boundary_seconds),
                    ("polygonization_seconds".into(), d.polygonization_seconds),
                    ("boundary_edges".into(), d.boundary_edges as f64),
                    ("rings".into(), d.rings as f64),
                    ("removed_polygons".into(), d.removed_polygons as f64),
                    ("removed_area_m2".into(), d.removed_area_m2),
                    (
                        "excluded_invalid_cells".into(),
                        (self.rings.len() - selected.len()) as f64,
                    ),
                ]);
                Ok((
                    g.regions
                        .into_iter()
                        .map(|r| {
                            (
                                r.mesh_id,
                                r.label,
                                r.polygons
                                    .into_iter()
                                    .map(|p| (p.shell, p.holes, p.area_m2))
                                    .collect(),
                            )
                        })
                        .collect(),
                    timings,
                ))
            })
        })
    }
}

#[pyfunction]
fn validate_geometry(
    py: Python<'_>,
    points: Vec<[f64; 2]>,
    rings: Vec<Vec<usize>>,
) -> PyResult<Vec<(usize, String)>> {
    crate::panic_guard::guard(|| {
        py.detach(|| fluvial_geometry::validate_cells(&points, &rings).map_err(error))
    })
}

#[pyfunction]
fn assemble_rings(
    py: Python<'_>,
    info: Vec<[i64; 2]>,
    values: Vec<[i64; 2]>,
    faces: Vec<Vec<usize>>,
    physical: Vec<bool>,
) -> PyResult<Vec<Vec<usize>>> {
    crate::panic_guard::guard(|| {
        py.detach(|| {
            fluvial_topology::assemble_cell_rings(&info, &values, &faces, &physical).map_err(error)
        })
    })
}

#[pyfunction]
fn face_graph(
    py: Python<'_>,
    mesh_ids: Vec<u32>,
    cell_ids: Vec<Vec<u64>>,
    physical: Vec<Vec<bool>>,
    faces: Vec<Vec<[i64; 2]>>,
) -> PyResult<GraphOutput> {
    crate::panic_guard::guard(|| {
        let n = mesh_ids.len();
        if cell_ids.len() != n || physical.len() != n || faces.len() != n {
            return Err(error("mesh array lengths differ"));
        }
        py.detach(|| {
            let meshes: Vec<_> = (0..n)
                .map(|i| fluvial_topology::MeshFaces {
                    mesh_id: mesh_ids[i],
                    cell_ids: &cell_ids[i],
                    physical: &physical[i],
                    faces: &faces[i],
                    boundary_sentinels: &[-1],
                })
                .collect();
            let built = fluvial_topology::build_face_graph(&meshes).map_err(error)?;
            let keys: Vec<_> = built
                .graph
                .keys()
                .iter()
                .map(|k| (k.mesh_id, k.cell_id))
                .collect();
            let mut offsets = vec![0];
            let mut neighbors = vec![];
            for i in 0..keys.len() {
                neighbors.extend_from_slice(built.graph.neighbors(i).unwrap());
                offsets.push(neighbors.len());
            }
            Ok((
                keys,
                offsets,
                neighbors,
                built
                    .source_rows
                    .iter()
                    .map(|r| (r.mesh_index, r.cell_row))
                    .collect(),
                format!("{:?}", built.diagnostics),
            ))
        })
    })
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NativeAnalysis>()?;
    m.add_function(wrap_pyfunction!(assemble_rings, m)?)?;
    m.add_function(wrap_pyfunction!(face_graph, m)?)?;
    m.add_function(wrap_pyfunction!(validate_geometry, m)?)?;
    Ok(())
}
