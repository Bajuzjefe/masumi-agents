"""Tests for the analyzer module — heuristic classification."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from schemas import AikidoFinding, Classification, EvidenceInfo, RemediationPriority
from analyzer import heuristic_classify


def _make_finding(**kwargs) -> AikidoFinding:
    defaults = {
        "detector": "test-detector",
        "severity": "high",
        "confidence": "likely",
        "title": "Test finding",
        "description": "Test description",
        "module": "test",
    }
    defaults.update(kwargs)
    return AikidoFinding(**defaults)


class TestHeuristicClassification:
    def test_info_severity_is_likely_fp(self):
        finding = _make_finding(severity="info", confidence="possible")
        review = heuristic_classify(finding)
        assert review.classification == Classification.LIKELY_FP

    def test_missing_min_ada_is_confirmed_fp(self):
        finding = _make_finding(
            detector="missing-min-ada-check",
            severity="info",
            confidence="possible",
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.CONFIRMED_FP
        assert "missing-min-ada-check" in review.reasoning

    def test_dead_code_is_confirmed_fp(self):
        finding = _make_finding(
            detector="dead-code-path",
            severity="info",
            confidence="possible",
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.CONFIRMED_FP

    def test_unused_import_is_confirmed_fp(self):
        finding = _make_finding(
            detector="unused-import",
            severity="info",
            confidence="possible",
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.CONFIRMED_FP

    def test_corroborated_definite_critical_is_confirmed_tp(self):
        finding = _make_finding(
            severity="critical",
            confidence="definite",
            evidence=EvidenceInfo(
                level="Corroborated",
                method="smt+simulation",
                confidence_boost=1.0,
            ),
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.CONFIRMED_TP
        assert review.reviewer_confidence >= 0.85

    def test_corroborated_definite_high_is_confirmed_tp(self):
        finding = _make_finding(
            severity="high",
            confidence="definite",
            evidence=EvidenceInfo(
                level="Corroborated",
                method="smt+simulation",
                confidence_boost=1.0,
            ),
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.CONFIRMED_TP

    def test_simulation_rejection_is_likely_fp(self):
        finding = _make_finding(
            severity="high",
            confidence="definite",
            evidence=EvidenceInfo(
                level="Corroborated",
                method="tx-simulation-rejected",
                details="Exploit rejected",
                witness={
                    "rejection_error": "UPLC evaluation failed: DeserialisationError"
                },
                confidence_boost=1.0,
            ),
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.LIKELY_FP
        assert "rejected" in review.reasoning.lower()

    def test_pattern_match_possible_is_likely_fp(self):
        finding = _make_finding(
            severity="medium",
            confidence="possible",
            evidence=EvidenceInfo(
                level="PatternMatch",
                method="static-pattern",
                confidence_boost=0.0,
            ),
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.LIKELY_FP

    def test_experimental_detector_defaults_to_likely_fp(self):
        finding = _make_finding(
            reliability_tier="experimental",
            severity="medium",
            confidence="possible",
        )
        review = heuristic_classify(finding)
        assert review.classification == Classification.LIKELY_FP

    def test_high_severity_likely_no_evidence_is_needs_review(self):
        finding = _make_finding(severity="high", confidence="likely")
        review = heuristic_classify(finding)
        assert review.classification == Classification.NEEDS_REVIEW

    def test_remediation_priority_matches_severity(self):
        for sev, expected in [
            ("critical", RemediationPriority.CRITICAL),
            ("high", RemediationPriority.HIGH),
            ("medium", RemediationPriority.MEDIUM),
            ("low", RemediationPriority.LOW),
            ("info", RemediationPriority.INFORMATIONAL),
        ]:
            finding = _make_finding(severity=sev)
            review = heuristic_classify(finding)
            assert review.remediation_priority == expected

    def test_smt_inconclusive_noted_in_reasoning(self):
        finding = _make_finding(
            severity="high",
            confidence="likely",
            evidence=EvidenceInfo(
                level="PatternMatch",
                method="smt-simple-solver",
                details="SMT inconclusive: beyond solver capability",
                confidence_boost=0.0,
            ),
        )
        review = heuristic_classify(finding)
        assert "inconclusive" in review.reasoning.lower()

    def test_mitigating_patterns_for_min_ada(self):
        finding = _make_finding(
            detector="missing-min-ada-check",
            severity="info",
            confidence="possible",
        )
        review = heuristic_classify(finding)
        assert any("protocol" in p.lower() for p in review.mitigating_patterns)
