# ssalmuk-agent

> [!IMPORTANT]
> This project strongly requires using an isolated `.venv` (virtual environment).
> Do not install into system Python. Most setup/run errors come from skipping `.venv`.

Language:
- English: [README.md](README.md)
- Korean: [README_ko.md](README_ko.md)

`ssalmuk-agent` is a phase-based Python CLI that runs patch -> verify -> review -> report in one auditable flow.
It uses provider bundles (`codex`, `google`, `local`), consensus review, run-folder artifacts, alert policies, and tracing.
Each run writes outputs to `reports/<repo_slug>/<timestamp>__<task_slug>/`.
For this repository (`--repo .`), that becomes `reports/ssalmuk-agent/<timestamp>__<task_slug>/`.

## Python and Packaging Policy

- Required Python: **3.10+** (`pyproject.toml` `requires-python = ">=3.10"`)
- Official install path: **pyproject editable install only** (`pip install -e .`)
- `requirements.txt`: **intentionally not used** in this repo

Why no `requirements.txt`?
- This project is packaged with `pyproject.toml` and maintained as an installable package.
- Keeping one official install path (`pip install -e .`) avoids duplicated dependency definitions and user confusion.

## Quickstart (5-minute copy/paste)

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
python -m my_opt_code_agent doctor
python -m my_opt_code_agent run --repo . --task "quickstart smoke" --review-providers codex,local --max-iters 1 --no-stop-on-alert
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m my_opt_code_agent doctor
python -m my_opt_code_agent run --repo . --task "quickstart smoke" --review-providers codex,local --max-iters 1 --no-stop-on-alert
```

If you installed incorrectly (system Python):
- deactivate current shell environment
- remove `.venv`
- recreate and reinstall

```bash
# macOS/Linux
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

