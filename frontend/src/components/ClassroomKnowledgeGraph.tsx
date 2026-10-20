import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, ThreeEvent, useFrame, useThree } from "@react-three/fiber";
import { Maximize2, Minimize2, RotateCcw, RotateCw, X } from "lucide-react";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY, forceZ } from "d3-force-3d";
import { TrackballControls } from "three/examples/jsm/controls/TrackballControls.js";
import { CanvasTexture, Quaternion, Vector3 } from "three";
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
  const [fullscreen, setFullscreen] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState("");
  const [positions, setPositions] = useState<Record<string, Position>>({});

  const modules = useMemo(() => {
    const byId = new Map<string, string>();
    graph.nodes.forEach((node) => byId.set(node.moduleId, node.moduleName));
    return Array.from(byId, ([id, name]) => ({ id, name }));
  }, [graph.nodes]);
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
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const links: SimulationLink[] = data.edges.map((edge) => ({ ...edge }));
    const moduleIds = [...new Set(nodes.map((node) => node.moduleId))].sort();
    const moduleCenters = new Map(moduleIds.map((id, index) => {
      const angle = 2 * Math.PI * index / Math.max(moduleIds.length, 1);
      const radius = moduleIds.length > 1 ? 2.2 : 0;
      return [id, new Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius)] as const;
    }));
    const flowRanks = new Map(nodes.map((node) => [node.id, 0]));
    data.edges.filter((edge) => edge.kind === "prerequisite").forEach((edge) => {
      flowRanks.set(edge.target, Math.max(flowRanks.get(edge.target) ?? 0, (flowRanks.get(edge.source) ?? 0) + 1));
    });

    const simulation = forceSimulation(nodes, 3)
      .force("links", forceLink(links).id((node: SimulationNode) => node.id)
        .distance((edge: SimulationLink) => edge.kind === "contains" ? 1.15 : 1.8).strength(0.72))
      .force("charge", forceManyBody().strength(-8))
      .force("collision", forceCollide((node: SimulationNode) => 0.54 + Math.min(node.label.length, 20) * 0.022).strength(0.85))
      .force("center", forceCenter(0, 0, 0))
      .force("cluster-x", forceX((node: SimulationNode) => layout === "free" ? 0 : moduleCenters.get(node.moduleId)?.x ?? 0)
        .strength(layout === "modules" ? 0.14 : layout === "dependencies" ? 0.025 : 0.008))
      .force("cluster-z", forceZ((node: SimulationNode) => layout === "free" ? 0 : moduleCenters.get(node.moduleId)?.z ?? 0)
        .strength(layout === "modules" ? 0.14 : layout === "dependencies" ? 0.025 : 0.008))
      .force("flow-y", forceY((node: SimulationNode) => layout === "dependencies" ? (flowRanks.get(node.id) ?? 0) * 1.2 : 0)
        .strength(layout === "dependencies" ? 0.16 : 0.018))
      .alphaDecay(0.035);

    const updatePositions = () => {
      frame = 0;
      const next: Record<string, Position> = {};
      const center = nodes.reduce((sum, node) => ({
        x: sum.x + (node.x ?? 0),
        y: sum.y + (node.y ?? 0),
        z: sum.z + (node.z ?? 0),
      }), { x: 0, y: 0, z: 0 });
      center.x /= Math.max(nodes.length, 1);
      center.y /= Math.max(nodes.length, 1);
      center.z /= Math.max(nodes.length, 1);
      nodes.forEach((node) => {
        next[node.id] = [(node.x ?? 0) - center.x, (node.y ?? 0) - center.y, (node.z ?? 0) - center.z];
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
            <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ backgroundColor: moduleColor(module.id) }} />
            <span className="max-w-[220px] truncate text-primary/80">{module.name}</span>
          </button>
        ))}
        {activeModule && <button type="button" onClick={() => setActiveModule("")} className="text-xs text-primary/80 underline underline-offset-2">Clear filter</button>}
      </div>

      {!isDesktop ? (
        <MobileGraph nodes={data.nodes} selectedNodeId={selectedNodeId} onSelect={onSelect} />
      ) : !webglAvailable ? (
        <p className="rounded-xl border border-primary/15 bg-black/20 px-4 py-5 text-sm text-primary/70">3D rendering is unavailable in this browser. Use the module list above and select a topic to inspect its details.</p>
      ) : (
        <div className={`relative overflow-hidden border border-primary/25 bg-[#0b1115] ${fullscreen ? "min-h-0 flex-1 rounded-xl" : "h-[480px] rounded-[20px]"}`} aria-label="Interactive 3D classroom knowledge graph">
          <Canvas camera={{ position: [0, 3.4, 9], fov: 42 }} dpr={[1, 1.5]} fallback={<p className="p-4 text-sm">3D is unavailable. Use the module list above.</p>}>
            <color attach="background" args={["#0b1115"]} />
            <ambientLight intensity={1.15} />
            <pointLight position={[4, 6, 5]} intensity={18} color="#dce9df" />
            <OrbitControlsScene resetRevision={cameraRevision} />
            <GraphScene nodes={data.nodes} edges={data.edges} positions={positions} selectedNodeId={selectedNodeId} hoveredNodeId={hoveredNodeId} activeModule={activeModule} onSelect={onSelect} onHover={setHoveredNodeId} />
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

function MobileGraph({ nodes, selectedNodeId, onSelect }: { nodes: KnowledgeGraphNode[]; selectedNodeId: string; onSelect: (id: string) => void }) {
  return (
    <div className="grid gap-2 md:hidden" aria-label="Completed topics in the knowledge graph">
      {nodes.map((node) => (
        <button key={node.id} type="button" aria-pressed={selectedNodeId === node.id} onClick={() => onSelect(node.id)} className={`flex w-full items-start gap-3 rounded-lg border p-3 text-left ${selectedNodeId === node.id ? "border-primary/35 bg-primary/10" : "border-primary/12 bg-black/20"}`}>
          <span className="mt-1 h-3 w-3 shrink-0 rounded-full" style={{ backgroundColor: moduleColor(node.moduleId) }} />
          <span className="min-w-0 flex-1"><span className="block break-words text-sm text-primary/90">{node.label}</span><span className="mt-1 block text-xs text-primary/55">{node.moduleName} · {node.mastery.score === null ? (node.started ? "Started · no assessment evidence" : "No assessment evidence") : `${node.mastery.score}% mastery · ${node.mastery.state}`}</span></span>
        </button>
      ))}
    </div>
  );
}

function OrbitControlsScene({ resetRevision }: { resetRevision: number }) {
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
    controls.maxDistance = 22;
    controlsRef.current = controls;
    return () => {
      controlsRef.current = null;
      controls.dispose();
    };
  }, [camera, gl]);
  useEffect(() => {
    controlsRef.current?.reset();
    controlsRef.current?.update();
  }, [resetRevision]);
  return null;
}

