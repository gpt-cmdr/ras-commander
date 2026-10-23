//! Live tests: every case executes the freshly built `ras2fim-batch` binary as a subprocess.
//!
//! Synthetic cases always run. Real public-sample cases need `RAS2FIM_BATCH_INPUTS` (directory
//! holding `terrain.tif` and `snapshot-{0,9,18}/scipy-simplices-1.request.json`); they are
//! `#[ignore]`d so a plain `cargo test` reports them as ignored rather than silently passing.
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicUsize, Ordering};

const BIN: &str = env!("CARGO_BIN_EXE_ras2fim-batch");
static COUNTER: AtomicUsize = AtomicUsize::new(0);
const WKT_FNV: &str = "867829783e6df879";

fn scratch(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!(
        "ras2fim-batch-test-{}-{}-{name}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    ));
    fs::create_dir_all(&d).unwrap();
    d
}

/// Runs the binary; returns (exit code, report or Null).
fn run(dir: &Path, name: &str, session: &Value) -> (i32, Value) {
    let req = dir.join(format!("{name}.json"));
    fs::write(&req, serde_json::to_vec_pretty(session).unwrap()).unwrap();
    let out = dir.join(format!("out-{name}"));
    let o = Command::new(BIN)
        .arg("run")
        .arg(&req)
        .arg(&out)
        .output()
        .unwrap();
    let code = o.status.code().unwrap_or(-1);
    let report = fs::read(out.join("report.json"))
        .ok()
        .map(|b| serde_json::from_slice(&b).unwrap())
        .unwrap_or(Value::Null);
    if code != 0 {
        eprintln!("stderr: {}", String::from_utf8_lossy(&o.stderr));
    }
    (code, report)
}

fn unit(dir: &Path, run: &str, profile: &str, aoi: &str) -> PathBuf {
    dir.join(format!("out-{run}"))
        .join("units")
        .join(profile)
        .join(aoi)
}

fn f64s(p: &Path) -> Vec<f64> {
    fs::read(p)
        .unwrap()
        .as_chunks::<8>()
        .0
        .iter()
        .map(|c| f64::from_le_bytes(*c))
        .collect()
}

const PRODUCTS: [&str; 5] = ["raw_wse", "wse", "depth", "simplex_id", "ground"];

fn assert_units_equal(a: &Path, b: &Path) {
    for p in PRODUCTS {
        let fa = a.join(format!("{p}.bin"));
        let fb = b.join(format!("{p}.bin"));
        assert_eq!(
            fs::read(&fa).unwrap(),
            fs::read(&fb).unwrap(),
            "{} vs {}",
            fa.display(),
            fb.display()
        );
    }
    let ua: Value = serde_json::from_slice(&fs::read(a.join("unit.json")).unwrap()).unwrap();
    let ub: Value = serde_json::from_slice(&fs::read(b.join("unit.json")).unwrap()).unwrap();
    assert_eq!(ua["raw_wse_valid"], ub["raw_wse_valid"]);
    assert_eq!(ua["wet"], ub["wet"]);
}

/// AOI unit must equal the crop of the full unit, byte for byte, for every product.
fn assert_crop(full: &Path, aoi: &Path) {
    let uf: Value = serde_json::from_slice(&fs::read(full.join("unit.json")).unwrap()).unwrap();
    let ua: Value = serde_json::from_slice(&fs::read(aoi.join("unit.json")).unwrap()).unwrap();
    let fw = &uf["window"];
    let aw = &ua["window"];
    let (fwid, fcol, frow) = (
        fw["width"].as_u64().unwrap() as usize,
        fw["col"].as_u64().unwrap() as usize,
        fw["row"].as_u64().unwrap() as usize,
    );
    let (acol, arow, aw_, ah) = (
        aw["col"].as_u64().unwrap() as usize,
        aw["row"].as_u64().unwrap() as usize,
        aw["width"].as_u64().unwrap() as usize,
        aw["height"].as_u64().unwrap() as usize,
    );
    for p in PRODUCTS {
        let f = fs::read(full.join(format!("{p}.bin"))).unwrap();
        let a = fs::read(aoi.join(format!("{p}.bin"))).unwrap();
        assert_eq!(a.len(), aw_ * ah * 8);
        for r in 0..ah {
            let src = ((arow + r - frow) * fwid + (acol - fcol)) * 8;
            assert_eq!(
                &a[r * aw_ * 8..(r + 1) * aw_ * 8],
                &f[src..src + aw_ * 8],
                "{p} row {r}"
            );
        }
    }
}

/// Synthetic cocircular lattice (squares split along alternating diagonals) with curved z.
fn synthetic_profile(id: &str, shift: f64, phase: f64) -> Value {
    let (nx, ny, step) = (14usize, 12usize, 10.0);
    let mut samples = Vec::new();
    for j in 0..ny {
        for i in 0..nx {
            let (x, y) = (i as f64 * step, j as f64 * step);
            samples.push(json!([
                x,
                y,
                100.0 + 0.3 * x + 0.1 * y + 2.0 * ((x + phase) / 17.0).sin() + shift
            ]));
        }
    }
    let mut simplices = Vec::new();
    for j in 0..ny - 1 {
        for i in 0..nx - 1 {
            let a = j * nx + i;
            let (b, c, d) = (a + 1, a + nx, a + nx + 1);
            if (i + j) % 2 == 0 {
                simplices.push(json!([a, b, d]));
                simplices.push(json!([a, d, c]));
            } else {
                simplices.push(json!([a, b, c]));
                simplices.push(json!([b, d, c]));
            }
        }
    }
    simplices.push(json!([0, 1, 2])); // collinear: skipped as degenerate
    let (w, h) = (150usize, 130usize);
    let mut mask = Vec::new();
    let mut terrain = Vec::new();
    for r in 0..h {
        for c in 0..w {
            mask.push(json!((r / 9 + c / 13) % 4 != 0));
            terrain.push(if (r * w + c) % 97 == 0 {
                Value::Null
            } else {
                json!(100.0 + 0.25 * c as f64 + 0.05 * r as f64)
            });
        }
    }
    json!({"id": id, "source": {"kind": "inline", "samples": samples, "simplices": simplices,
        "grid": {"kind": "explicit", "width": w, "height": h, "x0": -3.3, "y0": -2.7, "dx": 0.97, "dy": 0.93},
        "mask": mask, "terrain": terrain}})
}

fn session(profiles: Vec<Value>, aois: Value, threads: usize, tile: usize) -> Value {
    json!({"schema": "ras2fim-batch-session/1", "crs_epsg": 2277, "terrain": {"mode": "caller_buffer"},
        "budgets": {"threads": threads, "max_cache_bytes": 0, "max_inflight_profiles": 2,
                    "max_profile_bytes": 1u64 << 28, "output_tile": tile, "max_tiles_in_flight": 5},
        "products": PRODUCTS, "profiles": profiles, "aois": aois, "error_policy": "isolate_profile"})
}

fn synthetic_aois() -> Value {
    json!([{"id": "full"}, {"id": "straddle", "window": [20, 30, 77, 41]}, {"id": "px", "window": [149, 129, 1, 1]},
           {"id": "edge", "window": [140, 0, 50, 10]}, {"id": "bounds", "bounds": [10.0, 5.0, 60.5, 33.3]},
           {"id": "outside", "window": [500, 500, 3, 3]}])
}

#[test]
fn synthetic_batch_vs_single_threads_and_crops() {
    let d = scratch("synthetic");
    let p = [
        synthetic_profile("a", 0.0, 0.0),
        synthetic_profile("b", 0.7, 3.0),
        synthetic_profile("c", -0.4, 9.0),
    ];
    let (code, rep) = run(&d, "batch4", &session(p.to_vec(), synthetic_aois(), 4, 32));
    assert_eq!(code, 0);
    assert_eq!(rep["status"], "complete");
    assert_eq!(rep["profiles"][0]["degenerate_simplices_skipped"], 1);
    let (code, _) = run(&d, "batch1", &session(p.to_vec(), synthetic_aois(), 1, 16));
    assert_eq!(code, 0);
    for (i, prof) in p.iter().enumerate() {
        let id = prof["id"].as_str().unwrap();
        let name = format!("single{i}");
        let (code, _) = run(
            &d,
            &name,
            &session(vec![prof.clone()], json!([{"id": "full"}]), 2, 64),
        );
        assert_eq!(code, 0);
        for aoi in ["full", "straddle", "px", "edge", "bounds"] {
            assert_units_equal(&unit(&d, "batch4", id, aoi), &unit(&d, "batch1", id, aoi));
            assert_crop(
                &unit(&d, "batch4", id, "full"),
                &unit(&d, "batch4", id, aoi),
            );
        }
        assert_units_equal(
            &unit(&d, "batch4", id, "full"),
            &unit(&d, &name, id, "full"),
        );
        let empty: Value = serde_json::from_slice(
            &fs::read(unit(&d, "batch4", id, "outside").join("unit.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(empty["status"], "empty_window");
    }
    // Independent semantic spot checks of the binary output.
    let u = unit(&d, "batch4", "a", "full");
    let (raw, wse, depth, ground) = (
        f64s(&u.join("raw_wse.bin")),
        f64s(&u.join("wse.bin")),
        f64s(&u.join("depth.bin")),
        f64s(&u.join("ground.bin")),
    );
    let mut wet = 0;
    for i in 0..raw.len() {
        if !wse[i].is_nan() {
            wet += 1;
            assert_eq!(wse[i].to_bits(), raw[i].to_bits());
            assert_eq!(depth[i].to_bits(), (raw[i] - ground[i]).to_bits());
            assert!(depth[i] >= 0.0);
        } else if !raw[i].is_nan() && !ground[i].is_nan() {
            assert!(raw[i] - ground[i] < 0.0);
        }
    }
    assert!(wet > 1000);
}

#[test]
fn invalid_requests_fail_without_partial_success() {
    let d = scratch("invalid");
    let mut s = session(
        vec![synthetic_profile("a", 0.0, 0.0)],
        json!([{"id": "full"}]),
        1,
        32,
    );
    s["budgets"]["threads"] = json!(0);
    assert_eq!(run(&d, "threads0", &s).0, 1);
    let mut s = session(
        vec![synthetic_profile("a", 0.0, 0.0)],
        json!([{"id": "full", "crs_epsg": 4326}]),
        1,
        32,
    );
    assert_eq!(run(&d, "crs", &s).0, 1);
    s["aois"] = json!([{"id": "../x"}]);
    assert_eq!(run(&d, "badid", &s).0, 1);
    // Out-of-range simplex: profile fails explicitly; other profile completes; exit code 2.
    let mut bad = synthetic_profile("bad", 0.0, 0.0);
    bad["source"]["simplices"]
        .as_array_mut()
        .unwrap()
        .push(json!([0, 1, 99999]));
    let (code, rep) = run(
        &d,
        "isolate",
        &session(
            vec![bad, synthetic_profile("ok", 0.0, 0.0)],
            json!([{"id": "full"}]),
            2,
            32,
        ),
    );
    assert_eq!(code, 2);
    assert_eq!(rep["profiles"][0]["status"], "failed");
    assert_eq!(rep["profiles"][1]["status"], "complete");
    let u: Value = serde_json::from_slice(
        &fs::read(unit(&d, "isolate", "bad", "full").join("unit.json")).unwrap(),
    )
    .unwrap();
    assert_eq!(u["status"], "failed");
    assert!(!unit(&d, "isolate", "bad", "full").join("wse.bin").exists());
    // Budget: a prepared profile larger than max_profile_bytes fails explicitly.
    let mut s = session(
        vec![synthetic_profile("a", 0.0, 0.0)],
        json!([{"id": "full"}]),
        1,
        32,
    );
    s["budgets"]["max_profile_bytes"] = json!(1000);
    let (code, rep) = run(&d, "budget", &s);
    assert_eq!(code, 2);
    assert_eq!(rep["profiles"][0]["error"]["kind"], "budget");
    // Wet mask without any valid simplex is an error, not an empty raster.
    let mut p = synthetic_profile("deg", 0.0, 0.0);
    p["source"]["simplices"] = json!([[0, 1, 2]]);
    let (code, rep) = run(
        &d,
        "degen",
        &session(vec![p], json!([{"id": "full"}]), 1, 32),
    );
    assert_eq!(code, 2);
    assert_eq!(rep["profiles"][0]["error"]["kind"], "invalid");
    // fail_fast: a failing first batch stops the session; later profiles never start.
    let mut bad = synthetic_profile("bad", 0.0, 0.0);
    bad["source"]["simplices"] = json!([[0, 1, 99999]]);
    let mut s = session(
        vec![bad, synthetic_profile("later", 0.0, 0.0)],
        json!([{"id": "full"}]),
        1,
        32,
    );
    s["error_policy"] = json!("fail_fast");
    s["budgets"]["max_inflight_profiles"] = json!(1);
    let (code, rep) = run(&d, "failfast", &s);
    assert_eq!(code, 2);
    assert_eq!(rep["status"], "incomplete");
    assert_eq!(rep["profiles"][0]["status"], "failed");
    assert_eq!(rep["profiles"][1]["status"], "not_started");
    // Existing output directory is refused.
    fs::create_dir_all(d.join("out-exists")).unwrap();
    assert_eq!(
        run(
            &d,
            "exists",
            &session(
                vec![synthetic_profile("a", 0.0, 0.0)],
                json!([{"id": "full"}]),
                1,
                32
            )
        )
        .0,
        1
    );
}

// ----- Real public-sample cases (fresh binary, retained baseline inputs) -----

fn inputs() -> PathBuf {
    PathBuf::from(
        std::env::var("RAS2FIM_BATCH_INPUTS")
            .expect("set RAS2FIM_BATCH_INPUTS to the task-local inputs directory"),
    )
}

fn legacy_profiles(root: &Path) -> Vec<Value> {
    [0, 9, 18]
        .iter()
        .map(|s| json!({"id": format!("f{s}"), "source": {"kind": "legacy_request",
            "path": root.join(format!("snapshot-{s}/scipy-simplices-1.request.json")).to_str().unwrap()}}))
        .collect()
}

fn native(
    root: &Path,
    profiles: Vec<Value>,
    aois: Value,
    threads: usize,
    cache: u64,
    inflight: usize,
    tile: usize,
) -> Value {
    json!({"schema": "ras2fim-batch-session/1", "crs_epsg": 2277,
        "terrain": {"mode": "native_geotiff", "path": root.join("terrain.tif").to_str().unwrap(),
                    "query": "pixel_center", "nodata_policy": "dry",
                    "crs_identity": {"kind": "caller_verified_wkt", "fnv1a64": WKT_FNV}},
        "budgets": {"threads": threads, "max_cache_bytes": cache, "max_inflight_profiles": inflight,
                    "max_profile_bytes": 1u64 << 28, "output_tile": tile, "max_tiles_in_flight": 8},
        "products": PRODUCTS, "profiles": profiles, "aois": aois, "error_policy": "fail_fast"})
}

fn real_aois() -> Value {
    json!([{"id": "full"}, {"id": "w1", "window": [37, 50, 101, 77]}, {"id": "px", "window": [255, 0, 1, 1]},
           {"id": "reach", "bounds": [3224300.0, 10118200.0, 3225400.5, 10119100.0]}])
}

#[test]
#[ignore = "requires RAS2FIM_BATCH_INPUTS (real public sample)"]
fn real_native_matches_caller_buffer_and_batch_equals_single() {
    let root = inputs();
    let d = scratch("real-native");
    let mut caller = native(&root, legacy_profiles(&root), real_aois(), 4, 0, 3, 64);
    caller["terrain"] = json!({"mode": "caller_buffer"});
    assert_eq!(run(&d, "caller", &caller).0, 0);
    let (code, rep) = run(
        &d,
        "native",
        &native(
            &root,
            legacy_profiles(&root),
            real_aois(),
            4,
            64 << 20,
            3,
            64,
        ),
    );
    assert_eq!(code, 0);
    let c = &rep["terrain"]["stats"]["cache"];
    assert_eq!(
        c["tile_reads"], c["distinct_tiles_loaded"],
        "large cache must decode each block once"
    );
    assert_eq!(c["evictions"], 0);
    assert!(
        rep["os_threads"]["max_observed"].as_u64().unwrap()
            <= rep["os_threads"]["expected_max"].as_u64().unwrap(),
        "nested decode threads observed"
    );
    for (i, p) in legacy_profiles(&root).into_iter().enumerate() {
        let id = p["id"].as_str().unwrap().to_string();
        for aoi in ["full", "w1", "px", "reach"] {
            // Native pixel-center terrain reproduces the retained pre-aligned buffer bit for bit.
            assert_units_equal(&unit(&d, "caller", &id, aoi), &unit(&d, "native", &id, aoi));
            assert_crop(
                &unit(&d, "native", &id, "full"),
                &unit(&d, "native", &id, aoi),
            );
        }
        let name = format!("single{i}");
        assert_eq!(
            run(
                &d,
                &name,
                &native(&root, vec![p], json!([{"id": "full"}]), 1, 2 << 20, 1, 128)
            )
            .0,
            0
        );
        assert_units_equal(
            &unit(&d, "native", &id, "full"),
            &unit(&d, &name, &id, "full"),
        );
    }
}

#[test]
#[ignore = "requires RAS2FIM_BATCH_INPUTS (real public sample)"]
fn real_evicted_cache_equals_warm_cache() {
    let root = inputs();
    let d = scratch("real-evict");
    // Terrain-aligned query lattice over a block-aligned 700 x 520 terrain window (3 x 3 blocks).
    let aligned: Vec<Value> = [0, 9, 18]
        .iter()
        .map(|s| {
            let r: Value = serde_json::from_slice(&fs::read(root.join(format!("snapshot-{s}/scipy-simplices-1.request.json"))).unwrap()).unwrap();
            json!({"id": format!("a{s}"), "source": {"kind": "inline", "samples": r["samples"], "simplices": r["simplices"],
                "grid": {"kind": "terrain_aligned", "col": 768, "row": 512, "width": 700, "height": 520}, "mask_all_wet": true}})
        })
        .collect();
    let aois = json!([{"id": "full"}, {"id": "w", "window": [100, 33, 300, 250]}]);
    // One profile per batch and a 1-block-per-thread budget force re-decodes across batches.
    let (code, cold) = run(
        &d,
        "evict",
        &native(&root, aligned.clone(), aois.clone(), 2, 2 * 262_144, 1, 128),
    );
    assert_eq!(code, 0, "{cold}");
    let c = &cold["terrain"]["stats"]["cache"];
    assert!(
        c["evictions"].as_u64().unwrap() > 0 && c["reloads_after_eviction"].as_u64().unwrap() > 0,
        "{c}"
    );
    assert!(c["peak_bytes"].as_u64().unwrap() <= 2 * 262_144);
    let (code, warm) = run(
        &d,
        "warm",
        &native(&root, aligned.clone(), aois, 4, 256 << 20, 3, 256),
    );
    assert_eq!(code, 0);
    assert_eq!(warm["terrain"]["stats"]["cache"]["evictions"], 0);
    for p in &aligned {
        let id = p["id"].as_str().unwrap();
        for aoi in ["full", "w"] {
            assert_units_equal(&unit(&d, "evict", id, aoi), &unit(&d, "warm", id, aoi));
        }
        assert_crop(&unit(&d, "warm", id, "full"), &unit(&d, "warm", id, "w"));
    }
}
