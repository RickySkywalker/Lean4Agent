import Lean

/-!
# Section 8 — ELAIP-Bench Predicate Decidable Checks

Pure decidable `Bool` functions over the *raw JSON strings* the ELAIP agent saves
at runtime. They mirror the semantic content of the four ELAIP `.ext` predicates
declared at Layer 2:

  * `verdictEnumValid`     — every option's `verdict` is one of the canonical tags
  * `questionTypeEnum`     — `question_type` is one of the canonical tags
  * `boundedEvidenceList`  — `evidence_snippets` length ≤ 5
  * `verbatimSubstring`    — every `evidence_snippets[i].text` is a substring of
                             the supplied `paper_content`

At Layer 2 these predicates intentionally reduce to `nameExists` (placeholders
that defer to runtime). At Layer 3 we discharge them via these JSON-aware
checks, plumbed through `PerStepAnalysisRules.externalToolVerdict` (§7) — so the
"Tool" verdict slot (the external-Python-verification method) carries the
formal-style JSON check. Ported verbatim from the original under the `Dyn`
namespace; **no new `axiom` declarations.**
-/

namespace AgenticKernel.Dyn.ElaipBench.PredicateChecks

open Lean (Json)

/-- Canonical option-verdict vocabulary used in ELAIP `option_judgment`. -/
def verdictTags : List String := ["supported", "contradicted", "not_established"]

/-- Canonical `question_type` vocabulary used in ELAIP `question_analysis`. -/
def questionTypeTags : List String := ["MA-MCQ", "SA-MCQ", "Single-answer", "Multiple-answer"]

/-- Snippet-list bound enforced by `boundedEvidenceList`. -/
def maxEvidenceSnippets : Nat := 5

/-- Option keys we look for in `option_judgment` JSON. -/
def optionKeys : List String := ["A", "B", "C", "D"]

/-! ## Internal JSON helpers -/

private def jsonAsString (j : Json) : String :=
  match j.getStr? with | .ok s => s | .error _ => ""

private def getKey? (j : Json) (k : String) : Option Json :=
  match j.getObjVal? k with | .ok v => some v | .error _ => none

private def getKeyStr? (j : Json) (k : String) : Option String :=
  (getKey? j k).map jsonAsString

private def getKeyArr? (j : Json) (k : String) : Option (List Json) :=
  match getKey? j k with
  | some v => match v.getArr? with | .ok arr => some arr.toList | .error _ => none
  | none => none

/-! ## Predicate A.1 — `decideVerdictEnum` -/

def decideVerdictEnum (jsonStr : String) : Bool :=
  match Json.parse jsonStr with
  | .error _ => false
  | .ok j =>
    optionKeys.all fun key =>
      match getKey? j key with
      | none => false
      | some sub =>
        match getKeyStr? sub "verdict" with
        | none => false
        | some v => verdictTags.contains v

/-! ## Predicate A.2 — `decideQuestionTypeEnum` -/

def decideQuestionTypeEnum (jsonStr : String) : Bool :=
  match Json.parse jsonStr with
  | .error _ => false
  | .ok j =>
    match getKeyStr? j "question_type" with
    | none => false
    | some s => questionTypeTags.contains s

/-! ## Predicate A.3a — `decideBoundedEvidenceList` -/

def decideBoundedEvidenceList (jsonStr : String) : Bool :=
  match Json.parse jsonStr with
  | .error _ => false
  | .ok j =>
    match getKeyArr? j "evidence_snippets" with
    | none => false
    | some arr => arr.length ≤ maxEvidenceSnippets

/-! ## Predicate A.3b — `decideVerbatimSubstring`

Each `evidence_snippets[i].text` must appear verbatim (character-exact) as a
substring of `paper_content`. Strict by design — that is the formal content of
"verbatim". Empty `evidence_snippets` is `true` (no snippets cannot lie). -/

def decideVerbatimSubstring (evidenceJson paperContent : String) : Bool :=
  match Json.parse evidenceJson with
  | .error _ => false
  | .ok j =>
    match getKeyArr? j "evidence_snippets" with
    | none => false
    | some arr =>
      arr.all fun snippet =>
        match getKeyStr? snippet "text" with
        | none => false
        | some t =>
          let trimmed := t.trim
          if trimmed.isEmpty then false
          else decide ((paperContent.splitOn trimmed).length ≥ 2)

/-! ## Dispatch by variable name -/

def decideElaipPredicateByVar
    (varName : String) (jsonStr : String) (paperContent : String) : Option Bool :=
  if varName == "option_judgment" then some (decideVerdictEnum jsonStr)
  else if varName == "question_analysis" then some (decideQuestionTypeEnum jsonStr)
  else if varName == "evidence" then
    some (decideBoundedEvidenceList jsonStr && decideVerbatimSubstring jsonStr paperContent)
  else none

end AgenticKernel.Dyn.ElaipBench.PredicateChecks
