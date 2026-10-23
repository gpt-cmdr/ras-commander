//! r2 hardening live tests (fresh binary as a subprocess): failure-safe outputs (QA H1/R3),
//! case-colliding ids (M5/R6), serial in-flight bound (M3/R2), pre-read profile budget (M2/R4).
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const BIN: &str = env!("CARGO_BIN_EXE_ras2fim-batch");

fn scratch(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("ras2fim-hardening-{}-{name}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    d
}

fn lattice_profile(id: &str, w: usize, h: usize) -> Value {
    let (n, step) = (9usize, 10.0);
    let mut s = Vec::new();
    for j in 0..n {
        for i in 0..n {
            s.push(json!([
                i as f64 * step,
                j as f64 * step,
                100.0 + 0.1 * i as f64 + 0.05 * j as f64
            ]));
        }
    }
    let mut t = Vec::new();
    for j in 0..n - 1 {
        for i in 0..n - 1 {
            let a = j * n + i;
            t.push(json!([a, a + 1, a + n + 1]));
            t.push(json!([a, a + n + 1, a + n]));
        }
    }
    json!({"id": id, "source": {"kind": "inline", "samples": s, "simplices": t,
        "grid": {"kind": "explicit", "width": w, "height": h, "x0": 0.5, "y0": 0.5, "dx": 1.2, "dy": 1.2},
        "mask_all_wet": true, "terrain": vec![99.0; w * h]}})
}

fn session(profiles: Vec<Value>, aois: Value, inflight_tiles: usize) -> Value {
    json!({"schema": "ras2fim-batch-session/1", "crs_epsg": 2277, "terrain": {"mode": "caller_buffer"},
        "budgets": {"threads": 2, "max_cache_bytes": 0, "max_inflight_profiles": 1,
                    "max_profile_bytes": 1u64 << 28, "output_tile": 16, "max_tiles_in_flight": inflight_tiles},
        "products": ["raw_wse", "wse", "depth", "simplex_id", "ground"],
        "profiles": profiles, "aois": aois, "error_policy": "isolate_profile"})
}

fn write_session(d: &Path, name: &str, s: &Value) -> PathBuf {
    let p = d.join(format!("{name}.json"));
    fs::write(&p, serde_json::to_vec_pretty(s).unwrap()).unwrap();
    p
}

fn run(d: &Path, name: &str, s: &Value) -> (i32, Value, PathBuf) {
    let req = write_session(d, name, s);
    let out = d.join(format!("out-{name}"));
    let o = Command::new(BIN)
        .arg("run")
        .arg(&req)
        .arg(&out)
        .output()
        .unwrap();
    let rep = fs::read(out.join("report.json"))
        .ok()
        .map(|b| serde_json::from_slice(&b).unwrap())
        .unwrap_or(Value::Null);
    (o.status.code().unwrap_or(-1), rep, out)
}

fn files(root: &Path) -> Vec<String> {
    let mut v = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in fs::read_dir(&d).unwrap() {
            let p = e.unwrap().path();
            if p.is_dir() {
                stack.push(p);
            } else {
                v.push(
                    p.strip_prefix(root)
                        .unwrap()
                        .to_string_lossy()
                        .replace('\\', "/"),
                );
            }
        }
    }
    v.sort();
    v
}

