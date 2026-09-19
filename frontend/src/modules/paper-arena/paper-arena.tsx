"use client";

import { useEffect, useState } from "react";

import { supabase } from "@/lib/supabase";
import type { AgentProposal } from "@/contract/types";

/** An agent_logs row whose decision put (or kept) a position open. */
interface OpenPositionRow {
  proposal_id: string;
  strategy_id: string;
  proposal: AgentProposal;
  user_decision: "approve" | "executed";
  logged_at: string;
}

/**
 * Paper Arena — the live-data dashboard. Subscribes to Supabase Realtime and
 * renders open positions from agent_logs (approve/executed decisions).
 *
 * Closed-trade P&L is NOT wired yet: nothing writes execution_history today
 * (live_runner's close-out path is a tracked V1 TODO), so that stat stays
 * explicitly labeled rather than showing fabricated numbers.
 */
export function PaperArena() {
  const [connected, setConnected] = useState(false);
  const [positions, setPositions] = useState<OpenPositionRow[]>([]);
  const [loading, setLoading] = useState(true);

  async function loadOpenPositions() {
    const { data } = await supabase
      .from("agent_logs")
      .select("proposal_id,strategy_id,proposal,user_decision,logged_at")
      .in("user_decision", ["approve", "executed"])
      .order("logged_at", { ascending: false });
    setPositions((data as OpenPositionRow[]) ?? []);
  }

  useEffect(() => {
    loadOpenPositions().finally(() => setLoading(false));

    const channel = supabase
      .channel("paper-arena")
      .on("postgres_changes", { event: "*", schema: "public", table: "execution_history" }, () => {
        // Slice 4 will render streamed paper fills once close-outs are logged.
      })
      .on("postgres_changes", { event: "*", schema: "public", table: "agent_logs" }, () => {
        loadOpenPositions().catch(() => undefined);
      })
      .subscribe((status) => setConnected(status === "SUBSCRIBED"));
    return () => {
      supabase.removeChannel(channel);
    };
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow mb-1">Paper arena</p>
          <h1 className="font-serif text-2xl font-medium">Live paper feed</h1>
        </div>
        <span className="flex items-center gap-2 font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
          <span className={`h-2 w-2 rounded-full ${connected ? "bg-up" : "bg-muted-foreground"}`} aria-hidden="true" />
          {connected ? "Live" : "Connecting"}
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Stat
          label="Agent status"
          value={positions.length > 0 ? "Active" : "Idle"}
          note={positions.length > 0 ? "Positions open" : "Deploy in Co-Pilot to go live"}
        />
        <Stat
          label="Open positions"
          value={String(positions.length)}
          note={positions.length === 0 ? "No open positions" : "From approved/executed proposals"}
        />
        <Stat label="Live P&amp;L" value="—" note="Streams once close-out capture ships" />
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <p className="eyebrow mb-3">Open paper positions</p>
        {loading ? (
          <p className="font-mono text-xs uppercase tracking-[0.14em] text-muted-foreground">
            Loading…
          </p>
        ) : positions.length === 0 ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            No open positions yet. Approve a proposal in Co-Pilot, or wait for a deployed
            Agent&rsquo;s next match — positions stream here in real time.
          </p>
        ) : (
          <ul className="space-y-2">
            {positions.map((row) => (
              <PositionRow key={row.proposal_id} row={row} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function PositionRow({ row }: { row: OpenPositionRow }) {
  const p = row.proposal;
  return (
    <li className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">
          {p.symbol} · {p.direction === "long" ? "Long" : "Short"}
        </p>
        <p className="font-mono text-xs text-muted-foreground">
          Entry {p.entry_price} · SL {p.stop_loss_price} · TP {p.take_profit_prices.join(", ")}
        </p>
      </div>
      <span className="shrink-0 font-mono text-xs uppercase tracking-[0.12em] text-muted-foreground">
        open — awaiting close
      </span>
    </li>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="eyebrow mb-2">{label}</p>
      <p className="numeric text-2xl font-medium">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{note}</p>
    </div>
  );
}
