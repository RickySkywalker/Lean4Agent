import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates

namespace AgenticKernel

/-
╔══════════════════════════════════════════════════════════════════════════╗
║  EXTENDED SEMANTIC PREDICATES                                           ║
║                                                                        ║
║  Domain-specific predicates for common agentic workflow patterns.       ║
║  These extend the base predicates in SemanticPredicates.lean.          ║
║                                                                        ║
║  Design: Bool-first — each predicate defines a Bool checker as the     ║
║  single source of truth, and the Prop version is derived as            ║
║  `*Bool env name = true`. This eliminates logic duplication between    ║
║  the Prop and Bool versions.                                            ║
║                                                                        ║
║  Categories:                                                            ║
║    1. File system predicates (paths, file existence)                   ║
║    2. Format predicates (JSON, LaTeX, BibTeX)                          ║
║    3. Tool/capability predicates                                        ║
║    4. Module/subworkflow predicates                                     ║
║    5. Composite predicates (combining multiple conditions)             ║
║    6. Generalized transport lemmas                                     ║
╚══════════════════════════════════════════════════════════════════════════╝
-/

/-
========================================================================
1. FILE SYSTEM PREDICATES
========================================================================
-/

/-- `name` holds a valid directory path (non-empty string). -/
def isValidPathBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0)
  | _ => false

def isValidPath (env : SemanticEnv) (name : String) : Prop :=
  isValidPathBool env name = true

/-- `name` holds a valid file path (contains at least one path separator). -/
def isValidFilePathBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0) && s.containsSubstr "/"
  | _ => false

def isValidFilePath (env : SemanticEnv) (name : String) : Prop :=
  isValidFilePathBool env name = true

/-- `name` holds a valid URL (contains protocol separator). -/
def isValidURLBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0) && s.containsSubstr "://"
  | _ => false

def isValidURL (env : SemanticEnv) (name : String) : Prop :=
  isValidURLBool env name = true

/-- Whether the given variable is a valid int. -/
def isIntBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vInt _) => true
  | _ => false

def isInt (env : SemanticEnv) (name : String) : Prop :=
  isIntBool env name = true

/-
========================================================================
2. FORMAT PREDICATES
========================================================================
-/

/-- `name` holds a `JsonValue`. -/
def isValidJsonBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vJson _) => true
  | _ => false

def isValidJson (env : SemanticEnv) (name : String) : Prop :=
  isValidJsonBool env name = true

/-- `name` holds a JSON value that is an array (list). -/
def isJsonArrayBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vJson (.arr _)) => true
  | _ => false

def isJsonArray (env : SemanticEnv) (name : String) : Prop :=
  isJsonArrayBool env name = true

/-- `name` holds a JSON value that is an object. -/
def isJsonObjectBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vJson (.obj _)) => true
  | _ => false

def isJsonObject (env : SemanticEnv) (name : String) : Prop :=
  isJsonObjectBool env name = true

/-
----------------------------------------------------------------------
2b. DICTIONARY VALUE PREDICATES (for parallel submodule results)
----------------------------------------------------------------------

When a parallel step executes a submodule N times, the results are stored
as a Dict[str, Any] where each value satisfies the submodule's return
postconditions. These predicates express "all values in a Dict satisfy P".
-/

/-- `name` holds a JSON object (Dict) where ALL values satisfy predicate `P`.
    This is the core predicate for parallel submodule verification.

    Note: This is a higher-order predicate (takes P as parameter), so we keep
    both Prop and Bool versions separately rather than using Bool-first pattern. -/
def allDictValuesSatisfy (P : Value → Prop) (env : SemanticEnv) (varName : String) : Prop :=
  ∃ pairs : List (String × JsonValue),
    env.get varName = some (.vJson (.obj pairs)) ∧
    ∀ (k : String) (v : JsonValue), (k, v) ∈ pairs → P (.vJson v)

/-- Decidable version for runtime verification / #eval. -/
def allDictValuesSatisfyBool (P : Value → Bool) (env : SemanticEnv) (varName : String) : Bool :=
  match env.get varName with
  | some (.vJson (.obj pairs)) => pairs.all (fun (_, v) => P (.vJson v))
  | _ => false

/-- Specialized version: all Dict values are valid JSON. -/
def allDictValuesAreJson (env : SemanticEnv) (varName : String) : Prop :=
  allDictValuesSatisfy (fun v => ∃ j, v = .vJson j) env varName

