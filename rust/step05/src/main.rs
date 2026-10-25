//! CLI: `ras2fim-batch run <session.json> <new-output-dir>`, `method`, `terrain-info <tif>`.
//!
//! Exit codes: 0 all units complete/empty; 2 session ran but a profile failed/aborted;
//! 1 invalid request or session error. When this run created the output directory, a session
//! error still leaves `report.json` with `status: "aborted"` (best effort, see `session::run`);
//! no report exists when the request was rejected before the directory was created.
use ras2fim_stages_r2::{method_record, model::SessionRequest, session, terrain};
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};

const USAGE: &str = "usage:\n  ras2fim-batch run <session.json> <new-output-dir>\n  ras2fim-batch step05 <request.json> <new-output-dir>\n  ras2fim-batch method\n  ras2fim-batch terrain-info <terrain.tif>";

/// Samples this process's OS thread count (Linux /proc) to evidence no nested decode threads.
struct ThreadMonitor {
    stop: Arc<AtomicBool>,
    max: Arc<AtomicUsize>,
    samples: Arc<AtomicUsize>,
    handle: Option<std::thread::JoinHandle<()>>,
}

fn os_threads() -> Option<usize> {
    std::fs::read_dir("/proc/self/task").ok().map(|d| d.count())
}

impl ThreadMonitor {
    fn start() -> Self {
        let stop = Arc::new(AtomicBool::new(false));
        let max = Arc::new(AtomicUsize::new(0));
        let samples = Arc::new(AtomicUsize::new(0));
        let (s, m, n) = (stop.clone(), max.clone(), samples.clone());
        let handle = os_threads().map(|_| {
            std::thread::spawn(move || {
                while !s.load(Ordering::Relaxed) {
                    if let Some(c) = os_threads() {
                        m.fetch_max(c, Ordering::Relaxed);
                        n.fetch_add(1, Ordering::Relaxed);
                    }
                    std::thread::sleep(std::time::Duration::from_micros(200));
                }
            })
        });
        Self {
            stop,
            max,
            samples,
            handle,
        }
    }
    fn finish(mut self) -> serde_json::Value {
        self.stop.store(true, Ordering::Relaxed);
        if let Some(h) = self.handle.take() {
            let _ = h.join();
            serde_json::json!({"max_observed": self.max.load(Ordering::Relaxed),
                               "samples": self.samples.load(Ordering::Relaxed),
                               "method": "count /proc/self/task every ~200us; expected max = pool threads + main + monitor"})
        } else {
            serde_json::json!(null)
        }
    }
}

fn run() -> Result<i32, Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    let cmd = args.first().and_then(|a| a.to_str()).unwrap_or("");
    match (cmd, args.len()) {
        ("method", 1) => {
            let m = serde_json::json!({"batch_session_r1": method_record(), "step05_r2": ras2fim_stages_r2::step05::method_record(), "horizontal": ras2fim_stages_r2::horizontal::method_record()});
            println!("{}", serde_json::to_string_pretty(&m)?);
            Ok(0)
        }
        ("terrain-info", 2) => {
            let p = args[1].to_str().ok_or("terrain path is not UTF-8")?;
            println!("{}", serde_json::to_string_pretty(&terrain::inspect(p)?)?);
            Ok(0)
        }
        ("run", 3) => {
            let session_path = PathBuf::from(&args[1]);
            let out = PathBuf::from(&args[2]);
            if out.exists() {
                return Err("output directory exists; choose a new path".into());
            }
            let req = SessionRequest::load(&session_path)?;
            let base = session_path
                .canonicalize()?
                .parent()
                .map(PathBuf::from)
                .ok_or("session path has no parent")?;
            let monitor = ThreadMonitor::start();
            let result = session::run(&req, &base, &out);
            let threads = monitor.finish();
            let mut report = result?;
            report["os_threads"] = threads.clone();
            report["os_threads"]["expected_max"] = (req.budgets.threads + 2).into();
            ras2fim_stages_r2::sink::write_json(&out.join("report.json"), &report)?;
            let summary = serde_json::json!({
                "status": report["status"],
                "counters": report["counters"],
                "cache": report["terrain"]["stats"]["cache"],
                "os_threads": threads,
                "total_wall_seconds": report["timings"]["total_wall_seconds"],
            });
            println!("{summary}");
            Ok(if report["status"] == "complete" { 0 } else { 2 })
        }
        ("horizontal", 3) => {
            let request_path = PathBuf::from(&args[1]);
            let out = PathBuf::from(&args[2]);
            if out.exists() { return Err("output directory exists; choose a new path".into()); }
            let req: ras2fim_stages_r2::horizontal::Request = ras2fim_stages_r2::model::read_json(&request_path)?;
            let base = request_path.canonicalize()?.parent().ok_or("request has no parent")?.to_path_buf();
            let report = ras2fim_stages_r2::horizontal::run(&req, &base, &out)?;
            println!("{}", serde_json::json!({"status":report["status"],"total_seconds":report["total_seconds"]}));
            Ok(if report["status"] == "complete" { 0 } else { 2 })
        }
        ("step05", 3) => {
            let request_path = PathBuf::from(&args[1]);
            let out = PathBuf::from(&args[2]);
            if out.exists() {
                return Err("output directory exists; choose a new path".into());
            }
            let req = ras2fim_stages_r2::step05::Request::load(&request_path)?;
            let base = request_path
                .canonicalize()?
                .parent()
                .map(PathBuf::from)
                .ok_or("request path has no parent")?;
            let monitor = ThreadMonitor::start();
            let result = ras2fim_stages_r2::step05::run(&req, &base, &out);
            let threads = monitor.finish();
            let mut report = match result {
                Ok(r) => r,
                Err(e) => {
                    // The output directory may exist: record the session error durably.
                    if out.is_dir() {
                        let failed = serde_json::json!({"schema": "ras2fim-step05-report/1", "status": "error",
                            "error_kind": e.kind(), "error": e.to_string()});
                        let _ =
                            ras2fim_stages_r2::sink::write_json(&out.join("report.json"), &failed);
                    }
                    return Err(e.into());
                }
            };
            report["os_threads"] = threads;
            report["os_threads"]["expected_max"] = (req.budgets.threads + 2).into();
            ras2fim_stages_r2::sink::write_json(&out.join("report.json"), &report)?;
            let summary = serde_json::json!({"status": report["status"], "lookup_cache": report["lookup_cache"],
                "total_wall_seconds_diagnostic": report["total_wall_seconds_diagnostic"]});
            println!("{summary}");
            Ok(if report["status"] == "complete" { 0 } else { 2 })
        }
        _ => Err(USAGE.into()),
    }
}

fn main() {
    match run() {
        Ok(code) => std::process::exit(code),
        Err(e) => {
            eprintln!("{e}");
            std::process::exit(1);
        }
    }
}
