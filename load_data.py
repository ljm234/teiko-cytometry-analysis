"""Initialise the SQLite database and load the cell count dataset.

Run from the repository root with no arguments:

    python load_data.py

The script is idempotent: it rebuilds the database from scratch on every run, so
repeated executions converge on the same state rather than accumulating rows.
"""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
CSV_PATH = REPO_ROOT / "data" / "cell-count.csv"
SCHEMA_PATH = REPO_ROOT / "schema.sql"
DB_PATH = REPO_ROOT / "cell-count.db"

POPULATIONS = {
    "b_cell": "B cell",
    "cd8_t_cell": "CD8+ T cell",
    "cd4_t_cell": "CD4+ T cell",
    "nk_cell": "NK cell",
    "monocyte": "Monocyte",
}

EXPECTED_COLUMNS = [
    "project",
    "subject",
    "condition",
    "age",
    "sex",
    "treatment",
    "response",
    "sample",
    "sample_type",
    "time_from_treatment_start",
    *POPULATIONS,
]


class DataValidationError(RuntimeError):
    """Raised when the source file violates an assumption the schema depends on."""


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        raise DataValidationError(f"source file not found: {csv_path}")

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            raise DataValidationError(
                "unexpected column layout\n"
                f"  expected: {EXPECTED_COLUMNS}\n"
                f"  found:    {reader.fieldnames}"
            )
        rows = list(reader)

    if not rows:
        raise DataValidationError("source file contains no data rows")
    return rows


def validate(rows: list[dict[str, str]]) -> None:
    """Check the invariants the normalised schema relies on.

    Subject level attributes are stored once per subject, which is only correct if
    they never conflict across that subject's samples. Validating here converts a
    silent data corruption into an explicit failure at load time.
    """
    seen_samples: set[str] = set()
    subject_attributes: dict[str, tuple[str, ...]] = {}
    invariant_fields = ("project", "condition", "age", "sex", "treatment", "response")

    for line_number, row in enumerate(rows, start=2):
        sample_id = row["sample"]
        if not sample_id:
            raise DataValidationError(f"line {line_number}: empty sample identifier")
        if sample_id in seen_samples:
            raise DataValidationError(f"line {line_number}: duplicate sample {sample_id}")
        seen_samples.add(sample_id)

        for column in POPULATIONS:
            value = row[column]
            if not value.lstrip("-").isdigit():
                raise DataValidationError(
                    f"line {line_number}: non integer count in {column}: {value!r}"
                )
            if int(value) < 0:
                raise DataValidationError(
                    f"line {line_number}: negative count in {column}: {value!r}"
                )

        if sum(int(row[column]) for column in POPULATIONS) == 0:
            raise DataValidationError(
                f"line {line_number}: sample {sample_id} has a total count of zero, "
                "so relative frequencies would be undefined"
            )

        attributes = tuple(row[field] for field in invariant_fields)
        subject_id = row["subject"]
        previous = subject_attributes.setdefault(subject_id, attributes)
        if previous != attributes:
            conflicts = [
                f"{field}: {before!r} then {after!r}"
                for field, before, after in zip(invariant_fields, previous, attributes)
                if before != after
            ]
            raise DataValidationError(
                f"line {line_number}: subject {subject_id} has conflicting attributes "
                f"({'; '.join(conflicts)})"
            )


def build_database(rows: list[dict[str, str]], db_path: Path, schema_path: Path) -> None:
    db_path.unlink(missing_ok=True)

    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(schema_path.read_text(encoding="utf-8"))
        connection.execute("PRAGMA foreign_keys = ON")

        connection.executemany(
            "INSERT INTO cell_population (population_id, display_name) VALUES (?, ?)",
            POPULATIONS.items(),
        )

        projects = {row["project"] for row in rows}
        connection.executemany(
            "INSERT INTO project (project_id, project_name) VALUES (?, ?)",
            sorted((project, project) for project in projects),
        )

        subjects: dict[str, tuple[str, str, str, int, str, str, str | None]] = {}
        for row in rows:
            subjects.setdefault(
                row["subject"],
                (
                    row["subject"],
                    row["project"],
                    row["condition"],
                    int(row["age"]),
                    row["sex"],
                    row["treatment"],
                    row["response"] or None,
                ),
            )
        connection.executemany(
            "INSERT INTO subject "
            "(subject_id, project_id, condition, age, sex, treatment, response) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            subjects.values(),
        )

        connection.executemany(
            "INSERT INTO sample "
            "(sample_id, subject_id, sample_type, time_from_treatment_start) "
            "VALUES (?, ?, ?, ?)",
            (
                (
                    row["sample"],
                    row["subject"],
                    row["sample_type"],
                    int(row["time_from_treatment_start"]),
                )
                for row in rows
            ),
        )

        connection.executemany(
            "INSERT INTO cell_count (sample_id, population_id, count) VALUES (?, ?, ?)",
            (
                (row["sample"], population, int(row[population]))
                for row in rows
                for population in POPULATIONS
            ),
        )

        connection.commit()
    finally:
        connection.close()


def verify(db_path: Path, rows: list[dict[str, str]]) -> dict[str, int]:
    """Read the database back and confirm it matches the source file."""
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise DataValidationError(f"foreign key violations detected: {violations}")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise DataValidationError(f"integrity check failed: {integrity}")

        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("project", "subject", "sample", "cell_population", "cell_count")
        }

        expected_samples = len(rows)
        expected_subjects = len({row["subject"] for row in rows})
        expected_counts = expected_samples * len(POPULATIONS)

        if counts["sample"] != expected_samples:
            raise DataValidationError(
                f"sample count mismatch: {counts['sample']} loaded, "
                f"{expected_samples} in source"
            )
        if counts["subject"] != expected_subjects:
            raise DataValidationError(
                f"subject count mismatch: {counts['subject']} loaded, "
                f"{expected_subjects} in source"
            )
        if counts["cell_count"] != expected_counts:
            raise DataValidationError(
                f"cell count mismatch: {counts['cell_count']} loaded, "
                f"{expected_counts} expected"
            )

        source_total = sum(
            int(row[population]) for row in rows for population in POPULATIONS
        )
        loaded_total = connection.execute("SELECT SUM(count) FROM cell_count").fetchone()[0]
        if loaded_total != source_total:
            raise DataValidationError(
                f"cell total mismatch: {loaded_total} loaded, {source_total} in source"
            )

        off_by_more_than_tolerance = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT sample, SUM(percentage) AS total
                FROM sample_population_frequency
                GROUP BY sample
                HAVING ABS(total - 100.0) > 1e-9
            )
            """
        ).fetchone()[0]
        if off_by_more_than_tolerance:
            raise DataValidationError(
                f"{off_by_more_than_tolerance} samples have frequencies that do not "
                "sum to 100 percent"
            )

        return counts
    finally:
        connection.close()


def main() -> int:
    try:
        rows = read_rows(CSV_PATH)
        validate(rows)
        build_database(rows, DB_PATH, SCHEMA_PATH)
        counts = verify(DB_PATH, rows)
    except DataValidationError as error:
        print(f"load failed: {error}", file=sys.stderr)
        return 1

    print(f"database written to {DB_PATH.name}")
    for table, value in counts.items():
        print(f"  {table}: {value} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
