"""Shared database access helpers.

Every analysis module reads through this module so that the connection settings,
in particular foreign key enforcement, are applied consistently.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = REPO_ROOT / "cell-count.db"
OUTPUT_TABLES = REPO_ROOT / "outputs" / "tables"
OUTPUT_FIGURES = REPO_ROOT / "outputs" / "figures"

POPULATIONS = ("b_cell", "cd8_t_cell", "cd4_t_cell", "nk_cell", "monocyte")

POPULATION_LABELS = {
    "b_cell": "B cell",
    "cd8_t_cell": "CD8+ T cell",
    "cd4_t_cell": "CD4+ T cell",
    "nk_cell": "NK cell",
    "monocyte": "Monocyte",
}


class DatabaseNotFoundError(RuntimeError):
    """Raised when the database has not been built yet."""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise DatabaseNotFoundError(
            f"{db_path.name} not found. Run 'python load_data.py' first."
        )
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def query(sql: str, params: tuple = (), db_path: Path = DB_PATH) -> pd.DataFrame:
    connection = connect(db_path)
    try:
        return pd.read_sql_query(sql, connection, params=params)
    finally:
        connection.close()


def ensure_output_directories() -> None:
    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    OUTPUT_FIGURES.mkdir(parents=True, exist_ok=True)
