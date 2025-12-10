"""
Visualization utilities for RasFixit.

This module is lazy-loaded to avoid requiring matplotlib unless visualization
is explicitly requested. All matplotlib imports are contained within this module.

The visualization shows:
- Top panel: Original obstructions (with overlaps) using 'viridis' colormap
- Bottom panel: Fixed obstructions (elevation envelope) using 'plasma' colormap
"""

from pathlib import Path
from typing import List

from ..LoggingConfig import get_logger

logger = get_logger(__name__)

# Lazy import flag (cached result)
_MPL_AVAILABLE = None


def _check_matplotlib() -> bool:
    """
    Check if matplotlib is available, caching the result.

    Returns:
        True if matplotlib is importable, False otherwise.
    """
    global _MPL_AVAILABLE
    if _MPL_AVAILABLE is None:
        try:
            import matplotlib
            _MPL_AVAILABLE = True
        except ImportError:
            _MPL_AVAILABLE = False
    return _MPL_AVAILABLE


def visualize_obstruction_fix(
    original: List['BlockedObstruction'],
    fixed: List['BlockedObstruction'],
    rs_id: str,
    save_path: Path
) -> bool:
    """
    Generate before/after PNG visualization for obstruction fix.

    Creates a two-panel figure showing:
    - Top: Original obstructions with overlaps (viridis colormap)
    - Bottom: Fixed obstructions after elevation envelope (plasma colormap)

    Args:
        original: Original overlapping obstructions.
        fixed: Fixed non-overlapping obstructions.
        rs_id: River station identifier (used in title).
        save_path: Output PNG path.

    Returns:
        True if visualization was created successfully, False if matplotlib
        is unavailable or an error occurred.

    Note:
        This function lazy-loads matplotlib to avoid import overhead when
        visualization is not needed.
    """
    if not _check_matplotlib():
        logger.warning("matplotlib not available for visualization")
        return False

    # Import matplotlib inside function (lazy loading)
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import numpy as np

    try:
        # Create 2-subplot figure
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        fig.suptitle(f"Blocked Obstruction Fix for RS: {rs_id}",
                     fontsize=16, fontweight='bold')

        all_obs = original + fixed
        if not all_obs:
            plt.close(fig)
            return False

        # Calculate plot bounds with padding
        min_sta = min(o.start_sta for o in all_obs)
        max_sta = max(o.end_sta for o in all_obs)
        max_elev = max(o.elevation for o in all_obs)
        padding = (max_sta - min_sta) * 0.05 if (max_sta - min_sta) > 0 else 10

        # Top panel: Original (with overlaps)
        ax1.set_title("Original (with Overlaps)")
        if original:
            colors = plt.cm.get_cmap('viridis')(np.linspace(0, 1, len(original)))
            for i, obs in enumerate(original):
                ax1.add_patch(Rectangle(
                    (obs.start_sta, 0), obs.length, obs.elevation,
                    facecolor=colors[i], alpha=0.7, edgecolor='black'
                ))
        ax1.set_ylabel("Elevation")
        ax1.grid(True, linestyle='--', alpha=0.6)
        ax1.set_ylim(0, max_elev * 1.25)

        # Bottom panel: Fixed (elevation envelope)
        ax2.set_title("Fixed (Elevation Envelope)")
        if fixed:
            fixed_colors = plt.cm.get_cmap('plasma')(np.linspace(0, 1, len(fixed)))
            for i, obs in enumerate(fixed):
                ax2.add_patch(Rectangle(
                    (obs.start_sta, 0), obs.length, obs.elevation,
                    facecolor=fixed_colors[i], alpha=0.8, edgecolor='black'
                ))

        ax2.set_xlabel("Station")
        ax2.set_ylabel("Elevation")
        ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.set_xlim(min_sta - padding, max_sta + padding)
        ax2.set_ylim(0, max_elev * 1.25)

        plt.tight_layout(rect=(0, 0.03, 1, 0.95))
        plt.savefig(save_path, dpi=150)
        plt.close(fig)

        logger.debug(f"Saved visualization: {save_path.name}")
        return True

    except Exception as e:
        logger.warning(f"Visualization failed for RS {rs_id}: {e}")
        return False
