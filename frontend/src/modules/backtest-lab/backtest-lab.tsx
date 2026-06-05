"use client";

import { useEffect, useRef, useState } from "react";

import { getBacktest, listStrategies, runBacktest, type StrategyRow } from "@/lib/api";

import { ReportCard } from "./report-card";
import type { BacktestReport } from "./types";

export function BacktestLab() {
  const [strategies, setStrategies] = useState<StrategyRow[]>([]);
  const [selected, setSelected] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    listStrategies()
      .then((rows) => {
        setStrategies(rows);
        if (rows[0]) setSelected(rows[0].id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load strategies"));
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function stopPolling() {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = null;
    setBusy(false);
  }

  async function onRun() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setStatus("queued");
    try {
      const { id } = await runBacktest(selected);
      pollRef.current = setInterval(async () => {
        try {
          const row = await getBacktest(id);
          setStatus(row.status);
          if (row.status === "done") {
            setReport(row.report ?? null);
            stopPolling();
          } else if (row.status === "error") {
            setError(row.error ?? "Backtest failed");
            stopPolling();
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : "Polling failed");
          stopPolling();
        }
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the backtest");
      setStatus(null);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow mb-1">Backtest lab</p>
        <h1 className="font-serif text-2xl font-medium">Prove the edge on history</h1>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 sm:flex-row sm:items-end">
        <label className="flex-1 text-sm">
          <span className="eyebrow mb-1 block">Strategy</span>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full rounded border bg-background px-2 py-2 text-sm"
          >
            {strategies.length === 0 ? <option value="">No saved strategies yet</option> : null}
            {strategies.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} · v{s.version}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={onRun}
          disabled={busy || !selected}
          className="rounded-md bg-primary px-5 py-2.5 font-mono text-xs uppercase tracking-[0.16em] text-primary-foreground transition-opacity hover:opacity-95 disabled:opacity-50"
        >
          {busy ? "Running…" : "Run backtest"}
        </button>
      </div>

      {busy && status && (
        <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
          Status: {status}…
        </p>
      )}
      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {report && <ReportCard report={report} />}
    </div>
  );
}
