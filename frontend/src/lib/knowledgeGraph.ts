import type { ClassroomKnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "../types";

export type GraphLayout = "modules" | "dependencies" | "free";

export function moduleColor(moduleId: string): string {
  let hash = 2166136261;
  for (const character of moduleId) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  const hue = Math.abs(hash) % 360;
  const saturation = 62 + ((hash >>> 8) % 13);
  const lightness = 58 + ((hash >>> 16) % 9);
  return `hsl(${hue} ${saturation}% ${lightness}%)`;
}

export function visibleGraph(
  graph: ClassroomKnowledgeGraph,
  moduleId?: string,
): ClassroomKnowledgeGraph {
  const seenNodes = new Set<string>();
  const nodes = graph.nodes.filter((node) => {
    if (moduleId && node.moduleId !== moduleId) return false;
    if (seenNodes.has(node.id)) return false;
    seenNodes.add(node.id);
    return true;
  });
  const seenEdges = new Set<string>();
  const edges: KnowledgeGraphEdge[] = graph.edges.filter((edge) => {
    if (!seenNodes.has(edge.source) || !seenNodes.has(edge.target)) return false;
    const key = `${edge.source}\u0000${edge.target}\u0000${edge.kind}`;
    if (seenEdges.has(key)) return false;
    seenEdges.add(key);
    return true;
  });
  return { ...graph, nodes: nodes as KnowledgeGraphNode[], edges };
}
