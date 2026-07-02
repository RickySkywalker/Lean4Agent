import Lean
import Mathlib

namespace AgenticKernel

/-
----------------------------------------------------------------------
JSON SCHEMA
----------------------------------------------------------------------

The Json is an important part of the value and for the LLM interaction, we give our definition of Json values and a recursive schema type to describe expected structures
-/

/-- Runtime value type, indexed morally by `BaseType`.
    Every variable in the workflow environment holds a `Value`. -/
inductive JsonValue where
  | null   : JsonValue
  | bool   : Bool → JsonValue
  | num    : Float → JsonValue
  | str    : String → JsonValue
  | arr    : List JsonValue → JsonValue
  | obj    : List (String × JsonValue) → JsonValue
  deriving Repr, Inhabited, BEq

/--
A recursive Json schema type that mirrors the JsonValue structure. It can express nested types like array of objects with keys x y
  Examples:
    .jString                              -- a string
    .jArray (.jString)                    -- array of strings
    .jObject [("name", .jString),
              ("scores", .jArray .jNum)]  -- object with nested schema
    .jAny                                 -- any JSON value
This structure models the schema itself rather than a value, so it doesn't carry actual data but describes the expected shape of JSON values.
-/
inductive JsonSchema where
  | jString : JsonSchema
  | jNum : JsonSchema
  | jBool : JsonSchema
  | jNull : JsonSchema
  | jArray : JsonSchema → JsonSchema
  | jObject : List (String × JsonSchema) → JsonSchema
  | jAny : JsonSchema
  deriving Repr, Inhabited


/-
Define the BEq for JsonSchema (mutual mutual recursion)
-/
mutual
/--Auxiliary function for checking equality of JsonSchema -/
def JsonSchema.beqAux : JsonSchema → JsonSchema → Bool
  | .jString, .jString => true
  | .jNum, .jNum => true
  | .jBool, .jBool => true
  | .jNull, .jNull => true
  | .jAny, .jAny => true
  | .jArray a, .jArray b => JsonSchema.beqAux a b
  | .jObject fields1, .jObject fields2 => JsonSchema.beqFieldsAux fields1 fields2
  | _, _ => false

/--Auxiliary function for checking equality of JsonSchema fields -/
def JsonSchema.beqFieldsAux : List (String × JsonSchema) → List (String × JsonSchema) → Bool
  | [], [] => true
  | (k1, v1) :: rest1, (k2, v2) :: rest2 =>
    k1 == k2 && JsonSchema.beqAux v1 v2 && JsonSchema.beqFieldsAux rest1 rest2
  | _, _ => false
end

instance : BEq JsonSchema where
  beq := JsonSchema.beqAux


/-Prove Soundness (beq = true → eq)-/

mutual
/-- Prove soundness of JsonSchema.beqAux -/
theorem JsonSchema.beqAux_sound : ∀ (a b : JsonSchema), JsonSchema.beqAux a b = true → a = b := by
  intro a b
  cases a <;> cases b <;> simp [JsonSchema.beqAux]
  -- jArray case
  case jArray.jArray a b =>
    intro h
    have eqAB := JsonSchema.beqAux_sound a b h
    rw [eqAB]
  -- jObject case
  case jObject.jObject fields1 fields2 =>
    intro h
    have eqFields := JsonSchema.beqFieldsAux_sound fields1 fields2 h
    rw [eqFields]

/-- Prove soundness of JsonSchema.beqFieldsAux -/
theorem JsonSchema.beqFieldsAux_sound :
    ∀ (a b : List (String × JsonSchema)), JsonSchema.beqFieldsAux a b = true → a = b := by
  intro a b h
  match a, b with
  | [], [] => rfl
  | [], _ :: _ => simp [JsonSchema.beqFieldsAux] at h
  | _ :: _, [] => simp [JsonSchema.beqFieldsAux] at h
  | (k1, v1) :: tail1, (k2, v2) :: tail2 =>
    simp [JsonSchema.beqFieldsAux] at h
    have ⟨⟨hk, hv⟩, hrest⟩ := h
    have eqV := JsonSchema.beqAux_sound v1 v2 hv
    have eqTail := JsonSchema.beqFieldsAux_sound tail1 tail2 hrest
    subst hk eqV eqTail
    rfl
