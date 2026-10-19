//! Bounded geometry (`.g##`) index over a lossless [`TextDocument`].
//!
//! Every line belongs to exactly one [`Section`]; a keyed line owns the
//! following un-keyed lines as its payload. Known counted blocks (station /
//! elevation, Manning's n, GIS cut lines, reach and storage-area polylines,
//! weir profiles, ...) are validated against their declared counts. Anything
//! else stays an opaque span, so unknown or unsupported records round-trip.

use std::collections::hash_map::Entry;
use std::collections::HashMap;
use std::ops::Range;

use super::document::{latin1, trim_ascii, TextDocument};
use super::edit::EditBatch;
use super::error::{Diagnostic, Severity, TextError};
use super::fixed_width::{format_lines, FormatSpec};

/// HEC-RAS computational limit on cross-section points.
pub const MAX_XS_POINTS: usize = 500;
/// HEC-RAS 6.6 rejects 21+ Manning's n blocks per cross section.
pub const MAX_MANNINGS_N_BLOCKS: usize = 20;

/// Layout of a counted block: `count` (first value token) items of
/// `values_per_item` numbers in `width`-wide slots, `values_per_line` slots
/// per line (the last line holds the remainder).
///
/// Slots are positional, as HEC-RAS writes them: a blank slot is a missing
/// value (NaN), not a skipped one, and non-blank text past the expected slots
/// is an error. `GeomParser.parse_fixed_width` instead skips blank columns;
/// the two agree whenever no slot is blank, so a blank slot is an error
/// unless `allow_blank` marks it as a native missing value.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BlockSpec {
    pub key: &'static str,
    pub values_per_item: usize,
    pub width: usize,
    pub values_per_line: usize,
    pub allow_blank: bool,
}

const fn spec(key: &'static str, per_item: usize, width: usize, per_line: usize) -> BlockSpec {
    BlockSpec {
        key,
        values_per_item: per_item,
        width,
        values_per_line: per_line,
        allow_blank: false,
    }
}

/// A block whose blank slots are legitimate missing values.
const fn blanks(key: &'static str, per_item: usize, width: usize, per_line: usize) -> BlockSpec {
    BlockSpec {
        allow_blank: true,
        ..spec(key, per_item, width, per_line)
    }
}

/// Counted blocks whose layout is asserted. Layouts were checked on the
/// RasExamples 6.6/7.0 corpus (zero diagnostics); tests/rust_text_conformance
/// reports per-key occurrence counts so unexercised entries stay visible.
pub const BLOCK_SPECS: &[BlockSpec] = &[
    spec("#Sta/Elev", 2, 8, 10),
    spec("#Mann", 3, 8, 9),
    // Normal-format obstructions leave the undefined side/outer slots blank
    // (RasExamples DredgeChannel.g02, hick85.g01, ROCK_TEST.g02), as in
    // `#XS Ineff`; blanks stay NaN and are never filled in.
    blanks("#Block Obstruct", 3, 8, 9),
    blanks("#XS Ineff", 3, 8, 9),
    spec("#Inline Weir SE", 2, 8, 10),
    spec("XS GIS Cut Line", 2, 16, 4),
    spec("Reach XY", 2, 16, 4),
    spec("Storage Area Surface Line", 2, 16, 2),
    blanks("Storage Area Vol Elev", 2, 8, 10),
    spec("Storage Area 2D Points", 2, 16, 4),
    spec("BreakLine Polyline", 2, 16, 4),
    spec("BC Line Arc", 2, 16, 4),
    spec("Connection Line", 2, 16, 4),
    spec("Conn Weir SE", 2, 8, 10),
    spec("Connection Centerline Profile", 2, 8, 10),
    spec("Lateral Weir SE", 2, 8, 10),
    spec("Lateral Weir Centerline", 2, 16, 4),
    spec("LCMann Region Polygon", 2, 16, 4),
    spec("Pump Station Group HQ", 2, 8, 10),
    spec("Pump Station Group Pump Centerline", 2, 16, 4),
];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum SectionKind {
    Header,
    Reach,
    Node,
    Junction,
    StorageArea,
    Connection,
    PumpStation,
    BreakLine,
    BcLine,
    LandCover,
    LandCoverRegion,
    Global,
}

