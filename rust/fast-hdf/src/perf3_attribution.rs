//! Ignored local release attribution; never registered as a Python API.
use pyo3::prelude::*;
use ras_commander_rust::hdf::{ReadOnlyHdfSession, DEFAULT_MAX_BYTES};
use std::{path::Path, time::Instant};
#[test]
#[ignore = "RAS_PERF3_FIXTURES, embedded numpy; release diagnostic only"]
fn perf3_binding_attribution() {
    Python::initialize();
    Python::attach(|py| -> PyResult<()> {
        py.import("numpy")?;
        let root=std::env::var("RAS_PERF3_FIXTURES").expect("fixture directory required");
        let s=ReadOnlyHdfSession::with_options(Path::new(&root).join("AustinOyster.p01.hdf"),8,true).unwrap();
        let mut engine=0u128;let mut array=0u128;let mut envelope=0u128;
        for _ in 0..2000 {
            let t=Instant::now();
            let a=py.detach(||s.read_mesh_summary_values("Perimeter 1","Maximum Water Surface",None,DEFAULT_MAX_BYTES,DEFAULT_MAX_BYTES)).unwrap();
            engine+=t.elapsed().as_nanos();
            let t=Instant::now();std::hint::black_box(crate::reader::array(py,a)?);array+=t.elapsed().as_nanos();
            let r=py.detach(||s.read_mesh_summary("Perimeter 1","Maximum Water Surface",Some(&[0,1,2]),DEFAULT_MAX_BYTES,DEFAULT_MAX_BYTES)).unwrap();
            let t=Instant::now();std::hint::black_box(crate::fim::selection(py,r)?);envelope+=t.elapsed().as_nanos();
        }
        println!("BINDING_ATTRIBUTION calls=2000 engine_with_detach_ns={engine} numpy_from_owned_ns={array} identity_elements_rows_values_dict_ns={envelope}");
        Ok(())
    }).unwrap();
}
