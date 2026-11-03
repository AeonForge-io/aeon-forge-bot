"""The lint check's baseline ratchet and its tool-output handling."""

import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_lint.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_lint", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_lint = load_script()


def test_count_above_baseline_is_new() -> None:
    current = Counter({"a.py::S108": 3})
    assert check_lint.new_findings(current, {"a.py::S108": 2}) == [
        "a.py::S108: 3 found, baseline 2"
    ]


def test_count_at_or_below_baseline_is_not_new() -> None:
    current = Counter({"a.py::S108": 2, "b.py::E501": 1})
    assert check_lint.new_findings(current, {"a.py::S108": 2, "b.py::E501": 5}) == []


def test_unbaselined_pair_is_new() -> None:
    assert check_lint.new_findings(Counter({"c.py::F401": 1}), {}) == [
        "c.py::F401: 1 found, baseline 0"
    ]


def test_ruff_counts_group_by_file_and_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    out = json.dumps(
        [
            {"filename": "app/a.py", "code": "S108"},
            {"filename": "app/a.py", "code": "S108"},
            {"filename": "app/a.py", "code": "E501"},
        ]
    )
    done = check_lint.subprocess.CompletedProcess([], 0, out, "")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    assert check_lint.ruff_counts() == {"app/a.py::S108": 2, "app/a.py::E501": 1}


def test_ruff_warning_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    done = check_lint.subprocess.CompletedProcess([], 0, "[]", "warning: deprecated")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    with pytest.raises(check_lint.ToolFailedError):
        check_lint.ruff_counts()


def test_mypy_counts_only_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        {"file": "app/a.py", "severity": "error", "code": "arg-type"},
        {"file": "app/a.py", "severity": "note", "code": "arg-type"},
        {"file": "app/a.py", "severity": "error", "code": "arg-type"},
    ]
    done = check_lint.subprocess.CompletedProcess(
        [], 1, "\n".join(json.dumps(x) for x in lines), ""
    )
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    assert check_lint.mypy_counts() == {"app/a.py::arg-type": 2}


def test_mypy_crash_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    done = check_lint.subprocess.CompletedProcess([], 2, "", "boom")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    with pytest.raises(check_lint.ToolFailedError):
        check_lint.mypy_counts()


def test_sqlfluff_counts_group_by_file_and_rule(monkeypatch: pytest.MonkeyPatch) -> None:
    out = json.dumps(
        [{"filepath": "migrations/001_x.sql", "violations": [{"code": "LT01"}, {"code": "LT01"}]}]
    )
    done = check_lint.subprocess.CompletedProcess([], 1, out, "")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    assert check_lint.sqlfluff_counts() == {"migrations/001_x.sql::LT01": 2}


def test_pip_audit_skipped_package_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    out = json.dumps({"dependencies": [{"name": "x", "version": "1", "skip_reason": "not found"}]})
    done = check_lint.subprocess.CompletedProcess([], 0, out, "")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    monkeypatch.setattr(check_lint, "locked_requirements", lambda: Path("req.txt"))
    with pytest.raises(check_lint.ToolFailedError):
        check_lint.audit_findings()


def test_pip_audit_reports_advisories(monkeypatch: pytest.MonkeyPatch) -> None:
    out = json.dumps(
        {"dependencies": [{"name": "x", "version": "1", "vulns": [{"id": "PYSEC-1"}]}]}
    )
    done = check_lint.subprocess.CompletedProcess([], 1, out, "")
    monkeypatch.setattr(check_lint, "run", lambda _cmd: done)
    monkeypatch.setattr(check_lint, "locked_requirements", lambda: Path("req.txt"))
    assert check_lint.audit_findings() == ["x 1: PYSEC-1"]


def test_main_exit_codes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"a.py::S108": 1}))
    monkeypatch.setattr(check_lint, "BASELINE", baseline)
    monkeypatch.setattr(check_lint, "mypy_counts", Counter)
    monkeypatch.setattr(check_lint, "sqlfluff_counts", Counter)
    monkeypatch.setattr(check_lint, "secret_findings", list)
    monkeypatch.setattr(check_lint, "audit_findings", list)
    monkeypatch.setattr(check_lint.sys, "argv", ["check_lint.py"])

    monkeypatch.setattr(check_lint, "ruff_counts", lambda: Counter({"a.py::S108": 1}))
    assert check_lint.main() == 0
    monkeypatch.setattr(check_lint, "ruff_counts", lambda: Counter({"a.py::S108": 2}))
    assert check_lint.main() == 1

    def broken() -> Counter[str]:
        raise check_lint.ToolFailedError("no tool")

    monkeypatch.setattr(check_lint, "ruff_counts", broken)
    assert check_lint.main() == 2
