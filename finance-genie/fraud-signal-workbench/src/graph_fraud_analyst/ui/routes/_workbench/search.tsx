// search.tsx
// Screen 1 of the Fraud Analyst workbench. Search the Neo4j-backed FastAPI
// service for fraud rings, risky accounts, or central hub accounts. The route
// lives inside the `_workbench` pathless layout, so the URL is `/search` and
// Shell is provided by the parent.

import { Suspense, useMemo, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { QueryErrorResetBoundary } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type Column,
  type ColumnDef,
  type SortingFn,
  type SortingState,
  type Table as TanStackTable,
} from "@tanstack/react-table";
import { ErrorBoundary } from "react-error-boundary";
import {
  AlertTriangle,
  ArrowRight,
  ArrowDown,
  ArrowUp,
  ChevronsUpDown,
  Info,
  Network,
  Search as SearchIcon,
  Table2,
} from "lucide-react";

import { FraudRingCard } from "@/components/FraudRingCard";
import { Pill, type PillIntent } from "@/components/Pill";
import { RiskBar } from "@/components/RiskBar";
import { RingThumb } from "@/components/RingThumb";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  useSearchCentralAccountsSuspense,
  useSearchRingsSuspense,
  useSearchRiskAccountsSuspense,
  type HubAccountOut,
  type RingOut,
  type RiskAccountOut,
} from "@/lib/api";
import { useFlow } from "@/lib/flowContext";
import { RISK_LABEL, RISK_PILL_INTENT } from "@/lib/riskColors";
import selector from "@/lib/selector";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/_workbench/search")({
  component: SearchScreen,
});

// UI-only mode discriminator. Each mode maps to a different Suspense hook.
type Mode = "fraud_rings" | "risk_scores" | "central_accounts";
type RingResultsView = "graph" | "table";

interface ChoiceMeta {
  id: Mode;
  title: string;
  blurb: string;
  Icon: typeof SearchIcon;
}

const CHOICES: ChoiceMeta[] = [
  {
    id: "fraud_rings",
    title: "Fraud rings",
    blurb: "Communities of accounts moving money in tight loops.",
    Icon: SearchIcon,
  },
  {
    id: "risk_scores",
    title: "Risk scores",
    blurb: "Top accounts by individual risk score.",
    Icon: AlertTriangle,
  },
  {
    id: "central_accounts",
    title: "Central accounts",
    blurb: "Accounts that bridge the most paths.",
    Icon: Network,
  },
];

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const TABLE_HEAD_CLASS = "text-[11px] uppercase tracking-wide text-muted-ink";
const BAND_SORT_ORDER = {
  Low: 0,
  Medium: 1,
  High: 2,
} satisfies Record<"Low" | "Medium" | "High", number>;

declare module "@tanstack/react-table" {
  interface ColumnMeta<TData, TValue> {
    align?: "left" | "right";
    cellClassName?: string;
    className?: string;
  }
}

function bandPillIntent(band: "Low" | "Medium" | "High"): PillIntent {
  if (band === "High") return "risk-high";
  if (band === "Medium") return "risk-med";
  return "default";
}

const bandSortingFn: SortingFn<RiskAccountOut> = (rowA, rowB, columnId) => {
  const a = rowA.getValue<"Low" | "Medium" | "High">(columnId);
  const b = rowB.getValue<"Low" | "Medium" | "High">(columnId);
  return BAND_SORT_ORDER[a] - BAND_SORT_ORDER[b];
};

