import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer

/-!
# Section 1 — Dynamic Variable Predicates (Channel ①)

The runtime variable-level predicate engine and the bridge to Layer-2's
variable predicate system (`PredicateType` / `VariablePredicateRequirement` /
`PredicateRegistry` / `SemanticEnv`). This is the §1 of the dynamic layer
(see §0 `ExecutionTrace` for the full section spine).

Ported near-verbatim from the original
`AgentVerifier/DynamicVerification/DynamicVerificationBasics.lean` (clean, no
legacy deps; the variable channel is the most complete and the only one that
carries a soundness proof — see §4), re-homed under `namespace
AgenticKernel.Dyn`. The original "Section N" headers become "§1.N" to fit the
uniform spine.

The layer has three verification **methods** (orthogonal to the three
**channels** ①②③):
  1. LeanSymbolic : pure Lean computation, has soundness proof (§4)
  2. ExternalTool : deterministic Python checker, called via IO (§6) or
     pre-injected as `ExternalVerificationResult`
  3. LLMJudge     : semantic judgement, online (Python harness, §6/§8) or
     pre-injected as `LLMJudgementResult`

Two registries:
  `VerificationRegistry` : maps `.ext` `PredicateKey` → `VerificationMethod`
  (the tool→script registry lives in §6 with the IO boundary)

Two execution modes:
  1. Injection Mode : `ExternalVerificationResult` pre-computed by Python
  2. IO Mode        : call Python from Lean via IO (§6)
-/

namespace AgenticKernel
namespace Dyn

/-!
## §1.1 — Verification method and Verification Registry
-/

/-- How a predicate should be verified at runtime. -/
inductive VerificationMethod where
  | leanSymbolicVerification
  | externalToolVerification (toolName : String)
  | llmJudgeVerification
  deriving Repr, BEq, Inhabited, DecidableEq

/-- Maps `.ext` `PredicateKey` → `VerificationMethod` + optional Lean checker.
    Parallels Layer-2's `PredicateRegistry` but for runtime dispatch. -/
structure ExternalPredicateVerificationMethodRegistry where
  predicateKey : PredicateKey
  method : VerificationMethod
  leanChecker : Option (SemanticEnv → String → Bool) := none
  deriving Inhabited

structure VerificationRegistry where
  entries : List ExternalPredicateVerificationMethodRegistry := []
  deriving Inhabited

namespace VerificationRegistry

def empty : VerificationRegistry := ⟨[]⟩

def lookup
  (registry : VerificationRegistry)
  (key : PredicateKey) : Option ExternalPredicateVerificationMethodRegistry :=
  registry.entries.find? (fun entry => entry.predicateKey.semanticBEq key)

def getMethod
  (registry : VerificationRegistry)
  (key : PredicateKey)
  (fallback : VerificationMethod := .llmJudgeVerification) : VerificationMethod :=
  match registry.lookup key with
  | some entry => entry.method
  | none => fallback

def getLeanChecker
  (registry : VerificationRegistry)
  (key : PredicateKey) : Option (SemanticEnv → String → Bool) :=
  registry.lookup key |>.bind (·.leanChecker)

def register
  (registry : VerificationRegistry)
  (entry : ExternalPredicateVerificationMethodRegistry) : VerificationRegistry :=
  { registry with entries := entry :: registry.entries }

def registerExternalTool
  (registry : VerificationRegistry)
  (key : PredicateKey)
  (toolName : String) :=
  registry.register { predicateKey := key, method := .externalToolVerification toolName }

def registerLLMJudge
  (registry : VerificationRegistry)
  (key : PredicateKey) :=
  registry.register { predicateKey := key, method := .llmJudgeVerification }

def registerLeanChecker
  (registry : VerificationRegistry)
  (key : PredicateKey)
  (checker : SemanticEnv → String → Bool) :=
  registry.register {
    predicateKey := key,
    method := .leanSymbolicVerification,
    leanChecker := some checker
  }

/--
Import all entries from a Layer-2 `PredicateRegistry`. Usage:

  def myVarReg := VerificationRegistry.fromPredicateRegistry layer2Registry

