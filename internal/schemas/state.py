from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if is_dataclass(value):
        return asdict(value)
    return value


DEFAULT_REVIEW_ROLES = ["reviewer_a", "reviewer_b"]


try:
    from pydantic import BaseModel, Field

    class TaskSpec(BaseModel):
        user_request: str
        constraints: dict[str, Any] = Field(default_factory=dict)

    class VerificationItem(BaseModel):
        id: str
        cmd: str
        risk: str
        exit_code: int
        stdout_tail: str
        stderr_tail: str
        passed: bool

    class VerificationResult(BaseModel):
        executed: list[VerificationItem] = Field(default_factory=list)
        passed: bool = False

    class TestPlanItem(BaseModel):
        id: str
        cmd: str
        risk: str
        reason: str
        fallback: str | None = None

    class UserConstraints(BaseModel):
        approvals: list[dict[str, Any]] = Field(default_factory=list)
        rate_limit: dict[str, Any] = Field(default_factory=lambda: {"global_qps": 1})
        forbidden_actions: list[str] = Field(default_factory=list)
        approved_ids: list[str] = Field(default_factory=list)
        denied_ids: list[str] = Field(default_factory=list)
        mode: str = "fallback_only"
        hitl_input_history: list[str] = Field(default_factory=list)
        hitl_confirmed: bool = False

    class PolicyGateState(BaseModel):
        status: str = "not_checked"
        need_human: bool = False
        blocked_items: list[str] = Field(default_factory=list)
        message: str = ""

    class ReviewIssue(BaseModel):
        severity: str
        file: str
        location: str
        description: str
        suggested_fix: str
        code: str
        meta: dict[str, Any] = Field(default_factory=dict)

    class ImprovementProposal(BaseModel):
        title: str
        description: str
        motivation: str
        suggested_steps: list[str] = Field(default_factory=list)
        affected_files: list[str] = Field(default_factory=list)
        expected_benefit: str = ""
        risk_level: str = "low"

    class ReviewResult(BaseModel):
        verdict: str = "reject"
        issues: list[ReviewIssue] = Field(default_factory=list)
        rationale: str = ""
        improvement_proposals: list[ImprovementProposal] = Field(default_factory=list)
        proposal_policy_hint: str = "optional"

    class AggregationRules(BaseModel):
        if_any_blocker_reject: bool = True
        if_any_major_reject: bool = True
        allow_minor_only: bool = True

    class AggregationConfig(BaseModel):
        policy: str = "consensus"
        rules: AggregationRules = Field(default_factory=AggregationRules)

    class ReviewBundleConfig(BaseModel):
        providers: list[str] = Field(default_factory=lambda: ["codex"])
        roles: list[str] = Field(default_factory=lambda: list(DEFAULT_REVIEW_ROLES))
        aggregation: AggregationConfig = Field(default_factory=AggregationConfig)

    class ProviderRun(BaseModel):
        provider: str
        role: str
        verdict: str
        issues: list[ReviewIssue] = Field(default_factory=list)
        rationale: str = ""
        improvement_proposals: list[ImprovementProposal] = Field(default_factory=list)
        proposal_policy_hint: str = "optional"
        raw: dict[str, Any] | None = None

    class ReviewsState(BaseModel):
        provider_runs: list[ProviderRun] = Field(default_factory=list)
        aggregation_conclusion: str = ""

    class AlertEvent(BaseModel):
        type: str
        provider: str
        role: str | None = None
        message: str = ""
        ts: str = ""
        severity: str = "warn"

    class AgentState(BaseModel):
        task: TaskSpec
        repo_root: str
        status: str = "running"
        stopped_reason: str = ""
        patch_applied: bool = False
        iter: int = 0
        max_iters: int = 5
        coder_inputs: list[dict[str, Any]] = Field(default_factory=list)
        coder_runs: list[dict[str, Any]] = Field(default_factory=list)
        test_plan: list[TestPlanItem] = Field(default_factory=list)
        user_constraints: UserConstraints = Field(default_factory=UserConstraints)
        policy_gate: PolicyGateState = Field(default_factory=PolicyGateState)
        verification_history: list[VerificationResult] = Field(default_factory=list)
        review_history: list[ReviewResult] = Field(default_factory=list)
        latest_issues: list[ReviewIssue] = Field(default_factory=list)
        latest_proposals: list[ImprovementProposal] = Field(default_factory=list)
        review_bundle: ReviewBundleConfig = Field(default_factory=ReviewBundleConfig)
        reviews: ReviewsState = Field(default_factory=ReviewsState)
        provider_messages: list[str] = Field(default_factory=list)
        alerts: list[AlertEvent] = Field(default_factory=list)
        network_findings: list[dict[str, Any]] = Field(default_factory=list)
        proposal_decisions: list[dict[str, Any]] = Field(default_factory=list)

