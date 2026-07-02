import Lean
import Mathlib

namespace AgenticKernel

/-
========================================================================
1. BASE VALUE TYPES
========================================================================
-/

/-- Base types that can go through all the workflow --/
inductive BaseType where
  | TUnit : BaseType   -- Unit or default type
  | TString : BaseType    -- string value
  | TInt : BaseType   -- integer value
  | TFloat : BaseType -- float value
  | TBool : BaseType  -- boolean value
  | TJson : BaseType  -- unstructured json data value
  | TList : BaseType → BaseType -- list of base types
  | TDict : BaseType -> BaseType -> BaseType  -- dictionary type with key and value types
  | TSet : BaseType → BaseType  -- set of base types
  | TOption : BaseType -> BaseType -- optional base type
  | TRecord : List (String × BaseType) -> BaseType  -- structured record type
  | TUnknown : BaseType  -- unknown type for gradual typing
  deriving Repr, Hashable, Inhabited

def TypeEnv := Std.HashMap String BaseType


mutual
/-- We need to firstly hand-written the BEq-/
def BaseType.beqAux : BaseType → BaseType → Bool
  | .TUnit,    .TUnit    => true
  | .TString,  .TString  => true
  | .TInt,     .TInt     => true
  | .TFloat,   .TFloat   => true
  | .TBool,    .TBool    => true
  | .TJson,    .TJson    => true
  | .TUnknown, .TUnknown => true
  | .TList a,      .TList b      => BaseType.beqAux a b
  | .TSet a,       .TSet b       => BaseType.beqAux a b
  | .TOption a,    .TOption b    => BaseType.beqAux a b
  | .TDict k1 v1,  .TDict k2 v2  => BaseType.beqAux k1 k2 && BaseType.beqAux v1 v2
  | .TRecord fs1,  .TRecord fs2  => BaseType.beqFieldsAux fs1 fs2
  | _, _ => false

def BaseType.beqFieldsAux : List (String × BaseType) → List (String × BaseType) → Bool
  | [], [] => true
  | (s1, t1) :: rest1, (s2, t2) :: rest2 =>
    s1 == s2 && BaseType.beqAux t1 t2 && BaseType.beqFieldsAux rest1 rest2
  | _, _ => false
end

instance : BEq BaseType where
  beq := BaseType.beqAux

mutual
/--Then we will write prove the soundness (beq = true → eq) and completeness (eq → beq = true) -/
theorem BaseType.beqAux_sound : ∀ (a b : BaseType), BaseType.beqAux a b = true -> a = b := by
  intro a b
  cases a <;> cases b <;> simp [BaseType.beqAux]
  -- TList case
  case TList.TList a b =>
    intro h
    have : BaseType.beqAux a b = true := h
    have eqAB := BaseType.beqAux_sound a b this
    rw [eqAB]
  -- TSet case
  case TSet.TSet a b =>
    intro h
    have : BaseType.beqAux a b = true := h
    have eqAB := BaseType.beqAux_sound a b this
    rw [eqAB]
  -- TOption case
  case TOption.TOption a b =>
    intro h
    have : BaseType.beqAux a b = true := h
    have eqAB := BaseType.beqAux_sound a b this
    rw [eqAB]
  -- TDict case
  case TDict.TDict k1 v1 k2 v2 =>
    intro hk hv
    have eqK := BaseType.beqAux_sound k1 k2 hk
    have eqV := BaseType.beqAux_sound v1 v2 hv
    rw [eqK, eqV]
    simp [eqK, eqV]
  -- TRecord case
  case TRecord.TRecord fields1 fields2 =>
    intro h
    have eqFields := BaseType.beqFieldsAux_sound fields1 fields2 h
    rw [eqFields]

theorem BaseType.beqFieldsAux_sound :
  ∀ (a b : List (String × BaseType)), BaseType.beqFieldsAux a b = true → a = b := by
  intro a b h
  match a, b with
  | [], [] => rfl
  | [], _ :: _ => simp [BaseType.beqFieldsAux] at h
  | _ :: _, [] => simp [BaseType.beqFieldsAux] at h
  | (s1, t1) :: tail1, (s2, t2) :: tail2 =>
    simp [BaseType.beqFieldsAux] at h
    have ⟨⟨hs, ht⟩, hrest⟩ := h
    -- Recursive calls for head and tail
    have eqT := BaseType.beqAux_sound t1 t2 ht
    -- Recursive call for tail list (directly calling function name instead of inductionHyp)
    have eqTail := BaseType.beqFieldsAux_sound tail1 tail2 hrest
    subst hs eqT eqTail
    rfl
end

mutual
theorem BaseType.beqAux_refl : ∀ (a : BaseType), BaseType.beqAux a a = true := by
  intro a
  cases a <;> simp [BaseType.beqAux]
  case TList a => exact BaseType.beqAux_refl a
  case TSet a => exact BaseType.beqAux_refl a
  case TOption a => exact BaseType.beqAux_refl a
  case TDict k v =>
    exact ⟨BaseType.beqAux_refl k, BaseType.beqAux_refl v⟩
  case TRecord fs => exact BaseType.beqFieldsAux_refl fs

theorem BaseType.beqFieldsAux_refl :
    ∀ (a : List (String × BaseType)), BaseType.beqFieldsAux a a = true := by
  intro a
  match a with
  | [] => simp [BaseType.beqFieldsAux]
  | (s, t) :: tl =>
    simp [BaseType.beqFieldsAux, BaseType.beqAux_refl, BaseType.beqFieldsAux_refl]
end