This automatically makes all `.ext` predicates that have been registered in Layer 2 (e.g., DictAllValuesPredicate) available for the Layer 3 verification, using their Layer 2 `checkProp` as the Lean symbolic checker.
-/
def fromPredicateRegistry
  (predRegistry : PredicateRegistry)
  -- External overrides of (key, toolName) pairs that should use Python instead
  (externalOverrides : List (PredicateKey × String) := []) : VerificationRegistry :=
  ⟨predRegistry.entries.map fun entry =>
    match externalOverrides.find? (fun (k, _) => k.semanticBEq entry.predicateKey) with
    | some (_, toolName) =>
      -- Override: this predicate uses an external python checker
      {
        predicateKey := entry.predicateKey,
        method := .externalToolVerification toolName,
        leanChecker := some entry.checkProp
      }
    | none =>
      -- Default: use the Layer 2's checkProp as Lean checker
      {
        predicateKey := entry.predicateKey,
        method := .leanSymbolicVerification,
        leanChecker := some entry.checkProp
      }
  ⟩


/--
Import a Layer-2 `PredicateRegistry` into an existing `VerificationRegistry`, merging with any manually registered entries.
-/
def mergePredicateRegistry
  (existingRegistries : VerificationRegistry)
  (incomingPredReg : PredicateRegistry)
  (externalOverrides : List (PredicateKey × String) := []) : VerificationRegistry :=
  let importedVerificationRegistry := fromPredicateRegistry incomingPredReg externalOverrides
  ⟨existingRegistries.entries ++ importedVerificationRegistry.entries⟩

/-!
### Graph-level registrars

Convenience aliases for registering graph-level predicates (from §3) into the runtime verification registry. They behave exactly like their variable-level counterparts above — the distinction is documentation: the method-routing layer (key → lean/tool/llm) is shared by both channels; only the *checker signature* differs (variable: `SemanticEnv → String → Bool`; graph: `DynamicGraphCheckContext → Bool`, see §3).
-/

/-- Register a graph-level predicate to be verified by an external Python
    tool (handler in `checker.py`). -/
def registerGraphExternalTool
  (registry : VerificationRegistry)
  (key : PredicateKey)
  (toolName : String) : VerificationRegistry :=
  registry.registerExternalTool key toolName

/-- Register a graph-level predicate to be verified by LLM judge (result
    must be pre-injected as an `LLMJudgementResult`). -/
def registerGraphLLMJudge
  (registry : VerificationRegistry)
  (key : PredicateKey) : VerificationRegistry :=
  registry.registerLLMJudge key

/-- Register a graph-level predicate with a Lean symbolic checker. The
    checker runs over a `SemanticEnv` (graph-level checks typically
    derive the env from the final execution state). -/
def registerGraphLeanChecker
  (registry : VerificationRegistry)
  (key : PredicateKey)
  (checker : SemanticEnv → String → Bool) : VerificationRegistry :=
  registry.registerLeanChecker key checker

end VerificationRegistry


/-- Classify each `PredicateType` into its verification method.

    NOTE (namespace): this is an extension of the *static* `PredicateType`
    defined under `Dyn`, so it must be called qualified
    (`PredicateType.verificationMethod predType …`) rather than via dot
    notation (`predType.verificationMethod`), which would resolve in
    `AgenticKernel.PredicateType.*`. -/
