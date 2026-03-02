import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

from internal.schemas.state import UserConstraints
from internal.tools.policy_gate import apply_policy_gate
from internal.tools.risk_scan import detect_network_indicators
from internal.tools.test_plan import build_test_plan


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / ".tmp"
TMP_ROOT.mkdir(parents=True, exist_ok=True)


class RiskScanPolicyTest(unittest.TestCase):
    def test_detect_network_indicators_returns_findings(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            src = repo / "src"
            src.mkdir(parents=True, exist_ok=True)
            target = src / "net_client.py"
            target.write_text(
                'URL = "https://api.example.com/v1/order"\n'
                'WS = "wss://stream.example.com/ws"\n'
                "kind = 'websocket'\n",
                encoding="utf-8",
            )
            findings = detect_network_indicators(repo, touched_files=["src/net_client.py"], extra_paths=[])
            self.assertGreaterEqual(len(findings), 3)
            kinds = {item.kind for item in findings}
            self.assertIn("http_url", kinds)
            self.assertIn("ws_url", kinds)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_build_test_plan_escalates_low_to_mid_when_network_indicator_exists(self) -> None:
        plan = build_test_plan(["python -m compileall ."], network_indicator_detected=True)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0].risk, "mid")
        self.assertIn("Network indicator detected", plan[0].reason)

    def test_policy_gate_blocks_mid_when_hitl_off(self) -> None:
        plan = build_test_plan(["python -m compileall ."], network_indicator_detected=True)
        state, gated = apply_policy_gate(
            test_plan=plan,
            hitl=False,
            approve_mid_high=False,
            deny_mid_high=False,
            user_constraints=UserConstraints(),
        )
        self.assertEqual(state.status, "blocked")
        self.assertEqual(gated, [])

    def test_run_blocks_when_network_indicator_detected_and_hitl_off(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            tests_dir = repo / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            (tests_dir / "test_network.py").write_text(
                'ENDPOINT = "https://api.example.com/v2/orders"\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "risk scan block",
                    "--verify-cmd",
                    "python -m compileall .",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["policy_gate"]["status"], "blocked")
            self.assertTrue(any(a["type"] == "risk_network_indicator" for a in state.get("alerts", [])))
            report_text = (repo / paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("## Network Indicators Detected", report_text)
            self.assertIn("kind=http_url", report_text)
            trace_text = (repo / paths["TRACE"]).read_text(encoding="utf-8")
            self.assertIn('"event": "risk_scan"', trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_run_hitl_on_without_input_requires_interactive_decision(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            (repo / "settings_test.py").write_text(
                'UPSTREAM = "http://localhost:9000/v1/ping"\n',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "risk scan hitl no approve",
                    "--verify-cmd",
                    "python -m compileall .",
                    "--review-providers",
                    "local",
                    "--hitl",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            state = json.loads((repo / paths["STATE"]).read_text(encoding="utf-8"))
            self.assertIn(state["policy_gate"]["status"], {"blocked", "not_checked"})
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def _make_temp_repo_dir(self) -> Path:
        repo = TMP_ROOT / f"risk_repo_{uuid.uuid4().hex}"
        repo.mkdir(parents=True, exist_ok=False)
        return repo

    def _parse_artifact_paths(self, text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            for key in ["RUN_DIR", "REPORT", "DIFF", "STATE", "TRACE"]:
                prefix = f"{key}:"
                if line.startswith(prefix):
                    out[key] = line[len(prefix) :].strip()
        self.assertEqual(set(out.keys()), {"RUN_DIR", "REPORT", "DIFF", "STATE", "TRACE"})
        return out


if __name__ == "__main__":
    unittest.main()