impl SectionKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Header => "header",
            Self::Reach => "reach",
            Self::Node => "node",
            Self::Junction => "junction",
            Self::StorageArea => "storage_area",
            Self::Connection => "connection",
            Self::PumpStation => "pump_station",
            Self::BreakLine => "breakline",
            Self::BcLine => "bc_line",
            Self::LandCover => "land_cover",
            Self::LandCoverRegion => "land_cover_region",
            Self::Global => "global",
        }
    }
}

/// Keys that open a new top-level section.
pub fn section_kind_for_key(key: &[u8]) -> Option<SectionKind> {
    Some(match key {
        b"River Reach" | b"Reach" => SectionKind::Reach,
        b"Type RM Length L Ch R" => SectionKind::Node,
        b"Junct Name" => SectionKind::Junction,
        b"Storage Area" => SectionKind::StorageArea,
        b"Connection" => SectionKind::Connection,
        b"Pump Station" => SectionKind::PumpStation,
        b"BreakLine Name" => SectionKind::BreakLine,
        b"BC Line Name" => SectionKind::BcLine,
        b"LCMann Time" | b"LCMann Region Time" | b"LCMann Table" => SectionKind::LandCover,
        b"LCMann Region Name" => SectionKind::LandCoverRegion,
        b"Chan Stop Cuts"
        | b"Use User Specified Reach Order"
        | b"GIS Ratio Cuts To Invert"
        | b"GIS Limit At Bridges"
        | b"Composite Channel Slope"
        | b"GIS DTM Type"
        | b"GIS DTM"
        | b"GIS Stream Layer"
        | b"GIS Cross Section Layer"
        | b"GIS Map Projection"
        | b"GIS Projection Zone"
        | b"GIS Datum"
        | b"GIS Vertical Datum"
        | b"GIS Data Extents"
        | b"GIS Units" => SectionKind::Global,
        _ => return None,
    })
}