def PredicateType.verificationMethod
  (predType : PredicateType)
  (verificationRegistry : VerificationRegistry := .empty)
  -- We default to preferring external tools when available, but this flag allows overriding to prefer Lean checkers if both are available for a predicate
  (preferExternal : Bool := true) : VerificationMethod :=
  match predType with
  | .nameExists | .isNonEmptyString | .isNonEmptyList | .isValidList
  | .containsSubstring _ | .taskCompleted | .isInt => .leanSymbolicVerification
  | .isValidURL => if preferExternal then .externalToolVerification "url_validator" else .leanSymbolicVerification
  | .isValidFilePath => if preferExternal then .externalToolVerification "file_path_validator" else .leanSymbolicVerification
  | .isValidPath => if preferExternal then .externalToolVerification "path_validator" else .leanSymbolicVerification
  | .isValidBibtex => if preferExternal then .externalToolVerification "bibtex_validator" else .leanSymbolicVerification
  | .isValidLatex => if preferExternal then .externalToolVerification "latex_validator" else .leanSymbolicVerification
  | .isValidJson => if preferExternal then .externalToolVerification "json_validator" else .leanSymbolicVerification
  | .matchesJsonSchema _ => if preferExternal then .externalToolVerification "json_schema_validator" else .leanSymbolicVerification
  | .isJsonWithFields _ => if preferExternal then .externalToolVerification "json_schema_validator" else .leanSymbolicVerification
  | .fileExistsAtPath => .externalToolVerification "file_existence_checker"
  | .toolExists => .externalToolVerification "tool_existence_checker"
  | .moduleExists => .externalToolVerification "module_existence_checker"
  | .ext key => verificationRegistry.getMethod key .llmJudgeVerification
  | .custom _ => .llmJudgeVerification  -- default to LLM judge for unknown custom predicates
  | .predicateAnd _ _ => .leanSymbolicVerification
  | .predicateOr _ _ => .leanSymbolicVerification


/-!
## §1.2 — Execution values and execution state space
-/

structure NodeExecutionValue where
  rawString : String
  parsedValue : Option Value := none
  deriving Repr, Inhabited

def NodeExecutionValue.fromString
  (s : String) : NodeExecutionValue :=
  {rawString := s, parsedValue := some (.vString s)}  -- for simplicity, we treat all raw strings as vString values. In a real implementation, we would have more sophisticated parsing based on expected types.

def NodeExecutionValue.withParsed
  (rawString : String)
  (parsedValue : Value) : NodeExecutionValue :=
  {rawString := rawString, parsedValue := some parsedValue}

def NodeExecutionState := List (String × NodeExecutionValue)

namespace NodeExecutionState

def get (state : NodeExecutionState) (varName : String) : Option NodeExecutionValue :=
  state.find? (fun (name, _) => name == varName) |>.map (·.2)

def getRawString (state: NodeExecutionState) (varName : String) : Option String :=
  state.get varName |>.map (·.rawString)

def getParsedValue (state: NodeExecutionState) (varName : String) : Option Value :=
  state.get varName |>.bind (·.parsedValue)

def stateToSemanticEnv (state : NodeExecutionState) : SemanticEnv :=
  fun name => match state.find? (fun (n, _) => n == name) with
    | some (_, execValue) => execValue.parsedValue
    | none => none

def setExecutionValue
  (state : NodeExecutionState)
  (varName : String)
  (nodeExecutionValue : NodeExecutionValue) : NodeExecutionState :=
  (varName, nodeExecutionValue) :: state.filter (fun (name, _) => name != varName)  -- overwrite if exists, otherwise add new

def getVarnames (state : NodeExecutionState) : List String := state.map (·.1)

def stateContainsVar (state : NodeExecutionState) (varName : String) : Bool := state.any (fun (name, _) => name == varName)

def emptyState : NodeExecutionState := []

end NodeExecutionState

/-!
## §1.3 — Structures to store external verification results
-/

structure ExternalToolJudgementResult where
  toolName : String
  passed : Bool
  additionalInfo : String := ""
  deriving Repr, BEq, Inhabited, DecidableEq

structure LLMJudgementResult where
  holds : Bool
  confidence : Float := 1.0
  llmExplanation : String := ""
  nodeInstruction : String := ""  -- the instruction given to the LLM for this judgement, for debugging purposes
  deriving Repr, BEq, Inhabited

/-- Create an instance for ExternalToolJudgement. -/
def makeExternalToolJudgementResult
  (toolName : String)
  (passed : Bool)
  (additionalInfo : String := "") : ExternalToolJudgementResult :=
  {
    toolName := toolName,
    passed := passed,
    additionalInfo := additionalInfo
  }
/-- Create an instance for LLMJudgementResult -/
def makeLLMJudgementResult
  (holds : Bool)
  (confidence : Float := 1.0)
  (llmExplanation : String := "")
  (nodeInstruction : String := "") : LLMJudgementResult :=
  {
    holds := holds,
    confidence := confidence,
    llmExplanation := llmExplanation,
    nodeInstruction := nodeInstruction
  }

/-!
## §1.4 — Predicate verification result
-/

