import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticLayer

namespace AgenticKernel

/-
================================================================================
STATIC VERIFICATION: loop_swe_agent_bench_lite

Source: YAML workflow
Goal: Given an issue description from a github repo, debug and prepare a
      final patch.diff that solves the issue.
Parameters: ['code_path', 'memory_file', 'operation_rule']

Workflow Structure:
  Node   0: step             [SPEC] "read_README"
          reads:  code_path, memory_file
          writes: (implicit knowledge)
  Node   1: step             [SPEC] "analyze_codebase"
          reads:  code_path, memory_file
          writes: (implicit knowledge)
  Node   2: setVariable      [DET]  "set_iter"
          reads:  (none)
          writes: iter
  Node   3: whileLoop        [LOOP] "while_loop"
          condition: "1 > 0" (infinite loop)
          reads:  iter
          writes: (none)
  Node   4: conditional      [DET]  "check_iter"
          reads:  iter
          writes: (none)
  Node   5: step             [SPEC] "first_iteration_analysis" (then branch)
          reads:  memory_file, code_path
          writes: (implicit plan)
  Node   6: step             [SPEC] "normal_iteration" (else branch)
          reads:  memory_file, code_path, iter
          writes: (implicit plan)
  Node   7: step             [SPEC] "main_step"
          reads:  memory_file, code_path, operation_rule
          writes: (implicit result)
  Node   8: step             [SPEC] "save_analysis"
          reads:  memory_file, iter
          writes: (implicit saved progress)
  Node   9: incrementVariable [DET] "increment_iter"
          reads:  iter
          writes: iter
  Node  10: setVariable      [DET]  "set_prev"
          reads:  iter
          writes: prev

  Control flow edges:
    seqEdge      0 → 1
    seqEdge      1 → 2
    seqEdge      2 → 3
    loopEdge     3 → body:4, exit:3 (infinite loop)
    branchEdge   4 → then:5, else:6
    seqEdge      5 → 7
    seqEdge      6 → 7
    seqEdge      7 → 8
    seqEdge      8 → 9
    seqEdge      9 → 10
    loopBackEdge 10 → 3
================================================================================
-/


/-
========================================================================
STEP 1: TRANSLATE YAML INTO WORKFLOW GRAPH (Layer 1)
========================================================================
-/

-- Node IDs
def swe_nodeId_readReadme : NodeId := ⟨0⟩
def swe_nodeId_analyze : NodeId := ⟨1⟩
def swe_nodeId_setIter : NodeId := ⟨2⟩
def swe_nodeId_whileHeader : NodeId := ⟨3⟩
def swe_nodeId_ifCond : NodeId := ⟨4⟩
def swe_nodeId_firstIter : NodeId := ⟨5⟩
def swe_nodeId_normalIter : NodeId := ⟨6⟩
def swe_nodeId_mainStep : NodeId := ⟨7⟩
def swe_nodeId_saveAnalysis : NodeId := ⟨8⟩
def swe_nodeId_increment : NodeId := ⟨9⟩
def swe_nodeId_setPrev : NodeId := ⟨10⟩

-- Node 0: step "read_README"
def swe_node_readReadme : WorkflowNode := {
  id := swe_nodeId_readReadme
  name := some "read_README"
  stepType := .step
  reads := [⟨"code_path", .TString⟩, ⟨"memory_file", .TString⟩]
  writes := []
  llmInstruction := some "NOTE: Memory file at {{memory_file}}\n\nGiven the codebase located at {{code_path}}\n\nRead the README.md to get familiar with the repo, record the usage of the repo, quick start, how to run tests, etc, save them into the memory with proper key and tags."
}

-- Node 1: step "analyze_codebase"
def swe_node_analyze : WorkflowNode := {
  id := swe_nodeId_analyze
  name := some "analyze_codebase"
  stepType := .step
  reads := [⟨"code_path", .TString⟩, ⟨"memory_file", .TString⟩]
  writes := []
  llmInstruction := some "NOTE: Memory file at {{memory_file}}\n\nGiven the codebase located at {{code_path}}\n\nPlease explore and analyze the code base based on the pr_description you received from system prompt.\n\nRecord at least 5 key factors, usage guide, or knowledge that you consider important and necessary to remember, and save them using the memory file with proper key and tags."
}

