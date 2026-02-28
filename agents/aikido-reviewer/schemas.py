"""Pydantic models for aikido findings input and review output."""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input models — aikido.findings.v1
# ---------------------------------------------------------------------------

class FindingLocation(BaseModel):
    path: str
    byte_start: int
    byte_end: int
    line_start: Optional[int] = None
    column_start: Optional[int] = None
    line_end: Optional[int] = None
    column_end: Optional[int] = None


class CwcInfo(BaseModel):
    id: str
    name: str
    severity: str


class EvidenceInfo(BaseModel):
    level: str  # PatternMatch | PathVerified | SmtProven | SimulationConfirmed | Corroborated
    method: str
    details: Optional[str] = None
    code_flow: List[Dict[str, Any]] = Field(default_factory=list)
    witness: Optional[Dict[str, Any]] = None
    confidence_boost: float = 0.0


class AikidoFinding(BaseModel):
    detector: str
    reliability_tier: str = "stable"  # stable | beta | experimental
    severity: str  # critical | high | medium | low | info
    confidence: str  # definite | likely | possible
    title: str
    description: str
    module: str
    cwc: Optional[CwcInfo] = None
    location: Optional[FindingLocation] = None
    suggestion: Optional[str] = None
    related_findings: List[str] = Field(default_factory=list)
    semantic_group: Optional[str] = None
    evidence: Optional[EvidenceInfo] = None


class AnalysisLaneInfo(BaseModel):
    enabled: bool = False
    count: Optional[int] = None
    runtime_integrated: bool = False
    backend: Optional[str] = None
    context_builder_command_configured: Optional[bool] = None
    corroborated_findings: Optional[int] = None
    status: Optional[str] = None
    note: Optional[str] = None


class AikidoReport(BaseModel):
    schema_version: str = "aikido.findings.v1"
    project: str
    version: str = "0.0.0"
    analysis_lanes: Dict[str, AnalysisLaneInfo] = Field(default_factory=dict)
    findings: List[AikidoFinding] = Field(default_factory=list)
    total: int


# ---------------------------------------------------------------------------
# Output models — aikido.review.v1
# ---------------------------------------------------------------------------

class Classification(str, Enum):
    CONFIRMED_TP = "confirmed_tp"
    LIKELY_TP = "likely_tp"
    NEEDS_REVIEW = "needs_review"
    LIKELY_FP = "likely_fp"
    CONFIRMED_FP = "confirmed_fp"


class RemediationPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class FindingReview(BaseModel):
    finding_index: int
    detector: str
    title: str
    original_severity: str
    original_confidence: str
    classification: Classification
    reviewer_confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    mitigating_patterns: List[str] = Field(default_factory=list)
    exploitation_scenario: Optional[str] = None
    remediation_priority: RemediationPriority
    evidence_assessment: Optional[str] = None


class ClassificationSummary(BaseModel):
    confirmed_tp: int = 0
    likely_tp: int = 0
    needs_review: int = 0
    likely_fp: int = 0
    confirmed_fp: int = 0


class ReviewReport(BaseModel):
    schema_version: str = "aikido.review.v1"
    project: str
    aikido_version: str = "aikido.findings.v1"
    review_depth: str  # deep
    total_findings: int
    classification_summary: ClassificationSummary
    risk_score: float = Field(ge=0.0, le=10.0)
    risk_level: str  # critical | high | medium | low | minimal
    executive_summary: str
    finding_reviews: List[FindingReview] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