function SearchScreen() {
  const navigate = useNavigate();
  const {
    selectedRings,
    selectedRiskAccounts,
    selectedCentralAccounts,
    selectedSignalIds,
    toggleRing,
    toggleRiskAccount,
    toggleCentralAccount,
  } = useFlow();

  const [mode, setMode] = useState<Mode>("fraud_rings");
  const [dateRange, setDateRange] = useState("Last 30 days");
  const [minAmount, setMinAmount] = useState<number>(500);
  const [maxNodes, setMaxNodes] = useState<number>(500);

  const handleModeChange = (next: Mode) => {
    if (next === mode) return;
    setMode(next);
  };

  const continueDisabled = selectedSignalIds.length === 0;
  const selectedWord = selectedSignalIds.length === 1 ? "signal" : "signals";

  // Note: dateRange and minAmount are kept in the UI for fidelity but the
  // backend does not yet honor them; only maxNodes is part of the query key,
  // so changing it auto-refetches via React Query. The "Search Neo4j" button
  // is a visual affordance — refetch already happens implicitly via maxNodes.
  return (
    <div className="p-6 space-y-4">
      <header>
        <h1 className="text-xl font-semibold text-ink">Surface fraud signals</h1>
        <p className="text-sm text-muted-ink">
          Search the Neo4j relationship graph for suspicious structural patterns.
        </p>
      </header>

      {/* Mode card */}
      <Card className="p-4">
        <div className="mb-3">
          <div className="text-sm font-medium text-ink-2">
            What are you looking for?
          </div>
          <div className="text-xs text-muted-ink">Pick one pattern type.</div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {CHOICES.map((c) => {
            const selected = c.id === mode;
            const Icon = c.Icon;
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => handleModeChange(c.id)}
                aria-pressed={selected}
                className={cn(
                  "flex flex-col items-start text-left p-4 rounded-md border-2 transition-colors",
                  selected
                    ? "border-accent-ink bg-accent-soft text-ink"
                    : "border-line-2 bg-surface text-ink-2 hover:border-line-3",
                )}
              >
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4" />
                  <span className="text-sm font-medium">{c.title}</span>
                </div>
                <span className="text-xs text-muted-ink mt-2">{c.blurb}</span>
              </button>
            );
          })}
        </div>
      </Card>

      {/* Filters strip */}
      <Card>
        <div className="flex flex-wrap gap-3 items-end p-4">
          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wide text-muted-ink">
              Date range
            </label>
            <Select value={dateRange} onValueChange={setDateRange}>
              <SelectTrigger className="w-[170px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Last 7 days">Last 7 days</SelectItem>
                <SelectItem value="Last 30 days">Last 30 days</SelectItem>
                <SelectItem value="Last 90 days">Last 90 days</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wide text-muted-ink">
              Minimum amount
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-ink">
                $
              </span>
              <Input
                type="number"
                inputMode="numeric"
                min={0}
                value={minAmount}
                onChange={(e) => setMinAmount(Number(e.target.value))}
                className="pl-6 w-[140px] font-mono tabular-nums"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1">
            <label className="text-[11px] uppercase tracking-wide text-muted-ink">
              Max nodes
            </label>
            <Input
              type="number"
              inputMode="numeric"
              min={1}
              value={maxNodes}
              onChange={(e) => setMaxNodes(Number(e.target.value))}
              className="w-[120px] font-mono tabular-nums"
            />
          </div>

          <div className="ml-auto">
            <Button type="button">
              <SearchIcon className="h-4 w-4" />
              Search Neo4j
            </Button>
          </div>
        </div>
      </Card>

      {/* Results region: ErrorBoundary wraps Suspense, which wraps the
          mode-specific data-fetching subtree. Switching modes remounts the
          inner ResultsBody so only the active mode's hook fires. */}
      <QueryErrorResetBoundary>
        {({ reset }) => (
          <ErrorBoundary
            onReset={reset}
            fallbackRender={({ error, resetErrorBoundary }) => (
              <ErrorCard
                message={error instanceof Error ? error.message : "Search failed"}
                onRetry={resetErrorBoundary}
              />
            )}
          >
            <Suspense fallback={<ResultsSkeleton />}>
              <ResultsBody
                mode={mode}
                maxNodes={maxNodes}
                selectedRings={selectedRings}
                selectedRiskAccounts={selectedRiskAccounts}
                selectedCentralAccounts={selectedCentralAccounts}
                onToggleRing={toggleRing}
                onToggleRiskAccount={toggleRiskAccount}
                onToggleCentralAccount={toggleCentralAccount}
              />
            </Suspense>
          </ErrorBoundary>
        )}
      </QueryErrorResetBoundary>

      {/* Continue footer */}
      <div className="mt-6 flex items-center justify-between">
        <span className="text-xs text-muted-ink">
          {selectedSignalIds.length > 0
            ? `${selectedSignalIds.length} ${selectedWord} selected`
            : ""}
        </span>
        <Button
          type="button"
          disabled={continueDisabled}
          onClick={() => navigate({ to: "/load" })}
        >
          Continue to Load
          <ArrowRight className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────

