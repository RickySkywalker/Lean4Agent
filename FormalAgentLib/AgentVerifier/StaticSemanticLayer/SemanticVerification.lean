import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.StaticSemanticVariable
import AgentVerifier.StaticSemanticLayer.SemanticGraph


namespace AgenticKernel


/-
This file models the semantic verification layer
-/

/-
# Section 1: Basic verification Data Structures
-/

inductive NodeVerifyResult where
  | success (outputPredicates : List VariablePredicateRequirement)
  | failure (missingPredicateCauseError : VariablePredicateRequirement) (availablePredicates : List VariablePredicateRequirement)
  deriving Repr, BEq, DecidableEq, Inhabited

inductive GraphVerifyResult where
  | success (finalPredicates : List VariablePredicateRequirement)
  | failure
    (failedNodeId : NodeId)
    (failNodeName : String)
    (missingPredicate : VariablePredicateRequirement)
    (availablePredicates : List VariablePredicateRequirement)
  | loopInvariantMissing
    (loopHeaderId : NodeId)
    (nodeName : String)
  | loopInvariantNotEstablished
    (loopHeaderId : NodeId)
    (nodeName : String)
    (missingInvariantPredicate : VariablePredicateRequirement)
    (availablePredicates : List VariablePredicateRequirement)
  | loopInvariantNotPreserved
    (loopHeaderId : NodeId)
    (nodeName : String)
    (missingInvariantPredicate : VariablePredicateRequirement)
    (availableWhenBodyEndsPredicates : List VariablePredicateRequirement)
  /-- Loop termination specification is missing or invalid -/
  | loopTerminationSpecInvalid
    (loopHeaderId : NodeId)
    (nodeName : String)
    (reason : String)
  -- When the topological sort fails (which should not happen in a well-formed graph), we can return an error with the reason for debugging
  | topologicalSortFailed (reason : String)
  deriving Repr, BEq, DecidableEq, Inhabited


/-
# Section 2: Verification Logic
-/

/--
Build for predicateOr chain from the list of PredicateTypes following the below rules:
  1, [p] → p
  2. [p1, p2] → predicateOr p1 p2
  3. [p1, p2, p3, ...] → predicateOr p1 (predicateOr p2 (predicateOr p3 ...))
-/
def buildPredicateOrChain (preds : List PredicateType) : PredicateType :=
  match preds with
  | [] => .nameExists
  | [p] => p
  | p :: rest => .predicateOr p (buildPredicateOrChain rest)


/--
Build a predicateAnd chain from the list of PredicateTypes following the below rules:
  1. [p] → p
  2. [p1, p2] → predicateAnd p1 p2
  3. [p1, p2, p3, ...] → predicateAnd p1 (predicateAnd p2 (predicateAnd p3 ...))
-/
def buildPredicateAndChain (preds : List PredicateType) : PredicateType :=
  match preds with
  | [] => .nameExists
  | [p] => p
  | p :: rest => .predicateAnd p (buildPredicateAndChain rest)


/-- Merge predicates for a single variable across multiple branches.
    Each inner list is one branch's predicates for this variable.
    Returns the merged PredicateType (pOr of pAnd chains). -/
def mergePredicatesForVariable
  (perBranchPreds : List (List PredicateType)): PredicateType :=
  let branchPreds := perBranchPreds.map buildPredicateAndChain
  let uniquePreds := branchPreds.eraseDups
  buildPredicateOrChain uniquePreds


/-- Combine predicate lists from multiple branches using disjunction semantics.

    For each variable:
    1. Only variables present in ALL branches are retained (conservative)
    2. Predicates from different branches are combined with `pOr`
    3. If all branches agree on the same predicate, no `pOr` is introduced

    This correctly models the semantics of branch merge: we know exactly one
    branch executed, so the result satisfies at least one branch's postconditions.

    Note: variables present in only SOME branches are dropped. This is
    conservative but sound — we cannot guarantee anything about a variable
    that might not have been written. -/