except ImportError:
    @dataclass
    class TaskSpec:
        user_request: str
        constraints: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class VerificationItem:
        id: str
        cmd: str
        risk: str
        exit_code: int
        stdout_tail: str
        stderr_tail: str
        passed: bool

    @dataclass
    class VerificationResult:
        executed: list[VerificationItem] = field(default_factory=list)
        passed: bool = False

    @dataclass
    class TestPlanItem:
        id: str
        cmd: str
        risk: str
        reason: str
        fallback: str | None = None

    @dataclass
    class UserConstraints:
        approvals: list[dict[str, Any]] = field(default_factory=list)
        rate_limit: dict[str, Any] = field(default_factory=lambda: {"global_qps": 1})
        forbidden_actions: list[str] = field(default_factory=list)
        approved_ids: list[str] = field(default_factory=list)
        denied_ids: list[str] = field(default_factory=list)
        mode: str = "fallback_only"
        hitl_input_history: list[str] = field(default_factory=list)
        hitl_confirmed: bool = False

    @dataclass
    class PolicyGateState:
        status: str = "not_checked"
        need_human: bool = False
        blocked_items: list[str] = field(default_factory=list)
        message: str = ""

    @dataclass
    class ReviewIssue:
        severity: str
        file: str
        location: str
        description: str
        suggested_fix: str
        code: str
        meta: dict[str, Any] = field(default_factory=dict)

    @dataclass
    class ImprovementProposal:
        title: str
        description: str
        motivation: str
        suggested_steps: list[str] = field(default_factory=list)
        affected_files: list[str] = field(default_factory=list)
        expected_benefit: str = ""
        risk_level: str = "low"

    @dataclass
    class ReviewResult:
        verdict: str = "reject"
        issues: list[ReviewIssue] = field(default_factory=list)
        rationale: str = ""
        improvement_proposals: list[ImprovementProposal] = field(default_factory=list)
        proposal_policy_hint: str = "optional"

    @dataclass
    class AggregationRules:
        if_any_blocker_reject: bool = True
        if_any_major_reject: bool = True
        allow_minor_only: bool = True

    @dataclass
    class AggregationConfig:
        policy: str = "consensus"
        rules: AggregationRules = field(default_factory=AggregationRules)

    @dataclass
    class ReviewBundleConfig:
        providers: list[str] = field(default_factory=lambda: ["codex"])
        roles: list[str] = field(default_factory=lambda: list(DEFAULT_REVIEW_ROLES))
        aggregation: AggregationConfig = field(default_factory=AggregationConfig)

    @dataclass
    class ProviderRun:
        provider: str
        role: str
        verdict: str
        issues: list[ReviewIssue] = field(default_factory=list)
        rationale: str = ""
        improvement_proposals: list[ImprovementProposal] = field(default_factory=list)
        proposal_policy_hint: str = "optional"
        raw: dict[str, Any] | None = None

    @dataclass
    class ReviewsState:
        provider_runs: list[ProviderRun] = field(default_factory=list)
        aggregation_conclusion: str = ""

    @dataclass
    class AlertEvent:
        type: str
        provider: str
        role: str | None = None
        message: str = ""
        ts: str = ""
        severity: str = "warn"

    @dataclass
    class AgentState:
        task: TaskSpec
        repo_root: str
        status: str = "running"
        stopped_reason: str = ""
        patch_applied: bool = False
        iter: int = 0
        max_iters: int = 5
        coder_inputs: list[dict[str, Any]] = field(default_factory=list)
        coder_runs: list[dict[str, Any]] = field(default_factory=list)
        test_plan: list[TestPlanItem] = field(default_factory=list)
        user_constraints: UserConstraints = field(default_factory=UserConstraints)
        policy_gate: PolicyGateState = field(default_factory=PolicyGateState)
        verification_history: list[VerificationResult] = field(default_factory=list)
        review_history: list[ReviewResult] = field(default_factory=list)
        latest_issues: list[ReviewIssue] = field(default_factory=list)
        latest_proposals: list[ImprovementProposal] = field(default_factory=list)
        review_bundle: ReviewBundleConfig = field(default_factory=ReviewBundleConfig)
        reviews: ReviewsState = field(default_factory=ReviewsState)
        provider_messages: list[str] = field(default_factory=list)
        alerts: list[AlertEvent] = field(default_factory=list)
        network_findings: list[dict[str, Any]] = field(default_factory=list)
        proposal_decisions: list[dict[str, Any]] = field(default_factory=list)
