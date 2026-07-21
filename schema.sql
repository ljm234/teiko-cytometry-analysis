-- Schema for clinical trial cytometry data.
--
-- Design rationale
-- ----------------
-- The source data is a denormalised flat file in which every row carries both
-- sample-level measurements and the full set of subject-level attributes. Because
-- each subject contributes multiple longitudinal samples, subject attributes are
-- repeated verbatim across rows. Profiling the source file confirms that project,
-- condition, age, sex, treatment and response are invariant within a subject: no
-- subject in the dataset carries conflicting values for any of them.
--
-- The schema therefore separates the three natural entities: project, subject and
-- sample, with cell counts stored in long format keyed by sample and population.
-- Subject attributes are stored exactly once, which makes contradictory values
-- structurally impossible rather than merely unlikely.
--
-- Long-format counts are preferred over one column per population because adding a
-- new immune population becomes a data insert instead of a schema migration. Panels
-- differ between studies, so this is the difference between a schema that survives
-- the next assay and one that does not.

PRAGMA foreign_keys = ON;

CREATE TABLE project (
    project_id   TEXT PRIMARY KEY,
    project_name TEXT NOT NULL
) STRICT;

CREATE TABLE subject (
    subject_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES project(project_id) ON DELETE RESTRICT,
    condition  TEXT NOT NULL,
    age        INTEGER NOT NULL CHECK (age >= 0 AND age <= 130),
    sex        TEXT NOT NULL CHECK (sex IN ('M', 'F')),
    treatment  TEXT NOT NULL,
    -- NULL is the correct representation for untreated healthy controls: response
    -- to a treatment is undefined when no treatment was administered. This is a
    -- structural NULL, not missing data.
    response   TEXT CHECK (response IN ('yes', 'no'))
) STRICT;

CREATE TABLE sample (
    sample_id                 TEXT PRIMARY KEY,
    subject_id                TEXT NOT NULL REFERENCES subject(subject_id) ON DELETE CASCADE,
    sample_type               TEXT NOT NULL,
    time_from_treatment_start INTEGER NOT NULL CHECK (time_from_treatment_start >= 0)
) STRICT;

CREATE TABLE cell_population (
    population_id TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL
) STRICT;

CREATE TABLE cell_count (
    sample_id     TEXT NOT NULL REFERENCES sample(sample_id) ON DELETE CASCADE,
    population_id TEXT NOT NULL REFERENCES cell_population(population_id) ON DELETE RESTRICT,
    count         INTEGER NOT NULL CHECK (count >= 0),
    PRIMARY KEY (sample_id, population_id)
) STRICT;

-- Indices target the access patterns the analyses actually use: cohort filtering on
-- subject attributes, timepoint filtering on samples, and joins from counts back to
-- their sample.
CREATE INDEX idx_subject_project   ON subject(project_id);
CREATE INDEX idx_subject_cohort    ON subject(condition, treatment, response);
CREATE INDEX idx_subject_sex       ON subject(sex);
CREATE INDEX idx_sample_subject    ON sample(subject_id);
CREATE INDEX idx_sample_type_time  ON sample(sample_type, time_from_treatment_start);
CREATE INDEX idx_cell_count_sample ON cell_count(sample_id);

-- Relative frequency is derived, never stored, so it cannot drift out of sync with
-- the counts it is computed from. The window function computes each sample total in
-- a single pass over the table.
CREATE VIEW sample_population_frequency AS
SELECT
    cc.sample_id                                             AS sample,
    SUM(cc.count) OVER (PARTITION BY cc.sample_id)           AS total_count,
    cc.population_id                                         AS population,
    cc.count                                                 AS count,
    100.0 * cc.count / SUM(cc.count) OVER (PARTITION BY cc.sample_id) AS percentage
FROM cell_count cc;

-- Convenience view flattening the entity split back into one analysis-ready row per
-- sample and population, so downstream queries do not repeat the same four joins.
CREATE VIEW sample_analysis AS
SELECT
    s.sample_id                  AS sample,
    s.sample_type,
    s.time_from_treatment_start,
    sub.subject_id,
    sub.condition,
    sub.age,
    sub.sex,
    sub.treatment,
    sub.response,
    p.project_id                 AS project,
    f.population,
    f.count,
    f.total_count,
    f.percentage
FROM sample s
JOIN subject sub ON sub.subject_id = s.subject_id
JOIN project p   ON p.project_id   = sub.project_id
JOIN sample_population_frequency f ON f.sample = s.sample_id;
