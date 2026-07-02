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

namespace AgenticKernel

/-
# Section 2: Extensible predicate using Type Class

This is the extensive part of the predicate. Users implement this type class for their
own predicate type α, providing:
  1. How to convert α to a PredicateKey
  2. How to interpret α as a Prop
  3. How to check α as a Bool
  4. What standard predicates α implies
  5. What standard predicate imply α

The type class is OPEN, anyone can add instances without modifying this file or PredicateType
-/

/-- Type class for user-defined predicate semantics -/
class ExtendedPredicate (α : Type) where
  /-- COnvert to universal key (for DecidableEq). Must be injective, if toKey a = toKey b, then a and b should be semantically equiivalent -/
  toKey : α → PredicateKey
  /-- Prop-level semantic interpretation. Given an env and var name, what does this predicate assert -/
  toProp : α → SemanticEnv → String → Prop
  /-- Bool-level check for runtime verification or #eval. Should be consistent with toProp -/
  checkProp : α → SemanticEnv → String → Bool := fun _ _ _ => false  -- default implementation that always returns true
  /-- Which PredicateKey does this predicate imply? -/
  impliedKeys : α → List PredicateKey := fun _ => []
  /-- Which PredicateKeys imply this predicate? -/
  impliedByKeys : α → List PredicateKey := fun _ => []
  deriving Inhabited

/-
## Section 2.1: Predicate Registry

The registry maps PredicateKey → semantic functions at runtime. This is needed because PredicateType.ext only stores the key (for DecidableEq), but at Layer 3 runtime verification, we need actual Prop/Bool semantics.
-/

/-- A single entry in the predicate registry. It stores the runtime semantics for a PredicateKey. -/
structure PredicateRegistryEntry where
  /-- The key this entry resolves -/
  predicateKey : PredicateKey
  /-- Prop intpretation -/
  toProp : SemanticEnv → String → Prop
  /-- Bool check for runtime  -/
  checkProp : SemanticEnv → String → Bool
  /-- Keys that this predicate implies -/
  impliedKeys : List PredicateKey := []
  /-- Keys that imply this predicate -/
  impliedByKeys : List PredicateKey := []
  /-- Human-readable description -/
  description : String := ""

/-- The predicate registry: a collection of resolved predicate definitions. Used at runtime for enhanced compatibility checking -/
structure PredicateRegistry where
  entries : List PredicateRegistryEntry := []
  deriving Inhabited

namespace PredicateRegistry

def empty : PredicateRegistry := ⟨[]⟩

/-- Register a new predicate entry. -/
def register
  (registry : PredicateRegistry)
  (entry : PredicateRegistryEntry) : PredicateRegistry :=
  ⟨registry.entries ++ [entry]⟩

/-- REgister a predicate from any type with PredicarteSemantics instance. -/
def registerPred
  [ExtendedPredicate α]
  (registry : PredicateRegistry)
  (pred : α) : PredicateRegistry :=
  registry.register {
    predicateKey := ExtendedPredicate.toKey pred,
    toProp := ExtendedPredicate.toProp pred,
    checkProp := ExtendedPredicate.checkProp pred,
    impliedKeys := ExtendedPredicate.impliedKeys pred,
    impliedByKeys := ExtendedPredicate.impliedByKeys pred,
  }

/-- Loop up an entry by key -/
def lookup (registry : PredicateRegistry) (predKey : PredicateKey) : Option PredicateRegistryEntry :=
  registry.entries.find? (·.predicateKey == predKey)

/-- Resolve a key to its prop interpretation. it will falls back to `nameExists` if not found -/
def resolveToProp
  (registry : PredicateRegistry)
  (predicateKey : PredicateKey)
  (semanticEnv : SemanticEnv)
  (varName : String) : Prop :=
  match registry.lookup predicateKey with
  | some entry => entry.toProp semanticEnv varName
  | none => nameExists semanticEnv varName

