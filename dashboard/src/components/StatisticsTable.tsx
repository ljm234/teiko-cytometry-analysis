import type { Comparison } from "../types";

interface Props {
  rows: Comparison[];
  alpha: number;
}

export function StatisticsTable({ rows, alpha }: Props) {
  return (
    <table>
      <caption>
        Mann-Whitney U tests within each timepoint. The adjusted column controls the
        false discovery rate across the five populations tested at that visit, and
        significance is judged on it rather than on the raw value.
      </caption>
      <thead>
        <tr>
          <th scope="col">Population</th>
          <th scope="col">Day</th>
          <th scope="col">Median R</th>
          <th scope="col">Median NR</th>
          <th scope="col">Shift</th>
          <th scope="col">Effect</th>
          <th scope="col">p</th>
          <th scope="col">Adjusted p</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={`${row.population}-${row.timepoint}`}>
            <td>{row.populationLabel}</td>
            <td>{row.timepoint}</td>
            <td>{row.medianResponders.toFixed(2)}</td>
            <td>{row.medianNonResponders.toFixed(2)}</td>
            <td>{row.shift >= 0 ? `+${row.shift.toFixed(2)}` : row.shift.toFixed(2)}</td>
            <td>{row.effectSize.toFixed(3)}</td>
            <td>{row.pValue.toFixed(4)}</td>
            <td style={{ fontWeight: row.qValue < alpha ? 700 : 400 }}>
              {row.qValue.toFixed(4)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