end

/- Prove Reflexivity (beq a a = true) -/

mutual
theorem JsonSchema.beqAux_refl : ∀ (a : JsonSchema), JsonSchema.beqAux a a = true := by
  intro a
  cases a <;> simp [JsonSchema.beqAux]
  case jArray a => exact JsonSchema.beqAux_refl a
  case jObject fields => exact JsonSchema.beqFieldsAux_refl fields

theorem JsonSchema.beqFieldsAux_refl :
    ∀ (a : List (String × JsonSchema)), JsonSchema.beqFieldsAux a a = true := by
  intro a
  match a with
  | [] => simp [JsonSchema.beqFieldsAux]
  | (k, v) :: tl =>
    simp [JsonSchema.beqFieldsAux, JsonSchema.beqAux_refl, JsonSchema.beqFieldsAux_refl]
end

/- Construct DecidableEq from soundness + reflexivity -/
instance : DecidableEq JsonSchema := fun a b =>
  match h : JsonSchema.beqAux a b with
  | true  => isTrue (JsonSchema.beqAux_sound a b h)
  | false => isFalse fun heq => by
    subst heq
    rw [JsonSchema.beqAux_refl a] at h
    exact Bool.noConfusion h

/- Hashable instance -/
mutual
partial def JsonSchema.hashImpl : JsonSchema → UInt64
  | .jString => 0
  | .jNum => 1
  | .jBool => 2
  | .jNull => 3
  | .jArray elemSchema => mixHash 4 elemSchema.hashImpl
  | .jObject fields => mixHash 5 (JsonSchema.hashFieldsImpl fields)
  | .jAny => 6

partial def JsonSchema.hashFieldsImpl : List (String × JsonSchema) → UInt64
  | [] => 0
  | (k, v) :: rest => mixHash (mixHash (hash k) v.hashImpl) (JsonSchema.hashFieldsImpl rest)
end

instance : Hashable JsonSchema where
  hash := JsonSchema.hashImpl

/-- Lookup a key in a Json object's field list. -/
def jsonLookup
  (fields : List (String × JsonValue))
  (key : String) : Option JsonValue :=
  fields.find? (fun p => p.1 == key) |>.map (·.2)

/-- Check whether a Jsonvalue matches a JsonSchema under prop type and doing it recursively. It defined as an inductive relation to avoid termination issues.-/
inductive JsonMatchesSchema : JsonValue → JsonSchema → Prop where
  | null : JsonMatchesSchema .null .jNull
  | bool : ∀ b, JsonMatchesSchema (.bool b) .jBool
  | num : ∀ n, JsonMatchesSchema (.num n) .jNum
  | str : ∀ s, JsonMatchesSchema (.str s) .jString
  | arr : ∀ items elemSchema,
          (∀ item ∈ items, JsonMatchesSchema item elemSchema) →
          JsonMatchesSchema (.arr items) (.jArray elemSchema)
  | obj : ∀ fields fieldSchemas,
          -- Witness: for each field specific, provide the matching value
          (witness : ∀ key schema, (key, schema) ∈ fieldSchemas → JsonValue) →
          -- Condition 1: The witness is found by lookup
          (∀ (key : String) (schema : JsonSchema) (h : (key, schema) ∈ fieldSchemas),
            jsonLookup fields key = some (witness key schema h)) →
          -- Condition 2: the witness matches the sub-schema
          (∀ (key : String) (schema : JsonSchema) (h : (key, schema) ∈ fieldSchemas),
            JsonMatchesSchema (witness key schema h) schema) →
          JsonMatchesSchema (.obj fields) (.jObject fieldSchemas)
  | any : ∀ j, JsonMatchesSchema j .jAny  -- Any JSON value matches jAny schema

