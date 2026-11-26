import sys
import unittest

from ci_plan import select


class SelectionTests(unittest.TestCase):
    def test_documentation_only(self):
        self.assertFalse(select(["AGENTS.md", "CLAUDE.md"])[0])

    def test_uncertain_inputs_always_widen(self):
        for path in [
            "tests/fixture.md",
            "tests/conftest.py",
            "docs/fixture.json",
            ".github/workflows/ci.yml",
            "Cargo.lock",
            "pipeline/a.py",
            "src/a.rs",
            "old.py",
            "new.py",
            "docs/new-owner.md",
            "__deleted_renamed_copied_or_typechanged_input__",
        ]:
            self.assertTrue(select(["README.md", path])[0], path)

    def test_unknown_empty_manual_schedule_and_override_widen(self):
        self.assertTrue(select([])[0])
        for event in ["schedule", "workflow_dispatch", "workflow_call"]:
            self.assertTrue(select(["README.md"], event)[0])
        self.assertTrue(select(["README.md"], force=True)[0])


class GitDiffTests(unittest.TestCase):
    def test_real_diff_missing_base_deletion_rename_and_new_owner(self):
        import json
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        script = str(Path(__file__).with_name("ci_plan.py").resolve())
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repo = root / "repo"
            repo.mkdir()

            def git(*args):
                return subprocess.check_output(
                    [
                        "git",
                        "-c",
                        "commit.gpgsign=false",
                        "-c",
                        "user.name=CI Test",
                        "-c",
                        "user.email=ci@example.invalid",
                        *args,
                    ],
                    cwd=repo,
                    text=True,
                ).strip()

            git("init", "--template=")
            (repo / "AGENTS.md").write_text("original", encoding="utf8")
            git("add", "AGENTS.md")
            git("commit", "-m", "base")
            base = git("rev-parse", "HEAD")
            event = root / "event.json"
            event.write_text(json.dumps({"pull_request": {"base": {"sha": base}}}), encoding="utf8")

            def check(expected, bad_base=False):
                if bad_base:
                    event.write_text("{}", encoding="utf8")
                output = root / "output"
                output.write_text("", encoding="utf8")
                env = dict(
                    os.environ,
                    GITHUB_EVENT_NAME="pull_request",
                    GITHUB_EVENT_PATH=str(event),
                    GITHUB_SHA=git("rev-parse", "HEAD"),
                    GITHUB_OUTPUT=str(output),
                    GITHUB_STEP_SUMMARY=str(root / "summary"),
                    CI_FULL="false",
                )
                subprocess.run(
                    [sys.executable, script], cwd=repo, env=env, check=True, capture_output=True
                )
                self.assertIn("heavy=" + str(expected).lower(), output.read_text())

            (repo / "AGENTS.md").write_text("modified", encoding="utf8")
            git("commit", "-am", "modified known docs")
            check(False)
            git("mv", "AGENTS.md", "CLAUDE.md")
            git("commit", "-m", "renamed docs")
            check(True)
            git("rm", "CLAUDE.md")
            git("commit", "-m", "deleted docs")
            check(True)
            check(True, bad_base=True)


class TimingTests(unittest.TestCase):
    def test_failure_exit_and_receipt_are_preserved(self):
        import json
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            env = dict(
                os.environ, RUNNER_TEMP=folder, GITHUB_STEP_SUMMARY=str(Path(folder) / "summary")
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("ci_time.py")),
                    "failing-check",
                    "--",
                    sys.executable,
                    "-c",
                    "raise SystemExit(7)",
                ],
                env=env,
            )
            self.assertEqual(result.returncode, 7)
            receipt = json.loads((Path(folder) / "ci-receipts/timings.jsonl").read_text())
            self.assertEqual(receipt["exit_code"], 7)
            self.assertGreaterEqual(receipt["seconds"], 0)


if __name__ == "__main__":
    unittest.main()
