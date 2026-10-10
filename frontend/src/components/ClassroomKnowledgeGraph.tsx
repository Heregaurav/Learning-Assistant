import { useEffect, useState } from "react";
import { Canvas, ThreeEvent, useThree } from "@react-three/fiber";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { Quaternion, Vector3 } from "three";
import type { ClassroomKnowledgeGraph, KnowledgeGraphNode } from "../types";

type Props = {
  graph: ClassroomKnowledgeGraph;
  selectedNodeId: string;
  onSelect: (nodeId: string) => void;
};

export default function ClassroomKnowledgeGraph({ graph, selectedNodeId, onSelect }: Props) {
  const [webglAvailable] = useState(() => {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
    } catch {
      return false;
    }
  });

  if (!webglAvailable) {
    return <p className="py-3 text-sm text-primary/70">3D rendering is unavailable in this browser. The curriculum graph is available in the list below.</p>;
  }

  return (
    <div className="hidden h-[440px] overflow-hidden rounded-lg border border-primary/20 bg-[#101416] md:block" aria-label="Interactive 3D classroom knowledge graph">
      <Canvas camera={{ position: [0, 4.5, 8], fov: 45 }} dpr={[1, 1.5]} fallback={<p className="p-4 text-sm">3D is unavailable. Use the graph list below.</p>}>
        <ambientLight intensity={1.1} />
        <pointLight position={[4, 6, 5]} intensity={30} />
        <OrbitControlsScene />
        <GraphScene graph={graph} selectedNodeId={selectedNodeId} onSelect={onSelect} />
      </Canvas>
    </div>
  );
}

function OrbitControlsScene() {
  const { camera, gl } = useThree();
  useEffect(() => {
    const controls = new OrbitControls(camera, gl.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 3;
    controls.maxDistance = 18;
    return () => controls.dispose();
  }, [camera, gl]);
  return null;
}

function GraphScene({ graph, selectedNodeId, onSelect }: Props) {
  const positions = new Map<string, Vector3>();
  const topics = graph.nodes.filter((node) => node.kind === "topic");
  topics.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(topics.length, 1);
    const radius = topics.length === 1 ? 0 : 2.7;
    positions.set(node.id, new Vector3(Math.cos(angle) * radius, 0, Math.sin(angle) * radius));
  });

  const childrenByTopic = new Map<string, KnowledgeGraphNode[]>();
  graph.edges.filter((edge) => edge.kind === "contains").forEach((edge) => {
    const child = graph.nodes.find((node) => node.id === edge.target);
    if (!child) return;
    const current = childrenByTopic.get(edge.source) ?? [];
    current.push(child);
    childrenByTopic.set(edge.source, current);
  });
  childrenByTopic.forEach((children, parentId) => {
    const parentPosition = positions.get(parentId) ?? new Vector3();
    children.forEach((child, index) => {
      const angle = (2 * Math.PI * index) / Math.max(children.length, 1);
      positions.set(child.id, parentPosition.clone().add(new Vector3(Math.cos(angle) * 1.15, 0.85, Math.sin(angle) * 1.15)));
    });
  });

  return (
    <group>
      <gridHelper args={[12, 12, "#53636a", "#273339"]} position={[0, -1.1, 0]} />
      {graph.edges.map((edge) => {
        const start = positions.get(edge.source);
        const end = positions.get(edge.target);
        if (!start || !end) return null;
        const vector = new Vector3().subVectors(end, start);
        const quaternion = new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), vector.clone().normalize());
        return (
          <mesh key={`${edge.source}-${edge.target}-${edge.kind}`} position={start.clone().add(end).multiplyScalar(0.5)} quaternion={quaternion}>
            <cylinderGeometry args={[edge.kind === "prerequisite" ? 0.035 : 0.018, edge.kind === "prerequisite" ? 0.035 : 0.018, vector.length(), 7]} />
            <meshStandardMaterial color={edge.kind === "prerequisite" ? "#e5a451" : "#5799a3"} transparent opacity={0.78} />
          </mesh>
        );
      })}
      {graph.nodes.map((node) => {
        const mastery = node.mastery.score;
        const radius = node.kind === "topic" ? 0.38 + (mastery ?? 0) / 250 : 0.24 + (mastery ?? 0) / 300;
        const color = node.mastery.state === "strong" ? "#73c99a"
          : node.mastery.state === "developing" ? "#e4bf62"
          : node.mastery.state === "needs_improvement" ? "#dd7465"
          : node.mastery.state === "provisional" ? "#df9857"
          : "#87949a";
        return (
          <mesh
            key={node.id}
            position={positions.get(node.id) ?? new Vector3()}
            onClick={(event: ThreeEvent<MouseEvent>) => { event.stopPropagation(); onSelect(node.id); }}
          >
            <sphereGeometry args={[radius, 24, 16]} />
            <meshStandardMaterial
              color={selectedNodeId === node.id ? "#f2e4b7" : color}
              emissive={color}
              emissiveIntensity={selectedNodeId === node.id ? 0.55 : 0.18}
              transparent={node.coverage !== "covered"}
              opacity={node.coverage === "covered" ? 1 : 0.48}
              roughness={0.35}
            />
          </mesh>
        );
      })}
    </group>
  );
}
