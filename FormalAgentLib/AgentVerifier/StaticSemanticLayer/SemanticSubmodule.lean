import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.StaticSemanticVariable
import AgentVerifier.StaticSemanticLayer.SemanticGraph
import AgentVerifier.StaticSemanticLayer.SemanticVerification


namespace AgenticKernel

/-
╔══════════════════════════════════════════════════════════════════════════╗
║  LAYER 2 EXTENSION: SUBMODULE INTEGRATION                              ║
║                                                                        ║
║  When a parent workflow calls a submodule (via `call` or `parallel`),  ║
║  we treat the submodule as a black box:                                ║
║    - Precondition  = submodule's parameter conditions + tool/module    ║
║                      existence conditions                              ║
║    - Postcondition = submodule's return variable postconditions        ║
║                                                                        ║
║  The key insight is that if the submodule's SemanticWorkflowGraph has  ║
║  been verified (isSemanticallySoundBool = true), then we can safely    ║
║  abstract it into a single SemanticWorkflowNode and plug it into the  ║
║  parent graph's verification pipeline.                                 ║
║                                                                        ║
║  Design:                                                               ║
║    1. SubmoduleSpec: captures a verified submodule's interface          ║
║    2. deriveSubmodulePrecond: extract preconditions from paramNode      ║
║    3. deriveSubmodulePostcond: extract postconditions from exit nodes   ║
║    4. submoduleToSemanticNode: convert SubmoduleSpec → SemanticNode     ║
║    5. Axiom: verified submodule satisfies its spec (analogous to       ║
║       llmExecAxiom but for submodules)                                 ║
║    6. Parallel integration: handle `parallel` steps that invoke a      ║
║       submodule multiple times with different parameters                 ║
╚══════════════════════════════════════════════════════════════════════════╝
-/


/-
# Section 1: Exit fact and return variable extraction
-/

/-- Extract exit var preds from a verified graph. `verify` must return `.success` or we will have contradition results -/
def extractExitVarPreds
  (graph : SemanticWorkflowGraph)
  (registry : PredicateRegistry := emptyRegistry)  -- Registry is not used in the current extraction logic, but can be added for more complex cases
  (h : graph.isSemanticallySoundBool registry = true) : List VariablePredicateRequirement :=
  match h_submodule : graph.verify registry with
  | .success exitVarPreds => exitVarPreds
  | .failure .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h
  | .loopInvariantMissing .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h
  | .loopInvariantNotEstablished .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h
  | .loopInvariantNotPreserved .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h
  | .loopTerminationSpecInvalid .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h
  | .topologicalSortFailed .. => by
    simp [SemanticWorkflowGraph.isSemanticallySoundBool, h_submodule] at h


/-- Extract all return variable names from a workflow graph and finds all returnValue Nodes and collect their read variable names. -/
def extractReturnVarNames (graph : WorkflowGraph) : List String :=
  let returnNodes := graph.nodes.filter (fun node => node.stepType == .returnValue)
  let names := returnNodes.filterMap (
    fun node =>
      match node.reads with
      | [readVar] => some readVar.name
      | _ => none
  )
  names.eraseDups

/--
Extract return variable predicates directly from exit nodes' postconditions. For each exit node that is a returnValue node, we do the following things:
  1. Find the corresponding semantic node
  2. Get its precondVariables
  3. Filter the return varaiable

This presevers return variable predicates even when different branches return different variable names.
-/
def extractReturnVarPredsFromExitNodes
  (graph : SemanticWorkflowGraph) : List VariablePredicateRequirement :=
  let returnNodes := graph.baseGraph.nodes.filter (fun node => node.stepType == .returnValue)
  returnNodes.flatMap (
    fun returnNode =>
      match graph.semanticNodes.find? (·.baseNode.id == returnNode.id) with
      | some semNode =>
        -- Return nodes should have postcond = precond for the return variable, the precondVariables contain the predicates we guarantee about the return
        let returnVarName := match returnNode.reads with
          | [readVar] => some readVar.name
          | _ => none
        match returnVarName with
        | some varName => semNode.precondVariables.filter (·.varName == varName)
        | none => []
      | none => []
  )

