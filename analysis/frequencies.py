"""Part 2: relative frequency of each cell population within each sample.

For every sample the total cell count is the sum across the five measured
populations, and the relative frequency of a population is its share of that total
expressed as a percentage.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from analysis.database import OUTPUT_TABLES, ensure_output_directories, query

FREQUENCY_SQL = """
SELECT
    sample,
    total_count,
    population,
    count,
    percentage
FROM sample_population_frequency
ORDER BY sample, population
"""


def compute_frequencies() -> pd.DataFrame:
    """Return one row per sample and population with counts and percentages."""
    frequencies = query(FREQUENCY_SQL)

    totals = frequencies.groupby("sample")["percentage"].sum()
    largest_deviation = (totals - 100.0).abs().max()
    if largest_deviation > 1e-9:
        raise ValueError(
            "relative frequencies do not sum to 100 percent within every sample "
            f"(largest deviation {largest_deviation:.3e})"
        )

    return frequencies


def write_frequencies(frequencies: pd.DataFrame, path: Path | None = None) -> Path:
    ensure_output_directories()
    destination = path or OUTPUT_TABLES / "cell_frequencies.csv"
    frequencies.to_csv(destination, index=False, float_format="%.10f")
    return destination


def main() -> None:
    frequencies = compute_frequencies()
    destination = write_frequencies(frequencies)
    print(f"summary table written to {destination.relative_to(destination.parents[2])}")
    print(f"  rows: {len(frequencies)}")
    print(f"  samples: {frequencies['sample'].nunique()}")
    print(f"  populations: {frequencies['population'].nunique()}")


if __name__ == "__main__":
    main()
