import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer

namespace AgenticKernel

/-
================================================================================
STATIC VERIFICATION: extract_single_citation_module

Source: parsed_task.json
Goal: Extract citation information from a single downloaded paper file
Parameters: ['url', 'file_path']
Total nodes: 7
Entry: Node 0
Exits: [6]

  Node   0: step             [SPEC] "extract_paper_title"
          reads:  file_path
          writes: paper_title
  Node   1: step             [SPEC] "extract_bibtex_by_tool"
          reads:  paper_title, url
          writes: bibtex_citation
  Node   2: step             [SPEC] "extract_abstract_by_tool"
          reads:  paper_title, url
          writes: abstract
  Node   3: conditional      [DET]  "check_abstract == None"
          reads:  abstract
          writes: (none)
  Node   4: step             [SPEC] "extract_abstract_by_read_file"
          reads:  file_path
          writes: abstract
  Node   5: step             [SPEC] "prepare_return_dict"
          reads:  abstract, bibtex_citation, file_path, paper_title
          writes: return_dict
  Node   6: returnValue      [DET]  "return_result"
          reads:  return_dict
          writes: (none)

  Control flow edges:
    seqEdge     0 → 1
    seqEdge     1 → 2
    seqEdge     2 → 3
    branchEdge  3 → then:4, else:5
    seqEdge     4 → 5
    seqEdge     5 → 6
================================================================================
-/


/-
========================================================================
STEP 1: TRANSLATE YAML INTO WORKFLOW GRAPH
========================================================================
-/

-- Node IDs
def writer_nodeId0 : NodeId := ⟨0⟩
def writer_nodeId1 : NodeId := ⟨1⟩
def writer_nodeId2 : NodeId := ⟨2⟩
def writer_nodeId3 : NodeId := ⟨3⟩
def writer_nodeId4 : NodeId := ⟨4⟩
def writer_nodeId5 : NodeId := ⟨5⟩
def writer_nodeId6 : NodeId := ⟨6⟩

-- Node 0: step "extract_paper_title"
def writer_node0 : WorkflowNode := {
  id       := writer_nodeId0
  name     := some "extract_paper_title"
  stepType := .step
  reads    := [⟨"file_path", .TString⟩]
  writes   := [⟨"paper_title", .TString⟩]
  llmInstruction := some "NOTE: Use the EXACT path provided below, DO NOT add any parent directories !!!\n\nRead the first 3000 bytes from the paper file at: {{file_path}}\n\nExtract ONLY the title of the paper. The title is usually:\n- At the top of the first page\n- In a larger or bold font\n- Above the author names\n\nReturn ONLY the extracted title as a single line of text with no extra commentary or formatting.\n"
}

-- Node 1: step "extract_bibtex_by_tool"
def writer_node1 : WorkflowNode := {
  id       := writer_nodeId1
  name     := some "extract_bibtex_by_tool"
  stepType := .step
  reads    := [⟨"paper_title", .TString⟩, ⟨"url", .TString⟩]
  writes   := [⟨"bibtex_citation", .TString⟩]
  llmInstruction := some "Use get_bibtex_from_url tool to retrieve the bibtex using the given url: {{url}} and the paper title: {{paper_title}}\n\nONLY return the content of the bibtex with no extra commentary.\n"
}

-- Node 2: step "extract_abstract_by_tool"
def writer_node2 : WorkflowNode := {
  id       := writer_nodeId2
  name     := some "extract_abstract_by_tool"
  stepType := .step
  reads    := [⟨"paper_title", .TString⟩, ⟨"url", .TString⟩]
  writes   := [⟨"abstract", .TString⟩]
  llmInstruction := some "Use get_abstract_from_url tool to retrieve the bibtex using the given url: {{url}} and the paper title: {{paper_title}}\n\nONLY return the content of the abstract with no extra commentary, if no abstract retreived, ONLY return None.\n"
}

-- Node 3: conditional "check_abstract == None"
def writer_node3 : WorkflowNode := {
  id       := writer_nodeId3
  name     := some "check_abstract == None"
  stepType := .conditional
  reads    := [⟨"abstract", .TString⟩]
  writes   := []
  llmInstruction := none
}

