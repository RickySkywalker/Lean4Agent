import Lean
import Mathlib
import AgentVerifier.DynamicVerification.Basics.DynamicVariablePredicate

/-!
# Section 2 — Dynamic Information Flow (Channel ②)

The runtime information-flow engine and its bridge to Layer-2's information
system (`AgentVerifier/StaticSemanticLayer/WorkflowQualityAnalysis/InformationSystem.lean`:
`InformationPredicate` / `VariableInformationPredicate` /
`ContextInformationPredicate` / `NodeInformationSpec` / `InformationFlowSpec`
/ `verifyInformationFlow`).

This is the §2 of the dynamic layer and is **entirely new** — the old Layer-3
had no information-flow channel at all (the `info_flow` block in its JSON was the
*static* Layer-2 result passed through). It mirrors Layer-2's `InformationSystem`
the way §1 mirrors the variable predicates, but adds the **dynamic** dimension.

## Why a *dynamic* information channel is not redundant

Layer-2's `verifyInformationFlow` is *step/order-blind about execution*: it
assumes every producer node runs, so it asks only "is this fact reachable in the
plan?". At runtime a producer can be **skipped** (branch not taken) or **fail**
(step crashed), so a downstream node runs **information-starved** even though the
plan was sound. Static says fine; the dynamic channel must alarm. This is exactly
isomorphic to how the goal-coverage channel uses `contributingNodesExecuted`.

So the dynamic judgment refines Layer-2's two visibility routes (variable, and
conversation-context) by **intersecting the producers with the trace-completed
set**:

  * A variable's information is *live* only if the node that writes it actually
    **completed** (parameters are always live).
  * A context node contributes information only if it actually **completed**.

An unmet requirement is then partitioned into:
  * `starved` — statically visible, but its producer did NOT execute (the
    dynamic-only failure), and
  * `absent`  — not visible even statically (a genuine plan-level gap).

## Three methods (orthogonal to the channel), mirroring §1

  1. Lean symbolic — the structural routing above (always computed, decidable).
  2. External tool — optional injected/IO judgement that the produced *content*
     really carries the required information.
  3. LLM judge     — optional injected/online semantic judgement of the content.

The structural Lean route is the primary verdict; the tool/LLM verdicts are an
optional *semantic refinement* on structurally-satisfied atoms (a variable can be
present yet not actually carry the fact the step needs). Verdicts are injected as
`DynamicInfoFlowInjection` (injection mode) or resolved over IO in §6.
-/

namespace AgenticKernel
namespace Dyn

/-!
## §2.1 — Bridging the trace to the executed-producer set

The dynamic judgment needs the set of nodes that actually completed. Two
constructors: from an explicit `List NodeId`, or derived from the §1
`DynamicNodeSpec`s (whose `executionStatus` records the trace outcome).
-/

/-- Node ids whose §1 spec recorded a `completed` execution status. This is the
    bridge from the per-node dynamic specs (§1) to the producer-liveness set
    used below. -/
def executedNodeIdsOfSpecs (specs : List DynamicNodeSpec) : List NodeId :=
  (specs.filter (fun s => s.executionStatus == .completed)).map (·.id)

/-!
## §2.2 — Semantic-refinement injection (Methods 2 & 3)

An optional per-(node, info-atom) judgement that the produced content really
carries the required information. Reuses §1's `LLMJudgementResult` /
`ExternalToolJudgementResult` so the injection plumbing is uniform across
channels.
-/

structure DynamicInfoFlowInjection where
  nodeId        : NodeId
  infoName      : String
  llmJudgement  : Option LLMJudgementResult := none
  toolJudgement : Option ExternalToolJudgementResult := none
  deriving Repr, Inhabited

def makeDynamicInfoFlowInjection
    (nodeId : NodeId) (infoName : String)
    (llmJudgement : Option LLMJudgementResult := none)
    (toolJudgement : Option ExternalToolJudgementResult := none) : DynamicInfoFlowInjection :=
  { nodeId := nodeId, infoName := infoName,
    llmJudgement := llmJudgement, toolJudgement := toolJudgement }