#[derive(Clone, Debug, PartialEq)]
pub struct Section {
    pub kind: SectionKind,
    /// Opening key (empty for the header).
    pub key: String,
    /// First comma token of the opening value, trimmed (names, RS, ...).
    pub name: String,
    pub lines: Range<usize>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CountedBlock {
    pub key: &'static str,
    pub spec: BlockSpec,
    pub header_line: usize,
    pub count: usize,
    /// Absolute bytes of the count token in the header line.
    pub count_span: Range<usize>,
    /// Payload lines consumed by the block.
    pub data_lines: Range<usize>,
    /// Absolute bytes covering the payload lines including terminators.
    pub data_span: Range<usize>,
    pub values: Vec<f64>,
    pub section: usize,
}

#[derive(Clone, Debug, PartialEq)]
pub struct ReachRecord {
    pub river: String,
    pub reach: String,
    pub section: usize,
    pub legacy: bool,
}

/// A `Type RM Length L Ch R` node (XS, culvert, bridge, inline/lateral
/// structure, ...). Identifiers are case-sensitive and kept verbatim.
#[derive(Clone, Debug, PartialEq)]
pub struct NodeRecord {
    pub river: Option<String>,
    pub reach: Option<String>,
    pub node_type: i64,
    pub station: String,
    pub lengths: [f64; 3],
    pub node_name: String,
    pub section: usize,
    pub blocks: Vec<usize>,
    pub bank_sta_line: Option<usize>,
}

#[derive(Clone, Debug)]
pub struct GeometryIndex {
    pub title: Option<String>,
    pub program_version: Option<String>,
    pub sections: Vec<Section>,
    pub reaches: Vec<ReachRecord>,
    pub nodes: Vec<NodeRecord>,
    pub blocks: Vec<CountedBlock>,
    pub diagnostics: Vec<Diagnostic>,
    node_lookup: HashMap<(String, String, String), usize>,
}

fn split_trimmed(value: &str) -> Vec<String> {
    value.split(',').map(|s| s.trim().to_string()).collect()
}

fn parse_f64(text: &str) -> Option<f64> {
    text.trim().parse::<f64>().ok()
}

fn diag(
    sev: Severity,
    code: &'static str,
    doc: &TextDocument,
    line: usize,
    msg: String,
) -> Diagnostic {
    Diagnostic {
        severity: sev,
        code,
        line,
        span: doc.lines()[line].content(),
        message: msg,
    }
}

impl GeometryIndex {
    /// Index a geometry document. Never mutates it; malformed spans become
    /// diagnostics (`Severity::Error` for count/payload disagreements).
    pub fn parse(doc: &TextDocument) -> Self {
        let n = doc.line_count();
        let mut diagnostics = Vec::new();

        // 1. Sections.
        let mut sections = vec![Section {
            kind: SectionKind::Header,
            key: String::new(),
            name: String::new(),
            lines: 0..0,
        }];
        for line in 0..n {
            if let Some(kind) = doc.key_name(line).and_then(section_kind_for_key) {
                sections.last_mut().unwrap().lines.end = line;
                let value = doc.value_text(line).unwrap_or_default();
                sections.push(Section {
                    kind,
                    key: latin1(doc.key_name(line).unwrap()),
                    name: split_trimmed(&value).into_iter().next().unwrap_or_default(),
                    lines: line..line,
                });
            }
        }
        sections.last_mut().unwrap().lines.end = n;
        let mut section_of_line = vec![0usize; n];
        for (s, sec) in sections.iter().enumerate() {
            for l in sec.lines.clone() {
                section_of_line[l] = s;
            }
        }

        // 2. Counted blocks.
        let mut blocks = Vec::new();
        for line in 0..n {
            let Some(key) = doc.key_name(line) else {
                continue;
            };
            let Some(spec) = BLOCK_SPECS.iter().find(|s| s.key.as_bytes() == key) else {
                continue;
            };
            let Some(count_span) = doc.value_token_span(line, 0) else {
                continue;
            };
            let count_text = latin1(&doc.as_bytes()[count_span.clone()]);
            let Ok(count) = count_text.parse::<usize>() else {
                diagnostics.push(diag(
                    Severity::Error,
                    "bad-count",
                    doc,
                    line,
                    format!(
                        "{}: count token '{count_text}' is not a non-negative integer",
                        spec.key
                    ),
                ));
                continue;
            };
            let Some(expected) = count.checked_mul(spec.values_per_item) else {
                diagnostics.push(diag(
                    Severity::Error,
                    "bad-count",
                    doc,
                    line,
                    format!("{}: count {count} overflows the value total", spec.key),
                ));
                continue;
            };
            // The count is untrusted input: reserve no more than the remaining
            // lines can hold, so a huge declared count cannot exhaust memory.
            let readable = (n - line - 1).saturating_mul(spec.values_per_line);
            let mut values = Vec::with_capacity(expected.min(readable));
            let mut cur = line + 1;
            while values.len() < expected && cur < n {
                if doc.key_line(cur).is_some() || doc.is_free_text(cur) {
                    break;
                }
                let content = doc.line_bytes(cur);
                let take = spec.values_per_line.min(expected - values.len());
                for k in 0..take {
                    let lo = (k * spec.width).min(content.len());
                    let hi = ((k + 1) * spec.width).min(content.len());
                    let slot = trim_ascii(&content[lo..hi]);
                    let parsed = std::str::from_utf8(slot)
                        .ok()
                        .and_then(|t| t.parse::<f64>().ok());
                    let value = match parsed {
                        _ if slot.is_empty() => {
                            if !spec.allow_blank {
                                diagnostics.push(diag(
                                    Severity::Error,
                                    "blank-slot",
                                    doc,
                                    cur,
                                    format!("{}: slot {k} is blank", spec.key),
                                ));
                            }
                            f64::NAN
                        }
                        Some(v) if v.is_finite() => v,
                        _ => {
                            diagnostics.push(diag(
                                Severity::Error,
                                "invalid-field",
                                doc,
                                cur,
                                format!(
                                    "{}: slot {k} '{}' is not a finite number",
                                    spec.key,
                                    latin1(slot)
                                ),
                            ));
                            f64::NAN
                        }
                    };
                    values.push(value);
                }
                let tail = &content[(take * spec.width).min(content.len())..];
                if !trim_ascii(tail).is_empty() {
                    diagnostics.push(diag(
                        Severity::Error,
                        "too-many-values",
                        doc,
                        cur,
                        format!("{}: data beyond {take} slots", spec.key),
                    ));
                }
                cur += 1;
            }
            if values.len() != expected {
                diagnostics.push(diag(
                    Severity::Error,
                    "count-mismatch",
                    doc,
                    line,
                    format!(
                        "{}: declared {count} items ({expected} values), read {}",
                        spec.key,
                        values.len()
                    ),
                ));
            }
            let lines = doc.lines();
            let data_span = if cur > line + 1 {
                lines[line + 1].start..lines[cur - 1].end
            } else {
                lines[line].end..lines[line].end
            };
            blocks.push(CountedBlock {
                key: spec.key,
                spec: *spec,
                header_line: line,
                count,
                count_span,
                data_lines: line + 1..cur,
                data_span,
                values,
                section: section_of_line[line],
            });
        }

        // 3. Reaches and nodes.
        let mut reaches = Vec::new();
        let mut nodes = Vec::new();
        let mut node_lookup = HashMap::new();
        let mut current: Option<(String, String)> = None;
        for (s, sec) in sections.iter().enumerate() {
            let head = sec.lines.start;
            match sec.kind {
                SectionKind::Reach => {
                    let value = doc.value_text(head).unwrap_or_default();
                    let legacy = sec.key == "Reach";
                    let parts = split_trimmed(&value);
                    let pair = if legacy {
                        (!value.is_empty()).then(|| (value.clone(), value.clone()))
                    } else if parts.len() >= 2 && !parts[0].is_empty() && !parts[1].is_empty() {
                        Some((parts[0].clone(), parts[1].clone()))
                    } else {
                        None
                    };
                    match pair {
                        Some((river, reach)) => {
                            current = Some((river.clone(), reach.clone()));
                            reaches.push(ReachRecord {
                                river,
                                reach,
                                section: s,
                                legacy,
                            });
                        }
                        None => diagnostics.push(diag(
                            Severity::Error,
                            "bad-reach",
                            doc,
                            head,
                            "reach header lacks river/reach names".into(),
                        )),
                    }
                }
                SectionKind::Node => {
                    let value = doc.value_text(head).unwrap_or_default();
                    let parts = split_trimmed(&value);
                    if parts.len() < 4 {
                        diagnostics.push(diag(
                            Severity::Error,
                            "bad-node-header",
                            doc,
                            head,
                            format!("node header has {} fields, expected >= 4", parts.len()),
                        ));
                        continue;
                    }
                    let node_type = if parts[0].is_empty() {
                        Some(1)
                    } else {
                        parts[0].parse().ok()
                    };
                    let Some(node_type) = node_type else {
                        diagnostics.push(diag(
                            Severity::Error,
                            "bad-node-type",
                            doc,
                            head,
                            format!("node type '{}' is not an integer", parts[0]),
                        ));
                        continue;
                    };
                    // Blank lengths are 0.0 (as in Python); a non-numeric
                    // token is reported so callers can skip the node exactly
                    // like `GeomCrossSection.get_cross_sections` does.
                    if let Some(bad) = parts
                        .iter()
                        .take(5)
                        .skip(2)
                        .find(|p| !p.is_empty() && parse_f64(p).is_none())
                    {
                        diagnostics.push(diag(
                            Severity::Warning,
                            "bad-node-length",
                            doc,
                            head,
                            format!("node length '{bad}' is not a number"),
                        ));
                    }
                    let length = |i: usize| parts.get(i).and_then(|p| parse_f64(p)).unwrap_or(0.0);
                    let mut node_name = String::new();
                    let mut bank_sta_line = None;
                    for l in sec.lines.clone() {
                        match doc.key_name(l) {
                            Some(b"Node Name") if node_name.is_empty() => {
                                node_name = doc.value_text(l).unwrap_or_default()
                            }
                            Some(b"Bank Sta") if bank_sta_line.is_none() => bank_sta_line = Some(l),
                            _ => {}
                        }
                    }
                    let node_blocks: Vec<usize> = blocks
                        .iter()
                        .enumerate()
                        .filter(|(_, b)| b.section == s)
                        .map(|(i, _)| i)
                        .collect();
                    if current.is_none() {
                        diagnostics.push(diag(
                            Severity::Warning,
                            "node-without-reach",
                            doc,
                            head,
                            "node appears before any reach header".into(),
                        ));
                    }
                    let (river, reach) = current.clone().unzip();
                    let idx = nodes.len();
                    if let (Some(r), Some(h)) = (&river, &reach) {
                        let key = (r.clone(), h.clone(), parts[1].clone());
                        match node_lookup.entry(key) {
                            Entry::Occupied(_) => diagnostics.push(diag(
                                Severity::Warning,
                                "duplicate-node-id",
                                doc,
                                head,
                                format!("duplicate node {r}/{h}/{}", parts[1]),
                            )),
                            Entry::Vacant(slot) => {
                                slot.insert(idx);
                            }
                        }
                    }
                    nodes.push(NodeRecord {
                        river,
                        reach,
                        node_type,
                        station: parts[1].clone(),
                        lengths: [length(2), length(3), length(4)],
                        node_name,
                        section: s,
                        blocks: node_blocks,
                        bank_sta_line,
                    });
                }
                _ => {}
            }
        }

        for node in nodes.iter().filter(|n| n.node_type == 1) {
            let head = sections[node.section].lines.start;
            let count_of = |key: &str| {
                node.blocks
                    .iter()
                    .map(|&b| &blocks[b])
                    .find(|b| b.key == key)
                    .map(|b| b.count)
            };
            if count_of("#Sta/Elev").is_some_and(|c| c > MAX_XS_POINTS) {
                diagnostics.push(diag(
                    Severity::Warning,
                    "xs-point-limit",
                    doc,
                    head,
                    format!("XS {} exceeds {MAX_XS_POINTS} points", node.station),
                ));
            }
            if count_of("#Mann").is_some_and(|c| c > MAX_MANNINGS_N_BLOCKS) {
                diagnostics.push(diag(
                    Severity::Warning,
                    "mannings-block-limit",
                    doc,
                    head,
                    format!(
                        "XS {} exceeds {MAX_MANNINGS_N_BLOCKS} Manning's n blocks",
                        node.station
                    ),
                ));
            }
        }

        Self {
            title: doc.first_value("Geom Title"),
            program_version: doc.first_value("Program Version"),
            sections,
            reaches,
            nodes,
            blocks,
            diagnostics,
            node_lookup,
        }
    }

