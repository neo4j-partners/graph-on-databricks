import { cn } from "@/lib/utils";

export type RiskLetter = "H" | "M" | "L";

export interface RiskBarProps {
  score: number;
  risk?: RiskLetter;
  width?: number;
  showValue?: boolean;
  className?: string;
}

const riskColorVar: Record<RiskLetter, string> = {
  H: "var(--color-risk-high)",
  M: "var(--color-risk-med)",
  L: "var(--color-risk-low)",
};

function deriveRisk(score: number): RiskLetter {
  if (score >= 0.75) return "H";
  if (score >= 0.5) return "M";
  return "L";
}

export function RiskBar({
  score,
  risk,
  width = 120,
  showValue = true,
  className,
}: RiskBarProps) {
  const clamped = Math.max(0, Math.min(1, score));
  const letter = risk ?? deriveRisk(clamped);
  const fillColor = riskColorVar[letter];

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className="h-1.5 rounded-sm bg-canvas-soft border border-line overflow-hidden"
        style={{ width: `${width}px` }}
      >
        <div
          className="h-full rounded-sm"
          style={{
            width: `${clamped * 100}%`,
            backgroundColor: fillColor,
          }}
        />
      </div>
      {showValue && (
        <span className="font-mono text-[11px] text-ink-2 tabular-nums">
          {clamped.toFixed(2)}
        </span>
      )}
    </div>
  );
}

export default RiskBar;
