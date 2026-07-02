import Lean
import Mathlib
import AgentVerifier.StaticLayer

/-!
# Section 0 — ExecutionTrace (Dynamic Verification)

Typed Lean representation of the agent's runtime execution trace (the
`*_agent_events.log` files the agent writes during a run). Every dynamic
verification check — variable (§1), information-flow (§2), graph-level (§3) —
reads from this typed value; there is no free-form string inspection anywhere
in the verification pipeline.

This is the §0 foundation of the dynamic layer. The full section spine
(tracked uniformly across files, mirroring the Layer-2 design) is:

  §0  Basics/ExecutionTrace          — this file: trace model + queries
  §1  Basics/DynamicVariablePredicate — Channel ① variable predicates + bridge
  §2  Basics/DynamicInformationFlow   — Channel ② information flow + bridge
  §3  Basics/DynamicGraphPredicate    — Channel ③ graph-level predicates + bridge
  §4  DynamicVerificationGraph        — dynamic graph carrying the 3 channels + soundness
  §5  DynamicUnifiedReport            — unified 3-channel report + JSON
  §6  DynamicVerificationIO           — IO / external-Python (checker.py) boundary
  §7  PerStepView                     — per-step 3-method view + re-roll
  §8  ElaipBench/PredicateChecks      — ELAIP decidable checks
  §9  ElaipBench/ElaipBench           — ELAIP benchmark glue
  §10 DynamicVerification           — umbrella + JSON face

This file is ported near-verbatim from the original
`AgentVerifier/DynamicVerification/ExecutionTrace.lean` (clean, no legacy deps),
re-homed under `namespace AgenticKernel.Dyn`, with the per-step trace-summary
helpers (§0.4) folded in from `PerStepMoveAnalysis` where they did not belong.

## Event log format (what the agent actually emits)

```
[2026-04-09 18:26:25] Event log started
<<<EVENT>>>{"type":"workflow_start","timestamp":"...","data":{...}}<<</EVENT>>>
<<<EVENT>>>{"type":"step_start",   "data":{"step_id":"1","name":"explore_repository","step_type":"task",...}}<<</EVENT>>>
<<<EVENT>>>{"type":"llm_response", "data":{"step_id":"1","iteration":1,"content":"..."}}<<</EVENT>>>
<<<EVENT>>>{"type":"tool_call_start","data":{"step_id":"1","iteration":1,"call":1,"name":"shell_run","args":"..."}}<<</EVENT>>>
<<<EVENT>>>{"type":"tool_call_end",  "data":{"step_id":"1","iteration":1,"call":1,"name":"shell_run","result":"..."}}<<</EVENT>>>
<<<EVENT>>>{"type":"step_end",     "data":{"step_id":"1","status":"completed","tokens":12345}}<<</EVENT>>>
<<<EVENT>>>{"type":"workflow_end","data":{...}}<<</EVENT>>>
```

`loadEventLog` strips the `<<<EVENT>>>...<<</EVENT>>>` markers, parses
each inner JSON object with `Lean.Json.parse`, and dispatches on `type`
into the typed `TraceEvent` union. Informational events
(`agent_iteration`, `messages_start`, `messages_end`, `workflow_start`,
`workflow_end`) are silently skipped — they carry no verification
evidence. Unknown event types are skipped as well.
-/

namespace AgenticKernel
namespace Dyn

/-! ## §0.1 — Event payloads -/

/-- Data payload for `step_start` events. -/
structure StepStartData where
  stepId    : String
  stepName  : String
  stepType  : String
  deriving Repr, Inhabited, BEq

/-- Data payload for `step_end` events. `status` is the string the agent
    emits — typically `"completed"`, `"failed"`, `"skipped"`. -/
structure StepEndData where
  stepId : String
  status : String
  deriving Repr, Inhabited, BEq

/-- Data payload for `llm_response` events. `content` is opaque free-form
    LLM output; structural checks never parse it. -/
structure LlmResponseData where
  stepId    : String
  iteration : Nat
  content   : String
  deriving Repr, Inhabited, BEq

/-- Data payload for `tool_call_start` events. `argsJson` is the raw JSON
    string of the tool arguments; structural checks never parse it. -/
