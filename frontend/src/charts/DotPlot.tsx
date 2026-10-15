import { scaleLinear } from "d3-scale";

/** Quantile dot plot (ux-design §0.3/§5.4): N equally likely historical quantiles, "k of N" — never a probability. */
export interface DotPlotProps {
  label: string;
  /** Quantile values as fractions (decimal strings), sorted ascending; length = number of dots (20 by default). */
  quantiles: string[];
  /** Pre-formatted display strings matching `quantiles` (from the API — the UI never computes them). */
  displays: string[];
  /** Target line; `hits` is the engine-computed "k of N" count (the UI never counts or computes outcomes). */
  target?: { value: string; display: string; label: string; hits: number } | null;
  baseline?: { value: string; display: string; label: string } | null;
  width?: number;
}

export function DotPlot({ label, quantiles, displays, target, baseline, width = 560 }: DotPlotProps) {
  const vals = quantiles.map(Number); // display geometry only; values are already final
  const extras = [target, baseline].filter(Boolean).map((x) => Number(x?.value));
  const lo = Math.min(...vals, ...extras);
  const hi = Math.max(...vals, ...extras);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  const height = 120;
  const x = scaleLinear()
    .domain([lo - pad, hi + pad])
    .range([24, width - 24]);
  const r = 6;
  // Stack dots that collide horizontally.
  const placed: { cx: number; cy: number }[] = [];
  vals.forEach((v) => {
    const cx = x(v);
    let level = 0;
    while (placed.some((p) => Math.abs(p.cx - cx) < 2 * r && p.cy === height - 40 - level * 2 * r)) level += 1;
    placed.push({ cx, cy: height - 40 - level * 2 * r });
  });
  const ticks = x.ticks(5);

  return (
    <figure className="chart">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        role="img"
        aria-label={`${label}. ${vals.length} equally likely historical outcomes from ${displays[0]} to ${displays[displays.length - 1]}.`}
      >
        <line x1={24} x2={width - 24} y1={height - 28} y2={height - 28} className="axis" />
        {ticks.map((t) => (
          <g key={t}>
            <line x1={x(t)} x2={x(t)} y1={height - 28} y2={height - 24} className="axis" />
            <text x={x(t)} y={height - 10} className="tick" textAnchor="middle">
              {(t * 100).toFixed(1)}%
            </text>
          </g>
        ))}
        {baseline ? (
          <g>
            <line x1={x(Number(baseline.value))} x2={x(Number(baseline.value))} y1={8} y2={height - 28} className="ref-line" />
            <text x={x(Number(baseline.value)) + 4} y={16} className="tick">
              {baseline.label}
            </text>
          </g>
        ) : null}
        {target ? (
          <g>
            <line x1={x(Number(target.value))} x2={x(Number(target.value))} y1={8} y2={height - 28} className="target-line" />
            <text
              x={x(Number(target.value)) + (x(Number(target.value)) > width * 0.7 ? -4 : 4)}
              y={28}
              className="tick"
              textAnchor={x(Number(target.value)) > width * 0.7 ? "end" : "start"}
            >
              {target.label}
            </text>
          </g>
        ) : null}
        {placed.map((p, i) => (
          // Not focusable: an svg role="img" has presentational children, so per-dot labels were 20 silent Tab stops
          // (WCAG 4.1.2). The svg's own label summarises the range; "View as table" lists every dot. The <title> is a
          // mouse tooltip only.
          <circle key={i} cx={p.cx} cy={p.cy} r={r - 0.5} className="dot">
            <title>{`Outcome ${i + 1} of ${vals.length}: ${displays[i]}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="small">
        {label}. Each dot is one of {vals.length} equally likely historical outcomes — a historical frequency, not a forecast.
        {target ? ` Reached or beat the target in ${target.hits} of ${vals.length}.` : ""}
      </figcaption>
      <details className="small">
        <summary>View as table</summary>
        <table className="table table--compact">
          <thead>
            <tr>
              <th scope="col">Quantile</th>
              <th scope="col" className="num">
                Outcome
              </th>
            </tr>
          </thead>
          <tbody>
            {displays.map((d, i) => (
              <tr key={i}>
                <td>
                  {i + 1} of {displays.length}
                </td>
                <td className="num">{d}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
