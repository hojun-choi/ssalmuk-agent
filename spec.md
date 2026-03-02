# SPEC ??ssalmuk-agent
> Multi-agent repo editing tool with deterministic workflow, verification, and structured reporting (with human-in-the-loop for risky actions)

## 0) One-line Summary
`ssalmuk-agent`???뱀젙 Git ?덊룷??????ъ슜?먭? 吏?쒗븳 ?묒뾽??**?뺥솗???섏젙(diff 湲곕컲)** ?섍퀬, 媛?ν븳 踰붿쐞?먯꽌 **寃利??뚯뒪??由고듃/鍮뚮뱶)** ???? ?쒕Т?뉗쓣 ???대뼸寃?諛붽엥?붿??앸? **援ъ“?붾맂 寃곌낵 蹂닿퀬??*濡?諛섑솚?섎뒗 硫?곗뿉?댁쟾???댁씠??  
?몃? API ?몄텧(嫄곕옒??二쇰Ц/異쒓툑 ??泥섎읆 ?꾪뿕??寃利앹? ?먮룞 ?ㅽ뻾?섏? ?딄퀬, **risk = low/mid/high**濡?遺꾨쪟??**?ъ슜??寃??HITL)** 瑜?嫄곗튇??

---

## 1) Goals
1. ?ъ슜?먯쓽 ?붽뎄?ы빆??肄붾뱶 蹂寃쎌쑝濡?諛섏쁺?쒕떎 (unified diff/patch 湲곕컲).
2. 蹂寃쎌궗??쓣 濡쒖뺄?먯꽌 寃利앺븳??(safe 踰붿쐞 ??tests/lint/build).
3. ?ㅽ뙣 ???먮룞 猷⑦봽: ?섏젙 ??寃利???由щ럭 ???ъ닔??
4. 理쒖쥌 ?곗텧臾? **ChangeLog + Requirement Trace + Verification Log + PR-ready summary**.
5. ?먯씠?꾪듃/紐⑤뜽 諛붽퓭?쇱슦湲?媛??(Orchestrator/Coder/Reviewers ??븷 遺꾨━ + Adapter).

## 2) Non-goals
- 諛깃렇?쇱슫???곕が ?뺥깭???μ떆媛?臾댁씤 ?댁쁺.
- 諛고룷/?명봽???꾨줈?뺤뀡 ?댁쁺 ?먮룞 蹂寃쎄퉴吏 ?ы븿(?꾩냽 ?뺤옣).
- ?뚯뒪?멸? ?녿뒗 ?덊룷?먯꽌???덉쟾??蹂댁옣(寃利앹씠 ?놁쑝硫?由ъ뒪??寃쎄퀬).

---

## 3) Principles
- **LLM??留먯? 誘우? ?딅뒗?? ?ㅽ뻾 寃곌낵瑜?誘용뒗??**
- 醫낅즺 議곌굔? ?쒕???醫낅즺?앷? ?꾨땲???쒓?利?+ 由щ럭 ?뱀씤?앹씠??
- 紐⑤뱺 ?④퀎???곗텧臾쇱쓣 ?④린怨?state???꾩쟻), 留덉?留됱뿉 **蹂닿퀬???먮룞 ?앹꽦**?쒕떎.
- ?몃? API/?덉씠 嫄몃┛ ?됰룞? ?먮룞 ?ㅽ뻾?섏? ?딄퀬 **??긽 ?ъ슜??寃??*瑜?嫄곗튇??

---

