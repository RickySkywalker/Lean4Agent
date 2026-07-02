import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.InformationSystem
import AgentVerifier.StaticSemanticLayer.UnifiedVerification

namespace AgenticKernel

/-!
# Verification JSON Output

Structured JSON serialization for all verification result types across the
three verification layers. Used by the `lean_query` Python tool to extract
machine-readable verification results.
-/

open Lean (Json)

-- ============================================================================
-- Shared / Utility
-- ============================================================================

private def mkObj := Lean.Json.mkObj

private def jStr (s : String) : Lean.Json := .str s
private def jBool (b : Bool) : Lean.Json := .bool b
private def jNat (n : Nat) : Lean.Json := .num n
private def jArr (xs : List Lean.Json) : Lean.Json := .arr xs.toArray
private def jNull : Lean.Json := .null

private def baseTypeToStr : BaseType → String
  | .TString => "TString"
  | .TInt => "TInt"
  | .TFloat => "TFloat"
  | .TBool => "TBool"
  | .TJson => "TJson"
  | .TList t => s!"TList({baseTypeToStr t})"
  | .TDict kt vt => s!"TDict({baseTypeToStr kt}, {baseTypeToStr vt})"
  | .TSet t => s!"TSet({baseTypeToStr t})"
  | .TOption t => s!"TOption({baseTypeToStr t})"
  | .TRecord fields => s!"TRecord({fields.length} fields)"
  | .TUnit => "TUnit"
  | .TUnknown => "TUnknown"

private def stepTypeToStr : StepType → String
  | .step => "step"
  | .task => "task"
  | .forEachLoop => "forEachLoop"
  | .whileLoop => "whileLoop"
  | .conditional => "conditional"
  | .switchBranch => "switchBranch"
  | .setVariable => "setVariable"
  | .incrementVariable => "incrementVariable"
  | .returnValue => "returnValue"
  | .input => "input"
  | .parallel => "parallel"
  | .call => "call"
  | .gather => "gather"
  | .save => "save" | .discover => "discover" | .evaluate => "evaluate" | .validate => "validate" | .synthesize => "synthesize"  -- deprecated/unused

private def variableToJson (v : TypedVar) : Lean.Json :=
  mkObj [("var_name", jStr v.name), ("type", jStr (baseTypeToStr v.type))]

