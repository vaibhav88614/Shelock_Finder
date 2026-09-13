import { memo, useMemo } from "react";
import type { SparklinePoint } from "../types";

interface Props {
  points: SparklinePoint[];
  width?: number;
  height?: number;
  strokeClassName?: string;
  fillClassName?: string;
  ariaLabel?: string;
}

/**
 * Compact inline SVG sparkline. Draws a polyline through `points`, autoscaled
 * so the min value sits at the bottom and the max value at the top of the
 * chart box. The last point gets a small marker so users can eyeball the
 * current value against the trend.
 *
 * Rendered inline (no SVG viewport queries, no external deps) so a page can
 * paint five of them without any measurable cost.
 */
export const Sparkline = memo(function Sparkline({
  points,
  width = 100,
  height = 28,
  strokeClassName = "text-slate-400 dark:text-slate-500",
  fillClassName = "text-slate-200/60 dark:text-slate-700/50",
  ariaLabel,
}: Props) {
  const { path, area, dot, hasData } = useMemo(() => {
    if (points.length === 0) {
      return { path: "", area: "", dot: null, hasData: false };
    }
    const values = points.map((p) => p.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const stepX = points.length > 1 ? width / (points.length - 1) : 0;
    const coords = points.map((p, i) => {
      const x = stepX * i;
      const y = height - ((p.value - min) / span) * (height - 4) - 2;
      return { x, y };
    });
    const line = coords
      .map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(2)},${c.y.toFixed(2)}`)
      .join(" ");
    const fill =
      coords.length > 1
        ? `${line} L${(width).toFixed(2)},${height} L0,${height} Z`
        : "";
    return {
      path: line,
      area: fill,
      dot: coords[coords.length - 1],
      hasData: true,
    };
  }, [points, width, height]);

  if (!hasData) {
    return (
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={ariaLabel ?? "no data"}
        className="opacity-30"
      >
        <line x1={0} y1={height / 2} x2={width} y2={height / 2}
              stroke="currentColor" strokeWidth={1} strokeDasharray="2 2" />
      </svg>
    );
  }

  return (
    <svg
      width={width}
      height={height}
      role="img"
      aria-label={ariaLabel ?? `sparkline of ${points.length} values`}
    >
      {area && (
        <path d={area} fill="currentColor" className={fillClassName} />
      )}
      <path d={path} fill="none" stroke="currentColor" strokeWidth={1.5}
            strokeLinecap="round" strokeLinejoin="round" className={strokeClassName} />
      {dot && (
        <circle cx={dot.x} cy={dot.y} r={1.75} fill="currentColor"
                className={strokeClassName} />
      )}
    </svg>
  );
});
