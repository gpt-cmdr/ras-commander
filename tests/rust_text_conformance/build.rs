//! Locates the extension's lossless text core in a checkout of
//! https://github.com/gpt-cmdr/ras-commander-fast-hdf (`RAS_FAST_HDF_SOURCE`)
//! and compiles it in place, unchanged.
use std::env;
use std::fs;
use std::path::{self, PathBuf};

fn main() {
    println!("cargo:rerun-if-env-changed=RAS_FAST_HDF_SOURCE");
    let root = env::var_os("RAS_FAST_HDF_SOURCE").unwrap_or_else(|| {
        panic!("set RAS_FAST_HDF_SOURCE to a checkout of https://github.com/gpt-cmdr/ras-commander-fast-hdf")
    });
    let module = path::absolute(PathBuf::from(root).join("python/src/ras_text/mod.rs"))
        .expect("RAS_FAST_HDF_SOURCE must be a valid path");
    assert!(module.is_file(), "{} not found; is RAS_FAST_HDF_SOURCE a ras-commander-fast-hdf checkout?", module.display());
    println!("cargo:rerun-if-changed={}", module.display());
    let module = module.to_str().expect("RAS_FAST_HDF_SOURCE must be valid UTF-8");
    let out = PathBuf::from(env::var_os("OUT_DIR").unwrap()).join("ras_text_module.rs");
    fs::write(out, format!("#[path = {module:?}]\npub mod ras_text;\n")).unwrap();
}
