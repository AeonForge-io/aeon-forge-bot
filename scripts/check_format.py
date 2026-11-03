"""Check that app/, tests/ and scripts/ are formatted.

Usage: scripts/check.sh format    non-zero if any file would change; there is no baseline.

To fix: `uv run ruff format app tests scripts`.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "ruff", "format", "--check", "app", "tests", "scripts"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print(f"not formatted (exit {result.returncode}):\n{result.stdout}{result.stderr}")
        return 1
    print("format: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