interface ResultsBodyProps {
  mode: Mode;
  maxNodes: number;
  selectedRings: string[];
  selectedRiskAccounts: string[];
  selectedCentralAccounts: string[];
  onToggleRing: (ringId: string) => void;
  onToggleRiskAccount: (accountId: string) => void;
  onToggleCentralAccount: (accountId: string) => void;
}

function ResultsBody({
  mode,
  maxNodes,
  selectedRings,
  selectedRiskAccounts,
  selectedCentralAccounts,
  onToggleRing,
  onToggleRiskAccount,
  onToggleCentralAccount,
}: ResultsBodyProps) {
  if (mode === "fraud_rings") {
    return (
      <RingsBody
        maxNodes={maxNodes}
        selectedRings={selectedRings}
        onToggleRing={onToggleRing}
      />
    );
  }
  if (mode === "risk_scores") {
    return (
      <RiskBody
        selectedRiskAccounts={selectedRiskAccounts}
        onToggleRiskAccount={onToggleRiskAccount}
      />
    );
  }
  return (
    <HubBody
      selectedCentralAccounts={selectedCentralAccounts}
      onToggleCentralAccount={onToggleCentralAccount}
    />
  );
}

function RingsBody({
  maxNodes,
  selectedRings,
  onToggleRing,
}: {
  maxNodes: number;
  selectedRings: string[];
  onToggleRing: (ringId: string) => void;
}) {
  const { data: rings } = useSearchRingsSuspense({
    params: { max_nodes: maxNodes },
    ...selector<RingOut[]>(),
  });
  return (
    <RingResults
      rings={rings}
      selectedRings={selectedRings}
      onToggle={onToggleRing}
    />
  );
}

function RiskBody({
  selectedRiskAccounts,
  onToggleRiskAccount,
}: {
  selectedRiskAccounts: string[];
  onToggleRiskAccount: (accountId: string) => void;
}) {
  const { data: rows } = useSearchRiskAccountsSuspense(
    selector<RiskAccountOut[]>(),
  );
  return (
    <RiskResults
      rows={rows}
      selectedRiskAccounts={selectedRiskAccounts}
      onToggleRiskAccount={onToggleRiskAccount}
    />
  );
}

function HubBody({
  selectedCentralAccounts,
  onToggleCentralAccount,
}: {
  selectedCentralAccounts: string[];
  onToggleCentralAccount: (accountId: string) => void;
}) {
  const { data: rows } = useSearchCentralAccountsSuspense(
    selector<HubAccountOut[]>(),
  );
  return (
    <HubResults
      rows={rows}
      selectedCentralAccounts={selectedCentralAccounts}
      onToggleCentralAccount={onToggleCentralAccount}
    />
  );
}

function ResultsSkeleton() {
  return (
    <Card className="p-4 space-y-2">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </Card>
  );
}

function ErrorCard({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <Card className="p-4 flex items-start justify-between gap-4 border-risk-high/40">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-risk-high mt-0.5" />
        <div>
          <div className="text-sm font-medium text-ink">Search failed</div>
          <div className="text-xs text-muted-ink mt-1">{message}</div>
        </div>
      </div>
      <Button variant="outline" onClick={onRetry}>
        Retry
      </Button>
    </Card>
  );
}