def combinePredictsIntersection
  (predLists : List (List VariablePredicateRequirement)) : List VariablePredicateRequirement :=
  match predLists with
  | [] => []
  | [singlePred] => singlePred
  | _ =>
    let numBranches := predLists.length
    -- Collect all variable names mentioned across all branches
    let allVarNames := (predLists.flatMap id).map (·.varName) |>.eraseDups
    -- Only keep variables that appear in ALL branches
    allVarNames.filterMap fun varName =>
      -- For each branch, collect the predicates for this variable
      let perBranchPreds := predLists.map fun branchPreds =>
        (branchPreds.filter (·.varName == varName)).map (·.requiredPredicate)
      -- Only include if variable is present in all branches
      let branchesWithVar := perBranchPreds.filter (!·.isEmpty)
      if branchesWithVar.length == numBranches then
        some ⟨varName, mergePredicatesForVariable branchesWithVar⟩
      else
        none

/-- Verify whether the precondition is satisfied. If the precond is satisfied, then returns none, if not, returns the first failed predicate -/
def checkPrecondSatisfied
  (availablePreds : List VariablePredicateRequirement)
  (precondPreds : List VariablePredicateRequirement) : Option VariablePredicateRequirement :=
  precondPreds.find? fun requiredPred => !availablePreds.any (·.satisfies requiredPred)

/-- Compute the output predicates when it is correctly executed. It will change the newly established preds and keep the unchanged preds. -/
def computeOutputPredicates
  (inputVarPreds : List VariablePredicateRequirement)
  (changedVarPreds : List VariablePredicateRequirement) : List VariablePredicateRequirement :=
  let modifiedVars := changedVarPreds.map (·.varName) |>.eraseDups
  let unchangedVars := inputVarPreds.filter (fun pred => !modifiedVars.contains pred.varName)
  unchangedVars ++ changedVarPreds

-- /--
-- Verification of a single Semantic node by the following steps:
--   1. Collect the NodeId for all predecessor nodes
--   2. Conpute the VarPreds for all predecessors
--   3. Merge the VarPreds from all predecessors by intersection (keep the strongest preds)
--   4. Check whether precondVarables are satisfied
--   5. If satisfied, compute the output VarPreds; otherwise return the failed pred
-- -/
-- def SemanticWorkflowGraph.verifyNode
--   (graph : SemanticWorkflowGraph)
--   (node : SemanticWorkflowNode)
--   (predecessorVarPostcondPreds : List (NodeId × List VariablePredicateRequirement))
--   -- Note the current framework can handle the change in paramVarPreds
--   (paramVarPreds : List VariablePredicateRequirement) : NodeVerifyResult :=
--   let predIds := graph.findPredecessors node.id
--   let predVarPreds := predIds.filterMap fun predId =>
--     predecessorVarPostcondPreds.find? (fun pred => pred.1 == predId) |>.map (·.2)
--   let availablePreds := if predVarPreds.isEmpty then paramVarPreds
--     else combinePredictsIntersection predVarPreds
--   match checkPrecondSatisfied availablePreds node.precondVariables with
--   | some missingPreds => .failure missingPreds availablePreds
--   | none => .success (computeOutputPredicates availablePreds node.postcondVariables)

/-
# Section 3: Registry-aware precondition checking
-/

/-- Check if established preds can satisfy required predicate using registry. -/
def predicatesSatisfiesWithRegistry
  (establishedPreds requiredPreds : VariablePredicateRequirement)
  (registry : PredicateRegistry) : Bool :=
  establishedPreds.varName == requiredPreds.varName &&
  establishedPreds.requiredPredicate.compatibleWithRegistry
    requiredPreds.requiredPredicate registry

/-- Check preconditions with registry support. -/
def verifyPrecondSatisfiedWithRegistry
  (availablePreds : List VariablePredicateRequirement)
  (precondPreds : List VariablePredicateRequirement)
  (registry : PredicateRegistry) : Option VariablePredicateRequirement :=
  precondPreds.find? fun requiredPred =>
    !availablePreds.any (fun established => predicatesSatisfiesWithRegistry established requiredPred registry)

