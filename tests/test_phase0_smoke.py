import json
import os
import shutil
import subprocess
import sys
import textwrap
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

import my_opt_code_agent.cli as cli_module
from internal.agents.adapter.google_provider import GoogleProviderClient
from internal.schemas.state import (
    AgentState,
    ImprovementProposal,
    ProviderRun,
    ReviewBundleConfig,
    ReviewResult,
    ReviewsState,
    TaskSpec,
    VerificationItem,
    VerificationResult,
)
from internal.tools.artifacts import build_artifact_paths


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tests" / ".tmp"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("OPENAI_API_KEY", "unit-test-key")


class PhaseSmokeTest(unittest.TestCase):
    def _ok_verification(self) -> VerificationResult:
        return VerificationResult(
            executed=[
                VerificationItem(
                    id="verify-1",
                    cmd="python -m compileall .",
                    risk="low",
                    exit_code=0,
                    stdout_tail="ok",
                    stderr_tail="",
                    passed=True,
                )
            ],
            passed=True,
        )

    def test_help_works(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "my_opt_code_agent", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("run", proc.stdout)
        self.assertIn("doctor", proc.stdout)

    def test_run_help_has_review_provider_options(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "my_opt_code_agent", "run", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--review-providers", proc.stdout)
        self.assertIn("--provider-config", proc.stdout)
        self.assertIn("--set-provider", proc.stdout)
        self.assertIn("--hitl", proc.stdout)

    def test_doctor_prints_provider_checks(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "my_opt_code_agent", "doctor"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[Check] codex provider", proc.stdout)
        self.assertIn("[Check] google provider", proc.stdout)

    def test_doctor_reports_fail_when_provider_keys_missing(self) -> None:
        buf = StringIO()
        fake_registry = {
            "codex": {"auth_mode": "api_key", "command": "codex"},
            "google": {"auth_mode": "ai_studio_key", "command": "gemini"},
        }
        with mock.patch("my_opt_code_agent.cli.load_provider_registry", return_value=fake_registry):
            with mock.patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "VIRTUAL_ENV": ""},
                clear=False,
            ):
                with mock.patch("my_opt_code_agent.cli.shutil.which") as which_mock:
                    which_mock.side_effect = lambda cmd: "C:/fake/pip.exe" if cmd == "pip" else None
                    with redirect_stdout(buf):
                        rc = cli_module.run_doctor()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("[FAIL] OPENAI_API_KEY is missing", out)
        self.assertIn("[FAIL] GEMINI_API_KEY/GOOGLE_API_KEY is missing", out)
        self.assertIn("[FAIL] google CLI command not found", out)

    def test_doctor_codex_chatgpt_login_missing_cli_warns_with_guide(self) -> None:
        buf = StringIO()
        fake_registry = {"codex": {"auth_mode": "chatgpt_login", "command": "codex"}}
        with mock.patch("my_opt_code_agent.cli.load_provider_registry", return_value=fake_registry):
            with mock.patch("my_opt_code_agent.cli.shutil.which") as which_mock:
                which_mock.side_effect = lambda cmd: "C:/fake/pip.exe" if cmd == "pip" else None
                with redirect_stdout(buf):
                    rc = cli_module.run_doctor()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("- configured auth_mode: chatgpt_login", out)
        self.assertIn("[FAIL] codex CLI command not found", out)
        self.assertIn("run `codex login`", out)

    def test_doctor_vertex_api_key_mode_checks_required_env(self) -> None:
        buf = StringIO()
        fake_registry = {"google": {"auth_mode": "vertex_api_key", "command": "gemini"}}
        with mock.patch("my_opt_code_agent.cli.load_provider_registry", return_value=fake_registry):
            with mock.patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "unit-test-key",
                    "GOOGLE_API_KEY": "",
                    "GOOGLE_GENAI_USE_VERTEXAI": "",
                    "GOOGLE_CLOUD_PROJECT": "",
                    "GOOGLE_CLOUD_LOCATION": "",
                },
                clear=False,
            ):
                with mock.patch("my_opt_code_agent.cli.shutil.which", return_value="C:/fake/gemini.exe"):
                    with redirect_stdout(buf):
                        rc = cli_module.run_doctor()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("- configured auth_mode: vertex_api_key", out)
        self.assertIn("[FAIL] vertex_api_key env is incomplete", out)

    def test_google_provider_cli_json_parsing(self) -> None:
        verification = self._ok_verification()
        client = GoogleProviderClient()

        help_stdout = "Usage: gemini\n  -p, --prompt\n  --output-format\n  -m, --model\n"
        response_stdout = json.dumps(
            {
                "response": json.dumps(
                    {
                        "verdict": "approve",
                        "issues": [],
                        "rationale": "Looks good.",
                    }
                )
            }
        )

        with mock.patch("internal.agents.adapter.google_provider.shutil.which", return_value="C:/fake/gemini.exe"):
            with mock.patch("internal.agents.adapter.google_provider.subprocess.run") as run_mock:
                run_mock.side_effect = [
                    subprocess.CompletedProcess(["gemini", "--help"], 0, help_stdout, ""),
                    subprocess.CompletedProcess(["gemini", "-p", "x"], 0, response_stdout, ""),
                ]
                result, raw = client.run_review(
                    role="reviewer_a",
                    context={"verification": verification},
                    provider_cfg={
                        "type": "cli",
                        "command": "gemini",
                        "model": "gemini-3.1-pro-preview-customtools",
                        "timeout_sec": 10,
                    },
                )
        self.assertEqual(result.verdict, "approve")
        self.assertEqual(result.rationale, "Looks good.")
        self.assertEqual(raw.get("mode"), "gemini_cli_json")

    def test_alert_rate_limit_from_codex_kept_in_state_and_report(self) -> None:
        class FakeAdapter:
            def run_review(self, provider, role, context, provider_cfg):
                if provider == "codex":
                    return cli_module._build_empty_review(), {
                        "error": "HTTP 429 Too Many Requests",
                        "message": "insufficient_quota",
                    }
                return cli_module._build_empty_review(), {"mode": "inprocess"}

        verification = self._ok_verification()
        bundle = ReviewBundleConfig(providers=["codex", "local"], roles=["reviewer_a", "reviewer_b"])
        provider_messages: list[str] = []
        alerts = []
        provider_runs, final_review, conclusion = cli_module._run_review_bundle(
            adapter=FakeAdapter(),
            providers=bundle.providers,
            roles=bundle.roles,
            review_bundle=bundle,
            provider_registry={"codex": {}, "local": {}},
            verification=verification,
            iter_idx=1,
            strict=False,
            stop_on_alert=False,
            provider_messages=provider_messages,
            alerts=alerts,
            trace=None,
        )
        self.assertTrue(any(a.type in {"rate_limit", "quota"} and a.provider == "codex" for a in alerts))
        self.assertTrue(any("fallback_runtime" in m for m in provider_messages))
        self.assertTrue(all(run.provider != "codex" for run in provider_runs))

        repo = self._make_temp_repo_dir()
        try:
            artifacts = build_artifact_paths(repo, "alert report")
            state = AgentState(
                task=TaskSpec(user_request="alert report"),
                repo_root=str(repo),
                review_bundle=bundle,
                reviews=ReviewsState(provider_runs=provider_runs, aggregation_conclusion=conclusion),
                provider_messages=provider_messages,
                alerts=alerts,
            )
            cli_module._write_run_report(
                path=artifacts.report_path,
                artifacts=artifacts,
                state=state,
                verification=verification,
                review=final_review,
                final_diff_text="",
            )
            report_text = artifacts.report_path.read_text(encoding="utf-8")
            self.assertIn("## Alerts", report_text)
            self.assertIn("provider=codex", report_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_alert_quota_from_google_resource_exhausted(self) -> None:
        class FakeAdapter:
            def run_review(self, provider, role, context, provider_cfg):
                if provider == "google":
                    return cli_module._build_empty_review(), {
                        "mode": "fallback_local_review",
                        "stderr_tail": "RESOURCE_EXHAUSTED: quota exceeded",
                        "note": "google CLI returned non-zero exit code",
                    }
                return cli_module._build_empty_review(), {"mode": "inprocess"}

        verification = self._ok_verification()
        bundle = ReviewBundleConfig(providers=["google", "local"], roles=["reviewer_a", "reviewer_b"])
        provider_messages: list[str] = []
        alerts = []
        provider_runs, _, _ = cli_module._run_review_bundle(
            adapter=FakeAdapter(),
            providers=bundle.providers,
            roles=bundle.roles,
            review_bundle=bundle,
            provider_registry={"google": {}, "local": {}},
            verification=verification,
            iter_idx=1,
            strict=False,
            stop_on_alert=False,
            provider_messages=provider_messages,
            alerts=alerts,
            trace=None,
        )
        self.assertTrue(any(a.type == "quota" and a.provider == "google" for a in alerts))
        self.assertTrue(any("fallback_runtime" in m for m in provider_messages))
        self.assertTrue(all(run.provider == "local" for run in provider_runs))

    def test_alert_non_strict_fallback_preserves_alerts(self) -> None:
        class FakeAdapter:
            def run_review(self, provider, role, context, provider_cfg):
                if provider == "codex":
                    return cli_module._build_empty_review(), {"error": "429 rate limit"}
                return cli_module._build_empty_review(), {"mode": "inprocess"}

        verification = self._ok_verification()
        bundle = ReviewBundleConfig(providers=["codex", "local"], roles=["reviewer_a", "reviewer_b"])
        provider_messages: list[str] = []
        alerts = []
        provider_runs, _, _ = cli_module._run_review_bundle(
            adapter=FakeAdapter(),
            providers=bundle.providers,
            roles=bundle.roles,
            review_bundle=bundle,
            provider_registry={"codex": {}, "local": {}},
            verification=verification,
            iter_idx=1,
            strict=False,
            stop_on_alert=False,
            provider_messages=provider_messages,
            alerts=alerts,
            trace=None,
        )
        self.assertGreaterEqual(len(alerts), 1)
        self.assertTrue(any(a.type == "rate_limit" for a in alerts))
        self.assertTrue(any(run.provider == "local" for run in provider_runs))

    def test_alert_strict_mode_fails_immediately_on_rate_limit(self) -> None:
        class FakeAdapter:
            def run_review(self, provider, role, context, provider_cfg):
                return cli_module._build_empty_review(), {"error": "429 Too Many Requests"}

        verification = self._ok_verification()
        bundle = ReviewBundleConfig(providers=["codex", "local"], roles=["reviewer_a", "reviewer_b"])
        with self.assertRaises(RuntimeError):
            cli_module._run_review_bundle(
                adapter=FakeAdapter(),
                providers=bundle.providers,
                roles=bundle.roles,
                review_bundle=bundle,
                provider_registry={"codex": {}, "local": {}},
                verification=verification,
                iter_idx=1,
                strict=True,
                stop_on_alert=False,
                provider_messages=[],
                alerts=[],
                trace=None,
            )

    def test_stop_on_alert_default_stops_on_provider_unavailable(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "stop on alert setup",
                    "--review-providers",
                    "google,local",
                    "--set-provider",
                    "google.command=__missing_gemini__",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("ALERT: provider_unavailable", proc.stdout + proc.stderr)
            self.assertIn("STOPPED:", proc.stdout + proc.stderr)
            artifact_paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state.get("status"), "stopped")
            self.assertTrue(state.get("stopped_reason"))
            self.assertTrue(any(a.get("type") == "provider_unavailable" for a in state.get("alerts", [])))
            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("Run stopped due to alert", report_text)
            trace_rel = self._parse_trace_path(proc.stdout + proc.stderr)
            self.assertTrue(trace_rel)
            trace_text = (repo / trace_rel).read_text(encoding="utf-8")
            self.assertIn('"event": "stopped"', trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_codex_chatgpt_login_runtime_auth_error_stops_by_default(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "codex auth stop",
                    "--review-providers",
                    "codex,local",
                    "--set-provider",
                    "codex.auth_mode=chatgpt_login",
                    "--set-provider",
                    "codex.command=python",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("ALERT: auth", proc.stdout + proc.stderr)
            self.assertIn("STOPPED:", proc.stdout + proc.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_no_stop_on_alert_keeps_non_strict_fallback(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "no stop fallback",
                    "--review-providers",
                    "codex,local",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "codex.auth_mode=chatgpt_login",
                    "--set-provider",
                    "codex.command=python",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("ALERT: auth", proc.stdout + proc.stderr)
            artifact_paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertNotEqual(state.get("status"), "stopped")
            self.assertIn("fallback_runtime", " ".join(state.get("provider_messages", [])))
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_proposal_strong_triggers_extra_coder_loop(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "proposal loop",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "2",
                ]
            )

            call_count = {"n": 0}

            def fake_run_review_bundle(**kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    proposal = ImprovementProposal(
                        title="Refine verification flow",
                        description="Use clearer checks",
                        motivation="Improve maintainability",
                        suggested_steps=["Adjust check ordering"],
                        affected_files=["my_opt_code_agent/cli.py"],
                        expected_benefit="Cleaner reviews",
                        risk_level="low",
                    )
                    return (
                        [
                            ProviderRun(
                                provider="local",
                                role="reviewer_a",
                                verdict="approve",
                                issues=[],
                                rationale="ok",
                                improvement_proposals=[proposal],
                                proposal_policy_hint="strong",
                                raw={"iter": kwargs.get("iter_idx", 1)},
                            )
                        ],
                        ReviewResult(
                            verdict="approve",
                            issues=[],
                            rationale="ok",
                            improvement_proposals=[proposal],
                            proposal_policy_hint="strong",
                        ),
                        "policy=consensus; decision=approve; reason=all_runs_approve",
                    )
                return (
                    [
                        ProviderRun(
                            provider="local",
                            role="reviewer_a",
                            verdict="approve",
                            issues=[],
                            rationale="ok2",
                            raw={"iter": kwargs.get("iter_idx", 2)},
                        )
                    ],
                    ReviewResult(verdict="approve", issues=[], rationale="ok2"),
                    "policy=consensus; decision=approve; reason=all_runs_approve",
                )

            out = StringIO()
            with mock.patch("my_opt_code_agent.cli._run_review_bundle", side_effect=fake_run_review_bundle):
                with redirect_stdout(out):
                    rc = cli_module.run_phase3(args)
            self.assertEqual(rc, 0)
            self.assertGreaterEqual(call_count["n"], 2)
            artifact_paths = self._parse_artifact_paths(out.getvalue())
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(state.get("coder_inputs", [])), 2)
            self.assertGreaterEqual(
                len(state.get("coder_inputs", [])[1].get("improvement_proposals", [])),
                1,
            )
            trace_rel = self._parse_trace_path(out.getvalue())
            self.assertTrue(trace_rel)
            trace_text = (repo / trace_rel).read_text(encoding="utf-8")
            self.assertIn('"event": "proposal_detected"', trace_text)
            self.assertIn('"event": "proposal_applied"', trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_phase3_policy_gate_blocks_mid_high_without_hitl(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "phase3 gate block",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--review-providers",
                    "codex",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key"}),
            )
            self.assertNotEqual(proc.returncode, 0)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            self._assert_artifact_files(repo, artifact_paths)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["policy_gate"]["status"], "blocked")
            self.assertTrue(state["policy_gate"]["need_human"])
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_phase3_hitl_approval_approve_all_and_approves(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "phase3 gate approve",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--hitl",
                    "--approve-mid-high",
                    "--review-providers",
                    "codex",
                    "--max-iters",
                    "2",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key"}),
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("review_verdict=approve", proc.stdout)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["policy_gate"]["status"], "allowed")
            self.assertGreaterEqual(len(state["verification_history"]), 1)
            cmd = state["verification_history"][0]["executed"][0]["cmd"]
            self.assertEqual(cmd, "echo withdraw now")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_phase3_reject_then_rework_loop_stores_issues_json(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "phase3 reject loop",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--hitl",
                    "--approve-mid-high",
                    "--max-iters",
                    "3",
                    "--review-providers",
                    "codex",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key"}),
            )
            self.assertEqual(proc.returncode, 0)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            self._assert_artifact_files(repo, artifact_paths)

            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["review_bundle"]["providers"], ["codex"])
            self.assertEqual(state["review_bundle"]["roles"], ["reviewer_a", "reviewer_b"])
            self.assertIn("policy=consensus", state["reviews"]["aggregation_conclusion"])
            provider_runs = state["reviews"]["provider_runs"]
            self.assertTrue(any(r["provider"] == "codex" and r["role"] == "reviewer_a" for r in provider_runs))
            self.assertTrue(any(r["provider"] == "codex" and r["role"] == "reviewer_b" for r in provider_runs))

            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("## Artifacts", report_text)
            self.assertIn("## TestPlan", report_text)
            self.assertIn("## PolicyGate", report_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_google_provider_non_strict_codex_fallback_when_google_unavailable(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "provider fallback",
                    "--review-providers",
                    "codex,google",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                    "--set-provider",
                    "google.command=__missing_gemini__",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key", "GEMINI_API_KEY": None}),
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("non-strict provider fallback", proc.stdout)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["review_bundle"]["providers"], ["codex"])
            self.assertIn("fallback_applied", " ".join(state.get("provider_messages", [])))
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_google_provider_strict_mode_fails_when_unavailable(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "provider strict",
                    "--review-providers",
                    "google",
                    "--strict-review-providers",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "google.command=__missing_gemini__",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"GEMINI_API_KEY": None}),
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("strict review provider mode enabled -> aborting", proc.stdout + proc.stderr)
            artifact_paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            self._assert_artifact_files(repo, artifact_paths)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_google_provider_strict_mode_fails_on_runtime_login_path(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "provider strict runtime login",
                    "--review-providers",
                    "google",
                    "--strict-review-providers",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "google.auth_mode=google_login",
                    "--set-provider",
                    "google.command=python",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("provider runtime alert in strict mode", proc.stdout + proc.stderr)
            artifact_paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            self._assert_artifact_files(repo, artifact_paths)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_google_only_non_strict_still_fails_when_unavailable(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "google only non-strict",
                    "--review-providers",
                    "google",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "google.command=__missing_gemini__",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"GEMINI_API_KEY": None}),
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("google-only request cannot fallback", proc.stdout + proc.stderr)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_phase4_multi_provider_bundle_and_trace_artifact(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "phase4 providers+trace",
                    "--review-providers",
                    "codex,google,local",
                    "--no-stop-on-alert",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                    "--set-provider",
                    "google.command=python",
                    "--max-iters",
                    "1",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key", "GEMINI_API_KEY": "fake-key"}),
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("TRACE:", proc.stdout)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            self._assert_artifact_files(repo, artifact_paths)

            trace_rel = self._parse_trace_path(proc.stdout)
            self.assertTrue(trace_rel)
            trace_path = repo / trace_rel
            self.assertTrue(trace_path.exists())
            trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(trace_lines), 3)
            self.assertTrue(any('"event": "run_started"' in line for line in trace_lines))
            self.assertTrue(any('"event": "review_bundle_finished"' in line for line in trace_lines))

            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            provider_runs = state["reviews"]["provider_runs"]
            self.assertEqual(len(provider_runs), 4)
            providers = {r["provider"] for r in provider_runs}
            self.assertEqual(providers, {"codex", "local"})
            self.assertIn("fallback_runtime", " ".join(state.get("provider_messages", [])))
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_critical_diff_blocked_without_allow_still_creates_artifacts(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            self._seed_repo(repo)
            diff_file = self._write_critical_diff(repo)

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "critical block",
                    "--diff-file",
                    str(diff_file),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key"}),
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("CRITICAL CHANGE APPROVAL REQUIRED", proc.stdout)
            self.assertIn("requirements.txt", proc.stdout)

            artifact_paths = self._parse_artifact_paths(proc.stdout)
            self._assert_artifact_files(repo, artifact_paths)
            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("Critical Changes (Approval Required)", report_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_critical_diff_allowed_with_flag(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            self._seed_repo(repo)
            diff_file = self._write_critical_diff(repo)

            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "my_opt_code_agent",
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "critical allow",
                    "--diff-file",
                    str(diff_file),
                    "--allow-critical",
                    "--set-provider",
                    "codex.auth_mode=api_key",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=self._env({"OPENAI_API_KEY": "unit-test-key"}),
            )
            self.assertEqual(proc.returncode, 0)
            artifact_paths = self._parse_artifact_paths(proc.stdout)
            self._assert_artifact_files(repo, artifact_paths)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def _parse_artifact_paths(self, text: str) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            for key in ["RUN_DIR", "REPORT", "DIFF", "STATE"]:
                prefix = f"{key}:"
                if line.startswith(prefix):
                    out[key] = line[len(prefix) :].strip()
        self.assertEqual(set(out.keys()), {"RUN_DIR", "REPORT", "DIFF", "STATE"})
        return out

    def _assert_artifact_files(self, repo: Path, artifact_paths: dict[str, str]) -> None:
        run_dir_rel = artifact_paths["RUN_DIR"]
        self.assertTrue(run_dir_rel.startswith("reports/"))
        self.assertTrue(run_dir_rel.endswith("/"))

        run_dir = repo / run_dir_rel.rstrip("/")
        report_path = repo / artifact_paths["REPORT"]
        diff_path = repo / artifact_paths["DIFF"]
        state_path = repo / artifact_paths["STATE"]

        self.assertTrue(run_dir.exists())
        self.assertTrue(report_path.exists())
        self.assertTrue(diff_path.exists())
        self.assertTrue(state_path.exists())

        report_text = report_path.read_text(encoding="utf-8")
        self.assertIn("## Artifacts", report_text)
        self.assertIn(f"- Run folder: {artifact_paths['RUN_DIR']}", report_text)
        self.assertIn(f"- report.md: {artifact_paths['REPORT']}", report_text)
        self.assertIn(f"- final.diff: {artifact_paths['DIFF']}", report_text)
        self.assertIn(f"- state.json: {artifact_paths['STATE']}", report_text)
        self.assertIn("## Changes (File-by-file)", report_text)
        self.assertIn("## Alerts", report_text)
        self.assertIn("## Requirement Trace", report_text)
        self.assertIn("## PR-ready", report_text)

    def _parse_trace_path(self, text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("TRACE:"):
                return line[len("TRACE:") :].strip()
        return ""

    def _make_temp_repo_dir(self) -> Path:
        repo = TMP_ROOT / f"repo_{uuid.uuid4().hex}"
        repo.mkdir(parents=True, exist_ok=False)
        return repo

    def _seed_repo(self, repo: Path) -> None:
        (repo / "requirements.txt").write_text("flask==1.0.0\n", encoding="utf-8")
        self._git(["init"], repo)
        self._git(["config", "user.email", "dev@example.com"], repo)
        self._git(["config", "user.name", "Dev"], repo)
        self._git(["add", "requirements.txt"], repo)
        self._git(["commit", "-m", "init"], repo)

    def _write_critical_diff(self, repo: Path) -> Path:
        diff_text = textwrap.dedent(
            """
            diff --git a/requirements.txt b/requirements.txt
            index 8f4519e..405bd20 100644
            --- a/requirements.txt
            +++ b/requirements.txt
            @@ -1 +1,2 @@
             flask==1.0.0
            +requests==2.31.0
            """
        ).lstrip()
        diff_file = repo / "critical.diff"
        diff_file.write_text(diff_text, encoding="utf-8")
        return diff_file

    def _git(self, args: list[str], cwd: Path) -> None:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
        if proc.returncode != 0:
            self.fail(f"git command failed: {' '.join(args)}\n{proc.stderr}\n{proc.stdout}")

    def _env(self, overrides: dict[str, str | None]) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("OPENAI_API_KEY", "unit-test-key")
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env


if __name__ == "__main__":
    unittest.main()
