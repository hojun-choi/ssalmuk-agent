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
- Codex is used as an external CLI (`codex`), not a Python library.
- `ssalmuk-agent` Codex provider calls this CLI via subprocess.

Setup (Windows/macOS/Linux):

1. Check Node/npm:

```bash
node -v
npm -v
```

2. Install Codex CLI globally (recommended):

```bash
npm install -g @openai/codex
codex --help
```

3. Login:

```bash
codex login
```

Windows troubleshooting:
- If `codex` is not found, reopen PowerShell and check `npm config get prefix`.
- Ensure npm global bin is on PATH (commonly `%AppData%\\npm`).
- If global install fails by permission, run PowerShell as Administrator and retry.

Optional API key mode:
- set `codex.auth_mode=api_key`
- set `OPENAI_API_KEY`

### Google provider (Gemini CLI)

Default:
- `google.auth_mode = google_login`
- `google.model = gemini-3.1-pro-preview`

Setup:

```bash
gemini --help
gemini
```

Then rerun the agent command.

Windows-first installation/login flow:

```powershell
node --version
npm --version
npm install -g @google/gemini-cli
gemini --help
gemini
```

After login, use `/model` in Gemini CLI and enable `remember model`.

UI vs non-interactive behavior:
- Running `gemini` without flags normally opens an interactive UI.
- `ssalmuk-agent` google provider runs Gemini non-interactively:
  - `gemini -p "{prompt}" --output-format json`
- If UI opens during provider execution, verify supported flags/version with `gemini --help`.

If `gemini` is not found, reopen PowerShell and verify npm global prefix:

```powershell
npm config get prefix
```

Typical global bin path is `%AppData%\\npm`. For the current shell, you can append:

```powershell
$env:Path = "$env:APPDATA\\npm;$env:Path"
gemini --help
```

Other auth modes:
- `ai_studio_key`: `GEMINI_API_KEY` or `GOOGLE_API_KEY`
- `vertex_api_key`: `GOOGLE_API_KEY` + vertex env vars
- `vertex_adc`: vertex env vars + ADC credentials

Model naming policy:
- `google_login` mode can only use model names provided by the installed Gemini CLI.
- API/Vertex identifiers (for example customtools-style names) are for `vertex_*` modes only, when backend support is available.

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

