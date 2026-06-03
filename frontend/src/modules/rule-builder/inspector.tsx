"use client";

import type { ReactNode } from "react";

import type { StrategySpec } from "@/contract/types";

import { setAtPath, type NodeData } from "./graph";

const TIMEFRAMES = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"];
const inputCls = "w-full rounded border bg-background px-2 py-1 text-sm";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="mb-3 block text-sm">
      <span className="mb-1 block text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function get(spec: StrategySpec, path: (string | number)[]): unknown {
  return path.reduce<unknown>(
    (acc, k) => (acc == null ? acc : (acc as Record<string | number, unknown>)[k]),
    spec,
  );
}

/**
 * Edits the spec slice for the selected node. Every change writes straight back
 * to the StrategySpec (the single source of truth); the canvas re-derives from it.
 * Direction is NOT edited here — it is confirmed/flipped on the Setup node itself.
 */
export function Inspector({
  spec,
  selected,
  onChange,
}: {
  spec: StrategySpec;
  selected: NodeData | null;
  onChange: (s: StrategySpec) => void;
}) {
  if (!selected) {
    return (
      <p className="text-sm text-muted-foreground">
        Select any node to edit it. The canvas is a view of your strategy JSON — edits write straight
        back to it.
      </p>
    );
  }

  const { kind, path } = selected;
  const node = (get(spec, path) ?? {}) as Record<string, unknown>;
  const cur = (sub: (string | number)[]) => get(spec, [...path, ...sub]);
  const set = (sub: (string | number)[], value: unknown) =>
    onChange(setAtPath(spec, [...path, ...sub], value));
  const numOrNull = (v: string) => (v === "" ? null : Number(v));

  const text = (label: string, sub: (string | number)[]) => (
    <Field label={label}>
      <input className={inputCls} value={String(cur(sub) ?? "")} onChange={(e) => set(sub, e.target.value)} />
    </Field>
  );
  const number = (label: string, sub: (string | number)[]) => (
    <Field label={label}>
      <input
        type="number"
        className={inputCls}
        value={cur(sub) == null ? "" : String(cur(sub))}
        onChange={(e) => set(sub, numOrNull(e.target.value))}
      />
    </Field>
  );
  const choose = (label: string, sub: (string | number)[], options: string[]) => (
    <Field label={label}>
      <select className={inputCls} value={String(cur(sub) ?? "")} onChange={(e) => set(sub, e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </Field>
  );

  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold capitalize">{kind.replace(/_/g, " ")}</h3>

      {kind === "strategy" && text("Name", ["name"])}

      {kind === "instrument" && (
        <>
          {text("Symbol", ["symbol"])}
          {choose("Asset class", ["asset_class"], ["forex", "metal", "index_cfd"])}
        </>
      )}

      {kind === "timeframes" && choose("Entry timeframe", ["entry"], TIMEFRAMES)}

      {kind === "guards" && (
        <p className="text-sm text-muted-foreground">
          Martingale, averaging-down, and grid are denied by default and stay locked across all setups.
        </p>
      )}

      {kind === "condition" && node.kind === "indicator" && (
        <>
          {text("Indicator", ["indicator"])}
          {choose("Comparator", ["comparator"], [
            "gt", "gte", "lt", "lte", "eq", "crosses_above", "crosses_below",
          ])}
          {number("Value", ["value"])}
          {text("Reference series", ["reference"])}
        </>
      )}
      {kind === "condition" && node.kind !== "indicator" && (
        <p className="text-sm text-muted-foreground">{selected.label}</p>
      )}

      {kind === "setup" && (
        <>
          {text("Setup name", ["name"])}
          <p className="mb-3 text-xs text-muted-foreground">
            Direction is set with Confirm / Flip on the setup node.
          </p>
          {choose("Per-trade risk model", ["per_trade_risk", "model"], [
            "fixed_percent", "fixed_amount", "atr_based",
          ])}
          {number("Per-trade risk value", ["per_trade_risk", "value"])}
          {choose("Stop model", ["exit", "stop_loss", "model"], ["fixed_pips", "atr", "structure"])}
          {number("Stop value", ["exit", "stop_loss", "value"])}
          {number("ATR period", ["exit", "stop_loss", "atr_period"])}
          {choose("TP1 model", ["exit", "take_profit", 0, "model"], ["rr", "fixed_pips", "atr"])}
          {number("TP1 value", ["exit", "take_profit", 0, "value"])}
          {number("TP1 close %", ["exit", "take_profit", 0, "close_percent"])}
        </>
      )}
    </div>
  );
}
