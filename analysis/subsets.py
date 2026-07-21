"""Part 4: subset queries against the database.

Every figure reported here is produced by SQL running against the database rather than
by filtering a dataframe in Python. The schema was designed for exactly these access
patterns, so exercising it through queries is both the honest demonstration and the
form that scales when the same questions are asked of a much larger study.

A note on units. The task asks how many samples come from each project, and then how
many subjects were responders or non-responders. The noun changes, and that is not
incidental: a sample is one blood draw, a subject is one patient, and a patient in this
study contributes three draws. At baseline the two happen to coincide, because each
subject has exactly one day zero sample, but the distinction matters as soon as the
filter moves off baseline. Both counts are therefore reported and labelled explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from analysis.database import OUTPUT_TABLES, ensure_output_directories, query

BASELINE_FILTER = """
    FROM sample s
    JOIN subject sub ON sub.subject_id = s.subject_id
    WHERE sub.condition = 'melanoma'
      AND sub.treatment = 'miraclib'
      AND s.sample_type = 'PBMC'
      AND s.time_from_treatment_start = 0
"""

BASELINE_SAMPLES_SQL = f"""
SELECT
    s.sample_id                 AS sample,
    sub.subject_id,
    sub.project_id              AS project,
    sub.sex,
    sub.age,
    sub.response
{BASELINE_FILTER}
ORDER BY s.sample_id
"""

SAMPLES_PER_PROJECT_SQL = f"""
SELECT
    sub.project_id                      AS project,
    COUNT(*)                            AS n_samples,
    COUNT(DISTINCT sub.subject_id)      AS n_subjects
{BASELINE_FILTER}
GROUP BY sub.project_id
ORDER BY sub.project_id
"""

SUBJECTS_BY_RESPONSE_SQL = f"""
SELECT
    sub.response                        AS response,
    COUNT(DISTINCT sub.subject_id)      AS n_subjects,
    COUNT(*)                            AS n_samples
{BASELINE_FILTER}
GROUP BY sub.response
ORDER BY sub.response
"""

SUBJECTS_BY_SEX_SQL = f"""
SELECT
    sub.sex                             AS sex,
    COUNT(DISTINCT sub.subject_id)      AS n_subjects,
    COUNT(*)                            AS n_samples
{BASELINE_FILTER}
GROUP BY sub.sex
ORDER BY sub.sex
"""

# The final question widens the filter deliberately. It asks for melanoma males across
# all sample types and all treatments, so sample_type and treatment are absent from the
# WHERE clause on purpose, and both PBMC and whole blood samples, under miraclib and
# phauximab alike, are included.
MALE_RESPONDER_BASELINE_B_CELLS_SQL = """
SELECT
    COUNT(*)                            AS n_samples,
    COUNT(DISTINCT sub.subject_id)      AS n_subjects,
    AVG(cc.count)                       AS mean_b_cell_count,
    SUM(cc.count)                       AS total_b_cell_count
FROM cell_count cc
JOIN sample s   ON s.sample_id = cc.sample_id
JOIN subject sub ON sub.subject_id = s.subject_id
WHERE cc.population_id = 'b_cell'
  AND sub.condition = 'melanoma'
  AND sub.sex = 'M'
  AND sub.response = 'yes'
  AND s.time_from_treatment_start = 0
"""

MALE_RESPONDER_BREAKDOWN_SQL = """
SELECT
    s.sample_type,
    sub.treatment,
    COUNT(*)        AS n_samples,
    AVG(cc.count)   AS mean_b_cell_count
FROM cell_count cc
JOIN sample s   ON s.sample_id = cc.sample_id
JOIN subject sub ON sub.subject_id = s.subject_id
WHERE cc.population_id = 'b_cell'
  AND sub.condition = 'melanoma'
  AND sub.sex = 'M'
  AND sub.response = 'yes'
  AND s.time_from_treatment_start = 0