inductive DynamicPredicateVerificationResult where
  | leanSymbolicVerificationPass
  | leanSymbolicVerificationFail (reason : String)
  | externalToolVerificationPass (result : ExternalToolJudgementResult)
  | externalToolVerificationFail (result : ExternalToolJudgementResult)
  | llmJudgeVerificationPass (judgement : LLMJudgementResult)
  | llmJudgeVerificationFail (judgement : LLMJudgementResult)
  | pendingVerification (method : VerificationMethod)
  | variableNotFound
  deriving Repr, BEq, Inhabited

inductive DynamicPredicateVerificationTrustLevel where
  | formal
  | trusted
  | llmJudgment (confidence : Float)
  | pending
  | error
  deriving Repr, BEq, Inhabited

def DynamicPredicateVerificationResult.passed : DynamicPredicateVerificationResult → Bool
  | .leanSymbolicVerificationPass => true
  | .externalToolVerificationPass _ => true
  | .llmJudgeVerificationPass _ => true
  | _ => false

def DynamicPredicateVerificationResult.failed : DynamicPredicateVerificationResult → Bool
  | .leanSymbolicVerificationFail _ => true
  | .externalToolVerificationFail _ => true
  | .llmJudgeVerificationFail _ => true
  | _ => false

def DynamicPredicateVerificationResult.isPending : DynamicPredicateVerificationResult → Bool
  | .pendingVerification _ => true
  | _ => false

def DynamicPredicateVerificationResult.trustLevel : DynamicPredicateVerificationResult → DynamicPredicateVerificationTrustLevel
  | .leanSymbolicVerificationPass | .leanSymbolicVerificationFail _ => .formal
  | .externalToolVerificationPass _  | .externalToolVerificationFail _ => .trusted
  | .llmJudgeVerificationPass judgement | .llmJudgeVerificationFail judgement => .llmJudgment judgement.confidence
  | .pendingVerification _ => .pending
  | .variableNotFound => .error

/-!
## §1.5 — Lean symbolic verification (Method 1)
-/

