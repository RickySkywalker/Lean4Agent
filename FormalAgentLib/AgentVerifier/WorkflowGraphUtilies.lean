import Lean
import Mathlib
import AgentVerifier.BaseTypes
import AgentVerifier.YamlStepType
import AgentVerifier.WorkflowGraphBaiscs

namespace AgenticKernel


/-
========================================================================
8. GRAPH QUERY UTILITIES
========================================================================
-/

/-- Find a node by id -/
def WorkflowGraph.findNode
  (graph : WorkflowGraph) (nodeId : NodeId) : Option WorkflowNode :=
  graph.nodes.find? (fun n => n.id == nodeId)

/-- Get predecessor node ids -/
def WorkflowGraph.findPredecessors
  (graph : WorkflowGraph) (nodeId: NodeId) : List NodeId
:=
  graph.edges.foldl (
    fun acc edge =>
      match edge with
      | .seqEdge fromNode toNode
        => if toNode == nodeId then fromNode :: acc else acc
      | .branchEdge cond thenEntry elseEntry
        => if thenEntry == nodeId || elseEntry == nodeId then cond :: acc else acc
      | .loopEdge header bodyEntry exit
        => if bodyEntry == nodeId then header :: acc
        else if exit == nodeId then header :: acc else acc
      | .loopBackEdge bodyEnd header
        => if header == nodeId then bodyEnd :: acc else acc
      | .forkEdge forkNode branches
        => if branches.any (fun b => b == nodeId) then forkNode :: acc else acc
      | .joinEdge branches joinNode
        => if joinNode == nodeId then branches ++ acc else acc
      | .switchEdge switchNode cases defaultCase
        => if cases.any (fun c => c == nodeId) then switchNode :: acc
          else match defaultCase with
            | some defaultCaseId => if defaultCaseId == nodeId then switchNode :: acc else acc
            | none => acc
  ) []

/-- Get successor node ids -/
def WorkflowGraph.findSuccessors
  (graph : WorkflowGraph) (nodeId : NodeId) : List NodeId
:=
  graph.edges.foldl (fun acc edge =>
    match edge with
      | .seqEdge fromNode toNode =>
        if fromNode == nodeId then toNode :: acc else acc
      | .branchEdge condition thenEntry elseEntry =>
        if condition == nodeId then thenEntry :: elseEntry :: acc else acc
      | .loopEdge header bodyEntry exit =>
        if header == nodeId then bodyEntry :: exit :: acc else acc
      | .loopBackEdge bodyEnd header =>
        if bodyEnd == nodeId then header :: acc else acc
      | .forkEdge forkNode branches =>
        if forkNode == nodeId then branches ++ acc else acc
      | .joinEdge branches joinNode =>
        if branches.any (fun b => b == nodeId) then joinNode :: acc else acc
      | .switchEdge switchNode cases defaultCase =>
        if switchNode == nodeId then
          match defaultCase with
          | some defaultCaseId => cases ++ [defaultCaseId] ++ acc
          | none => cases ++ acc
        else acc
  ) []

/-- Check if two nodes are directly adjacent -/
def WorkflowGraph.adjecent
  (graph : WorkflowGraph) (fromId : NodeId) (toId : NodeId) : Bool :=
  (graph.findSuccessors fromId).any (fun succId => succId == toId)

/-- Check reachability using BFS with a visited set and fuel.
    This correctly handles cycles (including nested loops with loopBackEdges)
    by never revisiting a node.  Fuel is set to nodes.length + edges.length + 1,
    which is sufficient because each node is expanded at most once (tracked by
    visited), and each edge contributes at most one duplicate queue entry
    that is skipped immediately. -/
def WorkflowGraph.reachable
  (graph : WorkflowGraph) (fromId toId : NodeId) : Bool :=
  let fuel := graph.nodes.length + graph.edges.length + 1
  let rec bfs
    (queue : List NodeId)
    (visited : List NodeId)
    (fuel : Nat) : Bool :=
    match fuel with
    | 0 => false  -- fuel exhausted, unreachable within finite graph
    | fuel + 1 =>
      match queue with
      | [] => false
      | cur :: rest =>
        if cur == toId then true
        else if visited.contains cur then
          bfs rest visited fuel
        else
          let succs := graph.findSuccessors cur
          bfs (rest ++ succs) (cur :: visited) fuel
  bfs [fromId] [] fuel


/-
========================================================================
10. EXECUTION MODE QUERIES
========================================================================

Given a workflow graph, determine which nodes need semantic specs
(pre/postconditions from the LLM) and which are fully verified
at the structural layer.
-/

/-- Get all nodes that require semantic specs from the LLM-/
def WorkflowGraph.nodesNeedingSpecs
  (graph : WorkflowGraph) : List WorkflowNode :=
  graph.nodes.filter (fun n => n.needSemanticSpec)

/-- Get all nodes that are fully verified at the structural layer-/
def WorkflowGraph.deterministicNodes
  (graph : WorkflowGraph) : List WorkflowNode :=
  graph.nodes.filter (fun n => !n.needSemanticSpec)

/-- The return type of this workflow module, inferred from the returnValue node. Used by the parent workflows to determine the output type of a `call` step.-/
def WorkflowGraph.returnType
  (graph : WorkflowGraph) : Option BaseType :=
  match graph.nodes.find? (fun n => n.stepType == .returnValue) with
  | some returnNode =>
    match returnNode.reads with
    | [node] => some node.type
    | _ => none
  | none => none

/-- Summary of how many nodes of each exec type are in the workflow graph -/
structure VerificationSummary where
  totalNodes          : Nat
  deterministicNodes  : Nat   -- fully verified at structural layer
  structuredNodes     : Nat   -- output type known, need content spec
  unstructuredNodes   : Nat   -- need full semantic spec
  compositionNodes    : Nat   -- depends on sub-module analysis
  deriving Repr

def WorkflowGraph.verificationSummary (g : WorkflowGraph) : VerificationSummary :=
  let (deterministicNum, structuredNum, unstructuredNum, compositionNum) :=
  g.nodes.foldl (fun (deterministicNum, structuredNum, unstructuredNum, compositionNum) n =>
    match n.execType with
    | .deterministic  => (deterministicNum + 1, structuredNum, unstructuredNum, compositionNum)
    | .structured     => (deterministicNum, structuredNum + 1, unstructuredNum, compositionNum)
    | .unstructured   => (deterministicNum, structuredNum, unstructuredNum + 1, compositionNum)
    | .composition    => (deterministicNum, structuredNum, unstructuredNum, compositionNum + 1)
  ) (0, 0, 0, 0)
  { totalNodes := g.nodes.length
    deterministicNodes := deterministicNum
    structuredNodes := structuredNum
    unstructuredNodes := unstructuredNum
    compositionNodes := compositionNum }

end AgenticKernel
