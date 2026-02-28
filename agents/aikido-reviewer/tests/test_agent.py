"""Tests for agent pipeline orchestration behavior."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import agent


@pytest.mark.asyncio
async def test_process_job_forces_deep_review_depth(monkeypatch):
    captured = {}

    async def fake_analyze_findings(findings, source_files, depth, anthropic_credential=None):
        captured["depth"] = depth
        return []

    monkeypatch.setattr(agent, "analyze_findings", fake_analyze_findings)

    aikido_report = {
        "schema_version": "aikido.findings.v1",
        "project": "demo",
        "version": "0.0.0",
        "analysis_lanes": {},
        "findings": [],
        "total": 0,
    }

    result = await agent.process_job_async(
        {
            "aikido_report": json.dumps(aikido_report),
            "source_files": "{}",
            "review_depth": "quick",
        }
    )

    assert captured["depth"] == "deep"
    assert result["review_depth"] == "deep"