structure ToolCallStartData where
  stepId    : String
  iteration : Nat
  callIdx   : Nat
  toolName  : String
  argsJson  : String
  deriving Repr, Inhabited, BEq

/-- Data payload for `tool_call_end` events. `resultJson` is the raw JSON
    string of the tool result; structural checks never parse it. -/
structure ToolCallEndData where
  stepId     : String
  iteration  : Nat
  callIdx    : Nat
  toolName   : String
  resultJson : String
  deriving Repr, Inhabited, BEq

/-- Typed sum of the trace events the verifier cares about. Informational
    events like `agent_iteration` are not represented — they are dropped
    during parsing. -/
inductive TraceEvent where
  | stepStart  : StepStartData     → TraceEvent
  | stepEnd    : StepEndData       → TraceEvent
  | llm        : LlmResponseData   → TraceEvent
  | toolStart  : ToolCallStartData → TraceEvent
  | toolEnd    : ToolCallEndData   → TraceEvent
  deriving Repr, Inhabited

/-- A full execution trace is an ordered list of typed events.
    Defined as `abbrev` so `List`'s type classes (e.g. `ForIn`, `Append`,
    `Repr`) lift automatically. -/
abbrev ExecutionTrace : Type := List TraceEvent

/-!
## §0.2 — Queries

All queries are pure structural operations on the typed list — identity
comparisons and index arithmetic only. No substring searches.
-/

namespace TraceEvent

/-- The step id this event belongs to, if any. -/
def stepIdOf : TraceEvent → String
  | .stepStart d => d.stepId
  | .stepEnd   d => d.stepId
  | .llm       d => d.stepId
  | .toolStart d => d.stepId
  | .toolEnd   d => d.stepId

/-- The iteration number this event belongs to, if any.
    Returns 0 for `stepStart` / `stepEnd` (they are not per-iteration). -/
def iterationOf : TraceEvent → Nat
  | .stepStart _ => 0
  | .stepEnd _   => 0
  | .llm       d => d.iteration
  | .toolStart d => d.iteration
  | .toolEnd   d => d.iteration

end TraceEvent

namespace ExecutionTrace

/-- All events belonging to a given step id, preserving order. -/
def eventsForStep (t : ExecutionTrace) (sid : String) : List TraceEvent :=
  t.filter (fun e => TraceEvent.stepIdOf e == sid)

/-- Unique step ids in the order they first appear. -/
def executedStepIds (t : ExecutionTrace) : List String :=
  let folded := t.foldl (init := ([] : List String)) fun acc e =>
    let sid := TraceEvent.stepIdOf e
    if acc.contains sid then acc else acc ++ [sid]
  folded

/-- Max iteration number recorded for a given step id. `0` if the step
    never appeared or only appeared in `stepStart` / `stepEnd`. -/
def maxIteration (t : ExecutionTrace) (sid : String) : Nat :=
  (t.filter (fun e => TraceEvent.stepIdOf e == sid)).foldl
    (fun acc e => Nat.max acc (TraceEvent.iterationOf e)) 0

/-- Index of the first event for this step id, if any. -/
def stepFirstIndex (t : ExecutionTrace) (sid : String) : Option Nat :=
  t.findIdx? (fun e => TraceEvent.stepIdOf e == sid)

/-- Index of the last event for this step id, if any. -/
def stepLastIndex (t : ExecutionTrace) (sid : String) : Option Nat := Id.run do
  let mut idx : Option Nat := none
  let mut i : Nat := 0
  for e in t do
    if TraceEvent.stepIdOf e == sid then
      idx := some i
    i := i + 1
  return idx

/-- All tool-call starts within a step, in order. -/
def toolCallsByStep (t : ExecutionTrace) (sid : String) : List ToolCallStartData :=
  t.filterMap fun
    | .toolStart d => if d.stepId == sid then some d else none
    | _ => none

/-- Derived execution status for a step id, computed structurally from
    the trace: `completed` iff a `stepEnd` with `status == "completed"`
    was recorded; `failed` if a `stepEnd` with any other status was
    recorded; `pending` if a `stepStart` appeared but no `stepEnd`;
    `skipped` if neither appeared.

    These are the four values `ExecutionStatus` from §1 also uses, but
    expressed here as a `String` to keep this file independent of
    `DynamicVariablePredicate`. -/
