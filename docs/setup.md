# Setup Guide

This project should be run in an isolated `.venv`.
Using system Python can cause dependency conflicts and path issues.
If setup fails, recreate `.venv` and reinstall cleanly.

## Requirements

- Python **3.10+**
- `pip`
- Git (recommended for diff/report workflows)

Packaging policy:
- Official install path is `pip install -e .` from `pyproject.toml`.
- `requirements.txt` is intentionally not used in this repository.

## 1) Create and use `.venv`

### Windows (PowerShell)

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
```

## 2) Repository setup (first time)

Create local config directory:

```bash
mkdir -p configs/local
```

Copy example files:

```bash
cp configs/examples/providers_example.yaml configs/local/providers.yaml
cp configs/examples/risk_keywords_example.yaml configs/local/risk_keywords.yaml
cp configs/examples/local_settings_example.yaml configs/local/local_settings.yaml
cp .env.example .env
```

Edit only local files (`configs/local/*`, `.env`) with your machine-specific values.

## 3) Doctor and smoke run

```bash
python -m my_opt_code_agent doctor
python -m my_opt_code_agent run --repo . --task "setup smoke" --review-providers codex,local --max-iters 1 --no-stop-on-alert
```

If `configs/local/providers.yaml` is missing, doctor/run prints copy guidance from `configs/examples/providers_example.yaml`.
When running this repository with `--repo .`, run artifacts are created under `reports/ssalmuk-agent/<timestamp>__<task_slug>/`.

## 4) Provider setup summary

### Codex provider

Default:
- `codex.auth_mode = chatgpt_login`

Setup:

```bash
codex --help
codex login
```

Optional API key mode:
- set `codex.auth_mode=api_key`
- set `OPENAI_API_KEY`

### Google provider (Gemini CLI)

Default:
- `google.auth_mode = google_login`

Setup:

```bash
gemini --help
gemini
```

Then rerun the agent command.

Other auth modes:
- `ai_studio_key`: `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `vertex_api_key`: `GOOGLE_API_KEY` + vertex env vars
- `vertex_adc`: vertex env vars + ADC credentials

## 5) What should NOT be committed

- `configs/local/`
- `.env`, `.env.*`, secret key files
- `reports/` run artifacts
- `docs/reports/` generated phase/audit markdown

## 6) Alert and run policy notes

- `--stop-on-alert` is default true.
- auth/quota/rate-limit/provider-unavailable alerts stop the run immediately.
- Use `--no-stop-on-alert` only when you intentionally want non-strict fallback continuation.

## 7) Recovery (wrong system install)

### Windows (PowerShell)

```powershell
if (Test-Path .venv) { Remove-Item -Recurse -Force .venv }
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e .
python -m my_opt_code_agent doctor
```

### macOS/Linux

```bash
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e .
python -m my_opt_code_agent doctor
```