-- (Removed `isSentinelVarNameBool`: sentinel classification now uses the
-- type-based `isSentinelPredicate` on the requirement's predicate, not a
-- `startsWith "__"` name match — FIX #2: type-based sentinel detection.)

-- ============================================================================
-- VariablePredicateRequirement → JSON
-- ============================================================================

def VariablePredicateRequirement.toJsonFull (req : VariablePredicateRequirement) : Lean.Json :=
  mkObj [
    ("var_name", jStr req.varName),
    ("predicate_type", jStr (toString (repr req.requiredPredicate))),
    ("predicate_json", req.requiredPredicate.toJson),
    ("is_sentinel", jBool (isSentinelPredicate req.requiredPredicate))
  ]

-- ============================================================================
-- Layer 1: WorkflowGraph → JSON
-- ============================================================================

private def edgeTypeToStr : WorkflowEdge → String
  | .seqEdge _ _ => "sequential"
  | .branchEdge _ _ _ => "branch"
  | .loopEdge _ _ _ => "loop"
  | .loopBackEdge _ _ => "loop_back"
  | .forkEdge _ _ => "fork"
  | .joinEdge _ _ => "join"
  | .switchEdge _ _ _ => "switch"

private def countEdgeTypes (edges : List WorkflowEdge) : Lean.Json :=
  let count (target : String) :=
    edges.filter (fun e => edgeTypeToStr e == target) |>.length
  mkObj [
    ("sequential", jNat (count "sequential")),
    ("branch", jNat (count "branch")),
    ("loop", jNat (count "loop")),
    ("loop_back", jNat (count "loop_back")),
    ("fork", jNat (count "fork")),
    ("join", jNat (count "join")),
    ("switch", jNat (count "switch"))
  ]

/-- Per-node Layer 1 diagnostics -/
def WorkflowNode.perNodeToJson (node : WorkflowNode) (graph : WorkflowGraph) : Lean.Json :=
  let readJsons := node.reads.map fun rv =>
    let fromParam := graph.parameters.any (fun p =>
      p.name == rv.name && p.type.compatible rv.type)
    let fromPred := graph.nodes.any (fun o =>
      o.id != node.id && graph.reachable o.id node.id &&
      (!graph.isParallelScopedNode o.id || graph.isParallelScopedNode node.id) &&
      o.writes.any (fun w => w.name == rv.name && w.type.compatible rv.type))
    let resolved := fromParam || fromPred
    let source := if fromParam then "parameter"
      else if fromPred then "predecessor"
      else "unresolved"
    mkObj [
      ("var_name", jStr rv.name),
      ("type", jStr (baseTypeToStr rv.type)),
      ("resolved", jBool resolved),
      ("source", jStr source),
      ("type_compatible", jBool resolved)
    ]
  let writeJsons := node.writes.map variableToJson
  let predecessors := graph.findPredecessors node.id |>.map (fun id => jNat id.val)
  let successors := graph.findSuccessors node.id |>.map (fun id => jNat id.val)
  mkObj [
    ("node_id", jNat node.id.val),
    ("node_name", jStr (node.name.getD "(unnamed)")),
    ("step_type", jStr (stepTypeToStr node.stepType)),
    ("needs_semantic_spec", jBool node.needSemanticSpec),
    ("output_type_determined", jBool node.outputTypeDetermined),
    ("writes_consistent", jBool node.writesConsistent),
    ("reachable_from_entry", jBool (graph.reachable graph.entry node.id)),
    ("reads", jArr readJsons),
    ("writes", jArr writeJsons),
    ("llm_instruction_present", jBool node.llmInstruction.isSome),
    ("predecessors", jArr predecessors),
    ("successors", jArr successors)
  ]

/-- Full Layer 1 verification output -/
def WorkflowGraph.layer1ToJson (graph : WorkflowGraph) : Lean.Json :=
  let theorems := mkObj [
    ("allWritesConsistent", jBool graph.allWritesConsistent),
    ("allReadResolvable", jBool graph.allReadResolvable),
    ("edgesValid", jBool graph.edgesValid),
    ("entryNodeValid", jBool graph.entryNodeValid),
    ("exitNodesValid", jBool graph.exitNodesValid),
    ("allExitsReachable", jBool graph.allExitsReachable),
    ("noOrphanNodes", jBool graph.noOrphanNodes)
  ]
  let perNode := graph.nodes.map fun n => n.perNodeToJson graph
  let summary := graph.verificationSummary
  let parallelScoped := graph.nodes.filter (fun n => graph.isParallelScopedNode n.id)
    |>.map (fun n => jNat n.id.val)
  let graphLevel := mkObj [
    ("node_count", jNat graph.nodes.length),
    ("edge_count", jNat graph.edges.length),
    ("entry_node_id", jNat graph.entry.val),
    ("exit_node_ids", jArr (graph.exits.map (fun id => jNat id.val))),
    ("parameters", jArr (graph.parameters.map variableToJson)),
    ("verification_summary", mkObj [
      ("total_nodes", jNat summary.totalNodes),
      ("deterministic_nodes", jNat summary.deterministicNodes),
      ("structured_nodes", jNat summary.structuredNodes),
      ("unstructured_nodes", jNat summary.unstructuredNodes),
      ("composition_nodes", jNat summary.compositionNodes)
    ]),
    ("parallel_scoped_nodes", jArr parallelScoped),
    ("edge_types", countEdgeTypes graph.edges)
  ]
  mkObj [
    ("layer", jNat 1),
    ("theorem_results", theorems),
    ("per_node_results", jArr perNode),
    ("graph_level_results", graphLevel)
  ]

-- ============================================================================
-- Layer 2: Semantic Verification → JSON
-- ============================================================================

/-- GraphVerifyResult → JSON with failure details -/
def GraphVerifyResult.toJson (result : GraphVerifyResult) : Lean.Json :=
  match result with
  | .success finalPreds =>
    mkObj [
      ("status", jStr "success"),
      ("is_sound", jBool true),
      ("exit_facts_count", jNat finalPreds.length),
      ("exit_facts", jArr (finalPreds.map VariablePredicateRequirement.toJsonFull)),
      ("failure_info", jNull)
    ]
  | .failure nodeId nodeName missingPred availPreds =>
    mkObj [
      ("status", jStr "failure"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "failure"),
        ("failed_node_id", jNat nodeId.val),
        ("failed_node_name", jStr nodeName),
        ("missing_predicate", missingPred.toJsonFull),
        ("available_predicates", jArr (availPreds.map VariablePredicateRequirement.toJsonFull)),
        ("available_predicates_count", jNat availPreds.length)
      ])
    ]
  | .loopInvariantMissing loopId name =>
    mkObj [
      ("status", jStr "loopInvariantMissing"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "loopInvariantMissing"),
        ("loop_header_id", jNat loopId.val),
        ("loop_header_name", jStr name)
      ])
    ]
  | .loopInvariantNotEstablished loopId name missingPred availPreds =>
    mkObj [
      ("status", jStr "loopInvariantNotEstablished"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "loopInvariantNotEstablished"),
        ("loop_header_id", jNat loopId.val),
        ("loop_header_name", jStr name),
        ("missing_invariant_predicate", missingPred.toJsonFull),
        ("available_predicates", jArr (availPreds.map VariablePredicateRequirement.toJsonFull)),
        ("available_predicates_count", jNat availPreds.length)
      ])
    ]
  | .loopInvariantNotPreserved loopId name missingPred bodyEndPreds =>
    mkObj [
      ("status", jStr "loopInvariantNotPreserved"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "loopInvariantNotPreserved"),
        ("loop_header_id", jNat loopId.val),
        ("loop_header_name", jStr name),
        ("missing_invariant_predicate", missingPred.toJsonFull),
        ("body_end_predicates", jArr (bodyEndPreds.map VariablePredicateRequirement.toJsonFull)),
        ("body_end_predicates_count", jNat bodyEndPreds.length)
      ])
    ]
  | .loopTerminationSpecInvalid loopId name reason =>
    mkObj [
      ("status", jStr "loopTerminationSpecInvalid"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "loopTerminationSpecInvalid"),
        ("loop_header_id", jNat loopId.val),
        ("loop_header_name", jStr name),
        ("reason", jStr reason)
      ])
    ]
  | .topologicalSortFailed reason =>
    mkObj [
      ("status", jStr "topologicalSortFailed"),
      ("is_sound", jBool false),
      ("exit_facts_count", jNat 0),
      ("exit_facts", jArr []),
      ("failure_info", mkObj [
        ("failure_type", jStr "topologicalSortFailed"),
        ("reason", jStr reason)
      ])
    ]

