"""Measure buffered sequential I/O at writer-relevant request sizes.

This is a storage-path microbenchmark, not a local-staging feature. It creates
one owned file at a time in the requested directory, flushes it, performs a
warm-cache sequential read, and removes it unless ``--keep-files`` is set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from benchmark_store_maps_memory import _storage_metadata


def _parse_block_sizes(raw: str) -> list[int]:
    values = []
    for item in raw.split(","):
        value = int(item.strip())
        if value < 1:
            raise argparse.ArgumentTypeError("block sizes must be positive")
        values.append(value * 1024)
    if not values:
        raise argparse.ArgumentTypeError("at least one block size is required")
    return values


def _throughput_mib_per_second(byte_count: int, elapsed: float) -> float:
    return byte_count / (1024 * 1024) / elapsed if elapsed > 0 else 0.0


def _run_pass(path: Path, total_bytes: int, block_bytes: int) -> dict[str, Any]:
    payload = bytes((index % 251 for index in range(block_bytes)))
    remaining = total_bytes
    write_operations = 0
    started = time.perf_counter()
    with path.open("xb", buffering=0) as stream:
        while remaining:
            chunk = payload if remaining >= block_bytes else payload[:remaining]
            stream.write(chunk)
            remaining -= len(chunk)
            write_operations += 1
        os.fsync(stream.fileno())
    write_elapsed = time.perf_counter() - started

    digest = hashlib.sha256()
    read_operations = 0
    read_bytes = 0
    started = time.perf_counter()
    with path.open("rb", buffering=0) as stream:
        while True:
            chunk = stream.read(block_bytes)
            if not chunk:
                break
            digest.update(chunk)
            read_bytes += len(chunk)
            read_operations += 1
    read_elapsed = time.perf_counter() - started

    return {
        "block_bytes": block_bytes,
        "file_bytes": total_bytes,
        "write_operations": write_operations,
        "write_elapsed_seconds": round(write_elapsed, 6),
        "write_mib_per_second": round(
            _throughput_mib_per_second(total_bytes, write_elapsed),
            3,
        ),
        "warm_read_operations": read_operations,
        "warm_read_elapsed_seconds": round(read_elapsed, 6),
        "warm_read_mib_per_second": round(
            _throughput_mib_per_second(read_bytes, read_elapsed),
            3,
        ),
        "sha256": digest.hexdigest(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--label", default="")
    parser.add_argument("--size-mb", type=int, default=256)
    parser.add_argument(
        "--block-sizes-kb",
        type=_parse_block_sizes,
        default=_parse_block_sizes("4,16,64,1024,8192"),
    )
    parser.add_argument("--keep-files", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    directory = Path(os.path.abspath(args.directory))
    report_path = Path(os.path.abspath(args.report_path))
    if args.size_mb < 1:
        raise ValueError("size-mb must be positive")
    directory.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total_bytes = args.size_mb * 1024 * 1024
    results = []
    for block_bytes in args.block_sizes_kb:
        path = directory / f"ras_io_profile_{block_bytes}.bin"
        if path.exists():
            raise FileExistsError(f"Benchmark-owned path already exists: {path}")
        try:
            result = _run_pass(path, total_bytes, block_bytes)
            result["path"] = str(path)
            results.append(result)
        finally:
            if path.exists() and not args.keep_files:
                path.unlink()

    report = {
        "schema": "ras-commander.storage-io-benchmark/1",
        "label": args.label,
        "directory": str(directory),
        "storage": _storage_metadata(directory),
        "size_mb": args.size_mb,
        "buffering": "unbuffered Python stream; Windows filesystem cache active",
        "flush_semantics": "one os.fsync after all writes",
        "read_semantics": "immediate warm-cache sequential read",
        "results": results,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
