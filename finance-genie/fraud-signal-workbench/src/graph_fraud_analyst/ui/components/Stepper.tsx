import * as React from "react";
import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type Step = 1 | 2 | 3;

export interface StepperProps {
  current: Step;
  onJump?: (step: Step) => void;
  className?: string;
}

const stepLabels: Record<Step, string> = {
  1: "Search",
  2: "Load",
  3: "Analyze",
};

type StepState = "past" | "current" | "future";

function stateFor(step: Step, current: Step): StepState {
  if (step < current) return "past";
  if (step === current) return "current";
  return "future";
}

interface StepItemProps {
  step: Step;
  state: StepState;
  onJump?: (step: Step) => void;
}

function StepItem({ step, state, onJump }: StepItemProps) {
  const circleClasses = cn(
    "h-6 w-6 rounded-full grid place-items-center text-xs",
    state === "current" && "bg-accent-ink text-white",
    state === "past" && "bg-good text-white",
    state === "future" &&
      "bg-canvas border border-line-2 text-muted-ink",
  );

  const labelClasses = cn(
    "text-xs",
    state === "current" && "text-ink font-medium",
    state === "past" && "text-ink-2",
    state === "future" && "text-muted-ink",
  );

  const inner = (
    <>
      <span className={circleClasses}>
        {state === "past" ? <Check className="h-3.5 w-3.5" /> : step}
      </span>
      <span className={labelClasses}>{stepLabels[step]}</span>
    </>
  );

  if (onJump) {
    return (
      <button
        type="button"
        onClick={() => onJump(step)}
        className="flex items-center gap-2 cursor-pointer"
      >
        {inner}
      </button>
    );
  }

  return <div className="flex items-center gap-2">{inner}</div>;
}

export function Stepper({ current, onJump, className }: StepperProps) {
  const steps: Step[] = [1, 2, 3];
  return (
    <div className={cn("flex items-center gap-3", className)}>
      {steps.map((step, idx) => (
        <React.Fragment key={step}>
          <StepItem step={step} state={stateFor(step, current)} onJump={onJump} />
          {idx < steps.length - 1 && <span className="h-px w-8 bg-line" />}
        </React.Fragment>
      ))}
    </div>
  );
}

export default Stepper;
