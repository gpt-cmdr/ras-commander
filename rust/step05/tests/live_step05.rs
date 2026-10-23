//! Live tests of the freshly built `step05` command on real prepared inputs.
//! Requires RAS2FIM_STEP05_INPUTS (adapter inputs root with wsel_max_10/) and
//! RAS2FIM_STEP05_TERRAIN (public sample terrain.tif); skipped (ignored) otherwise.
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::process::Command;

const BIN: &str = env!("CARGO_BIN_EXE_ras2fim-batch");

fn env_paths() -> Option<(PathBuf, PathBuf)> {
    Some((
        PathBuf::from(std::env::var("RAS2FIM_STEP05_INPUTS").ok()?),
        PathBuf::from(std::env::var("RAS2FIM_STEP05_TERRAIN").ok()?),
    ))
}

fn tmp(name: &str) -> PathBuf {
    let d = std::env::temp_dir().join(format!("r2-step05-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d);
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// Flow-10 destination grid (oracle 09 transform; Python computes it identically).
fn request(
    inputs: &Path,
    terrain: &Path,
    method: &str,
    aois: Value,
    max_profile: u64,
    threads: usize,
) -> Value {
    json!({"schema": "ras2fim-step05-request/1",
        "terrain": {"path": terrain, "epsg": 2277, "crs_identity": {"kind": "caller_verified_wkt", "fnv1a64": "867829783e6df879"}},
        "source_crs": {"kind": "terrain"},
        "budgets": {"threads": threads, "max_cache_bytes": 64u64 << 20, "max_profile_bytes": max_profile, "max_inflight_profiles": 1},
        "interpolation": {"selection": "auto"},
        "nudge": {"dst_epsg": 3857, "error_threshold": 0.125, "memory_limit_bytes": 67108864.0, "method": method},
        "profiles": [{"id": "wsel_max_10", "inputs_dir": inputs.join("wsel_max_10"),
            "dest_grid": {"geotransform": [-10844667.0, 3.0, 0.0, 3556350.0, 0.0, -3.0], "width": 1924, "height": 1376},
            "aois": aois}]})
}

fn run(dir: &Path, req: &Value) -> (i32, PathBuf) {
    std::fs::create_dir_all(dir).unwrap();
    let rp = dir.join("request.json");
    std::fs::write(&rp, serde_json::to_vec_pretty(req).unwrap()).unwrap();
    let out = dir.join("out");
    let s = Command::new(BIN)
        .arg("step05")
        .arg(&rp)
        .arg(&out)
        .output()
        .unwrap();
    (s.status.code().unwrap_or(-1), out)
}

fn f32s(p: &Path) -> Vec<u32> {
    std::fs::read(p)
        .unwrap()
        .as_chunks::<4>()
        .0
        .iter()
        .map(|c| u32::from_le_bytes(*c))
        .collect()
}

#[test]
#[ignore = "requires RAS2FIM_STEP05_INPUTS and RAS2FIM_STEP05_TERRAIN"]
fn real_lookup_aois_equal_crop_of_full_warp() {
    let (inputs, terrain) = env_paths().expect("env");
    let d = tmp("crop");
    let (code, full) = run(
        &d.join("full"),
        &request(
            &inputs,
            &terrain,
            "full_warp",
            json!([{"id": "full"}]),
            1 << 30,
            4,
        ),
    );
    assert_eq!(code, 0);
    let mask: Vec<u8> = (0..50 * 40)
        .map(|i| ((i / 50 + i % 50) % 3 != 0) as u8)
        .collect();
    std::fs::create_dir_all(d.join("aoi")).unwrap();
    std::fs::write(d.join("aoi/poly.u8"), &mask).unwrap();
    let aois = json!([{"id": "reach", "window": [700, 600, 50, 40]}, {"id": "poly", "window": [700, 600, 50, 40], "mask_u8": d.join("aoi/poly.u8")},
                      {"id": "edge", "window": [1900, 1370, 100, 100]}, {"id": "out", "window": [5000, 0, 3, 3]}]);
    let (code, aoi) = run(
        &d.join("aoi"),
        &request(&inputs, &terrain, "lookup", aois, 1 << 30, 1),
    );
    assert_eq!(code, 0);
    for prod in ["depth.f32", "wse.f32"] {
        let f = f32s(&full.join("units/wsel_max_10/full").join(prod));
        for (id, w) in [
            ("reach", [700usize, 600, 50, 40]),
            ("poly", [700, 600, 50, 40]),
            ("edge", [1900, 1370, 24, 6]),
        ] {
            let got = f32s(&aoi.join("units/wsel_max_10").join(id).join(prod));
            assert_eq!(got.len(), w[2] * w[3], "{id}");
            for r in 0..w[3] {
                for c in 0..w[2] {
                    let mut e = f[(w[1] + r) * 1924 + w[0] + c];
                    if id == "poly" && mask[r * w[2] + c] == 0 {
                        e = f32::NAN.to_bits();
                    }
                    let g = got[r * w[2] + c];
                    let both_nan = f32::from_bits(e).is_nan() && f32::from_bits(g).is_nan();
                    assert!(both_nan || e == g, "{id} {prod} r{r} c{c}");
                }
            }
        }
        let unit: Value = serde_json::from_slice(
            &std::fs::read(aoi.join("units/wsel_max_10/out/unit.json")).unwrap(),
        )
        .unwrap();
        assert_eq!(unit["status"], "empty_window");
    }
    let rep: Value =
        serde_json::from_slice(&std::fs::read(aoi.join("report.json")).unwrap()).unwrap();
    let p = &rep["profiles"][0];
    assert!(p["source_pixels_interpolated"].as_u64().unwrap() < 10_000);
    assert_eq!(
        p["lookup"]["full_grid_prep"]["source_pixels_encoded"],
        1322 * 1893
    );
    assert_eq!(rep["lookup_cache"]["resident_bytes"], 0);
}

/// Three real profiles (flows 1/10/19) plus one broken profile, run with
/// max_inflight_profiles = 2 and = 1 on the same 2-thread pool: identical unit bytes and unit.json,
/// report order = request order, isolated failure, active profiles <= 2, no extra OS threads.
#[test]
#[ignore = "requires RAS2FIM_STEP05_INPUTS and RAS2FIM_STEP05_TERRAIN"]
fn real_concurrent_profiles_equal_sequential_with_isolation() {
    let (inputs, terrain) = env_paths().expect("env");
    let d = tmp("concurrency");
    let grid = |f: u32| match f {
        1 => {
            json!({"geotransform": [-10844613.0, 3.0, 0.0, 3556296.0, 0.0, -3.0], "width": 1889, "height": 1357})
        }
        10 => {
            json!({"geotransform": [-10844667.0, 3.0, 0.0, 3556350.0, 0.0, -3.0], "width": 1924, "height": 1376})
        }
        _ => {
            json!({"geotransform": [-10844718.0, 3.0, 0.0, 3556515.0, 0.0, -3.0], "width": 1979, "height": 1434})
        }
    };
    let aois = json!([{"id": "full"}, {"id": "reach", "window": [700, 600, 120, 90]}]);
    let mut profiles = Vec::new();
    for (i, f) in [1u32, 10, 19].iter().enumerate() {
        profiles.push(json!({"id": format!("wsel_max_{f}"), "inputs_dir": inputs.join(format!("wsel_max_{f}")),
            "dest_grid": grid(*f), "aois": aois}));
        if i == 0 {
            profiles.push(json!({"id": "broken", "inputs_dir": inputs.join("does_not_exist"), "dest_grid": grid(10), "aois": aois}));
        }
    }
    let ids = ["wsel_max_1", "broken", "wsel_max_10", "wsel_max_19"];
    let mut reports = Vec::new();
    for k in [2usize, 1] {
        let mut req = request(&inputs, &terrain, "lookup", json!([]), 1 << 30, 2);
        req["profiles"] = json!(profiles);
        req["budgets"]["max_inflight_profiles"] = json!(k);
        let (code, out) = run(&d.join(format!("k{k}")), &req);
        assert_eq!(code, 2, "broken profile makes the session exit 2");
        let rep: Value =
            serde_json::from_slice(&std::fs::read(out.join("report.json")).unwrap()).unwrap();
        let got: Vec<&str> = rep["profiles"]
            .as_array()
            .unwrap()
            .iter()
            .map(|p| p["id"].as_str().unwrap())
            .collect();
        assert_eq!(got, ids, "report order = request order");
        assert_eq!(rep["profiles"][1]["status"], "failed");
        assert!(!out.join("units/broken").exists());
        for i in [0, 2, 3] {
            assert_eq!(rep["profiles"][i]["status"], "complete");
        }
        let c = &rep["concurrency"];
        assert_eq!(c["effective_max_inflight_profiles"], k);
        assert!(c["peak_active_profiles"].as_u64().unwrap() <= k as u64);
        assert_eq!(c["active_bound_respected"], true);
        let t = &rep["os_threads"];
        if !t.is_null() {
            assert!(t["max_observed"].as_u64().unwrap() <= t["expected_max"].as_u64().unwrap());
        }
        reports.push((out, rep));
    }
    let (a, b) = (&reports[0].0, &reports[1].0);
    for id in ["wsel_max_1", "wsel_max_10", "wsel_max_19"] {
        for aoi in ["full", "reach"] {
            for f in ["depth.f32", "wse.f32", "unit.json"] {
                let pa = a.join("units").join(id).join(aoi).join(f);
                assert_eq!(
                    std::fs::read(&pa).unwrap(),
                    std::fs::read(b.join("units").join(id).join(aoi).join(f)).unwrap(),
                    "{id}/{aoi}/{f}"
                );
            }
            // The reach AOI equals the crop of the full AOI.
            if aoi == "reach" {
                let w = reports[0].1["profiles"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .find(|p| p["id"] == id)
                    .unwrap()["dest_grid"]["width"]
                    .as_u64()
                    .unwrap() as usize;
                for f in ["depth.f32", "wse.f32"] {
                    let full = f32s(&a.join("units").join(id).join("full").join(f));
                    let reach = f32s(&a.join("units").join(id).join("reach").join(f));
                    for r in 0..90 {
                        for c in 0..120 {
                            assert_eq!(
                                reach[r * 120 + c],
                                full[(600 + r) * w + 700 + c],
                                "{id} {f}"
                            );
                        }
                    }
                }
            }
        }
    }
    let mb = &reports[0].1["memory_bounds"];
    assert!(
        mb["observed_peak_inflight_planned_bytes"].as_u64().unwrap()
            <= mb["estimated_aggregate_planned_bytes_k_largest"]
                .as_u64()
                .unwrap()
    );
}

#[test]
#[ignore = "requires RAS2FIM_STEP05_INPUTS and RAS2FIM_STEP05_TERRAIN"]
fn real_budget_failure_is_reported_not_oom_and_invalid_requests_fail() {
    let (inputs, terrain) = env_paths().expect("env");
    let d = tmp("budget");
    let (code, out) = run(
        &d.join("small"),
        &request(
            &inputs,
            &terrain,
            "lookup",
            json!([{"id": "full"}]),
            4 << 20,
            2,
        ),
    );
    assert_eq!(code, 2);
    let rep: Value =
        serde_json::from_slice(&std::fs::read(out.join("report.json")).unwrap()).unwrap();
    assert_eq!(rep["profiles"][0]["error_kind"], "budget");
    assert!(
        !out.join("units/wsel_max_10/full").exists(),
        "no unit for failed profile"
    );
    // Existing output dir and invalid schema both exit 1.
    let (code, _) = run(
        &d.join("small"),
        &request(
            &inputs,
            &terrain,
            "lookup",
            json!([{"id": "full"}]),
            1 << 30,
            2,
        ),
    );
    assert_eq!(code, 1);
    let mut bad = request(
        &inputs,
        &terrain,
        "lookup",
        json!([{"id": "con"}]),
        1 << 30,
        2,
    );
    let (code, _) = run(&d.join("badid"), &bad);
    assert_eq!(code, 1);
    bad["schema"] = json!("other");
    let (code, _) = run(&d.join("badschema"), &bad);
    assert_eq!(code, 1);
}
