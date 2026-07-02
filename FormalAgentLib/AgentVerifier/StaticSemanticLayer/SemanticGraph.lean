import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.StaticSemanticVariable

namespace AgenticKernel

/-
╔══════════════════════════════════════════════════════════════════════════╗
║  LAYER 2 — PART 0: SHARED SEMANTIC IDENTITY & INFORMATION TYPES           ║
║                                                                          ║
║  (Solution 2) A semantic node now carries THREE separate record groups:  ║
║    (1) variable-level predicates   — precond/postcondVariables           ║
║    (2) information-flow            — requires + produced var/context info ║
║    (3) graph-level predicates      — the sub-goals it contributes/verifies║
║                                                                          ║
║  The identity/atom types those groups need (`SubGoalName`, the           ║
║  information predicates, and the workflow's `GoalSpecification`) live     ║
║  HERE, at the base, so the node and the whole-graph `goalSpec` field can  ║
║  carry typed data WITHOUT a circular import — the WQA submodules          ║
║  (`InformationSystem`, `GraphLevelPredicates`) import this file and build ║
║  their verification logic on top of these primitives.                    ║
╚══════════════════════════════════════════════════════════════════════════╝
-/

/-- A sub-goal's typed identity (FIX #3). One-field wrapper over `String`: a
    plan declares its sub-goal names once as `SubGoalName` constants and
    references them in both the node graph-fields and the `GoalSpecification`,
    so a typo is a compile error, not a silent miss. -/
structure SubGoalName where
  val : String
deriving Repr, BEq, DecidableEq, Inhabited, Hashable

/-- A single named unit of information that flows through a workflow
    (e.g. `info "root_cause"`). The atom of the information-flow system. -/
structure InformationPredicate where
  name : String
deriving Repr, BEq, DecidableEq, Inhabited, Hashable

/-- Convenience constructor: `info "relevant_files"`. -/
def info (name : String) : InformationPredicate := ⟨name⟩

/-- Human-readable description of an information atom. -/
def InformationPredicate.describe (i : InformationPredicate) : String := i.name

/-- Membership of an atom in a list, by name. -/
def InformationPredicate.elem (i : InformationPredicate) (is : List InformationPredicate) : Bool :=
  is.any (· == i)

/-- "Variable `varName` bears the information `carries`." Readable by a node
    only when the node actually reads `varName`. -/
structure VariableInformationPredicate where
  varName : String
  carries : List InformationPredicate
deriving Repr, BEq, Inhabited

/-- Does this variable bear the given information atom? -/
def VariableInformationPredicate.bears (vi : VariableInformationPredicate) (i : InformationPredicate) : Bool :=
  vi.carries.any (· == i)

/-- Convenience constructor: `varInfo "codebase_analysis" ["relevant_files", …]`. -/
def varInfo (varName : String) (atoms : List String) : VariableInformationPredicate :=
  ⟨varName, atoms.map info⟩

/-- A single sub-goal of the workflow's acceptance specification. `name` is the
    typed identity; `variableName` is the dataflow variable that must carry
    `requiredPredicate` at the workflow exit; `requiredGraphPredicates` selects
    which graph-level structural checks this sub-goal demands. -/
structure SubGoalSpec where
  name : SubGoalName
  variableName : String
  requiredPredicate : PredicateType
  description : String := ""
  requiredGraphPredicates : List PredicateKey := []
deriving Repr, BEq, Inhabited

/-- The workflow's full goal specification — the acceptance contract, provided
    when the `SemanticWorkflowGraph` is constructed (Solution 2 §2.3.1). -/
structure GoalSpecification where
  originalGoal : String
  subGoals : List SubGoalSpec := []
deriving Repr, Inhabited

/-
╔══════════════════════════════════════════════════════════════════════════╗
║  LAYER 2 — PART 4: SEMANTIC NODE SPECIFICATION                           ║
║                                                                          ║
║  Each workflow node that involves LLM inference receives a               ║
║  `SemanticNodeSpec`: a precondition and postcondition expressed as       ║
║  Lean `Prop`s over `SemanticEnv`.                                        ║
║                                                                          ║
║  Design (inspired by VERINA):                                            ║
║    VERINA:  precond(x) → postcond(f(x))   with f = code impl             ║
║    Ours:    precond(env) → postcond(env, env')  with env' = LLM result   ║
║                                                                          ║
║  Since LLM behavior is unknown, we axiomatize:                           ║
║    "If precond holds, there exists an env' s.t. postcond holds"          ║
║  This is the `sorry` in VERINA's theorem statements.                     ║
║                                                                          ║
║  What we CAN prove in Lean:                                              ║
║    Chain soundness — the postcondition of node i, together with the      ║
║    accumulated environment, implies the precondition of node i+1.        ║
╚══════════════════════════════════════════════════════════════════════════╝
-/

/-
========================================================================
PART 4A: SEMANTIC NODE SPECIFICATION
========================================================================
-/

/-- Semantic specification for a single workflow node.

    For LLM nodes: preconditions and postconditions come from NL parsing
    (the "semantic meaning" extracted from the YAML prompt).

    For deterministic nodes: preconditions are trivially `True` and
    postconditions describe the concrete variable update. -/
structure SemanticWorkflowNode where
  /-- The Layer 1 node this spec annotates -/
  baseNode : WorkflowNode
  -- ── Record group (1): variable-level predicates (the traditional Hoare chain) ──
  /-- Decidable precondition requirements -/
  precondVariables : List VariablePredicateRequirement := []
  /-- Decidable postcondition facts established -/
  postcondVariables : List VariablePredicateRequirement := []
  -- ── Record group (2): information flow (dynamic-context system, Solution 2) ──
  /-- Information this node must be able to READ to execute correctly. -/
  infoRequires : List InformationPredicate := []
  /-- Variable-borne information this node WRITES (one entry per written variable). -/
  producesVariableInfo : List VariableInformationPredicate := []
  /-- Context-borne information this node contributes to its conversation context. -/
  producesContextInfo : List InformationPredicate := []
  -- ── Record group (3): graph-level predicates this node satisfies (Solution 2) ──
  --    (formerly smuggled into `postcondVariables` as `markSubGoal*` sentinels).
  /-- Sub-goals this node establishes/advances (the "producer" role). -/
  graphContributions : List SubGoalName := []
  /-- Sub-goals this node independently reads & checks (the "verifier" role). -/
  graphVerifications : List SubGoalName := []
  /-- Sub-goals for which this node provides implicit (task-context) retry. -/
  graphImplicitRetries : List SubGoalName := []
  /-- Prop precondition (auto-derived) -/
  precond : SemanticEnv → Prop :=
    fun env => ∀ predVar ∈ precondVariables, predVar.toProp env
  /-- Postcondition: After the execution of this node, what should be true in the environment inferred from the LLM prompt or python code.-/
  postcond : SemanticEnv → SemanticEnv → Prop :=
    fun _ env' => ∀ predVar ∈ postcondVariables, predVar.toProp env'


/--
Loop termination specification

Every loop must specify how it terminates. This enables:
    1. Static verification that termination is explicitly considered
    2. Documentation of termination mechanism for code review
    3. Different verification strategies based on termination type
-/
inductive LoopTerminationSpec where
  /-- Loop is finite and will terminate due to the variable change -/
  | finiteCondition (terminationVars : List String)
  /-- Loop terminates when LLM outputs specific a sentienl string. -/
  | llmControlledExit (potentialExitNodeId : NodeId) (sentinelPattern : String)
  /-- Loop is terminated by external system (like timeout, max iterations ...) -/
  | externalTermination (mechanism : String)
  /-- Explicitly mark as intentionally unbounded (requires justification) -/
  | allowUnbounded (justification : String)
  deriving Repr, BEq, DecidableEq, Inhabited

/-- Check if a termination spec if well-formed-/
def LoopTerminationSpec.isValid : LoopTerminationSpec → Bool
  | .finiteCondition vars => !vars.isEmpty
  | .llmControlledExit _ pattern => !pattern.isEmpty
  | .externalTermination mechanism => !mechanism.isEmpty
  | .allowUnbounded justification => !justification.isEmpty

/-- Describe the termination spec for error messages -/
def LoopTerminationSpec.describe : LoopTerminationSpec → String
  | .finiteCondition vars => s!"finiteCondition({vars})"
  | .llmControlledExit nodeId pattern => s!"sentinelExit(node {nodeId.val}, \"{pattern}\")"
  | .externalTermination mechanism => s!"externalTermination(\"{mechanism}\")"
  | .allowUnbounded justification => s!"allowUnbounded(\"{justification}\")"

/--
  Loop Semantic node (extends SemanticWorkflowNode)

  It is used for whileLoop
    Loop verification requires:
    1. Entry facts must establish loopInvariant
    2. loopInvariant must satisfy precondReqs
    3. After loop body, facts must preserve loopInvariant
    4. Loop MUST have a valid termination specification

  Exit semantics (following Hoare logic):
    When loop exits: exitFacts = loopInvariant ∧ exitPostconditions
    - For finiteCondition: exitPostconditions typically includes ¬(loop condition)
    - For sentinelExit: exitPostconditions includes facts about sentinel being output
    - For externalTermination: exitPostconditions may include timeout/iteration count
-/
structure SemanticLoopNode extends SemanticWorkflowNode where
  /-- The loop invariant holds at the start of each iteration -/
  loopInvariant : List VariablePredicateRequirement
  /-- The SemanticEnv format for loop invariants -/
  invariantEnv : SemanticEnv → Prop :=
    fun env => ∀ predVar ∈ loopInvariant, predVar.toProp env
  /-- REQUIRED: How does this loop terminate? -/
  terminationSpec : LoopTerminationSpec
  /-- Exit postconditions: what additional facts hold when the loop exits.
      Exit facts = loopInvariant ++ exitPostconditions (following Hoare logic rule) -/
  exitPostconditions : List VariablePredicateRequirement := []
  /-- Variable used in termination condition (derived from terminationSpec for finite loops) -/
  terminationVars : List String := match terminationSpec with
    | .finiteCondition vars => vars
    | _ => []
  /-- If true, the loop body is guaranteed to execute at least once (e.g., the
      loop condition is provably true on first entry). When set, the verification
      engine propagates exitPostconditions to the loop header's output so that
      variables written inside the loop body are available after the loop exits.
      This models the common pattern where a counter starts at 0 with max > 0. -/
  executesAtLeastOnce : Bool := false

/-- Compute the exit facts for a loop: invariant ∧ exitCondition -/
def SemanticLoopNode.computeExitFacts (node : SemanticLoopNode) : List VariablePredicateRequirement :=
  -- Combine loop invariant with exit postconditions
  -- The invariant is preserved, plus exit-specific facts become true
  let combined := node.loopInvariant ++ node.exitPostconditions
  -- Remove duplicates by variable name (keep the stronger predicate from exitPostconditions)
  let varNames := combined.map (·.varName) |>.eraseDups
  varNames.filterMap fun varName =>
    -- Prefer exitPostconditions over invariant for same variable
    match node.exitPostconditions.find? (·.varName == varName) with
    | some p => some p
    | none => node.loopInvariant.find? (·.varName == varName)

/-- Force type change when we want to use some function in base type -/
instance : Coe SemanticLoopNode SemanticWorkflowNode where
  coe loopNode := loopNode.toSemanticWorkflowNode

/--
  ForEach loop semantic node (extends SemanticWorkflowNode)
    Used for: forEachLoop

  Similar to SemanticLoopNode but also tracks:
    - The list being iterated
    - The iterator variable
-/
structure SemanticForEachLoopNode extends SemanticLoopNode where
  /-- The iteration Variable (for documentation only) -/
  iterationVar : String

instance : Coe SemanticForEachLoopNode SemanticLoopNode where
  coe := SemanticForEachLoopNode.toSemanticLoopNode


/--
  Conditional node semantic specification (for if-else branches)

  This extends SemanticWorkflowNode to support branch-aware postconditions:
  - `thenPostcond`: facts that hold when the condition is TRUE (then branch taken)
  - `elsePostcond`: facts that hold when the condition is FALSE (else branch taken)

  Example: For "check_abstract == None":
  - thenPostcond: abstract is None (weak predicate)
  - elsePostcond: abstract is non-empty (strong predicate, since we know it's not None)

  The verification system will propagate the appropriate postconditions
  based on which branch edge is being followed.
-/
structure SemanticConditionalNode extends SemanticWorkflowNode where
  /-- The ID of the then-branch target node -/
  thenTargetId : NodeId
  /-- The ID of the else-branch target node -/
  elseTargetId : NodeId
  /-- Postconditions when condition is TRUE (then branch) -/
  thenPostcondVariables : List VariablePredicateRequirement
  /-- Postconditions when condition is FALSE (else branch) -/
  elsePostcondVariables : List VariablePredicateRequirement

/-- Get postconditions for a specific branch target -/
def SemanticConditionalNode.getPostcondForTarget
    (condNode : SemanticConditionalNode)
    (targetId : NodeId) : List VariablePredicateRequirement :=
  if targetId == condNode.thenTargetId then
    condNode.thenPostcondVariables
  else if targetId == condNode.elseTargetId then
    condNode.elsePostcondVariables
  else
    -- Fallback to base postcondVariables if target doesn't match
    condNode.postcondVariables

instance : Coe SemanticConditionalNode SemanticWorkflowNode where
  coe condNode := condNode.toSemanticWorkflowNode


/-- Get the node ID -/
def SemanticWorkflowNode.id (node : SemanticWorkflowNode) : NodeId := node.baseNode.id

/-- Get the node name -/
def SemanticWorkflowNode.name (node : SemanticWorkflowNode) : Option String := node.baseNode.name

/-- Get the step type -/
def SemanticWorkflowNode.stepType (node : SemanticWorkflowNode) : StepType := node.baseNode.stepType

/-- Get the variables reads by this node -/
def SemanticWorkflowNode.readVars (node : SemanticWorkflowNode) : List TypedVar := node.baseNode.reads

/-- Get the variables written by this node -/
def SemanticWorkflowNode.writeVars (node : SemanticWorkflowNode) : List TypedVar := node.baseNode.writes

/-- Check it this node needs semantic specification -/
def SemanticWorkflowNode.needSemanticSpec (node : SemanticWorkflowNode) : Bool := node.baseNode.needSemanticSpec

/-- Check if this node is deterministic -/
def SemanticWorkflowNode.isDeterministic (node : SemanticWorkflowNode) : Bool := node.baseNode.execType == .deterministic


/-
========================================================================
PART 4B: DETERMINISTIC NODE SEMANTICS
========================================================================

For deterministic nodes (setVariable, incrementVariable, etc.),
we can give concrete postconditions that fully describe the env update.
These don't require LLM axioms — they are provable from definitions.
-/

/-- Postcondition for `setVariable`: sets the variable based on the valueFun, leave other variables unchanged. -/
def setVariablePostcond
  (varName : String)
  (valueFun : SemanticEnv → Value)   -- The function for the new value, which can depend on the current env for flexibility.
  (env env' : SemanticEnv) : Prop :=
  env'.get varName = some (valueFun env) ∧
  ∀ otherVarName, otherVarName ≠ varName → env'.get otherVarName = env.get otherVarName

/-- Postcondition for `incrementVariable`: increase an Int variable by 1-/
def incrementVariablePostcond
  (varName : String)
  (env env' : SemanticEnv) : Prop :=
  ∃ n : Int, env.get varName = some (.vInt n) ∧
  env'.get varName = some (.vInt (n + 1)) ∧
  ∀ otherVarName, otherVarName ≠ varName → env'.get otherVarName = env.get otherVarName

/-- Postcondition for nodes that don't modify the enviroment at all-/
def noOpPostcond
  (env env' : SemanticEnv) : Prop :=
  ∀ name, env'.get name = env.get name

/-
========================================================================
PART 4C: LLM EXECUTION AXIOMATIZATION
========================================================================

Since we cannot know what the LLM actually computes, we introduce an
axiom: if the precondition is satisfied, then there EXISTS a post-
environment satisfying the postcondition.

This is exactly the `sorry` in VERINA's theorem:
  `theorem f_spec ... : postcond ... := by sorry`

The crucial difference: we don't `sorry` the chain theorems.
Chain soundness (post_i → pre_{i+1}) IS proved in Lean.
-/

/-- Axiom: The LLM perform executions just as its instruction specify given the precondition holds, this is the core assumption for static semantic reasoning. -/
axiom llmExecAxiom
  (semanticNode : SemanticWorkflowNode)
  (env : SemanticEnv)
  (precond: semanticNode.precond env) :
  ∃ env', semanticNode.postcond env env'

/-
LAYER 2: SEMANTIC WORKFLOW GRAPH

This file extends Layer 1's WorkflowGraph with semantic annotations.
Each node that requires semantic verification (as identified by
`WorkflowNode.needSemanticSpec`) receives preconditions and
postconditions expressed as Lean `Prop`s.
-/

/-
PART 2: SEMANTIC WORKFLOW GRAPH

The SemanticWorkflowGraph wraps a Layer 1 WorkflowGraph and provides semantic annotations for each node. It reuses Layer 1's edge structure and graph utilities.
-/

/-- Semantic workflow graph based on Layer 1 WorkflowGraph and provides Semantic annotations for each node. It reuses Layer 1's edge structure and graph utilities. -/
structure SemanticWorkflowGraph where
  /-- The underlying Layer 1 WorkflowGraph -/
  baseGraph : WorkflowGraph
  /-- The initial node with the parameter information. Its precondition should be empty and the postcondition should be all requirements on the parameters as well as tools. -/
  paramNode : SemanticWorkflowNode
  /-- Semantic nodes with pre/post conditions -/
  semanticNodes : List SemanticWorkflowNode
  /-- Invariant: Every node that needs semantic spec has an entry in `semanticNodes` -/
  (specInvariant : ∀ node ∈ baseGraph.nodes, node.needSemanticSpec → ∃ spec ∈ semanticNodes, spec.id = node.id)
  /-- Loop nodes that contains loop-invariants -/
  loopNodes : List SemanticLoopNode := []
  /-- Conditional nodes with branch-aware postconditions -/
  conditionalNodes : List SemanticConditionalNode := []
  /-- (Solution 2 §2.3.1) The workflow's graph-level acceptance requirements,
      provided at construction. The unified verifier checks goal coverage and
      information flow against this. Defaults to empty so graphs built before the
      requirements were embedded still elaborate. -/
  goalSpec : GoalSpecification := { originalGoal := "" }

/-- Make the parameter node -/
def makeParamNode
  (parameterPredicates : List VariablePredicateRequirement) : SemanticWorkflowNode :=
  {
    baseNode := {
      id := ⟨20041122⟩
      name := some "param_node"
      stepType := .setVariable
      reads := []
      writes := []
      llmInstruction := none
    }
    precondVariables := []
    postcondVariables := parameterPredicates
  }

/-- Get the edges of the semantic workflow graph -/
def SemanticWorkflowGraph.getEdges (graph : SemanticWorkflowGraph) : List WorkflowEdge :=
  graph.baseGraph.edges

/-- Get the entry node ID -/
def SemanticWorkflowGraph.entry (graph : SemanticWorkflowGraph) : NodeId := graph.baseGraph.entry

/-- Get the exit node IDs -/
def SemanticWorkflowGraph.exits (graph : SemanticWorkflowGraph) : List NodeId := graph.baseGraph.exits

/-- Get the initial parameters -/
def SemanticWorkflowGraph.parameters (graph : SemanticWorkflowGraph) : TypedContext := graph.baseGraph.parameters

/-- Find the semantic node by ID -/
def SemanticWorkflowGraph.findSemanticNode
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : Option SemanticWorkflowNode :=
  graph.semanticNodes.find? (fun node => node.id == nodeId)

/-- Find the loop node by ID -/
def SemanticWorkflowGraph.findLoopNode
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : Option SemanticLoopNode :=
  graph.loopNodes.find? (fun node => node.id == nodeId)

/-- Find the conditional node by ID -/
def SemanticWorkflowGraph.findConditionalNode
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : Option SemanticConditionalNode :=
  graph.conditionalNodes.find? (fun node => node.id == nodeId)

/-- Get all conditional node IDs -/
def SemanticWorkflowGraph.getConditionalNodeIds
  (graph : SemanticWorkflowGraph) : List NodeId :=
  graph.conditionalNodes.map (·.id)

/-- Find predecessor node IDs (delegated to Layer 1) for a given node -/
def SemanticWorkflowGraph.findPredecessors
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : List NodeId :=
  graph.baseGraph.findPredecessors nodeId

/-- Find successor node IDs (delegated to Layer 1) for a given node -/
def SemanticWorkflowGraph.findSuccessors
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : List NodeId :=
  graph.baseGraph.findSuccessors nodeId

/-- Get all loop header IDs from edges -/
def SemanticWorkflowGraph.getLoopHeadersFromEdges
  (graph : SemanticWorkflowGraph) : List NodeId :=
  graph.baseGraph.edges.filterMap fun edge =>
    match edge with
    | .loopBackEdge _ header => some header
    | .loopEdge header _ _ => some header
    | _ => none

/-- Find predecessors ignoring back edges (for topological sort) -/
def SemanticWorkflowGraph.findPredecessorsIgnoringBackEdge (graph : SemanticWorkflowGraph) (nodeId : NodeId)
    : List NodeId :=
  graph.baseGraph.edges.foldl (fun acc edge =>
    match edge with
    | .loopBackEdge _ _ => acc  -- Ignore back edge
    | .seqEdge fromNode toNode =>
      if toNode == nodeId then fromNode :: acc else acc
    | .branchEdge cond thenEntry elseEntry =>
      if thenEntry == nodeId || elseEntry == nodeId then cond :: acc else acc
    | .loopEdge header bodyEntry exit =>
      if bodyEntry == nodeId || exit == nodeId then header :: acc else acc
    | .forkEdge forkNode branches =>
      if branches.any (· == nodeId) then forkNode :: acc else acc
    | .joinEdge branches joinNode =>
      if joinNode == nodeId then branches ++ acc else acc
    | .switchEdge switchNode cases defaultCase =>
      if cases.any (· == nodeId) then switchNode :: acc
      else match defaultCase with
        | some d => if d == nodeId then switchNode :: acc else acc
        | none => acc
  ) []

/-- Find the body end node ID for a loop header (source of loopBackEdge) -/
def SemanticWorkflowGraph.findLoopBodyEnd (graph : SemanticWorkflowGraph) (headerId : NodeId) : Option NodeId :=
  graph.baseGraph.edges.findSome? fun edge =>
    match edge with
    | .loopBackEdge bodyEnd header => if header == headerId then some bodyEnd else none
    | _ => none

/-- Get all loop header IDs (from loopNodes) -/
def SemanticWorkflowGraph.getLoopHeaders (graph : SemanticWorkflowGraph) : List NodeId :=
  graph.loopNodes.map (·.id)

/-- Check the reachability (delegated to Layer 1) for a given pair of nodes. -/
def SemanticWorkflowGraph.reachable
  (graph : SemanticWorkflowGraph)
  (fromId toId : NodeId) : Bool :=
  graph.baseGraph.reachable fromId toId

/-- Get all predecessor semantic nodes -/
def SemanticWorkflowGraph.findPredecessorSemanticNodes
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : List SemanticWorkflowNode :=
  let predecessorIds := graph.findPredecessors nodeId
  predecessorIds.filterMap (fun predId => graph.findSemanticNode predId)

/-- Get all transitive predecessor semantic nodes (i.e., any node that can reach this node)-/
def SemanticWorkflowGraph.findTransitivePredecessorSemanticNodes
  (graph : SemanticWorkflowGraph)
  (nodeId : NodeId) : List SemanticWorkflowNode :=
  graph.semanticNodes.filter (fun n => n.id != nodeId ∧ graph.reachable n.id nodeId)

/-- Find back edge targets from a given node.
    Returns the list of loop headers that this node has back edges to. -/
def SemanticWorkflowGraph.findBackEdgeTargets (graph : SemanticWorkflowGraph) (nodeId : NodeId) : List NodeId :=
  graph.baseGraph.edges.filterMap fun e =>
    match e with
    | .loopBackEdge bodyEnd header => if bodyEnd == nodeId then some header else none
    | _ => none

/-- Find all back edges in the graph.
    Returns list of (bodyEnd, header) pairs. -/
def SemanticWorkflowGraph.findAllBackEdges (graph : SemanticWorkflowGraph) : List (NodeId × NodeId) :=
  graph.baseGraph.edges.filterMap fun e =>
    match e with
    | .loopBackEdge bodyEnd header => some (bodyEnd, header)
    | _ => none

/-- Check if there is a back edge from `fromId` to `toId` -/
def SemanticWorkflowGraph.hasBackEdge (graph : SemanticWorkflowGraph) (fromId toId : NodeId) : Bool :=
  graph.baseGraph.edges.any fun e =>
    match e with
    | .loopBackEdge bodyEnd header => bodyEnd == fromId && header == toId
    | _ => false

/-- Find forward successors (excluding back edge targets) -/
def SemanticWorkflowGraph.findForwardSuccessors (graph : SemanticWorkflowGraph) (nodeId : NodeId) : List NodeId :=
  let allSuccessors := graph.findSuccessors nodeId
  let backEdgeTargets := graph.findBackEdgeTargets nodeId
  allSuccessors.filter (fun s => !backEdgeTargets.contains s)


/--
Topological sort ignoring the back edges. This ensures we process nodes in dependency order, treating loops as if the back edge does not exist.
-/
def SemanticWorkflowGraph.topologicalSortIgnoringBackEdges
  (graph : SemanticWorkflowGraph) : Except String (List NodeId) :=
  let maxSearchDepth := graph.baseGraph.nodes.length + 10086
  let rec bfs
      (queue : List NodeId)
      (visitedNodes : List NodeId)
      (result : List NodeId)
      (depth : Nat) : Except String (List NodeId) :=
    match depth with
    | 0 => .error s!"Topological sort failed: fuel exhausted (possible ∞ cycle or too many nodes)"
    | depth + 1 =>
      match queue with
      | [] => .ok result
      | nodeId :: rest =>
        if visitedNodes.contains nodeId then
          bfs rest visitedNodes result depth
        else
          let forwardSuccessors := graph.findForwardSuccessors nodeId
          bfs (rest ++ forwardSuccessors) (nodeId :: visitedNodes) (result ++ [nodeId]) depth
  bfs [graph.entry] [] [] maxSearchDepth

end AgenticKernel