## 4) System Architecture Overview
### 4.1 Orchestration Engine
- LangGraph 湲곕컲 ?곹깭癒몄떊(洹몃옒??濡??뚰겕?뚮줈瑜?媛뺤젣?쒕떎.
- Durable execution / interrupt(HITL) / ?곹깭 湲곕컲 ?ш컻瑜?吏?먰븳??

### 4.2 Agents (Default: 4)
- **Orchestrator (Codex)**  
  ?곹깭 愿由? ?④퀎 吏꾪뻾, 醫낅즺 議곌굔 ?먯젙, 理쒖쥌 蹂닿퀬???앹꽦
- **Coder (Codex)**  
  蹂寃?怨꾪쉷 湲곕컲 diff ?앹꽦/?섏젙 諛섎났
- **ReviewerA (Codex)**  
  湲곕뒫 ?붽뎄 異⑹”/?ㅺ퀎/?덉쟾??愿??由щ럭
- **ReviewerB (Codex)**  
  ?뚯뒪???ｌ?耳?댁뒪/由ш렇?덉뀡/?ㅽ???愿??由щ럭

> ?쒖뿉?댁쟾??= ??븷?? ?쒕え??= 援ы쁽泥닳? 紐⑤뜽? Adapter濡?援먯껜 媛??

### 4.3 Model Abstraction (Swap-friendly)
- `AgentAdapter` ?명꽣?섏씠?ㅻ줈 Codex/Gemini/湲고? LLM??諛붽퓭?쇱슫??
- ?ㅼ??ㅽ듃?덉씠?섏? LangGraph媛 ?대떦(?먮쫫 媛뺤젣).
- (?듭뀡) OpenAI Agents SDK??**?몃뱶 ?대?**?먯꽌 ?댁퐳/?몃젅?댁떛???꾪빐 ?ъ슜 媛??

---

## 5) Workflow (LangGraph Graph)
### 5.1 Nodes
N0. **InputNormalize**
- ?ъ슜??吏?쒕? 援ъ“??TaskSpec)濡??뺣━
- ?쒖빟/湲덉? 洹쒖튃/?곗꽑?쒖쐞 諛섏쁺

N1. **RepoScan**
- ?뚯씪 ?몃━/?듭떖 紐⑤뱢 ?꾨낫/?뚯뒪??而ㅻ㎤???꾨낫 ?섏쭛
- `repo_map` ?앹꽦(二쇱슂 ?⑦궎吏/?뷀듃由ы룷?명듃/?뚯뒪???꾩튂)

N2. **Plan**
- 蹂寃?怨꾪쉷(????뚯씪/?묎렐 ?꾨왂/寃利??꾨왂/由ъ뒪??
- 蹂寃?湲덉? ?곸뿭(forbidden_paths)怨??섏젙 ?덉슜 ?곸뿭(allowed_paths) 諛섏쁺

N3. **Implement (Coder)**
- unified diff ?앹꽦
- ?뚯씪蹂?rationale(???섏젙?덈뒗吏) ?꾩닔

N4. **ApplyPatch**
- ?묒뾽 ?몃━??patch ?곸슜
- ?ㅽ뙣 ??Implement濡??섎룎由?

N5. **TestPlan (Planner/Orchestrator)**
- ?ㅽ뻾??寃利??뚯뒪??由고듃/鍮뚮뱶) 紐⑸줉???앹꽦
- 媛???ぉ?????**risk: low | mid | high**瑜?遺?ы븯怨?洹쇨굅瑜??④퍡 湲곕줉
- 媛?ν븳 寃쎌슦, ?꾪뿕????ぉ??**?泥?寃利?fallback)** ???쒖븞(?? mock/replay/sandbox)

N6. **PolicyGate (HITL interrupt)**
- TestPlan??`risk=mid` ?먮뒗 `risk=high` ??ぉ???덉쑝硫?**以묐떒**?섍퀬 ?ъ슜?먯뿉寃??뱀씤/?쒖빟 ?낅젰???붿껌
- ?ъ슜?먮뒗 ??붾줈 ?ㅼ쓬??吏??媛??
  - ?쒖씠 ?뚯뒪?몃뒗 ?댁쁺 ?뚯븘媛???1珥덉뿉 1踰덈쭔??
  - ?쒖＜臾몄? 10 USDT源뚯?留뚢?
  - ?쐗ithdraw/transfer???덈? 湲덉???
  - ?쒖씠嫄?dry-run / paper 怨꾩젙?쇰줈留뚢?
