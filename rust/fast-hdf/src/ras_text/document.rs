use std::collections::HashMap;
use std::ops::Range;

use super::edit::{apply_batch, EditBatch, EditResult};
use super::error::{Diagnostic, Severity, TextError};

/// Line terminator observed on a line. `Eof` marks a final unterminated line.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Newline {
    Lf,
    CrLf,
    Cr,
    Eof,
}

impl Newline {
    pub fn as_bytes(self) -> &'static [u8] {
        match self {
            Self::Lf => b"\n",
            Self::CrLf => b"\r\n",
            Self::Cr => b"\r",
            Self::Eof => b"",
        }
    }
}

/// Byte offsets of one line: `start..content_end` is the text and
/// `content_end..end` its terminator.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LineSpan {
    pub start: usize,
    pub content_end: usize,
    pub end: usize,
}

impl LineSpan {
    pub fn content(&self) -> Range<usize> {
        self.start..self.content_end
    }

    pub fn full(&self) -> Range<usize> {
        self.start..self.end
    }
}

/// A `Key=Value` line. `key` excludes the `=`; `value` runs to the line end
/// (terminator excluded). Both are absolute byte ranges.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct KeyLine {
    pub line: usize,
    pub key: Range<usize>,
    pub value: Range<usize>,
}

/// Encoding and newline facts. Bytes are never transcoded; text accessors
/// decode as Latin-1 so every byte maps to exactly one char.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct EncodingReport {
    pub utf8_bom: bool,
    pub valid_utf8: bool,
    pub non_ascii_bytes: usize,
    pub nul_bytes: usize,
    pub lf: usize,
    pub crlf: usize,
    pub cr: usize,
    pub final_newline: bool,
}

impl EncodingReport {
    /// Most frequent terminator, used for inserted lines. CRLF wins ties as
    /// the HEC-RAS default on Windows.
    pub fn dominant_newline(&self) -> Newline {
        if self.crlf >= self.lf && self.crlf >= self.cr {
            Newline::CrLf
        } else if self.lf >= self.cr {
            Newline::Lf
        } else {
            Newline::Cr
        }
    }
}

/// Immutable, byte-exact view of a HEC-RAS text file with a line/key index.
#[derive(Clone, Debug)]
pub struct TextDocument {
    bytes: Vec<u8>,
    lines: Vec<LineSpan>,
    keys: Vec<Option<KeyLine>>,
    free_text: Vec<bool>,
    key_index: HashMap<Vec<u8>, Vec<usize>>,
    encoding: EncodingReport,
    diagnostics: Vec<Diagnostic>,
}

fn trim_ascii_end(bytes: &[u8]) -> &[u8] {
    let mut end = bytes.len();
    while end > 0 && bytes[end - 1].is_ascii_whitespace() {
        end -= 1;
    }
    &bytes[..end]
}

pub(crate) fn trim_ascii(bytes: &[u8]) -> &[u8] {
    let mut start = 0;
    while start < bytes.len() && bytes[start].is_ascii_whitespace() {
        start += 1;
    }
    trim_ascii_end(&bytes[start..])
}

/// Byte-preserving decode (Latin-1). HEC-RAS writes Windows-1252/ASCII text.
pub fn latin1(bytes: &[u8]) -> String {
    bytes.iter().map(|&b| b as char).collect()
}

fn is_description_marker(content: &[u8], prefix: &[u8]) -> bool {
    let t = trim_ascii(content);
    t.len() >= prefix.len()
        && t[..prefix.len()].eq_ignore_ascii_case(prefix)
        && t.to_ascii_uppercase().ends_with(b"DESCRIPTION:")
}