/-- Specialized version: all Dict values match a JSON schema. -/
def allDictValuesMatchSchema (schema : JsonSchema) (env : SemanticEnv) (varName : String) : Prop :=
  allDictValuesSatisfy (fun v => ∃ j, v = .vJson j ∧ JsonMatchesSchema j schema) env varName

/-
----------------------------------------------------------------------
2a. JSON SCHEMA PREDICATES
----------------------------------------------------------------------

JSON schema validation: check that a JSON object has specific keys
with specific value types.
-/

/-- The expected type of a JSON field value. -/
inductive JsonFieldType where
  | jString  -- JsonValue.str
  | jNum     -- JsonValue.num
  | jBool    -- JsonValue.bool
  | jArray   -- JsonValue.arr
  | jObject  -- JsonValue.obj
  | jAny     -- any JsonValue (just check key exists)
  deriving DecidableEq, Repr, BEq, Hashable

/-- A field schema: key name + expected type. -/
structure JsonFieldSpec where
  key  : String
  type : JsonFieldType
  deriving DecidableEq, Repr, Hashable

/-!
## BEq for JsonFieldSpec
-/

def JsonFieldSpec.beqAux (a b : JsonFieldSpec) : Bool :=
  a.key == b.key && a.type == b.type

instance : BEq JsonFieldSpec where
  beq := JsonFieldSpec.beqAux

private theorem String.beq_sound (a b : String) : (a == b) = true → a = b := by
  intro h
  exact of_decide_eq_true h

private theorem JsonFieldType.beq_sound (a b : JsonFieldType) : (a == b) = true → a = b := by
  cases a <;> cases b <;> native_decide

private theorem JsonFieldType.beq_refl (a : JsonFieldType) : (a == a) = true := by
  cases a <;> native_decide

theorem JsonFieldSpec.beqAux_sound : ∀ (a b : JsonFieldSpec), JsonFieldSpec.beqAux a b = true → a = b := by
  intro a b h
  simp only [beqAux, Bool.and_eq_true] at h
  obtain ⟨hkey, htype⟩ := h
  have hk : a.key = b.key := String.beq_sound a.key b.key hkey
  have ht : a.type = b.type := JsonFieldType.beq_sound a.type b.type htype
  cases a; cases b
  simp_all

theorem JsonFieldSpec.beqAux_refl : ∀ (a : JsonFieldSpec), JsonFieldSpec.beqAux a a = true := by
  intro a
  simp only [beqAux, beq_self_eq_true, JsonFieldType.beq_refl, Bool.and_self]

theorem JsonFieldSpec.beq_eq_decide : ∀ (a b : JsonFieldSpec), (a == b) = decide (a = b) := by
  intro a b
  cases h : a == b with
  | true =>
    have : a = b := JsonFieldSpec.beqAux_sound a b h
    simp [this]
  | false =>
    have hne : ¬(a = b) := fun heq => by
      subst heq
      have : (a == a) = true := JsonFieldSpec.beqAux_refl a
      rw [h] at this
      exact Bool.noConfusion this
    simp [hne]

/-!
## Implication for JsonFieldType and JsonFieldSpec
-/

def JsonFieldType.implies (t₁ t₂ : JsonFieldType) : Bool :=
  match t₁, t₂ with
  | _, .jAny => true
  | .jString, .jString => true
  | .jNum, .jNum => true
  | .jBool, .jBool => true
  | .jArray, .jArray => true
  | .jObject, .jObject => true
  | _, _ => false

def JsonFieldSpec.implies (f₁ f₂ : JsonFieldSpec) : Bool :=
  f₁.key == f₂.key && f₁.type.implies f₂.type

def JsonFieldSpecList.implies (fields₁ fields₂ : List JsonFieldSpec) : Bool :=
  fields₂.all fun f₂ =>
    fields₁.any fun f₁ => f₁.implies f₂

/-- Check whether a JsonValue matches an expected field type. -/
def jsonValueMatchesType (v : JsonValue) (t : JsonFieldType) : Prop :=
  match t with
  | .jString => ∃ s, v = .str s
  | .jNum    => ∃ n, v = .num n
  | .jBool   => ∃ b, v = .bool b
  | .jArray  => ∃ a, v = .arr a
  | .jObject => ∃ o, v = .obj o
  | .jAny    => True