/// QA R3: an output I/O error mid-session (RLIMIT_FSIZE, SIGXFSZ ignored -> EFBIG) must leave
/// no data files, failed unit status, and an aborted report.
#[cfg(target_os = "linux")]
#[test]
fn sink_io_error_aborts_cleanly_with_report() {
    let d = scratch("r3");
    // p0 completes in batch 0; p1's 128x128 full unit pre-sizes 128 KiB > the 64 KiB limit.
    let s = session(
        vec![lattice_profile("p0", 8, 8), lattice_profile("p1", 128, 128)],
        json!([{"id": "small", "window": [0, 0, 4, 4]}, {"id": "full"}]),
        4,
    );
    let req = write_session(&d, "r3", &s);
    let out = d.join("out-r3");
    let o = Command::new("sh")
        .arg("-c")
        .arg("trap '' XFSZ; ulimit -f 64; exec \"$0\" run \"$1\" \"$2\"")
        .arg(BIN)
        .arg(&req)
        .arg(&out)
        .output()
        .unwrap();
    let stderr = String::from_utf8_lossy(&o.stderr);
    assert_eq!(o.status.code(), Some(1), "{stderr}");
    let rep: Value = serde_json::from_slice(&fs::read(out.join("report.json")).unwrap()).unwrap();
    assert_eq!(rep["status"], "aborted");
    assert_eq!(rep["error"]["kind"], "io", "{}", rep["error"]);
    assert_eq!(rep["cleanup_problems"], json!([]));
    assert_eq!(rep["profiles"][0]["status"], "complete");
    assert_eq!(rep["profiles"][1]["status"], "aborted");
    let all = files(&out);
    assert!(!all.iter().any(|f| f.ends_with(".partial")), "{all:?}");
    for aoi in ["small", "full"] {
        let u = out.join("units/p1").join(aoi);
        assert_eq!(files(&u), ["unit.json"], "p1/{aoi}");
        let doc: Value = serde_json::from_slice(&fs::read(u.join("unit.json")).unwrap()).unwrap();
        assert_eq!(doc["status"], "failed");
    }
    // The completed profile's units stay committed and valid.
    let doc: Value =
        serde_json::from_slice(&fs::read(out.join("units/p0/full/unit.json")).unwrap()).unwrap();
    assert_eq!(doc["status"], "complete");
    assert_eq!(
        fs::read(out.join("units/p0/full/depth.bin")).unwrap().len(),
        8 * 8 * 8
    );
}

/// QA R6/M5: ids equal up to case (and Windows device names) are rejected before any output.
#[test]
fn case_colliding_and_reserved_ids_rejected_before_output() {
    let d = scratch("r6");
    for (name, ps, aois) in [
        (
            "case",
            vec![lattice_profile("A", 8, 8), lattice_profile("a", 8, 8)],
            json!([{"id": "full"}]),
        ),
        (
            "aoi",
            vec![lattice_profile("A", 8, 8)],
            json!([{"id": "R"}, {"id": "r"}]),
        ),
        (
            "nul",
            vec![lattice_profile("NUL", 8, 8)],
            json!([{"id": "full"}]),
        ),
        (
            "dot",
            vec![lattice_profile("p", 8, 8)],
            json!([{"id": "reach."}]),
        ),
    ] {
        let (code, rep, out) = run(&d, name, &session(ps, aois, 2));
        assert_eq!(code, 1, "{name}");
        assert_eq!(rep, Value::Null);
        assert!(!out.exists(), "{name}: no output directory");
    }
}

/// QA R2/M3: max_tiles_in_flight = 1 is a true bound (serial branch) and bit-identical output.
#[test]
fn inflight_one_is_serial_and_identical() {
    let d = scratch("r2");
    let ps = vec![lattice_profile("p0", 64, 48)];
    let aois = json!([{"id": "full"}, {"id": "w", "window": [5, 7, 30, 20]}]);
    let (c1, r1, o1) = run(&d, "one", &session(ps.clone(), aois.clone(), 1));
    let (c4, r4, o4) = run(&d, "four", &session(ps, aois, 4));
    assert_eq!((c1, c4), (0, 0));
    assert_eq!(r1["counters"]["peak_tiles_in_flight"], 1);
    assert_eq!(r1["output_buffer_bound_bytes"], 16 * 16 * 40);
    assert_eq!(r1["cpu_threads"]["pipelined"], false);
    assert!(r4["counters"]["peak_tiles_in_flight"].as_u64().unwrap() <= 4);
    for aoi in ["full", "w"] {
        for f in [
            "raw_wse.bin",
            "wse.bin",
            "depth.bin",
            "simplex_id.bin",
            "ground.bin",
            "unit.json",
        ] {
            let p = format!("units/p0/{aoi}/{f}");
            assert_eq!(
                fs::read(o1.join(&p)).unwrap(),
                fs::read(o4.join(&p)).unwrap(),
                "{p}"
            );
        }
    }
}

