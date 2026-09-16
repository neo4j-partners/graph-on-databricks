// RingThumb.tsx
// Per-ring topology preview. When the backend ships real nodes/edges from
// Neo4j, renders them with Cytoscape via RingGraph. Falls back to the static
// SVG layout for legacy/empty payloads.

import { useMemo } from "react";
import { RingGraph, type RingGraphEdge, type RingGraphNode } from "@/components/RingGraph";
import { ringLayout, type Topology } from "@/lib/ringLayout";
import { NODE_INK, NODE_INK_DIM, RISK_COLOR, type Risk } from "@/lib/riskColors";
import { cn } from "@/lib/utils";

export interface RingThumbProps {
  ring: {
    ring_id: string;
    nodes: number;
    topology: Topology;
    risk: Risk;
    graph?: {
      nodes: RingGraphNode[];
      edges: RingGraphEdge[];
    };
  };
  width?: number;
  height?: number;
  selected?: boolean;
  className?: string;
}

export function RingThumb({
  ring,
  width = 96,
  height = 44,
  selected = false,
  className,
}: RingThumbProps) {
  const hasRealGraph = !!ring.graph && ring.graph.nodes.length > 0;

  if (hasRealGraph && ring.graph) {
    return (
      <RingGraph
        nodes={ring.graph.nodes}
        edges={ring.graph.edges}
        width={width}
        height={height}
        selected={selected}
        className={className}
        ariaLabel={`Ring ${ring.ring_id} topology, ${ring.graph.nodes.length} accounts`}
      />
    );
  }

  return <StaticRingThumb ring={ring} width={width} height={height} selected={selected} className={className} />;
}

// Legacy static SVG thumbnail — used when the backend has not populated graph
// data (empty rings, fallback). Preserved verbatim from the wireframe.
function StaticRingThumb({
  ring,
  width,
  height,
  selected,
  className,
}: {
  ring: RingThumbProps["ring"];
  width: number;
  height: number;
  selected: boolean;
  className?: string;
}) {
  const { nodes, edges } = useMemo(
    () =>
      ringLayout(
        { id: ring.ring_id, nodes: ring.nodes, topology: ring.topology },
        width,
        height,
        { maxNodes: 12 },
      ),
    [ring.ring_id, ring.nodes, ring.topology, width, height],
  );

  const stroke = RISK_COLOR[ring.risk];
  const edgeColor = selected ? stroke : NODE_INK_DIM;

  return (
    <svg
      className={cn("block", className)}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      aria-hidden="true"
    >
      <g stroke={edgeColor} strokeWidth={1} fill="none" opacity={0.85}>
        {edges
          .filter(([a, b]) => nodes[a] && nodes[b])
          .map(([a, b], i) => (
            <line
              key={i}
              x1={nodes[a].x}
              y1={nodes[a].y}
              x2={nodes[b].x}
              y2={nodes[b].y}
            />
          ))}
      </g>
      <g>
        {nodes.map((p, i) => {
          const fill = p.hub || selected ? stroke : NODE_INK;
          const opacity = p.hub ? 1 : 0.85;
          return (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={p.hub ? 2.6 : 1.8}
              fill={fill}
              opacity={opacity}
            />
          );
        })}
      </g>
    </svg>
  );
}

export default RingThumb;