/-- GraphPredicateResult → JSON -/
def GraphPredicateResult.toJson (r : GraphPredicateResult) : Lean.Json :=
  mkObj [
    ("predicate_key", jStr r.predicateKey.name),
    ("short_label", jStr r.shortLabel),
    ("passed", jBool r.passed),
    ("required", jBool r.required),
    ("informational", jBool r.informational)
  ]

/-- GraphLevelIssue → JSON -/
def GraphLevelIssue.toJson : GraphLevelIssue → Lean.Json
  | .uncoveredSubGoal name =>
    mkObj [("type", jStr "uncoveredSubGoal"), ("sub_goal_name", jStr name.val)]
  | .requiredPredicateFailed name predKey desc =>
    mkObj [
      ("type", jStr "requiredPredicateFailed"),
      ("sub_goal_name", jStr name.val),
      ("predicate_key", jStr predKey.name),
      ("description", jStr desc)
    ]
  | .missingFromExitFacts name _ =>
    mkObj [
      ("type", jStr "missingFromExitFacts"),
      ("sub_goal_name", jStr name.val)
    ]

/-- SubGoalAnalysis → JSON -/
def SubGoalAnalysis.toJson (a : SubGoalAnalysis) : Lean.Json :=
  let level := computeSubGoalCoverageLevel a
  let levelStr := formatSubGoalCoverageLevel level
  let exitRes : GraphPredicateResult := {
    predicateKey := GraphLevelPredicateKeys.exitFactsConfirmed
    shortLabel := "exit_facts"
    passed := a.presentInExitFacts
    required := true
  }
  let allResults := a.predicateResults ++ [exitRes]
  mkObj [
    ("name", jStr a.subGoal.name.val),
    ("variable_name", jStr a.subGoal.variableName),
    ("required_predicate", a.subGoal.requiredPredicate.toJson),
    ("description", jStr a.subGoal.description),
    ("coverage_level", jStr levelStr),
    ("contributing_nodes", jArr (a.contributingNodes.map (fun id => jNat id.val))),
    ("verification_nodes", jArr (a.verificationNodes.map (fun id => jNat id.val))),
    ("predicate_results", jArr (allResults.map GraphPredicateResult.toJson)),
    ("present_in_exit_facts", jBool a.presentInExitFacts)
  ]

