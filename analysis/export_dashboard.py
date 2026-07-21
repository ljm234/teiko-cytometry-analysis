"""Assemble the payload the dashboard reads.

The dashboard is a static front end. It fetches one JSON document produced by this
module and renders it, with no server process and no database connection at browse
time. That choice removes a whole class of failure: there is no API to be unreachable,
no port conflict, and no version skew between the analysis and what is displayed. The
cost is that the payload has to be regenerated when the analysis changes, which is
exactly what running the pipeline does.

Sample level detail is summarised rather than shipped whole. Sending all 52500 rows
would produce a payload of several megabytes for a view that only ever draws
distributions, so each group is reduced to the five number summary a boxplot needs,
computed here where the statistical library lives rather than reimplemented in
TypeScript.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import statistics, subsets
from analysis.database import (
    POPULATION_LABELS,
    POPULATIONS,
    ensure_output_directories,
    query,
)

DASHBOARD_DATA = Path(__file__).resolve().parents[1] / "dashboard" / "public" / "data"

OVERVIEW_SQL = """
SELECT
    condition,
    treatment,
    sample_type,
    COUNT(DISTINCT sample)     AS n_samples,
    COUNT(DISTINCT subject_id) AS n_subjects
FROM sample_analysis
WHERE population = 'b_cell'
GROUP BY condition, treatment, sample_type
ORDER BY condition, treatment, sample_type
"""


def five_number_summary(values: np.ndarray) -> dict:
    """The quantities a boxplot draws, plus the count behind them.

    Whiskers follow the convention of extending to the most extreme observation within
    one and a half interquartile ranges of the nearer quartile, so they describe the
    bulk of the data rather than its outermost points.
    """
    values = np.asarray(values, dtype=float)
    q1, median, q3 = np.percentile(values, [25, 50, 75])
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    within = values[(values >= lower_fence) & (values <= upper_fence)]

    return {
        "n": int(values.size),
        "min": float(values.min()),
        "q1": float(q1),
        "median": float(median),
        "q3": float(q3),
        "max": float(values.max()),
        "whiskerLow": float(within.min()) if within.size else float(values.min()),
        "whiskerHigh": float(within.max()) if within.size else float(values.max()),
        "mean": float(values.mean()),
    }


def build_distributions(cohort: pd.DataFrame) -> list[dict]:
    """One summary per population, timepoint and response group."""
    records: list[dict] = []
    for population in POPULATIONS:
        for timepoint in statistics.TIMEPOINTS:
            for response in ("yes", "no"):
                values = cohort.loc[
                    (cohort["population"] == population)
                    & (cohort["time_from_treatment_start"] == timepoint)
                    & (cohort["response"] == response),
                    "percentage",
                ].to_numpy()
                if values.size == 0:
                    continue
                records.append(
                    {
                        "population": population,
                        "populationLabel": POPULATION_LABELS[population],
                        "timepoint": int(timepoint),
                        "response": response,
                        **five_number_summary(values),
                    }
                )
    return records


def build_statistics(cohort: pd.DataFrame) -> list[dict]:
    primary = statistics.compare_within_timepoints(cohort)
    return [
        {
            "population": row["population"],
            "populationLabel": row["population_label"],
            "timepoint": int(row["timepoint"]),
            "nResponders": int(row["n_responders"]),
            "nNonResponders": int(row["n_non_responders"]),
            "medianResponders": round(float(row["median_responders"]), 4),
            "medianNonResponders": round(float(row["median_non_responders"]), 4),
            "shift": round(float(row["hodges_lehmann_shift"]), 4),
            "effectSize": round(float(row["rank_biserial"]), 4),
            "pValue": float(row["p_value"]),
            "qValue": float(row["q_value"]),
            "significant": bool(row["significant"]),
        }
        for _, row in primary.iterrows()
    ]


def build_payload() -> dict:
    cohort = statistics.load_cohort()
    power = statistics.power_summary(cohort)
    icc = statistics.intraclass_correlation(cohort)
    subset_results = subsets.collect()
    overview = query(OVERVIEW_SQL)

    return {
        "generatedOn": date.today().isoformat(),
        "cohort": {
            "description": "Melanoma patients treated with miraclib, PBMC samples",
            "nSamples": int(cohort["sample"].nunique()),
            "nSubjects": int(cohort["subject_id"].nunique()),
            "timepoints": list(statistics.TIMEPOINTS),
            "alpha": statistics.ALPHA,
        },
        "studyOverview": overview.to_dict(orient="records"),
        "populations": [
            {"id": population, "label": POPULATION_LABELS[population]}
            for population in POPULATIONS
        ],
        "distributions": build_distributions(cohort),
        "statistics": build_statistics(cohort),
        "power": [
            {
                "timepoint": int(row["timepoint"]),
                "nResponders": int(row["n_responders"]),
                "nNonResponders": int(row["n_non_responders"]),
                "minimumDetectableEffect": round(
                    float(row["minimum_detectable_cohens_d"]), 4
                ),
            }
            for _, row in power.iterrows()
        ],
        "intraclassCorrelation": [
            {
                "population": row["population"],
                "populationLabel": row["population_label"],
                "icc1": round(float(row["icc1"]), 4),
                "samplesPerSubject": int(row["samples_per_subject"]),
            }
            for _, row in icc.iterrows()
        ],
        "subsets": subset_results,
    }


def write_payload(payload: dict, destination: Path | None = None) -> Path:
    target = destination or DASHBOARD_DATA / "analysis.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> None:
    ensure_output_directories()
    payload = build_payload()
    destination = write_payload(payload)
    size_kb = destination.stat().st_size / 1024
    print(f"dashboard payload written to {destination.name} ({size_kb:.1f} kB)")
    print(f"  distributions: {len(payload['distributions'])}")
    print(f"  statistical comparisons: {len(payload['statistics'])}")


if __name__ == "__main__":
    main()
