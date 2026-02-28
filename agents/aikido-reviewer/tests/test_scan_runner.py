"""Tests for auto-scan Aikido CLI runner."""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scan_runner import contains_aiken_toml, run_aikido_scan_from_source_files
from scan_runner import run_aikido_scan_from_repo


def test_contains_aiken_toml_root_and_nested():
    assert contains_aiken_toml({"aiken.toml": "name='demo'"})
    assert contains_aiken_toml({"contracts/aiken.toml": "name='demo'"})
    assert not contains_aiken_toml({"validators/main.ak": "validator main { spend(_,_,_) { True } }"})


def test_run_scan_requires_aiken_toml():
    with pytest.raises(ValueError, match="aiken.toml"):
        run_aikido_scan_from_source_files(
            {"validators/main.ak": "validator main { spend(_,_,_) { True } }"}
        )


def test_run_scan_success_parses_json(monkeypatch):
    source_files = {
        "aiken.toml": "name = 'demo'\nversion = '0.0.0'",
        "validators/main.ak": "validator main { spend(_,_,_) { True } }",
    }

    payload = {
        "schema_version": "aikido.findings.v1",
        "project": "demo",
        "version": "0.0.0",
        "analysis_lanes": {},
        "findings": [],
        "total": 0,
    }

    def fake_run(cmd, capture_output, text, timeout, check):
        assert "--format" in cmd
        assert "json" in cmd
        return subprocess.CompletedProcess(cmd, 2, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("scan_runner.subprocess.run", fake_run)

    report, normalized = run_aikido_scan_from_source_files(source_files)
    assert report["schema_version"] == "aikido.findings.v1"
    assert report["total"] == 0
    assert "aiken.toml" in normalized
    assert "validators/main.ak" in normalized


def test_run_scan_fails_on_invalid_json(monkeypatch):
    source_files = {
        "aiken.toml": "name = 'demo'\nversion = '0.0.0'",
        "validators/main.ak": "validator main { spend(_,_,_) { True } }",
    }

    def fake_run(cmd, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(cmd, 0, stdout="not-json", stderr="bad output")

    monkeypatch.setattr("scan_runner.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="JSON output parse failed"):
        run_aikido_scan_from_source_files(source_files)


def test_run_repo_scan_rejects_non_https():
    with pytest.raises(ValueError, match="https"):
        run_aikido_scan_from_repo("git@github.com:org/repo.git")


def test_run_repo_scan_rejects_disallowed_host():
    with pytest.raises(ValueError, match="not allowed"):
        run_aikido_scan_from_repo("https://example.com/org/repo")


def test_run_repo_scan_success(monkeypatch):
    payload = {
        "schema_version": "aikido.findings.v1",
        "project": "demo",
        "version": "0.0.0",
        "analysis_lanes": {},
        "findings": [],
        "total": 0,
    }

    def fake_run(cmd, capture_output, text, timeout, check):
        # clone call
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "clone":
            repo_dir = cmd[-1]
            os.makedirs(repo_dir, exist_ok=True)
            with open(os.path.join(repo_dir, "aiken.toml"), "w", encoding="utf-8") as f:
                f.write("name = 'demo'\nversion = '0.0.0'")
            os.makedirs(os.path.join(repo_dir, "validators"), exist_ok=True)
            with open(os.path.join(repo_dir, "validators", "main.ak"), "w", encoding="utf-8") as f:
                f.write("validator main { spend(_,_,_) { True } }")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        # aikido scan call
        return subprocess.CompletedProcess(cmd, 2, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr("scan_runner.subprocess.run", fake_run)

    report, source_files = run_aikido_scan_from_repo("https://github.com/org/repo")
    assert report["schema_version"] == "aikido.findings.v1"
    assert "aiken.toml" in source_files
    assert "validators/main.ak" in source_files
