import type * as React from "react";
import { cn } from "@/lib/utils";

export type PillIntent =
  | "default"
  | "accent"
  | "mono"
  | "risk-high"
  | "risk-med"
  | "risk-low";

export interface PillProps {
  children: React.ReactNode;
  intent?: PillIntent;
  className?: string;
}

const intentClasses: Record<PillIntent, string> = {
  default: "bg-canvas-soft text-ink-2 border-line",
  accent: "bg-accent-soft text-accent-ink border-line",
  mono: "bg-canvas-soft text-ink-2 border-line font-mono",
  "risk-high": "bg-risk-high/12 text-risk-high border-risk-high/30",
  "risk-med": "bg-risk-med/15 text-risk-med border-risk-med/35",
  "risk-low": "bg-risk-low/15 text-risk-low border-risk-low/30",
};

export function Pill({ children, intent = "default", className }: PillProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs",
        intentClasses[intent],
        className,
      )}
    >
      {children}
    </span>
  );
}

export default Pill;
