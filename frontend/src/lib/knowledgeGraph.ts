import type { ClassroomKnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "../types";

export type GraphLayout = "modules" | "dependencies" | "free";

const modulePalette = ["#ff5b55", "#35d07f", "#ffd166", "#4da3ff", "#ff8c42", "#b6e36b", "#22c1c3", "#f472b6"];

export function moduleColor(moduleId: string, paletteIndex?: number): string {
  let hash = 2166136261;
  for (const character of moduleId) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  const index = paletteIndex ?? (hash >>> 0) % modulePalette.length;
  return modulePalette[index % modulePalette.length];
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
