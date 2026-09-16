import { Printer, Save, Sparkles } from "lucide-react";

import { Pill } from "@/components/Pill";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useFlow } from "@/lib/flowContext";
import type { TranscriptEntry } from "@/lib/flowContext";
import { cn } from "@/lib/utils";

export interface ReportModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ReportModal({ open, onOpenChange }: ReportModalProps) {
  const {
    selectedRings,
    selectedRiskAccounts,
    selectedCentralAccounts,
    selectedSignalIds,
    transcript,
  } = useFlow();
  const generatedAt = new Date().toISOString();

  function onPrint() {
    window.print();
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Fraud Signal Report</DialogTitle>
          <DialogDescription>Generated {generatedAt}</DialogDescription>
        </DialogHeader>

        <ReportSection>
          <SectionTitle>Summary</SectionTitle>
          <p className="text-sm text-ink leading-relaxed">
            Investigation summary for {selectedSignalIds.length} graph signal
            {selectedSignalIds.length === 1 ? "" : "s"} loaded into the lakehouse.
          </p>
          {selectedSignalIds.length > 0 ? (
            <div className="mt-2 flex flex-row flex-wrap gap-1.5">
              {selectedRings.map((ring) => (
                <Pill key={`ring-${ring}`} intent="mono">
                  {ring}
                </Pill>
              ))}
              {selectedRiskAccounts.map((account) => (
                <Pill key={`risk-${account}`} intent="mono">
                  {account}
                </Pill>
              ))}
              {selectedCentralAccounts.map((account) => (
                <Pill key={`central-${account}`} intent="mono">
                  {account}
                </Pill>
              ))}
            </div>
          ) : null}
        </ReportSection>

        <ReportSection>
          <SectionTitle>Loaded signals</SectionTitle>
          {selectedSignalIds.length === 0 ? (
            <p className="text-sm text-muted-ink italic">No signals loaded.</p>
          ) : (
            <dl className="space-y-1.5">
              {selectedRings.map((ring) => (
                <div
                  key={`ring-${ring}`}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <dt className="font-mono text-ink-2">{ring}</dt>
                  <dd className="text-xs text-muted-ink">
                    ring materialized
                  </dd>
                </div>
              ))}
              {selectedRiskAccounts.map((account) => (
                <div
                  key={`risk-${account}`}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <dt className="font-mono text-ink-2">{account}</dt>
                  <dd className="text-xs text-muted-ink">
                    risk account materialized
                  </dd>
                </div>
              ))}
              {selectedCentralAccounts.map((account) => (
                <div
                  key={`central-${account}`}
                  className="flex items-center justify-between gap-3 text-sm"
                >
                  <dt className="font-mono text-ink-2">{account}</dt>
                  <dd className="text-xs text-muted-ink">
                    central account materialized
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </ReportSection>

        <ReportSection>
          <SectionTitle>Conversation log</SectionTitle>
          {transcript.length === 0 ? (
            <p className="text-sm text-muted-ink italic">
              No questions asked yet.
            </p>
          ) : (
            <div className="space-y-4">
              {transcript.map((entry, idx) => (
                <TranscriptBlock key={idx} entry={entry} />
              ))}
            </div>
          )}
        </ReportSection>

        <DialogFooter className="print:hidden">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={0}>
                  <Button variant="outline" disabled>
                    <Save className="h-4 w-4" />
                    Save to lakehouse
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>Endpoint pending</TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button onClick={onPrint}>
            <Printer className="h-4 w-4" />
            Print to PDF
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface ReportSectionProps {
  children: React.ReactNode;
  className?: string;
}

function ReportSection({ children, className }: ReportSectionProps) {
  return (
    <div
      className={cn("border-t border-line first:border-t-0 py-4", className)}
    >
      {children}
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-ink">
      {children}
    </h3>
  );
}

function TranscriptBlock({ entry }: { entry: TranscriptEntry }) {
  return (
    <div className="space-y-1.5">
      <div className="text-sm font-medium text-ink-2">Q: {entry.question}</div>
      <div className="text-sm text-ink leading-relaxed">A: {entry.text}</div>
      {entry.table ? <TranscriptTable table={entry.table} /> : null}
      {entry.summary ? (
        <div className="flex items-start gap-1.5 text-xs italic text-ink-2">
          <Sparkles className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>{entry.summary}</span>
        </div>
      ) : null}
    </div>
  );
}

interface TranscriptTableProps {
  table: { headers: string[]; rows: string[][] };
}

function TranscriptTable({ table }: TranscriptTableProps) {
  const visibleRows = table.rows.slice(0, 5);
  const hiddenCount = Math.max(0, table.rows.length - visibleRows.length);
  return (
    <div className="space-y-1">
      <Table className="text-xs font-mono">
        <TableHeader>
          <TableRow>
            {table.headers.map((header) => (
              <TableHead key={header}>{header}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleRows.map((row, ri) => (
            <TableRow key={ri}>
              {row.map((cell, ci) => (
                <TableCell key={ci}>{cell}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {hiddenCount > 0 ? (
        <div className="text-[11px] text-muted-ink">+ {hiddenCount} more</div>
      ) : null}
    </div>
  );
}

export default ReportModal;
