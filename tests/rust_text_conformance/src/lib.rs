//! Compiles the production module in place so tests exercise the exact
//! source that the integrator will register in rust/fast-hdf/src/lib.rs.
#[path = "../../../rust/fast-hdf/src/ras_text/mod.rs"]
pub mod ras_text;