-- Node 2: setVariable "iter = 1"
def swe_node_setIter : WorkflowNode := {
  id := swe_nodeId_setIter
  name := some "set_iter"
  stepType := .setVariable
  reads := []
  writes := [⟨"iter", .TInt⟩]
  llmInstruction := none
}

-- Node 3: whileLoop header "while 1 > 0"
def swe_node_whileHeader : WorkflowNode := {
  id := swe_nodeId_whileHeader
  name := some "while_loop"
  stepType := .whileLoop
  reads := [⟨"iter", .TInt⟩]
  writes := []
  llmInstruction := none
}

-- Node 4: conditional "if iter == 1"
def swe_node_ifCond : WorkflowNode := {
  id := swe_nodeId_ifCond
  name := some "check_iter"
  stepType := .conditional
  reads := [⟨"iter", .TInt⟩]
  writes := []
  llmInstruction := none
}

-- Node 5: step "first_iteration_analysis" (then branch)
def swe_node_firstIter : WorkflowNode := {
  id := swe_nodeId_firstIter
  name := some "first_iteration_analysis"
  stepType := .step
  reads := [⟨"memory_file", .TString⟩, ⟨"code_path", .TString⟩]
  writes := []
  llmInstruction := some "NOTE 1: Memory file at {{memory_file}}\nNOTE 2: Codebase locate at {{code_path}}\n\n## Memory Retrieval and Context Building\nUse memory tool to search for repository knowledge using tag \"sqlfluff\", i.e. memory(\"search\", tags=\"sqlfluff\")\n\n## FIRST ITERATION - Deep Analysis\nPerform comprehensive initial analysis:\n1. Understand the issue thoroughly\n2. Identify likely root causes (rank top 3)\n3. Plan investigation strategy\n4. Output: 400-600 words with detailed reasoning"
}

-- Node 6: step "normal_iteration" (else branch)
def swe_node_normalIter : WorkflowNode := {
  id := swe_nodeId_normalIter
  name := some "normal_iteration"
  stepType := .step
  reads := [⟨"memory_file", .TString⟩, ⟨"code_path", .TString⟩, ⟨"iter", .TInt⟩]
  writes := []
  llmInstruction := some "NOTE 1: Memory file at {{memory_file}}\nNOTE 2: Codebase locate at {{code_path}}\n\n## ITERATION {{iter}} - Focused Action\nQuick context: memory(\"search\", tags=\"iter_{{prev}}\")\n\nOutput (100-200 words):\n\nITER {{iter}}:\nLAST: [previous action + result]\nNEXT: [EXPLORE/TEST/MODIFY/VERIFY] - [target]\nWHY: [reasoning]\nCMD: [exact command]\nEXPECT: [outcome]"
}

-- Node 7: step "main_step"
def swe_node_mainStep : WorkflowNode := {
  id := swe_nodeId_mainStep
  name := some "main_step"
  stepType := .step
  reads := [⟨"memory_file", .TString⟩, ⟨"code_path", .TString⟩, ⟨"operation_rule", .TString⟩]
  writes := []
  llmInstruction := some "NOTE 1: Memory file at {{memory_file}}\nNOTE 2: Your changes should be in the codebase at: {{code_path}}\nNOTE 3: If you need to interact with the file in the codebase, FOLLOW these operation rule, otherwise use any tool you want: {{operation_rule}}\n\nFollow the previous step's analysis, instructions, and solve the issue step by step using bash command."
}

-- Node 8: step "save_analysis"
def swe_node_saveAnalysis : WorkflowNode := {
  id := swe_nodeId_saveAnalysis
  name := some "save_analysis"
  stepType := .step
  reads := [⟨"memory_file", .TString⟩, ⟨"iter", .TInt⟩]
  writes := []
  llmInstruction := some "NOTE: Memory file at {{memory_file}}\n\nUse memory(\"store\") to save your current debugging progress and analysis, using tag iter_{{iter}}.\n\nAfter save, end this step immediately."
}

-- Node 9: incrementVariable "iter"
def swe_node_increment : WorkflowNode := {
  id := swe_nodeId_increment
  name := some "increment_iter"
  stepType := .incrementVariable
  reads := [⟨"iter", .TInt⟩]
  writes := [⟨"iter", .TInt⟩]
  llmInstruction := none
}

-- Node 10: setVariable "prev = iter - 1"
def swe_node_setPrev : WorkflowNode := {
  id := swe_nodeId_setPrev
  name := some "set_prev"
  stepType := .setVariable
  reads := [⟨"iter", .TInt⟩]
  writes := [⟨"prev", .TInt⟩]
  llmInstruction := none
}