/-- Resolve the optional semantic verdict for one structurally-satisfied atom.
    Tool judgement (Method 2) takes precedence over LLM judgement (Method 3), as
    in §1; `none` means "no semantic check requested — structural Lean route only". -/
def resolveInfoSemanticVerdict
    (injections : List DynamicInfoFlowInjection)
    (nodeId : NodeId) (i : InformationPredicate) : Option DynamicPredicateVerificationResult :=
  match injections.find? (fun inj => inj.nodeId == nodeId && inj.infoName == i.name) with
  | none => none
  | some inj =>
    match inj.toolJudgement with
    | some t => some (if t.passed then .externalToolVerificationPass t else .externalToolVerificationFail t)
    | none =>
      match inj.llmJudgement with
      | some l => some (if l.holds then .llmJudgeVerificationPass l else .llmJudgeVerificationFail l)
      | none => none

/-!
## §2.3 — Dynamic visibility (Method 1: the structural routing)

These re-express Layer-2's `readableVariableInfo` / `readableContextInfo` but
with producers restricted to the executed set. They reuse Layer-2's static
visibility helpers (`visibleVariableNames`, `contextNodesVisibleTo`,
`visibleInfoAt`) unchanged — only the *producer set* is intersected with
execution.
-/

/-- Variable-information whose producing node actually completed. The param node
    is always live (parameters are always available), so it is folded into
    `effectiveExecuted` by the callers below. -/
def liveVariableInfo
    (spec : InformationFlowSpec)
    (effectiveExecuted : List NodeId) : List VariableInformationPredicate :=
  (spec.nodeSpecs.filter (fun ns => effectiveExecuted.contains ns.nodeId)).flatMap (·.producesVariableInfo)

/-- Dynamic analogue of Layer-2 `readableVariableInfo`: the information a node can
    obtain through variables it reads, restricted to variables whose producer
    actually executed. Reuses Layer-2 `visibleVariableNames` for the static
    "reads ∧ obtainable" part. -/
def dynReadableVariableInfo
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (effectiveExecuted : List NodeId)
    (nodeId : NodeId) : List InformationPredicate :=
  let visibleNames := visibleVariableNames graph nodeId
  ((liveVariableInfo spec effectiveExecuted).filter (fun vi => visibleNames.contains vi.varName)).flatMap (·.carries)
    |>.eraseDups

/-- Dynamic analogue of Layer-2 `readableContextInfo`: context information from
    nodes both context-visible (Layer-2 `contextNodesVisibleTo`) AND completed. -/
def dynReadableContextInfo
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (effectiveExecuted : List NodeId)
    (nodeId : NodeId) : List InformationPredicate :=
  ((contextNodesVisibleTo graph nodeId).filter (fun cid => effectiveExecuted.contains cid)
    |>.flatMap (fun cid => (spec.contextInfoOf cid).carries)).eraseDups

/-!
## §2.4 — Per-node and graph-level verdicts
-/

/-- The dynamic information-flow verdict for a single node. Mirrors Layer-2's
    `NodeInfoFlowResult` but (a) records whether the consuming node `executed`,
    (b) partitions the unmet requirements into `starved` (the dynamic-only
    failure) vs `absent`, and (c) carries optional semantic verdicts. -/
structure DynamicNodeInfoFlowResult where
  nodeId : NodeId
  executed : Bool
  required : List InformationPredicate
  satisfiedViaVariable : List InformationPredicate
  satisfiedViaContext : List InformationPredicate
  /-- Statically visible, but the producer did NOT execute — the dynamic alarm. -/
  starved : List InformationPredicate
  /-- Not visible even statically — a plan-level information gap. -/
  absent : List InformationPredicate
  /-- Optional Method 2/3 semantic verdicts on structurally-satisfied atoms. -/
  semanticResults : List (InformationPredicate × DynamicPredicateVerificationResult) := []
  deriving Inhabited

namespace DynamicNodeInfoFlowResult

/-- All unmet requirements (starved ∪ absent). -/
def missing (r : DynamicNodeInfoFlowResult) : List InformationPredicate :=
  r.starved ++ r.absent

/-- A failing semantic verdict means the content does not actually carry the
    information even though the variable/context is structurally present. -/