/-
# Section 4: Registry-aware mode verification
-/

/-- Verify a basic node using registry for ext predicates. -/
def verifyBasicNode
  (node : SemanticWorkflowNode)
  (availableVarPreds : List VariablePredicateRequirement)
  (registry : PredicateRegistry) : NodeVerifyResult :=
  match verifyPrecondSatisfiedWithRegistry availableVarPreds node.precondVariables registry with
  | some missingPreds => .failure missingPreds availableVarPreds
  | none => .success (computeOutputPredicates availableVarPreds node.postcondVariables)

-- /-- Verify of a basic node (without loop) -/
-- def verifyBasicNode
--   (node : SemanticWorkflowNode)
--   (availableVarPreds : List VariablePredicateRequirement) : NodeVerifyResult :=
--   match checkPrecondSatisfied availableVarPreds node.precondVariables with
--   | some missingPreds => .failure missingPreds availableVarPreds
--   | none => .success (computeOutputPredicates availableVarPreds node.postcondVariables)

/-
# Section 5: Loop verification helpers
-/

/-- Result of loop termination spec verification -/
inductive LoopTerminationVerifyResult where
  | valid
  | invalid (reason : String)
  deriving Repr, BEq, Inhabited

/-- Verify that the loop has a valid termination specification -/
def verifyLoopTerminationSpec
  (loopNode : _root_.AgenticKernel.SemanticLoopNode) : LoopTerminationVerifyResult :=
  if loopNode.terminationSpec.isValid then
    .valid
  else
    match loopNode.terminationSpec with
    | .finiteCondition vars =>
        if vars.isEmpty then .invalid "finiteCondition requires non-empty termination variables"
        else .valid
    | .llmControlledExit _ pattern =>
        if pattern.isEmpty then .invalid "llmControlledExit requires non-empty sentinel pattern"
        else .valid
    | .externalTermination mechanism =>
        if mechanism.isEmpty then .invalid "externalTermination requires mechanism description"
        else .valid
    | .allowUnbounded justification =>
        if justification.isEmpty then .invalid "allowUnbounded requires justification"
        else .valid

/--
Verify a loop header node by the following steps:
  0. Verify termination specification is valid
  1. Entry node must establish the loop invariant
  2. Loop invariant must satisfy the node's precondition
  3. Output loop invariant for loop body to further use as postcond for this node in the loop body

  Note: The preservation check only verifies loopInvariant (postcondVariables
  are re-established automatically by the loop mechanism each iteration).
-/
def verifyLoopHeaderNode
  (loopHeaderNode : _root_.AgenticKernel.SemanticLoopNode)
  (availableVarPreds : List VariablePredicateRequirement)
  (registry : PredicateRegistry) : NodeVerifyResult :=
  match verifyPrecondSatisfiedWithRegistry availableVarPreds loopHeaderNode.loopInvariant registry with
  | some missingPred => .failure missingPred availableVarPreds
  | none =>
    -- Base output: loopInvariant ++ postcondVariables
    let baseOutput := loopHeaderNode.loopInvariant ++ loopHeaderNode.postcondVariables
    -- If executesAtLeastOnce, also include exitPostconditions (variables written
    -- inside the loop body that are guaranteed to exist after exit)
    let fullOutput := if loopHeaderNode.executesAtLeastOnce
      then baseOutput ++ loopHeaderNode.exitPostconditions
      else baseOutput
    .success (computeOutputPredicates availableVarPreds fullOutput)

/-- Check if the loop body ends with facts preserve the invariant -/
def checkLoopInvariantPreservation
  (loopHeaderNode : _root_.AgenticKernel.SemanticLoopNode)
  (availableWhenBodyEndsPreds : List VariablePredicateRequirement)
  (registry : PredicateRegistry) : Option VariablePredicateRequirement :=
  verifyPrecondSatisfiedWithRegistry availableWhenBodyEndsPreds loopHeaderNode.loopInvariant registry


