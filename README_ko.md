# ssalmuk-agent

> [!IMPORTANT]
> 이 프로젝트는 격리된 `.venv`(가상환경) 사용을 강력 권장하며, 사실상 필수입니다.
> 시스템 Python에 직접 설치하지 마세요. 설치/실행 오류의 대부분은 `.venv` 미사용에서 발생합니다.

Language:
- English: [README.md](README.md)
- 한국어: [README_ko.md](README_ko.md)

`ssalmuk-agent`는 patch -> verify -> review -> report 흐름을 한 번에 수행하는 phase 기반 Python CLI입니다.
provider bundle(`codex`, `google`, `local`), consensus 리뷰, run-folder artifacts, alerts, tracing을 사용합니다.
모든 실행 결과는 `reports/<repo_slug>/<timestamp>__<task_slug>/` 아래에 저장됩니다.
이 레포에서 `--repo .`로 실행하면 `reports/ssalmuk-agent/<timestamp>__<task_slug>/` 형식이 됩니다.

## Python and Packaging Policy

- 지원 Python: **3.10+** (`pyproject.toml`의 `requires-python = ">=3.10"`)
- 공식 설치 경로: **pyproject editable install 단일 경로** (`pip install -e .`)
- `requirements.txt`: **이 레포에서는 의도적으로 사용하지 않음**

왜 `requirements.txt`를 쓰지 않나요?
- 이 레포는 `pyproject.toml` 기반 패키지 설치를 기준으로 관리합니다.
- 공식 설치 경로를 `pip install -e .` 하나로 고정해 중복 의존성 정의와 사용자 혼동을 줄입니다.

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

시스템 Python에 잘못 설치했다면:
- 현재 환경을 종료(deactivate)
- `.venv` 삭제
- `.venv` 재생성 후 재설치

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

provider 인증/환경 설정 상세는 [docs/setup.md](docs/setup.md)를 참고하세요.

핵심 요약:
- `codex` 기본 인증 모드는 `chatgpt_login`이며, 먼저 `codex login`이 필요합니다.
- `google` 기본 인증 모드는 `google_login`이며, 먼저 `gemini` 로그인 플로우가 필요합니다.
- `stop-on-alert` 기본값은 true라서 auth/quota/rate-limit/provider-unavailable 알람 시 실행이 중단됩니다.
- API key 인증 모드는 로컬 provider config에서 대안으로 설정할 수 있습니다.

### Codex CLI setup (Windows/macOS/Linux)

`codex` provider는 Python 라이브러리가 아니라 외부 Codex CLI(`codex` 명령)를 사용합니다.
`ssalmuk-agent`는 provider 점검/리뷰 단계에서 이 CLI를 subprocess로 호출합니다.

1. Node/npm 확인:

```bash
node -v
npm -v
```

2. Codex CLI 전역 설치(권장):

```bash
npm install -g @openai/codex
codex --help
```

3. 로그인:

```bash
codex login
```

Windows troubleshooting:
- `codex`를 찾지 못하면 PowerShell을 다시 열고 `npm config get prefix`를 확인하세요.
- npm global bin 경로(보통 `%AppData%\\npm`)가 PATH에 포함되어야 합니다.
- 전역 설치 권한 오류가 나면 관리자 권한 PowerShell에서 다시 실행하세요.

### Gemini CLI setup (Windows)

`google_login` 모드는 로컬 Gemini CLI 세션과 CLI에서 지원되는 모델명에 의존합니다.

```powershell
node --version
npm --version
npm install -g @google/gemini-cli
gemini --help
gemini
```

로그인 후 `/model`로 모델을 선택하고 `remember model`을 활성화하세요.

UI vs non-interactive 동작:
- `gemini` 단독 실행은 모델 선택/채팅을 위한 인터랙티브 UI가 뜨는 것이 정상입니다.
- `ssalmuk-agent` google provider는 non-interactive 모드로 실행합니다:
  - `gemini -p "{prompt}" --output-format json`
- provider 실행 중 UI가 뜨면 설치된 CLI 플래그/버전을 `gemini --help`로 확인하세요.

