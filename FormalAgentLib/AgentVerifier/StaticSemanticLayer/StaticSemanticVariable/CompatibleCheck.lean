import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType_DecidableEq
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType_utils
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.ExtensiblePredicate

namespace AgenticKernel

/-
# Section 3: Compatible check for PredicateType and ExtendedPredicate
-/

/-- Predicates that directly imply nameExists (almost all non-trivial predicates) -/
def predicateTypeImpliesNameExists : List PredicateType :=
  [
    .isNonEmptyString,
    .isNonEmptyList,
    .isValidURL,
    .isValidFilePath,
    .isValidPath,
    .isValidBibtex,
    .isValidLatex,
    .isValidJson,
    .isValidList,
    .toolExists,
    .moduleExists,
    .isInt
  ]

/-- Full atomic implication table: combines direct rules with universal nameExists rules -/
def predicateTypeDirectImplies : List (PredicateType × PredicateType) :=
  [ -- isValidURL implies isNonEmptyString
    (.isValidURL, .isNonEmptyString),
    -- isValidFilePath implies isNonEmptyString
    (.isValidFilePath, .isNonEmptyString),
    -- isValidPath implies isNonEmptyString (a valid path is non-empty)
    (.isValidPath, .isNonEmptyString),
    -- isValidBibtex implies isNonEmptyString
    (.isValidBibtex, .isNonEmptyString),
    -- isValidLatex implies isNonEmptyString
    (.isValidLatex, .isNonEmptyString),
    -- isValidJson implies isNonEmptyString (since empty string is not valid JSON)
    (.isValidJson, .isNonEmptyString),
    (.isInt, .isNonEmptyString),
    (.isNonEmptyString, .isInt)
  ]

/-- Full implication table: combines direct rules with universal nameExists rules -/
def predicateTypeCompatibleTable : List (PredicateType × PredicateType) :=
  predicateTypeDirectImplies ++
  predicateTypeImpliesNameExists.map (fun p => (p, .nameExists))

/-- Check if an atomic predicate p₁ implies atomic predicate p₂. This handles the base cases: identity, table lookup, and special JSON schema rules. -/
def PredicateType.atomicCompatible (p₁ p₂ : PredicateType) : Bool :=
  (p₁ == p₂) ||
  predicateTypeCompatibleTable.contains (p₁, p₂) ||
  -- Special handling for json schema
  (match p₁, p₂ with
    -- Any json schema compatiable with isValidJson
    | .matchesJsonSchema _, .isValidJson => true
    -- Any json schema with fields specification is compatible with name exists
    | .matchesJsonSchema _, .nameExists => true
    -- Transitive: matchesJsonSchema → isValidJson → isNonEmptyString
    | .matchesJsonSchema _, .isNonEmptyString => true
    -- When s1 is more specific than s2, then s1 is compatible with s2
    | .matchesJsonSchema s₁, .matchesJsonSchema s₂ => s₁.implies s₂
    -- Similar for JsonWithFields
    | .isJsonWithFields _, .nameExists => true
    | .isJsonWithFields _, .isValidJson => true
    -- Transitive: isJsonWithFields → isValidJson → isNonEmptyString
    | .isJsonWithFields _, .isNonEmptyString => true
    -- containsSubstring(s) implies isNonEmptyString and nameExists
    -- (if a string contains any substring, it must be non-empty)
    | .containsSubstring _, .isNonEmptyString => true
    | .containsSubstring _, .nameExists => true
    -- ★ NEW: ext predicates — equality is already handled by (p₁ == p₂) above.
    -- For cross-type implication (ext → base or base → ext), we need the registry.
    -- At the static level (no registry), ext predicates only match themselves
    -- and nameExists (conservative but sound).
    | .ext _, .nameExists => true
    -- All other cases is no compatibility
    | _, _ => false
  )

/--
Recursive entailment checker: does p₁ imply p₂ hold? This implements propositional logic rules and atomic implication table.
The `max_depth` parameter ensures terminaltion. It decreases on every recrisive call. In practice, predicate nesting depth is typically small, so the defaule 20020516 is more than sufficient.

Propositional logic rules:
  - (p₁ ∧ p₂) → q  if  p₁ → q  OR  p₂ → q  (either conjunct suffices)
  - (p₁ ∨ p₂) → q  if  p₁ → q  AND  p₂ → q  (both disjuncts must imply)
  - p → (q₁ ∧ q₂)  if  p → q₁  AND  p → q₂  (must imply both)
  - p → (q₁ ∨ q₂)  if  p → q₁  OR  p → q₂   (suffices to imply one)