/--
Check if all return nodes return the same var name. This is only a soft constraint, submodules with different return variable names across branches are still valid, but their predicates will be merged with `predicateOr` to maintian soundness.

When the return variable name is consistant, the all return paths use the same variable name, the predicates are directly usable. When the return var names are different across branches, we will use the `extractReturnVarPredsUnified` to merge into a single output
-/
def WorkflowGraph.returnVarNameConsistent (graph : WorkflowGraph) : Bool :=
  (extractReturnVarNames graph).eraseDups.length <= 1


/--
Extract only the return varaiable's postconditions from exit facts. The exit facts from `verify` include preds on all variables (intermediate + return). But the paraent can only see the returned variable, internal variables like `paper_title`, `abstract` etc. are not exposed.

For multiple return paths (e.g., different branches converging to
different return nodes, or conditional branches before return):
- When return var names are CONSISTENT: extract from merged exit facts
- When return var names DIFFER: extract directly from exit nodes

For `predicateAnd` (conjunctions from multiple postconditions):
- `predicateAnd(p₁, p₂) → q` if EITHER `p₁ → q` OR `p₂ → q`
- This allows extracting individual components from conjunctions
-/
def extractReturnVarPreds
  (graph : SemanticWorkflowGraph)
  (_registry : PredicateRegistry := emptyRegistry)  -- Registry is not used in the current extraction logic, but can be added for more complex cases
  (_h : graph.isSemanticallySoundBool _registry = true) : List VariablePredicateRequirement :=
  extractReturnVarPredsFromExitNodes graph

/--
Extract return variable predicates and unify them under a single name
-/
def extractReturnVarPredsUnified
  (graph : SemanticWorkflowGraph)
  (_registry : PredicateRegistry := emptyRegistry)  -- Registry is not used in the current extraction logic, but can be added for more complex cases
  (_h : graph.isSemanticallySoundBool _registry = true)
  (unifiedReturnVarName : String := "returnValue")
  : List VariablePredicateRequirement :=
  -- Extract return predicates directly from each exit node
  let returnVarPreds := extractReturnVarPredsFromExitNodes graph
  if returnVarPreds.isEmpty then
    -- No return predicates found, return minimal guarantee
    [⟨unifiedReturnVarName, PredicateType.nameExists⟩]
  else
    -- Group predicates by their type, then find common ones across all return vars
    let returnVarNames := extractReturnVarNames graph.baseGraph
    -- For each unique predicate type, check if ALL return vars have it
    let allPredsFlat := returnVarPreds.map (·.requiredPredicate) |>.eraseDups
    -- Find predicates that appear for ALL return variable names
    let commonPreds := allPredsFlat.filter fun pred =>
      returnVarNames.all fun varName =>
        returnVarPreds.any fun req =>
          req.varName == varName && req.requiredPredicate == pred
    let mergedPred := match commonPreds with
      | [] => PredicateType.nameExists
      | [p] => p
      | preds => buildPredicateAndChain preds
    [⟨unifiedReturnVarName, mergedPred⟩]


/-
# Section 2: Submodule specification
  A submodule captures the "interface" of a verified submodule:
    - Its name (for error messages and debugging)
    - Its parameter requirements (what the caller must provide)
    - Its return postconditions (what the caller can assume after the call)
    - A proof witness that the submodule's internal graph verified successfully
-/

/--
The specification of a verified submodule, used as a block-box interface for integration into the parent workflow.
-/
structure SubmoduleNode where
  /-- The Name of the submodule -/
  name : String
  /-- The verified SemanticWorkflowGraph of the submodule -/
  submoduleSemanticGraph : SemanticWorkflowGraph
  /-- The registry used for verification (for .ext predicate resolution) -/
  registry : PredicateRegistry := emptyRegistry
  /-- Proof that the submodule has been verified -/
  verifiedProof : submoduleSemanticGraph.isSemanticallySoundBool registry = true
  /-- Parameter variable predicate requirements: what the caller must ensure. It is derived from the submodule's paramNode.postcondVariables. -/
  parameterRequirements : List VariablePredicateRequirement :=
    submoduleSemanticGraph.paramNode.postcondVariables
  /-- Return postconditions: what the submodule guarantees about its output. It only includes predicates on the return variable, not the internal variables. Computed from exit facts + return node analysis -/
  returnPostconditions : List VariablePredicateRequirement
  /-- Whether the submodule has consistent return variable names across all paths -/
  hasConsistentReturnVarName : Bool :=
    submoduleSemanticGraph.baseGraph.returnVarNameConsistent

