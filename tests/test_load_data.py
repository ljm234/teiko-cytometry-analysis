"""Tests for the loader: what it accepts, what it refuses, and what it writes."""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import POPULATIONS

HEADER = (
    "project,subject,condition,age,sex,treatment,response,sample,sample_type,"
    "time_from_treatment_start,b_cell,cd8_t_cell,cd4_t_cell,nk_cell,monocyte\n"
)
VALID_ROW = "prj1,sbj0,melanoma,50,M,miraclib,yes,smp0,PBMC,0,10,20,30,40,50"


def run_loader(directory: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "load_data.py"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def sandbox(tmp_path: Path, repo_root: Path) -> Path:
    """An isolated copy of the loader with a writable data directory."""
    for name in ("load_data.py", "schema.sql"):
        shutil.copy(repo_root / name, tmp_path / name)
    (tmp_path / "data").mkdir()
    return tmp_path


def write_csv(sandbox: Path, body: str) -> None:
    (sandbox / "data" / "cell-count.csv").write_text(HEADER + body, encoding="utf-8")


def test_loads_the_real_dataset(database: Path, source_frame) -> None:
    connection = sqlite3.connect(database)
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("project", "subject", "sample", "cell_population", "cell_count")
        }
    finally:
        connection.close()

    assert counts["sample"] == len(source_frame)
    assert counts["subject"] == source_frame["subject"].nunique()
    assert counts["project"] == source_frame["project"].nunique()
    assert counts["cell_population"] == len(POPULATIONS)
    assert counts["cell_count"] == len(source_frame) * len(POPULATIONS)


def test_every_cell_count_survives_the_load(database: Path, source_frame) -> None:
    """The total across the database must equal the total in the file, exactly."""
    connection = sqlite3.connect(database)
    try:
        loaded = connection.execute("SELECT SUM(count) FROM cell_count").fetchone()[0]
    finally:
        connection.close()
    assert loaded == int(source_frame[list(POPULATIONS)].sum().sum())


def test_response_is_null_only_for_untreated_healthy_subjects(database: Path) -> None:
    """A healthy volunteer given no treatment cannot have responded to anything."""
    connection = sqlite3.connect(database)
    try:
        misplaced = connection.execute(
            "SELECT COUNT(*) FROM subject WHERE response IS NULL "
            "AND NOT (condition = 'healthy' AND treatment = 'none')"
        ).fetchone()[0]
        null_count = connection.execute(
            "SELECT COUNT(*) FROM subject WHERE response IS NULL"
        ).fetchone()[0]
    finally:
        connection.close()

    assert misplaced == 0
    assert null_count > 0


def test_running_twice_leaves_the_same_database(sandbox: Path) -> None:
    write_csv(sandbox, VALID_ROW + "\n")
    first = run_loader(sandbox)
    assert first.returncode == 0

    checksum = (sandbox / "cell-count.db").read_bytes()
    second = run_loader(sandbox)
    assert second.returncode == 0
    assert first.stdout == second.stdout
    assert len((sandbox / "cell-count.db").read_bytes()) == len(checksum)


@pytest.mark.parametrize(
    ("description", "body", "expected_message"),
    [
        ("negative count", "prj1,s,melanoma,50,M,miraclib,yes,x,PBMC,0,-5,10,10,10,10", "negative count"),
        ("non integer count", "prj1,s,melanoma,50,M,miraclib,yes,x,PBMC,0,abc,10,10,10,10", "not an integer"),
        ("age above range", "prj1,s,melanoma,999,M,miraclib,yes,x,PBMC,0,10,10,10,10,10", "outside the plausible range"),
        ("negative age", "prj1,s,melanoma,-5,M,miraclib,yes,x,PBMC,0,10,10,10,10,10", "outside the plausible range"),
        ("unknown sex", "prj1,s,melanoma,50,X,miraclib,yes,x,PBMC,0,10,10,10,10,10", "sex must be one of"),
        ("unknown response", "prj1,s,melanoma,50,M,miraclib,maybe,x,PBMC,0,10,10,10,10,10", "response must be one of"),
        ("negative timepoint", "prj1,s,melanoma,50,M,miraclib,yes,x,PBMC,-3,10,10,10,10,10", "is negative"),
        ("empty project", ",s,melanoma,50,M,miraclib,yes,x,PBMC,0,10,10,10,10,10", "project is empty"),
        ("zero total", "prj1,s,melanoma,50,M,miraclib,yes,x,PBMC,0,0,0,0,0,0", "total count of zero"),
    ],
)
def test_invalid_rows_are_reported_with_the_offending_line(
    sandbox: Path, description: str, body: str, expected_message: str
) -> None:
    """Bad input must produce an actionable message, never a stack trace."""
    write_csv(sandbox, body + "\n")
    result = run_loader(sandbox)

    assert result.returncode == 1, description
    assert "Traceback" not in result.stderr, description
    assert expected_message in result.stderr, description
    assert "line 2" in result.stderr or "column layout" in result.stderr, description


def test_duplicate_sample_identifiers_are_refused(sandbox: Path) -> None:
    write_csv(sandbox, VALID_ROW + "\n" + VALID_ROW.replace(",0,10,", ",7,10,") + "\n")
    result = run_loader(sandbox)
    assert result.returncode == 1
    assert "duplicate sample" in result.stderr


def test_conflicting_subject_attributes_are_refused(sandbox: Path) -> None:
    """A subject cannot be male in one sample and female in the next."""
    second = "prj1,sbj0,melanoma,50,F,miraclib,yes,smp1,PBMC,7,10,20,30,40,50"
    write_csv(sandbox, VALID_ROW + "\n" + second + "\n")
    result = run_loader(sandbox)
    assert result.returncode == 1
    assert "conflicting attributes" in result.stderr


def test_missing_source_file_is_reported_clearly(sandbox: Path) -> None:
    result = run_loader(sandbox)
    assert result.returncode == 1
    assert "not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_schema_drops_strict_when_the_engine_is_too_old(repo_root: Path) -> None:
    """STRICT is stripped below SQLite 3.37 so the schema still loads.

    A recent Python can be linked against an older SQLite than the release date
    suggests, since the library version is fixed when the interpreter is compiled.
    Where STRICT cannot be used the constraints that actually protect the data, the
    foreign keys and the range checks, are unaffected.
    """
    schema_path = repo_root / "schema.sql"
    original = schema_path.read_text(encoding="utf-8")
    assert ") STRICT;" in original

    stripped = re.sub(r"\)\s*STRICT\s*;", ");", original)
    assert not re.search(r"\)\s*STRICT\s*;", stripped)
    assert "ON DELETE RESTRICT" in stripped, "RESTRICT must survive the substitution"
    assert stripped.count("CHECK") == original.count("CHECK")
    assert stripped.count("REFERENCES") == original.count("REFERENCES")

    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(stripped)
        tables = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert tables == 5


def test_healthy_subjects_without_response_load_successfully(sandbox: Path) -> None:
    """An empty response is legitimate for untreated controls and must be accepted."""
    write_csv(sandbox, "prj1,s,healthy,50,M,none,,x,PBMC,0,10,20,30,40,50\n")
    result = run_loader(sandbox)
    assert result.returncode == 0

    connection = sqlite3.connect(sandbox / "cell-count.db")
    try:
        stored = connection.execute("SELECT response FROM subject").fetchone()[0]
    finally:
        connection.close()
    assert stored is None
