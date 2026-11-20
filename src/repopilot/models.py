from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["pass", "fail", "unknown", "skip"]
Severity = Literal["info", "low", "medium", "high", "critical"]


class Evidence(BaseModel):
    path: str
    detail: str


class Finding(BaseModel):
    rule_id: str
    status: Status
    severity: Severity
    message: str
    recommendation: str
    evidence: list[Evidence] = Field(default_factory=list)


class Score(BaseModel):
    score: float | None = Field(ge=0, le=100)
    coverage: float | None = Field(ge=0, le=100)
    evaluated_weight: int = Field(ge=0)
    applicable_weight: int = Field(ge=0)


class ScanReport(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    repository: str
    is_git_repository: bool
    findings: list[Finding] = Field(default_factory=list)
    summary: Score | None = None


class PlanTask(BaseModel):
    rule_id: str
    title: str
    severity: Severity
    acceptance_criteria: list[str]
