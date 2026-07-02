import dagre from 'dagre';
import {
  FlowNode, FlowEdge, FlowNodeData,
  IfNodeData, WhileNodeData, ForEachNodeData, SwitchNodeData,
} from '../types';

const DEFAULT_NODE_WIDTH = 180;
const DEFAULT_NODE_HEIGHT = 80;
const DEFAULT_PADDING = 24;

/** Recursively estimate pixel height for nested steps (used for container node sizing). */
function calculateNestedStepsHeight(steps: FlowNodeData[] | undefined): number {
  if (!steps || steps.length === 0) return 0;

  let totalHeight = 0;
  for (const step of steps) {
    switch (step.nodeType) {
      case 'if': {
        const { thenSteps, elseSteps } = step as IfNodeData;
        const branchHeight = Math.max(
          calculateNestedStepsHeight(thenSteps),
          calculateNestedStepsHeight(elseSteps),
        );
        totalHeight += 60 + branchHeight + 30;
        break;
      }
      case 'while':
      case 'for_each': {
        const { loopSteps } = step as WhileNodeData | ForEachNodeData;
        totalHeight += 50 + calculateNestedStepsHeight(loopSteps) + 30;
        break;
      }
      case 'switch': {
        const { cases, defaultSteps } = step as SwitchNodeData;
        let casesHeight = 0;
        if (cases) {
          for (const caseSteps of Object.values(cases)) {
            casesHeight += calculateNestedStepsHeight(caseSteps) + 40;
          }
        }
        totalHeight += 80 + casesHeight + calculateNestedStepsHeight(defaultSteps) + 50;
        break;
      }
      default:
        totalHeight += 40;
    }
  }
  return totalHeight;
}

