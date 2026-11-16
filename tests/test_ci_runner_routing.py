"""CI must use explicit local runners, without executing untrusted fork code."""

import json
import re
from pathlib import Path

import pytest

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
TRUSTED = (
    "github.event_name != 'pull_request' || "
    "github.event.pull_request.head.repo.full_name == github.repository"
)


def _jobs(text):
    """Read only job-level fields, leaving step scripts and YAML values untouched."""
    jobs = text.split("\njobs:\n", 1)[1]
    headers = list(re.finditer(r"(?m)^  ([\w-]+):\s*$", jobs))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(jobs)
        yield header[1], jobs[header.start() : end]


@pytest.mark.parametrize(
    "workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name
)
def test_jobs_use_local_runners_or_existing_protected_manual_routes(workflow):
    text = workflow.read_text(encoding="utf-8")
    for name, job in _jobs(text):
        match = re.search(r"(?m)^    runs-on: (.+)$", job)
        assert match, (workflow.name, name)
        route = match[1]
        if workflow.name == "fast-hdf-macos.yml":
            assert name == "native-macos" and route == "macos-15"
            assert (
                "github.event_name == 'workflow_dispatch' && inputs.include_macos"
                in job
            )
            assert not re.search(
                r"(?m)^  (push|pull_request|schedule|workflow_run):", text
            )
            continue
        if workflow.name == "publish-pypi.yml" and name == "publish":
            assert route == "ubuntu-latest"
            assert "name: pypi" in job and "needs: validate" in job
            assert not re.search(
                r"(?m)^  (push|pull_request|schedule|workflow_run):", text
            )
            continue
        if route.startswith("["):
            labels = [value.strip(" \"'") for value in route.strip("[]").split(",")]
            assert "self-hosted" in labels, (workflow.name, name, route)
            assert any(label.startswith("clb-ci-") for label in labels)
        else:
            assert route in {
                "${{ fromJSON(matrix.self_hosted) }}",
                (
                    "${{ fromJSON(matrix.os == 'macos-15' && "
                    '\'["self-hosted", "macOS", "ARM64", "clb-ci-macos"]\' '
                    "|| matrix.self_hosted) }}"
                ),
            }, (workflow.name, name, route)
            mappings = re.findall(r"(?m)^\s+self_hosted: '([^']+)'$", job)
            assert mappings
            for mapping in mappings:
                assert "self-hosted" in json.loads(mapping)
            assert "clb-ci-linux" in job and "clb-ci-windows" in job


@pytest.mark.parametrize(
    "workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name
)
def test_pull_request_jobs_do_not_execute_fork_code_locally(workflow):
    text = workflow.read_text(encoding="utf-8")
    if not re.search(r"(?m)^  pull_request:", text):
        return
    for name, job in _jobs(text):
        condition = re.search(r"(?m)^    if: (.+)$", job)
        # Packaging's build/validate inherit the fork guard via needs: plan.
        if workflow.name == "packaging-dry-run.yml" and name in {"build", "validate"}:
            assert re.search(r"(?m)^    needs:.*plan", job)
            continue
        if workflow.name == "fast-hdf.yml" and name == "bounded-codeql":
            assert (
                "github.event_name == 'workflow_dispatch' && inputs.qualify_codeql"
                in condition[1]
            )
            continue
        assert condition and TRUSTED in condition[1], (workflow.name, name)


def test_dss_coverage_and_release_authorization_are_retained():
    dss = (WORKFLOWS / "native-dss.yml").read_text(encoding="utf-8")
    assert len(re.findall(r"backend: native", dss)) == 2
    assert len(re.findall(r"backend: shadow", dss)) == 1
    assert "- os: linux" in dss and "- os: windows" in dss
    assert "--min-passed 600 $extra" in dss
    assert "python scripts/ci/native_dss_ci_guard.py engine" in dss
    release = dict(_jobs((WORKFLOWS / "publish-pypi.yml").read_text(encoding="utf-8")))[
        "publish"
    ]
    condition = re.search(r"(?m)^    if: (.+)$", release)[1]
    assert "vars.PUBLISH_PYPI == 'true'" in condition
    assert "github.event_name == 'workflow_dispatch'" in condition
    assert "github.event_name == 'release'" in condition
    assert "needs: validate" in release
    assert "name: pypi" in release