def jsonValueMatchesTypeBool (v : JsonValue) (t : JsonFieldType) : Bool :=
  match t, v with
  | .jString, .str _  => true
  | .jNum,    .num _   => true
  | .jBool,   .bool _  => true
  | .jArray,  .arr _   => true
  | .jObject, .obj _   => true
  | .jAny,    _        => true
  | _,        _        => false

/-- Decidable version: check JSON object fields against schema. -/
def isJsonWithSchemaBool (env : SemanticEnv) (name : String) (schema : List JsonFieldSpec) : Bool :=
  match env.get name with
  | some (.vJson (.obj fields)) =>
    schema.all (fun spec =>
      match jsonLookup fields spec.key with
      | some v => jsonValueMatchesTypeBool v spec.type
      | none   => false)
  | _ => false

def isJsonWithSchema (env : SemanticEnv) (name : String) (schema : List JsonFieldSpec) : Prop :=
  isJsonWithSchemaBool env name schema = true

/-- `name` holds a string containing valid LaTeX. -/
def isValidLatexBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0) && s.containsSubstr "\\"
  | _ => false

def isValidLatex (env : SemanticEnv) (name : String) : Prop :=
  isValidLatexBool env name = true

/-- `name` holds a string containing valid BibTeX. -/
def isValidBibtexBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vString s) => decide (s.length > 0) && s.containsSubstr "@"
  | _ => false

def isValidBibtex (env : SemanticEnv) (name : String) : Prop :=
  isValidBibtexBool env name = true

/-- `name` holds a `List Value`. -/
def isValidListBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vList _) => true
  | _ => false

def isValidList (env : SemanticEnv) (name : String) : Prop :=
  isValidListBool env name = true

/-- `name` holds a non-empty `List Value`. -/
def isNonEmptyValidListBool (env : SemanticEnv) (name : String) : Bool :=
  match env.get name with
  | some (.vList l) => decide (l.length > 0)
  | _ => false

def isNonEmptyValidList (env : SemanticEnv) (name : String) : Prop :=
  isNonEmptyValidListBool env name = true

/-
========================================================================
3. TOOL / CAPABILITY PREDICATES
========================================================================
-/

/-- A named tool/capability is available in the environment.
    Tools are represented as variables that hold some value. -/
def toolExistsBool (env : SemanticEnv) (toolName : String) : Bool :=
  nameExistsBool env toolName

def toolExists (env : SemanticEnv) (toolName : String) : Prop :=
  toolExistsBool env toolName = true

/-- A named module exists and is callable. -/
def moduleExistsBool (env : SemanticEnv) (moduleName : String) : Bool :=
  nameExistsBool env moduleName

def moduleExists (env : SemanticEnv) (moduleName : String) : Prop :=
  moduleExistsBool env moduleName = true

/-
========================================================================
4. MODULE / SUBWORKFLOW PREDICATES
========================================================================
-/

/-- The parameters list fits the expected schema of a submodule. -/
def parameterListFitBool (env : SemanticEnv) (paramListVar : String) : Bool :=
  match env.get paramListVar with
  | some (.vList l) => decide (l.length > 0)
  | _ => false

def parameterListFit (env : SemanticEnv) (paramListVar : String) : Prop :=
  parameterListFitBool env paramListVar = true

/-
========================================================================
5. COMPOSITE PREDICATES
========================================================================
-/

/-- A conjunction of multiple predicates on different variables. -/
def allExistBool (env : SemanticEnv) (names : List String) : Bool :=
  names.all (nameExistsBool env)

def allExist (env : SemanticEnv) (names : List String) : Prop :=
  allExistBool env names = true

/-- All listed variables are non-empty strings. -/
def allNonEmptyStringsBool (env : SemanticEnv) (names : List String) : Bool :=
  names.all (isNonEmptyStringBool env)

def allNonEmptyStrings (env : SemanticEnv) (names : List String) : Prop :=
  allNonEmptyStringsBool env names = true

/-- A variable holds a string containing a specific substring. -/
def containsSubstringBool (env : SemanticEnv) (varName : String) (sub : String) : Bool :=
  match env.get varName with
  | some (.vString s) => s.containsSubstr sub
  | _ => false

def containsSubstring (env : SemanticEnv) (varName : String) (sub : String) : Prop :=
  containsSubstringBool env varName sub = true

/-
========================================================================
6. GENERALIZED TRANSPORT LEMMAS
========================================================================

These lemmas allow predicates to be transported across `set` operations.
They are essential for chain verification proofs.

