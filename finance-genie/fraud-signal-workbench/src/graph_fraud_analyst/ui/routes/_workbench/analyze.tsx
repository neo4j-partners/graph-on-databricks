import { useState } from "react";
import type { KeyboardEvent } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import {
  AlertTriangle,
  ArrowLeft,
  Database,
  Download,
  MessageSquare,
  Send,
  Sparkles,
} from "lucide-react";

import { Pill } from "@/components/Pill";
import { ReportModal } from "@/components/ReportModal";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useAskGenie, type AnswerTable } from "@/lib/api";
import { useFlow } from "@/lib/flowContext";
import { SAMPLE_QUESTIONS, TABLES } from "@/lib/genieReference";

export const Route = createFileRoute("/_workbench/analyze")({
  component: AnalyzeRoute,
});

function AnalyzeRoute() {
  const navigate = useNavigate();
  const {
    selectedRings,
    selectedRiskAccounts,
    selectedCentralAccounts,
    selectedSignalIds,
    conversationId,
    setConversationId,
    transcript,
    appendTranscript,
  } = useFlow();
  const [input, setInput] = useState("");
  const [reportOpen, setReportOpen] = useState(false);

  const askMutation = useAskGenie();
  const loading = askMutation.isPending;

  if (selectedSignalIds.length === 0) {
    return (
      <Card className="bg-surface border-line p-8 text-center">
        <div className="mx-auto max-w-md space-y-3">
          <h2 className="text-lg font-semibold text-ink">No signals loaded</h2>
          <p className="text-sm text-ink-2">
            Start at Search to pick graph signals, then run the Load step before
            analyzing with Genie.
          </p>
          <Button
            variant="default"
            onClick={() => navigate({ to: "/search" })}
          >
            Go to Search
          </Button>
        </div>
      </Card>
    );
  }

  async function submit(question: string) {
    const trimmed = question.trim();
    if (!trimmed || loading) return;
    setInput("");
    try {
      const result = await askMutation.mutateAsync({
        question: trimmed,
        conversation_id: conversationId,
      });
      const response = result.data;
      setConversationId(response.conversation_id);
      appendTranscript({
        question: trimmed,
        text: response.text,
        table: response.table ?? null,
        summary: response.summary ?? null,
      });
    } catch {
      // Mutation surfaces error state via askMutation.isError; swallow here so
      // the input doesn't crash the route.
    }
  }

  function onSampleClick(question: string) {
    setInput(question);
    void submit(question);
  }

  function onAskClick() {
    void submit(input);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit(input);
    }
  }

  function onExport() {
    setReportOpen(true);
  }

  return (
    <>
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
      {/* Left sidebar */}
      <div className="space-y-4">
        <Card className="bg-surface border-line p-4">
          <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-ink-2">
            <Database className="h-3.5 w-3.5" />
            Schema
          </div>
          <div className="space-y-1">
            {TABLES.map((table) => (
              <details key={table.name} className="group">
                <summary className="font-mono text-xs text-ink-2 cursor-pointer flex items-center justify-between py-1">
                  <span>{table.name}</span>
                  <span className="text-[10px] text-muted-ink">
                    {table.rows} rows
                  </span>
                </summary>
                <div className="mt-2 mb-2 flex flex-wrap gap-1">
                  {table.cols.map((col) => (
                    <Pill key={col} intent="mono">
                      {col}
                    </Pill>
                  ))}
                </div>
              </details>
            ))}
          </div>
        </Card>

        <Card className="bg-surface border-line p-4">
          <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-ink-2">
            <Sparkles className="h-3.5 w-3.5" />
            Try asking…
          </div>
          <div className="space-y-2">
            {SAMPLE_QUESTIONS.map((question) => (
              <button
                key={question}
                type="button"
                onClick={() => onSampleClick(question)}
                disabled={loading}
                className="w-full text-left text-xs px-3 py-2 rounded-md bg-canvas-soft hover:bg-accent-soft text-ink-2 hover:text-accent-ink border border-line transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {question}
              </button>
            ))}
          </div>
        </Card>
      </div>

      {/* Right pane */}
      <div className="flex flex-col">
        {/* Top bar */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-ink">Loaded signals:</span>
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
          <Button variant="outline" onClick={onExport}>
            <Download className="h-4 w-4" />
            Export Report
          </Button>
        </div>

        {/* Transcript */}
        <div className="flex-1 space-y-4 mb-4 max-h-[60vh] overflow-y-auto pr-2">
          {askMutation.isError ? (
            <div className="flex items-start gap-2 rounded-md border border-risk-high/40 bg-risk-high/5 px-3 py-2 text-xs text-ink">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 text-risk-high shrink-0" />
              <div>
                <div className="font-medium">Genie failed to respond</div>
                <div className="text-muted-ink mt-0.5">
                  {askMutation.error instanceof Error
                    ? askMutation.error.message
                    : "Unknown error"}
                </div>
              </div>
            </div>
          ) : null}
          {transcript.length === 0 && !loading ? (
            <div className="flex flex-col items-center justify-center text-center py-12 text-ink-2">
              <MessageSquare className="h-8 w-8 mb-2 text-muted-ink" />
              <p className="text-sm">No questions yet.</p>
              <p className="text-xs text-muted-ink mt-1">
                Pick a sample question on the left or type your own below.
              </p>
            </div>
          ) : (
            transcript.map((entry, idx) => (
              <TranscriptTurn key={idx} entry={entry} />
            ))
          )}
          {loading ? <PendingBubble /> : null}
        </div>

        {/* Input row */}
        <div className="flex gap-2">
          <Textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask Genie about the loaded signals..."
            className="min-h-[60px] resize-none flex-1"
            disabled={loading}
          />
          <Button onClick={onAskClick} disabled={loading || !input.trim()}>
            <Send className="h-4 w-4" />
            Ask
          </Button>
        </div>

        {/* Bottom navigation */}
        <div className="mt-4">
          <Button
            variant="ghost"
            onClick={() => navigate({ to: "/load" })}
          >
            <ArrowLeft className="h-4 w-4" />
            Back to Load
          </Button>
        </div>
      </div>
    </div>
    <ReportModal open={reportOpen} onOpenChange={setReportOpen} />
    </>
  );
}