    /// Exact, case-sensitive lookup; the first occurrence wins (as in Python).
    pub fn find_node(&self, river: &str, reach: &str, station: &str) -> Option<usize> {
        self.node_lookup
            .get(&(river.to_string(), reach.to_string(), station.to_string()))
            .copied()
    }

    pub fn node_block(&self, node: usize, key: &str) -> Option<&CountedBlock> {
        self.nodes[node]
            .blocks
            .iter()
            .map(|&b| &self.blocks[b])
            .find(|b| b.key == key)
    }

    pub fn station_elevation(&self, node: usize) -> Option<Vec<(f64, f64)>> {
        self.node_block(node, "#Sta/Elev").map(|b| {
            b.values
                .as_chunks::<2>()
                .0
                .iter()
                .map(|c| (c[0], c[1]))
                .collect()
        })
    }

    pub fn mannings_n(&self, node: usize) -> Option<Vec<(f64, f64, f64)>> {
        self.node_block(node, "#Mann").map(|b| {
            b.values
                .as_chunks::<3>()
                .0
                .iter()
                .map(|c| (c[0], c[1], c[2]))
                .collect()
        })
    }

    pub fn bank_stations(&self, doc: &TextDocument, node: usize) -> Option<(f64, f64)> {
        let line = self.nodes[node].bank_sta_line?;
        let parts = split_trimmed(&doc.value_text(line)?);
        Some((parse_f64(parts.first()?)?, parse_f64(parts.get(1)?)?))
    }

