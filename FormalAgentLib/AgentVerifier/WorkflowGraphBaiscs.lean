import Lean
import Mathlib
import AgentVerifier.BaseTypes
import AgentVerifier.YamlStepType


namespace AgenticKernel


/-
========================================================================
5. WORKFLOW NODE
========================================================================

A WorkflowNode represents one step in the workflow.

Key fields:
  - tag: which of the 16 step types this is
  - reads: variables consumed (from {{...}} template references)
  - writes: variables produced (from save_as or step-type-specific rules)

The reads/writes use TypedVar, binding each variable to a BaseType.
This is where the type system connects to the AST.
-/


/-- A reference to the node by its ID, not purely Nat to avoid mixing with natural number-/
structure NodeId where
  val: Nat
  deriving Repr, BEq, Hashable, Inhabited, DecidableEq

instance : ToString NodeId where
  toString n := toString n.val

structure WorkflowNode where
  /-- Unique numeric identifier -/
  id      : NodeId
  /-- Optional human-readable name -/
  name    : Option String
  /-- Which of the 16 YAML step types -/
  stepType     : StepType
  /-- Variables read from context, with expected types -/
  reads   : List TypedVar
  /-- Variables written to context, with their types -/
  writes  : List TypedVar
  /-- The instruction/promot string for LLM steps, for op without LLM, this is None. The {{var}} references inside are extracted into `reads`.-/
  llmInstruction : Option String
  deriving Repr, BEq, Inhabited

/-- Get the execution mode of a node -/
def WorkflowNode.execType (node : WorkflowNode) : ExecType :=
  node.stepType.execType

