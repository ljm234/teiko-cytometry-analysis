"""Tests for the analysis modules: frequencies, statistics and subset queries.

Each test states a property that must hold rather than pinning an output to whatever
the code happened to produce. Where a published result is checked against a fixed
number, the number is derived independently in the test body or taken directly from
the task description.
"""

from __future__ import annotations

import numpy as np
import pytest

from analysis import frequencies, statistics, subsets
from analysis.database import POPULATIONS


@pytest.fixture(scope="module")
def frequency_table(database):
    return frequencies.compute_frequencies()


@pytest.fixture(scope="module")
def cohort(database):
    return statistics.load_cohort()


def test_frequency_table_has_the_columns_the_task_specifies(frequency_table) -> None:
    expected = ["sample", "total_count", "population", "count", "percentage"]
    assert list(frequency_table.columns) == expected


def test_one_row_per_sample_and_population(frequency_table, source_frame) -> None:
    assert len(frequency_table) == len(source_frame) * len(POPULATIONS)
    assert frequency_table["sample"].nunique() == len(source_frame)
    assert frequency_table["population"].nunique() == len(POPULATIONS)


def test_percentages_sum_to_one_hundred_within_every_sample(frequency_table) -> None:
    """The defining property of a relative frequency: the parts make the whole."""
    totals = frequency_table.groupby("sample")["percentage"].sum()
    assert np.allclose(totals, 100.0, atol=1e-9)


def test_total_count_equals_the_sum_of_the_five_populations(frequency_table) -> None:
    computed = frequency_table.groupby("sample")["count"].sum()
    reported = frequency_table.groupby("sample")["total_count"].first()
    assert (computed == reported).all()


def test_percentage_matches_count_over_total(frequency_table) -> None:
    expected = 100.0 * frequency_table["count"] / frequency_table["total_count"]
    assert np.allclose(frequency_table["percentage"], expected, atol=1e-12)


def test_frequencies_agree_with_the_source_file(frequency_table, source_frame) -> None:
    """Recompute one sample by hand from the CSV and compare."""
    row = source_frame.iloc[0]
    total = sum(int(row[population]) for population in POPULATIONS)
    subset = frequency_table[frequency_table["sample"] == row["sample"]]

    for population in POPULATIONS:
        entry = subset[subset["population"] == population].iloc[0]
        assert entry["count"] == int(row[population])
        assert entry["total_count"] == total
        assert entry["percentage"] == pytest.approx(
            100.0 * int(row[population]) / total, abs=1e-12
        )


def test_cohort_is_melanoma_miraclib_pbmc_only(cohort) -> None:
    assert cohort["sample"].nunique() == 1968
    assert cohort["subject_id"].nunique() == 656
    assert cohort["response"].notna().all()


def test_every_subject_contributes_one_sample_per_timepoint(cohort) -> None:
    """The premise behind analysing timepoints separately."""
    per_timepoint = cohort.groupby(["time_from_treatment_start", "subject_id", "population"])
    assert per_timepoint.size().max() == 1


def test_benjamini_hochberg_leaves_a_single_p_value_untouched() -> None:
    p_values = np.array([0.03])
    assert statistics.benjamini_hochberg(p_values) == pytest.approx(0.03)


def test_benjamini_hochberg_scales_the_smallest_by_the_number_of_tests() -> None:
    """With m tests the smallest p value is multiplied by m, capped at one."""
    p_values = np.array([0.01, 0.5, 0.6, 0.7, 0.8])
    adjusted = statistics.benjamini_hochberg(p_values)
    assert adjusted[0] == pytest.approx(0.05)


def test_benjamini_hochberg_never_decreases_with_rank() -> None:
    rng = np.random.default_rng(0)
    p_values = rng.uniform(size=50)
    adjusted = statistics.benjamini_hochberg(p_values)
    order = np.argsort(p_values)
    assert np.all(np.diff(adjusted[order]) >= -1e-12)


def test_benjamini_hochberg_is_never_smaller_than_the_raw_value() -> None:
    rng = np.random.default_rng(1)
    p_values = rng.uniform(size=30)
    assert np.all(statistics.benjamini_hochberg(p_values) >= p_values - 1e-12)


def test_benjamini_hochberg_rejects_values_outside_the_unit_interval() -> None:
    with pytest.raises(ValueError):
        statistics.benjamini_hochberg(np.array([0.5, 1.5]))


def test_rank_biserial_is_zero_when_the_groups_are_indistinguishable() -> None:
    """Half of all pairs favour each group, so the effect size sits at zero."""
    n_x = n_y = 10
    half_the_pairs = n_x * n_y / 2
    assert statistics.rank_biserial_correlation(half_the_pairs, n_x, n_y) == pytest.approx(0.0)


