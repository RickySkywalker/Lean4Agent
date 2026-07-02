import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
import AgentVerifier.DynamicVerification.Basics.DynamicVariablePredicate
import AgentVerifier.DynamicVerification.Basics.DynamicGraphPredicate

/-!
# Section 4 — The Dynamic Verification Graph (the system that places the 3 channels)

The runtime graph container — the dynamic-layer analogue of Layer-2's
`SemanticWorkflowGraph` — together with the variable channel's per-node
verification and the **human-written soundness proof chain** that discharges the
Layer-2 `llmExecAxiom`. This file is §4 of the dynamic layer; it imports the
three Basics channels (§1 variable, §3 graph-predicate; §2 information is folded
in by §5) and provides the runtime graph + the graph-check-context builder that
ties the graph channel to the executed trace.

Ported from the original
`AgentVerifier/DynamicVerification/DynamicVerificationGraph.lean`, re-homed under
`namespace AgenticKernel.Dyn`. The §13 soundness block is preserved **verbatim**
(the only edits: namespace, and one dot-notation call `predType.verificationMethod`
→ qualified `PredicateType.verificationMethod predType` since `verificationMethod`
is a `Dyn` extension of the static `PredicateType`, not dot-resolvable). The
three trust axioms are the **established** Layer-3 trust assumptions
(`jsonValueMatchesWithSchema_implies_JsonMatchesSchema`, `trustExternalVerification`,
`trustLLMVerification`) — re-homed, **not new** trust: they are exactly the axioms
the original soundness proof already depends on, and nothing here adds others.
-/

namespace AgenticKernel
namespace Dyn


/-!
## §4.1 — Dynamic Verification Graph in execution (the runtime container)

(Original "Section 11".) The runtime graph: a `SemanticWorkflowGraph` plus the
per-node §1 specs that record the trace outcome. This is the value all three
channels read off (variable here, information via §2, graph via §3).
-/
structure DynamicVerificationGraph where
  semanticWorkflowGraph : SemanticWorkflowGraph
  dynamicNodeSpecs : List DynamicNodeSpec := []
  conditionalNodeSpecs : List DynamicConditionalNodeSpec := []
  loopNodeSpecs : List DynamicLoopNodeSpec := []
  initialExecutionState : NodeExecutionState

/-!
## §4.2 — Dynamic graph verification (variable channel, graph level)

(Original "Section 12".)
-/

inductive DynamicNodeExecutionVerifyStatus where
  | verified
  | precondFailed (f : List PredicateVerificationEntry)
  | postcondFailed (f : List PredicateVerificationEntry)
  | pending (p : List PredicateVerificationEntry)
  | skipped
  deriving Repr, Inhabited

def getNodeVerifyStatus
  (spec : DynamicNodeSpec) : DynamicNodeExecutionVerifyStatus :=
  if spec.executionStatus == .skipped then .skipped
  else
    let failedPreconds := spec.failedPreconditions
    let failedPostconds := spec.failedPostconditions
    if not failedPreconds.isEmpty then .precondFailed failedPreconds
    else if not failedPostconds.isEmpty then .postcondFailed failedPostconds
    else if spec.hasPending then
      .pending (spec.precondVerificationEntries.filter (·.isPending) ++ spec.postcondVerificationEntries.filter (·.isPending))
    else .verified

/-- The type system for DynamicVerificationGraph's verify result -/
inductive DynamicVerificationGraphVerifyResult where
  | allVerified
  -- The string in here is the node name of the problematic node, and the failed predicates for that node
  | someNodesFailed (failedNodes : List (NodeId × String × DynamicNodeExecutionVerifyStatus))
  | hasPending (pendingNodes : List (NodeId × String))
  | structuralMismatch (reason : String)
  deriving Repr, Inhabited

/-- Verify the dynamic verification graph -/
def DynamicVerificationGraph.verify
  (graph : DynamicVerificationGraph) : DynamicVerificationGraphVerifyResult :=
  let statuses := graph.dynamicNodeSpecs.map fun spec => (spec, getNodeVerifyStatus spec)

  let failureNodes := statuses.filterMap fun (spec, status) =>
    match status with
    | .verified | .skipped => none
    | _ => some (spec.id, spec.trajectoryStepName, status)

  let pendingNodes := statuses.filterMap fun (spec, status) =>
    match status with
    | .pending _ => some (spec.id, spec.trajectoryStepName)
    | _ => none

  if failureNodes.isEmpty && pendingNodes.isEmpty then .allVerified
  else
    let trueFailures := failureNodes.filter fun (_, _, status) =>
      match status with
      | .pending _ => false
      | _ => true
    if not trueFailures.isEmpty then .someNodesFailed trueFailures
    else .hasPending pendingNodes

