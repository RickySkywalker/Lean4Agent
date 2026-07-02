import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer
-- Import the verified submodule
import TestVerifications.Verification_ai_scientists.writer.modules.Verification_extract_single_citation

namespace AgenticKernel

/-
╔══════════════════════════════════════════════════════════════════════════╗
║  COMPLETE VERIFICATION EXAMPLE: search_citations_module                 ║
║                                                                        ║
║  UPDATED TO USE OFFICIAL SUBMODULE + EXTENSIBLE PREDICATE SYSTEM       ║
║  Changes from temp version:                                            ║
║    - Uses official SemanticSubmodule (SubmoduleNode, makeSubmoduleNode, ║
║      makeParallelSubmoduleNode) instead of temp (SubmoduleSpec,         ║
║      mkSubmoduleSpec, mkParallelSubmoduleNode)                          ║
║    - Node 2 (parallel submodule) postcond uses                         ║
║      .ext (DictAllValuesPredicate ...).toPredicateKey                  ║
║    - Node 3 precond uses .ext to match the ext key                     ║
║    - PredicateRegistry maps DictAllValuesPredicate keys to their       ║
║      semantic functions (toProp, impliedKeys)                          ║
║    - Final theorem uses isSemanticallySoundBool with registry           ║
║    - Imports verified submodule from Verification_extract_single_       ║
║      citation.lean                                                     ║
╚══════════════════════════════════════════════════════════════════════════╝
-/


/-
========================================================================
SECTION A: IMPORT VERIFIED SUBMODULE (extract_single_citation)
========================================================================

The submodule verification is done in:
  TestVerifications.ComplexVerification.Verification_extract_single_citation

We reference its definitions via abbreviations for clarity.
-/

abbrev escGraph         := writerGraph
abbrev escSemanticGraph := extractCitationSemanticGraph
abbrev escReturnDictSchema := extractCitationReturnDictSchema

theorem esc_semantically_sound :
    escSemanticGraph.isSemanticallySoundBool emptyRegistry = true :=
  extract_single_citation_semantically_sound

#eval! do
  let result := escSemanticGraph.verify emptyRegistry
  IO.println (describeGraphVerificationResult result)


/-
========================================================================
SECTION B: CREATE SUBMODULE NODE (official API)
========================================================================

Uses official `SubmoduleNode` and `makeSubmoduleNode` from
AgentVerifier.StaticSemanticLayer.SemanticSubmodule
-/

def extractSingleCitationSpec : SubmoduleNode :=
  makeSubmoduleNode
    "extract_single_citation"
    escSemanticGraph
    emptyRegistry
    esc_semantically_sound

/-
Inspect what returnPostconditions the spec exposes.
The extract_single_citation submodule's return node (Node 6) has precond:
  [isValidJson "return_dict", matchesJsonSchema "return_dict" citationResultSchema]
makeSubmoduleNode extracts these as returnPostconditions.

liftSubmoduleReturnsToParallelPostconds then:
  combinedPred = predicateAnd isValidJson (matchesJsonSchema citationResultSchema)
  .ext DictAllValuesPredicate key encodes value-level schema

So sc_semNode2.postcondVariables ≈
  [{ varName := "all_citations",
     requiredPredicate :=
       predicateAnd (matchesJsonSchema (.jObject []))
                    (.ext ...) }]
-/

#eval! s!"Return postconditions: {extractSingleCitationSpec.returnPostconditions.map
  (fun r => s!"{r.varName}: {repr r.requiredPredicate}")}"


/-
========================================================================
SECTION C: EXTENSIBLE PREDICATE DEFINITIONS FOR PARALLEL STEP
========================================================================

Problem:
  sc_semNode2 (makeParallelSubmoduleNode) generates a postcond for
  "all_citations" that uses .ext with DictAllValuesPredicate.

  The extensible system:
  1. DictAllValuesPredicate carries the value predicates type-safely
  2. PredicateSemantics instance gives it toProp, checkProp, impliedKeys
  3. PredicateRegistry maps the key to runtime semantic functions
  4. verify uses the registry for compatibleWithRegistry

Step 1: Extract the predicates from submodule return.
-/

-- The return predicates from extract_single_citation submodule
private def sc_returnValuePreds : List PredicateType :=
  extractSingleCitationSpec.returnPostconditions.map (·.requiredPredicate)

