"use client";

import { useEffect, useState } from "react";

import { supabase } from "@/lib/supabase";

/**
 * Paper Arena — the live-data dashboard SHELL (this slice).
 * Subscribes to Supabase Realtime and shows Agent status + placeholders for open
 * paper positions and live P&L. NO order execution and NO agent loop — those are
 * Slice 4. Nothing here places trades.
 */
export function PaperArena() {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const channel = supabase
      .channel("paper-arena")
      .on("postgres_changes", { event: "*", schema: "public", table: "execution_history" }, () => {
        // Slice 4 will render streamed paper fills here; the shell only listens.
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
        <Stat label="Agent status" value="Idle" note="Deploy in Co-Pilot (Slice 4)" />
        <Stat label="Open positions" value="0" note="No paper positions yet" />
        <Stat label="Live P&amp;L" value="—" note="Streams once an Agent is live" />
      </div>

      <div className="rounded-lg border border-border bg-card p-5">
        <p className="eyebrow mb-2">Open paper positions</p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          This is the live-data dashboard shell. Open positions and P&amp;L stream over Supabase Realtime
          once an Agent is deployed in Co-Pilot. Order execution and the Agent loop arrive in Slice 4.
        </p>
      </div>
    </div>
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
