"""Shared fixtures for the test suite.

The database is built once per session from the real source file rather than from a
fabricated fixture. Tests that run against synthetic data verify that the code behaves
as written, whereas these verify that it produces the right answer for the study Bob
Loblaw actually needs analysed, which is the property that matters.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

POPULATIONS = ("b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def source_frame() -> pd.DataFrame:
    """The raw CSV, read independently of any project code."""
    return pd.read_csv(REPO_ROOT / "data" / "cell-count.csv")


@pytest.fixture(scope="session")
def database(repo_root: Path) -> Path:
    """Build the database once, then hand its path to every test that needs it."""
    result = subprocess.run(
        [sys.executable, "load_data.py"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"load_data.py failed:\n{result.stderr}")

    database_path = repo_root / "cell-count.db"
    if not database_path.exists():
        pytest.fail("load_data.py reported success but no database was written")
    return database_path
