import { RingThumb } from "@/components/RingThumb";
import type { RingOut } from "@/lib/api";
import { RISK_COLOR, RISK_LABEL } from "@/lib/riskColors";
import { cn } from "@/lib/utils";

interface FraudRingCardProps {
  ring: RingOut;
  selected: boolean;
  onToggle: (ringId: string) => void;
}

interface RingMetrics {
  densityLabel: "Low" | "Med" | "High";
  edgeCount: number;
  hubCount: number;
  maxDegree: number;
  nodeCount: number;
  shownCount: number;
}

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function riskPercent(score: number) {
  return Math.round(Math.max(0, Math.min(1, score)) * 100);
}

function ringMetrics(ring: RingOut): RingMetrics {
  const graphNodes = ring.graph?.nodes ?? [];
  const graphEdges = ring.graph?.edges ?? [];
  const nodeCount = Math.max(ring.nodes, graphNodes.length);
  const degrees = new Map(graphNodes.map((node) => [node.id, 0]));

  graphEdges.forEach((edge) => {
    if (degrees.has(edge.source)) {
      degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    }
    if (degrees.has(edge.target)) {
      degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
    }
  });

  const degreeValues = [...degrees.values()];
  const maxDegree = degreeValues.length ? Math.max(...degreeValues) : 0;
  const fallbackHubThreshold = Math.max(3, maxDegree * 0.5);
  const hubCount = degreeValues.filter(
    (degree) => degree >= fallbackHubThreshold,
  ).length;
  const possibleEdges = Math.max(1, (nodeCount * (nodeCount - 1)) / 2);
  const density = graphEdges.length / possibleEdges;
  const densityLabel = density >= 0.12 ? "High" : density >= 0.04 ? "Med" : "Low";

  return {
    densityLabel,
    edgeCount: graphEdges.length,
    hubCount,
    maxDegree,
    nodeCount,
    shownCount: Math.min(graphNodes.length || nodeCount, 40),
  };
}

function evidenceHeadline(metrics: RingMetrics) {
  const accounts = `${metrics.nodeCount.toLocaleString()} accounts`;
  if (metrics.hubCount >= 3) return `${metrics.hubCount} hub accounts`;
  if (metrics.maxDegree >= 5) return `Hub-led - ${accounts}`;
  if (metrics.densityLabel === "High") return `High density - ${accounts}`;
  if (metrics.nodeCount >= 100) return `${accounts} - ${metrics.densityLabel} density`;
  if (metrics.edgeCount >= metrics.nodeCount) {
    return `${metrics.edgeCount.toLocaleString()} links - ${accounts}`;
  }
  return `Connected - ${accounts}`;
}

function evidenceMeaning(ring: RingOut, metrics: RingMetrics) {
  const sharedIds = ring.shared_identifiers.length
    ? ring.shared_identifiers.join(", ")
    : "shared identifiers";

  if (metrics.maxDegree >= 5) {
    return `Highest-degree account connects to ${metrics.maxDegree} peers`;
  }
  if (metrics.densityLabel === "High") {
    return `High connection density across ${metrics.nodeCount.toLocaleString()} accounts`;
  }
  if (metrics.nodeCount >= 100) {
    return `${metrics.nodeCount.toLocaleString()} accounts linked by ${sharedIds}`;
  }
  if (metrics.edgeCount >= metrics.nodeCount) {
    return `${metrics.edgeCount.toLocaleString()} relationships among ${metrics.nodeCount.toLocaleString()} accounts`;
  }
  return "Connected accounts require review";
}

function MetricChip({
  label,
  value,
  tooltip,
}: {
  label: string;
  value: string;
  tooltip: string;
}) {
  return (
    <span
      className="min-w-0 rounded border border-line bg-surface px-1.5 py-1 text-center text-[10px] leading-tight text-muted-ink transition-colors hover:border-line-3"
      title={tooltip}
      aria-label={`${value} ${label}. ${tooltip}`}
    >
      <strong className="block truncate text-[11px] font-semibold text-ink">
        {value}
      </strong>
      {label}
    </span>
  );
}

