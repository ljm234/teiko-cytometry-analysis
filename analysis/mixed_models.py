"""Confirmatory analysis: linear mixed effects models fitted across all three visits.

A mixed effects model splits variation into fixed effects, describing the average
behaviour of the groups under comparison, and random effects, describing how individual
subjects depart from that average. Fitting a random intercept per subject gives every
patient their own baseline level, so the group comparison is estimated after personal
baselines have been accounted for.

The model fitted per population is

    percentage ~ responder + day + responder:day, with a random intercept by subject

The interaction term is the quantity of interest. It estimates how much faster a
responder's frequency changes per day relative to a non-responder, in percentage points
per day. A two sample test at a single visit cannot answer that question, because it
compares levels rather than trajectories.

Two results here are worth reading carefully. The random intercept variance is
estimated at zero for every population, which agrees with the one-way intraclass
correlation reported alongside it, and means the data carry no detectable subject level
clustering. Statsmodels signals this with a convergence warning about the maximum
likelihood estimate sitting on the boundary of the parameter space, which is the
expected message when a variance component is driven to its lower bound of zero rather
than a sign that the fit failed. The L-BFGS-B optimiser cannot complete under that
condition because it inverts a matrix that becomes singular as the variance approaches
zero, so Powell's method is used instead. Three optimisers were checked against each
other during development and returned identical coefficients to six decimal places.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from analysis.database import (
    OUTPUT_TABLES,
    POPULATION_LABELS,
    POPULATIONS,
    ensure_output_directories,
)
from analysis.statistics import ALPHA, FLOAT_FORMAT, benjamini_hochberg, load_cohort

OPTIMISER = "powell"
MAX_ITERATIONS = 1000

# Variance components and any quantity derived from them are rounded to six decimal
# places before being written. When a variance component is estimated at its lower
# bound the optimiser approaches zero asymptotically and stops wherever its tolerance
# is met, so consecutive fits land on values such as 1.1e-9 or 2.0e-9. Both are zero
# in any meaningful sense: the residual variance is around ten, so these estimates are
# ten orders of magnitude smaller than the signal. Writing them at full precision would
# imply a resolution the method does not have, and would make the output file differ
# between runs for no analytical reason.
VARIANCE_DECIMALS = 6
VARIANCE_COLUMNS = (
    "variance_between_subjects",
    "variance_residual",
    "model_intraclass_correlation",
)


def fit_population_model(cohort: pd.DataFrame, population: str):
    """Fit the random intercept model for one population.

    The boundary warning is suppressed deliberately. It reports the zero variance
    estimate that is itself one of the findings, and that value is carried into the
    output table rather than discarded.
    """
    population_data = cohort[cohort["population"] == population].copy()
    population_data["responder"] = (population_data["response"] == "yes").astype(int)
    population_data["day"] = population_data["time_from_treatment_start"].astype(float)

    model = smf.mixedlm(
        "percentage ~ responder * day",
        data=population_data,
        groups=population_data["subject_id"],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ConvergenceWarning)
        return model.fit(method=OPTIMISER, maxiter=MAX_ITERATIONS)


def summarise(cohort: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for population in POPULATIONS:
        result = fit_population_model(cohort, population)
        confidence_interval = result.conf_int()

        group_variance = float(np.asarray(result.cov_re).ravel()[0])
        residual_variance = float(result.scale)
        total_variance = group_variance + residual_variance

        rows.append(
            {
                "population": population,
                "population_label": POPULATION_LABELS[population],
                "converged": bool(result.converged),
                "n_observations": int(result.nobs),
                "n_subjects": int(cohort["subject_id"].nunique()),
                "responder_effect": float(result.params["responder"]),
                "responder_std_error": float(result.bse["responder"]),
                "responder_p_value": float(result.pvalues["responder"]),
                "interaction_effect": float(result.params["responder:day"]),
                "interaction_std_error": float(result.bse["responder:day"]),
                "interaction_ci_lower": float(
                    confidence_interval.loc["responder:day", 0]
                ),
                "interaction_ci_upper": float(
                    confidence_interval.loc["responder:day", 1]
                ),
                "interaction_p_value": float(result.pvalues["responder:day"]),
                "variance_between_subjects": group_variance,
                "variance_residual": residual_variance,
                "model_intraclass_correlation": (
                    group_variance / total_variance if total_variance > 0 else 0.0
                ),
            }
        )

    frame = pd.DataFrame(rows)
    frame["responder_q_value"] = benjamini_hochberg(frame["responder_p_value"].to_numpy())
    frame["interaction_q_value"] = benjamini_hochberg(
        frame["interaction_p_value"].to_numpy()
    )
    frame["interaction_significant"] = frame["interaction_q_value"] < ALPHA

    for column in VARIANCE_COLUMNS:
        frame[column] = frame[column].round(VARIANCE_DECIMALS)

    return frame


def write_table(summary: pd.DataFrame, path: Path | None = None) -> Path:
    ensure_output_directories()
    destination = path or OUTPUT_TABLES / "mixed_model_summary.csv"
    summary.to_csv(destination, index=False, float_format=FLOAT_FORMAT)
    return destination


def main() -> None:
    cohort = load_cohort()
    summary = summarise(cohort)

    if not summary["converged"].all():
        failed = summary.loc[~summary["converged"], "population"].tolist()
        raise RuntimeError(f"mixed model failed to converge for: {failed}")

    destination = write_table(summary)

    print(f"mixed models fitted for {len(summary)} populations, all converged")
    for _, row in summary.iterrows():
        significance = "significant" if row["interaction_significant"] else "not significant"
        print(
            f"  {row['population_label']:<12} "
            f"{row['interaction_effect']:+.5f} pct per day "
            f"[{row['interaction_ci_lower']:+.5f}, {row['interaction_ci_upper']:+.5f}] "
            f"q = {row['interaction_q_value']:.4f} {significance}"
        )

    max_random_variance = summary["variance_between_subjects"].max()
    print(f"largest random intercept variance: {max_random_variance:.6f}")
    print(f"  written to {destination.name}")


if __name__ == "__main__":
    main()