/--
Create a SubmoduleNode from a SemanticWorkflowGraph and its soundness proof. This is the main entry point for integrating a verified submodule. Return postconditions are automatically extracted from the return variable only. If the `returnVarname` is provided and the submodule has inconsistent return variable names across branches, all return predicates will be merged under the unified name using `predicateOr` for submodules
-/
def makeSubmoduleNode
  (name : String)
  (submoduleSemanticGraph : SemanticWorkflowGraph)
  (registry : PredicateRegistry := emptyRegistry)
  (proof : submoduleSemanticGraph.isSemanticallySoundBool registry = true)
  (returnVarName : Option String := none) : SubmoduleNode :=
  let returnVarPreds := match returnVarName with
    | some returnName =>
      -- use the unified extraction when the caller wants a single return var name
      extractReturnVarPredsUnified submoduleSemanticGraph registry proof returnName
    | none =>
      -- Standard extraction (works best when returnVarConsistent = true)
      extractReturnVarPreds submoduleSemanticGraph registry proof
  { name := name
    submoduleSemanticGraph := submoduleSemanticGraph
    registry := registry
    verifiedProof := proof
    returnPostconditions := returnVarPreds
  }

/-
# Section 3: Deriving preconditions and postconditions
-/

/-- Automatically derive the precondition predicates for a submodule call. -/
def SubmoduleNode.deriveSubmodulePrecond
  (submoduleNode : SubmoduleNode) : List VariablePredicateRequirement :=
  submoduleNode.parameterRequirements

/-- Derive the postcondition predicates for a submodule call. -/
def SubmoduleNode.deriveSubmodulePostcond
  (submoduleNode : SubmoduleNode) : List VariablePredicateRequirement :=
  submoduleNode.returnPostconditions

/--
Derive postconditions with variable renaming. When the parent workflow saves the submodule's return value into a different variable name (via save_as), we rename the return variable.

E.g.: submodule returns "return_dict", parent saves as "citation_result" → rename "return_dict" → "citation_result" in all postcond predicates.
-/
def SubmoduleNode.deriveSubmodulePostcondRenamed
  (submoduleNode : SubmoduleNode)
  (returnVarMapping : List (String × String)) : List VariablePredicateRequirement :=
  submoduleNode.returnPostconditions.map (
    fun req =>
      match returnVarMapping.find? (fun (subVar, _) => subVar == req.varName) with
      | some (_, parentVar) => { req with varName := parentVar }
      | none => req
  )

/--
Derive preconditions with variable mapping. When the parent passes variables under different names, we map from parent variable names to submodule parameter names.
-/
def SubmoduleNode.deriveSubmodulePrecondRenamed
  (submoduleNode : SubmoduleNode)
  (paramVarMapping : List (String × String)) : List VariablePredicateRequirement :=
  submoduleNode.parameterRequirements.map (
    fun req =>
      match paramVarMapping.find? (fun (subVar, _) => subVar == req.varName) with
      | some (_, parentVar) => { req with varName := parentVar }
      | none => req
  )

/-
# Section 4: Converting submodule node into semantic node

This section converting a SubmoduleNode into a SemanticWorkflowNode that can be placed into the parent's SemanticWorkflowGraph. The resulting node acts as a black box, only the interface matters
-/

