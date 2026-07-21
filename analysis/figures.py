"""Boxplots comparing population frequencies between responders and non-responders.

One figure per population, with the three timepoints side by side so the treatment
course reads left to right. Individual samples are drawn behind the boxes because a box
alone hides the sample size and the shape of the distribution, both of which matter when
the conclusion is that no difference was found.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.database import (
    OUTPUT_FIGURES,
    POPULATION_LABELS,
    POPULATIONS,
    ensure_output_directories,
)
from analysis.statistics import TIMEPOINTS, compare_within_timepoints, load_cohort

RESPONDER_COLOUR = "#2c7fb8"
NON_RESPONDER_COLOUR = "#d95f0e"
JITTER_WIDTH = 0.09
POINT_ALPHA = 0.18
FIGURE_DPI = 200


def _style_axes(axes: plt.Axes) -> None:
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(axis="y", linewidth=0.4, alpha=0.3)
    axes.set_axisbelow(True)


def plot_population(
    cohort: pd.DataFrame,
    primary: pd.DataFrame,
    population: str,
    destination: Path,
) -> Path:
    population_data = cohort[cohort["population"] == population]
    figure, axes = plt.subplots(figsize=(7.2, 4.6))
    rng = np.random.default_rng(0)

    positions: list[float] = []
    labels: list[str] = []

    for index, timepoint in enumerate(TIMEPOINTS):
        timepoint_data = population_data[
            population_data["time_from_treatment_start"] == timepoint
        ]
        groups = [
            (
                timepoint_data.loc[
                    timepoint_data["response"] == "yes", "percentage"
                ].to_numpy(),
                RESPONDER_COLOUR,
                index * 1.0 - 0.18,
            ),
            (
                timepoint_data.loc[
                    timepoint_data["response"] == "no", "percentage"
                ].to_numpy(),
                NON_RESPONDER_COLOUR,
                index * 1.0 + 0.18,
            ),
        ]

        for values, colour, position in groups:
            axes.scatter(
                position + rng.uniform(-JITTER_WIDTH, JITTER_WIDTH, values.size),
                values,
                s=5,
                color=colour,
                alpha=POINT_ALPHA,
                linewidths=0,
                zorder=1,
            )
            box = axes.boxplot(
                values,
                positions=[position],
                widths=0.26,
                showfliers=False,
                patch_artist=True,
                medianprops={"color": "black", "linewidth": 1.4},
                whiskerprops={"linewidth": 1.0},
                capprops={"linewidth": 1.0},
                zorder=2,
            )
            for patch in box["boxes"]:
                patch.set_facecolor(colour)
                patch.set_alpha(0.55)
                patch.set_linewidth(1.0)

        row = primary[
            (primary["population"] == population) & (primary["timepoint"] == timepoint)
        ].iloc[0]
        upper = timepoint_data["percentage"].max()
        axes.text(
            index * 1.0,
            upper * 1.04,
            f"q = {row['q_value']:.3f}",
            ha="center",
            fontsize=8.5,
            color="#404040",
        )

        positions.append(index * 1.0)
        labels.append(f"Day {timepoint}")

    axes.set_xticks(positions)
    axes.set_xticklabels(labels)
    axes.set_ylabel("Relative frequency (%)")
    axes.set_title(
        f"{POPULATION_LABELS[population]} frequency by response status\n"
        "Melanoma, miraclib, PBMC",
        fontsize=11,
    )
    handles = [
        plt.Line2D([], [], marker="s", linestyle="", color=RESPONDER_COLOUR, label="Responder"),
        plt.Line2D(
            [], [], marker="s", linestyle="", color=NON_RESPONDER_COLOUR, label="Non-responder"
        ),
    ]
    axes.legend(handles=handles, frameon=False, loc="upper right", fontsize=9)
    _style_axes(axes)

    figure.tight_layout()
    figure.savefig(destination, dpi=FIGURE_DPI)
    plt.close(figure)
    return destination


def plot_overview(cohort: pd.DataFrame, primary: pd.DataFrame, destination: Path) -> Path:
    """All five populations in one panel, pooling timepoints, for a single overview figure."""
    figure, axes = plt.subplots(figsize=(9.0, 4.8))
    rng = np.random.default_rng(0)

    for index, population in enumerate(POPULATIONS):
        population_data = cohort[cohort["population"] == population]
        for response, colour, offset in (
            ("yes", RESPONDER_COLOUR, -0.18),
            ("no", NON_RESPONDER_COLOUR, 0.18),
        ):
            values = population_data.loc[
                population_data["response"] == response, "percentage"
            ].to_numpy()
            position = index + offset
            axes.scatter(
                position + rng.uniform(-JITTER_WIDTH, JITTER_WIDTH, values.size),
                values,
                s=3,
                color=colour,
                alpha=0.10,
                linewidths=0,
                zorder=1,
            )
            box = axes.boxplot(
                values,
                positions=[position],
                widths=0.26,
                showfliers=False,
                patch_artist=True,
                medianprops={"color": "black", "linewidth": 1.3},
                zorder=2,
            )
            for patch in box["boxes"]:
                patch.set_facecolor(colour)
                patch.set_alpha(0.55)
                patch.set_linewidth(1.0)

    axes.set_xticks(range(len(POPULATIONS)))
    axes.set_xticklabels([POPULATION_LABELS[p] for p in POPULATIONS])
    axes.set_ylabel("Relative frequency (%)")
    axes.set_title(
        "Immune population frequencies by response status, all visits pooled\n"
        "Melanoma, miraclib, PBMC",
        fontsize=11,
    )
    handles = [
        plt.Line2D([], [], marker="s", linestyle="", color=RESPONDER_COLOUR, label="Responder"),
        plt.Line2D(
            [], [], marker="s", linestyle="", color=NON_RESPONDER_COLOUR, label="Non-responder"
        ),
    ]
    axes.legend(handles=handles, frameon=False, loc="upper right", fontsize=9)
    _style_axes(axes)

    figure.tight_layout()
    figure.savefig(destination, dpi=FIGURE_DPI)
    plt.close(figure)
    return destination


def main() -> None:
    ensure_output_directories()
    cohort = load_cohort()
    primary = compare_within_timepoints(cohort)

    written: list[Path] = []
    for population in POPULATIONS:
        destination = OUTPUT_FIGURES / f"{population}_response_boxplot.png"
        written.append(plot_population(cohort, primary, population, destination))

    written.append(
        plot_overview(cohort, primary, OUTPUT_FIGURES / "all_populations_overview.png")
    )

    print(f"figures written: {len(written)}")
    for path in written:
        print(f"  {path.name}")


if __name__ == "__main__":
    main()