/--
Check that a node's writes are consistent with its stepType's expected output type based on the following rules:
1. If the stepType has no default type, the node should have no writes to the context, expect for setVariable, which will update the system but currently we don't know which to update
2. If a stepType has a defult output type, the node should write at most one variable with a compatible type
3. Increment must read AND write the same TInt variable
4. forEachLoop must read a TList (or TString/TJson as serialized list) and write the loop variable with element type
5. returnVlaue must read exactly one variable, which is the returned value
-/
def WorkflowNode.writesConsistent (n : WorkflowNode) : Bool :=
  let instructionTrue := match n.execType with
    | .deterministic => true -- instruction is optional for determinstic steps, since we don't call LLMs anyway
    | .structured | .unstructured => n.llmInstruction.isSome -- instruction is required for LLM steps, since that's the only way to tell the LLM what to do and what variables to read
    | .composition => true -- call/gather use module path, not instruction

  let writesTrue := match n.stepType with
    -- Pure steps with fully determinstic rules

    -- forEachLoop: reads one list-like var, writes one loop var with element type
    -- The input can be:
    --   (a) TList elemType → loop var type must be compatible with elemType
    --   (b) TString / TJson → runtime parses it as a list, loop var type is TUnknown
    -- Case (b) arises when a regular `step` produces JSON text that
    -- for_each consumes as a list — the YAML doesn't distinguish these.
    -- Example: reads [("paper_list", TList TJson)], writes [("paper", TJson)]
    -- Example: reads [("json_output", TString)],    writes [("item", TUnknown)]
    | .forEachLoop =>
      match n.reads, n.writes with
      | [listVar], [loopVar] =>
        match listVar.type with
        | .TList elemType => elemType.compatible loopVar.type
        | .TString => loopVar.type.compatible .TUnknown  -- serialized JSON list
        | .TJson   => loopVar.type.compatible .TUnknown  -- JSON array
        | _ => false
      | _, _ => false
    -- Deterinistic steps

    -- whileLoop: reads the non-empty condition variables, writes nothing
    -- The condition variable are used to evaluate the loop condition.
    -- Example: reads [("current_depth", TInt), ("max_depth", TInt)]
    | .whileLoop => n.reads.length >= 1 && n.writes.isEmpty
    --conditional: reads condition var (at least one), writes nothing
    | .conditional => n.reads.length >= 1 && n.writes.isEmpty
    -- switchBranch: reads the switch variable, writes nothing
    | .switchBranch => n.reads.length == 1 && n.writes.isEmpty

    -- setVariable: must write exactly one veriable (type determined by value
    | .setVariable => n.writes.length == 1

    -- incrementVariable: reads and writes the same variable, must be TInt
    -- Example: reads [("counter", TInt)], writes [("counter", TInt)]
    | .incrementVariable =>
      match n.reads, n.writes with
      | [r], [w] => r.name == w.name && r.type == .TInt && w.type == .TInt
      | _, _ => false

    -- returnValue: reads exactly one variable and return to the parent, writes nothing to the current module's context
    | .returnValue => n.reads.length == 1 && n.writes.isEmpty

    -- input: writes exactly one variable of type TString (the user's response)
    -- Example: writes [("user_answer", TString)]
    | .input =>
      match n.writes with
      | [w] => w.type.compatible .TString
      | _ => false

    -- Unstructured LLM steps where output type defaults to TString or TUnknown
    -- step: the STATEFUL agent action with persistent conversation history (new-engine semantics); the history is modelled at runtime, not in this AST layer. Writes at most one variable, compatible with TString.
    -- Example: writes [("paper_list", TString)] or writes []
    | .step =>
      match n.writes with
      | [] => true
      | [w] => w.type.compatible .TString
      | _ => false
    -- task: same write rules as step, but the STATELESS, fresh-call variant without conversation history (new-engine semantics).
    -- Example: writes [("conversation_result", TString)] or writes []
    | .task =>
      match n.writes with
      | [] => true
      | [w] => w.type.compatible .TString
      | _ => false
    -- parallel: writes at most one variable. The type should be TList (list of sub-module results).
    -- Example: writes [("all_search_results", TList TUnknown)]
    | .parallel =>
      match n.writes with
      | [] => true
      | [w] =>
        match w.type with
        | .TList _ => true
        | .TUnknown => true  -- may not know element type yet
        | _ => false
      | _ => false

    -- Composition steps (output depends on sub-module)
    -- call: writes at most one variable (save_as). Type is TUnknown until resolved by inter-module analysis.
    -- Example: writes [("analysis_result", TUnknown)]
    | .call =>
      match n.writes with
      | [] => true
      | [_] => true  -- any type is acceptable; inter-module analysis refines it
      | _ => false
    -- gather: writes at most one variable. Type should be TList (heterogeneous results from different sub-modules).
    -- Example: writes [("all_results", TList TUnknown)]
    | .gather =>
      match n.writes with
      | [] => true
      | [w] =>
        match w.type with
        | .TList _ => true
        | .TUnknown => true
        | _ => false
      | _ => false
    -- deprecated/unused (retained-constructor) arm; the new engine never produces these step types
    | .save | .discover | .evaluate | .validate | .synthesize => true
   instructionTrue && writesTrue

/-
========================================================================
6. CONTROL FLOW EDGES
========================================================================

WfEdge defines how control flows between nodes. Each edge type
corresponds to a control flow pattern created by the step types:

  seq      ← most steps (step, task, setVariable, etc.)
  branch   ← conditional (if-then-else)
  loop     ← whileLoop, forEachLoop
  loopBack ← whileLoop, forEachLoop (back to header)
  fork     ← parallel
  join     ← parallel (after all branches complete)
  switchE  ← switchBranch
-/


inductive WorkflowEdge where
  | seqEdge : (fromNode : NodeId) -> (toNode : NodeId) -> WorkflowEdge -- sequential execution from -> to
  | branchEdge : (cond : NodeId) -> (thenEntry : NodeId) -> (elseEntry : NodeId) -> WorkflowEdge -- conditional
  | loopEdge : (header : NodeId) -> (bodyEntry : NodeId) -> (exit : NodeId) -> WorkflowEdge -- loop edge
  | loopBackEdge : (bodyEnd : NodeId) -> (header : NodeId) -> WorkflowEdge -- when the loop body ends, back to the header to check the loop condition again
  | forkEdge : (forkNode : NodeId) -> (branches : List NodeId) -> WorkflowEdge -- parallel fork: fork node → parallel branch entries
  | joinEdge : (branches : List NodeId) -> (joinNode : NodeId) -> WorkflowEdge -- Parallel join: parallel branch exits → join node
  | switchEdge : (switchNode : NodeId) -> (cases : List NodeId) -> (defaultCase : Option NodeId) -> WorkflowEdge -- Switch: switch node → case entries + optional default
  deriving Repr, BEq, Inhabited

/-- Check if an edge is a back edge (forms a loop) -/
def WorkflowEdge.isBackEdge : WorkflowEdge → Bool
  | .loopBackEdge _ _ => true
  | _ => false

/-
========================================================================
7. WORKFLOW GRAPH
========================================================================
-/

structure WorkflowGraph where
  nodes : List WorkflowNode       -- All nodes in the workflow
  edges : List WorkflowEdge       -- All control flow edges
  entry : NodeId                  -- Entry node id (where execution starts)
  exits : List NodeId             -- Exit node ids (may be multiple due to branches)
  parameters : List TypedVar      -- Initial parameters from YAML "parameters" section

/-
========================================================================
10. EXECUTION MODE QUERIES
========================================================================

Given a workflow graph, determine which nodes need semantic specs
(pre/postconditions from the LLM) and which are fully verified
at the structural layer.
-/

/-- A node's output type is structurally determined if it is deterministic or with structured output
For unstructured and composition nodes, the content is unknown at the structure layer-/
def WorkflowNode.outputTypeDetermined (n : WorkflowNode) : Bool :=
  match n.execType with
  | .deterministic | .structured => true
  | .unstructured | .composition => false

/-- A node needs a semantic spec (pre/postconditions from the LLM) if its output involves LLM inference. Deterministic steps don't need specs because their behavior is fully determined by the YAML semantics.-/
def WorkflowNode.needSemanticSpec (n : WorkflowNode) : Bool :=
  match n.execType with
  | .deterministic => false
  | .structured | .unstructured | .composition => true


end AgenticKernel