-- Combined into a single predicate for Dict values
private def sc_combinedReturnPred : PredicateType :=
  buildPredicateAndChain sc_returnValuePreds

/-
Step 2: Define the DictAllValuesPredicate for parallel execution.

This is the TYPE-SAFE replacement for .custom "dictValuesSchema:...".
The predicate family="dictAllValues", name uses the combined predicate repr,
and the instance provides proper semantic functions.
-/

def sc_dictAllValuesPredicate : DictAllValuesPredicate := {
  dictValuePredicates := sc_returnValuePreds
  dictVarName := "all_citations"
}

-- The corresponding PredicateKey (closed, decidable)
def sc_dictValuesPredicateKey : PredicateKey :=
  sc_dictAllValuesPredicate.toPredicateKey

-- The PredicateType using .ext constructor
def sc_dictValuesPredType : PredicateType :=
  .ext sc_dictValuesPredicateKey

#eval! s!"DictAllValuesPredicate key: {repr sc_dictValuesPredicateKey}"

/-
Step 3: Build the PredicateRegistry.

The registry maps PredicateKey → semantic functions at runtime.
This enables verify to check ext predicate compatibility.
-/

def searchCitationsRegistry : PredicateRegistry :=
  makeDictAllValuesRegistry [sc_dictAllValuesPredicate]


/-
========================================================================
SECTION D: NODE DEFINITIONS (Workflow + Semantic, paired)
========================================================================
-/

-- Schemas used by semantic annotations
def extractionParamsSchema : JsonSchema :=
  .jArray (.jObject [("url", .jString), ("file_path", .jString)])

def citationResultSchema : JsonSchema :=
  .jObject [("bibtex", .jString), ("file_path", .jString),
            ("title", .jString), ("abstract", .jString)]

-- Node IDs
def sc_nodeId0 : NodeId := ⟨100⟩
def sc_nodeId1 : NodeId := ⟨101⟩
def sc_nodeId2 : NodeId := ⟨102⟩
def sc_nodeId3 : NodeId := ⟨103⟩
def sc_nodeId4 : NodeId := ⟨104⟩

-- Parameter node (semantic only, establishes initial context)
def sc_paramNode : SemanticWorkflowNode := {
  baseNode := {
    id := ⟨20041122⟩
    name := some "parameters"
    stepType := .setVariable
    reads := []
    writes := []
    llmInstruction := none }
  precondVariables := []
  postcondVariables := [
    varIsNonEmptyString "query",
    varIsInt "max_papers",
    varIsValidTool "firecrawl_search",
    varIsValidTool "fs_read",
    varIsValidTool "get_bibtex_from_url",
    varIsValidTool "get_abstract_from_url",
    varIsValidModule "extract_single_citation"
  ]
}

-- ── Node 0: search_papers ─────────────────────────────────────────────

def sc_node0 : WorkflowNode := {
  id := sc_nodeId0
  name := some "search_papers"
  stepType := .step
  reads := [⟨"query", .TString⟩, ⟨"max_papers", .TInt⟩]
  writes := [⟨"search_results", .TString⟩]
  llmInstruction := some
    "Use firecrawl_search to search for academic papers.\nQuery: {{query}}\nNumber of results: {{max_papers}}"
}

def sc_semNode0 : SemanticWorkflowNode := {
  baseNode := sc_node0
  precondVariables := [
    varIsValidTool "firecrawl_search",
    varIsNonEmptyString "query",
    varIsInt "max_papers"
  ]
  postcondVariables := [
    varIsNonEmptyString "search_results"
  ]
}

-- ── Node 1: prepare_extraction_params ─────────────────────────────────

def sc_node1 : WorkflowNode := {
  id := sc_nodeId1
  name := some "prepare_extraction_params"
  stepType := .step
  reads := [⟨"search_results", .TString⟩]
  writes := [⟨"extraction_params", .TString⟩]
  llmInstruction := some
    "For each url and file path in: {{search_results}}\nCreate a list of parameter dicts for parallel processing."
}

def sc_semNode1 : SemanticWorkflowNode := {
  baseNode := sc_node1
  precondVariables := [
    varIsNonEmptyString "search_results"
  ]
  postcondVariables := [
    varIsValidJson "extraction_params",
    varIsValidJsonSchema "extraction_params" extractionParamsSchema
  ]
}

-- ── Node 2: parallel_extract_citations ────────────────────────────────