/-- The bool version of verification results -/
def DynamicVerificationGraph.isVerifiedBool
  (graph : DynamicVerificationGraph) : Bool :=
  match graph.verify with
  | .allVerified => true
  | _ => false


/-!
## §4.3 — Soundness theorems (PRESERVED VERBATIM — human-written)

(Original "Section 13".) These discharge the Layer-2 `llmExecAxiom`: when the
dynamic layer verifies every postcondition, the Layer-2 assumption that "the LLM
executes the node correctly" is proven for that run.
-/

/-!
### §4.3.1 — Axioms for the soundness proof

The three **established** trust axioms (re-homed from the original; not new trust).
-/

/-- Bridge axiom: Bool checker implies inductive Prop for JSON schema matching. -/
axiom jsonValueMatchesWithSchema_implies_JsonMatchesSchema
  (j : JsonValue) (s : JsonSchema)
  (h : jsonValueMatchesWithSchema j s = true) : JsonMatchesSchema j s

/-- The Axiom declares that we trust external tool verification -/
axiom trustExternalVerification
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (externalToolJudgementResult : ExternalToolJudgementResult) :
  predType.toProp semanticEnv varName

/-- The Axiom declares that we trust the LLM verification -/
axiom trustLLMVerification
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (llmJudgementResult : LLMJudgementResult) :
  predType.toProp semanticEnv varName

/-- Soundness of checkBool: if checkBool returns true, then toProp holds.
    Proven by well-founded recursion on PredicateType structure. -/
theorem checkBool_soundness
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (h : predType.checkBool semanticEnv varName = true) :
  predType.toProp semanticEnv varName := by
  match predType with
  | .nameExists =>
    simp only [PredicateType.toProp, PredicateType.checkBool, nameExists, nameExistsBool] at *
    exact h
  | .isNonEmptyString =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isNonEmptyString, isNonEmptyStringBool] at *
    split at h <;> simp_all
  | .isNonEmptyList =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isNonEmptyList, isNonEmptyListBool] at *
    split at h <;> simp_all
  | .isInt =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isInt, isIntBool] at *
    split at h <;> simp_all
  | .isValidURL =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidURL, isValidURLBool] at *
    split at h <;> simp_all
  | .isValidFilePath =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidFilePath, isValidFilePathBool] at *
    split at h <;> simp_all
  | .isValidPath =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidPath, isValidPathBool] at *
    split at h <;> simp_all
  | .isValidBibtex =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidBibtex, isValidBibtexBool] at *
    split at h <;> simp_all
  | .isValidLatex =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidLatex, isValidLatexBool] at *
    split at h <;> simp_all
  | .isValidJson =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidJson, isValidJsonBool] at *
    exact h
  | .isValidList =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isValidList, isValidListBool] at *
    split at h <;> simp_all
  | .toolExists =>
    simp only [PredicateType.toProp, PredicateType.checkBool, toolExists, toolExistsBool] at *
    exact h
  | .moduleExists =>
    simp only [PredicateType.toProp, PredicateType.checkBool, moduleExists, moduleExistsBool] at *
    exact h
  | .matchesJsonSchema schema =>
    simp only [PredicateType.toProp, PredicateType.checkBool, matchesJsonSchemaBool] at *
    simp only [matchesJsonSchemaBool, SemanticEnv.get] at h
    split at h
    · rename_i j hEq
      simp only [SemanticEnv.get, hEq]
      exact ⟨j, rfl, jsonValueMatchesWithSchema_implies_JsonMatchesSchema j schema h⟩
    · simp_all
  | .isJsonWithFields fields =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isJsonWithSchema, isJsonWithSchemaBool] at *
    exact h
  | .containsSubstring substring =>
    simp only [PredicateType.toProp, PredicateType.checkBool, hasSubstring, hasSubstringBool] at *
    split at h <;> simp_all
  | .fileExistsAtPath =>
    simp only [PredicateType.toProp, PredicateType.checkBool, isNonEmptyString, isNonEmptyStringBool] at *
    split at h <;> simp_all
  | .taskCompleted =>
    simp only [PredicateType.toProp, PredicateType.checkBool, nameExists, nameExistsBool] at *
    exact h
  | .custom _ =>
    simp only [PredicateType.toProp, PredicateType.checkBool, nameExists, nameExistsBool] at *
    exact h
  | .ext _ =>
    simp only [PredicateType.toProp, PredicateType.checkBool, nameExists, nameExistsBool] at *
    exact h
  | .predicateAnd p₁ p₂ =>
    simp only [PredicateType.toProp, PredicateType.checkBool, Bool.and_eq_true] at *
    exact ⟨checkBool_soundness p₁ semanticEnv varName h.1, checkBool_soundness p₂ semanticEnv varName h.2⟩
  | .predicateOr p₁ p₂ =>
    simp only [PredicateType.toProp, PredicateType.checkBool, Bool.or_eq_true] at *
    cases h with
    | inl h₁ => exact Or.inl (checkBool_soundness p₁ semanticEnv varName h₁)
    | inr h₂ => exact Or.inr (checkBool_soundness p₂ semanticEnv varName h₂)