- ?ъ슜?먯쓽 ?낅젰? `UserConstraints`濡?state????λ릺???댄썑 猷⑦봽?먮룄 吏???곸슜

N7. **Verify (Runner)**
- ?뱀씤????ぉ留??ㅽ뻾
- ?ㅽ뻾 寃곌낵(紐낅졊??異쒕젰/?깃났 ?щ?/?붿빟)瑜?VerificationLog濡????
- constraints(rate limit, 湲덉? ?≪뀡 ??瑜?Runner媛 媛뺤젣濡?諛섏쁺

N8. **ReviewA**
- approve/reject + issue list(severity ?ы븿) 諛섑솚

N9. **ReviewB**
- approve/reject + issue list(severity ?ы븿) 諛섑솚

N10. **Resolve (Coder)**
- Verify ?ㅽ뙣/Review reject ?먯씤??諛섏쁺???섏젙 diff ?ъ깮??
- Implement濡?loop

N11. **Report (Orchestrator)**
- 理쒖쥌 蹂닿퀬???앹꽦(蹂寃쎌궗???붽뎄?ы빆 留ㅽ븨/寃利?由щ럭/PR ?ㅻ챸)

### 5.2 Edges / Loop Conditions
- ApplyPatch ?ㅽ뙣 ??Implement濡?
- Verify ?ㅽ뙣 ??Resolve濡?
- ReviewA ?먮뒗 ReviewB reject ??Resolve濡?
- 醫낅즺(approve) 議곌굔:
  - Verify ?듦낵
  - ReviewA approve
  - ReviewB approve
- 諛섎났 ?쒗븳:
  - `max_iters` 湲곕낯 5
  - ?숈씪 ?댁뒋 諛섎났 ??`need_human=true` ?뚮옒洹?諛?HITL 沅뚯옣

---

## 6) Risk Classification (low/mid/high)
> ?쒕젅踰ⓥ?????ъ슜?먯뿉寃뚮뒗 **?몄뼱??由ъ뒪??*濡쒕쭔 蹂닿퀬?쒕떎.

### 6.1 Risk ?뺤쓽
- **low**: ?몃? ?ㅽ듃?뚰겕/?ㅺ퀎?????대룞 ?놁쓬. 濡쒖뺄?먯꽌 ?덉쟾?섍쾶 諛섎났 ?ㅽ뻾 媛??
  - ?? ?좊떅 ?뚯뒪??紐⑦궧), lint, fmt, typecheck, ?뺤쟻遺꾩꽍, ?쒖닔 濡쒖뺄 鍮뚮뱶