function HeaderTooltip({
  label,
  tooltip,
  align = "left",
}: {
  label: string;
  tooltip: string;
  align?: "left" | "right";
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn(
            "inline-flex cursor-help items-center whitespace-nowrap border-b border-dotted border-muted-ink/50 leading-none outline-none focus-visible:ring-2 focus-visible:ring-ring",
            align === "right" && "ml-auto",
          )}
        >
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[240px] text-center">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  );
}

function SortableHeader<TData, TValue>({
  column,
  label,
  tooltip,
  align = "left",
}: {
  column: Column<TData, TValue>;
  label: string;
  tooltip: string;
  align?: "left" | "right";
}) {
  const sorted = column.getIsSorted();
  const SortIcon =
    sorted === "asc" ? ArrowUp : sorted === "desc" ? ArrowDown : ChevronsUpDown;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={column.getToggleSortingHandler()}
          className={cn(
            "inline-flex h-7 cursor-pointer items-center gap-1 rounded-sm border-b border-dotted border-muted-ink/50 leading-none outline-none transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-ring",
            align === "right" && "ml-auto",
          )}
          aria-label={`Sort by ${label}`}
        >
          <span>{label}</span>
          <SortIcon className="h-3 w-3" aria-hidden="true" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-[240px] text-center">
        {tooltip}
      </TooltipContent>
    </Tooltip>
  );
}