termination_by sizeOf predType

/--
Check the soundness of the symbolic Lean verification results in the dynamic verification field. In here, for simplicity, we assume no registry used in here.
-/
lemma soundnessOfLeanSymbolicVerification
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (h : leanSymbolicPredicateVerification predType semanticEnv varName .empty false = .leanSymbolicVerificationPass) :
  predType.toProp semanticEnv varName := by
  unfold leanSymbolicPredicateVerification at h
  match hGet : semanticEnv.get varName with
  | none =>
    simp [hGet] at h
    cases predType <;> simp_all [PredicateType.verificationMethod, VerificationRegistry.empty]
  | some val =>
    simp only [SemanticEnv.get] at hGet  -- hGet now becomes: semanticEnv varName = some val
    simp only [SemanticEnv.get, hGet] at h
    cases predType with
    -- ════════════════════════════════════════════
    -- Contradiction cases: verificationMethod never returns .leanSymbolicVerification
    -- The hypothesis h asserts .pendingVerification = .leanSymbolicVerificationPass
    -- which is a contradiction
    -- ════════════════════════════════════════════
    | toolExists | moduleExists | fileExistsAtPath | custom _ =>
      simp only [PredicateType.verificationMethod] at h; cases h
    | ext key =>
      simp only [PredicateType.verificationMethod, VerificationRegistry.empty,
            VerificationRegistry.getMethod, VerificationRegistry.lookup] at h
      simp at h
    -- ════════════════════════════════════════════
    -- Direct cases: checkBool = Bool predicate directly equals toProp
    -- ════════════════════════════════════════════
    | nameExists | taskCompleted =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, nameExists, nameExistsBool, SemanticEnv.get, hGet]; rfl
    | isNonEmptyString =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isNonEmptyString, isNonEmptyStringBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isNonEmptyStringBool]
    | isNonEmptyList =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isNonEmptyList, isNonEmptyListBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isNonEmptyListBool]
    | isValidList =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidList, isValidListBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidListBool]
    | isInt =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isInt, isIntBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isIntBool]
    | containsSubstring sub =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, hasSubstring, hasSubstringBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, hasSubstringBool]
    -- ════════════════════════════════════════════
    -- Cases with preferExternal=false: use Lean symbolic verification
    -- ════════════════════════════════════════════
    | isValidURL =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidURL, isValidURLBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidURLBool]
    | isValidFilePath =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidFilePath, isValidFilePathBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidFilePathBool]
    | isValidPath =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidPath, isValidPathBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidPathBool]
    | isValidBibtex =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidBibtex, isValidBibtexBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidBibtexBool]
    | isValidLatex =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidLatex, isValidLatexBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidLatexBool]
    -- ════════════════════════════════════════════
    -- Cases with Bool-based toProp (checkBool = true → toProp directly)
    -- ════════════════════════════════════════════
    | isValidJson =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isValidJson, isValidJsonBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isValidJsonBool]
    | isJsonWithFields fields =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp, isJsonWithSchema, isJsonWithSchemaBool, SemanticEnv.get, hGet]
      split at h <;> simp_all [PredicateType.checkBool, isJsonWithSchemaBool]
    -- ════════════════════════════════════════════
    -- matchesJsonSchema: requires bridge theorem Bool → inductive Prop
    -- jsonValueMatchesWithSchema = true → JsonMatchesSchema
    -- ════════════════════════════════════════════
    | matchesJsonSchema schema =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp]
      -- checkBool passes, so matchesJsonSchemaBool semanticEnv varName schema = true
      simp only [PredicateType.checkBool, matchesJsonSchemaBool, SemanticEnv.get, hGet] at h
      -- Need to case split on val to extract the JsonValue
      cases val with
      | vJson j =>
        simp only [SemanticEnv.get, hGet]
        -- Simplify the match to get jsonValueMatchesWithSchema condition
        simp only [decide_eq_true_eq] at h
        -- Extract the Bool condition from the if
        by_cases hMatch : jsonValueMatchesWithSchema j schema = true
        · exact ⟨j, rfl, jsonValueMatchesWithSchema_implies_JsonMatchesSchema j schema hMatch⟩
        · simp [hMatch] at h  -- contradiction
      | _ => simp_all  -- other Value variants lead to contradiction
    -- ════════════════════════════════════════════
    -- Recursive cases: predicateAnd and predicateOr
    -- Uses checkBool_soundness axiom for recursive subpredicates
    -- ════════════════════════════════════════════
    | predicateAnd p₁ p₂ =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp]
      simp only [PredicateType.checkBool] at h
      -- h now contains: if (p₁.checkBool && p₂.checkBool) = true then pass else fail
      by_cases hCheck : (p₁.checkBool semanticEnv varName && p₂.checkBool semanticEnv varName) = true
      · simp only [Bool.and_eq_true] at hCheck
        constructor
        · exact checkBool_soundness p₁ semanticEnv varName hCheck.1
        · exact checkBool_soundness p₂ semanticEnv varName hCheck.2
      · simp [hCheck] at h  -- contradiction: verification passed but checkBool failed
    | predicateOr p₁ p₂ =>
      simp only [PredicateType.verificationMethod] at h
      simp only [PredicateType.toProp]
      simp only [PredicateType.checkBool] at h
      -- h now contains: if (p₁.checkBool || p₂.checkBool) = true then pass else fail
      by_cases hCheck : (p₁.checkBool semanticEnv varName || p₂.checkBool semanticEnv varName) = true
      · simp only [Bool.or_eq_true] at hCheck
        cases hCheck with
        | inl h₁ => exact Or.inl (checkBool_soundness p₁ semanticEnv varName h₁)
        | inr h₂ => exact Or.inr (checkBool_soundness p₂ semanticEnv varName h₂)
      · simp [hCheck] at h  -- contradiction