export function FraudRingCard({
  ring,
  selected,
  onToggle,
}: FraudRingCardProps) {
  const metrics = ringMetrics(ring);
  const sharedIds = ring.shared_identifiers.length
    ? ring.shared_identifiers.slice(0, 3)
    : ["No shared id"];
  const hiddenCount = Math.max(0, metrics.nodeCount - metrics.shownCount);
  const risk = riskPercent(ring.risk_score);
  const riskColor = RISK_COLOR[ring.risk];
  const graphNote =
    hiddenCount > 0
      ? `Top ${metrics.shownCount} risk-ranked accounts shown, ${hiddenCount.toLocaleString()} more in cluster`
      : `${metrics.shownCount.toLocaleString()} accounts shown`;

  return (
    <button
      type="button"
      onClick={() => onToggle(ring.ring_id)}
      aria-pressed={selected}
      aria-label={`${selected ? "Deselect" : "Select"} fraud ring ${ring.ring_id}, ${risk} percent risk, ${metrics.nodeCount.toLocaleString()} accounts`}
      data-testid={`ring-card-${ring.ring_id}`}
      className={cn(
        "group flex min-h-[276px] flex-col overflow-hidden rounded-md border-2 bg-canvas-soft text-left transition-colors hover:border-accent-ink/50 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        selected
          ? "border-accent-ink bg-accent-soft"
          : "border-line-2",
      )}
    >
      <div className="flex items-start justify-between gap-3 px-3 pt-2">
        <div className="min-w-0">
          <div className="truncate font-mono text-xs font-bold text-ink">
            {ring.ring_id}
          </div>
          <div className="mt-0.5 truncate text-[11px] font-semibold text-muted-ink">
            {evidenceHeadline(metrics)}
          </div>
        </div>
        <div className="shrink-0 text-right leading-none" style={{ color: riskColor }}>
          <strong className="block text-lg font-bold">{risk}</strong>
          <span className="mt-0.5 block text-[9px] font-bold uppercase tracking-wide text-muted-ink">
            Risk
          </span>
        </div>
      </div>

      <div className="px-3 pb-2 pt-2">
        <div
          className="h-1 overflow-hidden rounded-full bg-line"
          role="meter"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={risk}
          aria-label={`Risk score ${risk} percent, ${RISK_LABEL[ring.risk]}`}
        >
          <span
            className="block h-full rounded-full"
            style={{ width: `${risk}%`, backgroundColor: riskColor }}
          />
        </div>

        <div className="mt-2 grid grid-cols-4 gap-1.5">
          <MetricChip
            value={metrics.nodeCount.toLocaleString()}
            label="accounts"
            tooltip="Number of accounts assigned to this detected fraud-ring community."
          />
          <MetricChip
            value={metrics.hubCount.toLocaleString()}
            label="hubs"
            tooltip="Accounts with the strongest centrality signal inside this ring."
          />
          <MetricChip
            value={metrics.densityLabel}
            label="density"
            tooltip="How connected the cluster is relative to its size."
          />
          <MetricChip
            value={currency.format(ring.volume)}
            label="volume"
            tooltip="Total transaction volume represented by accounts in this ring."
          />
        </div>

        <div className="mt-2 flex flex-wrap gap-1">
          {sharedIds.map((id) => (
            <span
              key={id}
              className="rounded bg-accent-soft px-1.5 py-0.5 text-[10px] font-semibold text-accent-ink"
            >
              {id}
            </span>
          ))}
        </div>
      </div>

      <div className="relative mt-auto min-h-[156px] bg-surface">
        <div className="absolute left-3 right-3 top-2 z-10 truncate text-[11px] font-semibold text-ink-2">
          {evidenceMeaning(ring, metrics)}
        </div>
        <div className="flex h-[156px] items-center justify-center px-2 pt-4">
          <RingThumb
            ring={{
              ring_id: ring.ring_id,
              nodes: ring.nodes,
              topology: ring.topology,
              risk: ring.risk,
              graph: ring.graph,
            }}
            width={260}
            height={132}
            selected={selected}
          />
        </div>
        <div className="absolute bottom-2 left-3 right-3 truncate text-[10px] text-muted-ink">
          {graphNote}
        </div>
      </div>
    </button>
  );
}

export default FraudRingCard;