- **mid**: ?몃? ?ㅽ듃?뚰겕 ?몄텧 媛?μ꽦???덉쑝?? ???곹깭 蹂寃쎌? ?먯튃?곸쑝濡??놁쓬.  
  ?? rate-limit/?댁쁺 ?곹뼢 ?꾪뿕???덉쑝誘濡?湲곕낯? ?ъ슜??寃??沅뚯옣.
  - ?? public ?쒖꽭 議고쉶, healthcheck, read-only API ?몄텧(?댁쁺 ?섍꼍?대㈃ 遺??
- **high**: ???곹깭 蹂寃?媛?μ꽦, ?뱀? ?댁쁺??吏곸젒 ?곹뼢(二쇰Ц/異쒓툑/?異??곹솚/怨꾩젙 蹂寃???.  
  **??긽 ?ъ슜???뱀씤 ?꾩슂. 湲곕낯 deny.**
  - ?? place order, cancel order, withdraw, transfer, borrow/repay, leverage/margin actions

### 6.2 Risk ?곗젙 洹쒖튃(?대━?ㅽ떛)
Runner/Planner???꾨옒 ?ㅼ썙???됰룞??媛먯??섎㈃ risk瑜??щ┛??
- `withdraw|transfer|send|loan|borrow|repay|order|market_buy|market_sell|limit_buy|limit_sell`
- API ?붾뱶?ъ씤?멸? 嫄곕옒/?먯궛 愿??
- ?ㅺ퀎?????꾨줈?뺤뀡 ?섍꼍蹂??媛먯?
- ?ㅽ듃?뚰겕 ?몄텧??媛뺤젣?섎뒗 ?듯빀 ?뚯뒪??

---

## 7) Human-in-the-loop (HITL) Interaction
### 7.1 UserConstraints (State)
?ъ슜?먮뒗 mid/high 寃利??④퀎?먯꽌 ?꾨옒瑜??좊룞?곸쑝濡?吏?뺥븷 ???덈떎:
- rate limit: ?? global 1 qps, exchange蹂?1 qps
- 二쇰Ц ?쒗븳: ?? 理쒕? notional 10 USDT, market 湲덉?, ?뱀젙 ?щ낵留??덉슜
- ?섍꼍: ?? paper/sandbox 媛뺤젣, production 湲덉?
- 湲덉? ?≪뀡: ?? withdraw/transfer/loan 湲덉?
- ?ㅽ뻾 ?덉슜 紐⑸줉: ?? ?뱀젙 ?뚯뒪??ID留??뱀씤

### 7.2 HITL UX (CLI)
- Tool? mid/high 寃利앹씠 ?ы븿??TestPlan???ъ슜?먯뿉寃?蹂댁뿬以??
  - ?뚯뒪??ID, cmd, risk(low/mid/high), reason, fallback
- ?ъ슜?먮뒗 ?쒖듅??嫄곗젅/?쒖빟 議곌굔 異붽?/?泥?寃利??좏깮?앹쓣 ?낅젰?쒕떎.
- ?뱀씤 ?댁슜? state????λ릺???ㅼ쓬 猷⑦봽?먯꽌???좎??쒕떎.

---

## 8) State Schema (Pydantic Recommended)
### 8.1 Core State (Example)
- task:
  - user_request: string
  - constraints:
    - allowed_paths: []
    - forbidden_paths: []
    - style_rules: []
- repo:
  - root: string
  - repo_map: string
  - candidate_files: []
- plan:
  - approach: string
  - files_to_touch: []
  - verification_strategy: []
- patch:
  - diff: string
  - touched_files: []
  - rationale_by_file: {path: rationale}
- test_plan:
  - items: [
      {id, cmd, risk: "low|mid|high", reason, fallback?}
    ]
- user_constraints:
  - approvals: [{id, action: "approve|deny|approve_with_constraints"}]
  - rate_limit: {global_qps, per_exchange?}
  - order_cap: {max_notional_usdt, allow_market, allow_symbols?}
  - forbidden_actions: []
  - env_overrides: {}
- verification:
  - executed: [{id, cmd, start_ts, end_ts, exit_code, stdout_tail, stderr_tail, passed}]
  - passed: bool
- reviews:
  - reviewer_a: {verdict, issues[]}
  - reviewer_b: {verdict, issues[]}
- loop:
  - iter: int
  - max_iters: int
  - repeated_issues: {signature: count}
- report:
  - markdown: string
  - final_diff: string

---

## 9) Tools
### 9.1 Repo Tools
- read_file(path)
- write_file(path, content)  (HITL ?듭뀡)
- list_files(glob)
- search_text(query, paths)

### 9.2 Patch Tools
- apply_patch(diff)
- git_diff()
- git_status()

### 9.3 Runner Tools
- run_cmd(cmd, cwd, timeout)
- enforce_constraints(constraints):
  - 湲덉? ?≪뀡 ?ㅼ썙???붾뱶?ъ씤??李⑤떒
  - ?섍꼍 蹂??媛뺤젣(sandbox/paper)
  - rate limit ?곸슜(?뚯뒪???ㅽ뻾 媛?sleep ??

### 9.4 Guardrails
- forbidden_paths ?섏젙 ??利됱떆 ?ㅽ뙣
- diff ?ш린 ?쒗븳(?뚯씪 ???쇱씤 ??珥덇낵 ??HITL ?꾩슂)
- high risk ?뚯뒪?몃뒗 湲곕낯 deny (紐낆떆 ?뱀씤 ?놁쑝硫??ㅽ뻾 湲덉?)

---

## 10) Output Contracts (Strict)
### 10.1 Coder Output (JSON)
- diff: string (unified diff)
- touched_files: []
- rationale_by_file: {path: "why"}
- risk_notes: []
- followup_tests: []

### 10.2 TestPlan Output (JSON)
- items: [{id, cmd, risk, reason, fallback?}]
- notes: "why these tests"

### 10.3 Reviewer Output (JSON)
- verdict: "approve" | "reject"
- issues:
  - {severity: "blocker|major|minor", file, location, description, suggested_fix}
- missing_tests: []
- rationale: string

### 10.4 Final Report (Markdown)
?꾩닔 ?뱀뀡:
1) Summary
2) Changes (File-by-file)
3) Requirement Trace (?붽뎄?ы빆 ??肄붾뱶 蹂寃?洹쇨굅 ??寃利?洹쇨굅)
4) Verification (cmd + PASS/FAIL + 濡쒓렇 ?붿빟, risk ?ы븿)
5) Review Notes (A/B 肄붾찘???붿빟 + ?닿껐 怨쇱젙)
6) PR-ready (而ㅻ컠 硫붿떆吏/PR ?ㅻ챸/由ъ뒪??濡ㅻ갚)

