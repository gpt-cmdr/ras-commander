"""
Fixit Subpackage - Automated Geometry Repair for HEC-RAS Models

This subpackage provides automated fix capabilities for common HEC-RAS
geometry issues. It complements the check subpackage by providing
repair functionality for detected issues.

Classes:
    RasFixit - Main static class with fix methods
    FixResults - Container for fix operation results
    FixMessage - Individual fix action message
    FixAction - Enum of fix action types
    BlockedObstruction - Dataclass representing a single obstruction

Modules:
    log_parser - HEC-RAS compute log parsing for error detection

Supported Fixes:
    - Blocked Obstruction Overlaps (FX_BO_01): Resolves overlapping obstructions
      using maximum elevation envelope algorithm
    - HTAB Starting Elevation (FX_HTAB_01): Corrects starting_el < invert issues
      that cause HEC-RAS to fail during geometry preprocessing (common after
      version upgrades)

Integration with Check Module:
    RasCheck detects issues; RasFixit provides corresponding fix methods:
      - RasCheck.check_htab_params() -> RasFixit.fix_htab_starting_elevations()
      - RasCheck.check_xs() (obstructions) -> RasFixit.fix_blocked_obstructions()

Engineering Review Requirements:
    IMPORTANT: All fixes should be reviewed by a licensed professional engineer
    before accepting changes to production models. Visualization outputs
    provide audit trail for review.

Example - Fix HTAB Starting Elevation Issues:
    >>> from ras_commander import RasFixit
    >>>
    >>> # Fix HTAB starting_el < invert issues (version upgrade problem)
    >>> results = RasFixit.fix_htab_starting_elevations("model.g01")
    >>> print(f"Fixed {results.total_xs_fixed} cross sections")
    >>>
    >>> # Detection only (dry run)
    >>> results = RasFixit.detect_htab_issues("model.g01")
    >>> for msg in results.messages:
    ...     print(f"  {msg.river}/{msg.reach}/RS {msg.station}: {msg.message}")

Example - Fix Blocked Obstructions:
    >>> from ras_commander import RasFixit
    >>>
    >>> # Fix with visualization for engineering review
    >>> results = RasFixit.fix_blocked_obstructions(
    ...     "model.g01",
    ...     backup=True,
    ...     visualize=True
    ... )
    >>> print(f"Fixed {results.total_xs_fixed} cross sections")
    >>> print(f"Backup: {results.backup_path}")
    >>> print(f"Visualizations: {results.visualization_folder}")

Example - Detection Only:
    >>> results = RasFixit.detect_obstruction_overlaps("model.g01")
    >>> print(f"Found {results.total_xs_fixed} cross sections with overlaps")

Example - Log Parsing Workflow:
    >>> from ras_commander.fixit import log_parser
    >>> from ras_commander import RasFixit
    >>>
    >>> # Parse compute log for errors
    >>> with open("compute.log", "r") as f:
    ...     log_content = f.read()
    >>>
    >>> errors = log_parser.detect_obstruction_errors(log_content)
    >>> if errors:
    ...     print(log_parser.generate_error_report(errors))
    ...
    ...     # Find and fix affected geometry files
    ...     geom_files = log_parser.find_geometry_files_in_directory(project_dir)
    ...     for geom_path in geom_files:
    ...         results = RasFixit.fix_blocked_obstructions(geom_path, visualize=True)
    ...         print(f"Fixed {results.total_xs_fixed} cross sections in {geom_path}")

Example - DataFrame Output:
    >>> results = RasFixit.fix_blocked_obstructions("model.g01")
    >>> df = results.to_dataframe()
    >>> df.to_csv("fix_report.csv")
"""

from .RasFixit import RasFixit
from .results import FixResults, FixMessage, FixAction
from .obstructions import BlockedObstruction

# log_parser is available as a submodule: from ras_commander.fixit import log_parser

__all__ = [
    'RasFixit',
    'FixResults',
    'FixMessage',
    'FixAction',
    'BlockedObstruction',
]
