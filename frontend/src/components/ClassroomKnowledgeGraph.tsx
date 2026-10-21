import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { Maximize2, Minimize2, RotateCcw, RotateCw, X } from "lucide-react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, forceZ } from "d3-force-3d";
import { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
import { AdditiveBlending, CanvasTexture, Quaternion, Vector3 } from "three";
import { moduleColor, visibleGraph, type GraphLayout } from "../lib/knowledgeGraph";
import type { ClassroomKnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode } from "../types";

type Props = {
  graph: ClassroomKnowledgeGraph;
  selectedNodeId: string;
  onSelect: (nodeId: string) => void;
};

type Position = [number, number, number];
type SimulationNode = KnowledgeGraphNode & { x?: number; y?: number; z?: number; vx?: number; vy?: number; vz?: number };
type SimulationLink = KnowledgeGraphEdge & { source: string | SimulationNode; target: string | SimulationNode };

const layoutNames: Record<GraphLayout, string> = {
  modules: "Module clusters",
  dependencies: "Dependency flow",
  free: "Free exploration",
};

export default function ClassroomKnowledgeGraph({ graph, selectedNodeId, onSelect }: Props) {
  const [isDesktop, setIsDesktop] = useState(() => typeof window !== "undefined" && window.innerWidth >= 768);
  const [webglAvailable, setWebglAvailable] = useState(() => supportsWebGL());
  const [activeModule, setActiveModule] = useState("");
  const [layout, setLayout] = useState<GraphLayout>("modules");
  const [layoutRevision, setLayoutRevision] = useState(0);
  const [cameraRevision, setCameraRevision] = useState(0);
  const [fitDistance, setFitDistance] = useState(9);
  const [fullscreen, setFullscreen] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState("");
  const [positions, setPositions] = useState<Record<string, Position>>({});

  const modules = useMemo(() => {
    const byId = new Map<string, string>();
    graph.nodes.forEach((node) => byId.set(node.moduleId, node.moduleName));
    return Array.from(byId, ([id, name]) => ({ id, name }));
  }, [graph.nodes]);
  const moduleColors = useMemo(() => Object.fromEntries(
    modules.map((module, index) => [module.id, moduleColor(module.id, index)]),
  ), [modules]);
  const data = useMemo(() => visibleGraph(graph), [graph]);
  const nodeById = useMemo(() => new Map(data.nodes.map((node) => [node.id, node])), [data.nodes]);
  const hoveredNode = nodeById.get(hoveredNodeId);

  useEffect(() => {
    const updateViewport = () => {
      setIsDesktop(window.innerWidth >= 768);
      setWebglAvailable(supportsWebGL());
    };
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  useEffect(() => {
    if (activeModule && !modules.some((module) => module.id === activeModule)) setActiveModule("");
  }, [activeModule, modules]);

  useEffect(() => {
    let frame = 0;
    const nodes: SimulationNode[] = data.nodes.map((node) => ({ ...node }));
    const links: SimulationLink[] = data.edges.map((edge) => ({ ...edge }));
    const connectionCounts = new Map<string, number>();
    links.forEach((edge) => {
      if (typeof edge.source === "string") connectionCounts.set(edge.source, (connectionCounts.get(edge.source) ?? 0) + 1);
      if (typeof edge.target === "string") connectionCounts.set(edge.target, (connectionCounts.get(edge.target) ?? 0) + 1);
    });
    const moduleIds = [...new Set(nodes.map((node) => node.moduleId))].sort();
    const moduleCenters = new Map(moduleIds.map((id, index) => {
      const vertical = 1 - 2 * (index + 0.5) / Math.max(moduleIds.length, 1);
      const radial = Math.sqrt(1 - vertical * vertical);
      const angle = index * Math.PI * (3 - Math.sqrt(5));
      const center = new Vector3(Math.cos(angle) * radial, vertical, Math.sin(angle) * radial);
      return [id, center.multiplyScalar(moduleIds.length > 1 ? 2.2 : 0)] as const;
    }));
    const targetPositions = new Map<string, Vector3>();
    const topicGroups = new Map<string, SimulationNode[]>();
    nodes.filter((node) => node.kind === "topic").forEach((node) => {
      const group = topicGroups.get(node.moduleId) ?? [];
      group.push(node);
      topicGroups.set(node.moduleId, group);
    });
    topicGroups.forEach((topics, moduleId) => {
      const moduleCenter = moduleCenters.get(moduleId) ?? new Vector3();
      topics.sort((first, second) => first.label.localeCompare(second.label));
      topics.forEach((topic, index) => {
        const angle = index * Math.PI * (3 - Math.sqrt(5));
        const spread = index === 0 ? 0 : 0.42 + Math.sqrt(index) * 0.24;
        targetPositions.set(topic.id, moduleCenter.clone().add(new Vector3(
          Math.cos(angle) * spread,
          ((index % 2) * 2 - 1) * spread * 0.32,
          Math.sin(angle) * spread,
        )));
      });
    });
    const parentByConcept = new Map<string, string>();
    links.forEach((edge) => {
      if (edge.kind === "contains" && typeof edge.source === "string" && typeof edge.target === "string") {
        parentByConcept.set(edge.target, edge.source);
      }
    });
    const conceptGroups = new Map<string, SimulationNode[]>();
    nodes.filter((node) => node.kind === "concept").forEach((node) => {
      const topicId = parentByConcept.get(node.id);
      if (!topicId) return;
      const group = conceptGroups.get(topicId) ?? [];
      group.push(node);
      conceptGroups.set(topicId, group);
    });
    conceptGroups.forEach((concepts, topicId) => {
      const topicPosition = targetPositions.get(topicId) ?? new Vector3();
      concepts.sort((first, second) => first.label.localeCompare(second.label));
      concepts.forEach((concept, index) => {
        const angle = index * Math.PI * (3 - Math.sqrt(5));
        const vertical = 1 - 2 * (index + 0.5) / Math.max(concepts.length, 1);
        const radial = Math.sqrt(1 - vertical * vertical);
        const offset = new Vector3(Math.cos(angle) * radial, vertical, Math.sin(angle) * radial)
          .multiplyScalar(0.62 + Math.sqrt(index) * 0.12);
        targetPositions.set(concept.id, topicPosition.clone().add(offset));
      });
    });
    nodes.forEach((node) => {
      const target = targetPositions.get(node.id) ?? moduleCenters.get(node.moduleId) ?? new Vector3();
      node.x = target.x;
      node.y = target.y;
      node.z = target.z;
      targetPositions.set(node.id, target);
    });
    const initialBounds = Math.max(...[...targetPositions.values()].map((position) => position.length() + 1.8), 1);
    setFitDistance(Math.max(7, initialBounds * 3.2));
    const flowRanks = new Map(nodes.map((node) => [node.id, 0]));
    data.edges.filter((edge) => edge.kind === "prerequisite").forEach((edge) => {
      flowRanks.set(edge.target, Math.max(flowRanks.get(edge.target) ?? 0, (flowRanks.get(edge.source) ?? 0) + 1));
    });

    const simulation = forceSimulation(nodes, 3)
      .force("links", forceLink(links).id((node: SimulationNode) => node.id)
        .distance((edge: SimulationLink) => edge.kind === "contains" ? 0.9 : 1.35).strength(0.62))
      .force("charge", forceManyBody().strength(-2.5))
      .force("collision", forceCollide((node: SimulationNode) =>
        0.22 + nodeRadius(node, connectionCounts.get(node.id) ?? 0) * 0.7 + Math.min(node.label.length, 20) * 0.006,
      ).strength(0.82))
      .force("center", forceCenter(0, 0, 0))
      .force("cluster-x", forceX((node: SimulationNode) => layout === "free" ? 0 : targetPositions.get(node.id)?.x ?? 0)
        .strength(layout === "modules" ? 0.3 : layout === "dependencies" ? 0.16 : 0.008))
      .force("cluster-y", forceY((node: SimulationNode) => layout === "free" ? 0 : layout === "dependencies" ? (flowRanks.get(node.id) ?? 0) * 0.85 : targetPositions.get(node.id)?.y ?? 0)
        .strength(layout === "dependencies" ? 0.2 : layout === "modules" ? 0.3 : 0.008))
      .force("cluster-z", forceZ((node: SimulationNode) => layout === "free" ? 0 : targetPositions.get(node.id)?.z ?? 0)
        .strength(layout === "modules" ? 0.3 : layout === "dependencies" ? 0.16 : 0.008))
      .alphaDecay(0.035);

    const updatePositions = () => {
      frame = 0;
      const next: Record<string, Position> = {};
      nodes.forEach((node) => {
        next[node.id] = [node.x ?? 0, node.y ?? 0, node.z ?? 0];
      });
      setPositions(next);
    };
    const scheduleUpdate = () => {
      if (!frame) frame = window.requestAnimationFrame(updatePositions);
    };
    simulation.on("tick", scheduleUpdate);
    simulation.on("end", () => {
      if (frame) window.cancelAnimationFrame(frame);
      updatePositions();
      const boundsRadius = Math.max(...nodes.map((node) =>
        Math.hypot(node.x ?? 0, node.y ?? 0, node.z ?? 0) + nodeRadius(node, connectionCounts.get(node.id) ?? 0) + 1.8,
      ), 1);
      setFitDistance(Math.max(7, boundsRadius * 3.2));
      simulation.stop();
    });
    scheduleUpdate();
    return () => {
      simulation.stop();
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [data, layout, layoutRevision]);

  if (graph.nodes.length === 0) {
    return <p className="rounded-xl border border-primary/15 bg-black/20 px-4 py-5 text-sm text-primary/70">Mastered or completed topics will appear here as you progress through the curriculum.</p>;
  }

  const graphContent = (
    <>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1 rounded-lg border border-primary/15 bg-black/25 p-1" role="group" aria-label="Graph layout">
          {(Object.keys(layoutNames) as GraphLayout[]).map((mode) => (
            <button key={mode} type="button" aria-pressed={layout === mode} onClick={() => setLayout(mode)}
              className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${layout === mode ? "bg-primary/15 text-primary" : "text-primary/80 hover:text-primary"}`}>
              {layoutNames[mode]}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <button type="button" title="Reset layout" aria-label="Reset layout" onClick={() => setLayoutRevision((value) => value + 1)} className="grid h-9 w-9 place-items-center rounded-lg border border-primary/15 bg-black/25 text-primary/75 hover:bg-primary/10"><RotateCcw size={16} /></button>
          <button type="button" title="Reset camera" aria-label="Reset camera" onClick={() => setCameraRevision((value) => value + 1)} className="grid h-9 w-9 place-items-center rounded-lg border border-primary/15 bg-black/25 text-primary/75 hover:bg-primary/10"><RotateCw size={16} /></button>
          {isDesktop && <button type="button" title={fullscreen ? "Exit fullscreen" : "Fullscreen graph"} aria-label={fullscreen ? "Exit fullscreen" : "Fullscreen graph"} onClick={() => setFullscreen((value) => !value)} className="grid h-9 w-9 place-items-center rounded-lg border border-primary/15 bg-black/25 text-primary/75 hover:bg-primary/10">{fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}</button>}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2" aria-label="Filter by curriculum module">
        {modules.map((module) => (
          <button key={module.id} type="button" aria-pressed={activeModule === module.id}
            onClick={() => setActiveModule((current) => current === module.id ? "" : module.id)}
            className={`flex min-w-0 items-center gap-2 text-xs transition-opacity ${activeModule && activeModule !== module.id ? "opacity-45" : "opacity-100"}`}>
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: moduleColors[module.id] }} />
            <span className="max-w-[220px] truncate text-primary/80">{module.name}</span>
          </button>
        ))}
        {activeModule && <button type="button" onClick={() => setActiveModule("")} className="text-xs text-primary/80 underline underline-offset-2">Clear filter</button>}
      </div>

      {!isDesktop ? (
        <MobileGraph nodes={data.nodes} moduleColors={moduleColors} selectedNodeId={selectedNodeId} onSelect={onSelect} />
      ) : !webglAvailable ? (
        <p className="rounded-xl border border-primary/15 bg-black/20 px-4 py-5 text-sm text-primary/70">3D rendering is unavailable in this browser. Use the module list above and select a topic to inspect its details.</p>
      ) : (
        <div className={`relative overflow-hidden border border-primary/25 bg-[#0b1115] ${fullscreen ? "min-h-0 flex-1 rounded-xl" : "h-[480px] rounded-[20px]"}`} aria-label="Interactive 3D classroom knowledge graph">
          <Canvas camera={{ position: [0, 3.4, 9], fov: 42 }} dpr={[1, 1.5]} fallback={<p className="p-4 text-sm">3D is unavailable. Use the module list above.</p>}>
            <color attach="background" args={["#0b1115"]} />
            <ambientLight intensity={1.15} />
            <pointLight position={[4, 6, 5]} intensity={18} color="#dce9df" />
            <OrbitControlsScene resetRevision={cameraRevision} fitDistance={fitDistance} />
            <GraphScene nodes={data.nodes} edges={data.edges} positions={positions} moduleColors={moduleColors} selectedNodeId={selectedNodeId} hoveredNodeId={hoveredNodeId} activeModule={activeModule} onSelect={onSelect} onHover={setHoveredNodeId} />
          </Canvas>
          <p className="pointer-events-none absolute right-3 top-3 rounded-md border border-white/10 bg-black/65 px-2 py-1 text-[10px] text-primary/70">Drag to freely rotate · scroll to zoom · right-drag to pan</p>
          {hoveredNode && <div className="pointer-events-none absolute bottom-3 left-3 max-w-[min(80%,420px)] rounded-lg border border-white/15 bg-black/90 px-3 py-2 text-xs text-primary backdrop-blur-sm"><span className="font-medium">{hoveredNode.label}</span><span className="ml-2 text-primary/80">{hoveredNode.moduleName}</span></div>}
        </div>
      )}
    </>
  );

  return fullscreen ? (
    <div className="fixed inset-3 z-50 flex flex-col overflow-auto rounded-2xl border border-primary/20 bg-[#080d12] p-4 shadow-2xl sm:inset-5 sm:p-5">
      <div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-medium text-primary/90">Classroom knowledge graph</h3><button onClick={() => setFullscreen(false)} aria-label="Exit fullscreen" title="Exit fullscreen" className="grid h-9 w-9 place-items-center rounded-lg border border-primary/15 text-primary/70"><X size={16} /></button></div>
      {graphContent}
    </div>
  ) : <div>{graphContent}</div>;
}

function supportsWebGL() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function MobileGraph({ nodes, moduleColors, selectedNodeId, onSelect }: { nodes: KnowledgeGraphNode[]; moduleColors: Record<string, string>; selectedNodeId: string; onSelect: (id: string) => void }) {
  return (
    <div className="grid gap-2 md:hidden" aria-label="Completed topics in the knowledge graph">
      {nodes.map((node) => (
        <button key={node.id} type="button" aria-pressed={selectedNodeId === node.id} onClick={() => onSelect(node.id)} className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left ${selectedNodeId === node.id ? "border-primary/35 bg-primary/10" : "border-primary/12 bg-black/20"}`}>
          <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: moduleColors[node.moduleId] ?? moduleColor(node.moduleId) }} />
          <span className="min-w-0 flex-1"><span className="block break-words text-sm text-primary/90">{node.label}</span><span className="mt-1 block text-xs text-primary/55">{node.moduleName} · {node.mastery.score === null ? (node.started ? "Started · no assessment evidence" : "No assessment evidence") : `${node.mastery.score}% mastery · ${node.mastery.state}`}</span></span>
        </button>
      ))}
    </div>
  );
}

function OrbitControlsScene({ resetRevision, fitDistance }: { resetRevision: number; fitDistance: number }) {
  const { camera, gl } = useThree();
  const controlsRef = useRef<TrackballControls | null>(null);
  useFrame(() => controlsRef.current?.update());
  useEffect(() => {
    const controls = new TrackballControls(camera, gl.domElement);
    controls.rotateSpeed = 2.2;
    controls.zoomSpeed = 0.8;
    controls.panSpeed = 0.7;
    controls.staticMoving = false;
    controls.dynamicDampingFactor = 0.12;
    controls.minDistance = 3;
    controls.maxDistance = Math.max(22, fitDistance * 1.8);
    controlsRef.current = controls;
    return () => {
      controlsRef.current = null;
      controls.dispose();
    };
  }, [camera, gl]);
  useEffect(() => {
    camera.position.set(0, fitDistance * 0.24, fitDistance);
    camera.lookAt(0, 0, 0);
    if (controlsRef.current) {
      controlsRef.current.target.set(0, 0, 0);
      controlsRef.current.maxDistance = Math.max(22, fitDistance * 1.8);
    }
    controlsRef.current?.update();
  }, [camera, fitDistance, resetRevision]);
  return null;
}

function GraphScene({ nodes, edges, positions, moduleColors, selectedNodeId, hoveredNodeId, activeModule, onSelect, onHover }: {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  positions: Record<string, Position>;
  moduleColors: Record<string, string>;
  selectedNodeId: string;
  hoveredNodeId: string;
  activeModule: string;
  onSelect: (nodeId: string) => void;
  onHover: (nodeId: string) => void;
}) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const validEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
  const degrees = new Map<string, number>();
  validEdges.forEach((edge) => {
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
  });
  const radiusFor = (node: KnowledgeGraphNode) => nodeRadius(node, degrees.get(node.id) ?? 0);
  const relatedIds = new Set<string>();
  if (hoveredNodeId) {
    relatedIds.add(hoveredNodeId);
    validEdges.forEach((edge) => {
      if (edge.source === hoveredNodeId) relatedIds.add(edge.target);
      if (edge.target === hoveredNodeId) relatedIds.add(edge.source);
    });
  }
  const moduleNodeIds = new Set(nodes.filter((node) => node.moduleId === activeModule).map((node) => node.id));
  const moduleRelatedIds = new Set(moduleNodeIds);
  const moduleRelatedEdges = new Set<string>();
  if (activeModule) validEdges.forEach((edge) => {
    if (!moduleNodeIds.has(edge.source) && !moduleNodeIds.has(edge.target)) return;
    moduleRelatedIds.add(edge.source);
    moduleRelatedIds.add(edge.target);
    moduleRelatedEdges.add(`${edge.source}\u0000${edge.target}\u0000${edge.kind}`);
  });

  return (
    <group>
      {validEdges.map((edge) => {
        const start = positions[edge.source];
        const end = positions[edge.target];
        if (!start || !end) return null;
        const from = new Vector3(...start);
        const to = new Vector3(...end);
        const vector = new Vector3().subVectors(to, from);
        if (vector.lengthSq() < 0.001) return null;
        const startNode = nodeById.get(edge.source);
        const endNode = nodeById.get(edge.target);
        if (!startNode || !endNode) return null;
        const direction = vector.clone().normalize();
        from.addScaledVector(direction, radiusFor(startNode));
        to.addScaledVector(direction, -radiusFor(endNode));
        vector.subVectors(to, from);
        if (vector.lengthSq() < 0.001) return null;
        const quaternion = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), vector.clone().normalize());
        const emphasized = hoveredNodeId
          ? relatedIds.has(edge.source) && relatedIds.has(edge.target)
          : moduleRelatedEdges.has(`${edge.source}\u0000${edge.target}\u0000${edge.kind}`);
        const connectionDensity = (degrees.get(edge.source) ?? 0) + (degrees.get(edge.target) ?? 0);
        const edgeRadius = Math.min(0.034, 0.012 + connectionDensity * 0.0015);
        const edgeOpacity = hoveredNodeId || activeModule ? emphasized ? 0.82 : 0.06 : Math.min(0.52, 0.24 + connectionDensity * 0.012);
        return (
          <mesh key={`${edge.source}-${edge.target}-${edge.kind}`} position={from.add(to).multiplyScalar(0.5)} quaternion={quaternion}>
            <cylinderGeometry args={[edgeRadius, edgeRadius, vector.length(), 7]} />
            <meshBasicMaterial color={moduleColors[startNode.moduleId] ?? moduleColor(startNode.moduleId)} transparent opacity={edgeOpacity} depthWrite={false} />
          </mesh>
        );
      })}
      {nodes.map((node) => {
        const position = positions[node.id];
        const radius = radiusFor(node);
        const color = moduleColors[node.moduleId] ?? moduleColor(node.moduleId);
        const dimmed = Boolean((hoveredNodeId && !relatedIds.has(node.id)) || (activeModule && !moduleRelatedIds.has(node.id)));
        const selected = selectedNodeId === node.id;
        if (!position) return null;
        return (
          <group key={node.id} position={new Vector3(...position)} scale={selected ? 1.16 : 1}>
            <mesh>
              <sphereGeometry args={[radius * 1.75, 20, 16]} />
              <meshBasicMaterial color={color} transparent opacity={dimmed ? 0.025 : 0.12} blending={AdditiveBlending} depthWrite={false} />
            </mesh>
            <mesh onPointerOver={(event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); onHover(node.id); }} onPointerOut={() => onHover("")} onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(node.id); }}>
              <sphereGeometry args={[radius, 24, 20]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected || hoveredNodeId === node.id ? 0.56 : 0.19} transparent opacity={dimmed ? 0.18 : 1} roughness={0.38} metalness={0.12} />
            </mesh>
            <NodeLabel label={node.label} position={[radius + 0.12, 0.1, 0]} selected={selected} />
          </group>
        );
      })}
    </group>
  );
}

function nodeRadius(node: KnowledgeGraphNode, degree: number) {
  return (node.kind === "topic" ? 0.31 : 0.21)
    + Math.min(degree, 10) * 0.025
    + (node.mastery.score ?? 0) / 600
    + (node.mastered ? 0.05 : 0);
}

function NodeLabel({ label, position, selected }: { label: string; position: Position; selected: boolean }) {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (context) {
      const fontSize = selected ? 50 : 40;
      const font = `600 ${fontSize}px Almarai, sans-serif`;
      const maxLineWidth = selected ? 700 : 520;
      context.font = font;
      const lines: string[] = [];
      let currentLine = "";
      label.split(/\s+/).forEach((word) => {
        if (context.measureText(word).width > maxLineWidth) {
          if (currentLine) lines.push(currentLine);
          currentLine = "";
          let fragment = "";
          for (const character of word) {
            if (fragment && context.measureText(fragment + character).width > maxLineWidth) {
              lines.push(fragment);
              fragment = character;
            } else {
              fragment += character;
            }
          }
          currentLine = fragment;
          return;
        }
        const candidate = currentLine ? `${currentLine} ${word}` : word;
        if (currentLine && context.measureText(candidate).width > maxLineWidth) {
          lines.push(currentLine);
          currentLine = word;
        } else {
          currentLine = candidate;
        }
      });
      if (currentLine) lines.push(currentLine);
      const textWidth = Math.max(0, ...lines.map((line) => Math.min(context.measureText(line).width, maxLineWidth)));
      const paddingX = selected ? 26 : 20;
      const paddingY = selected ? 18 : 12;
      const lineHeight = selected ? 58 : 46;
      canvas.width = Math.ceil(Math.max(100, textWidth + paddingX * 2));
      canvas.height = lines.length * lineHeight + paddingY * 2;
      context.font = font;
      context.fillStyle = selected ? "rgba(3, 7, 9, 0.98)" : "rgba(8, 13, 18, 0.84)";
      context.strokeStyle = selected ? "rgba(248, 247, 239, 0.9)" : "rgba(225, 224, 204, 0.3)";
      context.lineWidth = selected ? 4 : 2;
      context.beginPath();
      context.roundRect(2, 2, canvas.width - 4, canvas.height - 4, selected ? 16 : 12);
      context.fill();
      context.stroke();
      context.fillStyle = "rgba(248, 247, 239, 1)";
      context.textBaseline = "middle";
      lines.forEach((line, index) => {
        context.fillText(line, paddingX, paddingY + lineHeight * index + lineHeight / 2, maxLineWidth);
      });
    }
    const map = new CanvasTexture(canvas);
    map.colorSpace = "srgb";
    map.needsUpdate = true;
    return map;
  }, [label, selected]);
  useEffect(() => () => texture.dispose(), [texture]);
  const height = texture.image.height / 60 * (selected ? 0.27 : 0.23);
  const width = texture.image.width / 60 * (selected ? 0.27 : 0.23);
  return <sprite position={position} scale={[width, height, 1]} renderOrder={selected ? 4 : 2} frustumCulled={false}><spriteMaterial map={texture} transparent depthWrite={false} /></sprite>;
}
