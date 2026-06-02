import type { Edge, Node } from "@xyflow/react";

import type { Condition, ConditionGroup, StrategySpec } from "@/contract/types";

export type NodeKind =
  | "strategy"
  | "instrument"
  | "timeframes"
  | "direction"
  | "group"
  | "condition"
  | "stop_loss"
  | "take_profit"
  | "risk"
  | "guards"
  | "filters";

/** Node payload. The index signature satisfies @xyflow/react's Node<T> constraint. */
export type NodeData = {
  label: string;
  kind: NodeKind;
  path: (string | number)[];
  [key: string]: unknown;
};

export type SpecNode = Node<NodeData>;

/** Immutable deep-set: returns a copy of `obj` with `path` set to `value`. */
export function setAtPath<T>(obj: T, path: (string | number)[], value: unknown): T {
  if (path.length === 0) return value as T;
  const [head, ...rest] = path;
  // Localized any: arbitrary-depth structural update over the StrategySpec.
  const src = obj as unknown as Record<string | number, unknown>;
  const clone: Record<string | number, unknown> = Array.isArray(obj)
    ? ([...(obj as unknown[])] as unknown as Record<string | number, unknown>)
    : { ...src };
  clone[head] = setAtPath(clone[head], rest, value);
  return clone as unknown as T;
}

function conditionLabel(c: Condition): string {
  switch (c.kind) {
    case "indicator": {
      const params = Object.values(c.params ?? {}).join(", ");
      const rhs = c.value != null ? ` ${c.value}` : c.reference ? ` ${c.reference}` : "";
      return `${c.indicator}(${params}) ${c.comparator}${rhs}`;
    }
    case "structure":
      return `${c.event} @ ${c.timeframe}`;
    case "candlestick":
      return `${c.pattern} @ ${c.timeframe}`;
    case "bias":
      return `${c.bias} bias @ ${c.timeframe}`;
    case "price_level":
      return `${c.level_type} ${c.comparator}${c.value != null ? ` ${c.value}` : ""}`;
  }
}

function isGroup(x: Condition | ConditionGroup): x is ConditionGroup {
  return typeof (x as ConditionGroup).operator === "string" && Array.isArray((x as ConditionGroup).children);
}

/** Derive a React Flow graph from a StrategySpec. The canvas is a view of the JSON. */
export function specToGraph(spec: StrategySpec): { nodes: SpecNode[]; edges: Edge[] } {
  const nodes: SpecNode[] = [];
  const edges: Edge[] = [];
  const add = (id: string, data: NodeData, x: number, y: number) =>
    nodes.push({ id, position: { x, y }, data });
  const link = (a: string, b: string) => edges.push({ id: `${a}->${b}`, source: a, target: b });

  add("strategy", { label: spec.name || "Strategy", kind: "strategy", path: ["name"] }, 0, 300);

  add(
    "instrument",
    { label: `${spec.instrument.symbol} · ${spec.instrument.asset_class}`, kind: "instrument", path: ["instrument"] },
    280,
    0,
  );
  add(
    "timeframes",
    {
      label: `Entry ${spec.timeframes.entry}${spec.timeframes.bias ? ` · bias ${spec.timeframes.bias}` : ""}`,
      kind: "timeframes",
      path: ["timeframes"],
    },
    280,
    80,
  );
  add("direction", { label: `Direction: ${spec.direction}`, kind: "direction", path: ["direction"] }, 280, 160);
  link("strategy", "instrument");
  link("strategy", "timeframes");
  link("strategy", "direction");

  // Entry condition tree (recursive).
  let row = 0;
  const layout = (group: ConditionGroup, path: (string | number)[], parentId: string, depth: number) => {
    const gid = `g:${path.join(".")}`;
    add(gid, { label: `${group.operator.toUpperCase()} (entry)`, kind: "group", path }, 280 + depth * 240, 280 + row * 64);
    link(parentId, gid);
    group.children.forEach((child, i) => {
      const cpath = [...path, "children", i];
      if (isGroup(child)) {
        layout(child, cpath, gid, depth + 1);
      } else {
        row += 1;
        const cid = `c:${cpath.join(".")}`;
        add(cid, { label: conditionLabel(child), kind: "condition", path: cpath }, 280 + (depth + 1) * 240, 280 + row * 64);
        link(gid, cid);
      }
    });
    row += 1;
  };
  layout(spec.entry.conditions, ["entry", "conditions"], "strategy", 0);

  // Exit.
  const sl = spec.exit.stop_loss;
  add(
    "sl",
    { label: `Stop: ${sl.model} ${sl.value}${sl.atr_period ? ` (ATR ${sl.atr_period})` : ""}`, kind: "stop_loss", path: ["exit", "stop_loss"] },
    0,
    470,
  );
  link("strategy", "sl");
  spec.exit.take_profit.forEach((tp, i) => {
    add(
      `tp${i}`,
      { label: `TP${i + 1}: ${tp.model} ${tp.value} · ${tp.close_percent}%`, kind: "take_profit", path: ["exit", "take_profit", i] },
      0,
      540 + i * 64,
    );
    link("sl", `tp${i}`);
  });

  // Risk.
  const pt = spec.risk.per_trade;
  add("risk", { label: `Risk: ${pt.model} ${pt.value}`, kind: "risk", path: ["risk", "per_trade"] }, 280, 470);
  link("strategy", "risk");
  add("guards", { label: "Guards: martingale / averaging-down / grid denied", kind: "guards", path: ["risk", "guards"] }, 280, 540);
  link("risk", "guards");

  // Filters (read-only summary).
  const f = spec.filters ?? {};
  const active = [
    f.sessions?.enabled ? "sessions" : null,
    f.news?.enabled ? "news" : null,
    f.time?.enabled ? "time" : null,
  ].filter(Boolean);
  add(
    "filters",
    { label: active.length ? `Filters: ${active.join(", ")}` : "No filters", kind: "filters", path: ["filters"] },
    280,
    240,
  );
  link("strategy", "filters");

  return { nodes, edges };
}