설치 후 `gemini`를 찾지 못하면 PowerShell을 다시 열고 npm global prefix를 확인하세요:

```powershell
npm config get prefix
```

일반적인 global bin 경로 예시는 `%AppData%\\npm`입니다.
현재 쉘에서 즉시 반영이 필요하면:

```powershell
$env:Path = "$env:APPDATA\\npm;$env:Path"
gemini --help
```

모델명 정책:
- `google_login`: 설치된 Gemini CLI에서 제공되는 모델명만 사용합니다.
- `vertex_*`: customtools 계열을 포함한 API/Vertex 모델 식별자는 해당 auth mode/backend가 지원할 때만 사용 가능합니다.

## Repository Setup (First time)

1. 로컬 설정 디렉토리 생성:

```bash
mkdir -p configs/local
```

2. example 파일 복사:

```bash
cp configs/examples/providers_example.yaml configs/local/providers.yaml
cp configs/examples/risk_keywords_example.yaml configs/local/risk_keywords.yaml
cp configs/examples/local_settings_example.yaml configs/local/local_settings.yaml
cp .env.example .env
```

3. 로컬 파일만 수정 (`configs/local/*`, `.env`)
4. doctor 실행:

```bash
python -m my_opt_code_agent doctor
```

## Provider presets (as of 2026-03-02)

기본값은 [configs/examples/providers_example.yaml](configs/examples/providers_example.yaml)을 따릅니다.

- `codex`
  - auth: `chatgpt_login` (또는 `api_key`)
  - model: `gpt-5.3-codex`
  - timeout: `1800`초 (최대 대기 상한)
- `google`
  - auth: `google_login` (`ai_studio_key`/`vertex_*`도 지원)
  - model: `gemini-3.1-pro-preview`
  - timeout: `1800`초 (최대 대기 상한)
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
> 안전한 인터랙티브 변형:
> ```bash
> python -m my_opt_code_agent run --repo <TARGET_REPO> --task "<WHAT TO CHANGE>" --review-providers codex,google --hitl
> ```
>
> - `--repo`: 수정할 대상 레포 경로
> - `--task`: 변경 요구를 한 문장으로 입력
> - Coder 기본값은 `codex` (별도 설정이 없으면 유지)
> - `--review-providers`는 reviewer A/B에만 적용 (orchestrator/coder에는 직접 적용되지 않음)

> [!NOTE]
> **Basic (Minimal)**
>
> ```bash
> python -m my_opt_code_agent run --repo <TARGET_REPO> --task "<WHAT TO CHANGE>" --review-providers codex
> ```

### What is HITL?

- HITL(사람 검수) ON (`--hitl`): mid/high 위험 항목이 있으면 실행이 멈추고 인터랙티브 프롬프트가 열립니다.
- 프롬프트에서 항목별 승인/거절, fallback-only, 제약(global_qps/forbidden_action)을 입력한 뒤 `continue`로 재개합니다.
- HITL OFF: mid/high 위험 검증은 자동 실행하지 않고 PolicyGate가 차단합니다.
- `pytest`/`go test` 같은 명령도 내부 코드 경로에서 실제 네트워크/실행 동작을 유발할 수 있습니다.
- `stop-on-alert` 기본값은 true이며 `auth`/`quota`/`rate_limit`/`provider_unavailable` 발생 시 즉시 중단하고 report/state/trace에 기록합니다.

## HITL Interactive Guide

### 프롬프트 예시

```text
== HITL TestPlan ==
1. test-1 | risk=low  | cmd=python -m compileall . | reason=Safe local verification command | fallback=-
2. test-2 | risk=mid  | cmd=echo withdraw now      | reason=Potentially unsafe/non-standard command; requires HITL approval | fallback=python -m compileall .
Type commands, then `continue` (or `abort`).
hitl>
```

### 입력 가능한 명령어