-- The complete workflow graph
def sweWorkflowGraph : WorkflowGraph := {
  nodes := [
    swe_node_readReadme,
    swe_node_analyze,
    swe_node_setIter,
    swe_node_whileHeader,
    swe_node_ifCond,
    swe_node_firstIter,
    swe_node_normalIter,
    swe_node_mainStep,
    swe_node_saveAnalysis,
    swe_node_increment,
    swe_node_setPrev
  ]
  edges := [
    .seqEdge swe_nodeId_readReadme swe_nodeId_analyze,
    .seqEdge swe_nodeId_analyze swe_nodeId_setIter,
    .seqEdge swe_nodeId_setIter swe_nodeId_whileHeader,
    -- Loop structure
    .loopEdge swe_nodeId_whileHeader swe_nodeId_ifCond swe_nodeId_whileHeader,
    .branchEdge swe_nodeId_ifCond swe_nodeId_firstIter swe_nodeId_normalIter,
    .seqEdge swe_nodeId_firstIter swe_nodeId_mainStep,
    .seqEdge swe_nodeId_normalIter swe_nodeId_mainStep,
    .seqEdge swe_nodeId_mainStep swe_nodeId_saveAnalysis,
    .seqEdge swe_nodeId_saveAnalysis swe_nodeId_increment,
    .seqEdge swe_nodeId_increment swe_nodeId_setPrev,
    .loopBackEdge swe_nodeId_setPrev swe_nodeId_whileHeader
  ]
  entry := swe_nodeId_readReadme
  exits := []  -- Infinite loop, no normal exit
  parameters := [
    ⟨"code_path", .TString⟩,
    ⟨"memory_file", .TString⟩,
    ⟨"operation_rule", .TString⟩
  ]
}


