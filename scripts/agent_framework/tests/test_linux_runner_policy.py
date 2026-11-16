"""Linux release jobs must remain local and preserve protected OIDC publishing."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class LinuxRunnerPolicyTests(unittest.TestCase):
    def test_no_hosted_linux_routes(self):
        for workflow in (ROOT / ".github/workflows").glob("*.yml"):
            text = workflow.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"(?i)ubuntu-(latest|[0-9])", workflow.name)
            for route in re.findall(r"(?m)^    runs-on: (.+)$", text):
                self.assertTrue(
                    "self-hosted" in route
                    or route == "${{ fromJSON(matrix.self_hosted) }}"
                    or (workflow.name == "fast-hdf-macos.yml" and route == "macos-15"),
                    (workflow.name, route),
                )
            for mapping in re.findall(r"(?m)^\s+self_hosted: '([^']+)'$", text):
                self.assertIn("self-hosted", mapping, workflow.name)

    def test_publish_preserves_oidc_and_approval_without_docker(self):
        text = (ROOT / ".github/workflows/publish-pypi.yml").read_text(encoding="utf-8")
        publish = text.split("\n  publish:\n", 1)[1]
        for required in (
            'runs-on: ["self-hosted", "Linux", "X64", "clb-ci-linux"]',
            "needs: validate",
            "name: pypi",
            "id-token: write",
            "vars.PUBLISH_PYPI == 'true'",
            "python -m pypi_attestations sign dist/*",
            "python -m twine upload --attestations --non-interactive --config-file /dev/null dist/*",
        ):
            self.assertIn(required, publish)
        self.assertNotIn("pypa/gh-action-pypi-publish", publish)
        self.assertNotIn("secrets.", publish)
        self.assertNotIn("actions/checkout", publish)

    def test_publish_clears_stale_artifacts_before_download(self):
        text = (ROOT / ".github/workflows/publish-pypi.yml").read_text(encoding="utf-8")
        publish = text.split("\n  publish:\n", 1)[1]
        cleanup = publish.index("name: Clear the publish artifact directory")
        download = publish.index("name: Download the validated distributions")
        self.assertLess(cleanup, download)
        self.assertIn("rm -rf -- dist", publish[cleanup:download])
        # No interpreter is guaranteed before setup-python runs.
        self.assertNotIn("python", publish[cleanup:download].split("run:", 1)[1])
        self.assertLess(cleanup, publish.index("uses: actions/setup-python"))