function SearchDataTable<TData>({
  table,
  getRowClassName,
}: {
  table: TanStackTable<TData>;
  getRowClassName?: (row: TData) => string | undefined;
}) {
  return (
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((headerGroup) => (
          <TableRow key={headerGroup.id}>
            {headerGroup.headers.map((header) => {
              const meta = header.column.columnDef.meta;
              const sorted = header.column.getIsSorted();
              return (
                <TableHead
                  key={header.id}
                  colSpan={header.colSpan}
                  className={cn(
                    TABLE_HEAD_CLASS,
                    meta?.align === "right" && "text-right",
                    meta?.className,
                  )}
                  aria-sort={
                    sorted === "asc"
                      ? "ascending"
                      : sorted === "desc"
                        ? "descending"
                        : undefined
                  }
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </TableHead>
              );
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow
            key={row.id}
            className={cn(
              "border-b border-line",
              getRowClassName?.(row.original),
            )}
          >
            {row.getVisibleCells().map((cell) => {
              const meta = cell.column.columnDef.meta;
              return (
                <TableCell
                  key={cell.id}
                  className={cn(
                    meta?.align === "right" && "text-right",
                    meta?.cellClassName,
                  )}
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function EmptyRingsCard() {
  return (
    <Card className="p-8 flex flex-col items-center text-center">
      <svg viewBox="0 0 220 80" width={220} height={80} aria-hidden="true">
        <g stroke="currentColor" strokeWidth={1} fill="none" className="text-line-3">
          <circle cx={40} cy={40} r={6} />
          <circle cx={90} cy={20} r={4} />
          <circle cx={105} cy={55} r={5} />
          <circle cx={155} cy={30} r={4} />
          <circle cx={180} cy={60} r={6} />
          <line x1={40} y1={40} x2={90} y2={20} />
          <line x1={40} y1={40} x2={105} y2={55} />
          <line x1={90} y1={20} x2={155} y2={30} />
          <line x1={105} y1={55} x2={180} y2={60} />
          <line x1={155} y1={30} x2={180} y2={60} />
        </g>
      </svg>
      <p className="mt-3 text-sm text-muted-ink">
        Run a search to see suspicious patterns from the graph.
      </p>
    </Card>
  );
}

function FraudRingCardGrid({
  rings,
  selectedRings,
  onToggle,
}: {
  rings: RingOut[];
  selectedRings: string[];
  onToggle: (ringId: string) => void;
}) {
  const nodeTotal = rings.reduce((sum, ring) => sum + ring.nodes, 0);

  return (
    <div className="overflow-hidden rounded-md border border-line bg-surface">
      <div className="flex h-10 items-center justify-between border-b border-line bg-canvas-soft px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-ink-2">
            Graph view
          </span>
          <span className="truncate text-xs text-muted-ink">
            {rings.length} clusters · {nodeTotal.toLocaleString()} nodes total
          </span>
        </div>
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line bg-surface text-muted-ink transition-colors hover:border-accent-ink hover:text-accent-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="What graph cards mean"
              >
                <Info className="h-3.5 w-3.5" />
              </button>
            </TooltipTrigger>
            <TooltipContent
              side="left"
              align="start"
              className="max-w-[320px] text-left leading-snug"
            >
              Cards rank fraud-ring evidence by risk, accounts, hubs, density,
              volume, and shared identifiers. Dots are accounts and lines are
              transfers inside the detected community.
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      <div className="px-4 pt-3 text-xs text-muted-ink">
        Topology stays in the table. Cards rank evidence: risk, accounts, hubs,
        density, volume, and shared identifiers.
      </div>
      <TooltipProvider delayDuration={150}>
        <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
          {rings.map((ring) => (
            <FraudRingCard
              key={ring.ring_id}
              ring={ring}
              selected={selectedRings.includes(ring.ring_id)}
              onToggle={onToggle}
            />
          ))}
        </div>
      </TooltipProvider>
    </div>
  );
}

function RingResults({
  rings,
  selectedRings,
  onToggle,
}: {
  rings: RingOut[];
  selectedRings: string[];
  onToggle: (ringId: string) => void;
}) {
  const [view, setView] = useState<RingResultsView>("graph");
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<RingOut>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: () => (
          <HeaderTooltip
            label="Select"
            tooltip="Choose fraud rings to carry forward into the load step."
          />
        ),
        cell: ({ row }) => {
          const ring = row.original;
          return (
            <Checkbox
              checked={selectedRings.includes(ring.ring_id)}
              onCheckedChange={() => onToggle(ring.ring_id)}
              aria-label={`Select ${ring.ring_id}`}
            />
          );
        },
        meta: { className: "w-10" },
      },
      {
        accessorKey: "ring_id",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Ring"
            tooltip="Graph community identifier returned by the fraud-ring search."
          />
        ),
        cell: ({ row }) => <Pill intent="mono">{row.original.ring_id}</Pill>,
      },
      {
        accessorKey: "topology",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Topology"
            tooltip="Preview of the ring shape and the structural pattern found in the graph."
          />
        ),
        cell: ({ row }) => {
          const ring = row.original;
          return (
            <div className="flex flex-col items-start">
              <RingThumb
                ring={{
                  ring_id: ring.ring_id,
                  nodes: ring.nodes,
                  topology: ring.topology,
                  risk: ring.risk,
                  graph: ring.graph,
                }}
                width={140}
                height={80}
                selected={selectedRings.includes(ring.ring_id)}
              />
              <span className="text-[11px] text-muted-ink mt-1">
                {ring.topology}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "nodes",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Nodes"
            tooltip="Number of accounts and entities included in the detected ring."
            align="right"
          />
        ),
        cell: ({ row }) => row.original.nodes,
        meta: {
          align: "right",
          cellClassName: "font-mono tabular-nums",
        },
      },
      {
        accessorKey: "volume",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Volume"
            tooltip="Total transaction volume associated with the detected ring."
            align="right"
          />
        ),
        cell: ({ row }) => currency.format(row.original.volume),
        meta: {
          align: "right",
          cellClassName: "font-mono tabular-nums",
        },
      },
      {
        accessorFn: (row) => row.shared_identifiers.join(", "),
        id: "shared_identifiers",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Shared identifiers"
            tooltip="Identifiers reused across ring members, such as shared devices, emails, or addresses."
          />
        ),
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1">
            {row.original.shared_identifiers.map((id) => (
              <Pill key={id}>{id}</Pill>
            ))}
          </div>
        ),
      },
      {
        accessorKey: "risk_score",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Risk"
            tooltip="Composite risk score and risk label assigned to the ring."
          />
        ),
        cell: ({ row }) => {
          const ring = row.original;
          return (
            <div className="flex items-center gap-2">
              <RiskBar score={ring.risk_score} risk={ring.risk} />
              <Pill intent={RISK_PILL_INTENT[ring.risk]}>
                {RISK_LABEL[ring.risk]}
              </Pill>
            </div>
          );
        },
      },
    ],
    [onToggle, selectedRings],
  );
  const table = useReactTable({
    data: rings,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (rings.length === 0) return <EmptyRingsCard />;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div
          className="inline-flex rounded-md border border-line bg-surface p-1"
          role="tablist"
          aria-label="Fraud ring result views"
        >
          <button
            type="button"
            role="tab"
            aria-selected={view === "graph"}
            onClick={() => setView("graph")}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-sm px-3 text-xs font-medium transition-colors",
              view === "graph"
                ? "bg-accent-soft text-ink"
                : "text-muted-ink hover:bg-canvas-soft hover:text-ink",
            )}
          >
            <Network className="h-3.5 w-3.5" />
            Graph
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "table"}
            onClick={() => setView("table")}
            className={cn(
              "inline-flex h-8 items-center gap-2 rounded-sm px-3 text-xs font-medium transition-colors",
              view === "table"
                ? "bg-accent-soft text-ink"
                : "text-muted-ink hover:bg-canvas-soft hover:text-ink",
            )}
          >
            <Table2 className="h-3.5 w-3.5" />
            Table
          </button>
        </div>
      </div>

      {view === "graph" ? (
        <FraudRingCardGrid
          rings={rings}
          selectedRings={selectedRings}
          onToggle={onToggle}
        />
      ) : null}

      {view === "table" ? (
        <Card className="overflow-hidden">
          <TooltipProvider delayDuration={150}>
            <SearchDataTable
              table={table}
              getRowClassName={(ring) =>
                selectedRings.includes(ring.ring_id)
                  ? "bg-accent-soft/40"
                  : undefined
              }
            />
          </TooltipProvider>
        </Card>
      ) : null}
    </div>
  );
}

function RiskResults({
  rows,
  selectedRiskAccounts,
  onToggleRiskAccount,
}: {
  rows: RiskAccountOut[];
  selectedRiskAccounts: string[];
  onToggleRiskAccount: (accountId: string) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<RiskAccountOut>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: () => (
          <HeaderTooltip
            label="Select"
            tooltip="Choose risk-scored accounts to carry forward into the load step."
          />
        ),
        cell: ({ row }) => {
          const account = row.original;
          return (
            <Checkbox
              checked={selectedRiskAccounts.includes(account.account_id)}
              onCheckedChange={() => onToggleRiskAccount(account.account_id)}
              aria-label={`Select account ${account.account_id}`}
            />
          );
        },
        meta: { className: "w-10" },
      },
      {
        accessorKey: "account_id",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Account"
            tooltip="Account identifier returned by the risk-score search."
          />
        ),
        cell: ({ row }) => <Pill intent="mono">{row.original.account_id}</Pill>,
      },
      {
        accessorKey: "risk_score",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Risk"
            tooltip="Individual account risk score on a zero-to-one scale."
          />
        ),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <RiskBar score={row.original.risk_score} />
            <span className="font-mono tabular-nums text-xs text-ink-2">
              {row.original.risk_score.toFixed(2)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "velocity",
        sortingFn: bandSortingFn,
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Velocity"
            tooltip="Relative transaction velocity band for the account."
          />
        ),
        cell: ({ row }) => (
          <Pill intent={bandPillIntent(row.original.velocity)}>
            {row.original.velocity}
          </Pill>
        ),
      },
      {
        accessorKey: "merchant_diversity",
        sortingFn: bandSortingFn,
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Merchant diversity"
            tooltip="Relative breadth of merchants connected to the account."
          />
        ),
        cell: ({ row }) => (
          <Pill intent={bandPillIntent(row.original.merchant_diversity)}>
            {row.original.merchant_diversity}
          </Pill>
        ),
      },
      {
        accessorKey: "account_age_days",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Account age"
            tooltip="Age of the account in days."
            align="right"
          />
        ),
        cell: ({ row }) => `${row.original.account_age_days}d`,
        meta: {
          align: "right",
          cellClassName: "font-mono tabular-nums",
        },
      },
    ],
    [onToggleRiskAccount, selectedRiskAccounts],
  );
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Card className="overflow-hidden">
      <TooltipProvider delayDuration={150}>
        <SearchDataTable
          table={table}
          getRowClassName={(row) =>
            selectedRiskAccounts.includes(row.account_id)
              ? "bg-accent-soft/40"
              : undefined
          }
        />
      </TooltipProvider>
    </Card>
  );
}

