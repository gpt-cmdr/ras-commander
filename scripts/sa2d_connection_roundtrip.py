"""Lossless SA/2D read/write example using a disposable official example project.

Run: uv run python scripts/sa2d_connection_roundtrip.py --output-dir working/sa2d-example
No HEC-RAS execution or hydraulic qualification is performed.
"""

import argparse
import shutil
from pathlib import Path

from ras_commander import GeomLateral, RasExamples, get_logger

logger = get_logger(__name__)


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    project = RasExamples.extract_project(
        "BaldEagleCrkMulti2D", output_path=args.output_dir
    )
    source = project / "BaldEagleDamBrk.g13"
    destination = args.output_dir / "roundtrip.g13"
    if destination.exists():
        raise FileExistsError(f"Choose a fresh output directory: {destination}")
    shutil.copy2(source, destination)
    connections = GeomLateral.get_connection_data(source)
    GeomLateral.write_connection_data(destination, connections)
    reread = GeomLateral.get_connection_data(destination)
    assert connections["RawBlock"].tolist() == reread["RawBlock"].tolist()
    assert source.read_bytes() == destination.read_bytes()
    logger.info("Round-tripped %d connections to %s", len(reread), destination)
    logger.info("Native attachment and hydraulic seam equivalence remain unverified")


if __name__ == "__main__":
    _main()