/-- Resolve a key to its bool check. Falls back to `false` if not found -/
def resolveCheckProp
  (registry : PredicateRegistry)
  (predicateKey : PredicateKey)
  (semanticEnv : SemanticEnv)
  (varName : String) : Bool :=
  match registry.lookup predicateKey with
  | some entry => entry.checkProp semanticEnv varName
  | none => false

/-- Check if key₁ implies key₂ to the registry. -/
def keyImplies (registry : PredicateRegistry) (key₁ key₂ : PredicateKey) : Bool :=
  if key₁ == key₂ then
    true
  else
    match registry.lookup key₁ with
      | some entry => entry.impliedKeys.any (· == key₂)
      | none => false
end PredicateRegistry

/-
## Section 2.2: Standard predicate keys

This section define predicate keys for all existing base predicastes. These are used in the impliedKeys or impliedByKeys fields.

Note: these are NOT needed for the verification algorithm itself
(which uses PredicateType directly). They are needed only for
cross-family implication declarations.
-/

namespace StdPredicateKeys

def nameExists       := PredicateKey.simple "base" "nameExists"
def isNonEmptyString := PredicateKey.simple "base" "isNonEmptyString"
def isNonEmptyList   := PredicateKey.simple "base" "isNonEmptyList"
def isValidURL       := PredicateKey.simple "base" "isValidURL"
def isValidFilePath  := PredicateKey.simple "base" "isValidFilePath"
def isValidPath      := PredicateKey.simple "base" "isValidPath"
def isValidBibtex    := PredicateKey.simple "base" "isValidBibtex"
def isValidLatex     := PredicateKey.simple "base" "isValidLatex"
def isValidJson      := PredicateKey.simple "base" "isValidJson"
def isValidList      := PredicateKey.simple "base" "isValidList"
def toolExists       := PredicateKey.simple "base" "toolExists"
def moduleExists     := PredicateKey.simple "base" "moduleExists"
def isInt            := PredicateKey.simple "base" "isInt"

def matchesJsonSchema (s : JsonSchema) := PredicateKey.withSchema "base" "matchesJsonSchema" s

end StdPredicateKeys

/-
## Section 2.3: Helper functions for register from ExtendedPredicate
-/

/-- Build a registry from a list of preicate values, each with a ExtendedPredicate instance. Uses a heterogeneous approach via entries -/
def makeRegistryFromPredicateRegistryEntries
  (predRegEntries : List PredicateRegistryEntry) : PredicateRegistry :=
  ⟨predRegEntries⟩

/-- Convert a ExtendedPredicate value to a registry entry. -/
def extendedPredicateToRegistryEntry
  [ExtendedPredicate α]
  (pred : α)
  (description : String := "") : PredicateRegistryEntry :=
  {
    predicateKey := ExtendedPredicate.toKey pred,
    toProp := ExtendedPredicate.toProp pred,
    checkProp := ExtendedPredicate.checkProp pred,
    impliedKeys := ExtendedPredicate.impliedKeys pred,
    impliedByKeys := ExtendedPredicate.impliedByKeys pred,
    description := description
  }

/-- Enhanced toProp that resolves `ext` predicates through a registry. -/
def PredicateType.toPropWithRegistry
  (predType : PredicateType)
  (registry : PredicateRegistry)
  (semanticEnv : SemanticEnv)
  (varName : String) : Prop :=
  match predType with
  | .ext key => registry.resolveToProp key semanticEnv varName
  | .predicateAnd p₁ p₂ =>
    p₁.toPropWithRegistry registry semanticEnv varName ∧
    p₂.toPropWithRegistry registry semanticEnv varName
  | .predicateOr p₁ p₂ =>
    p₁.toPropWithRegistry registry semanticEnv varName ∨
    p₂.toPropWithRegistry registry semanticEnv varName
  | other => other.toProp semanticEnv varName

end AgenticKernel