/// QA R4/M2: an oversized binary profile is rejected from file lengths before any read (a
/// sparse 2.4 GB samples file; reading it would take seconds and gigabytes).
#[test]
fn oversized_binary_profile_rejected_before_read() {
    let d = scratch("r4");
    let f = fs::File::create(d.join("s.f64")).unwrap();
    f.set_len(100_000_000 * 24).unwrap();
    fs::write(d.join("t.u32"), vec![0u8; 12]).unwrap();
    let prof = json!({"id": "big", "source": {"kind": "binary", "samples_f64": "s.f64", "simplices_u32": "t.u32",
        "grid": {"kind": "explicit", "width": 1, "height": 1, "x0": 0, "y0": 0, "dx": 1, "dy": 1}, "mask_all_wet": true}});
    let mut s = session(
        vec![prof, lattice_profile("ok", 8, 8)],
        json!([{"id": "full"}]),
        2,
    );
    s["profiles"][1]["source"]["terrain"] = json!(vec![99.0; 64]);
    s["budgets"]["max_profile_bytes"] = json!(1u64 << 24);
    let t = std::time::Instant::now();
    let (code, rep, _) = run(&d, "pre", &s);
    assert_eq!(code, 2);
    assert!(t.elapsed().as_secs_f64() < 10.0);
    let e = &rep["profiles"][0]["error"];
    assert_eq!(
        (e["stage"].as_str(), e["kind"].as_str()),
        (Some("preflight"), Some("budget")),
        "{e}"
    );
    assert!(
        rep["profiles"][0]["load_peak_estimate_bytes"]
            .as_u64()
            .unwrap()
            > 2_400_000_000
    );
    assert_eq!(rep["profiles"][1]["status"], "complete");
    assert_eq!(rep["memory_estimate"]["is_hard_bound"], false);
}

/// max_session_bytes packs profiles into smaller batches without changing outputs.
#[test]
fn session_budget_packs_batches_identically() {
    let d = scratch("pack");
    let ps = vec![lattice_profile("a", 96, 80), lattice_profile("b", 96, 80)];
    let mut s = session(ps, json!([{"id": "full"}]), 4);
    s["budgets"]["max_inflight_profiles"] = json!(2);
    let (c0, r0, o0) = run(&d, "free", &s);
    assert_eq!(c0, 0);
    assert_eq!(
        r0["memory_estimate"]["batches"].as_array().unwrap().len(),
        1
    );
    let stat = r0["memory_estimate"]["static_total_bytes"]
        .as_u64()
        .unwrap();
    let peak = r0["profiles"][0]["load_peak_estimate_bytes"]
        .as_u64()
        .unwrap();
    let plan = r0["memory_estimate"]["batches"][0]["plan_metadata_estimate_bytes"]
        .as_u64()
        .unwrap();
    s["budgets"]["max_session_bytes"] = json!(stat + peak + plan);
    let (c1, r1, o1) = run(&d, "packed", &s);
    assert_eq!(c1, 0, "{}", r1["profiles"]);
    assert_eq!(
        r1["memory_estimate"]["batches"].as_array().unwrap().len(),
        2
    );
    for id in ["a", "b"] {
        let p = format!("units/{id}/full/depth.bin");
        assert_eq!(
            fs::read(o0.join(&p)).unwrap(),
            fs::read(o1.join(&p)).unwrap()
        );
    }
    s["budgets"]["max_session_bytes"] = json!(stat - 1);
    let (c2, _, out) = run(&d, "tiny", &s);
    assert_eq!(c2, 1);
    assert!(!out.exists() || fs::read(out.join("report.json")).is_ok());
}
