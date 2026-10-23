use std::io::Write;
use std::ops::Range;
use std::path::Path;

use super::error::TextError;

/// Replace `range` of the source with `replacement`. An empty range inserts.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Edit {
    pub range: Range<usize>,
    pub replacement: Vec<u8>,
    pub label: String,
}

/// Unordered edits applied together in one pass over the source.
#[derive(Clone, Debug, Default)]
pub struct EditBatch {
    edits: Vec<Edit>,
}

impl EditBatch {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn replace(&mut self, range: Range<usize>, replacement: Vec<u8>, label: impl Into<String>) {
        self.edits.push(Edit {
            range,
            replacement,
            label: label.into(),
        });
    }

    pub fn insert(&mut self, at: usize, bytes: Vec<u8>, label: impl Into<String>) {
        self.replace(at..at, bytes, label);
    }

    pub fn extend(&mut self, other: EditBatch) {
        self.edits.extend(other.edits);
    }

    pub fn edits(&self) -> &[Edit] {
        &self.edits
    }

    pub fn len(&self) -> usize {
        self.edits.len()
    }

    pub fn is_empty(&self) -> bool {
        self.edits.is_empty()
    }
}

/// Where one edit landed: `original` in the source, `updated` in the output.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AppliedSpan {
    pub label: String,
    pub original: Range<usize>,
    pub updated: Range<usize>,
}

#[derive(Clone, Debug)]
pub struct EditResult {
    pub bytes: Vec<u8>,
    pub spans: Vec<AppliedSpan>,
}

/// Validate and apply all edits in a single copy. Bytes outside edit spans
/// are copied verbatim. Overlaps, out-of-range spans and two edits whose
/// relative order is ambiguous (same start, one empty) are rejected whole.
pub fn apply_batch(source: &[u8], batch: &EditBatch) -> Result<EditResult, TextError> {
    let mut order: Vec<&Edit> = batch.edits.iter().collect();
    for e in &order {
        if e.range.start > e.range.end || e.range.end > source.len() {
            return Err(TextError::SpanOutOfBounds {
                label: e.label.clone(),
                range: e.range.clone(),
                len: source.len(),
            });
        }
    }
    order.sort_by_key(|e| (e.range.start, e.range.end));
    for pair in order.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        let ambiguous =
            a.range.start == b.range.start && (a.range.is_empty() || b.range.is_empty());
        if a.range.end > b.range.start || ambiguous {
            return Err(TextError::OverlappingEdits {
                first: a.label.clone(),
                second: b.label.clone(),
            });
        }
    }
    let growth: isize = order
        .iter()
        .map(|e| e.replacement.len() as isize - e.range.len() as isize)
        .sum();
    let mut out = Vec::with_capacity((source.len() as isize + growth).max(0) as usize);
    let mut spans = Vec::with_capacity(order.len());
    let mut cursor = 0;
    for e in order {
        out.extend_from_slice(&source[cursor..e.range.start]);
        let start = out.len();
        out.extend_from_slice(&e.replacement);
        spans.push(AppliedSpan {
            label: e.label.clone(),
            original: e.range.clone(),
            updated: start..out.len(),
        });
        cursor = e.range.end;
    }
    out.extend_from_slice(&source[cursor..]);
    Ok(EditResult { bytes: out, spans })
}

/// Write `bytes` to a sibling temporary file, flush it to disk and rename it
/// over `path`, so readers never observe a partial file.
pub fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), TextError> {
    let io = |e: std::io::Error| TextError::Io(format!("{}: {e}", path.display()));
    let name = path
        .file_name()
        .ok_or_else(|| TextError::Io(format!("{}: no file name", path.display())))?;
    let tmp = path.with_file_name(format!(
        ".{}.{}.tmp",
        name.to_string_lossy(),
        std::process::id()
    ));
    let result = (|| {
        let mut file = std::fs::File::create(&tmp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&tmp, path)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&tmp);
    }
    result.map_err(io)
}
