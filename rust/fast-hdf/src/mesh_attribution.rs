// Ignored measurement harness only; no production registration or altered binding path.
use numpy::{IntoPyArray, PyReadonlyArray2};
use pyo3::{
    prelude::*,
    types::{PyAny, PyTuple},
};
use ras_commander_rust::mesh::{GeometryPolicy, OmissionKind, Topology};
use std::{
    path::{Path, PathBuf},
    time::Instant,
};
fn top(args: &[Bound<'_, PyAny>]) -> PyResult<Topology> {
    Ok(Topology::new(
        args[0]
            .extract::<PyReadonlyArray2<f64>>()?
            .as_array()
            .to_owned(),
        args[1]
            .extract::<PyReadonlyArray2<i64>>()?
            .as_array()
            .to_owned(),
        args[2]
            .extract::<PyReadonlyArray2<i64>>()?
            .as_array()
            .to_owned(),
        args[3]
            .extract::<PyReadonlyArray2<f64>>()?
            .as_array()
            .to_owned(),
        args[4]
            .extract::<PyReadonlyArray2<i64>>()?
            .as_array()
            .to_owned(),
        args[5]
            .extract::<PyReadonlyArray2<i64>>()?
            .as_array()
            .to_owned(),
    ))
}
fn profile<'py>(
    py: Python<'py>,
    args: &[Bound<'py, PyAny>],
    threads: usize,
    strict: bool,
) -> PyResult<(serde_json::Value, PyResult<Bound<'py, PyAny>>)> {
    let start = Instant::now();
    let top = top(args)?;
    let staging = start.elapsed().as_secs_f64();
    let start = Instant::now();
    let result = py.detach(|| {
        top.assemble(
            if strict {
                GeometryPolicy::Strict
            } else {
                GeometryPolicy::QuarantineInvalid
            },
            threads,
        )
    });
    let engine = start.elapsed().as_secs_f64();
    let mut timings = serde_json::json!({"staging":staging,"engine":engine});
    let packed = match result {
        Ok(p) => p,
        Err(e) => {
            let start = Instant::now();
            let legacy = crate::TopologyError::new_err(e.message.clone());
            legacy.value(py).setattr(
                "mesh_structure_error",
                e.kind != ras_commander_rust::ErrorKind::InvalidGeometry,
            )?;
            let elapsed = start.elapsed().as_secs_f64();
            let start = Instant::now();
            let err = crate::reader::err(e);
            timings["error_format"] = start.elapsed().as_secs_f64().into();
            timings["legacy_error_format_same_engine"] = elapsed.into();
            timings["error_message"] = err.value(py).str()?.to_string().into();
            timings["legacy_error_message"] = legacy.value(py).str()?.to_string().into();
            return Ok((timings, Err(err)));
        }
    };
    let start = Instant::now();
    let coords = packed.coordinates.into_iter().flatten().collect::<Vec<_>>();
    let offsets = packed
        .offsets
        .into_iter()
        .map(|n| {
            i64::try_from(n)
                .map_err(|_| pyo3::exceptions::PyValueError::new_err("coordinate count overflow"))
        })
        .collect::<PyResult<Vec<_>>>()?;
    let ids = packed.cell_ids;
    let coords = ndarray::Array2::from_shape_vec((coords.len() / 2, 2), coords).unwrap();
    timings["packing"] = start.elapsed().as_secs_f64().into();
    let start = Instant::now();
    let diagnostics = packed
        .diagnostics
        .into_iter()
        .filter(|d| d.kind == OmissionKind::InvalidGeometry)
        .map(|d| (d.cell_id, "invalid_geometry", d.reason))
        .collect::<Vec<_>>();
    timings["diagnostics_rust"] = start.elapsed().as_secs_f64().into();
    let start = Instant::now();
    let arrays = [
        coords.into_pyarray(py).into_any(),
        offsets.into_pyarray(py).into_any(),
        ids.into_pyarray(py).into_any(),
    ];
    timings["numpy_output"] = start.elapsed().as_secs_f64().into();
    let start = Instant::now();
    let diagnostics = crate::mesh::diagnostic_records(py, diagnostics)?
        .into_pyobject(py)?
        .into_any();
    timings["diagnostics_python"] = start.elapsed().as_secs_f64().into();
    let start = Instant::now();
    let result = PyTuple::new(
        py,
        arrays
            .into_iter()
            .chain(std::iter::once(diagnostics))
            .collect::<Vec<_>>(),
    )?
    .into_any();
    timings["tuple_output"] = start.elapsed().as_secs_f64().into();
    Ok((timings, Ok(result)))
}
fn public<'py>(
    py: Python<'py>,
    args: &[Bound<'py, PyAny>],
    threads: usize,
    strict: bool,
) -> PyResult<Bound<'py, PyAny>> {
    crate::mesh::assemble_cells(
        py,
        args[0].extract()?,
        args[1].extract()?,
        args[2].extract()?,
        args[3].extract()?,
        args[4].extract()?,
        args[5].extract()?,
        Some(threads),
        strict,
        true,
    )
}
fn synthetic(py: Python<'_>, cells: usize, invalid: bool) -> Vec<Bound<'_, PyAny>> {
    let mut p = Vec::new();
    let mut e = Vec::new();
    let mut f = Vec::new();
    let mut c = Vec::new();
    for n in 0..cells {
        let q = if invalid {
            [[0., 0.], [2., 2.], [0., 2.], [2., 0.]]
        } else {
            [[0., 0.], [2., 0.], [2., 2.], [0., 2.]]
        };
        for (i, v) in q.iter().enumerate() {
            p.extend([v[0] + n as f64 * 4., v[1]]);
            e.extend([(n * 4 + i) as i64, (n * 4 + (i + 1) % 4) as i64]);
            f.extend([(n * 4 + i) as i64, 0]);
        }
        c.extend([(n * 4) as i64, 4]);
    }
    vec![
        ndarray::Array2::from_shape_vec((cells * 4, 2), p)
            .unwrap()
            .into_pyarray(py)
            .into_any(),
        ndarray::Array2::from_shape_vec((cells * 4, 2), e)
            .unwrap()
            .into_pyarray(py)
            .into_any(),
        ndarray::Array2::<i64>::zeros((cells * 4, 2))
            .into_pyarray(py)
            .into_any(),
        ndarray::Array2::<f64>::zeros((0, 2))
            .into_pyarray(py)
            .into_any(),
        ndarray::Array2::from_shape_vec((cells, 2), c)
            .unwrap()
            .into_pyarray(py)
            .into_any(),
        ndarray::Array2::from_shape_vec((cells * 4, 2), f)
            .unwrap()
            .into_pyarray(py)
            .into_any(),
    ]
}
fn find(root: &Path, name: &str) -> Option<PathBuf> {
    for e in std::fs::read_dir(root).ok()?.flatten() {
        let p = e.path();
        if p.is_dir() {
            if let Some(p) = find(&p, name) {
                return Some(p);
            }
        } else if p.file_name().and_then(|n| n.to_str()) == Some(name) {
            return Some(p);
        }
    }
    None
}
fn run(
    py: Python<'_>,
    label: &str,
    args: &[Bound<'_, PyAny>],
    load: f64,
    repeats: usize,
) -> PyResult<()> {
    for threads in [1, 4] {
        for strict in [true, false] {
            for repeat in 0..repeats {
                // Alternate instrumented/public call order. Hash/equality outside timed regions.
                let call = || {
                    let s = Instant::now();
                    let out = public(py, args, threads, strict);
                    (s.elapsed().as_secs_f64(), out)
                };
                let ((public_seconds, actual), (timings, measured)) = if repeat % 2 == 0 {
                    (call(), profile(py, args, threads, strict)?)
                } else {
                    let p = profile(py, args, threads, strict)?;
                    (call(), p)
                };
                let outcome = match (actual, measured) {
                    (Ok(a), Ok(b)) => {
                        for i in 0..3 {
                            py.import("numpy")?.getattr("testing")?.call_method1(
                                "assert_array_equal",
                                (a.get_item(i)?, b.get_item(i)?),
                            )?;
                        }
                        assert_eq!(
                            a.get_item(3)?.repr()?.to_string(),
                            b.get_item(3)?.repr()?.to_string()
                        );
                        "returned"
                    }
                    (Err(a), Err(b)) => {
                        assert!(a.is_instance_of::<crate::TopologyError>(py));
                        assert!(a.get_type(py).is(b.get_type(py)));
                        assert_eq!(
                            a.value(py).str()?.to_string(),
                            b.value(py).str()?.to_string()
                        );
                        "refused"
                    }
                    _ => panic!("profile changed outcome"),
                };
                println!(
                    "BRIDGE_ATTRIBUTION {}",
                    serde_json::json!({"label":label,"threads":threads,"strict":strict,"repeat":repeat,"outcome":outcome,"input_load_conversion_seconds":load,"public_seconds":public_seconds,"stage_seconds":timings,"engine_commit":env!("RAS_ENGINE_COMMIT")})
                );
            }
        }
    }
    Ok(())
}
#[test]
#[ignore = "bridge attribution; requires embedded Python numpy/h5py, release for measurements"]
fn assembly_boundary_attribution() -> PyResult<()> {
    Python::initialize();
    Python::attach(|py| {
        let cells: usize = std::env::var("RAS_BRIDGE_BENCH_CELLS")
            .unwrap_or_else(|_| "100000".into())
            .parse()
            .unwrap();
        let repeats: usize = std::env::var("RAS_BRIDGE_BENCH_REPEATS")
            .unwrap_or_else(|_| "7".into())
            .parse()
            .unwrap();
        for invalid in [false, true] {
            let start = Instant::now();
            let args = synthetic(py, if invalid { 1 } else { cells }, invalid);
            run(
                py,
                if invalid {
                    "synthetic-invalid"
                } else {
                    "synthetic-valid"
                },
                &args,
                start.elapsed().as_secs_f64(),
                repeats,
            )?;
        }
        if let Ok(root) = std::env::var("RAS_NATIVE_FIXTURES") {
            for (name, mesh) in [
                ("JUL2020_D100RAS.p04.hdf", "D601"),
                ("BaldEagleDamBrk.p07.hdf", "BaldEagleCr"),
                ("BaldEagleDamBrk.p18.hdf", "BaldEagleCr"),
                ("BaldEagleDamBrk.p18.hdf", "Upper 2D Area"),
            ] {
                let path = find(Path::new(&root), name).expect("configured fixture missing");
                let start = Instant::now();
                let f = py
                    .import("h5py")?
                    .getattr("File")?
                    .call1((path.to_string_lossy().as_ref(), "r"))?;
                let mut args = Vec::new();
                for (i, key) in [
                    "FacePoints Coordinate",
                    "Faces FacePoint Indexes",
                    "Faces Perimeter Info",
                    "Faces Perimeter Values",
                    "Cells Face and Orientation Info",
                    "Cells Face and Orientation Values",
                ]
                .iter()
                .enumerate()
                {
                    let raw = f
                        .get_item(format!("Geometry/2D Flow Areas/{mesh}/{key}"))?
                        .get_item(py.Ellipsis())?;
                    let kw = pyo3::types::PyDict::new(py);
                    kw.set_item("dtype", if i == 0 || i == 3 { "float64" } else { "int64" })?;
                    args.push(
                        py.import("numpy")?
                            .getattr("ascontiguousarray")?
                            .call((raw,), Some(&kw))?,
                    );
                }
                f.call_method0("close")?;
                run(
                    py,
                    &format!("{name}/{mesh}"),
                    &args,
                    start.elapsed().as_secs_f64(),
                    repeats,
                )?;
            }
        }
        Ok(())
    })
}
