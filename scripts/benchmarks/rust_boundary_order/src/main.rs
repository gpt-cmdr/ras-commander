use clipper2_rust::{ClipType, Clipper64, FillRule, Path64, Paths64, Point64, make_path64};
fn merge(paths: &Paths64, split: bool) -> Paths64 {
    let mut c = Clipper64::new();
    c.set_preserve_collinear(false);
    if split {
        c.add_subject(&vec![paths[0].clone()]);
        c.add_clip(&paths[1..].to_vec());
    } else {
        c.add_subject(paths);
    }
    let mut out = vec![];
    assert!(c.execute(ClipType::Union, FillRule::NonZero, &mut out, None));
    out
}
fn area(paths: &Paths64) -> f64 {
    let total: i128 = paths
        .iter()
        .map(|p| {
            p.iter()
                .zip(p.iter().cycle().skip(1))
                .take(p.len())
                .map(|(a, b)| i128::from(a.x) * i128::from(b.y) - i128::from(b.x) * i128::from(a.y))
                .sum::<i128>()
        })
        .sum();
    total as f64 / 2.
}
fn main() {
    let a = make_path64(&[0, 0, 100, 0, 100, 100, 0, 100]);
    let h = make_path64(&[20, 20, 20, 80, 80, 80, 80, 20]);
    let b = make_path64(&[200, 0, 300, 0, 300, 100, 200, 100]);
    for (name, paths) in [
        ("outer-A-first", vec![a.clone(), h.clone(), b.clone()]),
        ("outer-B-first", vec![b, a, h]),
    ] {
        for split in [true, false] {
            let out = merge(&paths, split);
            let filled = split && name == "outer-A-first";
            assert_eq!(area(&out), if filled { 20000. } else { 16400. });
            assert_eq!(out.len(), if filled { 2 } else { 3 });
            println!(
                "{}",
                serde_json::json!({"case":name,"grouping":if split{"first-subject-rest-clip"}else{"all-subject"},"rings":out.len(),"area":area(&out),"coordinates":out.iter().map(|p|p.iter().map(|p|[p.x,p.y]).collect::<Vec<_>>()).collect::<Vec<_>>() })
            );
        }
    }
    if let Some(path) = std::env::args().nth(1) {
        let raw: Vec<Vec<[i64; 2]>> =
            serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        let paths: Paths64 = raw
            .into_iter()
            .map(|p| {
                p.into_iter()
                    .map(|q| Point64::new(q[0], q[1]))
                    .collect::<Path64>()
            })
            .collect();
        let probe: usize = std::env::args()
            .nth(2)
            .expect("candidate first-ring index required")
            .parse()
            .unwrap();
        assert!(probe < paths.len());
        for idx in [0, probe] {
            let mut p = paths.clone();
            let first = p.remove(idx);
            p.insert(0, first);
            for split in [true, false] {
                let out = merge(&p, split);
                println!(
                    "{}",
                    serde_json::json!({"case":"retained-contour-replay","first_source_ring":idx,"grouping":if split{"first-subject-rest-clip"}else{"all-subject"},"rings":out.len(),"area_projected_units2":area(&out)/1e6})
                );
            }
        }
    }
}