NOTE: For .ext predicates, uses semanticBEq for order-independent comparison.
-/
def PredicateType.compatible
  (p₁ p₂ : PredicateType) (max_depth := 20020516) : Bool :=
  match max_depth with
  | 0 => false  -- Out of fuel, assume not compatible to prevent infinite recursion
  | Nat.succ depth' =>
    -- Direct match: structural equality OR semantic equality for .ext
    let directMatch := match p₁, p₂ with
      | .ext k₁, .ext k₂ => k₁.semanticBEq k₂  -- Use semantic comparison!
      | _, _ => p₁ == p₂
    if directMatch then true
    else
      -- First handle source (p₁) being compound
      match p₁ with
      -- Source is conjunction: (p₁ ∧ p₂) → q if either p₁ → q OR p₂ → q
      -- This is because (A ∧ B) → A and (A ∧ B) → B are both valid
      | .predicateAnd q₁ q₂ =>
          q₁.compatible p₂ depth' || q₂.compatible p₂ depth'
      -- Source is disjunction: (p₁ ∨ p₂) → q if BOTH p₁ → q AND p₂ → q
      -- We need both branches to imply the target
      | .predicateOr q₁ q₂ =>
          q₁.compatible p₂ depth' && q₂.compatible p₂ depth'
      -- Source is atomic, check target structure
      | _ =>
        match p₂ with
        -- Target is conjunction: p implies (q₁ ∧ q₂) if p implies both q₁ and q₂
        | .predicateAnd q₁ q₂ =>
            p₁.compatible q₁ depth' && p₁.compatible q₂ depth'
        -- Target is disjunction: p implies (q₁ ∨ q₂) if p implies at least one of q₁ or q₂
        | .predicateOr q₁ q₂ =>
            p₁.compatible q₁ depth' || p₁.compatible q₂ depth'
        -- Both are atomic: check using the atomic implication rules
        | _ => p₁.atomicCompatible p₂


/-- Enhanced compatible with registry support. It extends the atomic compatible to consule the registry for ext →
base implication. Use this version when you have a registry and need cross-type compatability. -/
def PredicateType.compatibleWithRegistry
  (pred₁ pred₂ : PredicateType)
  (registry : PredicateRegistry)
  (max_depth := 20020516) : Bool :=
  match max_depth with
  | 0 => false  -- Out of fuel, assume not compatible to prevent infinite recursion
  | Nat.succ depth' =>
    -- Firsrt check: structural equality or semantic equality for .ext
    let directMatch :=
      match pred₁, pred₂ with
      | .ext k₁, .ext k₂ => k₁.semanticBEq k₂  -- Use semantic comparison for ext!
      | _, _ => pred₁ == pred₂
    if directMatch then true
    else
      match pred₁ with
      | .predicateAnd q₁ q₂ =>
          q₁.compatibleWithRegistry pred₂ registry depth' ||
          q₂.compatibleWithRegistry pred₂ registry depth'
      | .predicateOr q₁ q₂ =>
          q₁.compatibleWithRegistry pred₂ registry depth' &&
          q₂.compatibleWithRegistry pred₂ registry depth'
      | _ =>
        match pred₂ with
        | .predicateAnd q₁ q₂ =>
            pred₁.compatibleWithRegistry q₁ registry depth' &&
            pred₁.compatibleWithRegistry q₂ registry depth'
        | .predicateOr q₁ q₂ =>
            pred₁.compatibleWithRegistry q₁ registry depth' ||
            pred₁.compatibleWithRegistry q₂ registry depth'
        | _ =>
          -- First try standard atomic compatibility
          if pred₁.atomicCompatible pred₂ then true
          else
            -- Then try registry for ext predicates
            match pred₁, pred₂ with
            | .ext k₁, .ext k₂ =>
              -- Already checked semantic equality above, try registry implications
              registry.keyImplies k₁ k₂ || registry.keyImplies k₁.normalize k₂.normalize
            | .ext k₁, _ =>
              -- Check if k₁ implies any standard key that matches p₂
              match registry.lookup k₁ with
              | some entry => entry.impliedKeys.any fun impliedKey =>
                  -- Map the implied key back to see if it matches p₂
                  -- This is a heuristic; exact mapping depends on key naming
                  impliedKey == (StdPredicateKeys.nameExists) && pred₂ == .nameExists ||
                  impliedKey == (StdPredicateKeys.isValidJson) && pred₂ == .isValidJson
              | none => false
            | _, _ => false

