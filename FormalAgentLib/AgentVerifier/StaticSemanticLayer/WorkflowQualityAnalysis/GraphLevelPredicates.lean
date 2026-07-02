import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.SemanticGraph
import AgentVerifier.StaticSemanticLayer.SemanticVerification
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.ExtensiblePredicate

namespace AgenticKernel

/-!
# Graph-Level Predicate System (v2 — Context-Aware)

## Motivation

This file adds **graph-level structural predicates** that check
properties spanning multiple nodes — especially those involving information flow
quality between nodes.

## Key Innovation: Information Content Tracking

The `step` vs `task` distinction in agent plans controls whether conversation
history is shared. When using `step` with `save_as`, the information fidelity
depends on what SPECIFIC aspects the variable captures. This system tracks
information content at the aspect level (e.g., "this variable covers
repo_structure, relevant_files, root_cause") rather than a generic level
(high/medium/low).

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│   Information System → see InformationSystem.lean            │
│   (legacy aspect-based machinery moved to                    │
│    GraphLevelPredicate_legacy.lean — Layer-3 back-compat)    │
├────────────────────────────────────────────────────────────┤
│         Context Visibility System (computed)                 │
│  computeTaskChain: which preceding task nodes share history  │
│  computeInjectedVars: which save_as variables are available  │
│  Derived from graph topology + StepType — NOT annotated      │
│  (reused by InformationSystem.lean's info-flow judgment)     │
├────────────────────────────────────────────────────────────┤
│         Graph-Level Predicates (extensible via registry)     │
│  pathCoverage: sub-goal on all paths to exit                 │
│  unifiedLoopBack: retry via explicit loop OR task context    │
│  verificationCoverage: separate verify step exists           │
│  failSafe: best-effort submit after retry exhaustion         │
│  (contextContinuity / informationSufficiency are LEGACY,     │
│   moved to GraphLevelPredicate_legacy.lean, NOT registered)  │
└────────────────────────────────────────────────────────────┘
```

## Design Principle

LLM performs LOCAL analysis: for each node, derive preconditions and
postconditions from the instruction text and the context the node can see.
Lean performs GLOBAL verification: check that the local annotations are
consistent across the entire workflow graph.
-/

/-!
## Part 1: Information Content System — MOVED ⚠️

The legacy aspect-on-a-variable information machinery (`InfoContentKeys`,
`InfoContentPred`, `extractAspectFromKey`, `isInfoContentPredicate`,
`markInfoContent`) has been MOVED OUT of this file into
`GraphLevelPredicate_legacy.lean`. It is deprecated and superseded by
`InformationSystem.lean` (the three-predicate system + `verifyInformationFlow`),
and is retained only for Layer-3 back-compat. The umbrella `StaticSemanticLayer.lean`
imports the legacy file so Layer-3 still resolves those symbols.
-/

/-!
## Part 2: Node-Level Annotations for Sub-Goals

LLM annotates each node with which sub-goals it contributes to or verifies.
These are encoded as `.ext` predicates on sentinel variable names.
-/

-- `SubGoalName` (the typed sub-goal identity, FIX #3) now lives in the base
-- `SemanticGraph.lean` so the semantic node can carry typed graph-predicate
-- fields. It is in scope here via the `SemanticGraph` import.

namespace GraphLevelKeys
  def family : String := "graph_level"

  /-- Single source of truth for the predicate-kind `name` of each graph-level
      marker. Both the producer (`subGoalContribution` / `subGoalVerification`)
      and the consumer (`extractContributionFromKey` / `extractVerificationFromKey`)
      reference these constants, so a typo becomes a compile error instead of a
      silently-failing bare-string comparison (FIX #1: name-literal dedup). -/
  def contributionName : String := "subGoalContribution"
  def verificationName : String := "subGoalVerification"

  /-- This node contributes to establishing the named sub-goal -/
  def subGoalContribution (subGoalName : String) : PredicateKey :=
    .withParam family contributionName subGoalName

  /-- This node verifies the named sub-goal (reads & checks it) -/
  def subGoalVerification (subGoalName : String) : PredicateKey :=
    .withParam family verificationName subGoalName
end GraphLevelKeys


/-- Mark that this node contributes to establishing a sub-goal -/
def markSubGoalContribution (nodeId : NodeId) (subGoalName : SubGoalName) : VariablePredicateRequirement :=
  ⟨s!"__graph_contrib_{nodeId.val}_{subGoalName.val}",
   .ext (GraphLevelKeys.subGoalContribution subGoalName.val)⟩

/-- Mark that this node verifies a sub-goal -/
def markSubGoalVerification (nodeId : NodeId) (subGoalName : SubGoalName) : VariablePredicateRequirement :=
  ⟨s!"__graph_verify_{nodeId.val}_{subGoalName.val}",
   .ext (GraphLevelKeys.subGoalVerification subGoalName.val)⟩

-- Node capability: implicit LLM retry
namespace NodeCapabilityKeys
  def family : String := "node_capability"

  /-- Single source of truth for the implicit-retry predicate-kind `name`
      (referenced by both `implicitRetryFor` and `extractImplicitRetryFromKey`;
      FIX #1: name-literal dedup). -/
  def implicitRetryName : String := "implicitRetry"

  /-- Node supports implicit LLM-driven retry for a specific sub-goal -/
  def implicitRetryFor (subGoalName : String) : PredicateKey :=
    .makePredicateKey family implicitRetryName [.argStr subGoalName]
end NodeCapabilityKeys

/-- Mark that this node supports implicit LLM retry for a sub-goal -/
def markImplicitRetry (nodeId : NodeId) (subGoalName : SubGoalName) : VariablePredicateRequirement :=
  ⟨s!"__node_cap_{nodeId.val}_implicit_retry_{subGoalName.val}",
   .ext (NodeCapabilityKeys.implicitRetryFor subGoalName.val)⟩

-- Extraction helpers

def extractContributionFromKey (key : PredicateKey) : Option SubGoalName :=
  match key with
  | .makePredicateKey family name args =>
    if family == GraphLevelKeys.family && name == GraphLevelKeys.contributionName then
      match args with
      | [.argStr subGoalName] => some ⟨subGoalName⟩
      | _ => none
    else none

def extractVerificationFromKey (key : PredicateKey) : Option SubGoalName :=
  match key with
  | .makePredicateKey family name args =>
    if family == GraphLevelKeys.family && name == GraphLevelKeys.verificationName then
      match args with
      | [.argStr subGoalName] => some ⟨subGoalName⟩
      | _ => none
    else none

def extractImplicitRetryFromKey (key : PredicateKey) : Option SubGoalName :=
  match key with
  | .makePredicateKey family name args =>
    if family == NodeCapabilityKeys.family && name == NodeCapabilityKeys.implicitRetryName then
      match args with
      | [.argStr subGoalName] => some ⟨subGoalName⟩
      | _ => none
    else none

def extractContributionFromPredicate (pred : PredicateType) : Option SubGoalName :=
  match pred with | .ext key => extractContributionFromKey key | _ => none

def extractVerificationFromPredicate (pred : PredicateType) : Option SubGoalName :=
  match pred with | .ext key => extractVerificationFromKey key | _ => none

def extractImplicitRetryFromPredicate (pred : PredicateType) : Option SubGoalName :=
  match pred with | .ext key => extractImplicitRetryFromKey key | _ => none



/-!
## Part 3: Context Visibility System (Computed)

Context visibility is derived from the graph topology and node step types.
It is NOT annotated by the LLM — this prevents annotation errors and makes
the analysis deterministic.

Key semantics:
- `task` nodes share conversation history with preceding `task` nodes in
  a linear chain (the "task chain")
- `step` nodes start fresh — they only see injected `save_as` variables
  and parameters
-/

/-- What information a node can actually see at execution time -/
structure ContextVisibility where
  nodeId : NodeId
  stepType : StepType
  /-- Variables explicitly injected via save_as: (varName, producerNodeId) -/
  injectedVars : List (String × NodeId)
  /-- If step (stateful, new-engine semantics): chain of preceding step nodes sharing conversation history.
      Empty for task (stateless) nodes or step nodes after a branch merge. -/
  taskChain : List NodeId
  deriving Repr, Inhabited

/-- Compute the conversation-history chain for a node: the maximal sequence of consecutive
    step-type (stateful) predecessors, stopping at any task-type (stateless) node, branch merge
    (multiple predecessors), or graph entry.

    Only step nodes get a non-empty chain (new-engine semantics: step is the stateful action). -/
def computeTaskChain
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId)
    (fuel : Nat := graph.semanticNodes.length + 1) : List NodeId :=
  match fuel with
  | 0 => []
  | Nat.succ fuel' =>
    match graph.findSemanticNode nodeId with
    | none => []
    | some node =>
      if node.baseNode.stepType != .step then []
      else
        let preds := graph.findPredecessorsIgnoringBackEdge nodeId
        match preds with
        | [singlePred] =>
          match graph.findSemanticNode singlePred with
          | none => []
          | some predNode =>
            if predNode.baseNode.stepType == .step then
              singlePred :: computeTaskChain graph singlePred fuel'
            else []
        | _ => []  -- branch merge or no predecessors → no conversation-history chain

/-- Compute which variables are explicitly injected into a node via save_as.
    For each variable in the node's reads, find which predecessor writes it. -/
def computeInjectedVars
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId) : List (String × NodeId) :=
  match graph.findSemanticNode nodeId with
  | none => []
  | some node =>
    let readVarNames := node.baseNode.reads.map (·.name)
    let predecessors := graph.findTransitivePredecessorSemanticNodes nodeId
    readVarNames.filterMap fun varName =>
      -- Find the closest predecessor that writes this variable
      predecessors.findSome? fun predNode =>
        if predNode.baseNode.writes.any (fun w => w.name == varName)
        then some (varName, predNode.id)
        else none

/-- Compute full context visibility for a node -/
def computeContextVisibility
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId) : ContextVisibility :=
  let stepType := match graph.findSemanticNode nodeId with
    | some n => n.baseNode.stepType
    | none => .step
  { nodeId := nodeId
    stepType := stepType
    injectedVars := computeInjectedVars graph nodeId
    taskChain := computeTaskChain graph nodeId }

/-!
## Part 4: Extracted Graph-Level Attributes
-/

structure ExtractedSubGoalContribution where
  nodeId : NodeId
  subGoalName : SubGoalName
  deriving Repr, BEq, Inhabited

structure ExtractedSubGoalVerification where
  nodeId : NodeId
  subGoalName : SubGoalName
  deriving Repr, BEq, Inhabited

structure ExtractedGraphLevelAttributes where
  contributions : List ExtractedSubGoalContribution
  verifications : List ExtractedSubGoalVerification
  deriving Repr, Inhabited

-- Solution 2: a node's graph contributions/verifications now live in its
-- dedicated `graphContributions` / `graphVerifications` fields. Pre-Solution-2
-- plans encoded them as `markSubGoalContribution` / `markSubGoalVerification`
-- sentinels in `postcondVariables`. To keep BOTH formats verifying through the
-- same path (new `*_new.lean`, the migrated `*_v2.lean`, and Layer-3 alike),
-- extraction reads the UNION of the field and the legacy markers.
def extractSubGoalContributions (node : SemanticWorkflowNode) : List ExtractedSubGoalContribution :=
  ((node.graphContributions.map fun sg => (⟨node.id, sg⟩ : ExtractedSubGoalContribution))
    ++ node.postcondVariables.filterMap fun req =>
        extractContributionFromPredicate req.requiredPredicate
          |>.map fun sg => (⟨node.id, sg⟩ : ExtractedSubGoalContribution))
    |>.eraseDups

def extractSubGoalVerifications (node : SemanticWorkflowNode) : List ExtractedSubGoalVerification :=
  ((node.graphVerifications.map fun sg => (⟨node.id, sg⟩ : ExtractedSubGoalVerification))
    ++ node.postcondVariables.filterMap fun req =>
        extractVerificationFromPredicate req.requiredPredicate
          |>.map fun sg => (⟨node.id, sg⟩ : ExtractedSubGoalVerification))
    |>.eraseDups

def extractGraphLevelAttributes (graph : SemanticWorkflowGraph) : ExtractedGraphLevelAttributes :=
  let contributions := graph.semanticNodes.flatMap extractSubGoalContributions
  let verifications := graph.semanticNodes.flatMap extractSubGoalVerifications
  ⟨contributions, verifications⟩

/-!
## Part 5: Graph-Level Predicate Framework (Extensible)
-/

/-- Context passed to graph-level predicate check functions -/
structure GraphCheckContext where
  graph : SemanticWorkflowGraph
  subGoalName : SubGoalName
  contributingNodes : List NodeId
  verificationNodes : List NodeId
  exitFacts : List VariablePredicateRequirement
  registry : PredicateRegistry

/-- Type class for graph-level predicates -/
class GraphLevelPredicate (α : Type) where
  toKey : α → PredicateKey
  check : α → GraphCheckContext → Bool
  describe : α → String
  shortLabel : α → String
  /-- If true, never counts as required for coverage — always informational -/
  isInformational : α → Bool := fun _ => false

/-- A single entry in the graph-level predicate registry -/
structure GraphLevelPredicateEntry where
  predicateKey : PredicateKey
  check : GraphCheckContext → Bool
  description : String := ""
  shortLabel : String := ""
  /-- If true, this predicate is always informational — it is evaluated and
      displayed but NEVER counts as required for coverage computation,
      even if listed in requiredGraphPredicates. -/
  informational : Bool := false

/-- Unified predicate registry: variable-level + graph-level -/
structure UnifiedPredicateRegistry where
  varRegistry : PredicateRegistry := PredicateRegistry.empty
  graphEntries : List GraphLevelPredicateEntry := []
  deriving Inhabited

namespace UnifiedPredicateRegistry

def empty : UnifiedPredicateRegistry := ⟨PredicateRegistry.empty, []⟩

def fromPredicateRegistry (reg : PredicateRegistry) : UnifiedPredicateRegistry :=
  ⟨reg, []⟩

def toPredicateRegistry (reg : UnifiedPredicateRegistry) : PredicateRegistry :=
  reg.varRegistry

def registerVar (reg : UnifiedPredicateRegistry) (entry : PredicateRegistryEntry)
    : UnifiedPredicateRegistry :=
  { reg with varRegistry := reg.varRegistry.register entry }

def registerVarPred [ExtendedPredicate α] (reg : UnifiedPredicateRegistry) (pred : α)
    : UnifiedPredicateRegistry :=
  { reg with varRegistry := reg.varRegistry.registerPred pred }

def registerGraph (reg : UnifiedPredicateRegistry) (entry : GraphLevelPredicateEntry)
    : UnifiedPredicateRegistry :=
  { reg with graphEntries := reg.graphEntries ++ [entry] }

def registerGraphPred [GraphLevelPredicate α] (reg : UnifiedPredicateRegistry) (pred : α)
    : UnifiedPredicateRegistry :=
  reg.registerGraph {
    predicateKey := GraphLevelPredicate.toKey pred
    check := GraphLevelPredicate.check pred
    description := GraphLevelPredicate.describe pred
    shortLabel := GraphLevelPredicate.shortLabel pred
    informational := GraphLevelPredicate.isInformational pred
  }

def lookupGraph (reg : UnifiedPredicateRegistry) (key : PredicateKey)
    : Option GraphLevelPredicateEntry :=
  reg.graphEntries.find? (·.predicateKey == key)

def evaluateGraph (reg : UnifiedPredicateRegistry) (key : PredicateKey) (ctx : GraphCheckContext)
    : Option (Bool × String) :=
  reg.lookupGraph key |>.map fun entry => (entry.check ctx, entry.shortLabel)

end UnifiedPredicateRegistry

/-!
## Part 6: Built-in Graph-Level Predicates
-/

namespace GraphLevelPredicateKeys
  def family : String := "graph_check"

  def pathCoverage : PredicateKey := .simple family "pathCoverage"
  def verificationCoverage : PredicateKey := .simple family "verificationCoverage"
  def exitFactsConfirmed : PredicateKey := .simple family "exitFactsConfirmed"
  def contextContinuity : PredicateKey := .simple family "contextContinuity"
  def informationSufficiency : PredicateKey := .simple family "informationSufficiency"
  def unifiedLoopBack : PredicateKey := .simple family "unifiedLoopBack"
  def failSafe : PredicateKey := .simple family "failSafe"
end GraphLevelPredicateKeys

-- Helper: check if a variable name is a sentinel (metadata, not real info).
-- Retained as-is: it is part of the public surface consumed by string-only
-- callers (PerStepMoveAnalysis, ElaipBench, VerificationJsonOutput) that only
-- have a variable name in hand. Prefer `isSentinelPredicate` below whenever the
-- full requirement (with its predicate) is available.
def isSentinelVarName (varName : String) : Bool :=
  varName.startsWith "__step_tag_" ||
  varName.startsWith "__write_ctx_" ||
  varName.startsWith "__graph_contrib_" ||
  varName.startsWith "__graph_verify_" ||
  varName.startsWith "__node_cap_"

/-- Type-based counterpart of `isSentinelVarName`: classify a requirement as a
    metadata sentinel by the structural family of its predicate key, with no
    variable-name parsing. A requirement is a sentinel iff its predicate is an
    `.ext` key in a graph-level metadata family — sub-goal
    contribution/verification (`graph_level`) or node capability
    (`node_capability`). Those families are produced *only* by the
    `markSubGoal*` / `markImplicitRetry` markers, which are exactly the markers
    that also emit the `__graph_contrib_` / `__graph_verify_` / `__node_cap_`
    sentinel names — so for every requirement the system can construct this
    agrees with `isSentinelVarName`, without matching on the name. (The legacy
    `__step_tag_` / `__write_ctx_` prefixes have no producer in the codebase.) -/
def isSentinelPredicate (pred : PredicateType) : Bool :=
  match pred with
  | .ext key => key.family == GraphLevelKeys.family
             || key.family == NodeCapabilityKeys.family
  | _ => false

-- ═══════════════════════════════════════════════════════════════
-- 6a. Path Coverage
-- ═══════════════════════════════════════════════════════════════

structure PathCoverageCheck where deriving Repr, BEq, Inhabited

def isSubGoalCoveredToExit
    (graph : SemanticWorkflowGraph)
    (contributingNodeIds : List NodeId)
    (exitNodeId : NodeId) : Bool :=
  contributingNodeIds.any fun contribId =>
    contribId == exitNodeId || graph.reachable contribId exitNodeId

instance : GraphLevelPredicate PathCoverageCheck where
  toKey _ := GraphLevelPredicateKeys.pathCoverage
  check _ ctx :=
    ctx.graph.exits.all fun exitNodeId =>
      isSubGoalCoveredToExit ctx.graph ctx.contributingNodes exitNodeId
  describe _ := "Sub-goal must be established on all execution paths to exit"
  shortLabel _ := "path"

-- ═══════════════════════════════════════════════════════════════
-- 6b. Verification Coverage
-- ═══════════════════════════════════════════════════════════════

structure VerificationCoverageCheck where deriving Repr, BEq, Inhabited

instance : GraphLevelPredicate VerificationCoverageCheck where
  toKey _ := GraphLevelPredicateKeys.verificationCoverage
  check _ ctx :=
    ctx.verificationNodes.any fun verifyId =>
      ctx.contributingNodes.any fun contribId =>
        contribId != verifyId && ctx.graph.reachable contribId verifyId
  describe _ := "A verification step must exist after a contributing node"
  shortLabel _ := "verify"

-- ═══════════════════════════════════════════════════════════════
-- 6c. Context Continuity / 6d. Information Sufficiency — MOVED ⚠️
-- ═══════════════════════════════════════════════════════════════
--
-- The two legacy information graph-predicates `ContextContinuityCheck` and
-- `InformationSufficiencyCheck` (plus the helper `isPrecondSatisfiedByContext`)
-- have been MOVED OUT of this file into `GraphLevelPredicate_legacy.lean`. They
-- are deprecated, NOT registered in `defaultUnifiedRegistry`, and superseded by
-- `InformationSystem.lean` (`verifyInformationFlow`). They are retained only for
-- Layer-3 back-compat (`DynamicGraphLevelVerification.lean` ports their `check`);
-- the umbrella `StaticSemanticLayer.lean` imports the legacy file so Layer-3 still
-- resolves them.

-- ═══════════════════════════════════════════════════════════════
-- 6e. Unified Loop-Back (merges retryRobustness + implicitRetry)
-- ═══════════════════════════════════════════════════════════════

structure UnifiedLoopBackCheck where deriving Repr, BEq, Inhabited

def isNodeInsideLoop (graph : SemanticWorkflowGraph) (nodeId : NodeId) : Bool :=
  graph.loopNodes.any fun loopNode =>
    let headerId := loopNode.id
    match graph.findLoopBodyEnd headerId with
    | some bodyEndId =>
      (headerId == nodeId || graph.reachable headerId nodeId) &&
      (nodeId == bodyEndId || graph.reachable nodeId bodyEndId)
    | none => false

def hasImplicitRetryForSubGoal (graph : SemanticWorkflowGraph) (nodeId : NodeId) (subGoalName : SubGoalName) : Bool :=
  graph.semanticNodes.any fun node =>
    node.baseNode.id == nodeId &&
    -- Solution 2: implicit-retry capability lives in `graphImplicitRetries`;
    -- pre-Solution-2 plans used `markImplicitRetry` postcond sentinels (union).
    (node.graphImplicitRetries.contains subGoalName ||
     node.postcondVariables.any fun req =>
      match extractImplicitRetryFromPredicate req.requiredPredicate with
      | some sgName => sgName == subGoalName
      | none => false)

instance : GraphLevelPredicate UnifiedLoopBackCheck where
  toKey _ := GraphLevelPredicateKeys.unifiedLoopBack
  check _ ctx :=
    ctx.contributingNodes.any fun nodeId =>
      match ctx.graph.findSemanticNode nodeId with
      | none => false
      | some node =>
        -- Case 1: Node is inside an explicit retry loop
        let inLoop := isNodeInsideLoop ctx.graph nodeId
        -- Case 2: Step node (stateful, new-engine semantics) with implicit LLM retry (conversation history enables self-correction)
        let taskRetry := node.baseNode.stepType == .step &&
          hasImplicitRetryForSubGoal ctx.graph nodeId ctx.subGoalName
        -- NOTE: a former "Case 3" (step node inside a loop with structured predecessor
        -- info) was removed. It had `inLoop` as a conjunct, so it was logically subsumed
        -- by Case 1 and could never change `inLoop || taskRetry || ...`. Dropping it also
        -- removes this active predicate's only dependency on the legacy
        -- `isInfoContentPredicate` (now in GraphLevelPredicate_legacy.lean).
        inLoop || taskRetry
  describe _ := "Contributing node has retry capability: explicit retry loop, or step conversation history"
  shortLabel _ := "loop_back"

-- ═══════════════════════════════════════════════════════════════
-- 6f. Fail-Safe
-- ═══════════════════════════════════════════════════════════════

structure FailSafeCheck where deriving Repr, BEq, Inhabited

/-- Find the exit node of the loop containing a given node -/
def findLoopExitForNode
    (graph : SemanticWorkflowGraph)
    (nodeId : NodeId) : Option NodeId :=
  graph.baseGraph.edges.findSome? fun edge =>
    match edge with
    | .loopEdge header _ exit =>
      if isNodeInsideLoop graph nodeId &&
         (header == nodeId || graph.reachable header nodeId)
      then some exit
      else none
    | _ => none

instance : GraphLevelPredicate FailSafeCheck where
  toKey _ := GraphLevelPredicateKeys.failSafe
  check _ ctx :=
    -- Check if there's a fail-safe path for nodes inside loops
    ctx.contributingNodes.any fun nodeId =>
      if isNodeInsideLoop ctx.graph nodeId then
        match findLoopExitForNode ctx.graph nodeId with
        | none => false
        | some loopExitId =>
          -- Check if there's a node after the loop exit that still writes
          -- the sub-goal variable on a path to a graph exit
          ctx.graph.exits.any fun graphExit =>
            ctx.graph.semanticNodes.any fun fallbackNode =>
              fallbackNode.id != nodeId &&
              (fallbackNode.id == loopExitId || ctx.graph.reachable loopExitId fallbackNode.id) &&
              (fallbackNode.id == graphExit || ctx.graph.reachable fallbackNode.id graphExit) &&
              -- FIX #5 (exposed by the SubGoalName newtype): the old first
              -- disjunct `req.varName == ctx.subGoalName` compared a *variable*
              -- name against a *sub-goal* name — two different namespaces — so it
              -- was a silent always-false dead branch. With typed names that line
              -- is a type error, so it is removed; the structural contribution
              -- check below is the correct (and only) test.
              fallbackNode.postcondVariables.any fun req =>
                extractContributionFromPredicate req.requiredPredicate == some ctx.subGoalName
      else false
  describe _ := "After retry exhaustion, the workflow still submits best available results"
  shortLabel _ := "failsafe"
  isInformational _ := true

-- ═══════════════════════════════════════════════════════════════
-- 6g. Exit Facts Confirmed
-- ═══════════════════════════════════════════════════════════════

structure ExitFactsConfirmedCheck where
  variableName : String
  requiredPredicate : PredicateType
  deriving Repr, BEq, Inhabited

instance : GraphLevelPredicate ExitFactsConfirmedCheck where
  toKey _ := GraphLevelPredicateKeys.exitFactsConfirmed
  check p ctx :=
    ctx.exitFacts.any fun fact =>
      fact.varName == p.variableName &&
      fact.requiredPredicate.compatibleWithRegistry p.requiredPredicate ctx.registry
  describe _ := "Sub-goal predicate must be confirmed in Hoare-logic exit facts"
  shortLabel _ := "exit_facts"

/-!
## Part 7: Default Registry
-/

def defaultUnifiedRegistry : UnifiedPredicateRegistry :=
  -- INFORMATION FLOW IS NO LONGER JUDGED HERE.
  -- The old `ContextContinuityCheck` / `InformationSufficiencyCheck` predicates
  -- conflated variable-level and context-level information and treated both as
  -- ordinary graph predicates. They are intentionally NOT registered anymore.
  -- Information is now verified by the dedicated, context-visibility–aware system
  -- in `InformationSystem.lean` (`verifyInformationFlow`), which keeps the two
  -- channels distinct and stays out of the predicate judgment entirely.
  -- The two checks now live in `GraphLevelPredicate_legacy.lean` (Layer-3 back-compat
  -- only); do not re-add them here.
  UnifiedPredicateRegistry.empty
    |>.registerGraphPred (PathCoverageCheck.mk)
    |>.registerGraphPred (VerificationCoverageCheck.mk)
    |>.registerGraphPred (UnifiedLoopBackCheck.mk)
    |>.registerGraphPred (FailSafeCheck.mk)

def unifiedRegistryWithDefaults (varRegistry : PredicateRegistry := PredicateRegistry.empty)
    : UnifiedPredicateRegistry :=
  { defaultUnifiedRegistry with varRegistry := varRegistry }

/-!
## Part 8: Goal Specification — MOVED ⚠️

`SubGoalSpec` and `GoalSpecification` now live in the base `SemanticGraph.lean`
(so the whole-graph `goalSpec` field and the node graph-fields can be typed).
They are in scope here via the `SemanticGraph` import.

## Part 9: Analysis Results
-/

structure GraphPredicateResult where
  predicateKey : PredicateKey
  shortLabel : String
  passed : Bool
  required : Bool
  /-- Informational predicates: always displayed, never affect coverage -/
  informational : Bool := false
  deriving Repr, BEq, Inhabited

structure SubGoalAnalysis where
  subGoal : SubGoalSpec
  contributingNodes : List NodeId
  verificationNodes : List NodeId
  predicateResults : List GraphPredicateResult
  presentInExitFacts : Bool
  deriving Repr, Inhabited

inductive SubGoalCoverageLevel where
  | fullyCovered
  | partiallyCovered
  | weaklyCovered
  | uncovered
  deriving Repr, BEq, DecidableEq, Inhabited

def computeSubGoalCoverageLevel (analysis : SubGoalAnalysis) : SubGoalCoverageLevel :=
  if analysis.contributingNodes.isEmpty then
    .uncovered
  else
    let allRequiredPass := analysis.predicateResults.all fun r =>
      !r.required || r.passed
    let hasPathCoverage := analysis.predicateResults.any fun r =>
      r.predicateKey == GraphLevelPredicateKeys.pathCoverage && r.passed
    if allRequiredPass && analysis.presentInExitFacts then
      .fullyCovered
    else if hasPathCoverage then
      .partiallyCovered
    else
      .weaklyCovered

inductive GraphLevelIssue where
  | uncoveredSubGoal (subGoalName : SubGoalName)
  | requiredPredicateFailed (subGoalName : SubGoalName) (predicateKey : PredicateKey) (description : String)
  | missingFromExitFacts (subGoalName : SubGoalName) (requiredPredicate : PredicateType)
  deriving Repr, Inhabited

inductive GoalCoverageLevel where
  | fullyCovered
  | partiallyCovered
  | insufficientCoverage
  deriving Repr, BEq, DecidableEq, Inhabited

structure GoalCoverageReport where
  goalSpec : GoalSpecification
  subGoalAnalyses : List SubGoalAnalysis
  issues : List GraphLevelIssue
  coverageLevel : GoalCoverageLevel
  semanticSoundness : GraphVerifyResult
  deriving Repr, Inhabited

/-!
## Part 10: Main Analysis Entry Point
-/

def analyzeSubGoal
    (graph : SemanticWorkflowGraph)
    (graphAttrs : ExtractedGraphLevelAttributes)
    (subGoal : SubGoalSpec)
    (exitFacts : List VariablePredicateRequirement)
    (registry : UnifiedPredicateRegistry) : SubGoalAnalysis :=
  let contributingNodes := graphAttrs.contributions
    |>.filter (·.subGoalName == subGoal.name)
    |>.map (·.nodeId)
  let verificationNodes := graphAttrs.verifications
    |>.filter (·.subGoalName == subGoal.name)
    |>.map (·.nodeId)
  let ctx : GraphCheckContext := {
    graph := graph
    subGoalName := subGoal.name
    contributingNodes := contributingNodes
    verificationNodes := verificationNodes
    exitFacts := exitFacts
    registry := registry.varRegistry
  }
  let predicateResults := registry.graphEntries.map fun entry =>
    let passed := entry.check ctx
    -- Informational predicates are never required, even if listed in requiredGraphPredicates
    let required := !entry.informational && subGoal.requiredGraphPredicates.any (· == entry.predicateKey)
    { predicateKey := entry.predicateKey
      shortLabel := entry.shortLabel
      passed := passed
      required := required
      informational := entry.informational : GraphPredicateResult }
  let exitFactsCheck := ExitFactsConfirmedCheck.mk subGoal.variableName subGoal.requiredPredicate
  let inExit := GraphLevelPredicate.check exitFactsCheck ctx
  { subGoal := subGoal
    contributingNodes := contributingNodes
    verificationNodes := verificationNodes
    predicateResults := predicateResults
    presentInExitFacts := inExit }

def collectGraphLevelIssues
    (registry : UnifiedPredicateRegistry)
    (analyses : List SubGoalAnalysis) : List GraphLevelIssue :=
  analyses.flatMap fun a =>
    let issues := #[]
    let issues := if a.contributingNodes.isEmpty then
      issues.push (.uncoveredSubGoal a.subGoal.name)
    else issues
    let issues := a.predicateResults.foldl (fun acc r =>
      if r.required && !r.passed && !a.contributingNodes.isEmpty then
        let desc := match registry.lookupGraph r.predicateKey with
          | some entry => entry.description
          | none => s!"predicate {r.shortLabel}"
        acc.push (.requiredPredicateFailed a.subGoal.name r.predicateKey desc)
      else acc
    ) issues
    let issues := if !a.contributingNodes.isEmpty && !a.presentInExitFacts then
      issues.push (.missingFromExitFacts a.subGoal.name a.subGoal.requiredPredicate)
    else issues
    issues.toList

def computeGoalCoverageLevel (analyses : List SubGoalAnalysis) : GoalCoverageLevel :=
  let coverageLevels := analyses.map computeSubGoalCoverageLevel
  if coverageLevels.all (· == .fullyCovered) then
    .fullyCovered
  else if coverageLevels.all fun l => l == .fullyCovered || l == .partiallyCovered then
    .partiallyCovered
  else
    .insufficientCoverage

def analyzeGoalCoverage
    (graph : SemanticWorkflowGraph)
    (goalSpec : GoalSpecification)
    (registry : UnifiedPredicateRegistry := defaultUnifiedRegistry)
    : GoalCoverageReport :=
  let varRegistry := registry.varRegistry
  let soundness := graph.verify varRegistry

  let exitFacts := match soundness with
    | .success facts => facts
    | _ => []

  let graphAttrs := extractGraphLevelAttributes graph

  let subGoalAnalyses := goalSpec.subGoals.map fun subGoal =>
    analyzeSubGoal graph graphAttrs subGoal exitFacts registry

  let issues := collectGraphLevelIssues registry subGoalAnalyses
  let coverageLevel := computeGoalCoverageLevel subGoalAnalyses

  { goalSpec := goalSpec
    subGoalAnalyses := subGoalAnalyses
    issues := issues
    coverageLevel := coverageLevel
    semanticSoundness := soundness }

/-!
## Part 11: Pretty Printing
-/

def formatSubGoalCoverageLevel : SubGoalCoverageLevel → String
  | .fullyCovered => "FULL"
  | .partiallyCovered => "PARTIAL"
  | .weaklyCovered => "WEAK"
  | .uncovered => "NONE"

def formatGoalCoverageLevel : GoalCoverageLevel → String
  | .fullyCovered => "All Sub-Goals Fully Covered"
  | .partiallyCovered => "Partially Covered (some checks missing)"
  | .insufficientCoverage => "Insufficient Coverage"

def formatGraphLevelIssue : GraphLevelIssue → String
  | .uncoveredSubGoal name =>
    s!"UNCOVERED: Sub-goal '{name.val}' has no contributing nodes"
  | .requiredPredicateFailed name _ desc =>
    s!"FAILED: Sub-goal '{name.val}': {desc}"
  | .missingFromExitFacts name _ =>
    s!"NOT IN EXIT FACTS: Sub-goal '{name.val}' predicate not confirmed by Hoare-logic verification"

/-- Format a single predicate result.
    [+X] = required & pass,  [-X] = required & FAIL
    [~X] = optional & pass,  [.X] = optional & skip (hidden in report)
    [!X] = informational & FAIL (displayed but does not affect coverage) -/
def formatPredicateResult (r : GraphPredicateResult) : String :=
  if r.informational then
    if r.passed then s!"[~{r.shortLabel}]" else s!"[!{r.shortLabel}]"
  else if r.required then
    if r.passed then s!"[+{r.shortLabel}]" else s!"[-{r.shortLabel}]"
  else
    if r.passed then s!"[~{r.shortLabel}]" else s!"[.{r.shortLabel}]"

def formatSubGoalAnalysis (a : SubGoalAnalysis) : String :=
  let level := computeSubGoalCoverageLevel a
  let exitRes : GraphPredicateResult := {
    predicateKey := GraphLevelPredicateKeys.exitFactsConfirmed
    shortLabel := "exit_facts"
    passed := a.presentInExitFacts
    required := true
  }
  let allResults := a.predicateResults ++ [exitRes]
  -- Satisfied: all passed predicates (required [+], optional/informational [~])
  let satisfied := allResults.filter (·.passed) |>.map formatPredicateResult |> String.intercalate " "
  -- Failed: required fails [-] and informational fails [!]. Hide optional fails [.]
  let failed := allResults.filter (fun r => !r.passed && (r.required || r.informational))
    |>.map formatPredicateResult |> String.intercalate " "
  let line1 := s!"  {a.subGoal.name.val}: {formatSubGoalCoverageLevel level}"
  let line2 := s!"    Satisfied: {if satisfied.isEmpty then "(none)" else satisfied}"
  let line3 := s!"    Failed:    {if failed.isEmpty then "(none)" else failed}"
  s!"{line1}\n{line2}\n{line3}"

def formatGoalCoverageReport (report : GoalCoverageReport) : String :=
  let soundnessStr := match report.semanticSoundness with
    | .success _ => "Semantically Sound"
    | _ => "Semantic Issues Detected"

  let subGoalStr := report.subGoalAnalyses.map formatSubGoalAnalysis
    |> String.intercalate "\n"

  let issuesStr := if report.issues.isEmpty
    then "  None"
    else report.issues.map (fun i => s!"  - {formatGraphLevelIssue i}") |> String.intercalate "\n"

  let totalSubGoals := report.goalSpec.subGoals.length
  let fullyCovered := report.subGoalAnalyses.filter
    (fun a => computeSubGoalCoverageLevel a == .fullyCovered) |>.length
  let partiallyCovered := report.subGoalAnalyses.filter
    (fun a => computeSubGoalCoverageLevel a == .partiallyCovered) |>.length
  let uncovered := report.subGoalAnalyses.filter
    (fun a => computeSubGoalCoverageLevel a == .uncovered) |>.length

  s!"
═══════════════════════════════════════════════════
GOAL COVERAGE REPORT (Graph-Level Analysis v2)
═══════════════════════════════════════════════════

Goal: {report.goalSpec.originalGoal}
Semantic Soundness: {soundnessStr}

Legend: [+X]=required & pass  [-X]=required & FAIL  [~X]=optional/info & pass  [!X]=info & FAIL (not counted)

Sub-Goal Coverage ({fullyCovered}/{totalSubGoals} fully covered):
{subGoalStr}

Coverage Summary:
  - Fully covered:    {fullyCovered}
  - Partially covered: {partiallyCovered}
  - Uncovered:         {uncovered}
  - Overall: {formatGoalCoverageLevel report.coverageLevel}

Graph-Level Issues:
{issuesStr}
═══════════════════════════════════════════════════"

end AgenticKernel
