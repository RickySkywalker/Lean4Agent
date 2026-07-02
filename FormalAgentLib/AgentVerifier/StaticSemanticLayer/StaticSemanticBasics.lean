import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema

namespace AgenticKernel


/-
╔══════════════════════════════════════════════════════════════════════════╗
║  LAYER 2: SEMANTIC VERIFICATION LAYER                                  ║
║                                                                        ║
║  Preconditions and postconditions are REAL Lean `Prop`s, not strings.  ║
║  This allows the Lean type checker to participate in verification.     ║
║                                                                        ║
║  Design Philosophy (inspired by VERINA):                               ║
║  - A universal `Value` type mirrors `BaseType` with actual data        ║
║  - `SemanticEnv` maps variable names to `Value`                        ║
║  - Preconditions:  `SemanticEnv → Prop`                                ║
║  - Postconditions: `SemanticEnv → SemanticEnv → Prop`                  ║
║  - LLM execution is axiomatized (sorry / axiom)                        ║
║  - Chain theorems (prev postcond → next precond) are PROVED in Lean    ║
╚══════════════════════════════════════════════════════════════════════════╝
-/

/-
========================================================================
PART 1: VALUE UNIVERSE
========================================================================

`Value` is the universal runtime value type. Every piece of data that
flows through the workflow — strings, ints, lists, JSON — is embedded
into `Value`. This gives us a single type to quantify over in
preconditions and postconditions, while retaining the ability to
pattern-match on the concrete form.

`Value` mirrors `BaseType`: for each `BaseType` constructor there is
a corresponding `Value` constructor that carries the actual data.
-/




inductive Value where
  | vUnit   : Value
  | vString : String → Value
  | vInt    : Int → Value
  | vFloat  : Float → Value
  | vBool   : Bool → Value
  | vJson   : JsonValue → Value
  | vList   : List Value → Value
  | vDict   : List (Value × Value) → Value
  | vSet    : List Value → Value
  | vOption : Option Value → Value
  | vRecord : List (String × Value) → Value
  deriving Repr, Inhabited

/-- Extract the `BaseType` tag of a `Value` (inverse of the embedding). -/
def Value.typeTag : Value → BaseType
  | .vUnit => .TUnit
  | .vString _   => .TString
  | .vInt _      => .TInt
  | .vFloat _    => .TFloat
  | .vBool _     => .TBool
  | .vJson _     => .TJson
  | .vList _     => .TList .TUnknown  -- element type erased at this level
  | .vDict _     => .TDict .TUnknown .TUnknown
  | .vSet _      => .TSet .TUnknown
  | .vOption _   => .TOption .TUnknown
  | .vRecord _   => .TRecord []

/-- Check that a `Value` is compatible with an expected `BaseType`. -/
def Value.compatibleWith (v : Value) (bt : BaseType) : Bool :=
  v.typeTag.compatible bt

/-
========================================================================
PART 2: SEMANTIC ENVIRONMENT (Function Representation)
========================================================================

`SemanticEnv` is a function `String → Option Value`.
- `none` means the variable is not yet assigned.
- `some v` means the variable holds value `v`.

This representation makes frame condition proofs trivial:
  `env.set "x" v |>.get "y" = env.get "y"`
reduces to an if-then-else that `simp` handles directly.
-/

/-- The semantic environment: a total function from variable names to optional values. -/
def SemanticEnv := String → Option Value

namespace SemanticEnv

@[simp]
def get (env : SemanticEnv) (name : String) : Option Value := env name

/-- Set a variable, leaving all others unchanged. -/
@[simp]
def set (env : SemanticEnv) (name : String) (value : Value) : SemanticEnv :=
  fun k => if k == name then some value else env k

/-- The empty environment (nothing assigned). -/
def empty : SemanticEnv := fun _ => none

/-- Set multiple variables at once. -/
def setMultiVar
  (env : SemanticEnv)
  (bindings : List (String × Value)):SemanticEnv :=
  bindings.foldl (fun accumulator (n, v) => accumulator.set n v) env

/-! ### Core lemmas for `set` -/

/-- Reading the variable we just wrote returns the new value. -/
@[simp]
theorem get_set_identical
  (env : SemanticEnv) (name : String) (value : Value) :
  (env.set name value).get name = some value := by simp [get, set]

/-- Reading a DIFFERENT variable after a write returns the old value. -/
@[simp]
theorem get_set_different
  (env : SemanticEnv)
  (name₁ name₂ : String)
  (value : Value)
  (h : name₂ ≠ name₁) :
  (env.set name₁ value).get name₂ = env.get name₂ := by simp [get, set, h]

/-- Two consecutive writes to the same variable: last write wins. -/
@[simp]
theorem set_set_identical
  (env : SemanticEnv) (name : String) (value₁ value₂ : Value):
  (env.set name value₁).set name value₂ = env.set name value₂:= by
  funext k
  simp[set]
  split <;> rfl

/-- Two writes to different variables commute. -/
@[simp]
theorem set_set_commute
  (env : SemanticEnv)
  (name₁ name₂ : String)
  (value₁ value₂ : Value)
  (h : name₂ ≠ name₁) :
  (env.set name₁ value₁).set name₂ value₂ = (env.set name₂ value₂).set name₁ value₁ := by
  funext k
  simp [set]
  split <;> simp_all [h]

end SemanticEnv
end AgenticKernel
