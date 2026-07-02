import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.SemanticGraph
import AgentVerifier.StaticSemanticLayer.SemanticVerification
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.ExtensiblePredicate
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel

/-!
# Information System (v3 — context-visibility aware, faithful)

## Why this file exists

The previous information machinery (`InfoContentPred` / `markInfoContent` in
`GraphLevelPredicates.lean`) modelled *information* as ordinary
`VariablePredicateRequirement`s that rode the Hoare pre/post-condition chain.
That conflated two semantically different things and was unfaithful to how the
agent engine actually exposes information to an LLM step:

  * **Variable information** — facts carried by a real `save_as` variable. An LLM
    step can only read it **when the step actually reads that variable**. If the
    variable exists in the system but the step does not read it, the LLM cannot
    see it.
  * **Context information** — facts that live in the *conversation history* of a
    node's execution. A node can only read them **when the producing node is in
    its context** (i.e. it shares the conversation history — a `task` chain in
    this engine; a `step` node starts fresh and sees none of it).

The Hoare chain (`SemanticWorkflowGraph.verify`) is **step/task-blind**: it
accumulates post-conditions forward unconditionally, which is correct for real
variables but wrong for conversation-history facts. So information must NOT be a
normal predicate in that judgment. This file gives information its own,
first-class representation and its own verification, gated by the *dynamic
context system* (`computeContextVisibility` / `computeTaskChain` /
`computeInjectedVars`) that already lives in `GraphLevelPredicates.lean`.

## The three predicate systems

```
┌──────────────────────────────────────────────────────────────────────┐
│ 1. InformationPredicate            the extensible atom: one named fact │
│      e.g. info "relevant_files", info "root_cause"                     │
├──────────────────────────────────────────────────────────────────────┤
│ 2. VariableInformationPredicate    container ATTACHED TO A VARIABLE    │
│      "variable v bears information {i₁, i₂, …}"                        │
│      readable iff the consuming step actually READS v                  │
├──────────────────────────────────────────────────────────────────────┤
│ 3. ContextInformationPredicate     container ATTACHED TO A NODE        │
│      "node n's execution context contributes information {i₁, …}"     │
│      readable iff n is IN the consuming node's context (task chain)    │
└──────────────────────────────────────────────────────────────────────┘
```

## The two-level judgment (graph-predicate level)

Each step declares, in a `NodeInformationSpec`, what information it **requires**,
what **variable** information it produces, and what **context** information it
produces. Then:

  * **Variable-information verification** (leaf): a required atom `i` is visible
    via a variable iff the node reads a variable that bears `i` (and that
    variable is genuinely available — injected by a reachable producer or a
    parameter). "If the variable is read we can see its information; otherwise we
    cannot."
  * **Context-information verification** (node level): first use the dynamic
    context system to compute which nodes are in this node's context; a required
    atom `i` is satisfied iff it is visible **via a read variable** (the leaf
    check) **or** it is contributed to the context by some in-context node.

Information that is neither readable from a variable nor present in the visible
context is **missing** — that is exactly the failure a `step` node hits when it
needs a fact that a predecessor only produced into the (now invisible)
conversation history.
-/

/-!
## Part 1: Information Predicates — the extensible atom

Uniform, extensible base marking *which* piece of information is represented.
Kept deliberately close in spirit to the old `InfoContentKeys.coversAspect`
family, but as a standalone notion that never enters the Hoare predicate chain.
-/

namespace InformationKeys
  def family : String := "information"

  /-- Structural key for one named piece of information.
      Uses `PredicateKey.withParam` for structural matching — no string parsing. -/
  def info (name : String) : PredicateKey :=
    .withParam family "info" name
end InformationKeys

-- ⚠️ The `InformationPredicate` atom and its basic ops (`info`,
-- `InformationPredicate.describe`, `InformationPredicate.elem`) now live in the
-- base `SemanticGraph.lean`, so the semantic node can carry typed information
-- fields. They are in scope here via the `SemanticGraph` import. Only the
-- registry-facing `.ext`-key projection (which needs the WQA-specific
-- `InformationKeys`) stays here.
def InformationPredicate.toKey (i : InformationPredicate) : PredicateKey := InformationKeys.info i.name

/-!
## Part 2: Variable Information Predicate — container attached to a variable

