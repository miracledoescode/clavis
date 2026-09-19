"use client";

import { useEffect, useState } from "react";

import {
  approveProposal,
  listDecisionHistory,
  listPendingProposals,
  rejectProposal,
  type DecisionLogRow,
  type PendingProposal,
} from "@/lib/api";
import type { RejectReasonChip } from "@/contract/types";
import { supabase } from "@/lib/supabase";

const REASON_CHIPS: { value: RejectReasonChip; label: string }[] = [
  { value: "bad_timing", label: "Bad timing" },
  { value: "wrong_direction", label: "Wrong direction" },
  { value: "news_risk", label: "News risk" },
  { value: "already_in_trade", label: "Already in a trade" },
  { value: "low_conviction", label: "Low conviction" },
  { value: "spread_too_wide", label: "Spread too wide" },
  { value: "other", label: "Other" },
];

/**
 * Co-Pilot — approve or reject the live loop's proposals, and review the
 * decision history (the RLHF capture surface CLAUDE.md calls "the moat").
 * Every decision here is the trader's own judgment on the Agent's proposal —
 * the Agent never originates a recommendation the trader didn't author.
 */
export function CoPilot() {
  const [proposals, setProposals] = useState<PendingProposal[]>([]);
  const [decisions, setDecisions] = useState<DecisionLogRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejectingId, setRejectingId] = useState<string | null>(null);
  const [, forceTick] = useState(0);

  function load() {
    return Promise.all([listPendingProposals(), listDecisionHistory()]).then(
      ([p, d]) => {
        setProposals(p);
        setDecisions(d);
      },
    );
  }

  useEffect(() => {
    load()
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load Co-Pilot"))
      .finally(() => setLoading(false));

    // Re-fetch whenever this user's agent_logs rows change (RLS scopes the
    // subscription too) — proposals sent by the live loop, or decisions
    // recorded from Telegram, show up here without a manual refresh.
    const channel = supabase
      .channel("co-pilot")
      .on("postgres_changes", { event: "*", schema: "public", table: "agent_logs" }, () => {
        load().catch(() => undefined);
      })
      .subscribe();

    // Drives the countdown-to-expiry display on pending cards.
    const interval = setInterval(() => forceTick((n) => n + 1), 1000);

    return () => {
      supabase.removeChannel(channel);
      clearInterval(interval);
    };
  }, []);

  function removePending(proposalId: string) {
    setProposals((rows) => rows.filter((r) => r.proposal_id !== proposalId));
  }

  async function onApprove(proposalId: string) {
    setBusyId(proposalId);
    setError(null);
    try {
      await approveProposal(proposalId);
      removePending(proposalId);
      load().catch(() => undefined); // background refresh; server truth wins
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  }

  async function onReject(proposalId: string, reasonChip?: RejectReasonChip) {
    setBusyId(proposalId);
    setError(null);
    try {
      await rejectProposal(proposalId, reasonChip);
      removePending(proposalId);
      setRejectingId(null);
      load().catch(() => undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="eyebrow mb-1">Co-Pilot</p>
        <h1 className="font-serif text-2xl font-medium">Approve or reject</h1>
        <p className="mb-1 mt-1 text-sm text-muted-foreground">
          Every proposal below applies only the logic you authored. Nothing executes until you
          decide — approve, reject, or let the validity window expire.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}

      <section className="space-y-3">
        <p className="eyebrow">Pending proposals</p>
        {loading ? (
          <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
            Loading…
          </p>
        ) : proposals.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
            No pending proposals. Deploy an Agent in the Deploy Hub to start seeing them here.
          </div>
        ) : (
          <ul className="space-y-3">
            {proposals.map((p) => (
              <ProposalCard
                key={p.proposal_id}
                proposal={p}
                busy={busyId === p.proposal_id}
                rejecting={rejectingId === p.proposal_id}
                onApprove={() => onApprove(p.proposal_id)}
                onStartReject={() => setRejectingId(p.proposal_id)}
                onCancelReject={() => setRejectingId(null)}
                onConfirmReject={(chip) => onReject(p.proposal_id, chip)}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <p className="eyebrow">Decision history</p>
        {decisions.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
            Decisions you make (and any recorded via Telegram) will appear here.
          </div>
        ) : (
          <ul className="space-y-2">
            {decisions.map((d) => (
              <DecisionRow key={d.proposal_id} row={d} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function msUntil(iso: string): number {
  return new Date(iso).getTime() - Date.now();
}

function formatCountdown(ms: number): string {
  if (ms <= 0) return "expired";
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function ProposalCard({
  proposal,
  busy,
  rejecting,
  onApprove,
  onStartReject,
  onCancelReject,
  onConfirmReject,
}: {
  proposal: PendingProposal;
  busy: boolean;
  rejecting: boolean;
  onApprove: () => void;
  onStartReject: () => void;
  onCancelReject: () => void;
  onConfirmReject: (chip?: RejectReasonChip) => void;
}) {
  const p = proposal.proposal;
  const remaining = msUntil(p.expires_at);
  const expired = remaining <= 0;

  return (
    <li className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {p.symbol} · {p.direction === "long" ? "Long" : "Short"}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{p.rationale}</p>
        </div>
        <span
          className={`shrink-0 font-mono text-xs uppercase tracking-[0.14em] ${
            expired ? "text-destructive" : "text-muted-foreground"
          }`}
        >
          {formatCountdown(remaining)}
        </span>
      </div>

      <dl className="grid grid-cols-3 gap-3 font-mono text-xs">
        <div>
          <dt className="text-muted-foreground">Entry</dt>
          <dd className="numeric">{p.entry_price}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Stop loss</dt>
          <dd className="numeric">{p.stop_loss_price}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Take profit</dt>
          <dd className="numeric">{p.take_profit_prices.join(", ")}</dd>
        </div>
      </dl>

      {rejecting ? (
        <div className="space-y-2 rounded-md border border-border bg-secondary/40 p-3">
          <p className="font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">
            Why reject?
          </p>
          <div className="flex flex-wrap gap-2">
            {REASON_CHIPS.map((chip) => (
              <button
                key={chip.value}
                type="button"
                disabled={busy}
                onClick={() => onConfirmReject(chip.value)}
                className="rounded-full border border-border px-3 py-1 text-xs transition-colors hover:bg-secondary disabled:opacity-50"
              >
                {chip.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onCancelReject}
            className="font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground hover:text-foreground"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex gap-3">
          <button
            type="button"
            onClick={onApprove}
            disabled={busy || expired}
            className="rounded-md bg-primary px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-primary-foreground transition-opacity hover:opacity-95 disabled:opacity-50"
          >
            {busy ? "Approving…" : "Approve"}
          </button>
          <button
            type="button"
            onClick={onStartReject}
            disabled={busy || expired}
            className="rounded-md border border-destructive/50 px-4 py-2 font-mono text-xs uppercase tracking-[0.16em] text-destructive transition-colors hover:bg-destructive/10 disabled:opacity-50"
          >
            Reject
          </button>
        </div>
      )}
    </li>
  );
}

const DECISION_LABEL: Record<string, string> = {
  approve: "Approved",
  reject: "Rejected",
  invalidated: "Invalidated",
  executed: "Executed",
};

function DecisionRow({ row }: { row: DecisionLogRow }) {
  const p = row.proposal;
  return (
    <li className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card p-4">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">
          {p.symbol} · {p.direction === "long" ? "Long" : "Short"}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {p.rationale}
          {row.reject_reason_chip ? ` — ${row.reject_reason_chip.replace(/_/g, " ")}` : ""}
        </p>
      </div>
      <span className="shrink-0 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
        {DECISION_LABEL[row.user_decision] ?? row.user_decision}
      </span>
    </li>
  );
}