-- /--
-- Topological siort ignoring the back edges. This ensure we process nodes in dependency order, treating loops as if the back edge does not exists
-- -/
-- def SemanticWorkflowGraph.topologicalSortIgnoringBackEdges
--   (graph : SemanticWorkflowGraph) : Except String (List NodeId) :=
--   -- Since the graph we have is ignoring the loop back deges, we can directly perform a topological sort.
--   let maxSearchDepth := graph.baseGraph.nodes.length + 10086
--   let rec bfs
--     (queue : List NodeId)
--     (visitedNodes : List NodeId)
--     (result : List NodeId)
--     (depth : Nat) : Except String (List NodeId) :=
--     match depth with
--     | 0 => .error s!"Topological sort failed: fuel exhausted (possible ∞ cycle or too many nodes)"   -- hit the max depth, resutn the current result
--     | depth + 1 =>
--       match queue with
--       | [] => .ok result
--       | nodeId :: rest =>
--         if visitedNodes.contains nodeId then
--           bfs rest visitedNodes result depth
--         else
--           let forwardSuccessors := graph.findForwardSuccessors nodeId
--           bfs (rest ++ forwardSuccessors) (nodeId :: visitedNodes) (result ++ [nodeId]) depth
--   bfs [graph.entry] [] [] maxSearchDepth

/-- Check loop preservation for all loops. -/
def verifyAllLoopPreservedInvariants
    (loopsToVerify : List (SemanticLoopNode × NodeId))
    (outputVarPredsMap : List (NodeId × List VariablePredicateRequirement))
    (registry : PredicateRegistry) : Option GraphVerifyResult :=
  match loopsToVerify with
  | [] => none
  | (loopNode, bodyEndNodeId) :: rest =>
    match outputVarPredsMap.find? (fun p => p.1 == bodyEndNodeId) with
    | none => verifyAllLoopPreservedInvariants rest outputVarPredsMap registry
    | some (_, bodyEndVarPreds) =>
      match checkLoopInvariantPreservation loopNode bodyEndVarPreds registry with
      | some missingPred =>
        some (.loopInvariantNotPreserved loopNode.id (loopNode.name.getD "unknown") missingPred bodyEndVarPreds)
      | none =>
        verifyAllLoopPreservedInvariants rest outputVarPredsMap registry

/-
# Section 6: Helper constructors
-/

/-- Build a regustry from DictAllValuesPredicate instances. -/
def makeDictAllValuesRegistry (predicates : List DictAllValuesPredicate) : PredicateRegistry :=
  ⟨predicates.map fun pred => {
    predicateKey := pred.toPredicateKey
    toProp := pred.toPropImplication
    checkProp := fun _ _ => false  -- Default implementation
    impliedKeys := pred.impliedKeysImplication
  }⟩

/-- Empty registry — all ext predicates only match themselves. -/
def emptyRegistry : PredicateRegistry := PredicateRegistry.empty

/-
# Section 7: Registry-aware graph verification
-/
/--
Main verification with loop support. It has two-phase verification:
  1. Process all nodes in topological order ignoring the back edges
  2. Check loop invariant preservation for all loops
  3. Compute exit facts: for loops with sentinel/external exit, use loopInvariant ∧ exitPostconditions