/-- If the predicate has runtime check with passed = true, and we have provenance evidence
    for Lean symbolic verification, then the predicate's corresponding Lean proposition holds.
    The hLeanSource parameter provides evidence that for the leanSymbolicVerificationPass case,
    the result indeed came from a valid verification call. -/
theorem verificationResultsImpliesProp
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (dynamicPredicateVerificationResult : DynamicPredicateVerificationResult)
  (hPassed : dynamicPredicateVerificationResult.passed = true)
  (hLeanSource : dynamicPredicateVerificationResult = .leanSymbolicVerificationPass →
                 leanSymbolicPredicateVerification predType semanticEnv varName .empty false = .leanSymbolicVerificationPass) :
  predType.toProp semanticEnv varName
:= by
  cases dynamicPredicateVerificationResult with
  | leanSymbolicVerificationPass =>
    exact soundnessOfLeanSymbolicVerification predType semanticEnv varName (hLeanSource rfl)
  | externalToolVerificationPass result =>
    exact trustExternalVerification predType semanticEnv varName result
  | llmJudgeVerificationPass judgement =>
    exact trustLLMVerification predType semanticEnv varName judgement
  | leanSymbolicVerificationFail reason =>
    simp [DynamicPredicateVerificationResult.passed] at hPassed
  | externalToolVerificationFail result =>
    simp [DynamicPredicateVerificationResult.passed] at hPassed
  | llmJudgeVerificationFail judgement =>
    simp [DynamicPredicateVerificationResult.passed] at hPassed
  | pendingVerification method =>
    simp [DynamicPredicateVerificationResult.passed] at hPassed
  | variableNotFound =>
    simp [DynamicPredicateVerificationResult.passed] at hPassed