/-
# Section 4: Mapping the variable predicates with PredicateType and compatibility checking
Add a convinent shorthand function for creating variable requirements, previous, we only checks the properity of a variable, now, we can directly specify the PredicateType we want, and the system will check whether the provided predicate is compatible with the required predicate.
-/

/-- Base variable requirement structure -/
structure VariablePredicateRequirement where
  varName : String
  requiredPredicate : PredicateType
  deriving Repr, Inhabited, BEq, DecidableEq

instance : Inhabited VariablePredicateRequirement where
  default := ⟨"", .nameExists⟩

-- Basic predicates
def varNameExists (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .nameExists⟩

def varIsNonEmptyString (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isNonEmptyString⟩

def varIsNonEmptyList (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isNonEmptyList⟩

def varIsInt (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isInt⟩

-- File/URL predicates
def varIsValidURL (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidURL⟩

def varIsValidFilePath (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidFilePath⟩

def varIsValidPath (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidPath⟩

-- Format predicates
def varIsValidBibtex (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidBibtex⟩

def varIsValidLatex (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidLatex⟩

def varIsValidJson (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidJson⟩

def varIsValidList (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .isValidList⟩

-- Resource predicates
def varIsValidTool (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .toolExists⟩

def varIsValidModule (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .moduleExists⟩

-- Exit condition predicates (for loop termination)
def varContainsSentinel (varName : String) (sentinel : String) : VariablePredicateRequirement :=
  ⟨varName, .containsSubstring sentinel⟩

def varFileExistsAtPath (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .fileExistsAtPath⟩

def varTaskCompleted (varName : String) : VariablePredicateRequirement :=
  ⟨varName, .taskCompleted⟩

-- Schema predicates
def varIsValidJsonSchema
  (varName : String) (schema : JsonSchema) : VariablePredicateRequirement :=
  ⟨varName, .matchesJsonSchema schema⟩

def varIsValidJsonFields
  (varName : String) (fields : List JsonFieldSpec) : VariablePredicateRequirement :=
  ⟨varName, .isJsonWithFields fields⟩

-- Custom predicate (backward compatibility)
def varIsValidCustomPredicate (varName : String) (predicateName : String) : VariablePredicateRequirement :=
  ⟨varName, .custom predicateName⟩

-- ★ NEW: Extensible predicate via PredicateKey
def varExt (varName : String) (key : PredicateKey) : VariablePredicateRequirement :=
  ⟨varName, .ext key⟩

-- Propositional connecrtive constructors
def varPredicateAnd
  (varName : String) (pred₁ pred₂ : PredicateType) : VariablePredicateRequirement :=
  ⟨varName, .predicateAnd pred₁ pred₂⟩

def varPredicateOr
  (varName : String) (pred₁ pred₂ : PredicateType) : VariablePredicateRequirement :=
  ⟨varName, .predicateOr pred₁ pred₂⟩


/-
# Section 5: Higher-level Semantic Operations
This section aims to transform the basic semantic definition into more convinent high-level operations.
-/

/-- Convert a VariablePredicateRequirement to prop (automatically derivied from toEnvProp) -/
def VariablePredicateRequirement.toProp
  (req : VariablePredicateRequirement) : SemanticEnv → Prop :=
  fun env => req.requiredPredicate.toProp env req.varName

/-- Convert a list of VariablePredicateRequirements to a single semantic property -/
def listVariablePredicatesToProp
  (reqs : List VariablePredicateRequirement) : SemanticEnv → Prop :=
  fun env => ∀ req ∈ reqs, req.toProp env

/-- Build a precondition Prop from requirements -/
def makePreconditionFromVarPredicates
  (reqs : List VariablePredicateRequirement) : SemanticEnv → Prop :=
  listVariablePredicatesToProp reqs

/-- Check if established fact can safely required fact -/
def VariablePredicateRequirement.satisfies
  (establishedFact requiredPredicate : VariablePredicateRequirement) : Bool :=
  establishedFact.varName == requiredPredicate.varName &&
  establishedFact.requiredPredicate.compatible requiredPredicate.requiredPredicate

end AgenticKernel