```powershell
# Windows PowerShell
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

## Setup Guide

For full provider auth and environment details, see [docs/setup.md](docs/setup.md).

Key points:
- `codex` default auth mode is `chatgpt_login`; run `codex login` first.
- `google` default auth mode is `google_login`; run `gemini` login flow first.
- `stop-on-alert` is default true: auth/quota/rate-limit/provider-unavailable alerts stop runs.
- API key auth modes are available as alternatives in your local provider config.

## Repository Setup (First time)

1. Create local config directory:

```bash
mkdir -p configs/local
```

2. Copy example files:

```bash
cp configs/examples/providers_example.yaml configs/local/providers.yaml
cp configs/examples/risk_keywords_example.yaml configs/local/risk_keywords.yaml
cp configs/examples/local_settings_example.yaml configs/local/local_settings.yaml
cp .env.example .env
```

3. Edit local files only (`configs/local/*`, `.env`).
4. Run doctor:

```bash
python -m my_opt_code_agent doctor
```

## Provider presets (as of 2026-03-02)

Defaults from [configs/examples/providers_example.yaml](configs/examples/providers_example.yaml):

- `codex`
  - auth: `chatgpt_login` (or `api_key`)
  - model: `gpt-5.3-codex`
  - timeout: `1800` seconds (max wait upper bound)
- `google`
  - auth: `google_login` (`ai_studio_key`/`vertex_*` also supported)
  - model: `gemini-3.1-pro-preview-customtools`
  - timeout: `1800` seconds (max wait upper bound)
- `local`
  - model: `rule-based-v1`

## Common Commands

```bash
python -m my_opt_code_agent --help
python -m my_opt_code_agent doctor
python -m my_opt_code_agent run --repo . --task "provider bundle smoke" --review-providers codex,google,local --max-iters 1
```

## Run

> [!TIP]
> **Recommended (Most common)**
> - Coder = `codex` (default)
> - Reviewers A/B = `codex,google` (recommended bundle)
>
> ```bash
> python -m my_opt_code_agent run --repo <TARGET_REPO> --task "<WHAT TO CHANGE>" --review-providers codex,google
> ```
> Safe interactive variant:
> ```bash
> python -m my_opt_code_agent run --repo <TARGET_REPO> --task "<WHAT TO CHANGE>" --review-providers codex,google --hitl
> ```
>
> - `--repo`: path to the target repository that will be modified
> - `--task`: one-sentence change request for the run
> - Coder defaults to `codex` unless you change provider config
> - `--review-providers` applies to reviewer A/B only (not orchestrator/coder)

> [!NOTE]
> **Basic (Minimal)**
>
> ```bash
> python -m my_opt_code_agent run --repo <TARGET_REPO> --task "<WHAT TO CHANGE>" --review-providers codex
> ```

### What is HITL?

- HITL ON (`--hitl`): when mid/high-risk items exist, the run pauses and opens an interactive prompt.
- You can approve/deny specific test IDs, switch to fallback-only mode, add constraints, then `continue`.
- HITL OFF: mid/high-risk verification is not auto-executed and is blocked by PolicyGate.
- Even commands like `pytest` or `go test` can invoke real network/live actions indirectly in project code.
- `stop-on-alert` is default true: `auth`/`quota`/`rate_limit`/`provider_unavailable` stops the run and records alerts in report/state/trace.

## HITL Interactive Guide

### Prompt example

```text
== HITL TestPlan ==
1. test-1 | risk=low  | cmd=python -m compileall . | reason=Safe local verification command | fallback=-
2. test-2 | risk=mid  | cmd=echo withdraw now      | reason=Potentially unsafe/non-standard command; requires HITL approval | fallback=python -m compileall .
Type commands, then `continue` (or `abort`).
hitl>
```

### Commands

| Command | Meaning |
|---|---|
| `deny <ID...>` | Deny specific test items |
| `approve <ID...>` | Approve specific test items |
| `approve-all` | Approve all mid/high test items |
| `deny-all` | Deny all mid/high test items |
| `fallback-only` | Use fallback commands for all mid/high items |
| `set global_qps=<n>` | Set execution rate limit |
| `add forbidden_action=<kw>` | Add command keyword deny guard |
| `show` / `help` | Show current state or command help |
| `continue` / `abort` | Continue run or stop immediately |

### Common scenarios

A) Safety-first (deny all risky tests)

```text
deny-all
continue
```

B) Fallback-only + constraints

```text
fallback-only
set global_qps=1
add forbidden_action=withdraw
continue
```

C) Approve only selected tests

```text
show
approve test-2 test-3
deny test-4
continue
```

### Option relationship

When `--hitl` is on, interactive input is the default.  
If `--hitl --approve-mid-high` is set together, interactive prompt is skipped and treated as approve-all.  
`stop-on-alert` still applies and can stop the run immediately on alert conditions.

### Verification Safety Rules

- Command-string matching alone cannot prove safety 100%.
- Default principle:
  1. Auto-run low-risk local verification first.
  2. If external network/live-action indicators exist, elevate risk and require HITL approval/constraints.
  3. In target repos, keep explicit live-action guardrails (paper mode/allow flags) to prevent accidental real actions.
- Operational policy in this project: guardrails + HITL, not blind auto-execution.

### Advanced Examples

1. Codex-only reviews when you want the smallest provider surface.

```bash
python -m my_opt_code_agent run --repo . --task "refactor logging path" --review-providers codex
```

2. Multi-provider review with runtime fallback when one provider is temporarily unavailable.

```bash
python -m my_opt_code_agent run --repo . --task "provider bundle smoke" --review-providers codex,google,local --no-stop-on-alert --max-iters 1
```

3. Google-only strict validation when you want setup errors to fail immediately.

```bash
python -m my_opt_code_agent run --repo . --task "google strict check" --review-providers google --strict-review-providers
```

4. HITL approval flow for mid/high verification paths.

```bash
python -m my_opt_code_agent run --repo . --task "hitl verify flow" --verify-cmd "echo withdraw now" --hitl --approve-mid-high --review-providers codex
```

5. Critical change gate demonstration for dependency/CI/build files.

```bash
python -m my_opt_code_agent run --repo . --task "critical gate demo" --diff-file critical.diff
python -m my_opt_code_agent run --repo . --task "critical gate demo allow" --diff-file critical.diff --allow-critical
```

## Main options

- `--repo`, `--task`
- `--review-providers`, `--strict-review-providers`
- `--stop-on-alert` / `--no-stop-on-alert` (default stop)
- `--accept-proposals never|strong|all` (default `strong`)
- `--provider-config`, `--set-provider`
- `--max-iters` (default `5`)
- `--verify-cmd`
- `--hitl`, `--approve-mid-high`
- `--allow-critical`, `--allow-critical-files`, `--allow-critical-all`

Default provider config path:
- `configs/local/providers.yaml`
- if missing, doctor/run prints copy guidance from `configs/examples/providers_example.yaml`

## Artifacts (run output contract)

Each run creates one folder:

`reports/<repo_slug>/<timestamp>__<task_slug>/`

For `--repo .` in this repository:

`reports/ssalmuk-agent/<timestamp>__<task_slug>/`

Files:
- `report.md`
- `final.diff`
- `state.json`
- `trace.jsonl`

CLI always prints:
- `RUN_DIR:`
- `REPORT:`
- `DIFF:`
- `STATE:`
- `TRACE:`

## Troubleshooting

- venv not active
  - Symptom: `doctor` warns pip/venv mismatch
  - Fix: activate `.venv`, reinstall `pip install -e .`
- Python too old
  - Symptom: `doctor` shows `[FAIL] Python version is too low`
  - Fix: install Python 3.10+, recreate `.venv`
- OPENAI/GEMINI key or login issue
  - Symptom: auth alert for `codex`/`google`, or provider setup failure
  - Fix: for codex default run `codex login`; for key-based modes set `OPENAI_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`)
- codex login required
  - Symptom: auth alert, run stopped
  - Fix: `codex --help` then `codex login`
- gemini CLI missing
  - Symptom: provider_unavailable alert for google
  - Fix: install CLI, verify `gemini --help`, complete login
- stop-on-alert stopped my run
  - Symptom: `ALERT: ...` then `STOPPED: ...`
  - Fix: resolve root cause; if intentionally continuing fallback, use `--no-stop-on-alert`
- HITL ends as blocked
  - Symptom: PolicyGate remains blocked after HITL stage
  - Fix: provide approvals (`approve <ID...>` or `approve-all`) or choose `fallback-only`, then `continue`
- global_qps behavior
  - Symptom: verification feels throttled
  - Fix: `set global_qps=<n>` sets per-command pacing (sleep interval `1/n` seconds)
- forbidden_action matching
  - Symptom: command blocked unexpectedly
  - Fix: `add forbidden_action=<kw>` uses lowercase substring match against command text
- provider_unavailable / quota / rate_limit alerts
  - Symptom: `ALERT: provider_unavailable|quota|rate_limit ...`
  - Fix: install/enable provider, verify auth session/key, check plan/quota, retry later if rate-limited

## FAQ

- Q: Why no `requirements.txt`?
  - A: This repo intentionally uses `pyproject.toml` + `pip install -e .` as the single official path.
- Q: What Python version is supported?
  - A: Python 3.10+.
- Q: Why is `stop-on-alert` default true?
  - A: To fail safely on auth/quota/rate-limit/provider availability issues and prevent misleading partial runs.
- Q: Why is `google_login` conditional?
  - A: Non-interactive runs depend on an existing local Gemini CLI login session in the same environment. If session state is missing/expired, run `gemini` login flow again.

## Safety notes

- Critical Change Gate is default deny for dependency/version/CI/build critical files.
- Keep API keys out of git.
- Validate real provider integrations on your local machine.

## What should NOT be committed

- `configs/local/`
- `.env`, `.env.*`, `*.key`, `*.pem`
- `reports/` and `**/reports/`
- `docs/reports/` generated phase/audit markdown files
- local runtime logs and trace outputs

## How to customize

- Change local runtime/provider behavior in `configs/local/*` only.
- Keep committed examples in `configs/examples/*` as templates.
- Use `--provider-config <path>` when you intentionally need a non-default config location.

## References

- [spec.md](spec.md)
- [docs/setup.md](docs/setup.md)
- [configs/examples/providers_example.yaml](configs/examples/providers_example.yaml)

