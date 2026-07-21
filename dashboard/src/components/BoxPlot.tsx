import type { Comparison, Distribution } from "../types";

const WIDTH = 460;
const HEIGHT = 300;
const MARGIN = { top: 26, right: 14, bottom: 42, left: 46 };

const COLOURS: Record<string, string> = {
  yes: "#2c7fb8",
  no: "#d95f0e"
};

interface Props {
  populationLabel: string;
  timepoints: number[];
  distributions: Distribution[];
  comparisons: Comparison[];
}

/**
 * Boxplots drawn directly rather than through a charting library.
 *
 * The pipeline has already reduced each group to the five numbers a box needs, so a
 * charting dependency would only add weight and a second opinion about how to compute
 * quartiles. Drawing the marks here keeps the browser showing exactly the summary the
 * analysis produced.
 */
export function BoxPlot({ populationLabel, timepoints, distributions, comparisons }: Props) {
  if (distributions.length === 0) {
    return null;
  }

  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const lowest = Math.min(...distributions.map((d) => d.whiskerLow));
  const highest = Math.max(...distributions.map((d) => d.whiskerHigh));
  const padding = (highest - lowest) * 0.12;
  const domainLow = Math.max(0, lowest - padding);
  const domainHigh = highest + padding;

  const toY = (value: number) =>
    MARGIN.top + plotHeight - ((value - domainLow) / (domainHigh - domainLow)) * plotHeight;

  const bandWidth = plotWidth / timepoints.length;
  const boxWidth = Math.min(46, bandWidth * 0.3);

  const ticks = Array.from({ length: 5 }, (_, index) => {
    const value = domainLow + ((domainHigh - domainLow) * index) / 4;
    return { value, y: toY(value) };
  });

  return (
    <figure style={{ margin: 0 }}>
      <svg
        className="plot"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${populationLabel} frequency by response status at each timepoint`}
      >
        {ticks.map((tick) => (
          <g key={tick.value}>
            <line
              x1={MARGIN.left}
              x2={WIDTH - MARGIN.right}
              y1={tick.y}
              y2={tick.y}
              stroke="#d8d5cc"
              strokeWidth={1}
            />
            <text
              x={MARGIN.left - 8}
              y={tick.y + 3.5}
              textAnchor="end"
              fontSize={10}
              fontFamily="ui-monospace, Menlo, monospace"
              fill="#3d5a75"
            >
              {tick.value.toFixed(0)}
            </text>
          </g>
        ))}

        {timepoints.map((timepoint, index) => {
          const centre = MARGIN.left + bandWidth * (index + 0.5);
          const comparison = comparisons.find((c) => c.timepoint === timepoint);

          return (
            <g key={timepoint}>
              {(["yes", "no"] as const).map((response, side) => {
                const entry = distributions.find(
                  (d) => d.timepoint === timepoint && d.response === response
                );
                if (!entry) {
                  return null;
                }

                const offset = side === 0 ? -boxWidth * 0.58 : boxWidth * 0.58;
                const x = centre + offset;
                const colour = COLOURS[response] ?? "#3d5a75";

                return (
                  <g key={response}>
                    <title>
                      {`${entry.populationLabel}, day ${timepoint}, ` +
                        `${response === "yes" ? "responders" : "non-responders"}: ` +
                        `median ${entry.median.toFixed(2)}%, n = ${entry.n}`}
                    </title>
                    <line
                      x1={x}
                      x2={x}
                      y1={toY(entry.whiskerHigh)}
                      y2={toY(entry.whiskerLow)}
                      stroke={colour}
                      strokeWidth={1.2}
                    />
                    <line
                      x1={x - boxWidth * 0.22}
                      x2={x + boxWidth * 0.22}
                      y1={toY(entry.whiskerHigh)}
                      y2={toY(entry.whiskerHigh)}
                      stroke={colour}
                      strokeWidth={1.2}
                    />
                    <line
                      x1={x - boxWidth * 0.22}
                      x2={x + boxWidth * 0.22}
                      y1={toY(entry.whiskerLow)}
                      y2={toY(entry.whiskerLow)}
                      stroke={colour}
                      strokeWidth={1.2}
                    />
                    <rect
                      x={x - boxWidth / 2}
                      y={toY(entry.q3)}
                      width={boxWidth}
                      height={Math.max(1, toY(entry.q1) - toY(entry.q3))}
                      fill={colour}
                      fillOpacity={0.5}
                      stroke={colour}
                      strokeWidth={1.2}
                    />
                    <line
                      x1={x - boxWidth / 2}
                      x2={x + boxWidth / 2}
                      y1={toY(entry.median)}
                      y2={toY(entry.median)}
                      stroke="#0f2942"
                      strokeWidth={1.8}
                    />
                  </g>
                );
              })}

              {comparison ? (
                <text
                  x={centre}
                  y={MARGIN.top - 10}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="ui-monospace, Menlo, monospace"
                  fill={comparison.significant ? "#0f2942" : "#3d5a75"}
                  fontWeight={comparison.significant ? 700 : 400}
                >
                  {`q = ${comparison.qValue.toFixed(3)}`}
                </text>
              ) : null}

              <text
                x={centre}
                y={HEIGHT - MARGIN.bottom + 20}
                textAnchor="middle"
                fontSize={11}
                fontFamily="ui-monospace, Menlo, monospace"
                fill="#0f2942"
              >
                {`Day ${timepoint}`}
              </text>
            </g>
          );
        })}

        <line
          x1={MARGIN.left}
          x2={MARGIN.left}
          y1={MARGIN.top}
          y2={MARGIN.top + plotHeight}
          stroke="#0f2942"
          strokeWidth={1.2}
        />
        <line
          x1={MARGIN.left}
          x2={WIDTH - MARGIN.right}
          y1={MARGIN.top + plotHeight}
          y2={MARGIN.top + plotHeight}
          stroke="#0f2942"
          strokeWidth={1.2}
        />
        <text
          x={12}
          y={MARGIN.top + plotHeight / 2}
          fontSize={10}
          fontFamily="ui-monospace, Menlo, monospace"
          fill="#3d5a75"
          transform={`rotate(-90 12 ${MARGIN.top + plotHeight / 2})`}
          textAnchor="middle"
        >
          Relative frequency (%)
        </text>
      </svg>
      <figcaption
        style={{
          fontFamily: "Georgia, serif",
          fontSize: "0.98rem",
          paddingTop: "0.4rem"
        }}
      >
        {populationLabel}
      </figcaption>
    </figure>
  );
}
