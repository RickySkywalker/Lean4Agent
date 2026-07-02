import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics


namespace AgenticKernel

/-
========================================================================
PART 3: SEMANTIC PREDICATES
========================================================================

Building blocks for writing Prop-valued preconditions/postconditions.
All are defined in terms of `env.get name` pattern matching.
-/

/-- `name` holds a `String` satisfying `p`. -/
def envString
  (env : SemanticEnv) (name : String) (p : String → Prop) : Prop :=
  ∃ s, env.get name = some (.vString s) ∧ p s

/-- `name` holds an `Int` satisfying `p`. -/
def envInt
  (env : SemanticEnv) (name : String) (p : Int → Prop) : Prop :=
  ∃ n, env.get name = some (.vInt n) ∧ p n

/-- `name` holds a `Bool` satisfying `p`. -/
def envBool
  (env : SemanticEnv) (name : String) (p : Bool → Prop) : Prop :=
  ∃ b, env.get name = some (.vBool b) ∧ p b

/-- `name` holds a `Float` satisfying `p`. -/
def envFloat
  (env : SemanticEnv) (name : String) (p : Float → Prop) : Prop :=
  ∃ f, env.get name = some (.vFloat f) ∧ p f

/-- `name` holds a `List Value` satisfying `p`. -/
def envList (env : SemanticEnv) (name : String) (p : List Value → Prop) : Prop :=
  ∃ l, env.get name = some (.vList l) ∧ p l

/-- `name` holds a `JsonValue` satisfying `p`. -/
def envJson (env : SemanticEnv) (name : String) (p : JsonValue → Prop) : Prop :=
  ∃ j, env.get name = some (.vJson j) ∧ p j

/-- `name` holds a `Record` satisfying `p`. -/
def envRecord (env : SemanticEnv) (name : String) (p : List (String × Value) → Prop) : Prop :=
  ∃ r, env.get name = some (.vRecord r) ∧ p r

/-- `name` exists (holds some value). -/
def nameExistsBool (env : SemanticEnv) (name : String) : Bool :=
  env.get name |>.isSome

def nameExists (env : SemanticEnv) (name : String) : Prop :=
  nameExistsBool env name = true
-- def nameExists (env : SemanticEnv) (name : String) : Prop :=
--   ∃ v, env.get name = some v

/-- `name` holds a non-empty `String`. -/
def isNonEmptyStringBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0)
  | _ => false

def isNonEmptyString (env : SemanticEnv) (name : String) : Prop :=
  isNonEmptyStringBool env name = true
-- def isNonEmptyString (env : SemanticEnv) (name : String) : Prop :=
--   envString env name (fun s => s.length > 0)

/-- `name` holds a non-empty `List`. -/
def isNonEmptyListBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vList l) => decide (l.length > 0)
  | _ => false

def isNonEmptyList (env : SemanticEnv) (name : String) : Prop :=
  isNonEmptyListBool env name = true
-- def isNonEmptyList (env : SemanticEnv) (name : String) : Prop :=
--   envList env name (fun l => l.length > 0)

/-- `name` has the same value in both environments. -/
def isEqualInEnvs (env₁ env₂ : SemanticEnv) (name : String) : Prop :=
  env₁.get name = env₂.get name

/-- `name` holds a `String` containing substring `sub`. -/
def hasSubstringBool (env : SemanticEnv) (name : String) (sub : String) : Bool :=
  match env.get name with
  | some (.vString s) => s.containsSubstr sub
  | _ => false

def hasSubstring (env : SemanticEnv) (name : String) (sub : String) : Prop :=
  hasSubstringBool env name sub = true
-- def hasSubstring
--   (env : SemanticEnv) (name : String) (subString : String) : Prop :=
--   envString env name (fun str => str.containsSubstr subString)

/-- `name` holds a `JsonValue` matching the given `JsonSchema`.
    This is the parameterized version that takes schema as an argument. -/
def matchesJsonSchema (env : SemanticEnv) (name : String) (schema : JsonSchema) : Prop :=
  envJson env name (fun j => jsonValueMatchesWithSchema j schema = true)

def matchesJsonSchemaBool (env : SemanticEnv) (name : String) (schema : JsonSchema) : Bool :=
  match env.get name with
  | some (.vJson j) => jsonValueMatchesWithSchema j schema
  | _ => false

/-- `name` holds a `JsonValue` matching the given `JsonSchema` (Prop version using inductive relation). -/
def matchesJsonSchemaProp (env : SemanticEnv) (name : String) (schema : JsonSchema) : Prop :=
  envJson env name (fun j => JsonMatchesSchema j schema)

/-! ### Predicate transport lemmas

These lemmas let us "move" predicates across `set` operations.
They are the workhorses of chain theorem proofs. -/

/-- A predicate on variable `name` is preserved by writing to a DIFFERENT variable. -/
theorem varPreservedBySettingOthers
  (env : SemanticEnv)
  (name₁ name₂ : String)
  (value : Value)
  (h : name₁ ≠ name₂)
  (prop : String → Prop) :
  envString (env.set name₂ value) name₁ prop ↔ envString env name₁ prop := by
  unfold envString SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

theorem nonEmptyStringPreservedBySettingOthers
  (env : SemanticEnv)
  (name₁ name₂ : String)
  (value : Value)
  (h : name₁ ≠ name₂) :
  isNonEmptyString (env.set name₂ value) name₁ ↔ isNonEmptyString env name₁ := by
  simp [isNonEmptyString, isNonEmptyStringBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem varExistsPreservedBySettingOthers
  (env : SemanticEnv)
  (name₁ name₂ : String)
  (value : Value)
  (h : name₁ ≠ name₂) :
  nameExists (env.set name₂ value) name₁ ↔ nameExists env name₁ := by
  simp [nameExists, nameExistsBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

/-- After `set name v`, `name` is present. -/
theorem varExistAfterSet
  (env : SemanticEnv)
  (name : String)
  (value : Value) :
  nameExists (env.set name value) name := by
  simp [nameExists, nameExistsBool, SemanticEnv.get, SemanticEnv.set]

/-- After `set name (vString s)` where `s.length > 0`, `envNonEmptyString` holds. -/
theorem nonEmptyStringHoldsAfterSetNonEmptyString
  (env : SemanticEnv)
  (name : String)
  (s : String)
  (h : s.length > 0) :
  isNonEmptyString (env.set name (.vString s)) name := by
  simp [isNonEmptyString, isNonEmptyStringBool, SemanticEnv.get, SemanticEnv.set]
  exact h

end AgenticKernel
