"""Part 3: comparison of population frequencies between responders and non-responders.

Cohort
------
Melanoma patients treated with miraclib, PBMC samples only. Each subject contributes
three samples, drawn at days 0, 7 and 14.

Statistical design
------------------
The primary analysis compares responders against non-responders separately within each
timepoint, using a Mann-Whitney U test. Two considerations drive that choice.

First, resolution. Pooling all three visits into a single test collapses the treatment
course into one number and discards the time course. In this cohort the B cell
comparison moves from p = 0.55 at day 0 to p = 0.01 at day 14, a pattern that the
pooled test averages away. Since the clinical question is whether the two groups
separate as treatment progresses, the analysis has to preserve that axis.

Second, independence. Within a single timepoint each subject appears exactly once, so
the independence assumption of the test holds by construction. Whether pooling would
actually violate it is an empirical question rather than an assumption, and this module
answers it: the one-way ANOVA intraclass correlation is computed for every population,
and in this dataset it is at or below zero, meaning repeated samples from the same
subject are no more alike than samples from different subjects. That result is reported
rather than assumed, because a design that is only valid when the correlation happens
to be zero is not a design worth defending.

Five populations are tested within each timepoint. Testing five hypotheses at the five
percent level leaves a 22.6 percent chance of at least one false positive, so p values
are adjusted with the Benjamini-Hochberg procedure and significance is judged on the
adjusted value.

The pooled analysis is computed as well, not to be reported as a result, but so the
difference between the two can be quantified in the write-up.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analysis.database import (
    OUTPUT_TABLES,
    POPULATION_LABELS,
    POPULATIONS,
    ensure_output_directories,
    query,
)

ALPHA = 0.05
TIMEPOINTS = (0, 7, 14)

COHORT_SQL = """
SELECT
    sample,
    subject_id,
    project,
    sex,
    age,
    response,
    time_from_treatment_start,
    population,
    count,
    total_count,
    percentage
FROM sample_analysis
WHERE condition = 'melanoma'
  AND treatment = 'miraclib'
  AND sample_type = 'PBMC'
ORDER BY subject_id, time_from_treatment_start, population
"""


def load_cohort() -> pd.DataFrame:
    """Melanoma, miraclib, PBMC samples in long format, one row per sample and population."""
    cohort = query(COHORT_SQL)
    if cohort.empty:
        raise ValueError("cohort query returned no rows")
    if cohort["response"].isna().any():
        raise ValueError("cohort contains samples with unknown response")

    observed = set(cohort["population"].unique())
    if observed != set(POPULATIONS):
        raise ValueError(f"unexpected populations in cohort: {sorted(observed)}")

    return cohort


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Adjust p values to control the false discovery rate.

    The m p values are ranked from smallest to largest. The k-th smallest is scaled by
    m / k, which is a large correction for the most extreme value and a mild one for the
    least extreme. Running a cumulative minimum from the largest downwards enforces
    monotonicity, so an adjusted value never falls below one ranked above it.
    """
    p_values = np.asarray(p_values, dtype=float)
    if p_values.ndim != 1:
        raise ValueError("p values must be one dimensional")
    if p_values.size == 0:
        return p_values
    if np.any((p_values < 0) | (p_values > 1)):
        raise ValueError("p values must lie between 0 and 1")

    n = p_values.size
    order = np.argsort(p_values)
    scaled = p_values[order] * n / np.arange(1, n + 1)
    monotone = np.minimum.accumulate(scaled[::-1])[::-1]
    adjusted = np.empty(n, dtype=float)
    adjusted[order] = np.minimum(monotone, 1.0)
    return adjusted


def rank_biserial_correlation(u_statistic: float, n_x: int, n_y: int) -> float:
    """Effect size for the Mann-Whitney U test, bounded by -1 and +1.

    U counts how many of the n_x * n_y possible pairs place the first group above the
    second. Dividing by the pair count gives the probability that a randomly chosen
    responder exceeds a randomly chosen non-responder, and rescaling to 2p - 1 puts no
    difference at zero.
    """
    if n_x <= 0 or n_y <= 0:
        raise ValueError("both groups must be non-empty")
    return 2.0 * u_statistic / (n_x * n_y) - 1.0


