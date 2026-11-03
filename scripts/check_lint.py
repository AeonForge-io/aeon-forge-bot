"""Lint app/, tests/, scripts/ and migrations/ against a baseline; scan for secrets and audit dependencies.

Usage: scripts/check.sh lint            non-zero on any new finding.
       scripts/check.sh lint --update   rewrite scripts/lint_baseline.json

Runs ruff check (the rules in pyproject.toml), mypy strict and `sqlfluff lint --dialect postgres migrations/`.
The baseline holds a count per (file, rule): a ruff code, a mypy error code or a sqlfluff rule. A file may
keep its old count of a rule but not exceed it. Fixing findings lowers nothing automatically: run --update to
ratchet the baseline down. The baseline may only go down, unless the commit message says why it went up.
Ruff warnings fail the check.

Then detect-secrets scans every file `git ls-files --cached --others --exclude-standard` lists, and pip-audit
checks the requirements exported from uv.lock. Both fail on any finding, with no baseline.

pip-audit looks advisories up on pypi.org and caches them under ~/.cache/pip-audit, so the sandbox needs
network access to pypi.org and a writable ~/.cache. If the lookup fails the check stops with exit 2 and the
reason; it never passes without advisory data. Fix an advisory with `uv lock --upgrade-package NAME`.
A tool that cannot run also stops the check with exit 2.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "lint_baseline.json"
TARGETS = ["app", "tests", "scripts"]
SCRATCH = Path.home() / ".cache" / "aeon-forge-bot"
AUDIT_CACHE = Path.home() / ".cache" / "pip-audit"


class ToolFailedError(Exception):
    """A tool did not run or produced output that cannot be read."""


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)  # noqa: S603 - fixed argv


def python_tool(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def relative(path: str) -> str:
    return str(Path(path).relative_to(ROOT)) if Path(path).is_absolute() else path


def parse_json(tool: str, text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise ToolFailedError(f"{tool} output is not JSON: {error}") from error


def ruff_counts() -> Counter[str]:
    result = run(python_tool("ruff", "check", *TARGETS, "--output-format", "json", "--exit-zero"))
    if result.returncode or not result.stdout.strip():
        raise ToolFailedError(
            f"ruff check did not run (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )
    if "warning" in result.stderr.lower():
        raise ToolFailedError(f"ruff warned:\n{result.stderr}")
    findings = parse_json("ruff", result.stdout)
    assert isinstance(findings, list)
    return Counter(f"{relative(f['filename'])}::{f['code']}" for f in findings)


def mypy_counts() -> Counter[str]:
    result = run(python_tool("mypy", "-O", "json", *TARGETS))
    # mypy exits 1 when it reports errors; anything else non-zero, or exit 1 with nothing on stdout, is a crash.
    if result.returncode not in (0, 1) or (result.returncode == 1 and not result.stdout.strip()):
        raise ToolFailedError(
            f"mypy did not run (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )
    counts: Counter[str] = Counter()
    for line in filter(str.strip, result.stdout.splitlines()):
        diagnostic = parse_json("mypy", line)
        assert isinstance(diagnostic, dict)
        if diagnostic["severity"] == "error":
            counts[f"{relative(diagnostic['file'])}::{diagnostic['code']}"] += 1
    return counts


def sqlfluff_counts() -> Counter[str]:
    result = run(
        python_tool("sqlfluff", "lint", "--dialect", "postgres", "--format", "json", "migrations")
    )
    # sqlfluff exits 1 when it reports violations; anything else non-zero, or no report, is a crash.
    if result.returncode not in (0, 1) or not result.stdout.strip():
        raise ToolFailedError(
            f"sqlfluff did not run (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )
    files = parse_json("sqlfluff", result.stdout)
    assert isinstance(files, list)
    return Counter(
        f"{relative(file['filepath'])}::{violation['code']}"
        for file in files
        for violation in file["violations"]
    )


def listed_files() -> list[str]:
    """Every file git tracks or would add (not ignored) that exists in the worktree."""
    result = run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    if result.returncode:
        raise ToolFailedError(f"git ls-files failed (exit {result.returncode}):\n{result.stderr}")
    return [name for name in result.stdout.split("\0") if name and (ROOT / name).is_file()]


def secret_findings() -> list[str]:
    """A "file:line type" per suspected secret; the secret itself is never printed."""
    result = run(python_tool("detect_secrets", "scan", *listed_files()))
    if result.returncode:
        raise ToolFailedError(
            f"detect-secrets did not run (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )
    report = parse_json("detect-secrets", result.stdout)
    assert isinstance(report, dict)
    return [
        f"{name}:{hit['line_number']} {hit['type']}"
        for name, hits in sorted(report["results"].items())
        for hit in hits
    ]


def locked_requirements() -> Path:
    """The locked third-party packages, written under ~/.cache."""
    result = run(["uv", "export", "--locked", "--no-emit-project", "--no-hashes", "--quiet"])
    if result.returncode:
        raise ToolFailedError(f"uv export did not run (exit {result.returncode}):\n{result.stderr}")
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / "locked-requirements.txt"
    path.write_text(result.stdout)
    return path


def audit_findings() -> list[str]:
    """A "name version: advisory id" per known advisory against a locked package."""
    result = run(
        python_tool(
            "pip_audit",
            "--requirement",
            str(locked_requirements()),
            "--no-deps",
            "--disable-pip",
            "--cache-dir",
            str(AUDIT_CACHE),
            "--format",
            "json",
        )
    )
    # pip-audit exits 1 when it finds advisories; with no report on stdout, exit 1 is a failed lookup.
    if result.returncode not in (0, 1) or not result.stdout.strip():
        raise ToolFailedError(
            f"pip-audit did not run (exit {result.returncode}):\n{result.stderr}{result.stdout}"
        )
    report = parse_json("pip-audit", result.stdout)
    assert isinstance(report, dict)
    dependencies = report["dependencies"]
    skipped = [
        f"{dependency['name']} {dependency.get('version', '?')}: {dependency.get('skip_reason', 'no vulns reported')}"
        for dependency in dependencies
        if "vulns" not in dependency
    ]
    if skipped:
        raise ToolFailedError("pip-audit did not audit these packages:\n  " + "\n  ".join(skipped))
    return sorted(
        {
            f"{dependency['name']} {dependency['version']}: {vuln['id']}"
            for dependency in dependencies
            for vuln in dependency["vulns"]
        }
    )


def new_findings(current: Counter[str], baseline: dict[str, int]) -> list[str]:
    return [
        f"{key}: {count} found, baseline {baseline.get(key, 0)}"
        for key, count in sorted(current.items())
        if count > baseline.get(key, 0)
    ]


def main() -> int:
    try:
        current = ruff_counts() + mypy_counts() + sqlfluff_counts()
        secrets = secret_findings()
        advisories = audit_findings()
    except ToolFailedError as error:
        print(error, file=sys.stderr)
        return 2
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(dict(sorted(current.items())), indent=1) + "\n")
        print(
            f"baseline written: {sum(current.values())} findings in {len(current)} (file, rule) entries"
        )
        return 0
    new = new_findings(current, json.loads(BASELINE.read_text()))
    if new:
        print("new findings over the baseline:\n  " + "\n  ".join(new))
    if secrets:
        print("suspected secrets:\n  " + "\n  ".join(secrets))
    if advisories:
        print("locked dependencies with known advisories:\n  " + "\n  ".join(advisories))
    if new or secrets or advisories:
        return 1
    print(f"lint: ok ({sum(current.values())} baselined findings, none new)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