/- Check whether a json value matches a JsonSchema -/
mutual
def jsonValueMatchesWithSchema : JsonValue → JsonSchema → Bool
  | .null, .jNull => true
  | .bool _, .jBool => true
  | .num _, .jNum => true
  | .str _, .jString => true
  | .arr items, .jArray elementSchema =>
    jsonValueListMatchesWithSchema items elementSchema
  | .obj fields, .jObject fieldSchemas =>
    jsonValueFieldMatchesWithSchemaFields fields fieldSchemas
  | _, .jAny => true
  | _, _ => false


def jsonValueListMatchesWithSchema : List JsonValue → JsonSchema → Bool
  | [], _ => true
  | item :: otherElements, schema =>
    jsonValueMatchesWithSchema item schema && jsonValueListMatchesWithSchema otherElements schema

/-- Check whether a json object field matches every fields required by the schema and the type of the coneten is correct -/
def jsonValueFieldMatchesWithSchemaFields : List (String × JsonValue) → List (String × JsonSchema) → Bool
  | _, [] => true     -- if schema has no fields, any object matches
  | fields, (key, schema) :: otherElements =>
    match jsonLookup fields key with
    | some v => jsonValueMatchesWithSchema v schema && jsonValueFieldMatchesWithSchemaFields fields otherElements
    | none => false
end


mutual
/-- Check if JsonSchema s1 implies s2 (s1 is at least as specific as s2) -/
def JsonSchema.implies (s1 s2 : JsonSchema) : Bool :=
  match s1, s2 with
  | _, .jAny => true
  | .jString, .jString => true
  | .jNum, .jNum => true
  | .jBool, .jBool => true
  | .jNull, .jNull => true
  | .jArray elem1, .jArray elem2 => elem1.implies elem2
  | .jObject fields1, .jObject fields2 =>
    JsonSchema.impliesFields fields1 fields2
  | _, _ => false

/-- Helper: check if all fields in fields2 are implied by some field in fields1 -/
def JsonSchema.impliesFields (fields1 fields2 : List (String × JsonSchema)) : Bool :=
  match fields2 with
  | [] => true
  | (key2, schema2) :: rest =>
    match fields1.find? (fun (k, _) => k == key2) with
    | some (_, schema1) => schema1.implies schema2 && JsonSchema.impliesFields fields1 rest
    | none => false
end


/-
========================================================================
JSON SCHEMA NORMALIZATION & SEMANTIC EQUALITY
========================================================================

For predicate matching, we need order-independent comparison of JsonSchema.
JSON objects are fundamentally dictionaries, so field order should not
affect semantic equality.

Two approaches:
1. `normalize`: Sort fields alphabetically before comparison
2. `semanticBEq`: Order-independent equality check

We provide both. `normalize` is preferred for PredicateKey storage
because it produces a canonical form that can be compared with ==.
-/

/-- Sort fields by key name (alphabetically), recursively. -/
partial def JsonSchema.normalize : JsonSchema → JsonSchema
  | .jString => .jString
  | .jNum => .jNum
  | .jBool => .jBool
  | .jNull => .jNull
  | .jAny => .jAny
  | .jArray elemSchema => .jArray elemSchema.normalize
  | .jObject fields =>
    let normalizedFields := fields.map fun (k, s) => (k, s.normalize)
    let sortedFields := normalizedFields.toArray.qsort (fun (k1, _) (k2, _) => k1 < k2) |>.toList
    .jObject sortedFields

/-- Order-independent semantic equality for JsonSchema.
    For jObject, compares fields as sets rather than lists.
    Note: This compares normalized schemas to avoid mutual recursion complexity. -/
def JsonSchema.semanticBEq (s1 s2 : JsonSchema) : Bool :=
  s1.normalize == s2.normalize

end AgenticKernel