    pub fn error_count(&self) -> usize {
        self.diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Error)
            .count()
    }

    fn block_rewrite(
        &self,
        doc: &TextDocument,
        block: &CountedBlock,
        count: usize,
        values: &[f64],
        specs: &[FormatSpec],
        label: &str,
    ) -> Result<EditBatch, TextError> {
        let newline = doc.encoding().dominant_newline();
        let payload = format_lines(
            values,
            specs,
            block.spec.values_per_line,
            newline.as_bytes(),
        )?;
        let mut batch = EditBatch::new();
        batch.replace(
            block.count_span.clone(),
            count.to_string().into_bytes(),
            format!("{label}:count"),
        );
        // Preserve a missing final newline: if the block ends the file without
        // a terminator, the rewritten block must not add one.
        let mut data = payload;
        let last = if block.data_lines.is_empty() {
            block.header_line
        } else {
            block.data_lines.end - 1
        };
        if doc.newline(last) == super::Newline::Eof && !data.is_empty() {
            data.truncate(data.len() - newline.as_bytes().len());
            if block.data_lines.is_empty() {
                data.splice(0..0, newline.as_bytes().iter().copied());
            }
        }
        batch.replace(block.data_span.clone(), data, format!("{label}:data"));
        Ok(batch)
    }

    /// Replace a cross section's station/elevation table (count + payload).
    /// Stations must be finite and non-decreasing, 1..=500 points, and the
    /// existing bank stations must stay within the new station range.
    pub fn edit_station_elevation(
        &self,
        doc: &TextDocument,
        node: usize,
        points: &[(f64, f64)],
    ) -> Result<EditBatch, TextError> {
        let rec = &self.nodes[node];
        let block = self
            .node_block(node, "#Sta/Elev")
            .ok_or_else(|| TextError::NotFound(format!("#Sta/Elev in node {}", rec.station)))?;
        if points.is_empty() || points.len() > MAX_XS_POINTS {
            return Err(TextError::Invalid(format!(
                "station/elevation needs 1..={MAX_XS_POINTS} points, got {}",
                points.len()
            )));
        }
        if points.windows(2).any(|w| w[1].0 < w[0].0) {
            return Err(TextError::Invalid("stations must be non-decreasing".into()));
        }
        if let Some((l, r)) = self.bank_stations(doc, node) {
            let (lo, hi) = (points[0].0, points[points.len() - 1].0);
            if l < lo || r > hi {
                return Err(TextError::Invalid(format!(
                    "bank stations {l},{r} fall outside new station range {lo}..{hi}"
                )));
            }
        }
        let values: Vec<f64> = points.iter().flat_map(|&(s, e)| [s, e]).collect();
        let fmt = [FormatSpec::new(8, 2)];
        self.block_rewrite(
            doc,
            block,
            points.len(),
            &values,
            &fmt,
            &format!("sta_elev:{}", rec.station),
        )
    }

