//! FORTRAN-style fixed-width numeric fields (8- and 16-character columns).
//!
//! Parsing mirrors `GeomParser.parse_fixed_width`: columns are cut by
//! position, blank columns are skipped, and a column that is not a number is
//! split with the `-?\d+\.?\d*` fallback. Fallbacks are reported, not hidden.

use super::error::TextError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FieldKind {
    Number,
    Blank,
    /// Column was not one number; the fallback produced this many values.
    Merged(usize),
    /// Column produced no numeric value.
    Invalid,
}

/// One column, positioned relative to the start of the line content.
#[derive(Clone, Debug, PartialEq)]
pub struct Field {
    pub offset: usize,
    pub len: usize,
    pub kind: FieldKind,
    pub values: Vec<f64>,
}

fn parse_number(text: &[u8]) -> Option<f64> {
    let s = std::str::from_utf8(text).ok()?;
    // Rust accepts "inf"/"nan" like Python's float(); both are rejected by
    // later finiteness checks rather than silently diverging here.
    s.parse::<f64>().ok()
}

/// Emulates `re.findall(r'-?\d+\.?\d*', column)`.
fn merged_numbers(text: &[u8]) -> Vec<f64> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < text.len() {
        let start = i;
        let mut j = i;
        if text[j] == b'-' {
            j += 1;
        }
        let digits = j;
        while j < text.len() && text[j].is_ascii_digit() {
            j += 1;
        }
        if j == digits {
            i = start + 1;
            continue;
        }
        if j < text.len() && text[j] == b'.' {
            j += 1;
            while j < text.len() && text[j].is_ascii_digit() {
                j += 1;
            }
        }
        if let Some(v) = parse_number(&text[start..j]) {
            out.push(v);
        }
        i = j;
    }
    out
}

/// Cut `content` (no terminator) into `width`-byte columns.
pub fn split_fields(content: &[u8], width: usize) -> Vec<Field> {
    assert!(width > 0, "fixed-width column width must be positive");
    content
        .chunks(width)
        .enumerate()
        .map(|(n, chunk)| {
            let trimmed = super::document::trim_ascii(chunk);
            let (kind, values) = if trimmed.is_empty() {
                (FieldKind::Blank, Vec::new())
            } else if let Some(v) = parse_number(trimmed) {
                (FieldKind::Number, vec![v])
            } else {
                let merged = merged_numbers(trimmed);
                if merged.is_empty() {
                    (FieldKind::Invalid, merged)
                } else {
                    (FieldKind::Merged(merged.len()), merged)
                }
            };
            Field {
                offset: n * width,
                len: chunk.len(),
                kind,
                values,
            }
        })
        .collect()
}

/// Values in column order, exactly as the Python reader would produce them.
pub fn parse_values(content: &[u8], width: usize) -> Vec<f64> {
    split_fields(content, width)
        .into_iter()
        .flat_map(|f| f.values)
        .collect()
}

/// True when every non-blank column holds exactly one number.
pub fn is_clean_numeric(content: &[u8], width: usize) -> bool {
    split_fields(content, width)
        .iter()
        .all(|f| matches!(f.kind, FieldKind::Number | FieldKind::Blank))
}

/// Formatting options matching `ras_commander._fixed_width._format_fixed_width_value`.
#[derive(Clone, Copy, Debug)]
pub struct FormatSpec {
    pub width: usize,
    pub max_decimals: usize,
    pub min_decimals: usize,
    pub normalize_negative_zero: bool,
}

impl FormatSpec {
    pub const fn new(width: usize, max_decimals: usize) -> Self {
        Self {
            width,
            max_decimals,
            min_decimals: 0,
            normalize_negative_zero: false,
        }
    }
}

/// Keep `max_decimals` while the value fits, then drop one decimal at a time;
/// never fall back to exponent notation.
pub fn format_value(value: f64, spec: FormatSpec) -> Result<String, TextError> {
    if !value.is_finite() {
        return Err(TextError::NonFinite {
            value: value.to_string(),
        });
    }
    for decimals in (spec.min_decimals..=spec.max_decimals).rev() {
        let mut text = format!("{value:.decimals$}");
        if spec.normalize_negative_zero && text.parse::<f64>().is_ok_and(|v| v == 0.0) {
            text = format!("{:.decimals$}", 0.0);
        }
        if text.len() <= spec.width {
            return Ok(format!("{text:>width$}", width = spec.width));
        }
    }
    Err(TextError::FieldOverflow {
        value: value.to_string(),
        width: spec.width,
    })
}

/// Format `values` into lines of `per_line` columns. `specs` cycles per value
/// (e.g. station/n/flag for Manning triplets). Lines end with `newline`.
pub fn format_lines(
    values: &[f64],
    specs: &[FormatSpec],
    per_line: usize,
    newline: &[u8],
) -> Result<Vec<u8>, TextError> {
    let mut out = Vec::new();
    for (row_idx, row) in values.chunks(per_line).enumerate() {
        for (k, &v) in row.iter().enumerate() {
            let spec = specs[(row_idx * per_line + k) % specs.len()];
            out.extend_from_slice(format_value(v, spec)?.as_bytes());
        }
        out.extend_from_slice(newline);
    }
    Ok(out)
}