---

## 11) Repo Structure (Suggested)
ssalmuk-agent/
  cmd/agent/                  # CLI entry
  internal/
    graph/                    # langgraph runner, nodes, edges
    agents/
      adapter/                # AgentAdapter interface + impls
      orchestrator/
      coder/
      reviewer/
    tools/
      repo/
      patch/
      runner/
    policy/
      risk/                   # low/mid/high classifier
      guardrails/
    schemas/
      state.py
      outputs.py
  configs/
    presets.yaml              # test/lint/build presets
  docs/
    report_template.md
  examples/
    tasks/

---

## 12) CLI UX (MVP)
- `agent run --repo <path> --task "<instruction>" [--hitl] [--max-iters 5]`
- output artifacts:
  - `my_opt_report.md`
  - `final.diff`
  - (optional, HITL) branch/commit: `ssalmuk/<timestamp>`

---

## 13) Acceptance Criteria
- [ ] 吏?쒖궗??諛섏쁺??肄붾뱶 蹂寃쎌씠 ?ㅼ젣濡??곸슜??
- [ ] TestPlan???앹꽦?섎ŉ 媛???ぉ??risk(low/mid/high)媛 ?ы븿??
- [ ] mid/high ??ぉ? ?ъ슜???뱀씤/?쒖빟 ?놁씠???ㅽ뻾?섏? ?딆쓬
- [ ] Verify 寃곌낵媛 蹂닿퀬?쒖뿉 ?ы븿??
- [ ] ReviewerA/B approve ?쒖뿉留?醫낅즺
- [ ] 理쒖쥌 蹂닿퀬?쒓? 吏?뺣맂 ?щ㎎?쇰줈 ?앹꽦??
- [ ] AgentAdapter濡?紐⑤뜽 援먯껜 媛??

---

## 14) Implementation Phases
Phase 0: ?⑥씪 ?먯씠?꾪듃 + Verify(low only) + Report
Phase 1: Coder/Reviewer 遺꾨━ + reject loop
Phase 2: Reviewer 2紐?+ ?⑹쓽 醫낅즺 議곌굔
Phase 3: TestPlan + PolicyGate(HITL) + constraints ?곸슜
Phase 4: Adapter ?뺤옣(Codex/Gemini/湲고?) + ?몃젅?댁떛/愿痢≪꽦 媛뺥솕
## 15) Critical Change Gate