    /// Replace a cross section's Manning's n triplets (station, n, change
    /// flag). Only the count token and payload are rewritten; the remaining
    /// `#Mann=` header fields are preserved verbatim.
    pub fn edit_mannings_n(
        &self,
        doc: &TextDocument,
        node: usize,
        triplets: &[(f64, f64, f64)],
    ) -> Result<EditBatch, TextError> {
        let rec = &self.nodes[node];
        let block = self
            .node_block(node, "#Mann")
            .ok_or_else(|| TextError::NotFound(format!("#Mann in node {}", rec.station)))?;
        if triplets.is_empty() || triplets.len() > MAX_MANNINGS_N_BLOCKS {
            return Err(TextError::Invalid(format!(
                "Manning's n needs 1..={MAX_MANNINGS_N_BLOCKS} blocks, got {}",
                triplets.len()
            )));
        }
        if triplets.windows(2).any(|w| w[1].0 < w[0].0) {
            return Err(TextError::Invalid(
                "Manning's n stations must be non-decreasing".into(),
            ));
        }
        let values: Vec<f64> = triplets.iter().flat_map(|&(s, n, f)| [s, n, f]).collect();
        let fmt = [
            FormatSpec::new(8, 2),
            FormatSpec::new(8, 3),
            FormatSpec::new(8, 0),
        ];
        self.block_rewrite(
            doc,
            block,
            triplets.len(),
            &values,
            &fmt,
            &format!("mann:{}", rec.station),
        )
    }

