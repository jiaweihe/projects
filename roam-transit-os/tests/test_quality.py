import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed (pip install -e .[dev])")
def test_ruff_clean():
    r = subprocess.run(["ruff", "check", "roam", "tests", "--output-format", "concise"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-3000:]