def test_rank_biserial_reaches_one_when_separation_is_complete() -> None:
    n_x = n_y = 10
    assert statistics.rank_biserial_correlation(n_x * n_y, n_x, n_y) == pytest.approx(1.0)
    assert statistics.rank_biserial_correlation(0.0, n_x, n_y) == pytest.approx(-1.0)


def test_hodges_lehmann_recovers_a_known_shift() -> None:
    x = np.array([10.0, 11.0, 12.0])
    y = np.array([5.0, 6.0, 7.0])
    assert statistics.hodges_lehmann_shift(x, y) == pytest.approx(5.0)


def test_hodges_lehmann_resists_an_outlier() -> None:
    """The estimator is the median of pairwise differences, not the mean of them.

    On symmetric data the two agree, so a test built from symmetric inputs cannot tell
    them apart. One extreme value separates them: the median stays with the bulk of the
    differences while the mean is dragged towards the outlier, and it is that resistance
    that makes the estimator the right partner for a rank based test.
    """
    x = np.array([1.0, 2.0, 3.0, 400.0])
    y = np.array([0.0, 0.0, 0.0, 0.0])

    shift = statistics.hodges_lehmann_shift(x, y)
    differences = np.subtract.outer(x, y)

    assert shift == pytest.approx(2.5)
    assert shift != pytest.approx(float(differences.mean()))
    assert shift < differences.mean() / 10


def test_intraclass_correlation_is_near_zero_for_this_cohort(cohort) -> None:
    """Repeated samples here carry no subject level correlation.

    The estimator subtracts the within subject mean square in the numerator, so a
    dataset with no subject effect returns a value at or below zero rather than the
    1 / (1 + k) that a ratio of raw variances would report.
    """
    table = statistics.intraclass_correlation(cohort)
    assert (table["icc1"] < 0.05).all()
    assert (table["samples_per_subject"] == 3).all()


def test_detectable_effect_size_follows_the_standard_formula() -> None:
    from scipy import stats as scipy_stats

    n = 328
    expected = (scipy_stats.norm.ppf(0.975) + scipy_stats.norm.ppf(0.80)) * np.sqrt(2 / n)
    assert statistics.detectable_effect_size(n) == pytest.approx(expected)


def test_detectable_effect_size_shrinks_as_the_sample_grows() -> None:
    assert statistics.detectable_effect_size(1000) < statistics.detectable_effect_size(100)


def test_primary_comparison_covers_every_population_at_every_timepoint(cohort) -> None:
    primary = statistics.compare_within_timepoints(cohort)
    assert len(primary) == len(POPULATIONS) * len(statistics.TIMEPOINTS)
    assert set(primary["timepoint"]) == set(statistics.TIMEPOINTS)
    assert (primary["q_value"] >= primary["p_value"] - 1e-12).all()


def test_baseline_subset_matches_the_source_file(database, source_frame) -> None:
    """Part 4: melanoma PBMC samples at baseline under miraclib."""
    expected = source_frame[
        (source_frame["condition"] == "melanoma")
        & (source_frame["treatment"] == "miraclib")
        & (source_frame["sample_type"] == "PBMC")
        & (source_frame["time_from_treatment_start"] == 0)
    ]
    baseline = subsets.baseline_samples()
    assert len(baseline) == len(expected)
    assert set(baseline["sample"]) == set(expected["sample"])


def test_project_breakdown_accounts_for_every_baseline_sample(database) -> None:
    baseline = subsets.baseline_samples()
    projects = subsets.samples_per_project()
    assert projects["n_samples"].sum() == len(baseline)


def test_response_and_sex_breakdowns_account_for_every_subject(database) -> None:
    baseline = subsets.baseline_samples()
    for frame in (subsets.subjects_by_response(), subsets.subjects_by_sex()):
        assert frame["n_subjects"].sum() == baseline["subject_id"].nunique()


def test_male_responder_b_cell_average_matches_a_direct_calculation(
    database, source_frame
) -> None:
    """Part 4: all sample types and all treatments, not only PBMC under miraclib."""
    expected = source_frame[
        (source_frame["condition"] == "melanoma")
        & (source_frame["sex"] == "M")
        & (source_frame["response"] == "yes")
        & (source_frame["time_from_treatment_start"] == 0)
    ]
    result = subsets.male_responder_baseline_b_cells()

    assert result["n_samples"] == len(expected)
    assert result["total_b_cell_count"] == int(expected["b_cell"].sum())
    assert result["mean_b_cell_count_rounded"] == pytest.approx(
        round(expected["b_cell"].mean(), 2)
    )
    assert set(expected["sample_type"]) == {"PBMC", "WB"}
    assert set(expected["treatment"]) == {"miraclib", "phauximab"}