"Variable `varName` bears the information `carries`." This is only *seen* by a
step that actually reads `varName`; otherwise it is in the system but invisible
to the LLM.
-/

-- ⚠️ `VariableInformationPredicate`, `.bears`, and `varInfo` now live in the
-- base `SemanticGraph.lean` (so a node's `producesVariableInfo` field can be
-- typed). They are in scope here via the `SemanticGraph` import.

/-!
## Part 3: Context Information Predicate — container attached to a node

"Node `nodeId`'s execution contributes the information `carries` to its
conversation context." A downstream node may read this **only when `nodeId` is in
that node's context** — i.e. they share the conversation history. In this engine
that means a `task` chain; a `step` node starts fresh and reads none of it.
-/

structure ContextInformationPredicate where
  /-- The node whose execution context carries the information. -/
  nodeId : NodeId
  /-- The information that node contributes to the shared context. -/
  carries : List InformationPredicate
  deriving Repr, BEq, Inhabited

namespace ContextInformationPredicate

/-- Does this node's context contribute the given information atom? -/
def contributes (ci : ContextInformationPredicate) (i : InformationPredicate) : Bool :=
  ci.carries.any (· == i)

end ContextInformationPredicate

/-!
## Part 4: Per-node information specification

As the previous system did, each step notes down what it needs and what it
produces — but split into the two faithful channels. `requires` is what the step
must be able to read to execute correctly; `producesVariableInfo` is the
information it writes into real variables; `producesContextInfo` is the
information it contributes to its own conversation context.
-/

structure NodeInformationSpec where
  /-- The node this spec annotates. -/
  nodeId : NodeId
  /-- Information this node must be able to read to execute correctly. -/
  requires : List InformationPredicate := []
  /-- Variable-borne information this node produces (one entry per written variable). -/
  producesVariableInfo : List VariableInformationPredicate := []
  /-- Context-borne information this node contributes to its conversation context. -/
  producesContextInfo : List InformationPredicate := []
  deriving Repr, Inhabited

/-- The information-flow overlay for a whole workflow graph: one spec per node.
    It is intentionally a separate overlay rather than new fields on
    `SemanticWorkflowNode`, so the information system stays self-contained in the
    `WorkflowQualityAnalysis` layer and never enters the Hoare predicate chain. -/
structure InformationFlowSpec where
  nodeSpecs : List NodeInformationSpec := []
  deriving Inhabited

namespace InformationFlowSpec

/-- The spec for a node, if any. -/
def forNode (spec : InformationFlowSpec) (nodeId : NodeId) : Option NodeInformationSpec :=
  spec.nodeSpecs.find? (·.nodeId == nodeId)

/-- All variable-information declared by any node in the graph. -/
def allVariableInfo (spec : InformationFlowSpec) : List VariableInformationPredicate :=
  spec.nodeSpecs.flatMap (·.producesVariableInfo)

/-- The `ContextInformationPredicate` container for a node, built from its
    `producesContextInfo` (empty if the node has no spec). This materialises the
    third predicate type from the per-node declaration. -/
def contextInfoOf (spec : InformationFlowSpec) (nodeId : NodeId) : ContextInformationPredicate :=
  match spec.forNode nodeId with
  | some ns => ⟨nodeId, ns.producesContextInfo⟩
  | none    => ⟨nodeId, []⟩

/-- The `requires` set for a node (empty if the node has no spec). -/
def requiresOf (spec : InformationFlowSpec) (nodeId : NodeId) : List InformationPredicate :=
  match spec.forNode nodeId with
  | some ns => ns.requires
  | none    => []

/-- (Solution 2) Build the information-flow overlay directly FROM the semantic
    nodes' own information fields (`infoRequires` / `producesVariableInfo` /
    `producesContextInfo`). New-format plans declare information on the node, so
    the overlay is derived rather than supplied separately — and the existing
    `verifyInformationFlow` machinery is reused unchanged. -/
def fromGraph (graph : SemanticWorkflowGraph) : InformationFlowSpec :=
  -- The param node is included so its `producesVariableInfo` (e.g. a parameter
  -- like `problem_statement` bearing `issue_description`) joins `allVariableInfo`
  -- and is readable by the steps that read that parameter. `verifyInformationFlow`
  -- still only *checks* the `semanticNodes`, so the param node's own (empty)
  -- requirements are never verified — matching the old overlay's behaviour.
  { nodeSpecs := (graph.paramNode :: graph.semanticNodes).map fun node =>
      { nodeId := node.id
        requires := node.infoRequires
        producesVariableInfo := node.producesVariableInfo
        producesContextInfo := node.producesContextInfo } }