def statusForStep (t : ExecutionTrace) (sid : String) : String :=
  let hasStart := t.any fun
    | .stepStart d => d.stepId == sid
    | _ => false
  let endStatus := t.findSome? fun
    | .stepEnd d => if d.stepId == sid then some d.status else none
    | _ => none
  match endStatus with
  | some "completed" => "completed"
  | some s           => if s.isEmpty then "failed" else s
  | none             => if hasStart then "pending" else "skipped"

/-- Is this step id `completed` per the trace? -/
def stepCompleted (t : ExecutionTrace) (sid : String) : Bool :=
  t.statusForStep sid == "completed"

end ExecutionTrace

/-!
## §0.3 — JSON round-trip
-/

/-- Look up an optional field, returning `none` on missing or wrong type. -/
private def jsonOptStr (j : Lean.Json) (key : String) : Option String :=
  match j.getObjVal? key with
  | .ok (.str s) => some s
  | _ => none

private def jsonOptNat (j : Lean.Json) (key : String) : Option Nat :=
  match j.getObjVal? key with
  | .ok (.num n) =>
    -- JSON numbers can be negative; clamp at 0 for Nat.
    if n.mantissa < 0 then some 0
    else some n.mantissa.toNat
  | _ => none

/-- Strict parser for a single event JSON object. Returns `none` for
    events whose `type` is not one of the five we represent. -/
def TraceEvent.fromJson? (j : Lean.Json) : Option TraceEvent :=
  let ty := (jsonOptStr j "type").getD ""
  let data := (j.getObjVal? "data").toOption.getD Lean.Json.null
  match ty with
  | "step_start" =>
    let sid   := (jsonOptStr data "step_id").getD ""
    let name  := (jsonOptStr data "name").getD ""
    let stype := (jsonOptStr data "step_type").getD ""
    some (.stepStart ⟨sid, name, stype⟩)
  | "step_end" =>
    let sid := (jsonOptStr data "step_id").getD ""
    let st  := (jsonOptStr data "status").getD ""
    some (.stepEnd ⟨sid, st⟩)
  | "llm_response" =>
    let sid := (jsonOptStr data "step_id").getD ""
    let it  := (jsonOptNat data "iteration").getD 0
    let c   := (jsonOptStr data "content").getD ""
    some (.llm ⟨sid, it, c⟩)
  | "tool_call_start" =>
    let sid := (jsonOptStr data "step_id").getD ""
    let it  := (jsonOptNat data "iteration").getD 0
    let cl  := (jsonOptNat data "call").getD 0
    let tn  := (jsonOptStr data "name").getD ""
    let ar  := (jsonOptStr data "args").getD ""
    some (.toolStart ⟨sid, it, cl, tn, ar⟩)
  | "tool_call_end" =>
    let sid := (jsonOptStr data "step_id").getD ""
    let it  := (jsonOptNat data "iteration").getD 0
    let cl  := (jsonOptNat data "call").getD 0
    let tn  := (jsonOptStr data "name").getD ""
    let rs  := (jsonOptStr data "result").getD ""
    some (.toolEnd ⟨sid, it, cl, tn, rs⟩)
  | _ => none

/-- Parse a full JSON array of events into an `ExecutionTrace`. -/
def ExecutionTrace.fromJson (j : Lean.Json) : Except String ExecutionTrace :=
  match j.getArr? with
  | .error e => .error e
  | .ok arr =>
    .ok (arr.toList.filterMap TraceEvent.fromJson?)

/-! ### `loadEventLog` — parse the `<<<EVENT>>>...<<</EVENT>>>` format -/

private def EVENT_OPEN  : String := "<<<EVENT>>>"
private def EVENT_CLOSE : String := "<<</EVENT>>>"

/-- Extract JSON event bodies from an agent event-log string by
    scanning for `<<<EVENT>>>` / `<<</EVENT>>>` markers. Returns a list of
    JSON fragments (as `String`s) in the order they appear.

    Note: marker strings are fixed literals; this is **not** a
    verification-time substring search — it's a one-shot lexer for the
    file format the agent emits. Verification itself operates on the
    typed `TraceEvent`s produced downstream. -/