def sc_node2 : WorkflowNode := {
  id := sc_nodeId2
  name := some "parallel_extract_citations"
  stepType := .parallel
  reads := [⟨"extraction_params", .TString⟩]
  writes := [⟨"all_citations", .TList .TUnknown⟩]
  llmInstruction := none
}

-- makeParallelSubmoduleNode (official API) auto-generates postcond for "all_citations":
--   predicateAnd
--     (matchesJsonSchema (.jObject []))     ← Dict container shape (builtin)
--     (.ext sc_dictValuesPredicateKey)       ← values satisfy citation schema (ext)
--
-- verify + searchCitationsRegistry gives the .ext tag its real semantics.
def sc_semNode2 : SemanticWorkflowNode :=
  makeParallelSubmoduleNode
    extractSingleCitationSpec
    sc_node2
    "extraction_params"
    "all_citations"

-- Diagnostic: confirm the generated postcond contains the ext predicate
#eval! s!"sc_semNode2 postcond: {sc_semNode2.postcondVariables.map
  (fun r => s!"{r.varName}: {repr r.requiredPredicate}")}"

-- ── Node 3: set_formatted_citations ───────────────────────────────────

def sc_node3 : WorkflowNode := {
  id := sc_nodeId3
  name := some "set_formatted_citations"
  stepType := .setVariable
  reads := [⟨"all_citations", .TList .TUnknown⟩]
  writes := [⟨"formatted_citations", .TList .TUnknown⟩]
  llmInstruction := none
}

-- KEY: precond uses .ext sc_dictValuesPredicateKey
--
-- Why this is type-safe:
--   DictAllValuesPredicate carries the actual predicate list
--   PredicateSemantics instance provides toProp with real semantics
--   compatibleWithRegistry checks ext key match from registry
--
-- Why verify can satisfy this precond:
--   sc_semNode2 postcond = predicateAnd (matchesJsonSchema ...) (.ext sc_dictValuesPredicateKey)
--   compatibleWithRegistry rule (And-Elim): (p₁ ∧ p₂) → p₂
--   Then .ext key equality (DecidableEq on PredicateKey) → true
def sc_semNode3 : SemanticWorkflowNode := {
  baseNode := sc_node3
  precondVariables := [
    -- Requires the Dict values predicate (backed by DictAllValuesPredicate semantics)
    { varName := "all_citations"
      requiredPredicate := sc_dictValuesPredType }
  ]
  postcondVariables := [
    -- list(dict.values()) preserves element schema
    varIsValidJsonSchema "formatted_citations" (.jArray citationResultSchema)
  ]
}

-- ── Node 4: return_result ─────────────────────────────────────────────

def sc_node4 : WorkflowNode := {
  id := sc_nodeId4
  name := some "return_result"
  stepType := .returnValue
  reads := [⟨"formatted_citations", .TList .TUnknown⟩]
  writes := []
  llmInstruction := none
}

def sc_semNode4 : SemanticWorkflowNode := {
  baseNode := sc_node4
  precondVariables := [
    varIsValidJsonSchema "formatted_citations" (.jArray citationResultSchema)
  ]
  postcondVariables := []
}


/-
========================================================================
SECTION E: WORKFLOW GRAPH + STRUCTURAL THEOREMS
========================================================================
-/

def searchCitationsGraph : WorkflowGraph := {
  nodes := [sc_node0, sc_node1, sc_node2, sc_node3, sc_node4]
  edges := [
    .seqEdge sc_nodeId0 sc_nodeId1,
    .seqEdge sc_nodeId1 sc_nodeId2,
    .seqEdge sc_nodeId2 sc_nodeId3,
    .seqEdge sc_nodeId3 sc_nodeId4
  ]
  entry := sc_nodeId0
  exits := [sc_nodeId4]
  parameters := [⟨"query", .TString⟩, ⟨"max_papers", .TInt⟩]
}

-- Layer 1 structural theorems
theorem sc_writesConsistent :
    searchCitationsGraph.allWritesConsistent = true := by native_decide
theorem sc_readsResolvable :
    searchCitationsGraph.allReadResolvable = true := by native_decide
theorem sc_edgesValid :
    searchCitationsGraph.edgesValid = true := by native_decide
theorem sc_entryValid :
    searchCitationsGraph.entryNodeValid = true := by native_decide