GROUP BY s.sample_type, sub.treatment
ORDER BY s.sample_type, sub.treatment
"""


def baseline_samples() -> pd.DataFrame:
    """Melanoma PBMC samples at baseline from patients treated with miraclib."""
    samples = query(BASELINE_SAMPLES_SQL)
    if samples.empty:
        raise ValueError("baseline subset query returned no rows")
    return samples


def samples_per_project() -> pd.DataFrame:
    return query(SAMPLES_PER_PROJECT_SQL)


def subjects_by_response() -> pd.DataFrame:
    return query(SUBJECTS_BY_RESPONSE_SQL)


def subjects_by_sex() -> pd.DataFrame:
    return query(SUBJECTS_BY_SEX_SQL)


def male_responder_baseline_b_cells() -> dict:
    """Average B cell count for melanoma males responding at baseline.

    The average is reported to two decimal places as the task requires. Rounding is
    applied once, at the point of reporting, rather than to the stored value.
    """
    summary = query(MALE_RESPONDER_BASELINE_B_CELLS_SQL).iloc[0]
    if summary["n_samples"] == 0:
        raise ValueError("no samples matched the melanoma male responder baseline filter")

    breakdown = query(MALE_RESPONDER_BREAKDOWN_SQL)
    return {
        "n_samples": int(summary["n_samples"]),
        "n_subjects": int(summary["n_subjects"]),
        "total_b_cell_count": int(summary["total_b_cell_count"]),
        "mean_b_cell_count": float(summary["mean_b_cell_count"]),
        "mean_b_cell_count_rounded": round(float(summary["mean_b_cell_count"]), 2),
        "breakdown": breakdown.to_dict(orient="records"),
    }


def collect() -> dict:
    """Run every Part 4 query and return the results in one structure."""
    samples = baseline_samples()
    projects = samples_per_project()
    response = subjects_by_response()
    sex = subjects_by_sex()
    b_cells = male_responder_baseline_b_cells()

    # The per group counts must add up to the total, otherwise a filter has drifted.
    total_samples = len(samples)
    for name, frame in (("project", projects), ("response", response), ("sex", sex)):
        if int(frame["n_samples"].sum()) != total_samples:
            raise ValueError(
                f"{name} breakdown sums to {int(frame['n_samples'].sum())} samples "
                f"but the baseline subset holds {total_samples}"
            )

    return {
        "baseline_cohort": {
            "description": (
                "Melanoma PBMC samples at baseline from patients treated with miraclib"
            ),
            "n_samples": total_samples,
            "n_subjects": int(samples["subject_id"].nunique()),
        },
        "samples_per_project": projects.to_dict(orient="records"),
        "subjects_by_response": response.to_dict(orient="records"),
        "subjects_by_sex": sex.to_dict(orient="records"),
        "male_responder_baseline_b_cells": b_cells,
    }


def write_outputs(results: dict) -> dict[str, Path]:
    ensure_output_directories()
    destinations: dict[str, Path] = {}

    for key in ("samples_per_project", "subjects_by_response", "subjects_by_sex"):
        destination = OUTPUT_TABLES / f"baseline_{key}.csv"
        pd.DataFrame(results[key]).to_csv(destination, index=False)
        destinations[key] = destination

    summary_path = OUTPUT_TABLES / "subset_analysis.json"
    summary_path.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    destinations["summary"] = summary_path

    return destinations


def main() -> None:
    results = collect()
    destinations = write_outputs(results)

    cohort = results["baseline_cohort"]
    print(f"{cohort['description']}")
    print(f"  samples: {cohort['n_samples']}, subjects: {cohort['n_subjects']}")

    print("samples per project")
    for row in results["samples_per_project"]:
        print(f"  {row['project']}: {row['n_samples']} samples, {row['n_subjects']} subjects")

    print("subjects by response")
    for row in results["subjects_by_response"]:
        print(f"  {row['response']}: {row['n_subjects']} subjects, {row['n_samples']} samples")

    print("subjects by sex")
    for row in results["subjects_by_sex"]:
        print(f"  {row['sex']}: {row['n_subjects']} subjects, {row['n_samples']} samples")

    b_cells = results["male_responder_baseline_b_cells"]
    print(
        "melanoma males responding at baseline, all sample types and treatments"
    )
    print(f"  samples: {b_cells['n_samples']}, subjects: {b_cells['n_subjects']}")
    print(f"  average B cell count: {b_cells['mean_b_cell_count_rounded']:.2f}")

    for key, path in destinations.items():
        print(f"  {key}: {path.name}")


if __name__ == "__main__":
    main()