-- Node 4: step "extract_abstract_by_read_file"
def writer_node4 : WorkflowNode := {
  id       := writer_nodeId4
  name     := some "extract_abstract_by_read_file"
  stepType := .step
  reads    := [⟨"file_path", .TString⟩]
  writes   := [⟨"abstract", .TString⟩]
  llmInstruction := some "NOTE: Use the EXACT path provided below, DO NOT add any parent directories !!!\n\nRead the first 5000 bytes from the paper file at: {{file_path}}\n\nExtract ONLY the abstract of the paper. The title is usually:\n- At the first page\n- Has a section header of abstract\n- Below the author names\n\nReturn ONLY the extracted abstract as a single line of text with no extra commentary or formatting.\n"
}

-- Node 5: step "prepare_return_dict"
def writer_node5 : WorkflowNode := {
  id       := writer_nodeId5
  name     := some "prepare_return_dict"
  stepType := .step
  reads    := [⟨"abstract", .TString⟩, ⟨"bibtex_citation", .TString⟩, ⟨"file_path", .TString⟩, ⟨"paper_title", .TString⟩]
  writes   := [⟨"return_dict", .TString⟩]
  llmInstruction := some "Return as python compatible JSON dict:\n\n{\n    \"bibtex\": \"{{bibtex_citation}}\"\",\n    \"file_path\": \"{{file_path}}\"\n    \"title\": \"{{paper_title}}\"\n    \"abstract\": {{abstract}}\n}\n\nONLY return the python dict with no extra commentary.\n"
}

-- Node 6: returnValue "return_result"
def writer_node6 : WorkflowNode := {
  id       := writer_nodeId6
  name     := some "return_result"
  stepType := .returnValue
  reads    := [⟨"return_dict", .TString⟩]
  writes   := []
  llmInstruction := none
}

-- The complete workflow graph
def writerGraph : WorkflowGraph := {
  nodes      := [
    writer_node0,
    writer_node1,
    writer_node2,
    writer_node3,
    writer_node4,
    writer_node5,
    writer_node6
  ]
  edges      := [
    .seqEdge writer_nodeId0 writer_nodeId1,
    .seqEdge writer_nodeId1 writer_nodeId2,
    .seqEdge writer_nodeId2 writer_nodeId3,
    .branchEdge writer_nodeId3 writer_nodeId4 writer_nodeId5,
    .seqEdge writer_nodeId4 writer_nodeId5,
    .seqEdge writer_nodeId5 writer_nodeId6
  ]
  entry      := writer_nodeId0
  exits      := [writer_nodeId6]
  parameters := [⟨"url", .TString⟩, ⟨"file_path", .TString⟩]
}


