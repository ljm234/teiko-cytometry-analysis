import { useEffect, useMemo, useState } from "react";
import { BoxPlot } from "./components/BoxPlot";
import { StatisticsTable } from "./components/StatisticsTable";
import type { Payload } from "./types";

const DATA_URL = "./data/analysis.json";

export default function App() {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timepointFilter, setTimepointFilter] = useState<number | "all">("all");

  useEffect(() => {
    let cancelled = false;

    fetch(DATA_URL)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Request for ${DATA_URL} returned ${response.status}`);
        }
        return response.json() as Promise<Payload>;
      })
      .then((data) => {
        if (!cancelled) {
          setPayload(data);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const visibleStatistics = useMemo(() => {
    if (!payload) {
      return [];
    }
    return timepointFilter === "all"
      ? payload.statistics
      : payload.statistics.filter((row) => row.timepoint === timepointFilter);
  }, [payload, timepointFilter]);

  if (error) {
    return (
      <main className="status">
        <p>{error}</p>
        <p>Run make pipeline to regenerate the analysis, then reload this page.</p>
      </main>
    );
  }

  if (!payload) {
    return <main className="status">Loading the analysis.</main>;
  }

  const { cohort, subsets } = payload;
  const strongest = [...payload.statistics].sort((a, b) => a.qValue - b.qValue)[0];
  const anySignificant = payload.statistics.some((row) => row.significant);
  const largestIcc = Math.max(...payload.intraclassCorrelation.map((row) => row.icc1));
  const detectable = Math.max(...payload.power.map((row) => row.minimumDetectableEffect));

  return (
    <div className="shell">
      <header className="masthead">
        <p className="eyebrow">Clinical cytometry, response analysis</p>
        <h1>
          Immune cell frequencies do not separate responders from non-responders
        </h1>
        <p className="lede">
          {cohort.description}. Five populations measured at three visits across the
          first fortnight of treatment, compared between patients who responded and
          those who did not.
        </p>
        <div className="census">
          <div>
            <span>{cohort.nSubjects}</span>
            patients
          </div>
          <div>
            <span>{cohort.nSamples}</span>
            samples
          </div>
          <div>
            <span>{payload.populations.length}</span>
            populations
          </div>
          <div>
            <span>{cohort.timepoints.join(", ")}</span>
            days from start
          </div>
        </div>
      </header>

      <section>
        <h2>What the comparison shows</h2>
        <div className="finding">
          <p>
            {anySignificant
              ? "At least one population separates the two groups after correction for multiple testing."
              : `No population separates responders from non-responders at any visit once the five tests per timepoint are accounted for. The closest is ${strongest?.populationLabel ?? ""} at day ${strongest?.timepoint ?? ""}, with an adjusted p value of ${strongest?.qValue.toFixed(4) ?? ""}.`}
          </p>
          <p>
            The study is large enough to detect a standardised difference of{" "}
            {detectable.toFixed(2)} at eighty percent power, so this is a reasonably
            informative null rather than an underpowered one.
          </p>
          <p>
            Repeated samples from the same patient carry no detectable correlation. The
            largest intraclass correlation across the five populations is{" "}
            {largestIcc.toFixed(4)}, meaning two samples from one patient are no more
            alike than two samples from different patients.
          </p>
        </div>
      </section>

      <section>
        <h2>Distributions by visit</h2>
        <p className="section-note">
          Boxes span the interquartile range, the heavy line marks the median, and
          whiskers reach the furthest observation within one and a half interquartile
          ranges. The value above each pair is the adjusted p value for that comparison.
        </p>
        <div className="legend">
          <span>
            <i className="swatch" style={{ background: "#2c7fb8" }} />
            Responder
          </span>
          <span>
            <i className="swatch" style={{ background: "#d95f0e" }} />
            Non-responder
          </span>
        </div>
        <div className="figure-grid">
          {payload.populations.map((population) => (
            <BoxPlot
              key={population.id}
              populationLabel={population.label}
              timepoints={cohort.timepoints}
              distributions={payload.distributions.filter(
                (entry) => entry.population === population.id
              )}
              comparisons={payload.statistics.filter(
                (entry) => entry.population === population.id
              )}
            />
          ))}
        </div>
      </section>

      <section>
        <h2>Test results</h2>
        <div className="controls">
          <button
            type="button"
            aria-pressed={timepointFilter === "all"}
            onClick={() => setTimepointFilter("all")}
          >
            All visits
          </button>
          {cohort.timepoints.map((timepoint) => (
            <button
              key={timepoint}
              type="button"
              aria-pressed={timepointFilter === timepoint}
              onClick={() => setTimepointFilter(timepoint)}
            >
              Day {timepoint}
            </button>
          ))}
        </div>
        <StatisticsTable rows={visibleStatistics} alpha={cohort.alpha} />
      </section>

      <section>
        <h2>Baseline subset</h2>
        <p className="section-note">{subsets.baseline_cohort.description}.</p>
        <table>
          <caption>
            Composition of the {subsets.baseline_cohort.n_samples} baseline samples,
            drawn from {subsets.baseline_cohort.n_subjects} patients.
          </caption>
          <thead>
            <tr>
              <th scope="col">Grouping</th>
              <th scope="col">Category</th>
              <th scope="col">Patients</th>
              <th scope="col">Samples</th>
            </tr>
          </thead>
          <tbody>
            {subsets.samples_per_project.map((row) => (
              <tr key={`project-${row.project}`}>
                <td>Project</td>
                <td style={{ textAlign: "right" }}>{row.project}</td>
                <td>{row.n_subjects}</td>
                <td>{row.n_samples}</td>
              </tr>
            ))}
            {subsets.subjects_by_response.map((row) => (
              <tr key={`response-${row.response}`}>
                <td>Response</td>
                <td style={{ textAlign: "right" }}>
                  {row.response === "yes" ? "Responder" : "Non-responder"}
                </td>
                <td>{row.n_subjects}</td>
                <td>{row.n_samples}</td>
              </tr>
            ))}
            {subsets.subjects_by_sex.map((row) => (
              <tr key={`sex-${row.sex}`}>
                <td>Sex</td>
                <td style={{ textAlign: "right" }}>
                  {row.sex === "M" ? "Male" : "Female"}
                </td>
                <td>{row.n_subjects}</td>
                <td>{row.n_samples}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <footer>
        <p>
          Generated {payload.generatedOn} from the pipeline in this repository. Every
          figure on this page is read from the analysis output rather than computed in
          the browser.
        </p>
      </footer>
    </div>
  );
}
