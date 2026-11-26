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
        for event in ["push", "schedule", "workflow_dispatch", "workflow_call"]:
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

    def test_shell_metacharacters_are_literal_arguments(self):
        import os
        from pathlib import Path
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "literal.txt"
            marker = Path(folder) / "must-not-exist"
            payload = f'literal & echo injected > "{marker}"'
            probe = "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])"
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("ci_time.py")),
                    "literal-argv",
                    "--",
                    sys.executable,
                    "-c",
                    probe,
                    str(output),
                    payload,
                ],
                env=dict(os.environ, RUNNER_TEMP=folder),
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), payload)
            self.assertFalse(marker.exists())


class WorkflowAdmissionTests(unittest.TestCase):
    def test_actual_condition_and_receipt_fail_closed(self):
        import ast
        import os
        from pathlib import Path
        import shutil
        import subprocess

        workflow = Path(__file__).resolve().parents[1] / "workflows/native-dss.yml"
        block = workflow.read_text(encoding="utf8").split("  native-dss:", 1)[1]
        # Extract the actual GitHub condition, not a duplicated policy function.
        condition = next(
            line.strip()[4:].removeprefix("${{").removesuffix("}}").strip()
            for line in block.splitlines()
            if line.strip().startswith("if: ${{")
        )
        receipt = next(
            line.strip()[5:]
            for line in block.splitlines()
            if line.strip().startswith('run: test "$PLAN_RESULT"')
        )
        for result, heavy, cancelled, fork, admitted, valid in [
            ("success", "true", False, False, True, True),
            ("success", "false", False, False, False, True),
            ("failure", "", False, False, True, False),
            ("success", "", False, False, True, False),
            ("success", "invalid", False, False, True, False),
            ("skipped", "", False, False, True, False),
            ("success", "true", True, False, False, True),
            ("success", "true", False, True, False, True),
        ]:
            value = condition.removeprefix("${{").strip()
            replacements = {
                "!cancelled()": str(not cancelled),
                "needs.change-plan.result": repr(result),
                "needs.change-plan.outputs.heavy": repr(heavy),
                "github.event_name": repr("pull_request"),
                "github.event.pull_request.head.repo.full_name": repr(
                    "fork/repo" if fork else "owner/repo"
                ),
                "github.repository": repr("owner/repo"),
            }
            for key, replacement in replacements.items():
                value = value.replace(key, replacement)
            value = value.replace("&&", "and").replace("||", "or")
            tree = ast.parse(value, mode="eval")
            allowed = (
                ast.Expression,
                ast.BoolOp,
                ast.And,
                ast.Or,
                ast.Compare,
                ast.Eq,
                ast.NotEq,
                ast.Constant,
            )
            self.assertTrue(all(isinstance(node, allowed) for node in ast.walk(tree)))

            def evaluate(node):
                if isinstance(node, ast.Expression):
                    return evaluate(node.body)
                if isinstance(node, ast.Constant):
                    return node.value
                if isinstance(node, ast.BoolOp):
                    values = [evaluate(child) for child in node.values]
                    return all(values) if isinstance(node.op, ast.And) else any(values)
                if isinstance(node, ast.Compare):
                    left = evaluate(node.left)
                    for op, right_node in zip(node.ops, node.comparators):
                        right = evaluate(right_node)
                        if (left == right) != isinstance(op, ast.Eq):
                            return False
                        left = right
                    return True
                self.fail("Unsupported workflow expression")

            self.assertEqual(evaluate(tree), admitted)
            bash = shutil.which("bash")
            if os.name == "nt":
                git_bash = (
                    Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
                )
                if git_bash.is_file():
                    bash = str(git_bash)
            self.assertIsNotNone(bash)
            response = subprocess.run(
                [bash, "--noprofile", "--norc", "-c", receipt],
                env=dict(os.environ, PLAN_RESULT=result, PLAN_HEAVY=heavy),
                capture_output=True,
            )
            self.assertEqual(response.returncode == 0, valid)

    def test_non_pr_groups_retain_each_main_revision(self):
        from pathlib import Path

        workflow = (Path(__file__).resolve().parents[1] / "workflows/native-dss.yml").read_text(
            encoding="utf8"
        )
        self.assertIn("format('run-{0}', github.run_id)", workflow)
        self.assertTrue(select(["README.md"], event="push")[0])


if __name__ == "__main__":
    unittest.main()
