import type { components } from "@/lib/api/schema";
import { formatNumber } from "@/lib/format";

type Bin = components["schemas"]["HistogramBin"];

/** A small distribution sketch drawn from the profile's real histogram counts. */
export function MiniHistogram({ bins, label }: { bins: Bin[]; label: string }) {
  const max = Math.max(...bins.map((bin) => bin.count), 1);
  const width = 120;
  const height = 28;
  const barWidth = width / bins.length;
  const first = bins[0];
  const last = bins[bins.length - 1];
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Distribution of ${label} from ${formatNumber(first.start)} to ${formatNumber(last.end)}`}
      className="block"
    >
      {bins.map((bin, index) => {
        const barHeight = bin.count === 0 ? 0 : Math.max(1.5, (bin.count / max) * height);
        return (
          <rect
            key={index}
            x={index * barWidth + 0.5}
            y={height - barHeight}
            width={Math.max(barWidth - 1, 1)}
            height={barHeight}
            fill="var(--color-slate)"
            opacity={0.55}
          >
            <title>
              {`${formatNumber(bin.start)} to ${formatNumber(bin.end)}: ${bin.count.toLocaleString("en-US")}`}
            </title>
          </rect>
        );
      })}
    </svg>
  );
}