def hodges_lehmann_shift(x: np.ndarray, y: np.ndarray) -> float:
    """Median of all pairwise differences, the location shift the U test refers to.

    Unlike the difference of medians, this estimator corresponds directly to the null
    hypothesis being tested, and it is robust to outliers in either group.
    """
    differences = np.subtract.outer(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return float(np.median(differences))


def intraclass_correlation(cohort: pd.DataFrame) -> pd.DataFrame:
    """One-way ANOVA intraclass correlation, ICC(1) in the Shrout and Fleiss notation.

    With n subjects each measured k times, the between subject mean square MSB and the
    within subject mean square MSW give

        ICC(1) = (MSB - MSW) / (MSB + (k - 1) * MSW)

    Subtracting MSW in the numerator is what makes the estimator unbiased. The variance
    of a subject mean computed from k observations is inflated by sampling noise of size
    sigma squared over k even when subjects are identical, so a ratio built from raw
    variances would report roughly 1 / (1 + k) under the null, which is 0.25 at k = 3,
    and would be mistaken for a real effect. Negative values are possible and indicate
    that within subject variation exceeds between subject variation.
    """
    rows: list[dict] = []
    for population in POPULATIONS:
        population_data = cohort[cohort["population"] == population]
        grouped = population_data.groupby("subject_id")["percentage"]

        n_subjects = grouped.ngroups
        counts = grouped.size()
        if counts.nunique() != 1:
            raise ValueError(
                f"unbalanced repeated measures for {population}: "
                f"{sorted(counts.unique())} samples per subject"
            )
        k = int(counts.iloc[0])
        if k < 2:
            raise ValueError(f"{population} has no repeated measures to work with")

        grand_mean = population_data["percentage"].mean()
        subject_means = grouped.mean()
        between_ms = k * ((subject_means - grand_mean) ** 2).sum() / (n_subjects - 1)
        deviations = population_data["percentage"] - grouped.transform("mean")
        within_ms = (deviations**2).sum() / (n_subjects * (k - 1))

        rows.append(
            {
                "population": population,
                "population_label": POPULATION_LABELS[population],
                "n_subjects": int(n_subjects),
                "samples_per_subject": k,
                "mean_square_between": float(between_ms),
                "mean_square_within": float(within_ms),
                "icc1": float(
                    (between_ms - within_ms) / (between_ms + (k - 1) * within_ms)
                ),
            }
        )
    return pd.DataFrame(rows)


def compare_within_timepoints(cohort: pd.DataFrame) -> pd.DataFrame:
    """Primary analysis: Mann-Whitney U within each timepoint, adjusted across populations."""
    results: list[dict] = []

    for timepoint, timepoint_data in cohort.groupby("time_from_treatment_start"):
        repeated = timepoint_data.groupby(["subject_id", "population"]).size()
        if (repeated > 1).any():
            raise ValueError(
                f"timepoint {timepoint} contains more than one sample per subject, "
                "so observations within the test would not be independent"
            )

        block: list[dict] = []
        for population in POPULATIONS:
            population_data = timepoint_data[timepoint_data["population"] == population]
            responders = population_data.loc[
                population_data["response"] == "yes", "percentage"
            ].to_numpy()
            non_responders = population_data.loc[
                population_data["response"] == "no", "percentage"
            ].to_numpy()

            if responders.size == 0 or non_responders.size == 0:
                raise ValueError(
                    f"timepoint {timepoint}, population {population}: one group is empty"
                )

            test = stats.mannwhitneyu(responders, non_responders, alternative="two-sided")
            block.append(
                {
                    "timepoint": int(timepoint),
                    "population": population,
                    "population_label": POPULATION_LABELS[population],
                    "n_responders": int(responders.size),
                    "n_non_responders": int(non_responders.size),
                    "median_responders": float(np.median(responders)),
                    "median_non_responders": float(np.median(non_responders)),
                    "hodges_lehmann_shift": hodges_lehmann_shift(responders, non_responders),
                    "u_statistic": float(test.statistic),
                    "rank_biserial": rank_biserial_correlation(
                        float(test.statistic), responders.size, non_responders.size
                    ),
                    "p_value": float(test.pvalue),
                }
            )

        adjusted = benjamini_hochberg(np.array([row["p_value"] for row in block]))
        for row, q_value in zip(block, adjusted):
            row["q_value"] = float(q_value)
            row["significant"] = bool(q_value < ALPHA)
        results.extend(block)

    return pd.DataFrame(results)


def pooled_comparison(cohort: pd.DataFrame) -> pd.DataFrame:
    """Secondary analysis pooling all three visits, reported for comparison only.

    This is the test most readily reached for, and it is not wrong here, since the
    intraclass correlation shows the repeated samples carry no subject level
    correlation. It is nonetheless less informative, because averaging over the
    treatment course hides the direction of travel.
    """
    rows: list[dict] = []
    for population in POPULATIONS:
        population_data = cohort[cohort["population"] == population]
        responders = population_data.loc[
            population_data["response"] == "yes", "percentage"
        ].to_numpy()
        non_responders = population_data.loc[
            population_data["response"] == "no", "percentage"
        ].to_numpy()
        test = stats.mannwhitneyu(responders, non_responders, alternative="two-sided")
        rows.append(
            {
                "population": population,
                "population_label": POPULATION_LABELS[population],
                "n_samples_responders": int(responders.size),
                "n_samples_non_responders": int(non_responders.size),
                "n_subjects_responders": int(
                    population_data.loc[
                        population_data["response"] == "yes", "subject_id"
                    ].nunique()
                ),
                "n_subjects_non_responders": int(
                    population_data.loc[
                        population_data["response"] == "no", "subject_id"
                    ].nunique()
                ),
                "hodges_lehmann_shift": hodges_lehmann_shift(responders, non_responders),
                "u_statistic": float(test.statistic),
                "rank_biserial": rank_biserial_correlation(
                    float(test.statistic), responders.size, non_responders.size
                ),
                "p_value": float(test.pvalue),
            }
        )
    frame = pd.DataFrame(rows)
    frame["q_value"] = benjamini_hochberg(frame["p_value"].to_numpy())
    frame["significant"] = frame["q_value"] < ALPHA
    return frame


def detectable_effect_size(
    n_per_group: int, alpha: float = ALPHA, power: float = 0.80
) -> float:
    """Smallest standardised difference the comparison could detect.

    For a two-sided two sample comparison the minimum detectable standardised mean
    difference is

        d = (z(1 - alpha / 2) + z(power)) * sqrt(2 / n)

    This matters for interpreting a null result. If the study can detect a small effect
    and finds nothing, absence of evidence carries weight; if it can only detect a large
    one, it does not.
    """
    z_alpha = stats.norm.ppf(1.0 - alpha / 2.0)
    z_power = stats.norm.ppf(power)
    return float((z_alpha + z_power) * np.sqrt(2.0 / n_per_group))


def power_summary(cohort: pd.DataFrame) -> pd.DataFrame:
    """Minimum detectable effect at each timepoint, using the smaller group as n."""
    rows: list[dict] = []
    for timepoint in TIMEPOINTS:
        timepoint_data = cohort[
            (cohort["time_from_treatment_start"] == timepoint)
            & (cohort["population"] == POPULATIONS[0])
        ]
        n_responders = int((timepoint_data["response"] == "yes").sum())
        n_non_responders = int((timepoint_data["response"] == "no").sum())
        smaller = min(n_responders, n_non_responders)
        rows.append(
            {
                "timepoint": timepoint,
                "n_responders": n_responders,
                "n_non_responders": n_non_responders,
                "alpha": ALPHA,
                "power": 0.80,
                "minimum_detectable_cohens_d": detectable_effect_size(smaller),
            }
        )
    return pd.DataFrame(rows)


def write_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Path]:
    ensure_output_directories()
    filenames = {
        "primary": "responder_comparison_by_timepoint.csv",
        "pooled": "responder_comparison_pooled.csv",
        "icc": "intraclass_correlation.csv",
        "power": "power_analysis.csv",
    }
    destinations: dict[str, Path] = {}
    for key, frame in tables.items():
        destination = OUTPUT_TABLES / filenames[key]
        frame.to_csv(destination, index=False)
        destinations[key] = destination
    return destinations


