"""Bounded subprocess worker for legacy ScienceBase HEC-RAS validation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ras_commander import RasControl, RasPrj, init_ras_project


def main() -> int:
    """Run one legacy plan through ``RasControl`` and persist its result."""
    parser = argparse.ArgumentParser()
    parser.add_argument("project_file", type=Path)
    parser.add_argument("ras_version")
    parser.add_argument("plan_number")
    parser.add_argument("result_file", type=Path)
    args = parser.parse_args()

    ras_obj = RasPrj()
    init_ras_project(
        args.project_file,
        args.ras_version,
        ras_object=ras_obj,
        load_results_summary=False,
        hide_intro=True,
    )
    result = RasControl.run_plan(
        args.plan_number,
        ras_object=ras_obj,
        force_recompute=True,
        use_watchdog=True,
        refresh_results=False,
    )
    messages = RasControl.get_comp_msgs(args.plan_number, ras_object=ras_obj)
    payload = {
        "success": bool(result),
        "controller_messages": list(result.messages),
        "compute_messages": messages,
    }
    args.result_file.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    return 0 if result else 2


if __name__ == "__main__":
    raise SystemExit(main())
