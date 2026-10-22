//! `ras_text_probe` — JSON probe used by ras_text_conformance_test.py.
//!
//! ```text
//! ras_text_probe scan <file>...            # index + round-trip report per file
//! ras_text_probe edit <in> <out> <spec>    # apply a JSON batch once, atomically
//! ```
//! Inputs are only read; outputs go to the explicit `<out>` path.

use std::path::Path;
use std::time::Instant;

use ras_text_conformance::ras_text::{
    apply_batch, write_atomic, Diagnostic, EditBatch, GeometryIndex, TextDocument,
};
use serde_json::{json, Value};

fn diag_json(d: &Diagnostic) -> Value {
    json!({"severity": d.severity.as_str(), "code": d.code, "line": d.line,
           "span": [d.span.start, d.span.end], "message": d.message})
}

fn is_geometry(path: &Path) -> bool {
    path.extension().and_then(|e| e.to_str()).is_some_and(|e| {
        e.len() == 3 && e.starts_with('g') && e[1..].bytes().all(|b| b.is_ascii_digit())
    })
}

fn scan(path: &Path) -> Value {
    let original = match std::fs::read(path) {
        Ok(b) => b,
        Err(e) => return json!({"path": path.display().to_string(), "error": e.to_string()}),
    };
    let t0 = Instant::now();
    let doc = TextDocument::parse(original.clone());
    let parse_ns = t0.elapsed().as_nanos() as u64;

    // Span coverage: concatenated line spans must rebuild the input exactly.
    let mut rebuilt = Vec::with_capacity(original.len());
    for span in doc.lines() {
        rebuilt.extend_from_slice(&doc.as_bytes()[span.full()]);
    }
    let empty = apply_batch(doc.as_bytes(), &EditBatch::new()).map(|r| r.bytes);
    let enc = doc.encoding();
    let mut out = json!({
        "path": path.display().to_string(),
        "bytes": original.len(),
        "lines": doc.line_count(),
        "identity_roundtrip": doc.as_bytes() == original.as_slice(),
        "span_roundtrip": rebuilt == original,
        "empty_batch_roundtrip": empty.as_deref() == Ok(original.as_slice()),
        "parse_ns": parse_ns,
        "encoding": {"utf8_bom": enc.utf8_bom, "valid_utf8": enc.valid_utf8,
                     "non_ascii_bytes": enc.non_ascii_bytes, "nul_bytes": enc.nul_bytes,
                     "lf": enc.lf, "crlf": enc.crlf, "cr": enc.cr, "final_newline": enc.final_newline},
        "keys": doc.key_counts().into_iter().map(|(k, n)| json!([k, n])).collect::<Vec<_>>(),
        "doc_diagnostics": doc.diagnostics().iter().map(diag_json).collect::<Vec<_>>(),
    });
    if is_geometry(path) {
        let t1 = Instant::now();
        let gi = GeometryIndex::parse(&doc);
        let geom_ns = t1.elapsed().as_nanos() as u64;
        let nodes: Vec<Value> = gi
            .nodes
            .iter()
            .enumerate()
            .map(|(i, n)| {
                json!({
                    "river": n.river, "reach": n.reach, "rs": n.station, "type": n.node_type,
                    "lengths": n.lengths, "node_name": n.node_name,
                    "sta_elev": gi.station_elevation(i).map(|v| v.into_iter().map(|(a, b)| [a, b]).collect::<Vec<_>>()),
                    "mann": gi.mannings_n(i).map(|v| v.into_iter().map(|(a, b, c)| [a, b, c]).collect::<Vec<_>>()),
                    "bank": gi.bank_stations(&doc, i).map(|(a, b)| [a, b]),
                    "lines": [gi.sections[n.section].lines.start, gi.sections[n.section].lines.end],
                })
            })
            .collect();
        let mut block_stats = std::collections::BTreeMap::<&str, (usize, usize, usize)>::new();
        for b in &gi.blocks {
            let e = block_stats.entry(b.key).or_default();
            e.0 += 1;
            e.1 += b.count;
            e.2 = e.2.max(b.data_lines.len());
        }
        let mut section_kinds = std::collections::BTreeMap::<&str, usize>::new();
        for s in &gi.sections {
            *section_kinds.entry(s.kind.as_str()).or_default() += 1;
        }
        out["geometry"] = json!({
            "parse_ns": geom_ns,
            "title": gi.title, "program_version": gi.program_version,
            "reaches": gi.reaches.iter().map(|r| json!([r.river, r.reach, r.legacy])).collect::<Vec<_>>(),
            "sections": section_kinds,
            "blocks": block_stats.into_iter().map(|(k, (n, items, maxpl))| json!({"key": k, "blocks": n, "items": items, "max_data_lines": maxpl})).collect::<Vec<_>>(),
            "nodes": nodes,
            "diagnostics": gi.diagnostics.iter().map(diag_json).collect::<Vec<_>>(),
        });
    }
    out
}