def semanticFailures (r : DynamicNodeInfoFlowResult) : List InformationPredicate :=
  (r.semanticResults.filter (fun p => p.2.failed)).map (·.1)

/-- A node passes iff: it did not execute (no obligations — coverage is the graph
    channel's concern), OR nothing is starved/absent AND no semantic verdict failed. -/
def passed (r : DynamicNodeInfoFlowResult) : Bool :=
  !r.executed || (r.starved.isEmpty && r.absent.isEmpty && r.semanticResults.all (fun p => !p.2.failed))

/-- Did this node run starved (executed with at least one starved requirement)? -/
def hasStarvation (r : DynamicNodeInfoFlowResult) : Bool :=
  r.executed && !r.starved.isEmpty

end DynamicNodeInfoFlowResult

/-- Run the dynamic two-level judgment for one node. `executedNodeIds` are the
    semantic nodes that completed in the trace; the param node is always live. -/
def verifyDynamicNodeInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (executedNodeIds : List NodeId)
    (injections : List DynamicInfoFlowInjection)
    (nodeId : NodeId) : DynamicNodeInfoFlowResult :=
  let effectiveExecuted := graph.paramNode.id :: executedNodeIds
  let executed := executedNodeIds.contains nodeId
  let req := spec.requiresOf nodeId
  let viaVar := dynReadableVariableInfo graph spec effectiveExecuted nodeId
  let viaCtx := dynReadableContextInfo graph spec effectiveExecuted nodeId
  -- Static visibility (Layer-2, ignores execution) — used to split starved vs absent.
  let staticVisible := visibleInfoAt graph spec nodeId
  let satVar := req.filter (fun i => viaVar.any (· == i))
  let satCtx := req.filter (fun i => viaCtx.any (· == i) && !viaVar.any (· == i))
  let unmet := req.filter (fun i => !viaVar.any (· == i) && !viaCtx.any (· == i))
  let starved := unmet.filter (fun i => staticVisible.any (· == i))
  let absent := unmet.filter (fun i => !staticVisible.any (· == i))
  let semanticResults := (satVar ++ satCtx).filterMap (fun i =>
    match resolveInfoSemanticVerdict injections nodeId i with
    | some v => some (i, v)
    | none   => none)
  { nodeId := nodeId
    executed := executed
    required := req
    satisfiedViaVariable := satVar
    satisfiedViaContext := satCtx
    starved := starved
    absent := absent
    semanticResults := semanticResults }

/-- The dynamic information-flow verdict for the whole graph. -/
structure DynamicInformationFlowResult where
  nodeResults : List DynamicNodeInfoFlowResult
  deriving Inhabited

namespace DynamicInformationFlowResult

/-- The graph passes iff every node's runtime information needs are met. -/
def passed (r : DynamicInformationFlowResult) : Bool :=
  r.nodeResults.all (·.passed)

/-- Nodes whose information needs are not met at runtime. -/
def failingNodes (r : DynamicInformationFlowResult) : List DynamicNodeInfoFlowResult :=
  r.nodeResults.filter (fun nr => !nr.passed)

/-- Nodes that ran information-starved (the dynamic-only alarm). -/
def starvedNodes (r : DynamicInformationFlowResult) : List DynamicNodeInfoFlowResult :=
  r.nodeResults.filter (·.hasStarvation)

end DynamicInformationFlowResult

/-!
## §2.5 — Verification bridge
-/

/-- THE DYNAMIC INFORMATION-FLOW VERIFICATION (graph-predicate level).

    For every semantic node, verify that the information it requires is visible at
    runtime — via a variable it reads whose producer executed, or via the context
    of a node that executed. This is the dynamic discharge of Layer-2's
    `verifyInformationFlow` contract. -/
def verifyDynamicInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (executedNodeIds : List NodeId)
    (injections : List DynamicInfoFlowInjection := []) : DynamicInformationFlowResult :=
  let ids := graph.semanticNodes.map (·.id)
  { nodeResults := ids.map (verifyDynamicNodeInformationFlow graph spec executedNodeIds injections) }

/-- Convenience: derive the spec from the graph (Layer-2 `InformationFlowSpec.fromGraph`)
    and the executed set from §1 specs, then verify. This is the entry point §4/§5 use. -/
def verifyDynamicInformationFlowFromSpecs
    (graph : SemanticWorkflowGraph)
    (nodeSpecs : List DynamicNodeSpec)
    (injections : List DynamicInfoFlowInjection := []) : DynamicInformationFlowResult :=
  verifyDynamicInformationFlow graph (InformationFlowSpec.fromGraph graph)
    (executedNodeIdsOfSpecs nodeSpecs) injections

/-- Boolean entry point, for `native_decide` soundness theorems. Pure structural
    (no injections) so it stays decidable. -/
def isDynamicInformationFlowSoundBool
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (executedNodeIds : List NodeId) : Bool :=
  (verifyDynamicInformationFlow graph spec executedNodeIds []).passed

/-!
## §2.6 — Pretty printing (mirrors Layer-2 `formatInformationFlowReport`)
-/

def formatDynInfoList (is : List InformationPredicate) : String :=
  if is.isEmpty then "(none)"
  else String.intercalate ", " (is.map (fun i => i.describe))

def formatDynamicNodeInfoFlowResult
    (graph : SemanticWorkflowGraph)
    (r : DynamicNodeInfoFlowResult) : String :=
  let name := match graph.findSemanticNode r.nodeId with
    | some n => n.baseNode.name.getD s!"node_{r.nodeId.val}"
    | none   => s!"node_{r.nodeId.val}"
  let status := if r.passed then "PASS" else "FAIL"
  let execStr := if r.executed then "executed" else "not-executed"
  if r.required.isEmpty then
    s!"  [{status}] node {r.nodeId.val} \"{name}\" ({execStr}): no information required"
  else
    let l1 := s!"  [{status}] node {r.nodeId.val} \"{name}\" ({execStr})"
    let l2 := s!"      requires:          {formatDynInfoList r.required}"
    let l3 := s!"      via variable read: {formatDynInfoList r.satisfiedViaVariable}"
    let l4 := s!"      via context:       {formatDynInfoList r.satisfiedViaContext}"
    let l5 := s!"      STARVED (producer not executed): {formatDynInfoList r.starved}"
    let l6 := s!"      ABSENT (plan gap):               {formatDynInfoList r.absent}"
    let l7 := if r.semanticFailures.isEmpty then ""
              else s!"\n      SEMANTIC FAIL (content lacks info): {formatDynInfoList r.semanticFailures}"
    s!"{l1}\n{l2}\n{l3}\n{l4}\n{l5}\n{l6}{l7}"

def formatDynamicInformationFlowReport
    (graph : SemanticWorkflowGraph)
    (result : DynamicInformationFlowResult) : String :=
  let overall := if result.passed then "DYNAMIC INFORMATION FLOW SOUND" else "DYNAMIC INFORMATION FLOW UNSOUND"
  let nodeLines := result.nodeResults.map (formatDynamicNodeInfoFlowResult graph) |> String.intercalate "\n"
  let failing := result.failingNodes
  let failSummary := if failing.isEmpty then "  None"
    else failing.map (fun nr =>
      let name := match graph.findSemanticNode nr.nodeId with
        | some n => n.baseNode.name.getD s!"node_{nr.nodeId.val}"
        | none   => s!"node_{nr.nodeId.val}"
      s!"  - node {nr.nodeId.val} \"{name}\" cannot see at runtime: {formatDynInfoList nr.missing}")
      |> String.intercalate "\n"
  s!"
═══════════════════════════════════════════════════
DYNAMIC INFORMATION FLOW REPORT (variable + context, execution-aware)
═══════════════════════════════════════════════════

Overall: {overall}

Per-node runtime information visibility:
{nodeLines}

Nodes with unmet information needs:
{failSummary}
═══════════════════════════════════════════════════"

/-- Convenience: run the verification and format the report in one call. -/
def analyzeDynamicInformationFlow
    (graph : SemanticWorkflowGraph)
    (spec : InformationFlowSpec)
    (executedNodeIds : List NodeId)
    (injections : List DynamicInfoFlowInjection := []) : String :=
  formatDynamicInformationFlowReport graph (verifyDynamicInformationFlow graph spec executedNodeIds injections)

end Dyn
end AgenticKernel
