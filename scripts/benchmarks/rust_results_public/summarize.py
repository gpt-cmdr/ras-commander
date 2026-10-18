"""Summarize bench_max_depth.py JSON and pytest JUnit XML into results.json/markdown.

    python summarize.py --bench A.json [B.json] --junit X.xml [...] --out results.json --markdown out.md
"""
import argparse
import json
from pathlib import Path
import statistics
import xml.etree.ElementTree as ET


def junit(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root)
    totals = {k: sum(int(s.get(k, 0)) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    totals["seconds"] = round(sum(float(s.get("time", 0)) for s in suites), 2)
    totals["passed"] = totals["tests"] - totals["failures"] - totals["errors"] - totals["skipped"]
    return totals


def bench(report):
    rows = []
    groups = sorted({(r["fixture"], r["scope"]) for r in report["runs"]})
    for fixture, scope in groups:
        row = dict(fixture=fixture, scope=scope)
        for backend in ("python", "rust"):
            runs = [r for r in report["runs"] if (r["fixture"], r["scope"], r["backend"]) == (fixture, scope, backend)]
            med = lambda key: statistics.median(r.get(key) or 0 for r in runs)
            row[backend] = dict(
                reps=len(runs), total_median_s=round(med("total_seconds"), 4),
                total_min_s=round(min(r["total_seconds"] for r in runs), 4),
                total_max_s=round(max(r["total_seconds"] for r in runs), 4),
                reduction_s=round(med("reduction_seconds") if scope == "public" else med("reduce_seconds"), 4),
                extraction_s=round(med("extraction_seconds"), 4),
                frame_and_geometry_s=round(med("frame_and_geometry_seconds"), 4),
                peak_rss_mib=round(med("peak_rss") / 2**20, 1),
                rss_before_call_mib=round(med("rss_before_call") / 2**20, 1),
                output_sha256=runs[0]["output_sha256"])
        row["speedup_median"] = round(row["python"]["total_median_s"] / row["rust"]["total_median_s"], 2)
        row["outputs_equal"] = row["python"]["output_sha256"] == row["rust"]["output_sha256"]
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bench", nargs="+", type=Path, required=True)
    parser.add_argument("--junit", nargs="*", type=Path, default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    reports = [json.loads(p.read_text("utf-8")) for p in args.bench]
    result = dict(
        hardware=reports[0]["hardware"], native_sha256=reports[0]["native_sha256"],
        cache_scope=reports[0]["cache_scope"], temporary_disk=reports[0]["temporary_disk"],
        fixtures={k: v for r in reports for k, v in r["fixtures"].items()},
        benchmarks=[row for r in reports for row in bench(r)],
        tests={p.name: junit(p) for p in args.junit})
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    if args.markdown:
        lines = ["| Fixture | Scope | Python median s [min-max] | Native median s [min-max] | Speedup | "
                 "Reduction py/native s | Extraction py/native s | Frame+geometry py/native s | "
                 "Peak RSS py/native MiB | Equal |", "|" + "---|" * 10]
        for row in result["benchmarks"]:
            p, n = row["python"], row["rust"]
            lines.append(
                f"| {row['fixture']} | {row['scope']} | {p['total_median_s']} [{p['total_min_s']}-{p['total_max_s']}] | "
                f"{n['total_median_s']} [{n['total_min_s']}-{n['total_max_s']}] | {row['speedup_median']}x | "
                f"{p['reduction_s']}/{n['reduction_s']} | {p['extraction_s']}/{n['extraction_s']} | "
                f"{p['frame_and_geometry_s']}/{n['frame_and_geometry_s']} | {p['peak_rss_mib']}/{n['peak_rss_mib']} | "
                f"{row['outputs_equal']} |")
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