instance : DecidableEq BaseType := fun a b =>
  match h : BaseType.beqAux a b with
  | true  => isTrue (BaseType.beqAux_sound a b h)
  | false => isFalse fun heq => by
    subst heq
    rw [BaseType.beqAux_refl a] at h
    exact Bool.noConfusion h

/-- Infer corresponding BaseType from a Lean Expr -/
partial def inferBaseType
  (e : Lean.Expr) : Lean.MetaM BaseType
:= do
  let type <- Lean.Meta.inferType e
  let type <- Lean.Meta.whnf type

  match type with
    | .const `String _ => return BaseType.TString
    | .const `Int _ => return BaseType.TInt
    | .const `Float _ => return BaseType.TFloat
    | .const `Bool _ => return BaseType.TBool
    | .const `Unit _ => return BaseType.TUnit
    | .app (.const `List _) elemType =>
      let bt <- inferBaseType elemType
      return BaseType.TList bt
    | .app (.app (.const `Option _) _) innerType =>
      let bt <- inferBaseType innerType
      return BaseType.TOption bt
    | _ => return BaseType.TUnknown

/-- Transform from basic Lean type into the BaseType's type value-/
class ToBaseType (α : Type) where
  toBaseType : BaseType

instance : ToBaseType String where
  toBaseType := BaseType.TString

instance : ToBaseType Int where
  toBaseType := BaseType.TInt

instance : ToBaseType Float where
  toBaseType := BaseType.TFloat

instance : ToBaseType Bool where
  toBaseType := BaseType.TBool

instance : ToBaseType Unit where
  toBaseType := BaseType.TUnit

instance {α} [ToBaseType α] : ToBaseType (List α) where
  toBaseType := BaseType.TList (ToBaseType.toBaseType (α := α))

instance {α} [ToBaseType α] : ToBaseType (Option α) where
  toBaseType := BaseType.TOption (ToBaseType.toBaseType (α := α))

/-- Convert BaseType back to Lean type as Lean.Expr-/
def baseTypeToLeanType
  (bt : BaseType) : Lean.MetaM Lean.Expr
:= do
  match bt with
    | .TUnit => return .const `Unit []
    | .TString => return .const `String []
    | .TInt => return .const `Int []
    | .TFloat => return .const `Float []
    | .TBool => return .const `Bool []
    | .TJson => return .const `Lean.Json []
    | .TList elemType =>
      let elemExpr <- baseTypeToLeanType elemType
      return .app (.const `List []) elemExpr
    | .TDict keyType valType =>
      let keyExpr <- baseTypeToLeanType keyType
      let valExpr <- baseTypeToLeanType valType
      return .app (.app (.const `Std.HashMap []) keyExpr) valExpr
    | .TSet elemType =>
      let elemExpr <- baseTypeToLeanType elemType
      return .app (.const `Std.HashSet []) elemExpr
    | .TOption innerType =>
      let innerExpr <- baseTypeToLeanType innerType
      return .app (.const `Option []) innerExpr
    | .TRecord fields =>
      -- For simplicity, we can represent records as JSON objects in Lean
      return .const `Lean.Json []
    | .TUnknown =>
      -- We can represent unknown types as Unit in Lean for now
      return .const `Unit []

/-- Type class for converting BaseType to concrete Lean types --/
class FromBaseType (bt : BaseType) where
  LeanType : Type

instance : FromBaseType .TString where
  LeanType := String

instance : FromBaseType .TInt where
  LeanType := Int

instance : FromBaseType .TFloat where
  LeanType := Float

instance : FromBaseType .TBool where
  LeanType := Bool

instance : FromBaseType .TUnit where
  LeanType := Unit

instance {bt} [FromBaseType bt] : FromBaseType (.TList bt) where
  LeanType := List (FromBaseType.LeanType (bt := bt))

instance {bt} [FromBaseType bt] : FromBaseType (.TOption bt) where
  LeanType := Option (FromBaseType.LeanType (bt := bt))

mutual
/-- Type compatibility: This function answers can a value of type `a` flow into a slot expecting type `b`?-/
def BaseType.compatible : BaseType -> BaseType -> Bool
  | .TUnknown, _         => true
  | _, .TUnknown         => true
  | .TUnit, .TUnit       => true
  | .TString, .TString   => true
  | .TInt, .TInt         => true
  | .TFloat, .TFloat     => true
  | .TBool, .TBool       => true
  | .TJson, .TJson       => true
  | .TInt, .TFloat       => true
  | .TJson, .TString     => true
  | .TString, .TJson     => true
  | .TList a, .TList b         => compatible a b
  | .TOption a, .TOption b     => compatible a b
  | .TSet a, .TSet b           => compatible a b
  | .TDict k1 v1, .TDict k2 v2 => compatible k1 k2 && compatible v1 v2
  | .TRecord fields1, .TRecord fields2 =>
    BaseType.compatibleFields fields1 fields2
  | _, _ => false
  -- | .TUnknown, _ => true  -- unknown can flow into any type
  -- | _, .TUnknown => true
  -- | .TString, .TString => true
  -- | .TInt, .TInt => true
  -- | .TInt, .TFloat => true  -- int can flow into float
  -- | .TList a, .TList b => compatible a b
  -- | .TOption a, .TOption b => compatible a b
  -- | a, b => a == b

def BaseType.compatibleFields
  (fields1 fields2 : List (String × BaseType)) : Bool :=
  match fields2 with
  | [] => true
  | (name, type2) :: rest =>
    let found := match fields1.find? (fun (n, _) => n == name) with
      | some (_, type1) => BaseType.compatible type1 type2
      | none => false
    found && BaseType.compatibleFields fields1 rest
end
