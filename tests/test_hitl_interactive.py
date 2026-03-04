import json
import os
import shutil
import subprocess
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import my_opt_code_agent.cli as cli_module


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MYOPT_PRINT_ALERTS", "0")


class HitlInteractiveTest(unittest.TestCase):
    def _run_with_inputs(self, inputs: list[str]) -> tuple[int, str, dict[str, str], Path]:
        parser = cli_module.build_parser()
        tmp_root = ROOT / "tests" / ".tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        repo = tmp_root / f"hitl_repo_{uuid.uuid4().hex}"
        repo.mkdir(parents=True, exist_ok=False)
        (repo / "README.md").write_text("# HITL Repo\n", encoding="utf-8")
        self._git(["init"], repo)
        self._git(["config", "user.email", "dev@example.com"], repo)
        self._git(["config", "user.name", "Dev"], repo)
        self._git(["add", "README.md"], repo)
        self._git(["commit", "-m", "init"], repo)
        args = parser.parse_args(
            [
                "run",
                "--repo",
                str(repo),
                "--task",
                "hitl interactive test",
                "--verify-cmd",
                "echo withdraw now",
                "--hitl",
                "--review-providers",
                "local",
                "--max-iters",
                "1",
            ]
        )
        stream = StringIO()
        try:
            it = iter(inputs)

            def fake_input(_prompt: str) -> str:
                return next(it)

            with mock.patch.dict(
                os.environ,
                {"MYOPT_NON_INTERACTIVE": "", "MYOPT_ENABLE_REAL_PROVIDERS": "0"},
                clear=False,
            ):
                with redirect_stdout(stream):
                    rc = cli_module.run_phase3(args, input_fn=fake_input)
            text = stream.getvalue()
            return rc, text, self._parse_artifact_paths(text), repo
        finally:
            self.addCleanup(lambda: shutil.rmtree(repo, ignore_errors=True))

    def _git(self, args: list[str], cwd: Path) -> None:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            self.fail(f"git command failed: {' '.join(args)}\n{proc.stderr}\n{proc.stdout}")

    def test_hitl_prompt_entered_when_mid_high_exists(self) -> None:
        rc, _, paths, repo = self._run_with_inputs(["deny-all", "continue"])
        self.assertEqual(rc, 0)
        trace_text = (repo / paths["TRACE"]).read_text(encoding="utf-8")
        self.assertIn('"event": "hitl_prompt_shown"', trace_text)
        self.assertIn('"event": "hitl_command_received"', trace_text)

    def test_hitl_deny_all_then_continue_skips_mid_high(self) -> None:
        rc, out, paths, repo = self._run_with_inputs(["deny-all", "continue"])
        self.assertEqual(rc, 0)
        state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
        self.assertEqual(state["user_constraints"]["denied_ids"], ["all"])
        self.assertEqual(state["verification_history"][0]["executed"], [])

    def test_hitl_approve_all_and_set_qps(self) -> None:
        rc, _, paths, repo = self._run_with_inputs(["approve-all", "set global_qps=1", "continue"])
        self.assertNotEqual(rc, 0)
        state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
        self.assertIn("*", state["user_constraints"]["approved_ids"])
        self.assertEqual(state["user_constraints"]["rate_limit"]["global_qps"], 1.0)
        cmd = state["verification_history"][0]["executed"][0]["cmd"]
        self.assertEqual(cmd, "echo withdraw now")

    def test_hitl_fallback_only_executes_fallback(self) -> None:
        rc, _, paths, repo = self._run_with_inputs(["fallback-only", "continue"])
        self.assertEqual(rc, 0)
        state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
        cmd = state["verification_history"][0]["executed"][0]["cmd"]
        self.assertEqual(cmd, "python -m compileall .")

    def test_hitl_abort_stops_and_records_trace_report(self) -> None:
        rc, _, paths, repo = self._run_with_inputs(["abort"])
        self.assertNotEqual(rc, 0)

        state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "stopped")
        self.assertIn("HITL aborted by user", state.get("stopped_reason", ""))
        self.assertTrue(any(item["type"] == "hitl_abort" for item in state.get("alerts", [])))

        report_text = (repo / paths["REPORT"]).read_text(encoding="utf-8")
        self.assertIn("## HITL", report_text)
        self.assertIn("HITL aborted by user", report_text)

        trace_text = (repo / paths["TRACE"]).read_text(encoding="utf-8")
        self.assertIn('"event": "hitl_prompt_shown"', trace_text)
        self.assertIn('"event": "hitl_command_received"', trace_text)
        self.assertIn('"event": "hitl_decision_finalized"', trace_text)

    def _parse_artifact_paths(self, text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            for key in ["RUN_DIR", "REPORT", "DIFF", "STATE", "TRACE"]:
                prefix = f"{key}:"
                if line.startswith(prefix):
                    out[key] = line[len(prefix) :].strip()
        self.assertEqual(set(out.keys()), {"RUN_DIR", "REPORT", "DIFF", "STATE", "TRACE"})
        for key in ["REPORT", "DIFF", "STATE", "TRACE"]:
            p = Path(out[key])
            if not p.is_absolute():
                out[key] = str((ROOT / p).resolve())
        return out


if __name__ == "__main__":
    unittest.main()