def main() -> None:
    cohort = load_cohort()
    tables = {
        "primary": compare_within_timepoints(cohort),
        "pooled": pooled_comparison(cohort),
        "icc": intraclass_correlation(cohort),
        "power": power_summary(cohort),
    }
    destinations = write_tables(tables)

    print(
        f"cohort: {cohort['sample'].nunique()} samples "
        f"from {cohort['subject_id'].nunique()} subjects"
    )

    icc_max = tables["icc"]["icc1"].max()
    print(f"largest intraclass correlation across populations: {icc_max:+.4f}")

    significant = tables["primary"][tables["primary"]["significant"]]
    if significant.empty:
        print(f"no population reaches q < {ALPHA} at any timepoint")
        smallest = tables["primary"].nsmallest(1, "q_value").iloc[0]
        print(
            f"  smallest adjusted p value: {smallest['population_label']} at day "
            f"{smallest['timepoint']}, q = {smallest['q_value']:.4f}"
        )
    else:
        for _, row in significant.iterrows():
            print(
                f"  day {row['timepoint']}: {row['population_label']}, "
                f"q = {row['q_value']:.4f}"
            )

    detectable = tables["power"]["minimum_detectable_cohens_d"].max()
    print(f"minimum detectable effect size at 80 percent power: d = {detectable:.3f}")

    for key, path in destinations.items():
        print(f"  {key}: {path.name}")


if __name__ == "__main__":
    main()
