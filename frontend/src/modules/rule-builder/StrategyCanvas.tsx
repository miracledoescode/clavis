"use client";

import "@xyflow/react/dist/style.css";

import { useMemo, useState } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";

import type { StrategySpec } from "@/contract/types";

import { specToGraph, type NodeData } from "./graph";
import { Inspector } from "./inspector";

/**
 * Renders the StrategySpec as an editable React Flow tree. The spec is the
 * source of truth: the graph is derived from it, and the inspector writes edits
 * straight back via `onChange`.
 */
export function StrategyCanvas({
  spec,
  onChange,
}: {
  spec: StrategySpec;
  onChange: (s: StrategySpec) => void;
}) {
  const { nodes, edges } = useMemo(() => specToGraph(spec), [spec]);
  const [selected, setSelected] = useState<NodeData | null>(null);

  return (
    <div className="flex h-[560px] w-full overflow-hidden rounded-lg border">
      <div className="flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
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