fn f64s(v: &Value) -> Vec<Vec<f64>> {
    v.as_array()
        .map(|rows| {
            rows.iter()
                .map(|r| {
                    r.as_array()
                        .unwrap()
                        .iter()
                        .map(|x| x.as_f64().unwrap())
                        .collect()
                })
                .collect()
        })
        .unwrap_or_default()
}

fn edit(input: &Path, output: &Path, spec: &Path) -> Result<Value, String> {
    if input == output {
        return Err("refusing to overwrite the input; originals are immutable".into());
    }
    let spec: Value = serde_json::from_slice(&std::fs::read(spec).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    let doc = TextDocument::read(input).map_err(|e| e.to_string())?;
    let t0 = Instant::now();
    let gi = GeometryIndex::parse(&doc);
    let mut batch = EditBatch::new();
    for op in spec["ops"].as_array().ok_or("spec.ops must be a list")? {
        let s = |k: &str| op[k].as_str().unwrap_or_default().to_string();
        let node = gi
            .find_node(&s("river"), &s("reach"), &s("rs"))
            .ok_or_else(|| format!("node {}/{}/{} not found", s("river"), s("reach"), s("rs")))?;
        let part = match op["op"].as_str() {
            Some("sta_elev") => {
                let pts: Vec<(f64, f64)> =
                    f64s(&op["points"]).iter().map(|p| (p[0], p[1])).collect();
                gi.edit_station_elevation(&doc, node, &pts)
            }
            Some("mann") => {
                let t: Vec<(f64, f64, f64)> = f64s(&op["triplets"])
                    .iter()
                    .map(|p| (p[0], p[1], p[2]))
                    .collect();
                gi.edit_mannings_n(&doc, node, &t)
            }
            Some("bank") => gi.edit_bank_stations(
                &doc,
                node,
                op["left"].as_f64().unwrap_or(f64::NAN),
                op["right"].as_f64().unwrap_or(f64::NAN),
            ),
            other => return Err(format!("unknown op {other:?}")),
        }
        .map_err(|e| e.to_string())?;
        batch.extend(part);
    }
    let result = apply_batch(doc.as_bytes(), &batch).map_err(|e| e.to_string())?;
    let edit_ns = t0.elapsed().as_nanos() as u64;
    write_atomic(output, &result.bytes).map_err(|e| e.to_string())?;
    let reparsed = GeometryIndex::parse(&TextDocument::parse(result.bytes.clone()));
    Ok(json!({
        "input": input.display().to_string(), "output": output.display().to_string(),
        "edit_ns": edit_ns, "edits": batch.len(),
        "spans": result.spans.iter().map(|s| json!({"label": s.label, "original": [s.original.start, s.original.end], "updated": [s.updated.start, s.updated.end]})).collect::<Vec<_>>(),
        "reparse_errors": reparsed.error_count(),
    }))
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("scan") => Ok(json!(args[1..]
            .iter()
            .map(|p| scan(Path::new(p)))
            .collect::<Vec<_>>())),
        Some("edit") if args.len() == 4 => edit(
            Path::new(&args[1]),
            Path::new(&args[2]),
            Path::new(&args[3]),
        ),
        _ => Err("usage: ras_text_probe scan <file>... | edit <in> <out> <spec.json>".into()),
    };
    match result {
        Ok(v) => println!("{v}"),
        Err(e) => {
            println!("{}", json!({"error": e}));
            std::process::exit(2);
        }
    }
}
