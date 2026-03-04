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
from internal.agents.adapter.codex_provider import CodexProviderClient
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
os.environ["MYOPT_ENABLE_REAL_PROVIDERS"] = "0"
os.environ.setdefault("MYOPT_PRINT_ALERTS", "0")


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
        buf = StringIO()
        fake_registry = {
            "codex": {"auth_mode": "chatgpt_login", "command": "codex"},
            "google": {"auth_mode": "ai_studio_key", "command": "gemini"},
        }
        with mock.patch("my_opt_code_agent.cli.load_provider_registry", return_value=fake_registry):
            with mock.patch("my_opt_code_agent.cli.shutil.which") as which_mock:
                which_mock.side_effect = (
                    lambda cmd: "C:/fake/pip.exe"
                    if cmd == "pip"
                    else ("C:/fake/cli.exe" if cmd in {"codex", "gemini"} else None)
                )
                with mock.patch("my_opt_code_agent.cli.run_cli", return_value=(0, "ok", "")):
                    with redirect_stdout(buf):
                        rc = cli_module.run_doctor()
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("[Check] codex provider", out)
        self.assertIn("[Check] google provider", out)

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
                    "MYOPT_ENABLE_REAL_PROVIDERS": "0",
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
            with mock.patch("internal.agents.adapter.google_provider.run_cli") as run_cli_mock:
                run_cli_mock.side_effect = [
                    (0, help_stdout, ""),
                    (0, response_stdout, ""),
                ]
                with mock.patch.dict(os.environ, {"MYOPT_ENABLE_REAL_PROVIDERS": "1"}, clear=False):
                    result, raw = client.run_review(
                        role="reviewer_a",
                        context={"verification": verification},
                        provider_cfg={
                            "type": "cli",
                            "command": "gemini",
                            "model": "gemini-3.1-pro-preview",
                            "timeout_sec": 10,
                        },
                    )
        self.assertEqual(result.verdict, "approve")
        self.assertEqual(result.rationale, "Looks good.")
        self.assertEqual(raw.get("mode"), "gemini_cli_json")
        self.assertTrue(raw.get("model_flag_applied"))
        self.assertFalse(raw.get("warning"))

    def test_google_provider_warns_when_model_flag_not_supported(self) -> None:
        verification = self._ok_verification()
        client = GoogleProviderClient()

        help_stdout = "Usage: gemini\n  -p, --prompt\n  --output-format\n"
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
            with mock.patch("internal.agents.adapter.google_provider.run_cli") as run_cli_mock:
                run_cli_mock.side_effect = [
                    (0, help_stdout, ""),
                    (0, response_stdout, ""),
                ]
                with mock.patch.dict(os.environ, {"MYOPT_ENABLE_REAL_PROVIDERS": "1"}, clear=False):
                    _, raw = client.run_review(
                        role="reviewer_a",
                        context={"verification": verification},
                        provider_cfg={
                            "type": "cli",
                            "command": "gemini",
                            "model": "gemini-3.1-pro-preview",
                            "timeout_sec": 10,
                        },
                    )
        self.assertFalse(raw.get("model_flag_applied"))
        self.assertIn("Configured google.model", str(raw.get("warning", "")))

    def test_codex_provider_chatgpt_login_preflight_ok_when_exec_help_succeeds(self) -> None:
        verification = self._ok_verification()
        client = CodexProviderClient()
        with mock.patch("internal.agents.adapter.codex_provider.shutil.which", return_value="C:/fake/codex.exe"):
            with mock.patch("internal.agents.adapter.codex_provider.run_cli", return_value=(0, "ok", "")):
                with mock.patch.dict(os.environ, {"MYOPT_ENABLE_REAL_PROVIDERS": "1"}, clear=False):
                    _, raw = client.run_review(
                        role="reviewer_a",
                        context={"verification": verification},
                        provider_cfg={"auth_mode": "chatgpt_login", "command": "codex", "timeout_sec": 10},
                    )
        self.assertEqual(raw.get("mode"), "chatgpt_login_session")

    def test_codex_provider_chatgpt_login_detects_auth_from_stderr(self) -> None:
        verification = self._ok_verification()
        client = CodexProviderClient()
        stderr_text = "Login required: unauthorized"
        with mock.patch("internal.agents.adapter.codex_provider.shutil.which", return_value="C:/fake/codex.exe"):
            with mock.patch("internal.agents.adapter.codex_provider.run_cli", return_value=(1, "", stderr_text)):
                with mock.patch.dict(os.environ, {"MYOPT_ENABLE_REAL_PROVIDERS": "1"}, clear=False):
                    _, raw = client.run_review(
                        role="reviewer_a",
                        context={"verification": verification},
                        provider_cfg={"auth_mode": "chatgpt_login", "command": "codex", "timeout_sec": 10},
                    )
        self.assertEqual(raw.get("mode"), "auth_required")
        self.assertIn("login", str(raw.get("error", "")).lower())
        self.assertIn("unauthorized", str(raw.get("stderr_tail", "")).lower())

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

    def test_google_model_warning_is_forwarded_to_provider_messages(self) -> None:
        class FakeAdapter:
            def run_review(self, provider, role, context, provider_cfg):
                return cli_module._build_empty_review(), {
                    "mode": "gemini_cli_json",
                    "warning": "Configured google.model was not applied",
                }

        verification = self._ok_verification()
        bundle = ReviewBundleConfig(providers=["google"], roles=["reviewer_a"])
        provider_messages: list[str] = []
        provider_runs, _, _ = cli_module._run_review_bundle(
            adapter=FakeAdapter(),
            providers=bundle.providers,
            roles=bundle.roles,
            review_bundle=bundle,
            provider_registry={"google": {}},
            verification=verification,
            iter_idx=1,
            strict=False,
            stop_on_alert=False,
            provider_messages=provider_messages,
            alerts=[],
            trace=None,
        )
        self.assertEqual(len(provider_runs), 1)
        self.assertTrue(any(msg.startswith("warning: google/reviewer_a") for msg in provider_messages))

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
                env=self._env({"MYOPT_MOCK_CODEX_LOGIN_REQUIRED": "1", "MYOPT_ENABLE_REAL_PROVIDERS": "1"}),
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("STOPPED:", proc.stdout + proc.stderr)
            artifact_paths = self._parse_artifact_paths(proc.stdout + proc.stderr)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertTrue(any(a.get("type") == "auth" for a in state.get("alerts", [])))
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_no_stop_on_alert_keeps_non_strict_fallback(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            rc, _, artifact_paths = self._run_phase3_direct(
                repo,
                [
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
                env_overrides={"MYOPT_MOCK_CODEX_LOGIN_REQUIRED": "1", "MYOPT_ENABLE_REAL_PROVIDERS": "1"},
            )
            self.assertNotEqual(rc, 0)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state.get("status"), "failed")
            self.assertTrue(any(item["type"] == "auth" and item.get("role") == "coder" for item in state.get("alerts", [])))
            self.assertTrue(any("coder_failure" in m for m in state.get("provider_messages", [])))
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
            rc, _, artifact_paths = self._run_phase3_direct(
                repo,
                [
                    "--task",
                    "phase3 gate block",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--review-providers",
                    "local",
                ],
            )
            self.assertNotEqual(rc, 0)
            self._assert_artifact_files(repo, artifact_paths)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["policy_gate"]["status"], "blocked")
            self.assertTrue(state["policy_gate"]["need_human"])
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_phase3_hitl_approval_approve_all_and_approves(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            rc, _, artifact_paths = self._run_phase3_direct(
                repo,
                [
                    "--task",
                    "phase3 gate approve",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--hitl",
                    "--approve-mid-high",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "2",
                ],
            )
            self.assertEqual(rc, 0)
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
            rc, _, artifact_paths = self._run_phase3_direct(
                repo,
                [
                    "--task",
                    "phase3 reject loop",
                    "--verify-cmd",
                    "echo withdraw now",
                    "--hitl",
                    "--approve-mid-high",
                    "--max-iters",
                    "3",
                    "--review-providers",
                    "local",
                ],
            )
            self.assertEqual(rc, 0)
            self._assert_artifact_files(repo, artifact_paths)

            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["review_bundle"]["providers"], ["local"])
            self.assertEqual(state["review_bundle"]["roles"], ["reviewer_a", "reviewer_b"])
            self.assertIn("policy=consensus", state["reviews"]["aggregation_conclusion"])
            provider_runs = state["reviews"]["provider_runs"]
            self.assertTrue(any(r["provider"] == "local" and r["role"] == "reviewer_a" for r in provider_runs))
            self.assertTrue(any(r["provider"] == "local" and r["role"] == "reviewer_b" for r in provider_runs))

            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("## Artifacts", report_text)
            self.assertIn("## TestPlan", report_text)
            self.assertIn("## PolicyGate", report_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_google_provider_non_strict_codex_fallback_when_google_unavailable(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            def fake_provider_check(provider, provider_cfg, adapter):
                if provider == "google":
                    return False, ["google unavailable in unit test"]
                return True, [f"{provider}: ready"]

            with mock.patch("my_opt_code_agent.cli._provider_setup_checks", side_effect=fake_provider_check):
                rc, _, artifact_paths = self._run_phase3_direct(
                    repo,
                    [
                        "--task",
                        "provider fallback",
                        "--review-providers",
                        "codex,google",
                        "--no-stop-on-alert",
                        "--set-provider",
                        "codex.auth_mode=api_key",
                    ],
                )
            self.assertEqual(rc, 0)
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
            with mock.patch(
                "my_opt_code_agent.cli._run_review_bundle",
                side_effect=RuntimeError("provider runtime alert in strict mode: google/reviewer_a auth - login required"),
            ):
                rc, _, artifact_paths = self._run_phase3_direct(
                    repo,
                    [
                        "--task",
                        "provider strict runtime login",
                        "--review-providers",
                        "google",
                        "--strict-review-providers",
                        "--no-stop-on-alert",
                    ],
                )
            self.assertNotEqual(rc, 0)
            self._assert_artifact_files(repo, artifact_paths)
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "failed")
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
            rc, out, artifact_paths = self._run_phase3_direct(
                repo,
                [
                    "--task",
                    "phase4 providers+trace",
                    "--review-providers",
                    "codex,google,local",
                    "--no-stop-on-alert",
                    "--max-iters",
                    "1",
                ],
            )
            self.assertEqual(rc, 0)
            self._assert_artifact_files(repo, artifact_paths)

            trace_rel = self._parse_trace_path(out)
            self.assertTrue(trace_rel)
            trace_path = repo / trace_rel
            self.assertTrue(trace_path.exists())
            trace_lines = trace_path.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(trace_lines), 3)
            self.assertTrue(any('"event": "run_started"' in line for line in trace_lines))
            self.assertTrue(any('"event": "review_bundle_finished"' in line for line in trace_lines))

            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            provider_runs = state["reviews"]["provider_runs"]
            self.assertEqual(len(provider_runs), 6)
            providers = {r["provider"] for r in provider_runs}
            self.assertEqual(providers, {"codex", "google", "local"})
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_critical_diff_blocked_without_allow_still_creates_artifacts(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            self._seed_repo(repo)
            critical_diff = self._write_critical_diff(repo).read_text(encoding="utf-8")

            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={
                    "diff": critical_diff,
                    "touched_files": ["requirements.txt"],
                    "rationale_by_file": {"requirements.txt": "critical test"},
                },
            ):
                rc, out, artifact_paths = self._run_phase3_direct(
                    repo,
                    ["--task", "critical block", "--review-providers", "local", "--max-iters", "1"],
                )
            self.assertNotEqual(rc, 0)
            self.assertIn("CRITICAL CHANGE APPROVAL REQUIRED", out)
            self.assertIn("requirements.txt", out)
            self._assert_artifact_files(repo, artifact_paths)
            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("Critical Changes (Approval Required)", report_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_critical_diff_allowed_with_flag(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            self._seed_repo(repo)
            critical_diff = self._write_critical_diff(repo).read_text(encoding="utf-8")
            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={
                    "diff": critical_diff,
                    "touched_files": ["requirements.txt"],
                    "rationale_by_file": {"requirements.txt": "critical test"},
                },
            ):
                rc, _, artifact_paths = self._run_phase3_direct(
                    repo,
                    [
                        "--task",
                        "critical allow",
                        "--allow-critical",
                        "--review-providers",
                        "local",
                        "--max-iters",
                        "1",
                    ],
                )
            self.assertEqual(rc, 0)
            self._assert_artifact_files(repo, artifact_paths)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_run_readme_update_produces_non_empty_final_diff(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "README ?낅뜲?댄듃",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ]
            )
            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={
                    "diff": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n+++ b/README.md\n"
                        "@@ -1 +1,6 @@\n"
                        "-# Temp Repo\n"
                        "+# Temp Repo\n"
                        "+\n"
                        "+## Overview\n"
                        "+- cleaned duplicates\n"
                        "+\n"
                        "+## Usage\n"
                    ),
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "restructure readme"},
                    "final_file_contents": {"README.md": "# Temp Repo\n\n## Overview\n- cleaned duplicates\n\n## Usage\n"},
                },
            ):
                out = StringIO()
                with redirect_stdout(out):
                    rc = cli_module.run_phase3(args)
            self.assertEqual(rc, 0)
            artifact_paths = self._parse_artifact_paths(out.getvalue())
            diff_text = (repo / artifact_paths["DIFF"]).read_text(encoding="utf-8")
            self.assertTrue(diff_text.strip())
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertTrue(state.get("patch_applied"))
            trace_rel = self._parse_trace_path(out.getvalue())
            self.assertTrue(trace_rel)
            trace_text = (repo / trace_rel).read_text(encoding="utf-8")
            self.assertIn('"event": "coder_started"', trace_text)
            self.assertIn('"event": "coder_finished"', trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_regression_apply_must_not_run_before_coder(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "README ?낅뜲?댄듃",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ]
            )
            flow = {"coder_called": False, "applied": False}

            def fake_generate_coder_output(repo, coder_input, iter_idx):
                flow["coder_called"] = True
                return {
                    "diff": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n+++ b/README.md\n@@ -1 +1,4 @@\n"
                        "-# Temp Repo\n"
                        "+# Temp Repo\n"
                        "+\n"
                        "+## Notes\n"
                        "+updated\n"
                    ),
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "update"},
                    "final_file_contents": {"README.md": "# Temp Repo\n\n## Notes\nupdated\n"},
                }

            def fake_apply_unified_diff(repo, diff_text):
                if not flow["coder_called"]:
                    return False, "apply invoked before coder"
                flow["applied"] = True
                return True, "ok"

            def fake_get_git_diff(_repo):
                return (
                    "diff --git a/README.md b/README.md\n"
                    "--- a/README.md\n+++ b/README.md\n@@ -1 +1,2 @@\n # Temp Repo\n+updated\n"
                    if flow["applied"]
                    else ""
                )

            with mock.patch("my_opt_code_agent.cli.generate_coder_output", side_effect=fake_generate_coder_output):
                with mock.patch("my_opt_code_agent.cli.apply_unified_diff", side_effect=fake_apply_unified_diff):
                    with mock.patch("my_opt_code_agent.cli.get_git_diff", side_effect=fake_get_git_diff):
                        with mock.patch("my_opt_code_agent.cli.get_git_status", return_value=" M README.md"):
                            out = StringIO()
                            with redirect_stdout(out):
                                rc = cli_module.run_phase3(args)

            self.assertEqual(rc, 0)
            self.assertTrue(flow["coder_called"])
            self.assertTrue(flow["applied"])
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_run_rejects_when_coder_returns_empty_diff(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "README ?낅뜲?댄듃",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ]
            )
            out = StringIO()
            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={"diff": "", "touched_files": [], "rationale_by_file": {}},
            ):
                with redirect_stdout(out):
                    rc = cli_module.run_phase3(args)
            self.assertNotEqual(rc, 0)
            artifact_paths = self._parse_artifact_paths(out.getvalue())
            report_text = (repo / artifact_paths["REPORT"]).read_text(encoding="utf-8")
            self.assertIn("No changes produced", report_text)
            self.assertIn("review_verdict=reject", out.getvalue())
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_real_coder_cli_invocation_is_traced_and_saved(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            trace_path = repo / "trace.jsonl"
            trace = cli_module.TraceWriter(trace_path)
            cli_json = json.dumps(
                {
                    "diff": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n+++ b/README.md\n"
                        "@@ -1 +1,2 @@\n"
                        "-# Temp Repo\n"
                        "+# Temp Repo\n"
                        "+\n"
                    ),
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "rewrite"},
                    "final_file_contents": {"README.md": "# Temp Repo\n\n"},
                }
            ).encode("utf-8")
            proc_ok = subprocess.CompletedProcess(
                args=["cmd.exe", "/c", "codex", "exec", "-"],
                returncode=0,
                stdout=cli_json,
                stderr=b"",
            )
            with mock.patch("my_opt_code_agent.cli.platform.system", return_value="Windows"):
                with mock.patch("my_opt_code_agent.cli.subprocess.run", return_value=proc_ok):
                    payload, raw = cli_module._run_coder_via_codex_cli(
                        repo=repo,
                        coder_input={
                            "task": "README structure cleanup",
                            "issues": [],
                            "improvement_proposals": [],
                            "readme_current": "# Temp Repo\n",
                        },
                        iter_idx=1,
                        provider="codex",
                        auth_mode="chatgpt_login",
                        command="codex",
                        timeout_sec=60,
                        trace=trace,
                    )
            trace.event("coder_provider_selected", provider="codex", auth_mode="chatgpt_login", command="codex")
            self.assertIsNotNone(payload)
            self.assertEqual(raw.get("invoked"), True)
            self.assertEqual(raw.get("cmdline_sanitized"), "codex exec -")
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertIn('"event": "coder_provider_selected"', trace_text)
            self.assertIn('"event": "coder_cli_invoked"', trace_text)
            self.assertIn('"event": "coder_cli_result"', trace_text)
            self.assertIn('"stdin_used": true', trace_text.lower())
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_real_coder_cli_auth_failure_is_rejected_and_exposed(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            trace_path = repo / "trace.jsonl"
            trace = cli_module.TraceWriter(trace_path)
            proc_fail = subprocess.CompletedProcess(
                args=["cmd.exe", "/c", "codex", "exec", "-"],
                returncode=1,
                stdout=b"",
                stderr=b"unauthorized: login required",
            )
            with mock.patch("my_opt_code_agent.cli.platform.system", return_value="Windows"):
                with mock.patch("my_opt_code_agent.cli.subprocess.run", return_value=proc_fail):
                    payload, raw = cli_module._run_coder_via_codex_cli(
                        repo=repo,
                        coder_input={
                            "task": "README section cleanup",
                            "issues": [],
                            "improvement_proposals": [],
                            "readme_current": "# Temp Repo\n",
                        },
                        iter_idx=1,
                        provider="codex",
                        auth_mode="chatgpt_login",
                        command="codex",
                        timeout_sec=60,
                        trace=trace,
                    )
            self.assertIsNone(payload)
            self.assertEqual(raw.get("failure_type"), "auth")
            self.assertIn("unauthorized", raw.get("stderr_tail", "").lower())
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_coder_uses_stdin_prompt_not_cmdline_for_long_prompt(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            trace_path = repo / "trace.jsonl"
            trace = cli_module.TraceWriter(trace_path)
            huge_text = "A" * 20000
            coder_input = {
                "task": "README ?뺣━",
                "issues": [],
                "improvement_proposals": [],
                "readme_current": huge_text,
            }
            returned = json.dumps(
                {
                    "diff": (
                        "diff --git a/README.md b/README.md\n"
                        "--- a/README.md\n+++ b/README.md\n"
                        "@@ -1 +1,2 @@\n-# a\n+# b\n+line\n"
                    ),
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "ok"},
                    "final_file_contents": {"README.md": "# b\nline\n"},
                }
            ).encode("utf-8")
            proc_ok = subprocess.CompletedProcess(
                args=["cmd.exe", "/c", "codex", "exec", "-"],
                returncode=0,
                stdout=returned,
                stderr=b"",
            )
            with mock.patch("my_opt_code_agent.cli.platform.system", return_value="Windows"):
                with mock.patch("my_opt_code_agent.cli.subprocess.run", return_value=proc_ok) as run_mock:
                    payload, raw = cli_module._run_coder_via_codex_cli(
                        repo=repo,
                        coder_input=coder_input,
                        iter_idx=1,
                        provider="codex",
                        auth_mode="chatgpt_login",
                        command="codex",
                        timeout_sec=60,
                        trace=trace,
                    )
            self.assertIsNotNone(payload)
            self.assertEqual(raw.get("invoked"), True)
            self.assertEqual(raw.get("cmdline_sanitized"), "codex exec -")
            kwargs = run_mock.call_args.kwargs
            called_cmd = run_mock.call_args.args[0]
            self.assertEqual(called_cmd, ["cmd.exe", "/c", "codex", "exec", "-"])
            self.assertGreaterEqual(len(kwargs.get("input", b"")), 20000)
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertIn('"event": "coder_cli_invoked"', trace_text)
            self.assertIn('"stdin_used": true', trace_text.lower())
            self.assertIn('"prompt_source": "stdin"', trace_text)
            self.assertNotIn(huge_text[:200], trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_safe_decode_handles_cp949_like_bytes_without_exception(self) -> None:
        raw = b"\xbe\xc8\xb3\xe7 world"
        text, meta = cli_module._safe_decode_bytes(raw, stage="unit_decode")
        self.assertIn("world", text)
        self.assertTrue(meta.get("decode_used"))

    def test_trace_and_state_write_are_utf8_safe(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            trace_path = repo / "trace.jsonl"
            trace = cli_module.TraceWriter(trace_path)
            trace.event("unicode_event", text="한글 🚀 surrogate-\udcff")
            data = trace_path.read_text(encoding="utf-8")
            self.assertIn("unicode_event", data)

            state = AgentState(task=TaskSpec(user_request="한글 🚀"), repo_root=str(repo))
            state.provider_messages.append("msg: 🚀 \udcff")
            state_path = repo / "state.json"
            cli_module._write_state_json(state_path, state)
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["task"]["user_request"], "한글 🚀")
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_coder_subprocess_unicode_error_classified_as_encoding_error(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            trace_path = repo / "trace.jsonl"
            trace = cli_module.TraceWriter(trace_path)
            with mock.patch("my_opt_code_agent.cli.platform.system", return_value="Windows"):
                with mock.patch(
                    "my_opt_code_agent.cli.subprocess.run",
                    side_effect=UnicodeEncodeError("cp949", "🚀", 0, 1, "illegal multibyte sequence"),
                ):
                    payload, raw = cli_module._run_coder_via_codex_cli(
                        repo=repo,
                        coder_input={"task": "README", "issues": [], "improvement_proposals": []},
                        iter_idx=1,
                        provider="codex",
                        auth_mode="chatgpt_login",
                        command="codex",
                        timeout_sec=60,
                        trace=trace,
                    )
            self.assertIsNone(payload)
            self.assertEqual(raw.get("failure_type"), "encoding_error")
            self.assertEqual(raw.get("error_class"), "UnicodeEncodeError")
            self.assertEqual(raw.get("decode_stage"), "subprocess_invoke")
            self.assertTrue(raw.get("stack_location", "") is not None)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_readme_agent_updates_tiny_change_is_rejected(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "README ?뺣━",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ]
            )
            tiny_diff = (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n+++ b/README.md\n"
                "@@ -2,0 +3,1 @@\n"
                "+- iter 1: README ?뺣━\n"
            )
            out = StringIO()
            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={
                    "diff": tiny_diff,
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "small update"},
                },
            ):
                with mock.patch.dict(os.environ, {"MYOPT_ENABLE_REAL_PROVIDERS": "0"}, clear=False):
                    with redirect_stdout(out):
                        rc = cli_module.run_phase3(args)
            self.assertNotEqual(rc, 0)
            trace_rel = self._parse_trace_path(out.getvalue())
            self.assertTrue(trace_rel)
            trace_text = (repo / trace_rel).read_text(encoding="utf-8")
            self.assertIn('"event": "coder_output_invalid"', trace_text)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_readme_crlf_patch_fail_falls_back_to_full_rewrite(self) -> None:
        repo = self._make_temp_repo_dir()
        try:
            (repo / "README.md").write_bytes(b"# Temp Repo\r\n\r\nLine A\r\n")
            parser = cli_module.build_parser()
            args = parser.parse_args(
                [
                    "run",
                    "--repo",
                    str(repo),
                    "--task",
                    "README ?낅뜲?댄듃",
                    "--review-providers",
                    "local",
                    "--max-iters",
                    "1",
                ]
            )
            bad_diff = (
                "--- a/README.md\n+++ b/README.md\n@@ -999,1 +999,1 @@\n-Line Z\n+Line ZZ\n"
            )
            rewrite_text = "# Temp Repo\n\nLine A\nLine B (rewrite)\n"
            with mock.patch(
                "my_opt_code_agent.cli.generate_coder_output",
                return_value={
                    "diff": bad_diff,
                    "touched_files": ["README.md"],
                    "rationale_by_file": {"README.md": "rewrite fallback"},
                    "final_file_contents": {"README.md": rewrite_text},
                },
            ):
                with mock.patch(
                    "my_opt_code_agent.cli.apply_unified_diff",
                    return_value=(False, "README.md:273 patch does not apply", [{"cmd": "git apply"}]),
                ):
                    out = StringIO()
                    with redirect_stdout(out):
                        rc = cli_module.run_phase3(args)
            self.assertEqual(rc, 0)
            artifact_paths = self._parse_artifact_paths(out.getvalue())
            state = json.loads((repo / artifact_paths["STATE"]).read_text(encoding="utf-8"))
            self.assertTrue(state.get("patch_applied"))
            diff_text = (repo / artifact_paths["DIFF"]).read_text(encoding="utf-8")
            self.assertTrue(diff_text.strip())
            trace_rel = self._parse_trace_path(out.getvalue())
            self.assertTrue(trace_rel)
            trace_text = (repo / trace_rel).read_text(encoding="utf-8")
            self.assertIn('"event": "patch_fallback_rewrite"', trace_text)
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

    def _run_phase3_direct(
        self,
        repo: Path,
        argv: list[str],
        env_overrides: dict[str, str | None] | None = None,
        input_fn=None,
    ) -> tuple[int, str, dict[str, str]]:
        parser = cli_module.build_parser()
        args = parser.parse_args(["run", "--repo", str(repo), *argv])
        out = StringIO()
        env = self._env(env_overrides or {})
        run_input = input_fn if input_fn is not None else input
        with mock.patch.dict(os.environ, env, clear=False):
            with redirect_stdout(out):
                rc = cli_module.run_phase3(args, input_fn=run_input)
        text = out.getvalue()
        paths = self._parse_artifact_paths(text)
        return rc, text, paths

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
        (repo / "README.md").write_text("# Temp Repo\n", encoding="utf-8")
        self._git(["init"], repo)
        self._git(["config", "user.email", "dev@example.com"], repo)
        self._git(["config", "user.name", "Dev"], repo)
        self._git(["add", "README.md"], repo)
        self._git(["commit", "-m", "init"], repo)
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
        env["MYOPT_ENABLE_REAL_PROVIDERS"] = "0"
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env


if __name__ == "__main__":
    unittest.main()