/-- Convert a SubmoduleNode into a SemanticWorkflow for a `call` execution type. The resulting node is relatively simple, with only basis precondVariables and postcondVariables without renaming. -/
def submoduleToSemanticNode
  (submoduleNode : SubmoduleNode)
  (baseNode : WorkflowNode)
  (paramMapping : List (String × String) := [])
  (returnVarMapping : List (String × String) := [])
  : SemanticWorkflowNode :=
  let precondVars :=
    if paramMapping.isEmpty then
      submoduleNode.deriveSubmodulePrecond
    else
      submoduleNode.deriveSubmodulePrecondRenamed paramMapping
  let postcondVars :=
    if returnVarMapping.isEmpty then
      submoduleNode.deriveSubmodulePostcond
    else
      submoduleNode.deriveSubmodulePostcondRenamed returnVarMapping
  {
    baseNode := baseNode
    precondVariables := precondVars
    postcondVariables := postcondVars
  }

/--
# Section 5: Submodule execution axiom

Analogous to llmExecAxiom, but build for submodule calls. Since we have verified the submodule internally, this axion iss justified by the submodule's own verification.
## TODO: Maybe need to delete this to avoid inclusion of a new axiom
-/

axiom submoduleExecAxiom
  (submoduleNode : SubmoduleNode)
  (semanticNode : SemanticWorkflowNode)
  (env : SemanticEnv)
  (precond : semanticNode.precond env) :
  ∃ env', semanticNode.postcond env env'

/-
# Section 6: Parallel submodule integration

When a parent workflow uses `parallel` to invoke a submodule multiple times with different parameters:
  1. The parallel step takes a list of parameters sets (param_list)
  2. Each invocation produceas a result per submodule spec
  3. The collected results are stored as Dict[str, Any] object

The actual python return structure
```python
results = {
  "result_1": { ... },  # corresponds to first param set
  "result_2": { ... },  # corresponds to second param set
  ...
}
```
-/

/-
# Section 6.1: Dict Value Predicate integration
-/

/-- Create a DictAllValurePredicate from submodule return postconditions. This is the bridge between the verified submodule's return predicates and the extenxible predicate system. -/
def makeDictAllValuesPrediFromReturns
  (returnVarName : String)
  (returnPostconds : List VariablePredicateRequirement) : DictAllValuesPredicate :=
  {
    dictValuePredicates := returnPostconds.map (·.requiredPredicate)
    dictVarName := returnVarName
  }

/-
## Section 6.2: Node for parallel submodule invocation
-/

/-- Specification for the parallel submodule invocation node. Extends the basic Semantic Node with constraint tracking. -/
structure ParallelSubmoduleNode extends SubmoduleNode where
  /-- The variable name holding the parameter list -/
  parameterListVarName : String
  /-- The variable name where results are collected -/
  returnVarName : String
  /-- Max number of parallel workers -/
  maxWorkers : Nat := 1

/-- Coerction from `ParallelSubmoduleNode` to `SubmoduleNode`. Allowing passing a `ParallelSubmoduleNode` where a `SubmoduleNode` is expected. -/
instance : Coe ParallelSubmoduleNode SubmoduleNode where
  coe := ParallelSubmoduleNode.toSubmoduleNode

/-
## Section 6.3: Lifting predicates to parallel results

When we extract return values from each single parallel submodule invocation, we need to lift the returns each invocation into a dict as a json array as follows:
```python
results = {
  "result_1": { ... },  # corresponds to first param set
  "result_2": { ... },  # corresponds to second param set
  ...}
```
-/

/-- Lift a submodule's return postconditions onto the parallel results variable.

    The parallel step returns a `Dict[str, Any]` (JSON Object):
    ```python
    { "result_1": <return_value_1>, "result_2": <return_value_2>, ... }
    ```

    We encode this as a single `predicateAnd` chain combining:
    1. Container predicates (nameExists, isValidJson, jObject[])
    2. A `PredicateType.ext` marker wrapping `DictAllValuesPredicate`
       that encodes the per-value predicate list

    Redundant predicates (e.g. nameExists implied by isValidJson) are
    handled correctly at verification time by `compatibleWithRegistry`
    via And-Elim rules. -/
