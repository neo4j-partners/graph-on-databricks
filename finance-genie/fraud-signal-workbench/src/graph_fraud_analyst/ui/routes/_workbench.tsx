import { createFileRoute, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { Shell } from "@/components/Shell";
import { FlowProvider } from "@/lib/flowContext";

export const Route = createFileRoute("/_workbench")({
  component: WorkbenchLayout,
});

function pathToStep(path: string): 1 | 2 | 3 {
  if (path.startsWith("/load")) return 2;
  if (path.startsWith("/analyze")) return 3;
  return 1;
}

function stepToPath(step: 1 | 2 | 3): "/search" | "/load" | "/analyze" {
  if (step === 2) return "/load";
  if (step === 3) return "/analyze";
  return "/search";
}

function WorkbenchLayout() {
  const navigate = useNavigate();
  const path = useRouterState({ select: (s) => s.location.pathname });
  const step = pathToStep(path);

  return (
    <FlowProvider>
      <Shell
        step={step}
        onJump={(s) => navigate({ to: stepToPath(s) })}
        user="J. Lin · Financial Crimes"
      >
        <Outlet />
      </Shell>
    </FlowProvider>
  );
}