/-- Pure Lean verification, returns lean pass or lean fail for leanSymbolicationVerification predicates and returns .pending for predicates using external Tool or LLM judgement -/
def leanSymbolicPredicateVerification
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (varRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicPredicateVerificationResult :=
  match semanticEnv.get varName with
  | none => match predType with
    -- Tool and module existence checks should be deferred to external tools even if variable not found
    | .toolExists => .pendingVerification (.externalToolVerification "tool_existence_checker")
    | .moduleExists => .pendingVerification (.externalToolVerification "module_existence_checker")
    | _ => .variableNotFound
  | some _ =>
    let method := PredicateType.verificationMethod predType varRegistry preferExternal
    match method with
      | .externalToolVerification _ => .pendingVerification method
      | .llmJudgeVerification => .pendingVerification method
      | .leanSymbolicVerification =>
        if predType.checkBool semanticEnv varName then .leanSymbolicVerificationPass
        else .leanSymbolicVerificationFail s!"Predicate {repr predType} not satisfied for '{varName}'"

/-!
## §1.6 — Inject the verification result back to Lean (Injection mode)
-/

/-- Pre-computed verification result injected from external results.

    The `predicateType` field stores the actual `PredicateType` this injection
    answers for, not a string rendering of it. Matching in
    `findExternalVerificationResult` uses the `BEq PredicateType` instance
    (structural equality via `PredicateType.beqAux`), which is both robust
    and compositional — callers just pass the same `PredicateType` value
    they used in the pre/postcondition, no string hand-writing. -/
structure ExternalVerificationResult where
  varName : String
  predicateType : PredicateType
  externalToolResult : Option ExternalToolJudgementResult := none
  llmJudgementResult : Option LLMJudgementResult := none
  deriving Repr, Inhabited, BEq

def findExternalVerificationResult
  (externalVerificationResults : List ExternalVerificationResult)
  (varName : String)
  (predType : PredicateType) : Option ExternalVerificationResult :=
  externalVerificationResults.find? fun r =>
    r.varName == varName && r.predicateType == predType

def resolvePendingVerificationResult
  (verificationMethod : VerificationMethod)
  (externalVerificationResult : Option ExternalVerificationResult) : DynamicPredicateVerificationResult :=
  match externalVerificationResult with
  | none => .pendingVerification verificationMethod
  | some result =>
    match verificationMethod with
    | .externalToolVerification _ =>
      match result.externalToolResult with
      | some toolResult =>
        if toolResult.passed then .externalToolVerificationPass toolResult
        else .externalToolVerificationFail toolResult
      | none => .pendingVerification verificationMethod
    | .llmJudgeVerification =>
      match result.llmJudgementResult with
      | some llmResult =>
        if llmResult.holds then .llmJudgeVerificationPass llmResult
        else .llmJudgeVerificationFail llmResult
      | none => .pendingVerification verificationMethod
    | .leanSymbolicVerification => .pendingVerification verificationMethod

/-- Pure unified verifier: Lean first, then resolve pending from ExternalVerificationResult -/
def verifyPredicate
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String)
  (externalVerificationResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicPredicateVerificationResult :=
  match leanSymbolicPredicateVerification predType semanticEnv varName verificationRegistry preferExternal with
  | .pendingVerification method =>
    resolvePendingVerificationResult method (findExternalVerificationResult externalVerificationResults varName predType)
  | other => other

def verifyVariablePredicate
  (varPredRequirement : VariablePredicateRequirement)
  (semanticEnv : SemanticEnv)
  (externalVerificationResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicPredicateVerificationResult :=
  verifyPredicate
    varPredRequirement.requiredPredicate
    semanticEnv
    varPredRequirement.varName
    externalVerificationResults
    verificationRegistry
    preferExternal

/-!
## §1.7 — The matching predicate requirement and verification result
-/
structure PredicateVerificationEntry where
  requirement : VariablePredicateRequirement
  dynamicVerificationResult : DynamicPredicateVerificationResult
  deriving Repr, Inhabited

def PredicateVerificationEntry.passed
  (predEntry : PredicateVerificationEntry) : Bool := predEntry.dynamicVerificationResult.passed

def PredicateVerificationEntry.failed
  (predEntry : PredicateVerificationEntry) : Bool := predEntry.dynamicVerificationResult.failed

def PredicateVerificationEntry.isPending
  (predEntry : PredicateVerificationEntry) : Bool := predEntry.dynamicVerificationResult.isPending

def verifyPredicateRequirements
  (predicateRequirements : List VariablePredicateRequirement)
  (semanticEnv : SemanticEnv)
  (externalVerificationResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : List PredicateVerificationEntry :=
  predicateRequirements.map fun requirement =>
    {
      requirement := requirement,
      dynamicVerificationResult :=
        verifyVariablePredicate
          requirement
          semanticEnv
          externalVerificationResults
          verificationRegistry
          preferExternal
    }

/-!
## §1.8 — Dynamic Node Specs
-/

inductive ExecutionStatus where
  | pending
  | completed
  | failed
  | skipped
  deriving Repr, BEq, Inhabited

structure DynamicNodeSpec where
  semanticNode : SemanticWorkflowNode
  preExecutionState : NodeExecutionState
  postExecutionState : NodeExecutionState
  precondVerificationEntries : List PredicateVerificationEntry := []
  postcondVerificationEntries : List PredicateVerificationEntry := []
  trajectoryStepId : String := ""
  trajectoryStepName : String := ""
  executionStatus : ExecutionStatus := .completed

namespace DynamicNodeSpec

def id (nodeSpec : DynamicNodeSpec) : NodeId := nodeSpec.semanticNode.id

def name (nodeSpec : DynamicNodeSpec) :Option String := nodeSpec.semanticNode.name

def preconditionPassed (nodeSpec : DynamicNodeSpec) : Bool :=
  nodeSpec.precondVerificationEntries.all (·.passed)

def postconditionPassed (nodeSpec : DynamicNodeSpec) : Bool :=
  nodeSpec.postcondVerificationEntries.all (·.passed)

def hasPending (nodeSpec : DynamicNodeSpec) : Bool :=
  (nodeSpec.precondVerificationEntries.any (·.isPending)) ||
  (nodeSpec.postcondVerificationEntries.any (·.isPending))

def nodeVerified (nodeSpec : DynamicNodeSpec) : Bool :=
  nodeSpec.preconditionPassed && nodeSpec.postconditionPassed

def failedPreconditions (nodeSpec : DynamicNodeSpec) : List PredicateVerificationEntry :=
  nodeSpec.precondVerificationEntries.filter (·.failed)

def failedPostconditions (nodeSpec : DynamicNodeSpec) : List PredicateVerificationEntry :=
  nodeSpec.postcondVerificationEntries.filter (·.failed)

end DynamicNodeSpec

/-- Build a DynamicNodeSpec using the external verification result -/
def buildDynamicNodeSpec
  (semanticNode : SemanticWorkflowNode)
  (preExecutionState postExecutionState : NodeExecutionState)
  (stepId stepName : String)
  (status : ExecutionStatus := .completed)
  (precondExternalResults postcondExternalResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicNodeSpec :=
  {
    semanticNode := semanticNode,
    preExecutionState := preExecutionState,
    postExecutionState := postExecutionState,
    precondVerificationEntries := (verifyPredicateRequirements
      semanticNode.precondVariables
      (preExecutionState.stateToSemanticEnv)
      precondExternalResults
      verificationRegistry
      preferExternal),
    postcondVerificationEntries := (verifyPredicateRequirements
      semanticNode.postcondVariables
      (postExecutionState.stateToSemanticEnv)
      postcondExternalResults
      verificationRegistry
      preferExternal),
    trajectoryStepId := stepId,
    trajectoryStepName := stepName,
    executionStatus := status
  }

/-!
## §1.9 — Dynamic conditional node execution spec
-/

inductive ConditionalBranchType where
  | thenBranch
  | elseBranch
  deriving Repr, BEq, Inhabited, DecidableEq

structure DynamicConditionalNodeSpec extends DynamicNodeSpec where
  conditionalNode : SemanticConditionalNode
  conditionalBranchType : ConditionalBranchType

instance : Coe DynamicConditionalNodeSpec DynamicNodeSpec where
  coe := DynamicConditionalNodeSpec.toDynamicNodeSpec

def buildDynamicConditionalNodeSpec
  (baseSemanticConditionalNode : SemanticConditionalNode)
  (preExecutionState postExecutionState : NodeExecutionState)
  (branchType : ConditionalBranchType)
  (stepId stepName : String)
  (status : ExecutionStatus := .completed)
  (precondExternalResults branchPostcondExternalResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicConditionalNodeSpec :=
  let baseDynamicSpec := buildDynamicNodeSpec
    baseSemanticConditionalNode
    preExecutionState
    postExecutionState
    stepId
    stepName
    status
    precondExternalResults
    -- The postcond will always be empty since the real postcond depends on the branch information
    (postcondExternalResults := [])
    verificationRegistry
    preferExternal
  let branchPostconds := match branchType with
    | .thenBranch => baseSemanticConditionalNode.thenPostcondVariables
    | .elseBranch => baseSemanticConditionalNode.elsePostcondVariables
  let branchPostcondVerificationEntries := verifyPredicateRequirements
    branchPostconds
    (postExecutionState.stateToSemanticEnv)
    branchPostcondExternalResults
    verificationRegistry
    preferExternal
  {
    toDynamicNodeSpec := {baseDynamicSpec with postcondVerificationEntries := branchPostcondVerificationEntries},
    conditionalNode := baseSemanticConditionalNode,
    conditionalBranchType := branchType,
  }

/-!
## §1.10 — Loop node execution spec
-/

/-- Single loop iteration records with invariant checks -/
structure SingleLoopIterationRecord where
  iterationIndex : Nat
  preExecutionState : NodeExecutionState
  postExecutionState : NodeExecutionState
  invariantPreIteration : List PredicateVerificationEntry := []
  invariantPostIteration : List PredicateVerificationEntry := []

/-- Extends DynamicNodeSpec with loop-specific metadata. Exit postconditions are merged into the `postcondVerificationEntries` so `nodeVerified` automatically verifies them. -/
structure DynamicLoopNodeSpec extends DynamicNodeSpec where
  loopNode : SemanticLoopNode
  iterationRecords : List SingleLoopIterationRecord := []
  loopTerminatedNormally : Bool := true -- if false, it means the loop was exited via break or exception, which may be important for understanding which postconditions should hold

instance : Coe DynamicLoopNodeSpec DynamicNodeSpec where
  coe spec := spec.toDynamicNodeSpec

/-- Verify whether the invariant holds before the entire loop execution -/
def DynamicLoopNodeSpec.invariantHoldsBeforeLoop
  (spec : DynamicLoopNodeSpec) : Bool :=
  match spec.iterationRecords.head? with
  | some iter => iter.invariantPreIteration.all (·.passed)
  | none => true  -- if no iterations recorded, we assume invariant holds (this is a design choice that can be adjusted based on how we want to handle this case)

/-- Verify whether the invariant holds after the entire loop execution -/
def DynamicLoopNodeSpec.invariantHoldsAfterLoop
  (spec : DynamicLoopNodeSpec) : Bool :=
  spec.iterationRecords.all fun iter => iter.invariantPostIteration.all (·.passed)

/-- Full loop verification: node-level pre/post cond pass and invariant holds before and after the entire loop -/
def DynamicLoopNodeSpec.wholeLoopVerified
  (spec : DynamicLoopNodeSpec) : Bool :=
  spec.nodeVerified && spec.invariantHoldsBeforeLoop && spec.invariantHoldsAfterLoop

/-- Build a SingleLoopIterationRecord -/
def buildSingleLoopIterationRecord
  (semanticLoopNode : SemanticLoopNode)
  (iterIdx : Nat)
  (preExecutionState postExecutionState : NodeExecutionState)
  (precondExternalResults postcondExternalResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : SingleLoopIterationRecord :=
  {
    iterationIndex := iterIdx,
    preExecutionState := preExecutionState,
    postExecutionState := postExecutionState,
    invariantPreIteration := verifyPredicateRequirements
      semanticLoopNode.loopInvariant
      (preExecutionState.stateToSemanticEnv)
      precondExternalResults
      verificationRegistry
      preferExternal,
    invariantPostIteration := verifyPredicateRequirements
      semanticLoopNode.loopInvariant
      (postExecutionState.stateToSemanticEnv)
      postcondExternalResults
      verificationRegistry
      preferExternal
  }

/--
Build loop node spec using external tool verification result
  - `loopEntryPrecondExternalVerificationResults`: Resolves the preconditions before the entire loop (the precond of entry node)
  - `loopEntryPostcondExternalVerificationResults`: Resolves the postconditions before the entire loop (the postcond of entry node)
-/
def buildDynamicLoopNodeSpec
  (semanticLoopNode : SemanticLoopNode)
  (loopEntryExecutionState loopExitExecutionState : NodeExecutionState)
  (stepId stepName : String)
  (status : ExecutionStatus := .completed)
  (iterationRecords : List SingleLoopIterationRecord := [])
  (terminatedNormally : Bool := true)
  (loopEntryPrecondExternalVerificationResults loopEntryPostcondExternalVerificationResults : List ExternalVerificationResult := [])
  (loopExitPostcondExternalVerificationResults : List ExternalVerificationResult := [])
  (verificationRegistry : VerificationRegistry := .empty)
  (preferExternal : Bool := true) : DynamicLoopNodeSpec :=
  let baseDynamicNodeSpec := buildDynamicNodeSpec
    semanticLoopNode
    loopEntryExecutionState
    loopExitExecutionState
    stepId
    stepName
    status
    (precondExternalResults := loopEntryPrecondExternalVerificationResults)
    (postcondExternalResults := loopEntryPostcondExternalVerificationResults)
    verificationRegistry
    preferExternal

  let exitPostcondVerificationEntries := verifyPredicateRequirements
    semanticLoopNode.postcondVariables
    (loopExitExecutionState.stateToSemanticEnv)
    loopExitPostcondExternalVerificationResults
    verificationRegistry
    preferExternal

  {
    toDynamicNodeSpec := {baseDynamicNodeSpec with postcondVerificationEntries := exitPostcondVerificationEntries},
    loopNode := semanticLoopNode,
    iterationRecords := iterationRecords,
    loopTerminatedNormally := terminatedNormally
  }

end Dyn
end AgenticKernel
