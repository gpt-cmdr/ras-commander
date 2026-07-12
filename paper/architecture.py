"""Generate or verify the deterministic architecture figure used by JOSS."""

import argparse
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle


OUTPUT_PATH = Path(__file__).with_name("architecture.png")

COLORS = {
    "ink": "#17202A",
    "muted": "#566573",
    "line": "#5D6D7E",
    "api": "#D6EAF8",
    "author": "#D5F5E3",
    "data": "#FCF3CF",
    "engine": "#FADBD8",
    "white": "#FFFFFF",
}


def add_box(ax, x, y, width, height, title, lines, color):
    """Draw a square-cornered layer box with a compact heading and body."""
    ax.add_patch(
        Rectangle(
            (x, y),
            width,
            height,
            facecolor=color,
            edgecolor=COLORS["line"],
            linewidth=1.1,
            zorder=2,
        )
    )
    ax.text(
        x + 0.18,
        y + height - 0.20,
        title,
        ha="left",
        va="top",
        fontsize=9.5,
        fontweight="bold",
        color=COLORS["ink"],
        zorder=3,
    )
    ax.text(
        x + 0.18,
        y + height - 0.55,
        lines,
        ha="left",
        va="top",
        fontsize=7.8,
        linespacing=1.35,
        color=COLORS["ink"],
        zorder=3,
    )


def add_arrow(ax, start, end, *, double=False):
    """Draw a connector behind the layer boxes."""
    style = "<->" if double else "->"
    ax.add_patch(
        FancyArrowPatch(
            start,
            end,
            arrowstyle=style,
            mutation_scale=11,
            linewidth=1.1,
            color=COLORS["line"],
            zorder=1,
        )
    )


def render(output_path):
    """Build the architecture diagram at a fixed size and resolution."""
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8,
            "figure.facecolor": COLORS["white"],
            "savefig.facecolor": COLORS["white"],
        }
    )

    fig, ax = plt.subplots(figsize=(10.0, 6.2))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7)
    ax.axis("off")

    ax.text(
        5,
        6.68,
        "ras-commander architecture",
        ha="center",
        va="center",
        fontsize=15,
        fontweight="bold",
        color=COLORS["ink"],
    )
    ax.text(
        5,
        6.34,
        "Python orchestration around native, reviewable HEC-RAS projects",
        ha="center",
        va="center",
        fontsize=8.5,
        color=COLORS["muted"],
    )

    add_box(
        ax,
        1.0,
        5.10,
        8.0,
        0.95,
        "Public workflow API",
        "init_ras_project()  |  project DataFrames  |  static Ras* and Hdf* methods\n"
        "structured return values  |  concise operational logging",
        COLORS["api"],
    )

    add_box(
        ax,
        0.35,
        2.35,
        2.85,
        1.73,
        "Authoring and validation",
        "Plans and boundary conditions\nGeometry, land cover, and terrain\nRASMapper configuration\nModel checks and repair helpers",
        COLORS["author"],
    )
    add_box(
        ax,
        3.58,
        2.35,
        2.84,
        1.73,
        "Execution and monitoring",
        "Compute and preprocessors\nLocal parallel execution\nPsExec and container workers\nCallbacks and execution summaries",
        COLORS["api"],
    )
    add_box(
        ax,
        6.80,
        2.35,
        2.85,
        1.73,
        "Data access and analysis",
        "HDF geometry and hydraulic results\nDSS time series and precipitation\nUSGS observations\nPandas / GeoPandas / xarray",
        COLORS["data"],
    )

    add_arrow(ax, (3.30, 5.10), (1.78, 4.08), double=True)
    add_arrow(ax, (5.00, 5.10), (5.00, 4.08), double=True)
    add_arrow(ax, (6.70, 5.10), (8.22, 4.08), double=True)

    add_box(
        ax,
        0.58,
        0.35,
        2.55,
        1.40,
        "HEC-RAS engines",
        "Ras.exe and preprocessors\nLegacy HECRASController COM\nRasMapperLib where supported",
        COLORS["engine"],
    )
    add_box(
        ax,
        3.73,
        0.35,
        2.55,
        1.40,
        "Native project record",
        ".prj, .p##, .g##, .u##, .f##\nHDF5, HEC-DSS, and .rasmap\nTerrain and spatial resources",
        COLORS["engine"],
    )
    add_box(
        ax,
        6.88,
        0.35,
        2.55,
        1.40,
        "External data services",
        "USGS water data\nNOAA precipitation products\nPublic model and terrain sources",
        COLORS["engine"],
    )

    add_arrow(ax, (2.70, 2.35), (1.85, 1.75), double=True)
    add_arrow(ax, (4.60, 2.35), (4.95, 1.75), double=True)
    add_arrow(ax, (5.55, 2.35), (2.78, 1.75), double=True)
    add_arrow(ax, (7.28, 2.35), (5.95, 1.75), double=True)
    add_arrow(ax, (8.15, 2.35), (8.15, 1.75), double=True)

    fig.savefig(
        output_path,
        dpi=300,
        metadata={"Software": "ras-commander paper/architecture.py"},
    )
    plt.close(fig)


def sha256(path):
    """Return the SHA-256 digest of a generated artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_committed_figure():
    """Re-render and fail if the committed figure is not reproducible."""
    if not OUTPUT_PATH.exists():
        raise FileNotFoundError(f"Missing committed figure: {OUTPUT_PATH}")
    with TemporaryDirectory() as temp_dir:
        candidate = Path(temp_dir) / OUTPUT_PATH.name
        render(candidate)
        if candidate.read_bytes() != OUTPUT_PATH.read_bytes():
            raise RuntimeError(
                "architecture.png is stale or was generated in a different "
                f"environment (expected {sha256(OUTPUT_PATH)}, "
                f"rendered {sha256(candidate)})"
            )


def main():
    """Parse command-line options and generate or verify the figure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that architecture.png matches a fresh render",
    )
    args = parser.parse_args()
    if args.check:
        check_committed_figure()
    else:
        render(OUTPUT_PATH)


if __name__ == "__main__":
    main()