impl TextDocument {
    /// Index `bytes` without modifying them. Never fails: anomalies become
    /// diagnostics so callers can still round-trip arbitrary input.
    pub fn parse(bytes: Vec<u8>) -> Self {
        let mut encoding = EncodingReport {
            utf8_bom: bytes.starts_with(&[0xEF, 0xBB, 0xBF]),
            valid_utf8: std::str::from_utf8(&bytes).is_ok(),
            ..EncodingReport::default()
        };
        let mut lines = Vec::new();
        let mut start = 0;
        let mut i = 0;
        while i < bytes.len() {
            match bytes[i] {
                b'\n' => {
                    encoding.lf += 1;
                    lines.push(LineSpan {
                        start,
                        content_end: i,
                        end: i + 1,
                    });
                    start = i + 1;
                }
                b'\r' => {
                    let crlf = bytes.get(i + 1) == Some(&b'\n');
                    let end = if crlf { i + 2 } else { i + 1 };
                    if crlf {
                        encoding.crlf += 1;
                    } else {
                        encoding.cr += 1;
                    }
                    lines.push(LineSpan {
                        start,
                        content_end: i,
                        end,
                    });
                    start = end;
                    i = end;
                    continue;
                }
                b => {
                    if b >= 0x80 {
                        encoding.non_ascii_bytes += 1;
                    } else if b == 0 {
                        encoding.nul_bytes += 1;
                    }
                }
            }
            i += 1;
        }
        encoding.final_newline = start == bytes.len() && !bytes.is_empty();
        if start < bytes.len() {
            lines.push(LineSpan {
                start,
                content_end: bytes.len(),
                end: bytes.len(),
            });
        }

        let mut diagnostics = Vec::new();
        if encoding.nul_bytes > 0 {
            diagnostics.push(Diagnostic {
                severity: Severity::Warning,
                code: "nul-bytes",
                line: 0,
                span: 0..0,
                message: format!("{} NUL bytes present", encoding.nul_bytes),
            });
        }
        let kinds = [encoding.lf, encoding.crlf, encoding.cr]
            .iter()
            .filter(|&&n| n > 0)
            .count();
        if kinds > 1 {
            diagnostics.push(Diagnostic {
                severity: Severity::Info,
                code: "mixed-newlines",
                line: 0,
                span: 0..0,
                message: format!(
                    "mixed terminators lf={} crlf={} cr={}",
                    encoding.lf, encoding.crlf, encoding.cr
                ),
            });
        }

        // Description blocks are free text and may contain '='.
        let mut free_text = vec![false; lines.len()];
        let mut open: Option<usize> = None;
        for (idx, span) in lines.iter().enumerate() {
            let content = &bytes[span.content()];
            match open {
                None if is_description_marker(content, b"BEGIN ") => open = Some(idx),
                Some(first) if is_description_marker(content, b"END ") => {
                    for flag in &mut free_text[first + 1..idx] {
                        *flag = true;
                    }
                    open = None;
                }
                _ => {}
            }
        }
        if let Some(first) = open {
            diagnostics.push(Diagnostic {
                severity: Severity::Warning,
                code: "unterminated-description",
                line: first,
                span: lines[first].content(),
                message: "description block has no END marker; lines indexed as keys".into(),
            });
        }

        let mut keys = Vec::with_capacity(lines.len());
        let mut key_index: HashMap<Vec<u8>, Vec<usize>> = HashMap::new();
        for (idx, span) in lines.iter().enumerate() {
            let content = &bytes[span.content()];
            let key = if free_text[idx] {
                None
            } else {
                content.iter().position(|&b| b == b'=').and_then(|eq| {
                    let raw = &content[..eq];
                    let name = trim_ascii_end(raw);
                    // Numeric payload lines never start a key.
                    let first = *name.first()?;
                    if first == b' ' || first == b'-' || first == b'.' || first.is_ascii_digit() {
                        return None;
                    }
                    key_index.entry(name.to_vec()).or_default().push(idx);
                    Some(KeyLine {
                        line: idx,
                        key: span.start..span.start + name.len(),
                        value: span.start + eq + 1..span.content_end,
                    })
                })
            };
            keys.push(key);
        }

        Self {
            bytes,
            lines,
            keys,
            free_text,
            key_index,
            encoding,
            diagnostics,
        }
    }