/-- Runtime verification pass for a variable requirement implies
    its corresponding semantic proposition holds in the post environment. -/
lemma verifyPredicate_noExternalResults_simp
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String) :
  verifyPredicate predType semanticEnv varName [] .empty true =
    match leanSymbolicPredicateVerification predType semanticEnv varName .empty true with
    | .pendingVerification method => .pendingVerification method
    | other => other := by
  unfold verifyPredicate
  cases hLean : leanSymbolicPredicateVerification predType semanticEnv varName .empty true <;>
    simp [hLean, findExternalVerificationResult, resolvePendingVerificationResult]

lemma verifyPredicate_leanPass_implies_leanSymbolicPass_true
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (h : verifyPredicate predType semanticEnv varName [] .empty true = .leanSymbolicVerificationPass) :
  leanSymbolicPredicateVerification predType semanticEnv varName .empty true = .leanSymbolicVerificationPass := by
  unfold verifyPredicate at h
  cases hLean : leanSymbolicPredicateVerification predType semanticEnv varName .empty true with
  | pendingVerification method =>
    simp [hLean, findExternalVerificationResult, resolvePendingVerificationResult] at h
  | leanSymbolicVerificationPass =>
    simp [hLean] at h
    rfl
  | leanSymbolicVerificationFail reason =>
    simp [hLean] at h
  | externalToolVerificationPass result =>
    simp [hLean] at h
  | externalToolVerificationFail result =>
    simp [hLean] at h
  | llmJudgeVerificationPass judgement =>
    simp [hLean] at h
  | llmJudgeVerificationFail judgement =>
    simp [hLean] at h
  | variableNotFound =>
    simp [hLean] at h

lemma soundnessOfLeanSymbolicVerification_preferExternalTrue
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (h : leanSymbolicPredicateVerification predType semanticEnv varName .empty true = .leanSymbolicVerificationPass) :
  predType.toProp semanticEnv varName := by
  unfold leanSymbolicPredicateVerification at h
  simp only [SemanticEnv.get] at h
  match hGet : semanticEnv.get varName with
  | none =>
    simp only [SemanticEnv.get] at hGet
    have : False := by
      cases predType <;> simp [hGet] at h
    exact False.elim this
  | some _ =>
    simp only [SemanticEnv.get] at hGet
    cases hm : PredicateType.verificationMethod predType .empty true with
    | externalToolVerification toolName =>
      simp [hGet, hm] at h
    | llmJudgeVerification =>
      simp [hGet, hm] at h
    | leanSymbolicVerification =>
      have hCheck : predType.checkBool semanticEnv varName = true := by
        simpa [hGet, hm] using h
      exact checkBool_soundness predType semanticEnv varName hCheck


lemma verifyVariablePredicatePassedImpliesToProp
  (requirements : VariablePredicateRequirement)
  (postExecSemanticEnv : SemanticEnv)
  (hPassed : (verifyVariablePredicate requirements postExecSemanticEnv).passed = true) :
  requirements.toProp postExecSemanticEnv := by
  cases hRes : verifyVariablePredicate requirements postExecSemanticEnv with
  | leanSymbolicVerificationPass =>
    have hVerifyLean :
      verifyPredicate requirements.requiredPredicate postExecSemanticEnv requirements.varName [] .empty true =
        .leanSymbolicVerificationPass := by
      simpa [verifyVariablePredicate] using hRes
    have hLeanPass :
      leanSymbolicPredicateVerification requirements.requiredPredicate postExecSemanticEnv requirements.varName .empty true =
        .leanSymbolicVerificationPass :=
      verifyPredicate_leanPass_implies_leanSymbolicPass_true
        requirements.requiredPredicate
        postExecSemanticEnv
        requirements.varName
        hVerifyLean
    have hProp : requirements.requiredPredicate.toProp postExecSemanticEnv requirements.varName :=
      soundnessOfLeanSymbolicVerification_preferExternalTrue
        requirements.requiredPredicate
        postExecSemanticEnv
        requirements.varName
        hLeanPass
    simpa [VariablePredicateRequirement.toProp] using hProp
  | externalToolVerificationPass result =>
    have hProp : requirements.requiredPredicate.toProp postExecSemanticEnv requirements.varName :=
      trustExternalVerification requirements.requiredPredicate postExecSemanticEnv requirements.varName result
    simpa [VariablePredicateRequirement.toProp] using hProp
  | llmJudgeVerificationPass judgement =>
    have hProp : requirements.requiredPredicate.toProp postExecSemanticEnv requirements.varName :=
      trustLLMVerification requirements.requiredPredicate postExecSemanticEnv requirements.varName judgement
    simpa [VariablePredicateRequirement.toProp] using hProp
  | leanSymbolicVerificationFail reason =>
    simp [DynamicPredicateVerificationResult.passed, hRes] at hPassed
  | externalToolVerificationFail result =>
    simp [DynamicPredicateVerificationResult.passed, hRes] at hPassed
  | llmJudgeVerificationFail judgement =>
    simp [DynamicPredicateVerificationResult.passed, hRes] at hPassed
  | pendingVerification method =>
    simp [DynamicPredicateVerificationResult.passed, hRes] at hPassed
  | variableNotFound =>
    simp [DynamicPredicateVerificationResult.passed, hRes] at hPassed

