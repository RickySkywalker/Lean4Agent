import Lean
import Mathlib
import AgentVerifier.BaseTypes
import AgentVerifier.YamlStepType
import AgentVerifier.WorkflowGraphBaiscs
import AgentVerifier.WorkflowGraphUtilies
import AgentVerifier.WorkflowTypeCheck

namespace AgenticKernel

/-
========================================================================
11. WORKFLOW-LEVEL STRUCTURAL PROPERTIES
========================================================================

These are propositions about the workflow graph that can be stated as
Lean theorems. They represent the structural guarantees the AST layer
provides BEFORE the semantic layer adds pre/postconditions.
-/

/-- Property: all node ids are unique -/
def WorkflowGraph.uniqueIds (graph : WorkflowGraph) : Prop :=
  ∀ (i j : Nat) (ni nj : WorkflowNode),
    graph.nodes[i]? = some ni ->
    graph.nodes[j]? = some nj ->
    ni.id = nj.id -> i = j

/-- Property: all edges reference valid node ids -/
def WorkflowGraph.edgesValid (graph : WorkflowGraph) : Bool :=
  let ids := graph.nodes.map (fun node => node.id.val)
  graph.edges.all (fun edge =>
    match edge with
    | .seqEdge fromNode toNode => fromNode.val ∈ ids && toNode.val ∈ ids
    | .branchEdge cond thenEntry elseEntry =>
      cond.val ∈ ids && thenEntry.val ∈ ids && elseEntry.val ∈ ids
    | .loopEdge header bodyEntry exit =>
      header.val ∈ ids && bodyEntry.val ∈ ids && exit.val ∈ ids
    | .loopBackEdge bodyEnd header =>
      bodyEnd.val ∈ ids && header.val ∈ ids
    | .forkEdge forkNode branches =>
      forkNode.val ∈ ids && branches.all (fun b => b.val ∈ ids)
    | .joinEdge branches joinNode =>
      branches.all (fun b => b.val ∈ ids) && joinNode.val ∈ ids
    | .switchEdge switchNode cases defaultCase =>
      switchNode.val ∈ ids && cases.all (fun c => c.val ∈ ids) &&
      match defaultCase with
      | some defautCaseId => defautCaseId.val ∈ ids
      | none => true
  )

/-- Property: entry node exists in the graph -/
def WorkflowGraph.entryNodeValid (graph : WorkflowGraph) : Bool :=
  graph.nodes.any (fun node => node.id == graph.entry)


/-- Property: all exit nodes exits in the graph -/
def WorkflowGraph.exitNodesValid (graph : WorkflowGraph) : Bool :=
  let ids := graph.nodes.map (fun node => node.id.val)
  graph.exits.all (fun exitId => exitId.val ∈ ids)

/-- Property: all nodes satisfy step-type-specific write rules -/
def WorkflowGraph.allWritesConsistent (graph : WorkflowGraph) : Bool :=
  graph.nodes.all (fun n => n.writesConsistent)


/-- Check if a node is strictly inside a parallel branch body.
    A node is inside a parallel branch if:
    1. It's reachable from a branch entry of some forkEdge (not the fork itself)
    2. It can reach the joinNode of some joinEdge (not the join itself)
    Such nodes' writes are parallel-scoped: not visible outside the block. -/
def WorkflowGraph.isParallelScopedNode (graph : WorkflowGraph) (nodeId : NodeId) : Bool :=
  graph.edges.any fun edge =>
    match edge with
    | .forkEdge forkNode branches =>
      nodeId != forkNode &&
      branches.any (fun b => b == nodeId || graph.reachable b nodeId) &&
      -- Must also be upstream of a join (still inside the block)
      graph.edges.any fun joinE =>
        match joinE with
        | .joinEdge _ joinNode =>
          nodeId != joinNode && graph.reachable nodeId joinNode
        | _ => false
    | _ => false

/-- Property: all reads are resolvable — every variable a node reads is
    either provided by the initial parameters or written by some
    transitive predecessor (any node that can reach this node via edges).

    Parallel scoping: writes from nodes inside parallel branches
    (between forkEdge and joinEdge) are NOT visible to nodes outside
    those branches. This models the execution semantics where parallel
    sub-task variables are scoped to the parallel block.

    CHANGE LOG: Previously used `findPredecessors` (direct predecessors only),
    which broke for branching control flow where a variable is written
    several hops back. Now uses `reachable` for transitive predecessor check.
    Added parallel scoping check to prevent parallel-internal writes from
    leaking to the outer scope. -/
def WorkflowGraph.allReadResolvable (graph : WorkflowGraph) : Bool :=
  graph.nodes.all (
    fun node =>
      node.reads.all (fun readVar =>
        -- Provided by initial parameters
        graph.parameters.any (fun param =>
          param.name == readVar.name && param.type.compatible readVar.type
        ) ||
        -- Provided by some transitive predecessor's writes
        graph.nodes.any (fun otherNode =>
          otherNode.id != node.id &&
          graph.reachable otherNode.id node.id &&
          -- Parallel scoping: if the writer is inside a parallel branch,
          -- its writes are only visible to other nodes in the same branch,
          -- not to nodes outside the parallel block.
          (!graph.isParallelScopedNode otherNode.id ||
           graph.isParallelScopedNode node.id) &&
          otherNode.writes.any (
            fun writeVar =>
              writeVar.name == readVar.name && writeVar.type.compatible readVar.type
          )
        )
      )
  )

/-- Property: all exits are reachable from entry -/
def WorkflowGraph.allExitsReachable (graph : WorkflowGraph) : Bool :=
  graph.exits.all (fun exitId => graph.reachable graph.entry exitId)

/-- Property: no orphan nodes (every node is reachable from entry) -/
def WorkflowGraph.noOrphanNodes (graph : WorkflowGraph) : Bool :=
  graph.nodes.all (fun node => graph.reachable graph.entry node.id)

end AgenticKernel
