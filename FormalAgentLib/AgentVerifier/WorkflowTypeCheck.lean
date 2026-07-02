import Lean
import Mathlib
import AgentVerifier.BaseTypes
import AgentVerifier.YamlStepType
import AgentVerifier.WorkflowGraphBaiscs
import AgentVerifier.WorkflowGraphUtilies

namespace AgenticKernel

/-
========================================================================
9. TYPE CHECKING — CONTEXT THREADING
========================================================================

Type checking threads a TyCtx through the workflow graph.
Each node consumes variables from the context (reads) and
may extend it with new variables (writes).
-/

/-- Compute the context after executing a node -/
def WorkflowNode.applyToContext
  (node : WorkflowNode) (context: TypedContext) : TypedContext := context.extend node.writes

/-- The initial context comes from workflow parameters -/
def WorkflowGraph.initialContext (graph : WorkflowGraph) : TypedContext :=
  graph.parameters

/-- Check that all variables a node reads are available with compatible types -/
def WorkflowNode.readResolved
  (node : WorkflowNode) (context : TypedContext) : Bool :=
  node.reads.all (fun readVar =>
    match context.lookup readVar.name with
    | some actualType => actualType.compatible readVar.type
    | none => false
  )

/-- Type-check result: either success with updated context, or error -/
inductive TypeCheckResult where
  | ok : TypedContext -> TypeCheckResult
  | error : String -> TypeCheckResult
  deriving Repr

/-- Type-check a single node against a context. Checks both writesConsistent (step-type rules) and readsResolved (variable availability). -/
def WorkflowNode.typeCheck
  (node: WorkflowNode) (context : TypedContext) : TypeCheckResult :=
  -- 1. Check writes are consistent with step type
  if !node.writesConsistent then
    .error s!"Node {node.id} ({repr node.name}): writes inconsistent with step type {repr node.stepType}"
  else
      -- 2. Check all reads are resolved with compatible types
      let unresolvedReads := node.reads.filter (fun readVar =>
        match context.lookup readVar.name with
        | some actualType => !actualType.compatible readVar.type
        | none => true
      )
      if !unresolvedReads.isEmpty then
        let varNames := unresolvedReads.map (fun v => v.name)
        .error s!"Node {node.id} ({repr node.name}): unresolved or type-incompatible reads: {varNames}"
      else
        -- 3. If both checks pass, return updated context with writes
        .ok (node.applyToContext context)

/-- Type-check a linear sequence of nodes, threading the context through -/
def typeCheckSequence
  (nodes : List WorkflowNode) (context : TypedContext) : TypeCheckResult :=
  nodes.foldl (
    fun result node =>
      match result with
      | .error message => .error message -- propagate existing error
      | .ok currentContext => node.typeCheck currentContext
  ) (.ok context)

end AgenticKernel