interface TranscriptTurnProps {
  entry: {
    question: string;
    text: string;
    table?: AnswerTable | null;
    summary?: string | null;
  };
}

function TranscriptTurn({ entry }: TranscriptTurnProps) {
  return (
    <div className="space-y-2">
      <div className="ml-auto max-w-[80%] rounded-lg px-3 py-2 bg-accent-soft text-accent-ink text-sm">
        {entry.question}
      </div>
      <div className="mr-auto max-w-[92%] rounded-lg px-3 py-3 bg-surface border border-line text-sm space-y-3">
        <p className="text-ink leading-relaxed">{entry.text}</p>
        {entry.table ? <AnswerTableView table={entry.table} /> : null}
        {entry.summary ? (
          <div className="flex items-start gap-1.5 text-xs text-ink-2 italic border-t border-line pt-2">
            <Sparkles className="h-3.5 w-3.5 mt-0.5 shrink-0" />
            <span>{entry.summary}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AnswerTableView({ table }: { table: AnswerTable }) {
  const visibleRows = table.rows.slice(0, 10);
  const hiddenCount = Math.max(0, table.rows.length - visibleRows.length);
  return (
    <div className="space-y-1">
      <Table>
        <TableHeader>
          <TableRow>
            {table.headers.map((h) => (
              <TableHead key={h}>{h}</TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleRows.map((row, ri) => (
            <TableRow key={ri}>
              {row.map((cell, ci) => (
                <TableCell key={ci} className="font-mono text-xs">
                  {cell}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {hiddenCount > 0 ? (
        <div className="text-xs text-muted-ink">+ {hiddenCount} more rows</div>
      ) : null}
    </div>
  );
}

function PendingBubble() {
  return (
    <div className="mr-auto max-w-[92%] rounded-lg px-3 py-3 bg-surface border border-line space-y-2">
      <Skeleton className="h-3 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  );
}
