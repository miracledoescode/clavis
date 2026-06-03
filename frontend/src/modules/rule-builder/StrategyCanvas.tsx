"use client";

import "@xyflow/react/dist/style.css";

import { useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";

import type { StrategySpec } from "@/contract/types";

import { specToGraph, type NodeData } from "./graph";
import { Inspector } from "./inspector";
import type { SetupDirectionInfo } from "./types";

interface SetupNodeData extends NodeData {
  index: number;
  name: string;
  direction: "long" | "short";
  exitSummary: string;
  riskSummary: string;
  inferred?: boolean;
  rationale?: string;
  confirmed?: boolean;
  onConfirm?: (i: number) => void;
  onFlip?: (i: number) => void;
}

/** Custom node: a setup carries its proposed direction + confirm/flip control. */
function SetupNode({ data }: NodeProps) {
  const d = data as SetupNodeData;
  return (
    <div className="w-56 rounded-lg border-2 bg-background p-3 text-xs shadow-sm">
      <Handle type="target" position={Position.Left} />
      <div className="text-sm font-semibold">{d.name}</div>
      <div className="mt-1">
        {d.confirmed ? (
          <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
            {d.direction.toUpperCase()} ✓ confirmed
          </span>
        ) : (
          <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-700 dark:text-amber-400">
            Proposed{d.inferred ? " · inferred" : ""}: {d.direction.toUpperCase()}
          </span>
        )}
      </div>
      {!d.confirmed && d.rationale ? (
        <p className="mt-1 text-muted-foreground">{d.rationale}</p>
      ) : null}
      {!d.confirmed ? (
        <div className="mt-2 flex gap-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              d.onConfirm?.(d.index);
            }}
            className="rounded bg-primary px-2 py-1 text-primary-foreground"
          >
            Confirm
          </button>
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              d.onFlip?.(d.index);
            }}
            className="rounded border px-2 py-1 hover:bg-accent"
          >
            Flip
          </button>
        </div>
      ) : null}
      <div className="mt-2 text-muted-foreground">{d.exitSummary}</div>
      <div className="text-muted-foreground">{d.riskSummary}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

const nodeTypes: NodeTypes = { setup: SetupNode };

/**
 * Renders the StrategySpec as an editable React Flow graph. The spec is the
 * source of truth; the inspector writes edits back, and each Setup node owns its
 * direction confirm/flip control.
 */
export function StrategyCanvas({
  spec,
  setupsInfo,
  confirmed,
  onConfirm,
  onFlip,
  onChange,
}: {
  spec: StrategySpec;
  setupsInfo: SetupDirectionInfo[];
  confirmed: boolean[];
  onConfirm: (i: number) => void;
  onFlip: (i: number) => void;
  onChange: (s: StrategySpec) => void;
}) {
  const [selected, setSelected] = useState<NodeData | null>(null);

  const { nodes, edges } = useMemo(() => {
    const g = specToGraph(spec);
    const decorated = g.nodes.map((n) => {
      if (n.data.kind !== "setup") return n;
      const idx = n.data.index as number;
      const info = setupsInfo.find((s) => s.index === idx);
      return {
        ...n,
        type: "setup",
        data: {
          ...n.data,
          inferred: info?.inferred ?? false,
          rationale: info?.rationale ?? "",
          confirmed: confirmed[idx] ?? false,
          onConfirm,
          onFlip,
        },
      };
    });
    return { nodes: decorated, edges: g.edges };
  }, [spec, setupsInfo, confirmed, onConfirm, onFlip]);

  return (
    <div className="flex h-[600px] w-full overflow-hidden rounded-lg border">
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => setSelected(node.data as NodeData)}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
      <aside className="w-80 shrink-0 overflow-auto border-l p-4">
        <Inspector spec={spec} selected={selected} onChange={onChange} />
      </aside>
    </div>
  );
}
