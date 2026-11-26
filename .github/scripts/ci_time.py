"""Time an actual command; preserve its exit status and report Linux child RSS."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    label, *command = sys.argv[1:]
    if command and command[0] == "--":
        command = command[1:]
    start = time.monotonic()
    result = subprocess.run(command, check=False)
    peak = None
    if sys.platform == "linux":
        import resource

        # Maximum individual child RSS, not summed concurrent-worker memory.
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
    receipt = dict(
        phase=label,
        seconds=round(time.monotonic() - start, 3),
        exit_code=result.returncode,
        max_individual_child_rss_mib=peak,
        sha=os.environ.get("GITHUB_SHA"),
        run=os.environ.get("GITHUB_RUN_ID"),
    )
    folder = Path(os.environ.get("RUNNER_TEMP", ".")) / "ci-receipts"
    folder.mkdir(exist_ok=True)
    with (folder / "timings.jsonl").open("a", encoding="utf8") as f:
        f.write(json.dumps(receipt) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf8") as f:
            f.write(
                f"\n**{label}**: {receipt['seconds']} s, exit {result.returncode}; "
                f"max individual child RSS: {peak if peak is not None else 'unmeasured'} MiB.\n"
            )
    raise SystemExit(result.returncode if result.returncode >= 0 else 128 - result.returncode)


if __name__ == "__main__":
    main()