### 15.1 Critical File Patterns
- Python: `pyproject.toml`, `requirements*.txt`, `poetry.lock`, `uv.lock`, `Pipfile*`, `.python-version`, `runtime.txt`
- Go: `go.mod`, `go.sum`
- Node: `package.json`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`
- CI/Docker/Build: `Dockerfile*`, `docker-compose*.yml`, `Makefile`, `.github/workflows/*.yml`, `.tool-versions`

### 15.2 Policy
1. If any critical file pattern is included in a patch diff, classify `change_risk="high"`.
2. `change_risk="high"` is default deny. Without explicit user approval, do not proceed to ApplyPatch.
3. Approval request must include: why this change is needed, impact scope, and rollback method.

### 15.3 CLI Enforcement (Phase 0 policy extension)
- Default behavior: critical changes are blocked.
- Explicit overrides:
  - `--allow-critical` (allow this run)
  - `--allow-critical-files <glob,...>` (allow only specific critical files)
  - `--allow-critical-all` (allow all critical files)
- If blocked, runner must print approval-required details and write `Critical Changes (Approval Required)` in report.

## 16) Review Bundle Config (Provider-Extensible)

### 16.1 review_bundle
- `providers: [string]`  
  Example: `['codex']`, `['google']`, `['codex','google']`
- `roles: ['reviewer_a','reviewer_b']` (fixed two-role bundle)
- `aggregation:`
  - `policy: 'consensus'` (default)
  - `rules:`
    - `if_any_blocker_reject: true`
    - `if_any_major_reject: true` (default true, optional)
    - `allow_minor_only: true`

### 16.2 provider_runs
- For each provider, run `reviewer_a` and `reviewer_b` separately.
- Store outputs per provider run in state.

## 17) Provider Registry

### 17.1 providers_registry
- `codex:`
  - `type: 'openai' | 'agents_sdk' | 'http_openai_compatible'`
  - `model: <string>`
  - `options: {temperature, max_tokens, ...}`
  - `env: {OPENAI_API_KEY, OPENAI_BASE_URL?}`
- `google:`
  - `type: 'cli'`
  - `command: 'google' | 'gemini'` (actual setup command documented in setup docs)
  - `model: <string>`
  - `options: {...}`
  - `env: {GOOGLE_API_KEY?}`
- Extensible for additional providers (e.g. `anthropic`, `local`).

## 18) CLI Additions (Review Providers)
- `--review-providers "codex,google"`
- `--provider-config <path>` (default: `configs/local/providers.yaml`)
- `--set-provider "codex.model=gpt-5.3-codex"` (repeatable)
- default review provider when unspecified: `['codex']`
- strict mode option: `--strict-review-providers`

### 18.1 Current execution policy (pre-Phase-2)
- `codex` is fully supported.
- `google` is declared but not implemented yet (Phase 4 target).
- non-strict mode (default): if unsupported/unimplemented providers are requested, print a clear warning and fallback to `codex`.
- strict mode: fail fast when unsupported/unimplemented providers are requested.

## 19) State Schema Extension (Review Bundle)
- `state.review_bundle.providers: list[str]`
- `state.review_bundle.roles: ['reviewer_a','reviewer_b']`
- `state.reviews.provider_runs: list[{provider, role, verdict, issues, rationale, raw?}]`

## 20) Report Template Extension
- Review Notes must include provider-by-provider result summary.
- Aggregation conclusion must explain how final review conclusion was determined.

## 21) Artifact Output Policy (Run Folder Layout) [Authoritative]

This section supersedes previous single-file artifact path examples.

### 21.1 Report Directory Layout
- Use internal `reports/` directory at the project root.
- Repository-level folder:
  - `reports/<repo_slug>/`
- Run-level folder (one run = one folder):
  - `reports/<repo_slug>/<timestamp>__<task_slug>/`
- Example for this repository (`--repo .`):
  - `reports/ssalmuk-agent/<timestamp>__<task_slug>/`

### 21.2 Required Artifacts Per Run
For every run termination state (`approve`, `reject`, `max-iters`, `hitl interrupt`, `critical gate block`), the system MUST create the run folder and always write all of the following files:
1. `report.md`
2. `final.diff` (unified diff)
3. `state.json` (audit state)

Final layout:
- `reports/<repo_slug>/<timestamp>__<task_slug>/report.md`
- `reports/<repo_slug>/<timestamp>__<task_slug>/final.diff`
- `reports/<repo_slug>/<timestamp>__<task_slug>/state.json`

### 21.3 Report Title and Artifacts Section
- `report.md` H1 title format:
  - `# [<repo_slug>] <task_title>  <YYYY-MM-DD HH:MM KST>`
- `report.md` top section MUST include `Artifacts`:
  - `Run folder: reports/<repo_slug>/<timestamp>__<task_slug>/`
  - `report.md: reports/<repo_slug>/<timestamp>__<task_slug>/report.md`
  - `final.diff: reports/<repo_slug>/<timestamp>__<task_slug>/final.diff`
  - `state.json: reports/<repo_slug>/<timestamp>__<task_slug>/state.json`

### 21.4 CLI Output Contract
At run termination, CLI MUST print:
- `RUN_DIR: <relative_path_from_repo_root>`
- `REPORT: <relative_path_from_repo_root>`
- `DIFF: <relative_path_from_repo_root>`
- `STATE: <relative_path_from_repo_root>`

Path format is standardized as **relative paths from repository root**.

### 21.5 Critical Change Gate Linkage
- If patch apply is blocked by critical change gate, the run folder and all three artifacts MUST still be created.
- `report.md` MUST keep `Critical Changes (Approval Required)` section for blocked runs.

## 22) HITL Interactive Policy [Authoritative]

### 22.1 Trigger
- If `--hitl` is enabled and TestPlan contains any `mid`/`high` item, the run MUST open an interactive HITL prompt.
- Do not immediately terminate as blocked while interactive HITL is available.

### 22.2 Supported Commands
- `deny <ID...>`
- `approve <ID...>`
- `approve-all`
- `deny-all`
- `fallback-only`
- `set global_qps=<n>`
- `add forbidden_action=<kw>`
- `show`
- `help`
- `continue`
- `abort`

### 22.3 Defaults and Option Interaction
- With `--hitl` enabled: interactive input is the default path.
- If user continues without explicit approvals, default mode is `fallback_only`.
- If `--hitl --approve-mid-high` are both provided: skip prompt and treat as approve-all.
- With `--hitl` disabled: existing non-interactive policy remains (mid/high blocked unless explicitly transformed by policy path).

### 22.4 Constraints Persistence
State MUST store:
- `user_constraints.approved_ids`
- `user_constraints.denied_ids`
- `user_constraints.rate_limit.global_qps`
- `user_constraints.forbidden_actions`
- `user_constraints.mode` (`normal` | `fallback_only`)
- `user_constraints.hitl_input_history` (raw entered commands)

### 22.5 Execution Rules
- `denied_ids` must never run.
- `fallback_only` mode must execute only fallback commands for `mid/high`.
- approved IDs in `normal` mode execute original command.
- network-indicator-elevated items are part of the HITL decision list.

### 22.6 Required Recording
- `trace.jsonl` events:
  - `hitl_prompt_shown`
  - `hitl_command_received`
  - `hitl_decision_finalized`
- `report.md` MUST include an `HITL` section with decisions and constraints.
- `abort` MUST produce stop status and still emit artifacts/report/state/trace.