private partial def splitEventBodies (input : String) : List String :=
  let rec go (s : String) (acc : List String) : List String :=
    match s.findSubstr? EVENT_OPEN with
    | none => acc.reverse
    | some opened =>
      let afterOpen := s.extract (opened.stopPos) s.endPos
      match afterOpen.findSubstr? EVENT_CLOSE with
      | none => acc.reverse
      | some closed =>
        let body := afterOpen.extract 0 closed.startPos
        let rest := afterOpen.extract (closed.stopPos) afterOpen.endPos
        go rest (body :: acc)
  go input []

/-- Lenient loader: reads a file, splits it into event bodies, parses
    each with `Lean.Json.parse`, and dispatches via
    `TraceEvent.fromJson?`. **Malformed JSON events and unknown event
    types are silently skipped** — real agent logs sometimes contain
    individual events with embedded unescaped quotes / newlines, and
    one bad event should not block the rest of the trace. -/
def ExecutionTrace.loadEventLog (path : System.FilePath) : IO ExecutionTrace := do
  let raw ← IO.FS.readFile path
  let mut out : ExecutionTrace := []
  for body in splitEventBodies raw do
    match Lean.Json.parse body with
    | .error _ => pure ()  -- skip malformed event; cf. Python parser behavior
    | .ok j =>
      match TraceEvent.fromJson? j with
      | some ev => out := out ++ [ev]
      | none    => pure ()
  return out

/-!
## §0.4 — Per-step trace summary

Folded in from the old `PerStepMoveAnalysis` (where `countLlm` /
`countToolStarts` / `uniqueToolNames` / `summarizeStepTrace` were local
helpers duplicating query logic that belongs on the trace itself). A
`StepTraceSummary` is a pure structural fold over the events for one step;
the §7 per-step view renders it.
-/

/-- Compact structural summary of one step's slice of the trace. -/
structure StepTraceSummary where
  stepId         : String
  llmCount       : Nat
  toolStartCount : Nat
  toolNames      : List String
  maxIteration   : Nat
  status         : String
  deriving Repr, Inhabited, BEq

namespace ExecutionTrace

/-- Number of `llm_response` events recorded for a step id. -/
def countLlm (t : ExecutionTrace) (sid : String) : Nat :=
  (t.filter fun | .llm d => d.stepId == sid | _ => false).length

/-- Number of `tool_call_start` events recorded for a step id. -/
def countToolStarts (t : ExecutionTrace) (sid : String) : Nat :=
  (t.toolCallsByStep sid).length

/-- Distinct tool names invoked within a step id, in first-seen order. -/
def uniqueToolNames (t : ExecutionTrace) (sid : String) : List String :=
  (t.toolCallsByStep sid).foldl (init := ([] : List String)) fun acc d =>
    if acc.contains d.toolName then acc else acc ++ [d.toolName]

/-- Build the compact per-step trace summary. -/
def summarizeStep (t : ExecutionTrace) (sid : String) : StepTraceSummary :=
  { stepId         := sid
    llmCount       := t.countLlm sid
    toolStartCount := t.countToolStarts sid
    toolNames      := t.uniqueToolNames sid
    maxIteration   := t.maxIteration sid
    status         := t.statusForStep sid }

end ExecutionTrace

/-!
## §0.5 — StepIdMap

Typed bridge between runtime `stepId : String` and static `NodeId`.
Derived once at verification setup from a `SemanticWorkflowGraph`. Every
check that bridges runtime → static goes through this — never through a
string compare against a synthetic prefix.

This file stays independent of `SemanticGraph`; the canonical `fromGraph`
constructor lives in §3 (`DynamicGraphPredicate`) where the workflow-graph
types are already in scope.
-/

/-- Typed bridge between runtime `stepId : String` and static `NodeId`. -/
structure StepIdMap where
  toNodeId : String → Option NodeId
  toStepId : NodeId → Option String

namespace StepIdMap

def empty : StepIdMap :=
  ⟨fun _ => none, fun _ => none⟩

/-- Build a map from a list of `(stepId, nodeId)` pairs. -/
def ofList (pairs : List (String × NodeId)) : StepIdMap where
  toNodeId s := (pairs.find? (fun p => p.1 == s)).map (·.2)
  toStepId n := (pairs.find? (fun p => p.2 == n)).map (·.1)

end StepIdMap

end Dyn
end AgenticKernel