/-- When in dynamic verification layer, we identify that all verification is passed, then it indicates that our main assumptions in Layer 2, which is the LLM executes correctly, is true. This theorem discharges the axiom in Layer 2 -/
theorem dynamicLayerDischargesStaticSemanticAxiom
  (semanticWorkflowNode : SemanticWorkflowNode)
  (preExecSemanticEnv postExecSemanticEnv : SemanticEnv)
  (hPrecond : semanticWorkflowNode.precond preExecSemanticEnv)
  (hPostcondIsDefault :
    semanticWorkflowNode.postcond =
      (fun _ env' => ∀ requirements ∈ semanticWorkflowNode.postcondVariables, requirements.toProp env'))
  (hAllDynamicVerificationPass :
    ∀ requirements ∈ semanticWorkflowNode.postcondVariables, (verifyVariablePredicate requirements postExecSemanticEnv).passed = true) :
  semanticWorkflowNode.postcond preExecSemanticEnv postExecSemanticEnv := by
  have _ := hPrecond
  rw [hPostcondIsDefault]
  intro requirements hInPost
  have hPassed : (verifyVariablePredicate requirements postExecSemanticEnv).passed = true :=
    hAllDynamicVerificationPass requirements hInPost
  exact verifyVariablePredicatePassedImpliesToProp requirements postExecSemanticEnv hPassed


/-!
## §4.4 — Building a graph-check context from the runtime graph

The container-aware helpers that the §3 graph channel needs but that depend on
`DynamicVerificationGraph` (so they live here, not in Basics). These turn a
runtime graph + trace into the `DynamicGraphCheckContext` the §3 predicates read.
-/

/-- Final execution state derived from the dynamic graph (post-execution state of
    the last completed node, or the initial state if none). -/
def finalExecStateOf (dynGraph : DynamicVerificationGraph) : NodeExecutionState :=
  let completed := dynGraph.dynamicNodeSpecs.filter
    (·.executionStatus == ExecutionStatus.completed)
  match completed.getLast? with
  | some s => s.postExecutionState
  | none   => dynGraph.initialExecutionState

/-- Build a `DynamicGraphCheckContext` for a single sub-goal. Accepts an optional
    `stepIdMap` override — necessary when the agent's runtime step ids don't
    coincide with `toString nodeId.val`. -/
def buildGraphCheckContext
    (dynGraph : DynamicVerificationGraph)
    (trace : ExecutionTrace)
    (subGoalName : SubGoalName)
    (contributingNodes verificationNodes : List NodeId)
    (exitFacts : List VariablePredicateRequirement := [])
    (registry : PredicateRegistry := PredicateRegistry.empty)
    (stepIdMap : StepIdMap := StepIdMap.fromGraph dynGraph.semanticWorkflowGraph)
    : DynamicGraphCheckContext :=
  let graph := dynGraph.semanticWorkflowGraph
  let executed := executedCompletedNodes trace stepIdMap graph
  { graph := graph
    subGoalName := subGoalName
    contributingNodes := contributingNodes
    verificationNodes := verificationNodes
    exitFacts := exitFacts
    registry := registry
    trace := trace
    stepIdMap := stepIdMap
    executedContributingNodes := contributingNodes.filter (executed.contains ·)
    executedVerificationNodes := verificationNodes.filter (executed.contains ·)
    finalExecState := finalExecStateOf dynGraph }


