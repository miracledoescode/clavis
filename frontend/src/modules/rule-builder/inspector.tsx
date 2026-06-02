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
  const set = (sub: (string | number)[], value: unknown) =>
    onChange(setAtPath(spec, [...path, ...sub], value));
  const numOrNull = (v: string) => (v === "" ? null : Number(v));

  const text = (label: string, sub: (string | number)[], value: unknown) => (
    <Field label={label}>
      <input className={inputCls} value={String(value ?? "")} onChange={(e) => set(sub, e.target.value)} />
    </Field>
  );
  const number = (label: string, sub: (string | number)[], value: unknown) => (
    <Field label={label}>
      <input
        type="number"
        className={inputCls}
        value={value == null ? "" : String(value)}
        onChange={(e) => set(sub, numOrNull(e.target.value))}
      />
    </Field>
  );
  const choose = (label: string, sub: (string | number)[], value: unknown, options: string[]) => (
    <Field label={label}>
      <select className={inputCls} value={String(value ?? "")} onChange={(e) => set(sub, e.target.value)}>
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
      <h3 className="mb-3 text-sm font-semibold capitalize">{kind.replace("_", " ")}</h3>

      {kind === "strategy" && text("Name", [], spec.name)}

      {kind === "instrument" && (
        <>
          {text("Symbol", ["symbol"], node.symbol)}
          {choose("Asset class", ["asset_class"], node.asset_class, ["forex", "metal", "index_cfd"])}
        </>
      )}

      {kind === "timeframes" && choose("Entry timeframe", ["entry"], node.entry, TIMEFRAMES)}

      {kind === "direction" && choose("Direction", [], spec.direction, ["long", "short", "both"])}

      {kind === "condition" && node.kind === "indicator" && (
        <>
          {text("Indicator", ["indicator"], node.indicator)}
          {choose("Comparator", ["comparator"], node.comparator, [
            "gt", "gte", "lt", "lte", "eq", "crosses_above", "crosses_below",
          ])}
          {number("Value", ["value"], node.value)}
          {text("Reference series", ["reference"], node.reference)}
        </>
      )}
      {kind === "condition" && node.kind !== "indicator" && (
        <p className="text-sm text-muted-foreground">{selected.label}</p>
      )}

      {kind === "stop_loss" && (
        <>
          {choose("Model", ["model"], node.model, ["fixed_pips", "atr", "structure"])}
          {number("Value", ["value"], node.value)}
          {number("ATR period", ["atr_period"], node.atr_period)}
        </>
      )}

      {kind === "take_profit" && (
        <>
          {choose("Model", ["model"], node.model, ["rr", "fixed_pips", "atr"])}
          {number("Value", ["value"], node.value)}
          {number("Close %", ["close_percent"], node.close_percent)}
        </>
      )}

      {kind === "risk" && (
        <>
          {choose("Model", ["model"], node.model, ["fixed_percent", "fixed_amount", "atr_based"])}
          {number("Value", ["value"], node.value)}
        </>
      )}

      {kind === "guards" && (
        <p className="text-sm text-muted-foreground">
          Martingale, averaging-down, and grid are denied by default and stay locked.
        </p>
      )}

      {kind === "filters" && (
        <p className="text-sm text-muted-foreground">
          Session / news / time filters apply only when you add them.
        </p>
      )}
    </div>
  );
}