def liftSubmoduleReturnsToParallelPostconds
  (returnPostconds : List VariablePredicateRequirement)
  (resultsVarName : String) : List VariablePredicateRequirement :=
  -- Base postconditions: Dict container structure
  let containerPredicates : List PredicateType := [
    .nameExists,
    .isValidJson,
    .matchesJsonSchema (.jObject [])
  ]

  -- Create DictAllValuesPredicate and wrap as PredicateType.ext
  let dictPred := makeDictAllValuesPrediFromReturns resultsVarName returnPostconds
  let valueSchemaPred : List PredicateType :=
    if dictPred.dictValuePredicates.isEmpty then []
    else [dictAllValuesPredToExt dictPred]

  -- Combine container + ext predicate into a single predicateAnd chain
  let allPreds := containerPredicates ++ valueSchemaPred
  let combinedPred := buildPredicateAndChain allPreds
  [⟨resultsVarName, combinedPred⟩]

/--
Convert a ParallelSubmoduleSpec into a SemanticWorkflowNode.
Preconditions (derived from submodule):
  1. Parameter list variable is valid JSON (array of parameter dicts)
  2. Submodule exists (moduleExists)
  3. All tool dependencies from submodule are available

Postconditions (automatically lifted from submodule return):
  1. Results variable exists and is valid JSON
  2. Results variable is a JSON Object (Dict[str, Any]) with keys "result_1", "result_2", ... (dynamically sized)
  3. The submodule's return predicates are attached to the results variable using predicateAnd, allowing downstream extraction

Extra postconditions can be provided via `extraPostconds`.
 -/
def parallelSubmoduleToSemanticNode
  (parallelNode : ParallelSubmoduleNode)
  (baseNode : WorkflowNode)
  (extraPostconds : List VariablePredicateRequirement := []) : SemanticWorkflowNode :=
  -- Preconds
  let paramListPrecond : List VariablePredicateRequirement := [
    varIsValidJson parallelNode.parameterListVarName,
    varIsValidModule parallelNode.name
  ]

  let toolPreconds := parallelNode.parameterRequirements.filter
    fun req => req.requiredPredicate == .toolExists
  let allPreconds := paramListPrecond ++ toolPreconds

  -- Postconds: lifted from submodule return predicates
  let liftedPostconds := liftSubmoduleReturnsToParallelPostconds
    parallelNode.returnPostconditions
    parallelNode.returnVarName

  let allPostconds := liftedPostconds ++ extraPostconds

  {
    baseNode := baseNode
    precondVariables := allPreconds
    postcondVariables := allPostconds
  }

/-
# Sectionm 7: Constructors for Submodule node
-/

/-- Create a SemanticWorkflowNode for a `call` step that invokes a submodule. -/
def makeSubmoduleCallNode
  (submoduleNode : SubmoduleNode)
  (workflowNode : WorkflowNode)
  (paramMapping : List (String × String) := [])
  (returnMapping : List (String × String) := []) : SemanticWorkflowNode :=
  submoduleToSemanticNode submoduleNode workflowNode paramMapping returnMapping

/--
Create a SemanticWorkflowNode for a `parallel` step that invokes multiple submodule invocations.

The returned predicates on `resultsVar` include:
  1. Base predicates (nameExists, isValidJson, matchesJsonSchema jObject[])
  2. The combined value predicates from the submodule's return postconditions. These are directly usable when extracting individual values from the Dict.
-/
def makeParallelSubmoduleNode
  (submoduleNode : SubmoduleNode)
  (parallelWorkflowNode : WorkflowNode)
  (paramLitVarName : String)
  (returnVarName : String)
  (extraPostconds : List VariablePredicateRequirement := [])
  (maxWorkers : Nat := 1)
  : SemanticWorkflowNode :=
  let parallelNode : ParallelSubmoduleNode := {
    toSubmoduleNode := submoduleNode
    parameterListVarName := paramLitVarName
    returnVarName := returnVarName
    maxWorkers := maxWorkers
  }
  parallelSubmoduleToSemanticNode parallelNode parallelWorkflowNode extraPostconds

end AgenticKernel