end InformationFlowSpec

/-!
## Part 5: Variable-information verification (leaf check)

"If the variable is read, then we can see the information; if not, we cannot."

A variable's information is visible to a node iff the node actually reads that
variable AND the variable is genuinely available to it — i.e. it is one of the
variables injected from a reachable producer (`computeInjectedVars`, surfaced by
`computeContextVisibility`) or a graph parameter. Information attached to a
variable the node does not read, or to a read variable with no producer, is not
visible.
-/

/-- The names of variables a node both *reads* and can genuinely *obtain* —
    injected from a reachable producer, or supplied as a graph parameter. -/
def visibleVariableNames
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId) : List String :=
  let vis := computeContextVisibility graph nodeId
  let injectedNames : List String := vis.injectedVars.map (fun p => p.1)
  let readNames : List String := match graph.findSemanticNode nodeId with
    | some n => n.baseNode.reads.map (fun v => v.name)
    | none   => []
  let paramNames : List String := readNames.filter (fun rn => graph.parameters.any (fun p => p.name == rn))
  (injectedNames ++ paramNames).eraseDups

/-- VARIABLE INFORMATION VERIFICATION — the set of information a node can obtain
    through the variables it reads. -/
def readableVariableInfo
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (nodeId : NodeId) : List InformationPredicate :=
  let visibleNames := visibleVariableNames graph nodeId
  (spec.allVariableInfo.filter (fun vi => visibleNames.contains vi.varName)).flatMap (·.carries)
    |>.eraseDups

/-- Is a single information atom readable by a node via some variable it reads? -/
def variableInfoVisible
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (nodeId : NodeId)
    (i : InformationPredicate) : Bool :=
  (readableVariableInfo graph spec nodeId).any (· == i)

/-!
## Part 6: Context-information verification (node level)

First use the dynamic context system to see which nodes are in this node's
context, then check each required atom against the read variables **or** the
visible context.
-/

/-- The nodes whose context information is visible to a node. A `step` node (stateful,
    new-engine semantics) sees the conversation history of its chain (`computeTaskChain`); a `task`
    node is a fresh, stateless call and sees no prior node's context. -/
def contextNodesVisibleTo
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId) : List NodeId :=
  let vis := computeContextVisibility graph nodeId
  if vis.stepType == .step then vis.taskChain else []

/-- The set of information a node can obtain from its execution CONTEXT: the union
    of the context information contributed by every node visible in its context. -/
def readableContextInfo
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (nodeId : NodeId) : List InformationPredicate :=
  ((contextNodesVisibleTo graph nodeId).flatMap (fun cid => (spec.contextInfoOf cid).carries)).eraseDups

/-- All information visible to a node: via a read variable OR via its context. -/
def visibleInfoAt
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (nodeId : NodeId) : List InformationPredicate :=
  (readableVariableInfo graph spec nodeId ++ readableContextInfo graph spec nodeId).eraseDups

/-!
## Part 7: Per-node and graph-level verdicts
-/

/-- The information-flow verdict for a single node. `satisfiedViaVariable` and
    `satisfiedViaContext` partition the satisfied requirements by route (variable
    route takes precedence in the partition, for reporting clarity). -/
structure NodeInfoFlowResult where
  nodeId : NodeId
  required : List InformationPredicate
  satisfiedViaVariable : List InformationPredicate
  satisfiedViaContext : List InformationPredicate
  missing : List InformationPredicate
  deriving Repr, Inhabited

/-- A node passes iff none of its required information is missing. -/
def NodeInfoFlowResult.passed (r : NodeInfoFlowResult) : Bool := r.missing.isEmpty

/-- Run the two-level judgment for one node. -/
def verifyNodeInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (nodeId : NodeId) : NodeInfoFlowResult :=
  let req := spec.requiresOf nodeId
  let viaVar := readableVariableInfo graph spec nodeId
  let viaCtx := readableContextInfo graph spec nodeId
  let satVar := req.filter (fun i => viaVar.any (· == i))
  let satCtx := req.filter (fun i => viaCtx.any (· == i) && !viaVar.any (· == i))
  let missing := req.filter (fun i => !viaVar.any (· == i) && !viaCtx.any (· == i))
  { nodeId := nodeId
    required := req
    satisfiedViaVariable := satVar
    satisfiedViaContext := satCtx
    missing := missing }