/-- GoalCoverageReport → JSON -/
def GoalCoverageReport.toJson (report : GoalCoverageReport) : Lean.Json :=
  mkObj [
    ("overall_coverage_level", jStr (formatGoalCoverageLevel report.coverageLevel)),
    ("sub_goals", jArr (report.subGoalAnalyses.map SubGoalAnalysis.toJson)),
    ("issues", jArr (report.issues.map GraphLevelIssue.toJson)),
    ("semantic_soundness", report.semanticSoundness.toJson),
    ("formatted_text", jStr (formatGoalCoverageReport report))
  ]

-- ============================================================================
-- Layer 2: Information-flow channel & unified three-channel report → JSON
--
-- FIX 6.1 — the information-flow channel (`verifyInformationFlow`) and the
-- unified `verifyWorkflow` verdict previously had NO JSON representation; only
-- the text banners (`formatInformationFlowReport` / `formatUnifiedReport`)
-- existed. These serializers give the third channel and the unified conclusion
-- a machine-readable form, consumed alongside the existing variable/coverage
-- output by the `lean_query` tool.
-- ============================================================================

/-- A list of information atoms → JSON array of their names. -/
private def infoListToJson (is : List InformationPredicate) : Lean.Json :=
  jArr (is.map (fun i => jStr i.name))

/-- Per-node information-flow verdict → JSON. Required atoms and how each is (or
    is not) satisfied — via a read variable, via the visible context, or missing. -/
def NodeInfoFlowResult.toJson (r : NodeInfoFlowResult) : Lean.Json :=
  mkObj [
    ("node_id", jNat r.nodeId.val),
    ("passed", jBool r.passed),
    ("required", infoListToJson r.required),
    ("satisfied_via_variable", infoListToJson r.satisfiedViaVariable),
    ("satisfied_via_context", infoListToJson r.satisfiedViaContext),
    ("missing", infoListToJson r.missing)
  ]

/-- Whole-graph information-flow channel → JSON. -/
def InformationFlowResult.toJson
    (graph : SemanticWorkflowGraph)
    (r : InformationFlowResult) : Lean.Json :=
  let failing := r.failingNodes.map fun nr =>
    let nodeName := match graph.findSemanticNode nr.nodeId with
      | some n => n.baseNode.name.getD s!"node_{nr.nodeId.val}"
      | none   => s!"node_{nr.nodeId.val}"
    mkObj [
      ("node_id", jNat nr.nodeId.val),
      ("node_name", jStr nodeName),
      ("missing", infoListToJson nr.missing)
    ]
  mkObj [
    ("is_sound", jBool r.passed),
    ("blocked_node_count", jNat r.failingNodes.length),
    ("node_results", jArr (r.nodeResults.map NodeInfoFlowResult.toJson)),
    ("failing_nodes", jArr failing),
    ("formatted_text", jStr (formatInformationFlowReport graph r))
  ]