/-
========================================================================
STEP 2: STRUCTURAL CHECKS (computable, via #eval)
========================================================================
-/

-- 2a. Step-type consistency
#eval swe_node_readReadme.writesConsistent   -- expected: true
#eval swe_node_analyze.writesConsistent      -- expected: true
#eval swe_node_setIter.writesConsistent      -- expected: true
#eval swe_node_whileHeader.writesConsistent  -- expected: true
#eval swe_node_ifCond.writesConsistent       -- expected: true
#eval swe_node_firstIter.writesConsistent    -- expected: true
#eval swe_node_normalIter.writesConsistent   -- expected: true
#eval swe_node_mainStep.writesConsistent     -- expected: true
#eval swe_node_saveAnalysis.writesConsistent -- expected: true
#eval swe_node_increment.writesConsistent    -- expected: true
#eval swe_node_setPrev.writesConsistent      -- expected: true

-- 2b. Execution type classification
#eval swe_node_readReadme.execType   -- expected: unstructured
#eval swe_node_analyze.execType      -- expected: unstructured
#eval swe_node_setIter.execType      -- expected: deterministic
#eval swe_node_whileHeader.execType  -- expected: deterministic
#eval swe_node_ifCond.execType       -- expected: deterministic
#eval swe_node_firstIter.execType    -- expected: unstructured
#eval swe_node_normalIter.execType   -- expected: unstructured
#eval swe_node_mainStep.execType     -- expected: unstructured
#eval swe_node_saveAnalysis.execType -- expected: unstructured
#eval swe_node_increment.execType    -- expected: deterministic
#eval swe_node_setPrev.execType      -- expected: deterministic

-- 2c. Which nodes need semantic specs?
#eval swe_node_readReadme.needSemanticSpec   -- expected: true
#eval swe_node_analyze.needSemanticSpec      -- expected: true
#eval swe_node_setIter.needSemanticSpec      -- expected: false
#eval swe_node_whileHeader.needSemanticSpec  -- expected: false
#eval swe_node_ifCond.needSemanticSpec       -- expected: false
#eval swe_node_firstIter.needSemanticSpec    -- expected: true
#eval swe_node_normalIter.needSemanticSpec   -- expected: true
#eval swe_node_mainStep.needSemanticSpec     -- expected: true
#eval swe_node_saveAnalysis.needSemanticSpec -- expected: true
#eval swe_node_increment.needSemanticSpec    -- expected: false
#eval swe_node_setPrev.needSemanticSpec      -- expected: false


/-
========================================================================
STEP 3: GRAPH-LEVEL PROPERTIES (computable, via #eval)
========================================================================
-/

#eval sweWorkflowGraph.allWritesConsistent    -- expected: true
-- NOTE: allReadResolvable uses `reachable` which can cause infinite loops
-- in graphs with cycles (like while loops). Skipping this check for loop graphs.
-- #eval sweWorkflowGraph.allReadResolvable   -- expected: true (with loop consideration)
#eval sweWorkflowGraph.edgesValid             -- expected: true
#eval sweWorkflowGraph.entryNodeValid         -- expected: true
#eval sweWorkflowGraph.exitNodesValid         -- expected: true (empty exits for infinite loop)


/-
========================================================================
STEP 4: VERIFICATION SUMMARY
========================================================================
-/

#eval sweWorkflowGraph.verificationSummary
#eval (sweWorkflowGraph.nodesNeedingSpecs).map (fun n => (n.id, n.name))
#eval (sweWorkflowGraph.deterministicNodes).map (fun n => (n.id, n.name))


/-
========================================================================
STEP 5: STRUCTURAL WELL-FORMEDNESS THEOREMS
========================================================================
-/

/-- All writes are consistent with step-type rules -/
theorem swe_bench_writesConsistent :
    sweWorkflowGraph.allWritesConsistent = true := by native_decide

/-- All edges reference valid node ids -/
theorem swe_bench_edgesValid :
    sweWorkflowGraph.edgesValid = true := by native_decide

/-- Entry node exists in the graph -/
theorem swe_bench_entryValid :
    sweWorkflowGraph.entryNodeValid = true := by native_decide

/-- 6 out of 11 nodes need semantic specs -/
theorem swe_bench_specCount :
    sweWorkflowGraph.nodesNeedingSpecs.length = 6 := by native_decide


/-
========================================================================
STEP 6: SEMANTIC VERIFICATION (using new architecture)
========================================================================
-/

/-
Semantic Verification Layer:
  - Define semantic specs for each node that requires them
  - Define loop invariant for the while loop
  - Verify precondition/postcondition chaining
  - Verify loop invariant establishment and preservation
-/

-- Parameter node: establishes initial facts about parameters and tools
def swe_paramNode : SemanticWorkflowNode := {
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
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsNonEmptyString "operation_rule",
    varIsValidTool "term_send",
    varIsValidTool "term_read",
    varIsValidTool "memory"
  ]
}

-- Node 0: read_README
def swe_semNode_readReadme : SemanticWorkflowNode := {
  baseNode := swe_node_readReadme
  precondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsValidTool "memory"
  ]
  postcondVariables := [
    varIsNonEmptyString "readme_knowledge"
  ]
}

-- Node 1: analyze_codebase
def swe_semNode_analyze : SemanticWorkflowNode := {
  baseNode := swe_node_analyze
  precondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsValidTool "memory"
  ]
  postcondVariables := [
    varIsNonEmptyString "codebase_analysis"
  ]
}

-- Node 2: set_variable iter=1 (deterministic)
def swe_semNode_setIter : SemanticWorkflowNode := {
  baseNode := swe_node_setIter
  precondVariables := []
  postcondVariables := [
    varIsInt "iter"
  ]
}

-- Node 3: while_loop header - KEY: uses SemanticLoopNode with loopInvariant!
def swe_loopNode_while : SemanticLoopNode := {
  baseNode := swe_node_whileHeader
  precondVariables := [
    varIsInt "iter"
  ]
  postcondVariables := []
  -- Loop invariant: what must hold at start of EVERY iteration
  loopInvariant := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsNonEmptyString "operation_rule",
    varIsInt "iter",
    varIsValidTool "term_send",
    varIsValidTool "term_read",
    varIsValidTool "memory"
  ]
  -- Termination: Agent outputs "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT" in main_step
  terminationSpec := .llmControlledExit swe_nodeId_mainStep "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
  -- Exit postconditions: what must hold when loop terminates via sentinel
  -- Hoare logic: exitFacts = loopInvariant ∧ exitPostconditions
  exitPostconditions := [
    varContainsSentinel "final_output" "COMPLETE_TASK_AND_SUBMIT",
    varTaskCompleted "task_status"
  ]
}