function HubResults({
  rows,
  selectedCentralAccounts,
  onToggleCentralAccount,
}: {
  rows: HubAccountOut[];
  selectedCentralAccounts: string[];
  onToggleCentralAccount: (accountId: string) => void;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const columns = useMemo<ColumnDef<HubAccountOut>[]>(
    () => [
      {
        id: "select",
        enableSorting: false,
        header: () => (
          <HeaderTooltip
            label="Select"
            tooltip="Choose central accounts to carry forward into the load step."
          />
        ),
        cell: ({ row }) => {
          const account = row.original;
          return (
            <Checkbox
              checked={selectedCentralAccounts.includes(account.account_id)}
              onCheckedChange={() => onToggleCentralAccount(account.account_id)}
              aria-label={`Select account ${account.account_id}`}
            />
          );
        },
        meta: { className: "w-10" },
      },
      {
        accessorKey: "account_id",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Account"
            tooltip="Account identifier returned by the central-account search."
          />
        ),
        cell: ({ row }) => <Pill intent="mono">{row.original.account_id}</Pill>,
      },
      {
        accessorKey: "neighbors",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Neighbors"
            tooltip="Number of directly connected accounts or entities."
            align="right"
          />
        ),
        cell: ({ row }) => row.original.neighbors,
        meta: {
          align: "right",
          cellClassName: "font-mono tabular-nums",
        },
      },
      {
        accessorKey: "betweenness",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Betweenness"
            tooltip="Normalized betweenness centrality, measuring how often the account bridges graph paths."
          />
        ),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <BetweennessBar score={row.original.betweenness} />
            <span className="font-mono tabular-nums text-xs text-ink-2">
              {row.original.betweenness.toFixed(2)}
            </span>
          </div>
        ),
      },
      {
        accessorKey: "shortest_paths",
        header: ({ column }) => (
          <SortableHeader
            column={column}
            label="Shortest paths"
            tooltip="Count of shortest paths routed through the account."
            align="right"
          />
        ),
        cell: ({ row }) => row.original.shortest_paths,
        meta: {
          align: "right",
          cellClassName: "font-mono tabular-nums",
        },
      },
    ],
    [onToggleCentralAccount, selectedCentralAccounts],
  );
  const table = useReactTable({
    data: rows,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <Card className="overflow-hidden">
      <TooltipProvider delayDuration={150}>
        <SearchDataTable
          table={table}
          getRowClassName={(row) =>
            selectedCentralAccounts.includes(row.account_id)
              ? "bg-accent-soft/40"
              : undefined
          }
        />
      </TooltipProvider>
    </Card>
  );
}

function BetweennessBar({ score, width = 120 }: { score: number; width?: number }) {
  const clamped = Math.max(0, Math.min(1, score));
  return (
    <div
      className="h-1.5 rounded-sm bg-canvas-soft border border-line overflow-hidden"
      style={{ width: `${width}px` }}
    >
      <div
        className="h-full rounded-sm bg-ink-2"
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}