    /// Replace only the two `Bank Sta=` value tokens. Each token keeps its
    /// existing decimal precision (as `_bank_station_line` does) but never
    /// fewer decimals than the new value needs, so edits cannot silently
    /// round a bank station.
    pub fn edit_bank_stations(
        &self,
        doc: &TextDocument,
        node: usize,
        left: f64,
        right: f64,
    ) -> Result<EditBatch, TextError> {
        let rec = &self.nodes[node];
        let line = rec
            .bank_sta_line
            .ok_or_else(|| TextError::NotFound(format!("Bank Sta in node {}", rec.station)))?;
        if !(left.is_finite() && right.is_finite()) || left > right {
            return Err(TextError::Invalid(format!(
                "invalid bank stations {left},{right}"
            )));
        }
        if let Some(pts) = self.station_elevation(node) {
            if let (Some(first), Some(last)) = (pts.first(), pts.last()) {
                if left < first.0 || right > last.0 {
                    return Err(TextError::Invalid(format!(
                        "bank stations {left},{right} outside station range {}..{}",
                        first.0, last.0
                    )));
                }
            }
        }
        let mut batch = EditBatch::new();
        for (i, v) in [(0, left), (1, right)] {
            let span = doc
                .value_token_span(line, i)
                .ok_or_else(|| TextError::Invalid("Bank Sta= needs two values".into()))?;
            let original = latin1(&doc.as_bytes()[span.clone()]);
            let text = format_numeric_like(v, &original, shortest_decimals(v));
            batch.replace(
                span,
                text.into_bytes(),
                format!("bank_sta:{}:{i}", rec.station),
            );
        }
        Ok(batch)
    }
}

/// Python `f"{value:g}"` for finite values.
pub fn format_g(value: f64) -> String {
    if value == 0.0 {
        return if value.is_sign_negative() {
            "-0".into()
        } else {
            "0".into()
        };
    }
    let exp = value.abs().log10().floor() as i32;
    // Re-derive the exponent after rounding to 6 significant digits.
    let sci = format!("{:.5e}", value);
    let (mantissa, e) = sci.split_once('e').unwrap();
    let e: i32 = e.parse().unwrap_or(exp);
    if !(-4..6).contains(&e) {
        let m = mantissa.trim_end_matches('0').trim_end_matches('.');
        let sign = if e < 0 { '-' } else { '+' };
        return format!("{m}e{sign}{:02}", e.abs());
    }
    let decimals = (5 - e).max(0) as usize;
    let text = format!("{value:.decimals$}");
    if text.contains('.') {
        text.trim_end_matches('0').trim_end_matches('.').to_string()
    } else {
        text
    }
}

/// Decimal places of the shortest representation that round-trips `value`.
pub fn shortest_decimals(value: f64) -> usize {
    format!("{value}")
        .split_once('.')
        .map_or(0, |(_, frac)| frac.len())
}

/// `GeomCrossSection._format_numeric_like`: reuse the original token's
/// decimal count, raised to `min_decimals`. Unlike the Python helper, a
/// positive `min_decimals` also applies to integer-looking originals.
pub fn format_numeric_like(value: f64, original: &str, min_decimals: usize) -> String {
    match original.trim().split_once('.') {
        Some((_, frac)) => {
            let decimals = frac.len().max(min_decimals);
            format!("{value:.decimals$}")
        }
        None if min_decimals > 0 => format!("{value:.min_decimals$}"),
        None if value.fract() == 0.0 && value.abs() < 1e15 => format!("{}", value as i64),
        None => format_g(value),
    }
}
