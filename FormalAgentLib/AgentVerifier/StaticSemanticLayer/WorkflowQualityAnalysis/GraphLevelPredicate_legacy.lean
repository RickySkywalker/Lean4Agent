import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.SemanticGraph
import AgentVerifier.StaticSemanticLayer.SemanticVerification
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.ExtensiblePredicate
import AgentVerifier.StaticSemanticLayer.WorkflowQualityAnalysis.GraphLevelPredicates

namespace AgenticKernel

/-!
# Graph-Level Predicates — LEGACY information machinery

⚠️ This file holds the **deprecated** information system that used to live in
`GraphLevelPredicates.lean`. It was superseded by the context-visibility–aware
`InformationSystem.lean` (the three-predicate system + `verifyInformationFlow`).

It is kept ONLY for backward compatibility with Layer-3
(`DynamicVerification/DynamicGraphLevelVerification.lean`), which still ports
`extractAspectFromKey`, `ContextContinuityCheck`, and `InformationSufficiencyCheck`.
Layer-3 reaches these symbols because the umbrella module
`StaticSemanticLayer.lean` imports this file.

Do NOT use any of this in new Layer-2 plans:
  * information content   → declare it in an `InformationFlowSpec` (InformationSystem.lean)
  * information judgment   → `verifyInformationFlow` / `isInformationFlowSoundBool`

None of these definitions are registered in `defaultUnifiedRegistry`; they never
participate in the active Layer-2 graph-predicate judgment.

This file depends on `GraphLevelPredicates.lean` for the active infrastructure it
reuses (`GraphLevelPredicate` type class, `GraphLevelPredicateKeys`,
`computeContextVisibility` / `ContextVisibility`, `isSentinelPredicate`).
-/

/-!
## LEGACY Part 1: Information Content System (aspect-on-a-variable)

This modelled information as an ordinary `VariablePredicateRequirement` that rode
the Hoare pre/post-condition chain (`markInfoContent "var" "aspect"`). That
conflated *variable-level* information (real `save_as` variables) with
*context-level* information (conversation-history facts), and the chain is
step/task-blind — exactly the unfaithfulness the redesign removed.
-/

namespace InfoContentKeys
  def family : String := "info_content"

  /-- This variable contains information about a specific named aspect.
      Uses PredicateKey.withParam for structural matching — no string parsing. -/
  def coversAspect (aspect : String) : PredicateKey :=
    .withParam family "coversAspect" aspect
end InfoContentKeys

/-- ExtendedPredicate for information content aspects -/
structure InfoContentPred where
  aspect : String
  deriving Repr, BEq, Inhabited

instance : ExtendedPredicate InfoContentPred where
  toKey p := InfoContentKeys.coversAspect p.aspect
  toProp _ env varName := nameExists env varName
  checkProp _ env varName := nameExistsBool env varName
  impliedKeys _ := [StdPredicateKeys.nameExists]