/-- The unified three-channel report (variables · information flow · coverage)
    → JSON. This is the JSON face of `SemanticWorkflowGraph.verifyWorkflow` /
    `formatUnifiedReport`: one `all_sound` verdict plus a per-channel breakdown. -/
def UnifiedVerificationReport.toJson
    (graph : SemanticWorkflowGraph)
    (r : UnifiedVerificationReport) : Lean.Json :=
  mkObj [
    ("label", jStr r.label),
    ("all_sound", jBool r.allSound),
    ("channels", mkObj [
      ("variables", mkObj [
        ("is_sound", jBool r.hoareSound),
        ("exit_facts_count", jNat r.exitFactCount),
        ("result", r.hoare.toJson)
      ]),
      ("info_flow", mkObj [
        ("is_sound", jBool r.infoSound),
        ("result", InformationFlowResult.toJson graph r.info)
      ]),
      ("coverage", mkObj [
        ("is_sound", jBool (r.coverage.coverageLevel == .fullyCovered)),
        ("level", jStr (formatGoalCoverageLevel r.coverage.coverageLevel)),
        ("result", r.coverage.toJson)
      ])
    ]),
    ("formatted_text", jStr (formatUnifiedReport r))
  ]

/-- Compute per-node semantic state and produce per-node Layer 2 JSON -/
def SemanticWorkflowNode.perNodeLayer2ToJson
    (node : SemanticWorkflowNode)
    (availableState : List VariablePredicateRequirement) : Lean.Json :=
  let precondJsons := node.precondVariables.map fun p =>
    let satisfied := availableState.any (fun s => s.satisfies p)
    mkObj [
      ("var_name", jStr p.varName),
      ("predicate_type", jStr (toString (repr p.requiredPredicate))),
      ("predicate_json", p.requiredPredicate.toJson),
      ("satisfied", jBool satisfied),
      ("failure_detail",
        if satisfied then jNull
        else jStr s!"UNSATISFIED: predicate {repr p.requiredPredicate} for '{p.varName}' not found in cumulative state ({availableState.length} predicates)")
    ]
  let postcondJsons := node.postcondVariables.map VariablePredicateRequirement.toJsonFull
  -- FIX #2: extract sub-goal contributions/verifications structurally via the
  -- type-based extractors, not by `startsWith "__graph_contrib_/verify_"` +
  -- manual `.ext` arg parsing.
  let subGoalContribs := node.postcondVariables.filterMap (fun p =>
    extractContributionFromPredicate p.requiredPredicate)
  let subGoalVerifs := node.postcondVariables.filterMap (fun p =>
    extractVerificationFromPredicate p.requiredPredicate)
  let unsatCount := (precondJsons.filter (fun j =>
    match j with
    | .obj m => match m.find compare "satisfied" with
      | some (.bool false) => true
      | _ => false
    | _ => false)).length
  let errors : List Lean.Json :=
    if unsatCount > 0 then
      [jStr s!"PREDICATE CHAIN: {unsatCount} of {node.precondVariables.length} preconditions unsatisfied at node {node.baseNode.id.val} '{node.baseNode.name.getD "(unnamed)"}'"]
    else []
  mkObj [
    ("preconditions", jArr precondJsons),
    ("postconditions", jArr postcondJsons),
    ("sub_goal_contributions", jArr (subGoalContribs.map (fun s => jStr s.val))),
    ("sub_goal_verifications", jArr (subGoalVerifs.map (fun s => jStr s.val))),
    ("errors", jArr errors)
  ]

