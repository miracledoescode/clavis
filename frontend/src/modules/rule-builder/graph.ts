import type { Edge, Node } from "@xyflow/react";

import type {
  Condition,
  ConditionGroup,
  ExitSpec,
  PerTradeRisk,
  StrategySpec,
} from "@/contract/types";

export type NodeKind =
  | "strategy"
  | "instrument"
  | "timeframes"
  | "guards"
  | "group"
  | "condition"
  | "setup";

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

function exitSummary(exit: ExitSpec): string {
  const sl = exit.stop_loss;
  const tps = exit.take_profit
    .map((t) => `${t.value}${t.model === "rr" ? "R" : ` ${t.model}`}`)
    .join(", ");
  return `Stop ${sl.model} ${sl.value}${sl.atr_period ? `/${sl.atr_period}` : ""} · TP ${tps || "—"}`;
}

function riskSummary(r: PerTradeRisk): string {
  return `Risk ${r.value}${r.model === "fixed_percent" ? "%" : ` (${r.model})`}`;
}

function countLeaves(g: ConditionGroup): number {
  return g.children.reduce((n, c) => n + (isGroup(c) ? countLeaves(c) : 1), 0);
}

/**
 * Derive a React Flow graph from a StrategySpec. The canvas is a VIEW of the JSON.
 * Each setup is a Setup node fed by its checklist (condition nodes -> group ->
 * setup). Multiple setups render as multiple bands.
 */
export function specToGraph(spec: StrategySpec): { nodes: SpecNode[]; edges: Edge[] } {
  const nodes: SpecNode[] = [];
  const edges: Edge[] = [];
  const add = (id: string, data: NodeData, x: number, y: number) =>
    nodes.push({ id, position: { x, y }, data });
  const link = (a: string, b: string) => edges.push({ id: `${a}->${b}`, source: a, target: b });

  add("strategy", { label: spec.name || "Strategy", kind: "strategy", path: [] }, 0, 0);
  add(
    "instrument",
    { label: `${spec.instrument.symbol} · ${spec.instrument.asset_class}`, kind: "instrument", path: ["instrument"] },
    260,
    -90,
  );
  add(
    "timeframes",
    {
      label: `Entry ${spec.timeframes.entry}${spec.timeframes.bias ? ` · bias ${spec.timeframes.bias}` : ""}`,
      kind: "timeframes",
      path: ["timeframes"],
    },
    260,
    -10,
  );
  add(
    "guards",
    { label: "Guards: martingale / averaging-down / grid denied", kind: "guards", path: ["risk", "guards"] },
    260,
    70,
  );
  link("strategy", "instrument");
  link("strategy", "timeframes");
  link("strategy", "guards");

  // Recursive checklist layout: conditions/groups flow INTO the sink (child -> parent).
  const layout = (
    group: ConditionGroup,
    basePath: (string | number)[],
    sinkId: string,
    x: number,
    startY: number,
  ): number => {
    const gid = `grp:${basePath.join(".")}`;
    let y = startY;
    const childCenters: number[] = [];
    group.children.forEach((child, idx) => {
      const cpath = [...basePath, "children", idx];
      if (isGroup(child)) {
        const c = layout(child, cpath, gid, x - 230, y);
        childCenters.push(c);
        y = c + 70;
      } else {
        const cid = `cnd:${cpath.join(".")}`;
        add(cid, { label: conditionLabel(child), kind: "condition", path: cpath }, x - 230, y);
        link(cid, gid);
        childCenters.push(y);
        y += 70;
      }
    });
    const center = childCenters.length
      ? (childCenters[0] + childCenters[childCenters.length - 1]) / 2
      : startY;
    add(gid, { label: group.operator.toUpperCase(), kind: "group", path: basePath }, x, center);
    link(gid, sinkId);
    return center;
  };

  let bandY = 220;
  spec.setups.forEach((setup, i) => {
    const setupId = `setup:${i}`;
    const center = layout(setup.entry, ["setups", i, "entry"], setupId, 360, bandY);
    add(
      setupId,
      {
        label: setup.name,
        kind: "setup",
        path: ["setups", i],
        index: i,
        name: setup.name,
        direction: setup.direction,
        exitSummary: exitSummary(setup.exit),
        riskSummary: riskSummary(setup.per_trade_risk),
      },
      640,
      center,
    );
    link("strategy", setupId);
    bandY = Math.max(bandY + countLeaves(setup.entry) * 70 + 150, center + 200);
  });

  return { nodes, edges };
}