/-!
## §4.5 — Result formatting

(Original "Section 14".)
-/

def DynamicPredicateVerificationResult.describe : DynamicPredicateVerificationResult → String
  | .leanSymbolicVerificationPass => "✓ PASS [formal/lean]"
  | .leanSymbolicVerificationFail reason => s!"✗ FAIL [formal/lean]: {reason}"
  | .externalToolVerificationPass verifyResult => s!"✓ PASS [tool/{verifyResult.toolName}]: {verifyResult.additionalInfo}"
  | .externalToolVerificationFail verifyResult => s!"✗ FAIL [tool/{verifyResult.toolName}]: {verifyResult.additionalInfo}"
  | .llmJudgeVerificationPass judgement => s!"✓ PASS [llm-judge] (conf={judgement.confidence}): {judgement.llmExplanation}"
  | .llmJudgeVerificationFail judgement => s!"✗ FAIL [llm-judge] (conf={judgement.confidence}): {judgement.llmExplanation}"
  | .pendingVerification method =>
    match method with
    | .leanSymbolicVerification => "⏳ PENDING [formal/lean]"
    | .externalToolVerification toolName => s!"⏳ PENDING [tool/{toolName}]"
    | .llmJudgeVerification => "⏳ PENDING [llm-judge]"
  | .variableNotFound => "✗ FAIL: variable not found"

def PredicateVerificationEntry.describe (predicateVerificationEntry : PredicateVerificationEntry) : String :=
  s!"  {predicateVerificationEntry.requirement.varName} : {repr predicateVerificationEntry.requirement.requiredPredicate}\n     → {predicateVerificationEntry.dynamicVerificationResult.describe}"

def DynamicNodeSpec.describe (spec : DynamicNodeSpec) : String :=
  let status := if spec.executionStatus == .skipped then "- SKIPPED"
    else if spec.nodeVerified then "✓ VERIFIED"
    else if spec.hasPending then "⏳ PENDING"
    else "✗ FAILED"
  let pre := spec.precondVerificationEntries.map (·.describe) |> String.intercalate "\n"
  let post := spec.postcondVerificationEntries.map (·.describe) |> String.intercalate "\n"

  s!"Node {spec.id.val} ({spec.trajectoryStepName}) [{repr spec.executionStatus}]\n. Status: {status}\n  Preconditions:\n{pre}\n  Postconditions:\n{post}"

def DynamicVerificationGraph.describe
  (graph : DynamicVerificationGraph) : String :=
  let sep := "═══════════════════════════════════════════════════════════"
  let nodes := graph.dynamicNodeSpecs.map (·.describe) |> String.intercalate "\n\n"
  let allNodeResults := graph.dynamicNodeSpecs.flatMap
    fun s => s.precondVerificationEntries ++ s.postcondVerificationEntries
  let classCount (level : DynamicPredicateVerificationTrustLevel) := allNodeResults.filter (fun predVerifyEntry => predVerifyEntry.dynamicVerificationResult.trustLevel == level) |>.length
  let judgmentCount := allNodeResults.filter (fun predVerifyEntry =>
      match predVerifyEntry.dynamicVerificationResult.trustLevel with
      | .llmJudgment _ => true
      | _ => false) |>.length
  let summary :=
  match graph.verify with
    | .allVerified => "✓ ALL NODES VERIFIED — llmExecAxiom DISCHARGED"
    | .someNodesFailed failedNodes =>
      let names : List String := failedNodes.map
        fun (x : NodeId × String × DynamicNodeExecutionVerifyStatus) => x.2.1
      s!"✗ FAILED: {String.intercalate ", " names}"
    | .hasPending pendingNodes =>
      let names : List String := pendingNodes.map
        fun (x: NodeId × String) => x.2
      s!"⏳ PENDING: {String.intercalate ", " names}"
    | .structuralMismatch reason => s!"✗ STRUCTURAL MISMATCH: {reason}"
  s!"{sep}\n  LAYER 3: DYNAMIC EXECUTION VERIFICATION\n{sep}\n\n{nodes}\n\n{sep}\n  Formal: {classCount .formal}  Trusted: {classCount .trusted}  Judgment: {judgmentCount}  Pending: {classCount .pending}\n  {summary}\n{sep}"

end Dyn
end AgenticKernel
