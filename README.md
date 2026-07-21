# Cytometry analysis, melanoma cohort

A reproducible pipeline that loads clinical cytometry data into a relational database,
compares immune cell population frequencies between patients who responded to treatment
and those who did not, and publishes the result as an interactive dashboard.

**Dashboard:** https://ljm234.github.io/teiko-cytometry-analysis/

## The headline result

No immune cell population separates responders from non-responders at any visit, once
the five tests performed at each timepoint are accounted for. The closest comparison is
B cell frequency at day 14, with an adjusted p value of 0.0721.

That null deserves two qualifications. The study can detect a standardised difference of
0.22 at eighty percent power, so it is informative rather than merely underpowered. And
B cell frequency does show a consistent trend across the fortnight, moving from p = 0.55
at day 0 to p = 0.01 at day 14, which a longitudinal mixed model estimates as a
divergence of 0.061 percentage points per day with a confidence interval that excludes
zero. The trend is real; the evidence that it separates the groups is not yet strong
enough to survive correction for multiple testing.

## Running it

The pipeline needs Python 3.12 or newer. The dashboard needs Node 22 or newer.

### In GitHub Codespaces

Open the repository on GitHub, press the green **Code** button, choose the
**Codespaces** tab and create a codespace on `main`. When the terminal is ready:

```bash
make setup      # create a virtual environment and install dependencies
make pipeline   # load the data and produce every table, figure and payload
make dashboard  # serve the dashboard
```

Codespaces will offer to forward port 5173 once the dashboard starts. Accept, then open
the forwarded address in a browser.

### Locally

```bash
git clone https://github.com/ljm234/teiko-cytometry-analysis.git
cd teiko-cytometry-analysis
make setup
make pipeline
make dashboard
```

`make test` runs the test suite. `make clean` removes generated artefacts without
touching anything tracked by git.

Dependencies install into a project local `.venv`, so the system interpreter is left
alone. Recent releases of pip refuse to install into an externally managed interpreter,
which is the default on macOS under Homebrew and on several Linux distributions, and a
virtual environment sidesteps that entirely.

## What the pipeline produces

Running `make pipeline` writes ten tables to `outputs/tables`, six figures to
`outputs/figures`, and the payload the dashboard reads. All of them are committed, so
the results can be inspected without running anything.

| Output | Contents |
| --- | --- |
| `cell_frequencies.csv` | Relative frequency of each population in each sample, 52500 rows |
| `responder_comparison_by_timepoint.csv` | Primary analysis, one row per population and visit |
| `responder_comparison_pooled.csv` | Secondary analysis pooling all visits, for comparison |
| `mixed_model_summary.csv` | Longitudinal mixed model, one row per population |
| `intraclass_correlation.csv` | Repeated measures correlation for each population |
| `power_analysis.csv` | Minimum detectable effect at each visit |
| `baseline_*.csv`, `subset_analysis.json` | Composition of the baseline subset |
| `*_response_boxplot.png` | One figure per population, three visits side by side |

## Database schema

The source file is a flat table where every row repeats the project, the subject and all
of that subject's attributes. That layout makes three kinds of error easy: a subject can
be recorded as male in one row and female in another, a population can be added to one
sample and forgotten in the next, and any correction has to be applied to every row that
mentions the same subject. The schema below removes all three by storing each fact once.

```
project --< subject --< sample --< cell_count >-- cell_population
```

| Table | Holds | Key |
| --- | --- | --- |
| `project` | One row per study | `project_id` |
| `subject` | Patient attributes: condition, age, sex, treatment, response | `subject_id` |
| `sample` | One blood draw: type and days from treatment start | `sample_id` |
| `cell_population` | The five populations, with display labels | `population_id` |
| `cell_count` | One measured count | `(sample_id, population_id)` |

Two design decisions are worth stating explicitly.

**Counts are stored long rather than wide.** The source file gives each population its
own column, which means adding a sixth population would require altering the table and
every query that names the columns. Storing one row per sample and population makes that
a data change instead of a schema change, and it is the shape every downstream query
wants anyway.

**Response is nullable, and the null means something.** A healthy volunteer who received
no treatment has not failed to respond; the question does not apply. Storing `NULL`
rather than an empty string keeps that distinction, and a `CHECK` constraint confirms
that the only subjects with a null response are untreated healthy controls.

Every table is declared `STRICT`, so SQLite enforces column types instead of silently
coercing them. Foreign keys, range checks on age and timepoint, and membership checks on
sex and response are all declared in the schema, and six indices cover the access
patterns the analysis uses.

### Scaling to hundreds of projects and thousands of samples

The current file holds three projects, 3500 subjects and 10500 samples, which SQLite
handles comfortably. The structure was chosen so that growth changes the engine rather
than the model.

Storage grows linearly: a hundred projects at this density would be roughly two million
count rows, still well inside what SQLite serves from a laptop. The queries that matter
filter on condition, treatment, sample type and timepoint, all of which are indexed, and
the aggregate views push the work into the database rather than pulling rows into
Python.