// Calculate node dimensions based on type and content
export function getNodeDimensions(node: FlowNode): { width: number; height: number } {
  // Prefer measured size from ReactFlow when available (post-render).
  // This is the most reliable way to avoid overlaps when nodes auto-grow.
  const anyNode = node as unknown as {
    width?: number;
    height?: number;
    measured?: { width?: number; height?: number };
  };
  const mw = anyNode.measured?.width;
  const mh = anyNode.measured?.height;
  if (typeof mw === 'number' && mw > 0 && typeof mh === 'number' && mh > 0) {
    return { width: mw, height: mh };
  }
  if (typeof anyNode.width === 'number' && anyNode.width > 0 && typeof anyNode.height === 'number' && anyNode.height > 0) {
    return { width: anyNode.width, height: anyNode.height };
  }

  const nodeType = node.type;
  const data = node.data;

  if (nodeType === 'if') {
    const { thenSteps, elseSteps } = data as IfNodeData;
    const branchHeight = Math.max(
      calculateNestedStepsHeight(thenSteps) + 60,
      calculateNestedStepsHeight(elseSteps) + 60,
      60,
    );
    return { width: 320, height: Math.max(60 + branchHeight + 48, 150) };
  }

  if (nodeType === 'while' || nodeType === 'for_each') {
    const { loopSteps } = data as WhileNodeData;
    const loopHeight = calculateNestedStepsHeight(loopSteps);
    return { width: 220, height: Math.max(78 + Math.max(loopHeight + 48, 72) + 48, 150) };
  }
  
  if (nodeType === 'switch') {
    const { cases, defaultSteps } = data as SwitchNodeData;
    let totalCasesHeight = 0;
    const caseCount = cases ? Object.keys(cases).length : 0;
    if (cases) {
      for (const caseSteps of Object.values(cases)) {
        totalCasesHeight += calculateNestedStepsHeight(caseSteps) + 50;
      }
    }
    const defaultHeight = calculateNestedStepsHeight(defaultSteps) + 50;
    return { width: 350, height: Math.max(100 + totalCasesHeight + defaultHeight + 40, 200 + caseCount * 60) };
  }

  if (nodeType === 'gather') {
    const gatherData = data as unknown as { calls?: unknown[]; module?: string };
    const callsCount = gatherData.calls?.length || 0;
    // Base height ~80px + (calls * 30px per call); when module is set, submodule viewer adds more
    const baseHeight = 100 + (callsCount * 30);
    const expandedHeight = gatherData.module || callsCount > 0 ? baseHeight + 220 : baseHeight;
    return { width: DEFAULT_NODE_WIDTH, height: Math.max(expandedHeight, DEFAULT_NODE_HEIGHT) };
  }

  // Call / parallel with module show expanded submodule inline – use larger estimated height
  // so overlap resolution works before ReactFlow measured size is updated
  if (nodeType === 'call' || nodeType === 'parallel') {
    const hasModule = !!(data as { module?: string }).module;
    if (hasModule) {
      return { width: Math.max(DEFAULT_NODE_WIDTH, 260), height: 320 };
    }
  }

  // Default dimensions for other node types
  return { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
}

type Box = { x: number; y: number; w: number; h: number; id: string };

function boxesOverlap(a: Box, b: Box, pad: number): boolean {
  return (
    a.x < b.x + b.w + pad &&
    a.x + a.w + pad > b.x &&
    a.y < b.y + b.h + pad &&
    a.y + a.h + pad > b.y
  );
}

function resolveOverlaps(
  nodes: FlowNode[],
  nodeDimensions: Map<string, { width: number; height: number }>,
  direction: 'TB' | 'LR',
  pad: number = DEFAULT_PADDING
): FlowNode[] {
  // Deterministic, lightweight overlap resolution pass.
  // Dagre generally avoids overlaps, but our zig-zag xOffset can re-introduce them.
  const out = nodes.map((n) => ({ ...n, position: { ...n.position } }));

  const getBox = (n: FlowNode): Box => {
    const dim = nodeDimensions.get(n.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    return { id: n.id, x: n.position.x, y: n.position.y, w: dim.width, h: dim.height };
  };

  // We only push nodes "forward" (down in TB, right in LR) to preserve flow direction.
  const maxIters = 10;
  for (let iter = 0; iter < maxIters; iter++) {
    let moved = false;

    const sorted = [...out].sort((a, b) =>
      direction === 'TB' ? a.position.y - b.position.y : a.position.x - b.position.x
    );

    const placed: FlowNode[] = [];
    for (const n of sorted) {
      const dim = nodeDimensions.get(n.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      let nextPos = { ...n.position };

      for (const p of placed) {
        const a = { id: n.id, x: nextPos.x, y: nextPos.y, w: dim.width, h: dim.height };
        const pb = getBox(p);
        if (!boxesOverlap(a, pb, pad)) continue;

        if (direction === 'TB') {
          // push down below the placed node
          nextPos.y = Math.max(nextPos.y, pb.y + pb.h + pad);
        } else {
          // LR layout: preserve rankdir by avoiding large x drift; push down instead.
          nextPos.y = Math.max(nextPos.y, pb.y + pb.h + pad);
        }
      }

      if (nextPos.x !== n.position.x || nextPos.y !== n.position.y) {
        n.position = nextPos;
        moved = true;
      }
      placed.push(n);
    }

    if (!moved) break;
  }

  return out;
}

/**
 * Get the set of node IDs that belong to the same connected (task) flow as the given node.
 * Uses edges as undirected: two nodes are in the same flow if there is a path of edges between them.
 */
export function getConnectedNodeIds(nodeId: string, edges: FlowEdge[]): Set<string> {
  const adj = new Map<string, Set<string>>();
  const add = (a: string, b: string) => {
    if (!adj.has(a)) adj.set(a, new Set());
    adj.get(a)!.add(b);
  };
  edges.forEach((e) => {
    const s = e.source;
    const t = e.target;
    add(s, t);
    add(t, s);
  });
  const out = new Set<string>();
  const stack: string[] = [nodeId];
  out.add(nodeId);
  while (stack.length > 0) {
    const cur = stack.pop()!;
    for (const next of adj.get(cur) ?? []) {
      if (!out.has(next)) {
        out.add(next);
        stack.push(next);
      }
    }
  }
  return out;
}

/**
 * Resolve overlaps for a specific node by pushing down overlapping nodes.
 * Only nodes in the same connected task flow (as the target) are considered for overlap.
 * @param nodes All nodes in the graph
 * @param edges All edges (used to determine connected components)
 * @param targetNodeId The ID of the node that was expanded
 * @param nodeDimensions Map of node dimensions
 * @param pad Padding between nodes
 * @returns Updated nodes with overlaps resolved
 */
export function resolveOverlapsForNode(
  nodes: FlowNode[],
  edges: FlowEdge[],
  targetNodeId: string,
  nodeDimensions: Map<string, { width: number; height: number }>,
  pad: number = DEFAULT_PADDING
): FlowNode[] {
  const targetNode = nodes.find((n) => n.id === targetNodeId);
  if (!targetNode) return nodes;

  const inSameFlow = getConnectedNodeIds(targetNodeId, edges);

  const targetDim = nodeDimensions.get(targetNodeId) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
  const targetBox: Box = {
    id: targetNodeId,
    x: targetNode.position.x,
    y: targetNode.position.y,
    w: targetDim.width,
    h: targetDim.height,
  };

  // Only consider nodes in the same flow for overlap with target
  const overlappingInFlow: FlowNode[] = [];
  nodes.forEach((node) => {
    if (node.id === targetNodeId || !inSameFlow.has(node.id)) return;
    const nodeDim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    const nodeBox: Box = {
      id: node.id,
      x: node.position.x,
      y: node.position.y,
      w: nodeDim.width,
      h: nodeDim.height,
    };
    if (boxesOverlap(targetBox, nodeBox, pad)) overlappingInFlow.push(node);
  });

  if (overlappingInFlow.length === 0) {
    return nodes;
  }

  // Push down only nodes that overlap with target AND are in the same flow
  let updatedNodes = nodes.map((node) => {
    if (node.id === targetNodeId) return node;
    if (!inSameFlow.has(node.id)) return node;

    const nodeDim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    const nodeBox: Box = {
      id: node.id,
      x: node.position.x,
      y: node.position.y,
      w: nodeDim.width,
      h: nodeDim.height,
    };

    let newY = node.position.y;
    if (boxesOverlap(targetBox, nodeBox, pad)) {
      newY = Math.max(newY, targetBox.y + targetBox.h + pad);
    }
    if (newY !== node.position.y) {
      return { ...node, position: { ...node.position, y: newY } };
    }
    return node;
  });

  const buildPositionsMap = (nodeList: FlowNode[]): Map<string, { x: number; y: number }> => {
    const m = new Map<string, { x: number; y: number }>();
    nodeList.forEach((n) => m.set(n.id, n.position));
    return m;
  };

  const hasAnyOverlapInFlow = (nodeList: FlowNode[], positions?: Map<string, { x: number; y: number }>): boolean => {
    const inFlow = nodeList.filter((n) => inSameFlow.has(n.id));
    const posMap = positions ?? buildPositionsMap(nodeList);
    for (let i = 0; i < inFlow.length; i++) {
      const a = inFlow[i];
      const pa = posMap.get(a.id) ?? a.position;
      const dimA = nodeDimensions.get(a.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      const boxA: Box = { id: a.id, x: pa.x, y: pa.y, w: dimA.width, h: dimA.height };
      for (let j = i + 1; j < inFlow.length; j++) {
        const b = inFlow[j];
        const pb = posMap.get(b.id) ?? b.position;
        const dimB = nodeDimensions.get(b.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
        const boxB: Box = { id: b.id, x: pb.x, y: pb.y, w: dimB.width, h: dimB.height };
        if (boxesOverlap(boxA, boxB, pad)) return true;
      }
    }
    return false;
  };

  const maxIters = 20;
  for (let iter = 0; iter < maxIters; iter++) {
    const inFlowNodes = updatedNodes.filter((n) => inSameFlow.has(n.id));
    const sortedNodes = [...inFlowNodes].sort((a, b) => a.position.y - b.position.y);
    const placed: FlowNode[] = [];
    const newPositions = new Map<string, { x: number; y: number }>();

    sortedNodes.forEach((node) => {
      if (node.id === targetNodeId) {
        placed.push(node);
        newPositions.set(node.id, node.position);
        return;
      }
      const nodeDim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      let newPos = { ...node.position };

      // Push node down to avoid overlaps with already-placed nodes
      for (const placedNode of placed) {
        const px = newPositions.get(placedNode.id) ?? placedNode.position;
        const placedDim = nodeDimensions.get(placedNode.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
        const nodeBox: Box = { id: node.id, x: newPos.x, y: newPos.y, w: nodeDim.width, h: nodeDim.height };
        const placedBox: Box = { id: placedNode.id, x: px.x, y: px.y, w: placedDim.width, h: placedDim.height };
        if (boxesOverlap(nodeBox, placedBox, pad)) {
          newPos.y = Math.max(newPos.y, placedBox.y + placedBox.h + pad);
        }
      }

      newPositions.set(node.id, newPos);
      placed.push({ ...node, position: newPos });
    });

    updatedNodes = updatedNodes.map((node) => {
      if (!inSameFlow.has(node.id)) return node;
      const pos = newPositions.get(node.id);
      if (!pos) return node;
      return { ...node, position: pos };
    });

    if (!hasAnyOverlapInFlow(updatedNodes, newPositions)) break;
  }

  return updatedNodes;
}

export type LayoutOptions = {
  /** Compact layout: grid of nodes (auto rows × columns) instead of single row/column. */
  compact?: boolean;
};

// Compact grid: gap between cells; cap row height so one huge node doesn't blow up vertical spacing
const COMPACT_GRID_GAP = 30;
const COMPACT_GRID_MARGIN = 16;
const COMPACT_MAX_ROW_HEIGHT = 200;
// Default dagre spacing when not compact
const DEFAULT_NODESEP = 80;
const DEFAULT_RANKSEP = 150;
const DEFAULT_MARGIN = 50;

/** Build in/out edge maps. Outgoing stored with sourceHandle so we can put "next" (main flow) first. */
function buildGraph(
  nodes: FlowNode[],
  edges: FlowEdge[]
): {
  inEdges: Map<string, string[]>;
  outEdgesWithHandle: Map<string, { target: string; sourceHandle?: string }[]>;
  idSet: Set<string>;
} {
  const idSet = new Set(nodes.map((n) => n.id));
  const inEdges = new Map<string, string[]>();
  const outEdgesWithHandle = new Map<string, { target: string; sourceHandle?: string }[]>();
  nodes.forEach((n) => {
    inEdges.set(n.id, []);
    outEdgesWithHandle.set(n.id, []);
  });
  edges.forEach((e) => {
    if (!idSet.has(e.source) || !idSet.has(e.target)) return;
    inEdges.get(e.target)!.push(e.source);
    outEdgesWithHandle.get(e.source)!.push({
      target: e.target,
      sourceHandle: e.sourceHandle ?? undefined,
    });
  });
  return { inEdges, outEdgesWithHandle, idSet };
}

/** Main-flow handle first (next/bottom), then branch handles. */
function nextFlowPriority(handle: string | undefined): number {
  if (handle === undefined || handle === 'next' || handle === 'bottom' || handle === '') return 0;
  return 1;
}

/**
 * BFS order with "next" (main flow) edge first at each node. First column is strictly
 * Start → step1 → step2 → … along the main flow; no 4 above 3.
 */
function topoOrderIds(nodes: FlowNode[], edges: FlowEdge[]): string[] {
  const { inEdges, outEdgesWithHandle } = buildGraph(nodes, edges);
  const sources = nodes.filter((n) => (inEdges.get(n.id)?.length ?? 0) === 0).map((n) => n.id);
  if (sources.length === 0) return nodes.map((n) => n.id);

  const inDeg = new Map<string, number>();
  nodes.forEach((n) => inDeg.set(n.id, inEdges.get(n.id)!.length));

  const order: string[] = [];
  const queue: string[] = [...sources];

  while (queue.length > 0) {
    const id = queue.shift()!;
    order.push(id);
    const out = (outEdgesWithHandle.get(id) ?? []).slice();
    out.sort((a, b) => {
      const p = nextFlowPriority(a.sourceHandle) - nextFlowPriority(b.sourceHandle);
      if (p !== 0) return p;
      return a.target.localeCompare(b.target, undefined, { numeric: true });
    });
    for (const { target: targetId } of out) {
      const d = (inDeg.get(targetId) ?? 0) - 1;
      inDeg.set(targetId, d);
      if (d === 0) queue.push(targetId);
    }
  }

  return order.length === nodes.length ? order : nodes.map((n) => n.id);
}

/**
 * Place nodes in columns using greedy bin-packing by height budget.
 * Normal nodes (~80px) pack ~5 per column; oversized container nodes (while, for_each)
 * naturally get fewer neighbors or their own column, preventing one huge node from
 * stretching an entire column far beyond the others.
 *
 * Order = topo order; columns filled left-to-right (TB) or top-to-bottom (LR).
 */
function applyCompactGridLayout(
  nodes: FlowNode[],
  edges: FlowEdge[],
  direction: 'TB' | 'LR',
  nodeDimensions: Map<string, { width: number; height: number }>,
  gap: number,
  margin: number
): FlowNode[] {
  const n = nodes.length;
  if (n === 0) return nodes;
  const orderedIds = topoOrderIds(nodes, edges);
  const nodeById = new Map<string, FlowNode>();
  nodes.forEach((node) => nodeById.set(node.id, node));
  const orderedNodes = orderedIds.map((id) => nodeById.get(id)!).filter(Boolean);
  if (orderedNodes.length !== n) return nodes;

  // Stacking dimension helpers (TB: stack vertically, LR: stack horizontally)
  const mainSize = (node: FlowNode) => {
    const dim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    return direction === 'TB' ? dim.height : dim.width;
  };
  const crossSize = (node: FlowNode) => {
    const dim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
    return direction === 'TB' ? dim.width : dim.height;
  };

  // Height budget per column: roughly 5 normal-sized nodes.
  // Oversized nodes consume more budget → fewer nodes in that column.
  const maxGroupMain = 5 * (COMPACT_MAX_ROW_HEIGHT + gap);

  // Greedy bin-packing: fill each column until the next node would exceed the budget
  const groups: number[][] = [[]];
  let currentMain = 0;

  for (let i = 0; i < orderedNodes.length; i++) {
    const nodeMain = mainSize(orderedNodes[i]);
    const added = groups[groups.length - 1].length > 0 ? gap + nodeMain : nodeMain;

    if (groups[groups.length - 1].length > 0 && currentMain + added > maxGroupMain) {
      // Start a new column
      groups.push([i]);
      currentMain = nodeMain;
    } else {
      groups[groups.length - 1].push(i);
      currentMain += added;
    }
  }

  // Column cross-axis widths (actual dimensions, no cap)
  const numGroups = groups.length;
  const groupCrossWidths: number[] = new Array(numGroups).fill(0);
  for (let g = 0; g < numGroups; g++) {
    for (const i of groups[g]) {
      groupCrossWidths[g] = Math.max(groupCrossWidths[g], crossSize(orderedNodes[i]));
    }
  }

  // Cumulative cross-axis positions for each column
  const groupCrossPos: number[] = new Array(numGroups);
  groupCrossPos[0] = margin;
  for (let g = 1; g < numGroups; g++) {
    groupCrossPos[g] = groupCrossPos[g - 1] + groupCrossWidths[g - 1] + gap;
  }

  // Position each node: stack along main axis within its column
  const positionMap = new Map<string, { x: number; y: number }>();
  for (let g = 0; g < numGroups; g++) {
    let mainPos = margin;
    for (const i of groups[g]) {
      const node = orderedNodes[i];
      if (direction === 'TB') {
        positionMap.set(node.id, { x: groupCrossPos[g], y: mainPos });
      } else {
        positionMap.set(node.id, { x: mainPos, y: groupCrossPos[g] });
      }
      mainPos += mainSize(node) + gap;
    }
  }

  return orderedNodes.map((node) => ({
    ...node,
    position: positionMap.get(node.id)!,
  }));
}

/**
 * Find all connected components among nodes via edges (undirected).
 * Returns an array of node-ID sets, one per component.
 */
function findConnectedComponents(nodes: FlowNode[], edges: FlowEdge[]): Set<string>[] {
  const adj = new Map<string, Set<string>>();
  for (const n of nodes) adj.set(n.id, new Set());
  for (const e of edges) {
    adj.get(e.source)?.add(e.target);
    adj.get(e.target)?.add(e.source);
  }
  const visited = new Set<string>();
  const components: Set<string>[] = [];
  for (const n of nodes) {
    if (visited.has(n.id)) continue;
    const comp = new Set<string>();
    const stack = [n.id];
    while (stack.length > 0) {
      const cur = stack.pop()!;
      if (visited.has(cur)) continue;
      visited.add(cur);
      comp.add(cur);
      for (const nb of adj.get(cur) ?? []) {
        if (!visited.has(nb)) stack.push(nb);
      }
    }
    components.push(comp);
  }
  return components;
}

export function getLayoutedElements(
  nodes: FlowNode[],
  edges: FlowEdge[],
  direction: 'TB' | 'LR' = 'TB',
  options: LayoutOptions = {}
): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const { compact = false } = options;
  if (nodes.length === 0) {
    return { nodes, edges };
  }

  const nodeDimensions = new Map<string, { width: number; height: number }>();
  nodes.forEach((node) => {
    nodeDimensions.set(node.id, getNodeDimensions(node));
  });

  // ── Separate main workflow from orphan nodes ────────────────────
  // The main workflow is the connected component that contains a 'start' node.
  // All other components are treated as orphans and placed to the side.
  const components = findConnectedComponents(nodes, edges);
  const startNode = nodes.find((n) => n.type === 'start');
  const mainIds = startNode
    ? components.find((c) => c.has(startNode.id)) ?? new Set<string>()
    : components.reduce((largest, c) => (c.size > largest.size ? c : largest), new Set<string>());

  const mainNodes = nodes.filter((n) => mainIds.has(n.id));
  const orphanNodes = nodes.filter((n) => !mainIds.has(n.id));
  const mainEdges = edges.filter((e) => mainIds.has(e.source) && mainIds.has(e.target));

  // ── Layout main workflow ────────────────────────────────────────
  let layoutedMain: FlowNode[];

  if (compact) {
    layoutedMain = applyCompactGridLayout(
      mainNodes, mainEdges, direction, nodeDimensions,
      COMPACT_GRID_GAP, COMPACT_GRID_MARGIN,
    );
  } else {
    const dagreGraph = new dagre.graphlib.Graph();
    dagreGraph.setDefaultEdgeLabel(() => ({}));
    dagreGraph.setGraph({
      rankdir: direction,
      nodesep: DEFAULT_NODESEP,
      ranksep: DEFAULT_RANKSEP,
      marginx: DEFAULT_MARGIN,
      marginy: DEFAULT_MARGIN,
    });

    mainNodes.forEach((node) => {
      const dim = nodeDimensions.get(node.id)!;
      dagreGraph.setNode(node.id, { width: dim.width, height: dim.height });
    });
    mainEdges.forEach((edge) => {
      dagreGraph.setEdge(edge.source, edge.target);
    });
    dagre.layout(dagreGraph);

    const rawMain = mainNodes.map((node, index) => {
      const pos = dagreGraph.node(node.id);
      const dim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      const xOffset = direction === 'TB' ? (index % 2 === 0 ? -60 : 60) : 0;
      return {
        ...node,
        position: {
          x: pos.x - dim.width / 2 + xOffset,
          y: pos.y - dim.height / 2,
        },
      };
    });

    layoutedMain = resolveOverlaps(rawMain, nodeDimensions, direction, DEFAULT_PADDING);
  }

  // ── Place orphan nodes in a column to the right of the main flow ─
  let layoutedOrphans: FlowNode[] = [];
  if (orphanNodes.length > 0) {
    // Find the right edge of the main layout
    let maxRight = 0;
    for (const n of layoutedMain) {
      const dim = nodeDimensions.get(n.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      maxRight = Math.max(maxRight, n.position.x + dim.width);
    }

    const orphanX = maxRight + 120; // gap between main flow and orphans
    let orphanY = DEFAULT_MARGIN;

    layoutedOrphans = orphanNodes.map((node) => {
      const dim = nodeDimensions.get(node.id) || { width: DEFAULT_NODE_WIDTH, height: DEFAULT_NODE_HEIGHT };
      const positioned = { ...node, position: { x: orphanX, y: orphanY } };
      orphanY += dim.height + COMPACT_GRID_GAP;
      return positioned;
    });
  }

  return {
    nodes: [...layoutedMain, ...layoutedOrphans],
    edges,
  };
}

