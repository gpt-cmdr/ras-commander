//! Synthetic edge cases for the lossless text core. Real-model qualification
//! lives in ras_text_conformance_test.py; these pin behaviours the corpus may
//! not exercise (lone CR, no final newline, BOM, Latin-1, malformed counts).

use ras_text_conformance::ras_text::fixed_width::{
    format_value, parse_values, split_fields, FieldKind, FormatSpec,
};
use ras_text_conformance::ras_text::geometry::{format_g, format_numeric_like, shortest_decimals};
use ras_text_conformance::ras_text::{
    apply_batch, write_atomic, EditBatch, GeometryIndex, Newline, Severity, TextDocument,
    TextError, MAX_MANNINGS_N_BLOCKS, MAX_XS_POINTS,
};

// CRLF document whose final line has no terminator.
const XS_LF: &str = r"Geom Title=Synthetic
Program Version=6.60
River Reach=Creek           ,Upper~~~~~~~~~~~
Type RM Length L Ch R = 1 ,100.5   ,10,20,30
BEGIN DESCRIPTION:
free text with Key=Value inside
END DESCRIPTION:
#Sta/Elev= 3~
       0     110      50     100     100   110.5
#Mann= 2 , 0 , 0~
       0     .06       0      50     .04       0
Bank Sta=10,90.0
Type RM Length L Ch R = 1 ,100.5*  ,10,20,30
#Sta/Elev= 2~
       0     110     100     110
Type RM Length L Ch R = 1 ,upper   ,1,1,1
#Sta/Elev= 1~
       0       1";

fn xs() -> String {
    // '~' marks significant trailing blanks that editors would strip.
    XS_LF.replace('~', " ").replace('\n', "\r\n")
}

fn doc(text: &str) -> TextDocument {
    TextDocument::parse(text.as_bytes().to_vec())
}

#[test]
fn identity_and_span_roundtrip_for_every_newline_style() {
    let cases: [&[u8]; 8] = [
        b"",
        b"A=1",
        b"A=1\n",
        b"A=1\r\nB=2\r\n",
        b"A=1\rB=2\r",
        b"A=1\r\r\nB=2\n\nC=3",
        b"\xEF\xBB\xBFA=caf\xE9\r\n",
        b"A=\x00\x80\xFF\n\n\n",
    ];
    for bytes in cases {
        let d = TextDocument::parse(bytes.to_vec());
        assert_eq!(d.as_bytes(), bytes);
        let rebuilt: Vec<u8> = d
            .lines()
            .iter()
            .flat_map(|s| d.as_bytes()[s.full()].to_vec())
            .collect();
        assert_eq!(rebuilt, bytes, "span coverage for {bytes:?}");
        assert_eq!(apply_batch(bytes, &EditBatch::new()).unwrap().bytes, bytes);
    }
}

#[test]
fn newline_kinds_and_encoding_facts() {
    let d = TextDocument::parse(b"A=1\r\nB=2\nC=3\rD=4".to_vec());
    let kinds: Vec<Newline> = (0..d.line_count()).map(|l| d.newline(l)).collect();
    assert_eq!(
        kinds,
        [Newline::CrLf, Newline::Lf, Newline::Cr, Newline::Eof]
    );
    assert!(!d.encoding().final_newline);
    assert!(d.diagnostics().iter().any(|x| x.code == "mixed-newlines"));

    let latin = TextDocument::parse(b"\xEF\xBB\xBFGeom Title=Ca\xF1on\r\n".to_vec());
    assert!(latin.encoding().utf8_bom);
    assert!(!latin.encoding().valid_utf8);
    assert_eq!(latin.encoding().non_ascii_bytes, 4);
    // The BOM is part of the first key's bytes; nothing is stripped silently.
    assert!(latin.lines_with_key("Geom Title").is_empty());
    assert_eq!(latin.value_text(0).as_deref(), Some("Ca\u{f1}on"));
}

#[test]
fn keys_are_case_sensitive_and_descriptions_are_free_text() {
    let d = doc(&xs());
    assert_eq!(d.lines_with_key("Type RM Length L Ch R").len(), 3);
    assert!(d.lines_with_key("type rm length l ch r").is_empty());
    assert!(d.lines_with_key("free text with Key").is_empty());
    assert!(d.is_free_text(5));
    assert_eq!(d.first_value("Program Version").as_deref(), Some("6.60"));

    let unterminated = doc("BEGIN DESCRIPTION:\nX=1\n");
    assert_eq!(unterminated.lines_with_key("X").len(), 1);
    assert!(unterminated
        .diagnostics()
        .iter()
        .any(|x| x.code == "unterminated-description"));
}

