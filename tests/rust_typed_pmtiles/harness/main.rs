//! Qualification transport only, not a shipped executable.
fn main() {
    let args: Vec<_> = std::env::args_os().collect();
    let result = (|| -> ras_export::Result<_> {
        if args.len() != 5 { return Err("expected input output format max_rows".into()); }
        ras_export::export_ipc(std::path::Path::new(&args[1]), std::path::Path::new(&args[2]),
            args[3].to_str().ok_or("invalid format")?.parse()?,
            args[4].to_str().ok_or("invalid max_rows")?.parse()?)
    })();
    match result { Ok(metrics) => println!("{}", serde_json::to_string(&metrics).unwrap()),
        Err(error) => {eprintln!("{error}"); std::process::exit(1);} }
}
