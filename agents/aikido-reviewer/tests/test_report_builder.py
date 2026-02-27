"""Tests for report_builder module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import Classification, FindingReview, RemediationPriority
from report_builder import (
    build_classification_summary,
    build_executive_summary,
    build_recommendations,
    build_report,
    compute_risk_score,
    risk_level,
)


def _make_review(
    index: int = 0,
    classification: Classification = Classification.NEEDS_REVIEW,
    severity: str = "high",
    confidence: float = 0.5,
    detector: str = "test-detector",
    priority: RemediationPriority = RemediationPriority.HIGH,
) -> FindingReview:
    return FindingReview(
        finding_index=index,
        detector=detector,
        title=f"Test finding {index}",
        original_severity=severity,
        original_confidence="likely",
        classification=classification,
        reviewer_confidence=confidence,
        reasoning="Test reasoning",
        remediation_priority=priority,
    )


class TestClassificationSummary:
    def test_empty(self):
        summary = build_classification_summary([])
        assert summary.confirmed_tp == 0
        assert summary.likely_fp == 0

    def test_counts_each_type(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_TP),
            _make_review(1, Classification.CONFIRMED_TP),
            _make_review(2, Classification.LIKELY_TP),
            _make_review(3, Classification.NEEDS_REVIEW),
            _make_review(4, Classification.LIKELY_FP),
            _make_review(5, Classification.CONFIRMED_FP),
            _make_review(6, Classification.CONFIRMED_FP),
        ]
        summary = build_classification_summary(reviews)
        assert summary.confirmed_tp == 2
        assert summary.likely_tp == 1
        assert summary.needs_review == 1
        assert summary.likely_fp == 1
        assert summary.confirmed_fp == 2


class TestRiskScore:
    def test_all_confirmed_tp_critical(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_TP, severity="critical"),
            _make_review(1, Classification.CONFIRMED_TP, severity="critical"),
        ]
        score = compute_risk_score(reviews)
        assert score == 10.0

    def test_all_confirmed_fp(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_FP, severity="critical"),
            _make_review(1, Classification.CONFIRMED_FP, severity="high"),
        ]
        score = compute_risk_score(reviews)
        assert score == 0.0

    def test_mixed_findings(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_TP, severity="high"),
            _make_review(1, Classification.CONFIRMED_FP, severity="high"),
        ]
        score = compute_risk_score(reviews)
        # 1 TP at weight 7, 1 FP at weight 7 → 7/14 * 10 = 5.0
        assert score == 5.0

    def test_empty(self):
        assert compute_risk_score([]) == 0.0

    def test_needs_review_contributes_partial(self):
        reviews = [
            _make_review(0, Classification.NEEDS_REVIEW, severity="high"),
        ]
        score = compute_risk_score(reviews)
        # weight 7, contribution 7*0.4 = 2.8, max 7, score = 2.8/7*10 = 4.0
        assert score == 4.0


class TestRiskLevel:
    def test_levels(self):
        assert risk_level(9.0) == "critical"
        assert risk_level(8.0) == "critical"
        assert risk_level(7.0) == "high"
        assert risk_level(6.0) == "high"
        assert risk_level(5.0) == "medium"
        assert risk_level(3.0) == "low"
        assert risk_level(1.0) == "minimal"
        assert risk_level(0.0) == "minimal"


class TestExecutiveSummary:
    def test_includes_totals(self):
        summary = build_classification_summary([
            _make_review(0, Classification.CONFIRMED_TP),
            _make_review(1, Classification.CONFIRMED_FP),
        ])
        text = build_executive_summary(summary, 5.0, 2)
        assert "2 findings" in text
        assert "1 finding(s) classified as true" in text
        assert "1 finding(s) classified as false" in text

    def test_includes_risk_level(self):
        summary = build_classification_summary([])
        text = build_executive_summary(summary, 8.5, 0)
        assert "critical" in text


class TestRecommendations:
    def test_actionable_from_tps(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_TP, priority=RemediationPriority.CRITICAL),
            _make_review(1, Classification.CONFIRMED_FP, priority=RemediationPriority.HIGH),
        ]
        recs = build_recommendations(reviews)
        assert len(recs) == 1
        assert "CRITICAL" in recs[0]

    def test_no_tps_gives_positive_message(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_FP),
        ]
        recs = build_recommendations(reviews)
        assert any("No critical issues" in r for r in recs)

    def test_sorted_by_priority(self):
        reviews = [
            _make_review(0, Classification.LIKELY_TP, priority=RemediationPriority.LOW),
            _make_review(1, Classification.CONFIRMED_TP, priority=RemediationPriority.CRITICAL),
        ]
        recs = build_recommendations(reviews)
        assert recs[0].startswith("[CRITICAL]")
        assert recs[1].startswith("[LOW]")


class TestBuildReport:
    def test_full_report(self):
        reviews = [
            _make_review(0, Classification.CONFIRMED_TP, severity="high"),
            _make_review(1, Classification.LIKELY_FP, severity="medium"),
            _make_review(2, Classification.CONFIRMED_FP, severity="info"),
        ]
        report = build_report("test-project", reviews, "standard")
        assert report.schema_version == "aikido.review.v1"
        assert report.project == "test-project"
        assert report.review_depth == "standard"
        assert report.total_findings == 3
        assert report.classification_summary.confirmed_tp == 1
        assert report.risk_score > 0.0
        assert len(report.finding_reviews) == 3
        assert len(report.recommendations) >= 1