#[test]
fn geometry_index_reads_nodes_blocks_and_ids_verbatim() {
    let d = doc(&xs());
    let g = GeometryIndex::parse(&d);
    assert_eq!(g.error_count(), 0, "{:?}", g.diagnostics);
    assert_eq!(g.title.as_deref(), Some("Synthetic"));
    assert_eq!(g.reaches.len(), 1);
    assert_eq!(
        (g.reaches[0].river.as_str(), g.reaches[0].reach.as_str()),
        ("Creek", "Upper")
    );
    let ids: Vec<&str> = g.nodes.iter().map(|n| n.station.as_str()).collect();
    assert_eq!(ids, ["100.5", "100.5*", "upper"]);
    let a = g.find_node("Creek", "Upper", "100.5").unwrap();
    assert_ne!(Some(a), g.find_node("Creek", "Upper", "100.5*"));
    assert!(g.find_node("creek", "Upper", "100.5").is_none());
    assert_eq!(g.nodes[a].lengths, [10.0, 20.0, 30.0]);
    assert_eq!(
        g.station_elevation(a).unwrap(),
        [(0.0, 110.0), (50.0, 100.0), (100.0, 110.5)]
    );
    assert_eq!(
        g.mannings_n(a).unwrap(),
        [(0.0, 0.06, 0.0), (50.0, 0.04, 0.0)]
    );
    assert_eq!(g.bank_stations(&d, a), Some((10.0, 90.0)));
    // Final line has no terminator; block still parses.
    let last = g.find_node("Creek", "Upper", "upper").unwrap();
    assert_eq!(g.station_elevation(last).unwrap(), [(0.0, 1.0)]);
}

#[test]
fn malformed_counts_and_fields_are_diagnosed_not_fatal() {
    let text = r"River Reach=R,S
Type RM Length L Ch R = 1 ,1,0,0,0
#Sta/Elev= 3~
       0     110      50
Bank Sta=0,1
Type RM Length L Ch R = 1 ,2,0,0,0
#Sta/Elev= x~
Type RM Length L Ch R = 1 ,3,0,0,0
#Sta/Elev= 1~
       0 1e99abc
Type RM Length L Ch R = 1 ,4,0,0,0
#Sta/Elev= 1~
       0     110     999
Type RM Length L Ch R = zz ,5,0,0,0
Type RM Length L Ch R = 1 ,6,0,0,0
#Sta/Elev= 2~
Bank Sta=0,1
";
    let text = text.replace('~', " ");
    let d = doc(&text);
    let g = GeometryIndex::parse(&d);
    let codes: Vec<&str> = g.diagnostics.iter().map(|x| x.code).collect();
    for code in [
        "blank-slot",
        "count-mismatch",
        "bad-count",
        "invalid-field",
        "too-many-values",
        "bad-node-type",
    ] {
        assert!(codes.contains(&code), "missing {code} in {codes:?}");
    }
    assert!(g.diagnostics.iter().all(|x| x.severity == Severity::Error));
    assert_eq!(d.as_bytes(), text.as_bytes());
}

#[test]
fn blank_slots_are_missing_values() {
    let d = doc("Storage Area=SA,1,2\nStorage Area Vol Elev= 1 \n               0\n");
    let g = GeometryIndex::parse(&d);
    assert_eq!(g.error_count(), 0);
    let b = &g.blocks[0];
    assert!(b.values[0].is_nan());
    assert_eq!(b.values[1], 0.0);
}

#[test]
fn batch_edits_touch_only_intended_spans() {
    let d = doc(&xs());
    let g = GeometryIndex::parse(&d);
    let a = g.find_node("Creek", "Upper", "100.5").unwrap();
    let b = g.find_node("Creek", "Upper", "100.5*").unwrap();
    let mut batch = g
        .edit_station_elevation(
            &d,
            a,
            &[(0.0, 111.0), (25.0, 105.0), (50.0, 99.5), (100.0, 110.0)],
        )
        .unwrap();
    batch.extend(
        g.edit_mannings_n(
            &d,
            a,
            &[(0.0, 0.07, 0.0), (10.0, 0.035, 0.0), (90.0, 0.07, 0.0)],
        )
        .unwrap(),
    );
    batch.extend(g.edit_bank_stations(&d, a, 12.5, 88.25).unwrap());
    batch.extend(
        g.edit_station_elevation(&d, b, &[(0.0, 1.0), (1.0, 2.0)])
            .unwrap(),
    );
    let (out, result) = d.apply(&batch).unwrap();
    let text = String::from_utf8(out.as_bytes().to_vec()).unwrap();
    assert!(text.contains(
        "#Sta/Elev= 4 \r\n    0.00  111.00   25.00  105.00   50.00   99.50  100.00  110.00\r\n"
    ));
    assert!(text.contains("#Mann= 3 , 0 , 0 \r\n    0.00   0.070       0   10.00   0.035       0   90.00   0.070       0\r\n"));
    // Precision of the original tokens ("10", "90.0") is kept.
    assert!(text.contains("Bank Sta=12.5,88.25\r\n"), "{text}");
    // Bytes outside the applied spans are untouched.
    let mut cursor_src = 0;
    let mut cursor_out = 0;
    for span in &result.spans {
        assert_eq!(
            &d.as_bytes()[cursor_src..span.original.start],
            &out.as_bytes()[cursor_out..span.updated.start]
        );
        cursor_src = span.original.end;
        cursor_out = span.updated.end;
    }
    assert_eq!(&d.as_bytes()[cursor_src..], &out.as_bytes()[cursor_out..]);
    let g2 = GeometryIndex::parse(&out);
    assert_eq!(g2.error_count(), 0);
    let a2 = g2.find_node("Creek", "Upper", "100.5").unwrap();
    assert_eq!(g2.station_elevation(a2).unwrap().len(), 4);
    assert_eq!(g2.mannings_n(a2).unwrap()[1], (10.0, 0.035, 0.0));
}