/-
========================================================================
STEP 2: STRUCTURAL CHECKS (computable, via #eval)
========================================================================
-/

-- 2a. Step-type consistency
#eval writer_node0.writesConsistent  -- expected: true
#eval writer_node1.writesConsistent  -- expected: true
#eval writer_node2.writesConsistent  -- expected: true
#eval writer_node3.writesConsistent  -- expected: true
#eval writer_node4.writesConsistent  -- expected: true
#eval writer_node5.writesConsistent  -- expected: true
#eval writer_node6.writesConsistent  -- expected: true

-- 2b. Execution type classification
#eval writer_node0.execType  -- expected: unstructured
#eval writer_node1.execType  -- expected: unstructured
#eval writer_node2.execType  -- expected: unstructured
#eval writer_node3.execType  -- expected: deterministic
#eval writer_node4.execType  -- expected: unstructured
#eval writer_node5.execType  -- expected: unstructured
#eval writer_node6.execType  -- expected: deterministic

-- 2c. Which nodes need semantic specs?
#eval writer_node0.needSemanticSpec  -- expected: true
#eval writer_node1.needSemanticSpec  -- expected: true
#eval writer_node2.needSemanticSpec  -- expected: true
#eval writer_node3.needSemanticSpec  -- expected: false
#eval writer_node4.needSemanticSpec  -- expected: true
#eval writer_node5.needSemanticSpec  -- expected: true
#eval writer_node6.needSemanticSpec  -- expected: false

-- 2d. Type-check the sequential path
#eval match typeCheckSequence
  [writer_node0, writer_node1, writer_node2, writer_node3, writer_node4, writer_node5, writer_node6]
  [⟨"url", .TString⟩, ⟨"file_path", .TString⟩] with
  | .ok ctx => s!"✓ Type-checks. Final context has {ctx.length} vars"
  | .error msg => s!"✗ Type error: {msg}"


/-
========================================================================
STEP 3: GRAPH-LEVEL PROPERTIES (computable, via #eval)
========================================================================
-/

#eval writerGraph.allWritesConsistent    -- expected: true
#eval writerGraph.allReadResolvable      -- expected: true
#eval writerGraph.edgesValid             -- expected: true
#eval writerGraph.entryNodeValid         -- expected: true
#eval writerGraph.exitNodesValid         -- expected: true
#eval writerGraph.allExitsReachable      -- expected: true
#eval writerGraph.noOrphanNodes          -- expected: true
#eval writerGraph.returnType


/-
========================================================================
STEP 4: VERIFICATION SUMMARY
========================================================================
-/

#eval writerGraph.verificationSummary
#eval (writerGraph.nodesNeedingSpecs).map (fun n => (n.id, n.name))
#eval (writerGraph.deterministicNodes).map (fun n => (n.id, n.name))


/-
========================================================================
STEP 5: STRUCTURAL WELL-FORMEDNESS THEOREMS
========================================================================
-/

/-- All writes are consistent with step-type rules -/
theorem extract_single_citation_module_writesConsistent :
    writerGraph.allWritesConsistent = true := by native_decide

/-- All reads are resolvable from predecessors or parameters -/
theorem extract_single_citation_module_readsResolvable :
    writerGraph.allReadResolvable = true := by native_decide

/-- All edges reference valid node ids -/
theorem extract_single_citation_module_edgesValid :
    writerGraph.edgesValid = true := by native_decide

/-- Entry node exists in the graph -/
theorem extract_single_citation_module_entryValid :
    writerGraph.entryNodeValid = true := by native_decide

/-- Exit nodes exist in the graph -/
theorem extract_single_citation_module_exitsValid :
    writerGraph.exitNodesValid = true := by native_decide

/-- All exit nodes are reachable from entry -/
theorem extract_single_citation_module_exitsReachable :
    writerGraph.allExitsReachable = true := by native_decide

/-- No orphan nodes -/
theorem extract_single_citation_module_noOrphans :
    writerGraph.noOrphanNodes = true := by native_decide

/-- The sequential path type-checks with the given parameters -/
theorem extract_single_citation_module_seqPath_typeChecks :
    ∃ ctx, typeCheckSequence
      [writer_node0, writer_node1, writer_node2, writer_node3, writer_node4, writer_node5, writer_node6]
      [⟨"url", .TString⟩, ⟨"file_path", .TString⟩] = .ok ctx := by
  exact ⟨_, rfl⟩

/-- 5 out of 7 nodes need semantic specs -/
theorem extract_single_citation_module_specCount :
    writerGraph.nodesNeedingSpecs.length = 5 := by native_decide


/-
========================================================================
STEP 6: SEMANTIC VERIFICATION (using new architecture)
========================================================================
-/

/-
Semantic Verification Layer:
  - Define semantic specs for each node that requires them
  - Verify precondition/postcondition chaining
  - Prove semantic soundness
-/

-- Define the return dict JSON schema
def extractCitationReturnDictSchema : JsonSchema :=
  .jObject [
    ("bibtex", .jString),
    ("file_path", .jString),
    ("title", .jString),
    ("abstract", .jString)
  ]

-- Parameter node: establishes initial facts about parameters and tools
def extractCitation_paramNode : SemanticWorkflowNode := {
  baseNode := {
    id := ⟨20041122⟩  -- Special ID for parameter node
    name := some "parameters"
    stepType := .setVariable
    reads := []
    writes := []
    llmInstruction := none
  }
  precondVariables := []
  postcondVariables := [
    varIsValidURL "url",
    varIsValidFilePath "file_path",
    varIsValidTool "fs_read",
    varIsValidTool "get_bibtex_from_url",
    varIsValidTool "get_abstract_from_url"
  ]
}

-- Node 0: extract_paper_title
def extractCitation_semNode0 : SemanticWorkflowNode := {
  baseNode := writer_node0
  precondVariables := [
    varIsValidFilePath "file_path",
    varIsValidTool "fs_read"
  ]
  postcondVariables := [
    varIsNonEmptyString "paper_title"
  ]
}

-- Node 1: extract_bibtex_by_tool
def extractCitation_semNode1 : SemanticWorkflowNode := {
  baseNode := writer_node1
  precondVariables := [
    varIsValidTool "get_bibtex_from_url",
    varIsValidURL "url",
    varIsNonEmptyString "paper_title"
  ]
  postcondVariables := [
    varIsNonEmptyString "bibtex_citation",
    varIsValidBibtex "bibtex_citation"
  ]
}

-- Node 2: extract_abstract_by_tool
def extractCitation_semNode2 : SemanticWorkflowNode := {
  baseNode := writer_node2
  precondVariables := [
    varIsValidTool "get_abstract_from_url",
    varIsValidURL "url",
    varIsNonEmptyString "paper_title"
  ]
  postcondVariables := [
    varIsNonEmptyString "abstract"
  ]
}

-- Node 3: check_abstract == None (conditional node with branch-aware postconditions)
-- This is an if-else conditional that checks whether abstract is None
-- - Then branch (→ Node 4): abstract is None, need to extract from file
-- - Else branch (→ Node 5): abstract is valid (non-empty)
def extractCitation_condNode3 : SemanticConditionalNode := {
  baseNode := writer_node3
  precondVariables := [
    varNameExists "abstract"
  ]
  postcondVariables := [
    -- Default postcondition (used when target doesn't match either branch)
    varNameExists "abstract"
  ]
  thenTargetId := writer_nodeId4  -- Node 4 is the then branch target
  elseTargetId := writer_nodeId5  -- Node 5 is the else branch target
  thenPostcondVariables := [
    -- When condition is TRUE (abstract == None):
    -- abstract exists but may be None/empty - use weak predicate
    varNameExists "abstract"
  ]
  elsePostcondVariables := [
    -- When condition is FALSE (abstract != None):
    -- abstract is valid and non-empty
    varIsNonEmptyString "abstract"
  ]
}

-- Convert to SemanticWorkflowNode for the semanticNodes list
def extractCitation_semNode3 : SemanticWorkflowNode := extractCitation_condNode3.toSemanticWorkflowNode

-- Node 4: extract_abstract_by_read_file (then branch)
def extractCitation_semNode4 : SemanticWorkflowNode := {
  baseNode := writer_node4
  precondVariables := [
    varIsValidFilePath "file_path",
    varIsValidTool "fs_read"
  ]
  postcondVariables := [
    varIsNonEmptyString "abstract"
  ]
}

-- Node 5: prepare_return_dict
def extractCitation_semNode5 : SemanticWorkflowNode := {
  baseNode := writer_node5
  precondVariables := [
    varIsValidBibtex "bibtex_citation",
    varIsValidFilePath "file_path",
    varIsNonEmptyString "paper_title",
    varIsNonEmptyString "abstract"
  ]
  postcondVariables := [
    varIsValidJson "return_dict",
    varIsValidJsonSchema "return_dict" extractCitationReturnDictSchema
  ]
}

-- Node 6: return_result (returnValue, deterministic)
def extractCitation_semNode6 : SemanticWorkflowNode := {
  baseNode := writer_node6
  precondVariables := [
    varIsValidJson "return_dict",
    varIsValidJsonSchema "return_dict" extractCitationReturnDictSchema
  ]
  postcondVariables := []
}

-- Complete Semantic Workflow Graph
def extractCitationSemanticGraph : SemanticWorkflowGraph := {
  baseGraph := writerGraph
  paramNode := extractCitation_paramNode
  semanticNodes := [
    extractCitation_semNode0,
    extractCitation_semNode1,
    extractCitation_semNode2,
    extractCitation_semNode3,
    extractCitation_semNode4,
    extractCitation_semNode5,
    extractCitation_semNode6
  ]
  loopNodes := []
  conditionalNodes := [extractCitation_condNode3]  -- Add conditional node for branch-aware verification
  specInvariant := by decide
}

/-
========================================================================
STEP 7: SEMANTIC VERIFICATION TESTS AND THEOREMS
========================================================================
-/

-- Test: Find predecessors
#eval! extractCitationSemanticGraph.findPredecessors writer_nodeId0
-- Expected: [] (entry node has no predecessors)

#eval! extractCitationSemanticGraph.findPredecessors writer_nodeId5
-- Expected: [3, 4] (node 5 has two predecessors from branching)

-- Test: Topological sort
#eval! extractCitationSemanticGraph.topologicalSortIgnoringBackEdges
-- Expected: Some ordering of [0, 1, 2, 3, 4, 5, 6]

-- Test: Verify the semantic graph
#eval! do
  let result := extractCitationSemanticGraph.verify
  IO.println s!"Without registry: {describeGraphVerificationResult result}"

/-- Semantic soundness theorem for extract_single_citation workflow -/
theorem extract_single_citation_semantically_sound :
    extractCitationSemanticGraph.isSemanticallySoundBool = true := by
  native_decide
