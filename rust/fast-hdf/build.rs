fn metadata() -> Result<(), String> {
    let text = std::fs::read_to_string("Cargo.toml")
        .map_err(|e| format!("cannot read Cargo.toml: {e}"))?;
    let manifest: toml::Value = text
        .parse()
        .map_err(|e| format!("invalid Cargo.toml: {e}"))?;
    let dep = manifest
        .get("dependencies")
        .and_then(|d| d.get("ras-commander-rust"))
        .ok_or("missing dependencies.ras-commander-rust")?;
    let rev = dep
        .get("rev")
        .and_then(toml::Value::as_str)
        .ok_or("engine dependency must declare an exact Git rev")?;
    if rev.len() != 40 || !rev.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err("engine rev must be a complete 40-digit hexadecimal commit".into());
    }
    let features = dep
        .get("features")
        .and_then(toml::Value::as_array)
        .ok_or("engine dependency must declare a features array")?
        .iter()
        .map(|v| v.as_str().ok_or("engine features must be strings"))
        .collect::<Result<Vec<_>, _>>()?
        .join(",");
    println!("cargo:rustc-env=RAS_ENGINE_COMMIT={rev}");
    println!("cargo:rustc-env=RAS_ENGINE_FEATURES={features}");
    Ok(())
}
fn main() {
    println!("cargo:rerun-if-changed=Cargo.toml");
    if let Err(message) = metadata() {
        eprintln!("bridge build metadata: {message}");
        std::process::exit(1);
    }
}