#[test]
fn edit_on_unterminated_final_block_keeps_missing_newline() {
    let d = doc(&xs());
    let g = GeometryIndex::parse(&d);
    let last = g.find_node("Creek", "Upper", "upper").unwrap();
    let (out, _) = d
        .apply(
            &g.edit_station_elevation(&d, last, &[(0.0, 1.0), (5.0, 2.0)])
                .unwrap(),
        )
        .unwrap();
    assert!(out
        .as_bytes()
        .ends_with(b"#Sta/Elev= 2 \r\n    0.00    1.00    5.00    2.00"));
    assert!(!out.encoding().final_newline);
}

#[test]
fn limits_and_invariants_reject_whole_edit() {
    let d = doc(&xs());
    let g = GeometryIndex::parse(&d);
    let a = g.find_node("Creek", "Upper", "100.5").unwrap();
    let too_many: Vec<(f64, f64)> = (0..=MAX_XS_POINTS).map(|i| (i as f64, 1.0)).collect();
    assert!(matches!(
        g.edit_station_elevation(&d, a, &too_many),
        Err(TextError::Invalid(_))
    ));
    let ok: Vec<(f64, f64)> = (0..MAX_XS_POINTS).map(|i| (i as f64 * 0.2, 1.0)).collect();
    assert!(g.edit_station_elevation(&d, a, &ok).is_ok());
    assert!(g
        .edit_station_elevation(&d, a, &[(5.0, 1.0), (1.0, 1.0)])
        .is_err());
    // Banks (10, 90) must stay inside the new station range.
    assert!(g
        .edit_station_elevation(&d, a, &[(20.0, 1.0), (100.0, 1.0)])
        .is_err());
    let mann: Vec<(f64, f64, f64)> = (0..=MAX_MANNINGS_N_BLOCKS)
        .map(|i| (i as f64, 0.03, 0.0))
        .collect();
    assert!(g.edit_mannings_n(&d, a, &mann).is_err());
    assert!(g
        .edit_mannings_n(&d, a, &mann[..MAX_MANNINGS_N_BLOCKS])
        .is_ok());
    assert!(g.edit_bank_stations(&d, a, 90.0, 10.0).is_err());
    assert!(g.edit_bank_stations(&d, a, -1.0, 10.0).is_err());
    assert!(matches!(
        g.edit_station_elevation(&d, a, &[(0.0, 123456789.0), (100.0, 1.0)]),
        Err(TextError::FieldOverflow { .. })
    ));
}

#[test]
fn overlapping_or_ambiguous_batches_are_rejected() {
    let src = b"0123456789";
    let mut b = EditBatch::new();
    b.replace(2..5, b"x".to_vec(), "a");
    b.replace(4..6, b"y".to_vec(), "b");
    assert!(matches!(
        apply_batch(src, &b),
        Err(TextError::OverlappingEdits { .. })
    ));
    let mut b = EditBatch::new();
    b.insert(3, b"x".to_vec(), "a");
    b.replace(3..4, b"y".to_vec(), "b");
    assert!(apply_batch(src, &b).is_err());
    let mut b = EditBatch::new();
    b.replace(8..11, b"x".to_vec(), "oob");
    assert!(matches!(
        apply_batch(src, &b),
        Err(TextError::SpanOutOfBounds { .. })
    ));
    // Adjacent edits and an insert after a replacement are deterministic.
    let mut b = EditBatch::new();
    b.replace(6..8, b"B".to_vec(), "b");
    b.replace(0..2, b"A".to_vec(), "a");
    b.insert(8, b"+".to_vec(), "c");
    b.replace(2..4, Vec::new(), "d");
    assert_eq!(apply_batch(src, &b).unwrap().bytes, b"A45B+89");
}

