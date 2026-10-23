use std::fmt;
use std::ops::Range;

/// Hard failures: the requested operation was not performed.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TextError {
    /// An edit span lies outside the source buffer or is reversed.
    SpanOutOfBounds {
        label: String,
        range: Range<usize>,
        len: usize,
    },
    /// Two edits touch the same bytes, or their order is ambiguous.
    OverlappingEdits { first: String, second: String },
    /// A value cannot be written into its fixed-width field.
    FieldOverflow { value: String, width: usize },
    /// A value is not finite.
    NonFinite { value: String },
    /// An edit would violate a HEC-RAS limit or invariant.
    Invalid(String),
    /// A requested record does not exist.
    NotFound(String),
    /// Filesystem failure while writing an output.
    Io(String),
}

impl fmt::Display for TextError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::SpanOutOfBounds { label, range, len } => write!(
                f,
                "edit '{label}' span {}..{} is outside a {len}-byte source",
                range.start, range.end
            ),
            Self::OverlappingEdits { first, second } => {
                write!(
                    f,
                    "edits '{first}' and '{second}' overlap or have ambiguous order"
                )
            }
            Self::FieldOverflow { value, width } => {
                write!(f, "value {value} cannot fit a {width}-character field")
            }
            Self::NonFinite { value } => write!(f, "value {value} is not finite"),
            Self::Invalid(msg) => write!(f, "{msg}"),
            Self::NotFound(msg) => write!(f, "not found: {msg}"),
            Self::Io(msg) => write!(f, "io: {msg}"),
        }
    }
}

impl std::error::Error for TextError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Severity {
    Info,
    Warning,
    Error,
}

impl Severity {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Info => "info",
            Self::Warning => "warning",
            Self::Error => "error",
        }
    }
}

/// A non-fatal finding tied to a line (0-based) and byte span.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Diagnostic {
    pub severity: Severity,
    pub code: &'static str,
    pub line: usize,
    pub span: Range<usize>,
    pub message: String,
}
