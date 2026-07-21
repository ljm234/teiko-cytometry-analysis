export interface Distribution {
  population: string;
  populationLabel: string;
  timepoint: number;
  response: "yes" | "no";
  n: number;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  whiskerLow: number;
  whiskerHigh: number;
  mean: number;
}

export interface Comparison {
  population: string;
  populationLabel: string;
  timepoint: number;
  nResponders: number;
  nNonResponders: number;
  medianResponders: number;
  medianNonResponders: number;
  shift: number;
  effectSize: number;
  pValue: number;
  qValue: number;
  significant: boolean;
}

export interface PowerEntry {
  timepoint: number;
  nResponders: number;
  nNonResponders: number;
  minimumDetectableEffect: number;
}

export interface IccEntry {
  population: string;
  populationLabel: string;
  icc1: number;
  samplesPerSubject: number;
}

export interface OverviewRow {
  condition: string;
  treatment: string;
  sample_type: string;
  n_samples: number;
  n_subjects: number;
}

export interface SubsetGroup {
  project?: string;
  response?: string;
  sex?: string;
  n_samples: number;
  n_subjects: number;
}

export interface Subsets {
  baseline_cohort: {
    description: string;
    n_samples: number;
    n_subjects: number;
  };
  samples_per_project: SubsetGroup[];
  subjects_by_response: SubsetGroup[];
  subjects_by_sex: SubsetGroup[];
  male_responder_baseline_b_cells: {
    n_samples: number;
    n_subjects: number;
    mean_b_cell_count_rounded: number;
  };
}

export interface Payload {
  generatedOn: string;
  cohort: {
    description: string;
    nSamples: number;
    nSubjects: number;
    timepoints: number[];
    alpha: number;
  };
  studyOverview: OverviewRow[];
  populations: { id: string; label: string }[];
  distributions: Distribution[];
  statistics: Comparison[];
  power: PowerEntry[];
  intraclassCorrelation: IccEntry[];
  subsets: Subsets;
}