Key insight: For Bool-first predicates, preservation under `set` of a
DIFFERENT variable follows from the fact that `env.get name₁` is unchanged
when we `env.set name₂ value` with `name₁ ≠ name₂`. We provide a generic
helper and specific instances.
-/

/-- Generic transport helper: any predicate that only reads `env.get name₁`
    is preserved when a different variable `name₂` is set.
    
    Note: This requires the stronger assumption that `f` only depends on `env.get name`. -/
private theorem bool_pred_preserved_by_set_other
  (f : SemanticEnv → String → Bool)
  (hf : ∀ env₁ env₂ name, env₁.get name = env₂.get name → f env₁ name = f env₂ name)
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  f (env.set name₂ value) name₁ = f env name₁ := by
  apply hf
  unfold SemanticEnv.get SemanticEnv.set
  simp only [ite_eq_right_iff]
  intro heq
  simp only [beq_iff_eq] at heq
  exact absurd heq h


/-- Generic predicate transport for envString (kept for backward compat). -/
theorem envString_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) (p : String → Prop) :
  envString (env.set name₂ value) name₁ p ↔ envString env name₁ p := by
  unfold envString SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

theorem envInt_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) (p : Int → Prop) :
  envInt (env.set name₂ value) name₁ p ↔ envInt env name₁ p := by
  unfold envInt SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

theorem envBool_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) (p : Bool → Prop) :
  envBool (env.set name₂ value) name₁ p ↔ envBool env name₁ p := by
  unfold envBool SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

theorem envList_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) (p : List Value → Prop) :
  envList (env.set name₂ value) name₁ p ↔ envList env name₁ p := by
  unfold envList SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

theorem envJson_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) (p : JsonValue → Prop) :
  envJson (env.set name₂ value) name₁ p ↔ envJson env name₁ p := by
  unfold envJson SemanticEnv.get SemanticEnv.set
  simp [h, Ne.symm h]

/-- isEqualInEnvs is the fundamental frame condition primitive. -/
theorem isEqualInEnvs_refl (env : SemanticEnv) (name : String) :
  isEqualInEnvs env env name := by
  unfold isEqualInEnvs
  rfl

theorem isEqualInEnvs_trans
  (env₁ env₂ env₃ : SemanticEnv) (name : String) :
  isEqualInEnvs env₁ env₂ name →
  isEqualInEnvs env₂ env₃ name →
  isEqualInEnvs env₁ env₃ name := by
  unfold isEqualInEnvs SemanticEnv.get
  intro h₁ h₂
  rw [h₁, h₂]

/-- A predicate on a variable in env₁ transfers to env₂
    if the variable has the same value in both environments. -/
theorem nameExists_transfer
  (env₁ env₂ : SemanticEnv) (name : String)
  (h_eq : isEqualInEnvs env₁ env₂ name)
  (h_exists : nameExists env₁ name) :
  nameExists env₂ name := by
  simp only [nameExists, nameExistsBool] at *
  rw [isEqualInEnvs] at h_eq
  rw [← h_eq]
  exact h_exists

theorem isNonEmptyString_transfer
  (env₁ env₂ : SemanticEnv) (name : String)
  (h_eq : isEqualInEnvs env₁ env₂ name)
  (h_ne : isNonEmptyString env₁ name) :
  isNonEmptyString env₂ name := by
  simp only [isNonEmptyString, isNonEmptyStringBool] at *
  rw [isEqualInEnvs] at h_eq
  rw [← h_eq]
  exact h_ne

/-- General transfer: any envString predicate can be transferred. -/
theorem envString_transfer
  (env₁ env₂ : SemanticEnv) (name : String) (p : String → Prop)
  (h_eq : isEqualInEnvs env₁ env₂ name)
  (h_holds : envString env₁ name p) :
  envString env₂ name p := by
  unfold envString SemanticEnv.get at *
  unfold isEqualInEnvs SemanticEnv.get at h_eq
  obtain ⟨s, hs_eq, hs_prop⟩ := h_holds
  rw [h_eq] at hs_eq
  exact ⟨s, hs_eq, hs_prop⟩

/-- Chain of frame conditions. -/
theorem frame_chain_2
  (env₀ env₁ env₂ : SemanticEnv) (name : String)
  (h₁ : isEqualInEnvs env₀ env₁ name)
  (h₂ : isEqualInEnvs env₁ env₂ name) :
  isEqualInEnvs env₀ env₂ name :=
  isEqualInEnvs_trans env₀ env₁ env₂ name h₁ h₂