Beyond that, the migration path is a change of engine, not of design. The same tables
move to PostgreSQL unchanged, at which point `sample` can be partitioned by project and
`cell_count` by sample range. The long format is what makes this work: a new marker
panel arrives as new rows in `cell_population` and `cell_count`, with no migration and
no change to any query that groups by population.

Two further additions would matter at that scale and are deliberately absent here, since
neither earns its complexity on ten thousand samples: a batch or instrument table, to
let the analysis adjust for the run a sample was measured on, and an explicit visit
table if the study moves off a fixed three visit schedule.

## Code structure

```
load_data.py              Build the database from the source file
schema.sql                Table definitions, constraints and views
analysis/
  database.py             Connection helpers and shared constants
  frequencies.py          Part 2, relative frequency table
  statistics.py           Part 3, comparison between response groups
  mixed_models.py         Part 3, longitudinal confirmation
  figures.py              Part 3, boxplots
  subsets.py              Part 4, subset queries
  export_dashboard.py     Payload for the dashboard
dashboard/                React and TypeScript front end
tests/                    Test suite, 41 tests
```

`load_data.py` takes no arguments and is idempotent: it rebuilds the database from
scratch on every run, so there is no partial state to reason about. Every field is
validated before anything is inserted, and a malformed file produces a message naming
the line and the offending value rather than a stack trace. The schema constraints
remain as a second layer, because they also protect against anything written to the
database by another route.

Each analysis module runs standalone with `python -m analysis.<name>` and writes its own
outputs, so a single stage can be re-run without repeating the rest.

The dashboard is a static front end. It reads one JSON document produced by the pipeline
and renders it, with no server process and no database connection at browse time. That
removes a whole class of failure: there is no API to be unreachable and no version skew
between the analysis and what is displayed. Boxplots are drawn as SVG from the five
number summaries the pipeline computes, rather than through a charting library that
would form its own opinion about how to calculate quartiles.

## Statistical approach

The primary analysis compares responders against non-responders separately within each
timepoint, using a Mann-Whitney U test, and adjusts across the five populations tested
at that visit with the Benjamini-Hochberg procedure.

**Why the visits are analysed separately.** Pooling all three collapses the treatment
course into a single number. B cell frequency moves from p = 0.55 at day 0 to p = 0.01 at
day 14, a pattern the pooled test averages away, and the clinical question is precisely
whether the groups separate as treatment progresses. Within a single visit each subject
also appears exactly once, so the independence assumption holds by construction.

**Whether pooling would have been wrong is answered rather than assumed.** The one way
intraclass correlation is computed for every population and reported alongside the
results. It is at or below zero throughout, the largest being -0.0086, meaning two
samples from the same patient are no more alike than two samples from different
patients. Pooling would not have inflated the error rate here. It would simply have been
less informative, and the pooled analysis is included so the difference can be seen.

The intraclass correlation uses the estimator that subtracts the within subject mean
square, `(MSB - MSW) / (MSB + (k - 1) * MSW)`. A ratio built from raw variances is biased
upwards and returns roughly `1 / (1 + k)` even when subjects are identical, which is 0.25
at three samples per subject and is easily mistaken for a real effect.

A linear mixed model with a random intercept per subject confirms the timepoint analysis
across all three visits at once. It agrees: B cell frequency diverges by 0.061 percentage
points per day, with a confidence interval that excludes zero but an adjusted p value of
0.078 that does not clear the threshold. Its random intercept variance is estimated at
zero for every population, which is a fourth independent line of evidence that the
repeated samples carry no subject level structure.

## Notes on the data

**The task description and the file disagree on three column names.** The description
refers to `sample_id`, `indication` and `gender`; the file provides `sample`, `condition`
and `sex`. The code follows the file, since that is what has to load. The database uses
`sample_id` internally as a primary key name, which matches the description's intent
without renaming anything on the way in.

**Two of the fourteen subset questions widen the filter rather than narrowing it.** The
final question asks for melanoma males across all sample types and all treatments, so
whole blood is included alongside PBMC and phauximab alongside miraclib. The answer is
10206.15 B cells on average across 485 baseline samples.

**One value differs in its tenth decimal place between machines.** The adjusted p value
for the B cell mixed model reads 0.0781791349 under scipy 1.18 and 0.0781791350 under
scipy 1.17. Both are the same number to the precision a float64 can represent; the
difference is a single unit in the last place, arising from how each release evaluates
the t distribution. It is deterministic on any given machine and changes no conclusion.
Rounding it away would hide a real property of floating point arithmetic rather than fix
anything, so it is documented instead.

## Tests

`make test` runs 41 tests covering the loader, the frequency calculation, the statistical
functions and the subset queries. The suite checks properties rather than pinning
outputs: that percentages sum to one hundred within every sample, that the
Benjamini-Hochberg adjustment never decreases with rank and never falls below the raw
value, that the effect size reaches its bounds under complete separation, and that
seventeen kinds of malformed input each produce an actionable message rather than a
traceback.

Continuous integration runs the full pipeline and the test suite on every push, and
rebuilds and republishes the dashboard.

## Licence

MIT. See `LICENSE`.