/-- Full Layer 2 verification output -/
def SemanticWorkflowGraph.layer2ToJson
    (semGraph : SemanticWorkflowGraph)
    (goalSpec : Option GoalSpecification := none)
    (registry : PredicateRegistry := emptyRegistry) : Lean.Json :=
  let verifyResult := semGraph.verify registry
  -- FIX 6.1: the information-flow channel, derived from the nodes' own
  -- information fields (`infoRequires` / `producesVariableInfo` /
  -- `producesContextInfo`) via the same overlay `verifyWorkflow` uses.
  let infoResult := verifyInformationFlow semGraph (InformationFlowSpec.fromGraph semGraph)
  -- Compute predicate chain trace (threading state through nodes)
  let paramPost := semGraph.paramNode.postcondVariables
  let perNodeJsons := Id.run do
    let mut state : List VariablePredicateRequirement := paramPost
    let mut results : List Lean.Json := []
    for node in semGraph.semanticNodes do
      let nodeL1 := node.baseNode.perNodeToJson semGraph.baseGraph
      let nodeL2 := node.perNodeLayer2ToJson state
      -- Compute cumulative state after this node
      let newState := node.postcondVariables.foldl (init := state) fun acc p =>
        if acc.any (fun s => s == p) then acc else acc ++ [p]
      let cumulativeStateJson := mkObj [
        ("predicate_count", jNat newState.length)
      ]
      -- FIX 6.1: attach this node's information-flow verdict alongside the
      -- variable-state trace, so the per-node JSON mirrors the text report's
      -- per-node summary (variable state · information flow · predicate coverage).
      let nodeL2WithState := match nodeL2 with
        | .obj m =>
          let m := m.insert compare "cumulative_state_after" cumulativeStateJson
          let m := match infoResult.nodeResults.find? (·.nodeId == node.baseNode.id) with
            | some ir => m.insert compare "information_flow" ir.toJson
            | none    => m
          Lean.Json.obj m
        | other => other
      results := results ++ [mkObj [
        ("node_id", jNat node.baseNode.id.val),
        ("node_name", jStr (node.baseNode.name.getD "(unnamed)")),
        ("step_type", jStr (stepTypeToStr node.baseNode.stepType)),
        ("layer1", nodeL1),
        ("layer2", nodeL2WithState)
      ]]
      state := newState
    return results
  -- FIX 6.2: honour the graph's embedded `goalSpec` (Solution 2 §2.3.1) when the
  -- caller doesn't override it, matching `verifyWorkflow`. The `Option` override
  -- is retained for old-format graphs whose `goalSpec` field is still empty and
  -- whose acceptance spec is supplied externally by the driver. Emit `null` only
  -- when there is genuinely no goal spec (no sub-goals) to report coverage for.
  let effectiveGoalSpec := goalSpec.getD semGraph.goalSpec
  let goalCoverageReport := analyzeGoalCoverage semGraph effectiveGoalSpec
  let goalCovJson :=
    if effectiveGoalSpec.subGoals.isEmpty then jNull
    else goalCoverageReport.toJson
  -- FIX 6.1: the unified three-channel verdict (variables · information flow ·
  -- coverage) — the JSON face of `verifyWorkflow`. Built from the same effective
  -- goalSpec and info result so it stays consistent with the blocks above.
  let unifiedReport : UnifiedVerificationReport :=
    { label := effectiveGoalSpec.originalGoal
      hoare := goalCoverageReport.semanticSoundness
      info := infoResult
      coverage := goalCoverageReport
      nodes := semGraph.semanticNodes }
  let l1 := semGraph.baseGraph.layer1ToJson
  mkObj [
    ("layer", jNat 2),
    ("theorem_results", mkObj [
      ("layer1", match l1 with
        | .obj m => match m.find compare "theorem_results" with
          | some j => j
          | none => jNull
        | _ => jNull),
      ("semantically_sound", jBool (semGraph.isSemanticallySoundBool registry))
    ]),
    ("per_node_results", jArr perNodeJsons),
    ("graph_level_results", mkObj [
      ("layer1", match l1 with
        | .obj m => match m.find compare "graph_level_results" with
          | some j => j
          | none => jNull
        | _ => jNull),
      ("semantic_verification", verifyResult.toJson),
      ("semantic_verification_formatted", jStr (describeGraphVerificationResult verifyResult)),
      ("goal_coverage", goalCovJson),
      -- FIX 6.1: the information-flow channel and the unified three-channel
      -- verdict, previously absent from the JSON.
      ("information_flow", InformationFlowResult.toJson semGraph infoResult),
      ("unified", UnifiedVerificationReport.toJson semGraph unifiedReport)
    ])
  ]

end AgenticKernel