#[test]
fn same_node_edits_conflict_instead_of_double_applying() {
    let d = doc(&xs());
    let g = GeometryIndex::parse(&d);
    let a = g.find_node("Creek", "Upper", "100.5").unwrap();
    let mut batch = g
        .edit_station_elevation(&d, a, &[(0.0, 1.0), (100.0, 2.0)])
        .unwrap();
    batch.extend(
        g.edit_station_elevation(&d, a, &[(0.0, 3.0), (100.0, 4.0)])
            .unwrap(),
    );
    assert!(matches!(
        d.apply(&batch),
        Err(TextError::OverlappingEdits { .. })
    ));
}

#[test]
fn fixed_width_parser_matches_python_semantics() {
    // GeomParser.parse_fixed_width docstring examples.
    assert_eq!(
        parse_values(b"       0  963.04    27.2  963.04   32.64  963.02", 8),
        [0.0, 963.04, 27.2, 963.04, 32.64, 963.02]
    );
    assert_eq!(
        parse_values(
            b"   648224.43125   4551425.84375   648229.43125   4551425.84375",
            16
        ),
        [648224.43125, 4551425.84375, 648229.43125, 4551425.84375]
    );
    // Full-width 16-char coordinates with no separating blanks.
    assert_eq!(
        parse_values(b"2082012.57018957  364028.110016", 16),
        [2082012.57018957, 364028.110016]
    );
    let f = split_fields(b"    12.5-1.2.3          ", 8);
    assert_eq!(f[0].kind, FieldKind::Number);
    assert_eq!(f[1].kind, FieldKind::Merged(2));
    assert_eq!(f[1].values, [-1.2, 3.0]);
    assert_eq!(f[2].kind, FieldKind::Blank);
    assert_eq!(split_fields(b"     abc", 8)[0].kind, FieldKind::Invalid);
}

#[test]
fn formatter_matches_python_fixed_width_value() {
    // Expected strings computed with ras_commander._fixed_width._format_fixed_width_value.
    let s = |v, w, d| format_value(v, FormatSpec::new(w, d)).unwrap();
    assert_eq!(s(0.0, 8, 2), "    0.00");
    assert_eq!(s(963.04, 8, 2), "  963.04");
    assert_eq!(s(12345.678, 8, 2), "12345.68");
    assert_eq!(s(123456.78, 8, 2), "123456.8");
    assert_eq!(s(-0.0, 8, 2), "   -0.00");
    assert_eq!(s(0.125, 8, 2), "    0.12");
    assert_eq!(s(0.375, 8, 2), "    0.38");
    assert_eq!(s(2.675, 8, 2), "    2.67");
    assert_eq!(s(0.06, 8, 3), "   0.060");
    assert_eq!(s(648224.43125, 16, 5), "    648224.43125");
    let normalized = FormatSpec {
        normalize_negative_zero: true,
        ..FormatSpec::new(8, 2)
    };
    assert_eq!(format_value(-0.001, normalized).unwrap(), "    0.00");
    assert!(format_value(f64::NAN, FormatSpec::new(8, 2)).is_err());
    assert!(format_value(-12345678.0, FormatSpec::new(8, 2)).is_err());
    assert_eq!(format_g(1234567.0), "1.23457e+06");
    assert_eq!(format_g(0.0001), "0.0001");
    assert_eq!(format_g(0.00001), "1e-05");
    assert_eq!(format_g(12.5), "12.5");
    // Python parity (min_decimals = 0).
    assert_eq!(format_numeric_like(12.345, "10.00", 0), "12.35");
    assert_eq!(format_numeric_like(12.0, "10", 0), "12");
    assert_eq!(format_numeric_like(12.5, "10", 0), "12.5");
    assert_eq!(format_numeric_like(88.25, "90.0", 0), "88.2");
    // Bank edits raise precision to what the value needs.
    assert_eq!(shortest_decimals(1528.91), 2);
    assert_eq!(
        format_numeric_like(1528.91, "1497.5", shortest_decimals(1528.91)),
        "1528.91"
    );
}

#[test]
fn atomic_write_replaces_target_and_leaves_no_temp() {
    let dir = std::env::temp_dir().join(format!("ras_text_atomic_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let target = dir.join("out.g01");
    std::fs::write(&target, b"old").unwrap();
    write_atomic(&target, b"new\r\n").unwrap();
    assert_eq!(std::fs::read(&target).unwrap(), b"new\r\n");
    let leftovers: Vec<_> = std::fs::read_dir(&dir)
        .unwrap()
        .filter_map(Result::ok)
        .filter(|e| e.file_name().to_string_lossy().ends_with(".tmp"))
        .collect();
    assert!(leftovers.is_empty());
    std::fs::remove_dir_all(&dir).unwrap();
}