/-- Extract the aspect name from a PredicateKey, if it is a coversAspect key.
    Uses structural matching on PredicateKey — no string parsing.
    (Still consumed by Layer-3's `substringAspectFallback` / `requiredAspectsOf`.) -/
def extractAspectFromKey (key : PredicateKey) : Option String :=
  match key with
  | .makePredicateKey family name args =>
    if family == InfoContentKeys.family && name == "coversAspect" then
      match args with
      | [.argStr aspect] => some aspect
      | _ => none
    else none

/-- Check if a PredicateType is an info content predicate -/
def isInfoContentPredicate (pred : PredicateType) : Bool :=
  match pred with
  | .ext key => (extractAspectFromKey key).isSome
  | _ => false

/-- ⚠️ DEPRECATED (Layer-2): do not use in new plans. This makes information an
    ordinary `VariablePredicateRequirement` on the Hoare chain, which is exactly the
    conflation the redesign removes. Declare information in an `InformationFlowSpec`
    (see `InformationSystem.lean`) instead. Kept only so legacy example files that
    still call it continue to elaborate. -/
def markInfoContent (varName : String) (aspect : String) : VariablePredicateRequirement :=
  ⟨varName, .ext (InfoContentKeys.coversAspect aspect)⟩

/-!
## LEGACY 6c. Context Continuity

⚠️ No longer registered in `defaultUnifiedRegistry`. Superseded by the
context-information verification in `InformationSystem.lean`
(`readableContextInfo` / `verifyNodeInformationFlow`). Retained only because
`DynamicGraphLevelVerification.lean` (Layer-3) ports its `check` via
`GraphLevelPredicate.check ContextContinuityCheck.mk`.
-/

structure ContextContinuityCheck where deriving Repr, BEq, Inhabited

/-- Check if a precondition requirement is satisfied by the node's context.

    For task nodes with a task chain: check if any predecessor in the chain
    has a matching postcondition.

    For step nodes: check if the variable is injected via save_as AND the
    producer has a matching postcondition. -/
def isPrecondSatisfiedByContext
    (graph : SemanticWorkflowGraph)
    (vis : ContextVisibility)
    (req : VariablePredicateRequirement) : Bool :=
  -- Step nodes (stateful, new-engine semantics) with conversation history: predecessors in the chain provide context
  if vis.stepType == .step && !vis.taskChain.isEmpty then
    -- Check if any conversation-history-chain predecessor has this predicate in postcond
    vis.taskChain.any fun predId =>
      match graph.findSemanticNode predId with
      | none => false
      | some predNode =>
        predNode.postcondVariables.any fun fact =>
          fact.satisfies req
  else
    -- Step node (or isolated task): only injected variables available
    vis.injectedVars.any fun (varName, producerId) =>
      if varName == req.varName then
        match graph.findSemanticNode producerId with
        | none => false
        | some prodNode =>
          prodNode.postcondVariables.any fun fact =>
            fact.satisfies req
      else false

instance : GraphLevelPredicate ContextContinuityCheck where
  toKey _ := GraphLevelPredicateKeys.contextContinuity
  check _ ctx :=
    ctx.contributingNodes.all fun nodeId =>
      match ctx.graph.findSemanticNode nodeId with
      | none => false
      | some node =>
        let vis := computeContextVisibility ctx.graph nodeId
        -- Check all non-sentinel, non-tool preconditions
        node.precondVariables.all fun req =>
          isSentinelPredicate req.requiredPredicate ||
          -- Tool requirements are satisfied by environment, not context flow
          req.requiredPredicate == .toolExists ||
          -- Parameters are always available
          ctx.graph.parameters.any (fun p => p.name == req.varName) ||
          -- Check if context provides this
          isPrecondSatisfiedByContext ctx.graph vis req
  describe _ := "Each contributing node's information needs are satisfied by its execution context"
  shortLabel _ := "ctx_cont"

/-!
## LEGACY 6d. Information Sufficiency

⚠️ No longer registered in `defaultUnifiedRegistry`. Superseded by the
variable-information verification in `InformationSystem.lean`
(`readableVariableInfo` / `verifyNodeInformationFlow`). Retained only because
`DynamicGraphLevelVerification.lean` (Layer-3) ports its `check` via
`GraphLevelPredicate.check InformationSufficiencyCheck.mk`.
-/

structure InformationSufficiencyCheck where deriving Repr, BEq, Inhabited

/-- For step nodes receiving save_as variables: check if the injected variables
    carry the specific information aspects that the node needs.

    Extracts coversAspect requirements from preconditions and verifies that
    the producing node's postconditions include matching aspects. -/
instance : GraphLevelPredicate InformationSufficiencyCheck where
  toKey _ := GraphLevelPredicateKeys.informationSufficiency
  check _ ctx :=
    ctx.contributingNodes.all fun nodeId =>
      match ctx.graph.findSemanticNode nodeId with
      | none => false
      | some node =>
        let vis := computeContextVisibility ctx.graph nodeId
        -- For step nodes (stateful, new-engine semantics) with conversation history: trivially satisfied
        if vis.stepType == .step && !vis.taskChain.isEmpty then true
        else
          -- For task nodes (stateless): check each info content precondition
          let infoReqs := node.precondVariables.filter fun req =>
            isInfoContentPredicate req.requiredPredicate
          infoReqs.all fun req =>
            -- Parameters don't need aspect checking
            ctx.graph.parameters.any (fun p => p.name == req.varName) ||
            -- Check if the producer of this variable has the matching aspect
            vis.injectedVars.any fun (varName, producerId) =>
              if varName == req.varName then
                match ctx.graph.findSemanticNode producerId with
                | none => false
                | some prodNode =>
                  prodNode.postcondVariables.any fun fact =>
                    fact.satisfies req
              else false
  describe _ := "Injected variables carry the specific information aspects the consuming node needs"
  shortLabel _ := "info_suff"

end AgenticKernel
