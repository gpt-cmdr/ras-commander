//! Prepared native iterator experiment, not a production CLI.
use arrow_array::RecordBatch;
use arrow_ipc::reader::FileReader;
use ras_export::{Error, Result};
use std::{fs::File, path::Path, time::Instant};

fn run() -> Result<()> {
    let a: Vec<_> = std::env::args().collect();
    if a.len() != 4 {
        return Err("input output format required".into());
    }
    let started = Instant::now();
    let reader = FileReader::try_new(File::open(&a[1])?, None)?;
    let schema = reader.schema();
    // Deliberately resident prepared batches: no IPC decoding during writer timer.
    // This is NOT a bounded-total-memory claim; input transfer remains measured.
    let batches: Vec<RecordBatch> = reader.collect::<std::result::Result<_, _>>()?;
    let preparation_seconds = started.elapsed().as_secs_f64();
    println!(
        "{}",
        serde_json::json!({"phase":"writer","preparation_seconds":preparation_seconds})
    );
    let start = Instant::now();
    let metrics = ras_export::export_batches(
        schema,
        batches.into_iter().map(Ok::<_, Error>),
        Path::new(&a[2]),
        a[3].parse()?,
        4096,
    )?;
    println!(
        "{}",
        serde_json::json!({"metrics":metrics,"writer_seconds":start.elapsed().as_secs_f64(),
        "preparation_seconds":preparation_seconds,"transport":"resident Vec<RecordBatch> loaded once from prepared IPC"})
    );
    Ok(())
}
fn main() {
    if let Err(e) = run() {
        eprintln!("{e}");
        std::process::exit(1);
    }
}
