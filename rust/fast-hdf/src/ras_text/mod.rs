//! Lossless HEC-RAS plain-text documents.
//!
//! A [`TextDocument`] keeps the original bytes untouched and layers a line,
//! key and section index over them. Readers return byte spans into the
//! original buffer, so an unchanged document always serializes byte-exact.
//! Edits are collected into an [`EditBatch`] and applied in one pass that only
//! rewrites the intended spans (including dependent count tokens).
//!
//! This module is pure `std`: module registration in `lib.rs` and any Python
//! bindings are returned to the integrator as a separate patch.

pub mod document;
pub mod edit;
pub mod error;
pub mod fixed_width;
pub mod geometry;

pub use document::{EncodingReport, KeyLine, LineSpan, Newline, TextDocument};
pub use edit::{apply_batch, write_atomic, AppliedSpan, Edit, EditBatch, EditResult};
pub use error::{Diagnostic, Severity, TextError};
pub use geometry::{
    CountedBlock, GeometryIndex, NodeRecord, ReachRecord, Section, SectionKind, BLOCK_SPECS,
    MAX_MANNINGS_N_BLOCKS, MAX_XS_POINTS,
};
