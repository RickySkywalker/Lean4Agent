import Lean
import Mathlib
import AgentVerifier.BaseTypes


namespace AgenticKernel

/-
========================================================================
2. STEP EXECUTION TYPES
========================================================================

The fundamental classification: does the step involve LLM inference?
If yes, is the output structured or unstructured?

This is NOT just a label — it determines what the structural layer
can and cannot verify about this step.
-/

inductive ExecType where
  -- No LLM involved, behavior is fully determined by YAML semantics.
  | deterministic
  -- LLM involved in the process, but the output is expected to be structured and the format can be determined prior to execution.
  | structured
  -- LLM involved, output is free-form text, the format cannot be determined prior to execution.
  | unstructured
  -- The composition of submodule, makes the execution type of the composition the same as the submodule's execution type, which can be any of the above three.
  | composition
  deriving Repr, BEq, Inhabited


/-
========================================================================
3. STEP TAG — THE 13 YAML STEP TYPES
========================================================================

NOTE (AgentSPEX engine semantics): under the new engine the `step`/`task` roles are SWAPPED relative to the old engine — `step` is now the STATEFUL agent action (persistent conversation history, multi-step tool-call loop) and `task` is the STATELESS, fresh-call action. The new parser also dropped `discover/synthesize/validate/save/evaluate`, so those constructors are removed here.
-/

inductive StepType where
  -- Pure YAML semantics, no LLM involved.
  | forEachLoop         -- (3) Loop over a list
  | whileLoop           -- (4) Loop with a condition
  | conditional         -- (5) Conditional branch
  | setVariable         -- (7) Set a variable
  | incrementVariable   -- (8) Increment a variable
  | switchBranch        -- (13) Switch/case statement
  | returnValue         -- (16) Return a the value from submodule to parent workflow
  | input               -- (9) Collect user input → TString
  -- LLM steps with unstructured output
  | step                -- (1) Stateful agent action WITH persistent conversation history (multi-step tool-call loop) → TString
  | task                -- (2) Stateless agent action, a fresh independent LLM call without conversation history → TString
  | parallel            -- (15) Parallel execution → TList (module return type)
  -- The composition submodule, which is complicated behavior that cannot be determined until runtime, so we treat it as unstructured.
  | call                -- (14) Call sub-module → depends on module's return type
  | gather              -- (15) Parallel heterogeneous → TList TJson
  -- DEPRECATED (the new AgentSPEX parser/codegen reject these, so a NEW-format workflow never produces them — they are functionally absent). They are RETAINED in the inductive only to preserve its original 18-constructor shape: deleting them outright made Lean v4.20 mis-compile some native `#eval` code that reads `node.baseNode.stepType` into a runtime "incomplete case" (a codegen bug exposed by the shrunken inductive). Kept here, unreachable, they sidestep that bug while the engine semantics (step/task swap + dropped types) live in the parser/codegen.
  | save | discover | evaluate | validate | synthesize
  deriving Repr, BEq, Inhabited

/-- Map each StepType to its corresponding ExecType --/
def StepType.execType : StepType -> ExecType
  | .forEachLoop | .whileLoop | .conditional | .setVariable => .deterministic
  | .incrementVariable | .switchBranch | .returnValue | .input => .deterministic
  | .parallel | .gather => .deterministic
  | .step | .task | .call => .unstructured
  | .save => .deterministic | .discover | .evaluate | .validate => .structured | .synthesize => .unstructured  -- deprecated/unused

/-
========================================================================
4. TYPED VARIABLE BINDING
========================================================================
-/

structure TypedVar where
  name : String
  type : BaseType
deriving Repr, BEq, Hashable, Inhabited

abbrev TypedContext := List TypedVar

def TypedContext.lookup (context : TypedContext) (name : String) : Option BaseType :=
  match context.find? (fun v => v.name == name) with
  | some v => some v.type
  | none   => none

def TypedContext.contains (context : TypedContext) (name : String) : Bool :=
  context.any (fun v => v.name == name)

def TypedContext.extend (context : TypedContext) (newVars : List TypedVar) : TypedContext :=
  let filtered := context.filter (fun v => !newVars.any (fun nv => nv.name == v.name))
  filtered ++ newVars

/-
========================================================================
6. STEP-TYPE-SPECIFIC OUTPUT TYPE RULES
========================================================================

For each of the 13 step types, define what output type is expected.
This is where the structural layer uses BaseType to constrain outputs.

Pure steps: output type is fully determined
LLM + unstructured: output type defaults to TString or TUnknown
-/

/-- The default output type for a step tag (when save_as is used).
Returns none if the step doesn't produce a context variable. -/
def StepType.defaultOutputType : StepType -> Option BaseType
  -- Pure steps
  | .forEachLoop | .whileLoop | .conditional | .switchBranch | .setVariable => none
  | .returnValue => none  -- When returning a value, the output type does not affect the current context but return to the main workflow
  | .incrementVariable => some .TInt
  | .input => some .TString
  -- LLM + unstructured output, default is TString or unknown
  | .step | .task => some .TString -- free-form LLM output with or without conversation history.
  | .parallel => some (.TList .TUnknown) -- parallel execution with unknown submodule return type
  -- Composition (outputs depend on submodule)
  | .call => some .TUnknown -- output type depends on the submodule's return type
  | .gather => some (.TList .TUnknown) -- -- list of heterogeneous sub-module results
  -- deprecated/unused (retained-constructor) arms; never produced by the new engine
  | .discover => some (.TList .TJson) | .evaluate => some .TFloat | .validate => some .TBool
  | .synthesize => some .TString | .save => none
