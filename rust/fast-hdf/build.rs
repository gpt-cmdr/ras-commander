fn main() {
    println!("cargo:rerun-if-changed=Cargo.toml");
    let manifest = std::fs::read_to_string("Cargo.toml").expect("manifest");
    let dependency = manifest
        .lines()
        .find(|line| line.starts_with("ras-commander-rust ="))
        .expect("engine dependency");
    let rev = dependency
        .split("rev = \"")
        .nth(1)
        .and_then(|s| s.split('"').next())
        .expect("exact engine revision");
    assert!(rev.len() == 40 && rev.bytes().all(|b| b.is_ascii_hexdigit()));
    let features = dependency
        .split("features = [")
        .nth(1)
        .and_then(|s| s.split(']').next())
        .expect("engine features")
        .replace(['"', ' '], "");
    println!("cargo:rustc-env=RAS_ENGINE_COMMIT={rev}");
    println!("cargo:rustc-env=RAS_ENGINE_FEATURES={features}");
}
