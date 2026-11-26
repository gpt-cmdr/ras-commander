"""Conservative CI admission: only proven documentation-only diffs narrow work."""

import json
import os
import re
import subprocess
from pathlib import Path

SAFE_DOCS = frozenset(
    {
        ".github/CI-EFFICIENCY.md",
        "AGENTS.md",
        "CHANGELOG.md",
        "CLAUDE.md",
        "README.md",
        "docs/index.md",
        "docs/user-guide/dss-native-backend.md",
        "docs/user-guide/dss-operations.md",
    }
)


def select(paths, event="pull_request", force=False):
    if force or event != "pull_request" or not paths:
        return True, "full: explicit, scheduled, manual, or unavailable diff"
    for raw in paths:
        if raw not in SAFE_DOCS:
            return True, "full: runtime, test, fixture, configuration, or unknown owner"
    return False, "documentation-only: no executable or fixture input changed"


def main():
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf8"))
        base = (
            payload["pull_request"]["base"]["sha"]
            if event == "pull_request"
            else payload.get("before", "")
        )
        head = os.environ.get("GITHUB_SHA", "")
        if not all(
            re.fullmatch(r"[0-9a-f]{40,64}", x or "") and set(x) != {"0"} for x in (base, head)
        ):
            raise ValueError("missing comparison")
        paths = (
            subprocess.check_output(
                ["git", "diff", "--name-only", "--no-renames", "-z", base, head, "--"], timeout=30
            )
            .decode("utf8")
            .split("\0")
        )
        paths = [p for p in paths if p]
        exceptional = subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                "--diff-filter=CDRTUXB",
                "--find-renames",
                "-z",
                base,
                head,
                "--",
            ],
            timeout=30,
        )
        if exceptional:
            paths.append("__deleted_renamed_copied_or_typechanged_input__")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        paths = []
    heavy, reason = select(paths, event, os.environ.get("CI_FULL", "").lower() == "true")
    public = bool(list(Path("public").rglob("*"))) if Path("public").is_dir() else False
    result = {"heavy": str(heavy).lower(), "public": str(public).lower()}
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf8") as f:
        for key, value in result.items():
            f.write(f"{key}={value}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf8") as f:
        f.write(f"## CI selection\n{reason}. Changed paths: {len(paths)}.\n")
    print(reason)


if __name__ == "__main__":
    main()
