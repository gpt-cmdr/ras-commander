//! Compiles the extension's text core in place, from the ras-commander-fast-hdf
//! checkout named by RAS_FAST_HDF_SOURCE (see build.rs), so tests exercise the
//! exact source shipped in python/src/ras_text.
include!(concat!(env!("OUT_DIR"), "/ras_text_module.rs"));