function GraphScene({ nodes, edges, positions, selectedNodeId, hoveredNodeId, activeModule, onSelect, onHover }: {
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
  positions: Record<string, Position>;
  selectedNodeId: string;
  hoveredNodeId: string;
  activeModule: string;
  onSelect: (nodeId: string) => void;
  onHover: (nodeId: string) => void;
}) {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const validEdges = edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target));
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
        from.addScaledVector(direction, nodeRadius(startNode));
        to.addScaledVector(direction, -nodeRadius(endNode));
        vector.subVectors(to, from);
        if (vector.lengthSq() < 0.001) return null;
        const quaternion = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), vector.clone().normalize());
        const emphasized = hoveredNodeId
          ? relatedIds.has(edge.source) && relatedIds.has(edge.target)
          : moduleRelatedEdges.has(`${edge.source}\u0000${edge.target}\u0000${edge.kind}`);
        return (
          <mesh key={`${edge.source}-${edge.target}-${edge.kind}`} position={from.add(to).multiplyScalar(0.5)} quaternion={quaternion}>
            <cylinderGeometry args={[edge.kind === "prerequisite" ? 0.025 : 0.016, edge.kind === "prerequisite" ? 0.025 : 0.016, vector.length(), 6]} />
            <meshBasicMaterial color={edge.kind === "prerequisite" ? "#d4c8a0" : "#70878a"} transparent opacity={hoveredNodeId || activeModule ? emphasized ? 0.88 : 0.07 : 0.46} />
          </mesh>
        );
      })}
      {nodes.map((node) => {
        const position = positions[node.id];
        const radius = nodeRadius(node);
        const color = moduleColor(node.moduleId);
        const dimmed = Boolean((hoveredNodeId && !relatedIds.has(node.id)) || (activeModule && !moduleRelatedIds.has(node.id)));
        const selected = selectedNodeId === node.id;
        if (!position) return null;
        return (
          <group key={node.id} position={new Vector3(...position)} scale={selected ? 1.16 : 1}>
            <mesh onPointerOver={(event: ThreeEvent<PointerEvent>) => { event.stopPropagation(); onHover(node.id); }} onPointerOut={() => onHover("")} onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(node.id); }}>
              <sphereGeometry args={[radius, 24, 20]} />
              <meshStandardMaterial color={color} emissive={color} emissiveIntensity={selected || hoveredNodeId === node.id ? 0.56 : 0.19} transparent opacity={dimmed ? 0.18 : 1} roughness={0.38} metalness={0.12} />
            </mesh>
            <NodeLabel label={node.label} position={[radius + 0.12, 0.1, 0]} />
          </group>
        );
      })}
    </group>
  );
}

function nodeRadius(node: KnowledgeGraphNode) {
  return (node.kind === "topic" ? 0.34 : 0.25) + (node.mastery.score ?? 0) / 500 + (node.mastered ? 0.06 : 0);
}

function NodeLabel({ label, position }: { label: string; position: Position }) {
  const texture = useMemo(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 768;
    canvas.height = 160;
    const context = canvas.getContext("2d");
    if (context) {
      context.fillStyle = "rgba(8, 13, 18, 0.94)";
      context.strokeStyle = "rgba(225, 224, 204, 0.24)";
      context.lineWidth = 3;
      context.beginPath();
      context.roundRect(4, 4, canvas.width - 8, canvas.height - 8, 22);
      context.fill();
      context.stroke();
      context.font = "600 42px Almarai, sans-serif";
      context.fillStyle = "rgba(248, 247, 239, 1)";
      context.textBaseline = "middle";
      const measured = context.measureText(label).width;
      const shortened = measured > 720 ? `${label.slice(0, 28)}…` : label;
      context.fillText(shortened, 22, canvas.height / 2, 720);
    }
    const map = new CanvasTexture(canvas);
    map.colorSpace = "srgb";
    map.needsUpdate = true;
    return map;
  }, [label]);
  useEffect(() => () => texture.dispose(), [texture]);
  return <sprite position={position} scale={[3.15, 0.66, 1]} renderOrder={2}><spriteMaterial map={texture} transparent depthWrite={false} /></sprite>;
}