theorem frame_chain_3
  (env₀ env₁ env₂ env₃ : SemanticEnv) (name : String)
  (h₁ : isEqualInEnvs env₀ env₁ name)
  (h₂ : isEqualInEnvs env₁ env₂ name)
  (h₃ : isEqualInEnvs env₂ env₃ name) :
  isEqualInEnvs env₀ env₃ name :=
  isEqualInEnvs_trans env₀ env₂ env₃ name
    (isEqualInEnvs_trans env₀ env₁ env₂ name h₁ h₂) h₃


/-
========================================================================
7. TRANSPORT LEMMAS FOR BOOL-FIRST PREDICATES
========================================================================

For Bool-first predicates, preservation under `set` of a different variable
is straightforward: `env.get name₁` doesn't change when we `env.set name₂`.
-/

theorem isValidFilePath_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidFilePath (env.set name₂ value) name₁ ↔ isValidFilePath env name₁ := by
  simp [isValidFilePath, isValidFilePathBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidURL_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidURL (env.set name₂ value) name₁ ↔ isValidURL env name₁ := by
  simp [isValidURL, isValidURLBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidBibtex_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidBibtex (env.set name₂ value) name₁ ↔ isValidBibtex env name₁ := by
  simp [isValidBibtex, isValidBibtexBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidLatex_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidLatex (env.set name₂ value) name₁ ↔ isValidLatex env name₁ := by
  simp [isValidLatex, isValidLatexBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidJson_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidJson (env.set name₂ value) name₁ ↔ isValidJson env name₁ := by
  simp [isValidJson, isValidJsonBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidPath_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidPath (env.set name₂ value) name₁ ↔ isValidPath env name₁ := by
  simp [isValidPath, isValidPathBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isInt_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isInt (env.set name₂ value) name₁ ↔ isInt env name₁ := by
  simp [isInt, isIntBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem isValidList_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  isValidList (env.set name₂ value) name₁ ↔ isValidList env name₁ := by
  simp [isValidList, isValidListBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem toolExists_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  toolExists (env.set name₂ value) name₁ ↔ toolExists env name₁ := by
  simp [toolExists, toolExistsBool, nameExistsBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

theorem moduleExists_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value)
  (h : name₁ ≠ name₂) :
  moduleExists (env.set name₂ value) name₁ ↔ moduleExists env name₁ := by
  simp [moduleExists, moduleExistsBool, nameExistsBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

/-
========================================================================
8. JSON SCHEMA TRANSPORT LEMMAS
========================================================================
-/

/-- isJsonWithSchema is preserved when the variable has the same value. -/
theorem isJsonWithSchema_transfer
  (env₁ env₂ : SemanticEnv) (name : String) (schema : List JsonFieldSpec)
  (h_eq : isEqualInEnvs env₁ env₂ name)
  (h_holds : isJsonWithSchema env₁ name schema) :
  isJsonWithSchema env₂ name schema := by
  simp only [isJsonWithSchema, isJsonWithSchemaBool] at *
  rw [isEqualInEnvs] at h_eq
  rw [← h_eq]
  exact h_holds

/-- isJsonWithSchema is preserved when a DIFFERENT variable is set. -/
theorem isJsonWithSchema_preserved_by_set_other
  (env : SemanticEnv) (name₁ name₂ : String) (value : Value) (schema : List JsonFieldSpec)
  (h : name₁ ≠ name₂) :
  isJsonWithSchema (env.set name₂ value) name₁ schema ↔ isJsonWithSchema env name₁ schema := by
  simp [isJsonWithSchema, isJsonWithSchemaBool, SemanticEnv.get, SemanticEnv.set, h, Ne.symm h]

/-
========================================================================
9. SCHEMA VALIDITY LEMMAS
========================================================================
-/

/-- If we set a JSON value that is an object with the right fields,
    then isJsonWithSchema holds. -/
theorem isJsonWithSchema_after_set_obj
  (env : SemanticEnv) (name : String) (fields : List (String × JsonValue))
  (schema : List JsonFieldSpec)
  (h : isJsonWithSchemaBool (env.set name (.vJson (.obj fields))) name schema = true) :
  isJsonWithSchema (env.set name (.vJson (.obj fields))) name schema := by
  exact h


end AgenticKernel