theorem sc_exitsValid :
    searchCitationsGraph.exitNodesValid = true := by native_decide
theorem sc_exitsReachable :
    searchCitationsGraph.allExitsReachable = true := by native_decide
theorem sc_noOrphans :
    searchCitationsGraph.noOrphanNodes = true := by native_decide


/-
========================================================================
SECTION F: COMPLETE SEMANTIC GRAPH
========================================================================
-/

def searchCitationsSemanticGraph : SemanticWorkflowGraph := {
  baseGraph := searchCitationsGraph
  paramNode := sc_paramNode
  semanticNodes := [
    sc_semNode0,
    sc_semNode1,
    sc_semNode2,   -- postcond: predicateAnd (...) (.ext sc_dictValuesPredicateKey)
    sc_semNode3,   -- precond: .ext sc_dictValuesPredicateKey ← needs registry
    sc_semNode4
  ]
  loopNodes := []
  conditionalNodes := []
  specInvariant := by decide
}


/-
========================================================================
SECTION F.1: SEMANTIC STATE SPACE AFTER EACH NODE
========================================================================
-/

#eval do
  let semNodes := searchCitationsSemanticGraph.semanticNodes
  let paramPost := searchCitationsSemanticGraph.paramNode.postcondVariables
  IO.println "\n============================================================"
  IO.println "SEMANTIC STATE SPACE TRACE: search_citations"
  IO.println "============================================================"
  IO.println "\n--- Initial State (from parameters) ---"
  for p in paramPost do
    IO.println s!"  ✓ {p}"
  let mut state : List VariablePredicateRequirement := paramPost
  for node in semNodes do
    let name := node.baseNode.name.getD "(unnamed)"
    let nodeId := node.baseNode.id
    IO.println s!"\n--- After Node {nodeId}: \"{name}\" ---"
    -- Check preconditions against current state
    IO.println "  Preconditions:"
    for p in node.precondVariables do
      let satisfied := state.any (fun s => s.satisfies p)
      let mark := if satisfied then "✓" else "✗"
      IO.println s!"    {mark} requires: {p}"
    -- Show new facts established
    IO.println "  Postconditions (new facts):"
    for p in node.postcondVariables do
      IO.println s!"    + establishes: {p}"
    -- Update cumulative state: add new postconditions
    for p in node.postcondVariables do
      unless state.any (fun s => s == p) do
        state := state ++ [p]
    IO.println s!"  Cumulative State ({state.length} predicates):"
    for p in state do
      IO.println s!"    {p}"
  IO.println s!"\n============================================================"
  IO.println s!"Final state: {state.length} predicates established"
  IO.println "============================================================"


/-
========================================================================
SECTION G: VERIFICATION WITH REGISTRY
========================================================================
-/

-- Test: verify should succeed
#eval! do
  let result := searchCitationsSemanticGraph.verify searchCitationsRegistry
  IO.println (describeGraphVerificationResult result)
-- Expected: ✓ Graph verification successful!

-- Sanity check: empty registry should FAIL because Node 3 precond requires
-- .ext sc_dictValuesPredicateKey and empty registry doesn't know ext semantics
#eval do
  let result := searchCitationsSemanticGraph.verify emptyRegistry
  IO.println s!"Without registry: {describeGraphVerificationResult result}"
-- Expected: ✗ failure at set_formatted_citations, missing .ext predicate

/-- Main theorem: search_citations is semantically sound under searchCitationsRegistry.

    Proof chain:
    1. native_decide evaluates isSemanticallySoundBool → verify → Bool = true
    2. The critical step is Node 2 → Node 3:
         sc_semNode2 postcond: predicateAnd (matchesJsonSchema .jObject [])
                                            (.ext sc_dictValuesPredicateKey)
         sc_semNode3 precond:  .ext sc_dictValuesPredicateKey
         compatibleWithRegistry: (p₁ ∧ p₂) → p₂ (And-Elim) then key equality → true
    3. DictAllValuesPredicate.toPropImpl bridges to real Prop:
         allDictValuesSatisfy (basePredToProp combinedPred) env "all_citations"
    So the verification is sound end-to-end, not just a Bool coincidence. -/
theorem search_citations_semantically_sound :
    searchCitationsSemanticGraph.isSemanticallySoundBool
      searchCitationsRegistry = true := by
  native_decide

end AgenticKernel