-/
def SemanticWorkflowGraph.verify
    (graph : SemanticWorkflowGraph)
    (registry : PredicateRegistry := emptyRegistry) : GraphVerifyResult :=
  match graph.topologicalSortIgnoringBackEdges with
  | .error msg => .topologicalSortFailed msg
  | .ok sortedNodeIds =>
    let loopHeaders := graph.getLoopHeaders
    let paramVarPreds := graph.paramNode.postcondVariables

    -- Get output predicates from a predecessor, considering branch-specific
    -- postconditions for conditional nodes.
    --
    -- When the predecessor is a conditional node and the current node is
    -- its then/else target, use the branch-specific postconditions to OVERRIDE
    -- specific variables while PRESERVING other accumulated facts.
    -- This enables path-sensitive verification.
    let getOutputPredsFromPredecessor
        (predecessorId : NodeId)
        (currentNodeId : NodeId)
        (outputVarPredsMap : List (NodeId × List VariablePredicateRequirement))
        : Option (List VariablePredicateRequirement) :=
      -- Get base output from the predecessor (accumulated facts up to that point)
      let baseOutput := outputVarPredsMap.find? (fun pred => pred.1 == predecessorId) |>.map (·.2)
      match graph.findConditionalNode predecessorId with
      | some condNode =>
        -- Determine which branch-specific postconds to use
        let branchPreds :=
          if condNode.thenTargetId == currentNodeId then
            some condNode.thenPostcondVariables
          else if condNode.elseTargetId == currentNodeId then
            some condNode.elsePostcondVariables
          else
            none
        match branchPreds, baseOutput with
        | some branchPostconds, some basePreds =>
          -- Merge: start with base, then override with branch-specific preds
          -- For each variable in branchPostconds, replace its predicate in basePreds
          let branchVarNames := branchPostconds.map (·.varName) |>.eraseDups
          let unchangedPreds := basePreds.filter (fun p => !branchVarNames.contains p.varName)
          some (unchangedPreds ++ branchPostconds)
        | some branchPostconds, none =>
          -- No base output (shouldn't happen normally), just use branch preds
          some branchPostconds
        | none, _ =>
          -- Not a direct branch target, use base output
          baseOutput
      | none =>
        -- Not a conditional node, use standard postconds from map
        baseOutput

    let rec processNodes
        (remainingNodes : List NodeId)
        (outputVarPredsMap : List (NodeId × List VariablePredicateRequirement))
        (loopsToVerify : List (SemanticLoopNode × NodeId))
        : GraphVerifyResult :=
      match remainingNodes with
      | [] =>
        match verifyAllLoopPreservedInvariants loopsToVerify outputVarPredsMap registry with
        | some error => error
        | none =>
          -- Compute exit facts based on graph structure
          let exitFacts :=
            if graph.exits.isEmpty then
              -- No explicit exits (e.g., sentinel-based loop)
              -- Exit facts = loopInvariant ∧ exitPostconditions for each loop
              match graph.loopNodes with
              | [] => []
              | loops =>
                -- Combine exit facts from all loops (intersection semantics)
                let loopExitFacts := loops.map (·.computeExitFacts)
                combinePredictsIntersection loopExitFacts
            else
              -- Explicit exit nodes exist - use standard computation
              let exitVarPreds := graph.exits.filterMap fun exitNodeId =>
                outputVarPredsMap.find? (fun pred => pred.1 == exitNodeId) |>.map (·.2)
              combinePredictsIntersection exitVarPreds
          .success exitFacts

      | nodeId :: rest =>
        let predecessorIds := graph.findPredecessorsIgnoringBackEdge nodeId
        -- Use branch-aware predecessor predicate lookup for conditional nodes
        let predecessorVarPreds := predecessorIds.filterMap fun predecessorId =>
          getOutputPredsFromPredecessor predecessorId nodeId outputVarPredsMap
        let availableVarPreds := if predecessorVarPreds.isEmpty then paramVarPreds
          else combinePredictsIntersection predecessorVarPreds

        if loopHeaders.contains nodeId then
          match graph.findLoopNode nodeId with
          | some loopNode =>
            match verifyLoopTerminationSpec loopNode with
            | .invalid reason =>
              .loopTerminationSpecInvalid nodeId (loopNode.name.getD s!"Node {nodeId.val}") reason
            | .valid =>
              match verifyLoopHeaderNode loopNode availableVarPreds registry with
              | .success outputVarPreds =>
                let bodyEndNodeId := graph.findLoopBodyEnd loopNode.id
                let loopsToVerify' := match bodyEndNodeId with
                  | some bodyNodeId => (loopNode, bodyNodeId) :: loopsToVerify
                  | none => loopsToVerify
                processNodes rest ((nodeId, outputVarPreds) :: outputVarPredsMap) loopsToVerify'
              | .failure missingPreds availablePreds =>
                .loopInvariantNotEstablished nodeId (loopNode.name.getD s!"Node {nodeId.val}") missingPreds availablePreds
          | none =>
            .loopInvariantMissing nodeId s!"Unknown Loop Node with ID {nodeId.val}"
        else
          match graph.findSemanticNode nodeId with
          | some semanticNode =>
            match verifyBasicNode semanticNode availableVarPreds registry with
            | .success outputVarPreds =>
              processNodes rest ((nodeId, outputVarPreds) :: outputVarPredsMap) loopsToVerify
            | .failure missingPreds availablePreds =>
              .failure nodeId (semanticNode.name.getD s!"Node {nodeId.val}") missingPreds availablePreds
          | none =>
            processNodes rest ((nodeId, availableVarPreds) :: outputVarPredsMap) loopsToVerify

    processNodes sortedNodeIds [] []

/-- Boolean version for native_decide proofs with registry support. -/
def SemanticWorkflowGraph.isSemanticallySoundBool
    (graph : SemanticWorkflowGraph)
    (registry : PredicateRegistry := emptyRegistry) : Bool :=
  match graph.verify registry with
  | .success _ => true
  | _ => false

/-
# Section 8: Result Formatting
-/

instance : ToString VariablePredicateRequirement where
  toString req := s!"({req.varName}: {repr req.requiredPredicate})"

/-- Format a list of predicates with each on its own line -/
def formatPredicateList (preds : List VariablePredicateRequirement) (indent : String := "    ") : String :=
  preds.map (fun p => s!"{indent}{p.varName}: {repr p.requiredPredicate}") |> String.intercalate "\n"

/-- Format verification result for display -/
def describeGraphVerificationResult (result : GraphVerifyResult) : String :=
  match result with
  | .success finalPreds =>
      let predsStr := formatPredicateList finalPreds
      s!"✓ Graph verification successful!\n  Exit facts ({finalPreds.length} variables):\n{predsStr}"
  | .failure nodeId name missingPred availableVarPreds =>
      let availStr := formatPredicateList availableVarPreds
      s!"✗ Node {name} (ID {nodeId.val}): missing predicate {repr missingPred.requiredPredicate} for variable '{missingPred.varName}'\n  Available predicates ({availableVarPreds.length}):\n{availStr}"
  | .loopInvariantMissing nodeId name =>
      s!"✗ Loop invariant missing for loop header Node {name} (ID {nodeId.val})"
  | .loopInvariantNotEstablished nodeId name missingPred availableVarPreds =>
      let availStr := formatPredicateList availableVarPreds
      s!"✗ Loop {name} (Node ID {nodeId.val}): invariant not established at entry. Missing {repr missingPred.requiredPredicate} for variable '{missingPred.varName}'\n  Available predicates:\n{availStr}"
  | .loopInvariantNotPreserved nodeId name missingPred bodyEndPreds =>
      let bodyStr := formatPredicateList bodyEndPreds
      s!"✗ Loop {name} (Node ID {nodeId.val}): invariant not preserved. Missing {repr missingPred.requiredPredicate} for variable '{missingPred.varName}'\n  Body end predicates:\n{bodyStr}"
  | .loopTerminationSpecInvalid nodeId name reason =>
      s!"✗ Loop {name} (Node ID {nodeId.val}): invalid termination specification. {reason}\n  Every loop must specify how it terminates (finiteCondition, llmControlledExit, externalTermination, or allowUnbounded with justification)"
  | .topologicalSortFailed reason =>
      s!"✗ Topological sort failed: {reason}"


/-
TODO: Things to handle:
  1. The Loop case
  2. The variable that have many predicates
-/
end AgenticKernel
