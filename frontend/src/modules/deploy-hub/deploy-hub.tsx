"use client";

import { useEffect, useState } from "react";

import {
  deployStrategy,
  listStrategies,
  stopStrategy,
  type DeploymentStatus,
  type StrategyRow,
} from "@/lib/api";

/**
 * Deploy Hub — deploy a saved strategy's live Agent, see its state, and hit the
 * kill switch. The engine validates the spec and enforces the tier's live-Agent
 * limit before going live. Stop is a kill switch for the loop only: it never
 * closes open positions, because SL/TP live at the broker on every order
 * (CLAUDE.md, "SL/TP at the broker, always").
 */
export function DeployHub() {
  const [strategies, setStrategies] = useState<StrategyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    listStrategies()
      .then(setStrategies)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load strategies"))
      .finally(() => setLoading(false));
  }, []);

  function patchRow(id: string, deployment_status: DeploymentStatus) {
    setStrategies((rows) =>
      rows.map((r) => (r.id === id ? { ...r, deployment_status } : r)),
    );
  }

  async function onDeploy(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const res = await deployStrategy(id);
      patchRow(id, res.deployment_status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Deploy failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onStop(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const res = await stopStrategy(id);
      patchRow(id, res.deployment_status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Stop failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="eyebrow mb-1">Deploy hub</p>
        <h1 className="font-serif text-2xl font-medium">Put your Agent to work</h1>
        <p className="mb-1 mt-1 text-sm text-muted-foreground">
          Deploy a saved strategy to run live in Co-Pilot. Stop is a kill switch for the loop only —
          it never closes open positions, because every order keeps its stop loss and take profit at
          the broker.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
          Loading strategies…
        </p>
      ) : strategies.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
          No saved strategies yet. Author one in the Rule Builder, then come back to deploy it.
        </div>
      ) : (
        <ul className="space-y-2">
          {strategies.map((s) => {
            const deployed = s.deployment_status === "deployed";
            const busy = busyId === s.id;
            return (
              <li
                key={s.id}
                className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card p-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{s.name}</p>
                  <p className="font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">
                    v{s.version}
                  </p>
                </div>

                <div className="flex shrink-0 items-center gap-4">
                  <StatusBadge deployed={deployed} />
                  {deployed ? (
                    <button
                      type="button"
                      onClick={() => onStop(s.id)}
                      disabled={busy}
                      className="rounded-md border border-destructive/50 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
                    >
                      {busy ? "Stopping…" : "Stop"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => onDeploy(s.id)}
                      disabled={busy}
                      className="rounded-md bg-primary px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-primary-foreground transition-opacity hover:opacity-95 disabled:opacity-50"
                    >
                      {busy ? "Deploying…" : "Deploy"}
                    </button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ deployed }: { deployed: boolean }) {
  return (
    <span className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
      <span
        className={`h-2 w-2 rounded-full ${deployed ? "bg-up" : "bg-muted-foreground"}`}
        aria-hidden="true"
      />
      {deployed ? "Live" : "Stopped"}
    </span>
  );
}