/-- The information-flow verdict for the whole graph. -/
structure InformationFlowResult where
  nodeResults : List NodeInfoFlowResult
  deriving Repr, Inhabited

/-- The graph passes iff every node's information needs are met. -/
def InformationFlowResult.passed (r : InformationFlowResult) : Bool :=
  r.nodeResults.all (·.passed)

/-- The nodes whose information needs are not met. -/
def InformationFlowResult.failingNodes (r : InformationFlowResult) : List NodeInfoFlowResult :=
  r.nodeResults.filter (fun nr => !nr.passed)

/-- THE NEW INFORMATION-FLOW VERIFICATION (graph-predicate level).

    For every semantic node, verify that the information it requires is visible —
    via a variable it reads, or via the context it can see. This replaces the old
    `contextContinuity` / `informationSufficiency` graph predicates as the
    faithful information judgment, and is independent of the Hoare predicate chain. -/
def verifyInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec) : InformationFlowResult :=
  let ids := graph.semanticNodes.map (·.id)
  { nodeResults := ids.map (verifyNodeInformationFlow graph spec) }

/-- Boolean entry point, for `native_decide` soundness theorems. -/
def isInformationFlowSoundBool
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec) : Bool :=
  (verifyInformationFlow graph spec).passed

/-!
## Part 8: Pretty printing
-/

def formatInfoList (is : List InformationPredicate) : String :=
  if is.isEmpty then "(none)"
  else String.intercalate ", " (is.map (fun i => i.describe))

def formatNodeInfoFlowResult
    (graph : SemanticWorkflowGraph)
    (r : NodeInfoFlowResult) : String :=
  let name := match graph.findSemanticNode r.nodeId with
    | some n => n.baseNode.name.getD s!"node_{r.nodeId.val}"
    | none   => s!"node_{r.nodeId.val}"
  let status := if r.passed then "PASS" else "FAIL"
  let stepTypeStr := match graph.findSemanticNode r.nodeId with
    | some n => s!"{repr n.baseNode.stepType}"
    | none   => "?"
  if r.required.isEmpty then
    s!"  [{status}] node {r.nodeId.val} \"{name}\" ({stepTypeStr}): no information required"
  else
    let l1 := s!"  [{status}] node {r.nodeId.val} \"{name}\" ({stepTypeStr})"
    let l2 := s!"      requires: {formatInfoList r.required}"
    let l3 := s!"      via variable read: {formatInfoList r.satisfiedViaVariable}"
    let l4 := s!"      via context:       {formatInfoList r.satisfiedViaContext}"
    let l5 := s!"      MISSING:           {formatInfoList r.missing}"
    s!"{l1}\n{l2}\n{l3}\n{l4}\n{l5}"

def formatInformationFlowReport
    (graph : SemanticWorkflowGraph)
    (result : InformationFlowResult) : String :=
  let overall := if result.passed then "INFORMATION FLOW SOUND" else "INFORMATION FLOW UNSOUND"
  let nodeLines := result.nodeResults.map (formatNodeInfoFlowResult graph) |> String.intercalate "\n"
  let failing := result.failingNodes
  let failSummary := if failing.isEmpty then "  None"
    else failing.map (fun nr =>
      let name := match graph.findSemanticNode nr.nodeId with
        | some n => n.baseNode.name.getD s!"node_{nr.nodeId.val}"
        | none   => s!"node_{nr.nodeId.val}"
      s!"  - node {nr.nodeId.val} \"{name}\" cannot see: {formatInfoList nr.missing}")
      |> String.intercalate "\n"
  s!"
═══════════════════════════════════════════════════
INFORMATION FLOW REPORT (variable + context channels)
═══════════════════════════════════════════════════

Overall: {overall}

Per-node information visibility:
{nodeLines}

Nodes with unmet information needs:
{failSummary}
═══════════════════════════════════════════════════"

/-- Convenience: run the verification and format the report in one call. -/
def analyzeInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec) : String :=
  formatInformationFlowReport graph (verifyInformationFlow graph spec)

end AgenticKernel