| Command | 의미 |
|---|---|
| `deny <ID...>` | 특정 테스트 항목 실행 금지 |
| `approve <ID...>` | 특정 테스트 항목 실행 허용 |
| `approve-all` | mid/high 전체 허용 |
| `deny-all` | mid/high 전체 금지 |
| `fallback-only` | mid/high는 fallback만 실행 |
| `set global_qps=<n>` | 실행 속도 제한 설정 |
| `add forbidden_action=<kw>` | 금지 키워드 추가 |
| `show` / `help` | 현재 상태/도움말 출력 |
| `continue` / `abort` | 진행 / 즉시 중단 |

### 자주 쓰는 시나리오

A) 안전 우선(위험 테스트 전부 차단)

```text
deny-all
continue
```

B) 위험 테스트는 fallback만 + 제약 추가

```text
fallback-only
set global_qps=1
add forbidden_action=withdraw
continue
```

C) 특정 테스트만 허용

```text
show
approve test-2 test-3
deny test-4
continue
```

### 옵션 관계

`--hitl`이 켜져 있으면 기본은 인터랙티브 입력입니다.  
`--hitl --approve-mid-high`를 함께 주면 인터랙티브를 스킵하고 approve-all로 간주합니다.  
`stop-on-alert`는 그대로 적용되어 알람 조건 발생 시 즉시 중단될 수 있습니다.

### Verification Safety Rules

- 커맨드 문자열 매칭만으로 안전성을 100% 보장할 수 없습니다.
- 기본 원칙:
  1. 저위험(low) 로컬 검증부터 자동 실행
  2. 외부 네트워크/실행 가능성이 보이면 위험도를 상향하고 HITL 승인/제약을 요구
  3. 대상 레포에는 live action 방지 가드레일(paper mode/allow flag)을 유지 권장
- 이 프로젝트 운영 원칙은 blind auto-execution이 아니라 guardrails + HITL입니다.

### Advanced Examples

1. Codex만으로 간단히 리뷰하고 싶을 때 사용.

```bash
python -m my_opt_code_agent run --repo . --task "refactor logging path" --review-providers codex
```

2. 일부 provider가 일시적으로 불가할 때 fallback으로 계속 진행하고 싶을 때 사용.

```bash
python -m my_opt_code_agent run --repo . --task "provider bundle smoke" --review-providers codex,google,local --no-stop-on-alert --max-iters 1
```

3. Google 전용 경로를 엄격히 검증하고 setup 오류를 즉시 실패 처리하고 싶을 때 사용.

```bash
python -m my_opt_code_agent run --repo . --task "google strict check" --review-providers google --strict-review-providers
```

4. mid/high 검증 항목을 HITL 승인 경로로 처리할 때 사용.

```bash
python -m my_opt_code_agent run --repo . --task "hitl verify flow" --verify-cmd "echo withdraw now" --hitl --approve-mid-high --review-providers codex
```

5. 의존성/CI/build 중요 파일의 Critical gate 동작을 확인할 때 사용.

```bash
python -m my_opt_code_agent run --repo . --task "critical gate demo" --diff-file critical.diff
python -m my_opt_code_agent run --repo . --task "critical gate demo allow" --diff-file critical.diff --allow-critical
```

## Main options

- `--repo`, `--task`
- `--review-providers`, `--strict-review-providers`
- `--stop-on-alert` / `--no-stop-on-alert` (기본 stop)
- `--accept-proposals never|strong|all` (기본 `strong`)
- `--provider-config`, `--set-provider`
- `--max-iters` (기본 `5`)
- `--verify-cmd`
- `--hitl`, `--approve-mid-high`
- `--allow-critical`, `--allow-critical-files`, `--allow-critical-all`

Default provider config path:
- `configs/local/providers.yaml`
- 없으면 doctor/run이 `configs/examples/providers_example.yaml`에서 복사 안내를 출력

## Artifacts (run output contract)

실행 1회마다 폴더 1개가 생성됩니다.

`reports/<repo_slug>/<timestamp>__<task_slug>/`

이 레포에서 `--repo .`를 사용하면:

`reports/ssalmuk-agent/<timestamp>__<task_slug>/`

