//! Repair polygon topology AFTER integer MVT quantization. Source geometry is
//! never altered. Rounding can create backtracking spikes, self-touching rings,
//! or crossings; integer overlay removes these without a second projection.
use freestiler_core::mvt::{GeomType, Tile};
use i_float::int::point::IntPoint;
use i_overlay::core::{fill_rule::FillRule, overlay::Overlay, overlay_rule::OverlayRule};
use prost::Message;

fn area(ring: &[IntPoint]) -> i128 {
    ring.iter()
        .zip(ring.iter().cycle().skip(1))
        .take(ring.len())
        .map(|(a, b)| i128::from(a.x) * i128::from(b.y) - i128::from(b.x) * i128::from(a.y))
        .sum()
}
fn orient(a: IntPoint, b: IntPoint, c: IntPoint) -> i128 {
    (i128::from(b.x) - i128::from(a.x)) * (i128::from(c.y) - i128::from(a.y))
        - (i128::from(b.y) - i128::from(a.y)) * (i128::from(c.x) - i128::from(a.x))
}
fn intersects(a: IntPoint, b: IntPoint, c: IntPoint, d: IntPoint) -> bool {
    if a.x.max(b.x) < c.x.min(d.x)
        || c.x.max(d.x) < a.x.min(b.x)
        || a.y.max(b.y) < c.y.min(d.y)
        || c.y.max(d.y) < a.y.min(b.y)
    {
        return false;
    }
    let (ab_c, ab_d, cd_a, cd_b) = (
        orient(a, b, c),
        orient(a, b, d),
        orient(c, d, a),
        orient(c, d, b),
    );
    (ab_c == 0 || ab_d == 0 || (ab_c < 0) != (ab_d < 0))
        && (cd_a == 0 || cd_b == 0 || (cd_a < 0) != (cd_b < 0))
}
fn simple(ring: &[IntPoint]) -> bool {
    if ring.len() < 3 || area(ring) == 0 {
        return false;
    }
    for i in 0..ring.len() {
        let next = (i + 1) % ring.len();
        if ring[i] == ring[next] {
            return false;
        }
        // Adjacent edges may share a vertex but must not backtrack over one
        // another. This also catches spikes on three-vertex rings.
        let third = (i + 2) % ring.len();
        if orient(ring[i], ring[next], ring[third]) == 0 {
            let dot = (i128::from(ring[next].x) - i128::from(ring[i].x))
                * (i128::from(ring[third].x) - i128::from(ring[next].x))
                + (i128::from(ring[next].y) - i128::from(ring[i].y))
                    * (i128::from(ring[third].y) - i128::from(ring[next].y));
            if dot < 0 {
                return false;
            }
        }
        for j in i + 1..ring.len() {
            if j == next || (j + 1) % ring.len() == i {
                continue;
            }
            if intersects(ring[i], ring[next], ring[j], ring[(j + 1) % ring.len()]) {
                return false;
            }
        }
    }
    true
}
fn unzig(n: u32) -> i64 {
    i64::from(n >> 1) ^ -i64::from(n & 1)
}
fn parse(commands: &[u32]) -> Result<Vec<Vec<IntPoint>>, String> {
    let mut rings = Vec::new();
    let mut ring = Vec::new();
    let (mut x, mut y) = (0i64, 0i64);
    let mut i = 0;
    while i < commands.len() {
        let cmd = commands[i] & 7;
        let count = (commands[i] >> 3) as usize;
        i += 1;
        if count == 0 {
            return Err("zero MVT command count".into());
        }
        match cmd {
            1 | 2 => {
                if cmd == 1 && (count != 1 || !ring.is_empty()) {
                    return Err("unexpected polygon MoveTo".into());
                }
                if cmd == 2 && ring.is_empty() {
                    return Err("polygon LineTo before MoveTo".into());
                }
                for _ in 0..count {
                    if i + 1 >= commands.len() {
                        return Err("truncated MVT coordinates".into());
                    }
                    x += unzig(commands[i]);
                    y += unzig(commands[i + 1]);
                    i += 2;
                    ring.push(IntPoint::new(
                        i32::try_from(x).map_err(|_| "MVT x overflow")?,
                        i32::try_from(y).map_err(|_| "MVT y overflow")?,
                    ));
                }
            }
            7 if count == 1 => {
                if ring.len() < 3 {
                    return Err("degenerate MVT polygon command ring".into());
                }
                rings.push(std::mem::take(&mut ring));
            }
            _ => return Err("unexpected MVT polygon command".into()),
        }
    }
    if !ring.is_empty() {
        return Err("unclosed MVT command ring".into());
    }
    Ok(rings)
}
fn zig(n: i64) -> Result<u32, String> {
    u32::try_from((n << 1) ^ (n >> 63)).map_err(|_| "MVT coordinate delta overflow".into())
}
fn encode(rings: &[Vec<IntPoint>]) -> Result<Vec<u32>, String> {
    let mut out = Vec::new();
    let (mut x, mut y) = (0i64, 0i64);
    for ring in rings {
        if ring.len() < 3 {
            return Err("invalid repaired ring".into());
        }
        for (i, p) in ring.iter().enumerate() {
            if i == 0 {
                out.push(9);
            } else if i == 1 {
                let count = u32::try_from(ring.len() - 1).map_err(|_| "ring too large")?;
                out.push((count << 3) | 2);
            }
            out.push(zig(i64::from(p.x) - x)?);
            out.push(zig(i64::from(p.y) - y)?);
            x = i64::from(p.x);
            y = i64::from(p.y);
        }
        out.push(15);
    }
    Ok(out)
}
fn repair_rings(rings: Vec<Vec<IntPoint>>) -> Result<Vec<Vec<IntPoint>>, String> {
    let shapes =
        Overlay::with_contours(&rings, &[]).overlay(OverlayRule::Subject, FillRule::NonZero);
    let mut result = Vec::new();
    for shape in shapes {
        for (index, mut ring) in shape.into_iter().enumerate() {
            if !simple(&ring) {
                return Err("integer overlay produced a nonsimple tile ring".into());
            }
            // MVT exteriors have positive area in y-down coordinates.
            if (area(&ring) > 0) != (index == 0) {
                ring.reverse();
            }
            result.push(ring);
        }
    }
    if result.is_empty() {
        // Same visibility contract as freestiler: never drop collapsed features.
        let points: Vec<_> = rings.iter().flatten().collect();
        if points.is_empty() {
            return Err("empty polygon after tile quantization".into());
        }
        let x = (points.iter().map(|p| i64::from(p.x)).sum::<i64>() / points.len() as i64) as i32;
        let y = (points.iter().map(|p| i64::from(p.y)).sum::<i64>() / points.len() as i64) as i32;
        let x1 = x.checked_add(1).ok_or("collapsed tile x overflow")?;
        let y1 = y.checked_add(1).ok_or("collapsed tile y overflow")?;
        result.push(vec![
            IntPoint::new(x, y),
            IntPoint::new(x1, y),
            IntPoint::new(x1, y1),
            IntPoint::new(x, y1),
        ]);
    }
    Ok(result)
}
pub(crate) fn repair(bytes: Vec<u8>) -> Result<Vec<u8>, String> {
    let mut tile =
        Tile::decode(bytes.as_slice()).map_err(|e| format!("decode generated MVT: {e}"))?;
    let mut changed = false;
    for layer in &mut tile.layers {
        for feature in &mut layer.features {
            if feature.r#type != Some(GeomType::Polygon as i32) {
                continue;
            }
            let rings = parse(&feature.geometry)?;
            if rings.len() == 1 && simple(&rings[0]) {
                continue;
            }
            feature.geometry = encode(&repair_rings(rings)?)?;
            changed = true;
        }
    }
    Ok(if changed { tile.encode_to_vec() } else { bytes })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn points(p: &[(i32, i32)]) -> Vec<IntPoint> {
        p.iter().map(|&(x, y)| IntPoint::new(x, y)).collect()
    }
    #[test]
    fn real_g11_quantized_backtracking_spike() {
        // BaldEagle g11 Upper2DArea cell1041 at z6/x18/y23.
        let ring = points(&[(735, 4106), (737, 4106), (736, 4106), (735, 4107)]);
        assert!(!simple(&ring));
        let repaired = repair_rings(vec![ring]).unwrap();
        assert_eq!(repaired.len(), 1);
        assert!(simple(&repaired[0]));
        assert_eq!(area(&repaired[0]), 1);
        assert_eq!(parse(&encode(&repaired).unwrap()).unwrap(), repaired);
    }
    #[test]
    fn intersection_splits_without_dropping_identity() {
        let ring = points(&[(0, 0), (4, 4), (0, 4), (4, 0)]);
        let repaired = repair_rings(vec![ring]).unwrap();
        assert_eq!(repaired.len(), 2);
        assert!(repaired.iter().all(|r| simple(r)));
        assert_eq!(repaired.iter().map(|r| area(r)).sum::<i128>(), 16);
    }
    #[test]
    fn simple_ring_fast_path_and_hole_orientation() {
        let outer = points(&[(0, 0), (8, 0), (8, 8), (0, 8)]);
        let hole = points(&[(2, 2), (2, 6), (6, 6), (6, 2)]);
        assert!(simple(&outer));
        let repaired = repair_rings(vec![outer, hole]).unwrap();
        assert_eq!(repaired.len(), 2);
        assert!(area(&repaired[0]) > 0);
        assert!(area(&repaired[1]) < 0);
    }

    #[test]
    fn real_g01_g11_quantization_regressions() {
        // Eight failures decoded from actual BaldEagle g01/g11 tile archives.
        // Keep metadata in this compact fixture so source cell/tile is auditable.
        let samples: serde_json::Value =
            serde_json::from_str(include_str!("../tests/quantized_regressions.json")).unwrap();
        for sample in samples.as_array().unwrap() {
            let geometry = &sample["geometry"];
            let polygons = if geometry["type"] == "MultiPolygon" {
                geometry["coordinates"].as_array().unwrap().clone()
            } else {
                vec![geometry["coordinates"].clone()]
            };
            let mut rings = Vec::new();
            for polygon in polygons {
                for (i, ring) in polygon.as_array().unwrap().iter().enumerate() {
                    let mut ring: Vec<_> = ring
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|p| {
                            IntPoint::new(
                                p[0].as_i64().unwrap() as i32,
                                p[1].as_i64().unwrap() as i32,
                            )
                        })
                        .collect();
                    if ring.first() == ring.last() {
                        ring.pop();
                    }
                    if (area(&ring) > 0) != (i == 0) {
                        ring.reverse();
                    }
                    rings.push(ring);
                }
            }
            let repaired = repair_rings(rings).unwrap_or_else(|e| panic!("{sample}: {e}"));
            assert!(repaired.iter().all(|r| simple(r)), "{sample}");
            assert_eq!(parse(&encode(&repaired).unwrap()).unwrap(), repaired);
        }
    }
}