    pub fn read(path: &std::path::Path) -> Result<Self, TextError> {
        std::fs::read(path)
            .map(Self::parse)
            .map_err(|e| TextError::Io(format!("{}: {e}", path.display())))
    }

    /// The original bytes; serializing an unedited document is this slice.
    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn lines(&self) -> &[LineSpan] {
        &self.lines
    }

    pub fn line_count(&self) -> usize {
        self.lines.len()
    }

    pub fn line_bytes(&self, line: usize) -> &[u8] {
        &self.bytes[self.lines[line].content()]
    }

    pub fn line_text(&self, line: usize) -> String {
        latin1(self.line_bytes(line))
    }

    pub fn newline(&self, line: usize) -> Newline {
        let span = self.lines[line];
        match &self.bytes[span.content_end..span.end] {
            b"\n" => Newline::Lf,
            b"\r\n" => Newline::CrLf,
            b"\r" => Newline::Cr,
            _ => Newline::Eof,
        }
    }

    pub fn key_line(&self, line: usize) -> Option<&KeyLine> {
        self.keys[line].as_ref()
    }

    pub fn is_free_text(&self, line: usize) -> bool {
        self.free_text[line]
    }

    /// Case-sensitive key name (trailing blanks before `=` removed).
    pub fn key_name(&self, line: usize) -> Option<&[u8]> {
        self.keys[line].as_ref().map(|k| &self.bytes[k.key.clone()])
    }

    pub fn value_bytes(&self, line: usize) -> Option<&[u8]> {
        self.keys[line]
            .as_ref()
            .map(|k| &self.bytes[k.value.clone()])
    }

    /// Value with surrounding whitespace removed (mirrors Python `.strip()`
    /// for ASCII text).
    pub fn value_text(&self, line: usize) -> Option<String> {
        self.value_bytes(line).map(|v| latin1(trim_ascii(v)))
    }

    /// Lines whose key exactly equals `key` (case-sensitive), in file order.
    pub fn lines_with_key(&self, key: &str) -> &[usize] {
        self.key_index
            .get(key.as_bytes())
            .map_or(&[], Vec::as_slice)
    }

    pub fn first_value(&self, key: &str) -> Option<String> {
        self.lines_with_key(key)
            .first()
            .and_then(|&l| self.value_text(l))
    }

    /// Distinct keys with occurrence counts, sorted by key bytes.
    pub fn key_counts(&self) -> Vec<(String, usize)> {
        let mut out: Vec<_> = self
            .key_index
            .iter()
            .map(|(k, v)| (latin1(k), v.len()))
            .collect();
        out.sort();
        out
    }

    pub fn encoding(&self) -> &EncodingReport {
        &self.encoding
    }

    pub fn diagnostics(&self) -> &[Diagnostic] {
        &self.diagnostics
    }

    /// Absolute byte range of the stripped value token number `index` in a
    /// comma-separated value list (e.g. the count in `#Mann= 3 , 0 , 0`).
    pub fn value_token_span(&self, line: usize, index: usize) -> Option<Range<usize>> {
        let kl = self.keys[line].as_ref()?;
        let value = &self.bytes[kl.value.clone()];
        let mut offset = 0;
        for (n, part) in value.split(|&b| b == b',').enumerate() {
            if n == index {
                let lead = part.iter().take_while(|b| b.is_ascii_whitespace()).count();
                let trimmed = trim_ascii(part);
                let start = kl.value.start + offset + lead;
                return Some(start..start + trimmed.len());
            }
            offset += part.len() + 1;
        }
        None
    }

    /// Apply a batch once and re-index the result.
    pub fn apply(&self, batch: &EditBatch) -> Result<(TextDocument, EditResult), TextError> {
        let result = apply_batch(&self.bytes, batch)?;
        Ok((TextDocument::parse(result.bytes.clone()), result))
    }
}