생성 파일:
- `report.md`
- `final.diff`
- `state.json`
- `trace.jsonl`

CLI는 종료 시 항상 다음 경로를 출력합니다.
- `RUN_DIR:`
- `REPORT:`
- `DIFF:`
- `STATE:`
- `TRACE:`

## Troubleshooting

- venv 미활성화
  - 증상: `doctor`에서 pip/venv mismatch 경고
  - 해결: `.venv` 활성화 후 `pip install -e .` 재실행
- Python 버전이 낮음
  - 증상: `doctor`에서 `[FAIL] Python version is too low`
  - 해결: Python 3.10+ 설치 후 `.venv` 재생성
- OPENAI/GEMINI 키 또는 로그인 문제
  - 증상: `codex`/`google` auth alert 또는 provider setup 실패
  - 해결: codex 기본 모드는 `codex login`, 키 모드는 `OPENAI_API_KEY` / `GEMINI_API_KEY`(또는 `GOOGLE_API_KEY`) 설정
- codex login 필요
  - 증상: auth alert 발생 후 run 중단
  - 해결: `codex --help` 확인 후 `codex login`
- gemini 미설치
  - 증상: google `provider_unavailable` alert
  - 해결: Gemini CLI 설치 후 `gemini --help`, 로그인 완료
- stop-on-alert로 중단됨
  - 증상: `ALERT: ...` 이후 `STOPPED: ...`
  - 해결: 원인 해결 후 재실행. 의도적으로 계속 진행하려면 `--no-stop-on-alert`
- HITL에서 blocked로 끝남
  - 증상: HITL 이후에도 PolicyGate blocked
  - 해결: `approve <ID...>` 또는 `approve-all` 입력, 또는 `fallback-only` 설정 후 `continue`
- global_qps 적용 방식
  - 증상: 검증 실행이 느려짐
  - 해결: `set global_qps=<n>`은 명령 사이 대기(`1/n`초)를 조절
- forbidden_action 매칭
  - 증상: 예상보다 많이 차단됨
  - 해결: `add forbidden_action=<kw>`는 명령 문자열 소문자 substring 매칭
- provider_unavailable / quota / rate_limit 알람
  - 증상: `ALERT: provider_unavailable|quota|rate_limit ...`
  - 해결: provider 설치/인증 확인, 플랜/쿼터 확인, rate limit이면 잠시 후 재시도

## FAQ

- Q: 왜 `requirements.txt`가 없나요?
  - A: 이 레포는 `pyproject.toml` + `pip install -e .` 단일 경로를 공식 설치 방식으로 사용합니다.
- Q: 지원 Python 버전은?
  - A: Python 3.10+입니다.
- Q: 왜 `stop-on-alert` 기본값이 true인가요?
  - A: auth/quota/rate-limit/provider 상태 이상에서 안전하게 즉시 실패하도록 설계했기 때문입니다.
- Q: 왜 `google_login`은 조건부로 동작하나요?
  - A: non-interactive 실행은 동일 환경의 기존 Gemini CLI 로그인 세션에 의존합니다. 세션 만료/부재 시 `gemini` 로그인 플로우를 다시 수행해야 합니다.

## Safety notes

- Critical Change Gate는 dependency/version/CI/build 중요 파일 변경을 기본 거부합니다.
- API 키는 절대 커밋하지 마세요.
- 실제 provider 연동은 로컬 환경에서 확인하세요.

## What should NOT be committed

- `configs/local/`
- `.env`, `.env.*`, `*.key`, `*.pem`
- `reports/` 및 `**/reports/`
- `docs/reports/` 생성 보고서
- 로컬 실행 로그/trace 산출물

## How to customize

- 로컬 동작/설정은 `configs/local/*`에서만 수정
- 커밋되는 템플릿은 `configs/examples/*`에서 참고
- 다른 설정 경로가 필요하면 `--provider-config <path>` 사용

## References

- [spec.md](spec.md)
- [docs/setup.md](docs/setup.md)
- [configs/examples/providers_example.yaml](configs/examples/providers_example.yaml)