-- Node 4: check_iter (conditional, deterministic)
def swe_semNode_ifCond : SemanticWorkflowNode := {
  baseNode := swe_node_ifCond
  precondVariables := [
    varIsInt "iter"
  ]
  postcondVariables := [
    varIsInt "iter"
  ]
}

-- Node 5: first_iteration_analysis (then branch)
def swe_semNode_firstIter : SemanticWorkflowNode := {
  baseNode := swe_node_firstIter
  precondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsValidTool "memory"
  ]
  postcondVariables := [
    varIsNonEmptyString "iteration_plan"
  ]
}

-- Node 6: normal_iteration (else branch)
def swe_semNode_normalIter : SemanticWorkflowNode := {
  baseNode := swe_node_normalIter
  precondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsInt "iter",
    varIsValidTool "memory"
  ]
  postcondVariables := [
    varIsNonEmptyString "iteration_plan"
  ]
}

-- Node 7: main_step
def swe_semNode_mainStep : SemanticWorkflowNode := {
  baseNode := swe_node_mainStep
  precondVariables := [
    varIsValidFilePath "code_path",
    varIsValidFilePath "memory_file",
    varIsNonEmptyString "operation_rule",
    varIsValidTool "term_send",
    varIsValidTool "term_read"
  ]
  postcondVariables := [
    varIsNonEmptyString "step_result"
  ]
}

-- Node 8: save_analysis
def swe_semNode_saveAnalysis : SemanticWorkflowNode := {
  baseNode := swe_node_saveAnalysis
  precondVariables := [
    varIsValidFilePath "memory_file",
    varIsInt "iter",
    varIsValidTool "memory"
  ]
  postcondVariables := [
    varIsNonEmptyString "saved_progress"
  ]
}

-- Node 9: increment_iter (deterministic)
def swe_semNode_increment : SemanticWorkflowNode := {
  baseNode := swe_node_increment
  precondVariables := [
    varIsInt "iter"
  ]
  postcondVariables := [
    varIsInt "iter"  -- iter still exists after increment
  ]
}

-- Node 10: set_prev
-- CRITICAL: postcond must imply loopInvariant for preservation!
def swe_semNode_setPrev : SemanticWorkflowNode := {
  baseNode := swe_node_setPrev
  precondVariables := [
    varIsInt "iter"
  ]
  postcondVariables := [
    varIsInt "prev",
    varIsInt "iter"  -- iter preserved (frame rule keeps the rest)
  ]
}

-- Complete Semantic Workflow Graph
def sweSemanticGraph : SemanticWorkflowGraph := {
  baseGraph := sweWorkflowGraph
  paramNode := swe_paramNode
  semanticNodes := [
    swe_semNode_readReadme,
    swe_semNode_analyze,
    swe_semNode_setIter,
    swe_semNode_ifCond,
    swe_semNode_firstIter,
    swe_semNode_normalIter,
    swe_semNode_mainStep,
    swe_semNode_saveAnalysis,
    swe_semNode_increment,
    swe_semNode_setPrev
  ]
  loopNodes := [swe_loopNode_while]  -- Loop node separately!
  specInvariant := by decide
}


/-
========================================================================
STEP 7: SEMANTIC VERIFICATION TESTS
========================================================================
-/

-- Test: Get loop headers
#eval! sweSemanticGraph.getLoopHeaders
-- Expected: [⟨3⟩]

-- Test: Topological sort ignoring back edges
#eval! sweSemanticGraph.topologicalSortIgnoringBackEdges
-- Expected: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

-- Test: Find predecessors ignoring back edge for while header
#eval! sweSemanticGraph.findPredecessorsIgnoringBackEdge swe_nodeId_whileHeader
-- Expected: [⟨2⟩] (only set_iter, not set_prev via back edge)

-- Test: Find loop body end
#eval! sweSemanticGraph.findLoopBodyEnd swe_nodeId_whileHeader
-- Expected: some ⟨10⟩ (set_prev)

-- Test: Verify the semantic graph


#eval! do
  let result := sweSemanticGraph.verify
  IO.println s!"Without registry: {describeGraphVerificationResult result}"
-- Expected: ✓ Graph verification successful!


/-
========================================================================
STEP 8: SEMANTIC SOUNDNESS THEOREM
========================================================================
-/

/-- Semantic soundness theorem for SWE-bench workflow -/
theorem swe_bench_semantically_sound :
    sweSemanticGraph.isSemanticallySoundBool = true := by
  native_decide


end AgenticKernel
