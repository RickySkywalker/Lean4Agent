import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended

namespace AgenticKernel

/-
# Section 1: Concret Predicate Types and extensable predicate
PredicateType is a decidable representation of predicate types. Each type corresponds to an existing Prop predicate.
-/

/-
## Section 1.1: Mutual inductive definitions for PredicateType, PredicateKey, and ArgValue
-/
mutual
/-- PredicateType is a decidable representation of predicate types. Each type corresponds to an existing prop predicates via the `toProp`. -/
inductive PredicateType where
  | nameExists      -- The base predicate checks whether a variable name exists in the environment.
  | isNonEmptyString -- The base predicate checks whether a variable is a non-empty string.
  | isNonEmptyList   -- The base predicate checks whether a variable is a non-empty list.
  | isValidURL        -- Whether the URL is valid, correcponding to the `isValidURL` predicate in SemanticPredicates
  | isValidFilePath   -- Whether the file path is valid, corresponding to the `isValidFilePath` predicate in SemanticPredicates
  | isValidPath       -- Whether the path (file or URL) is valid, corresponding to the `isValidPath` predicate in SemanticPredicates
  | isValidBibtex   -- Whether the Bibtex entry is valid, corresponding to the `isValidBibtex` predicate in SemanticPredicates
  | isValidLatex   -- Whether the LaTeX string is valid, corresponding to the `isValidLatex` predicate in SemanticPredicates
  | isValidJson   -- Whether the JSON string is valid, corresponding to the `isValidJson` predicate in SemanticPredicates
  | isValidList -- Whether the value is a valid list, corresponding to the `isValidList` predicate in SemanticPredicates
  | toolExists  -- Whether the tool exists in the environment, corresponding to the `toolExists` predicate in SemanticPredicates
  | moduleExists -- Whether the module exists in the environment, corresponding to the `moduleExists` predicate in SemanticPredicates
  | isInt   -- Whether the variable is an integer, corresponding to the `isInt` predicate in temp_SemanticPredicatesExtended
  | matchesJsonSchema (schema : JsonSchema)   -- Whether the provided json schema matches, we perform recursive checking.
  | isJsonWithFields (fields : List JsonFieldSpec)  -- Whether the provided json value has the specified fields, it is sued for compatibility
  | containsSubstring (substring : String)  -- Whether the string variable contains the given substring (for sentinel detection)
  | fileExistsAtPath  -- Whether the variable represents a path to an existing file (runtime check, static just tracks intent)
  | taskCompleted  -- Marker predicate: task has been completed (semantic intent, not runtime verified)
  | custom (name : String) -- The base type for user defined predicates
  | ext (key : PredicateKey) -- The base type for extensible predicates, the semantics of which are defined in the registry
  -- Propositional connectives for composing predicates
  | predicateAnd (p₁ p₂ : PredicateType)  -- Logical AND of two predicates
  | predicateOr (p₁ p₂ : PredicateType)  -- Logical OR of two predicates
  deriving Repr, Inhabited, Hashable

/-- Typed argument values for PredicateKey, each variant preserves structure for reliable equality checking -/
inductive ArgValue where
  | argStr : String → ArgValue  -- Simple string argument
  | argInt : Int → ArgValue     -- Integer argument
  | argJsonSchema : JsonSchema → ArgValue -- JsonSchema argument
  | argJsonSchemas : List JsonSchema → ArgValue -- List of JsonSchemas for complex predicates
  | argPredType : PredicateType → ArgValue -- Single predicate type by direct compare
  | argPredTypes : List PredicateType → ArgValue -- List of predicate types for complex compatibility rules
  deriving Repr, Inhabited, Hashable

/-- Universal identity for any predicate, base or user-defined. Uses ArgValue for type-safe argument storrage with reliable equality -/
inductive PredicateKey where
  | makePredicateKey : (family : String) → (name : String) → (args : List ArgValue) → PredicateKey
deriving Repr, Inhabited, Hashable
end

/-
Accessors for PredicateKey
-/
def PredicateKey.family : PredicateKey → String
  | .makePredicateKey family _ _ => family

def PredicateKey.name : PredicateKey → String
  | .makePredicateKey _ name _ => name

def PredicateKey.args : PredicateKey → List ArgValue
  | .makePredicateKey _ _ args => args

/-
Inhabeted instances
-/
instance : Inhabited PredicateType where
  default := .nameExists

instance : Inhabited ArgValue where
  default := .argStr ""

instance : Inhabited PredicateKey where
  default := .makePredicateKey "" "" []

/-
### Section 1.1.1: Repr instances for PredicateType, ArgValue, and PredicateKey
-/

-- Repr instances (simple string representation)
-- Use mutual block since they reference each other
mutual
  partial def PredicateType.reprAux : PredicateType → String
    | .nameExists => "nameExists"
    | .isNonEmptyString => "isNonEmptyString"
    | .isNonEmptyList => "isNonEmptyList"
    | .isValidURL => "isValidURL"
    | .isValidFilePath => "isValidFilePath"
    | .isValidPath => "isValidPath"
    | .isValidBibtex => "isValidBibtex"
    | .isValidLatex => "isValidLatex"
    | .isValidJson => "isValidJson"
    | .isValidList => "isValidList"
    | .toolExists => "toolExists"
    | .moduleExists => "moduleExists"
    | .isInt => "isInt"
    | .fileExistsAtPath => "fileExistsAtPath"
    | .taskCompleted => "taskCompleted"
    | .matchesJsonSchema s => s!"matchesJsonSchema({reprStr s})"
    | .isJsonWithFields f => s!"isJsonWithFields({reprStr f})"
    | .containsSubstring s => s!"containsSubstring({s})"
    | .custom n => s!"custom({n})"
    | .ext k => s!"ext({PredicateKey.reprAux k})"
    | .predicateAnd p₁ p₂ => s!"({PredicateType.reprAux p₁} ∧ {PredicateType.reprAux p₂})"
    | .predicateOr p₁ p₂ => s!"({PredicateType.reprAux p₁} ∨ {PredicateType.reprAux p₂})"

  partial def ArgValue.reprAux : ArgValue → String
    | .argStr s => s!"str({s})"
    | .argInt i => s!"int({i})"
    | .argJsonSchema s => s!"schema({reprStr s})"
    | .argJsonSchemas ss => s!"schemas({reprStr ss})"
    | .argPredType p => s!"predType({PredicateType.reprAux p})"
    | .argPredTypes ps => s!"predTypeList([{String.intercalate ", " (ps.map PredicateType.reprAux)}])"

  partial def PredicateKey.reprAux : PredicateKey → String
    | .makePredicateKey f n a => s!"PredicateKey({f}, {n}, [{String.intercalate ", " (a.map ArgValue.reprAux)}])"
end

instance : Repr PredicateType where
  reprPrec p _ := PredicateType.reprAux p

instance : Repr ArgValue where
  reprPrec a _ := ArgValue.reprAux a

instance : Repr PredicateKey where
  reprPrec k _ := PredicateKey.reprAux k

-- Hashable instances
instance : Hashable PredicateType where
  hash p := hash (PredicateType.reprAux p)

instance : Hashable ArgValue where
  hash a := hash (ArgValue.reprAux a)

instance : Hashable PredicateKey where
  hash k := hash (PredicateKey.reprAux k)

/-
### Section 1.1.2: JSON serialization for `PredicateType` (used for IO-mode external checker protocol)

Produces a structured, machine-parsable `Lean.Json` encoding of a predicate.
Every constructor becomes a tagged object of the form
    { "kind": "<constructor>", <parameters> ... }
so a Python checker can dispatch on `kind` and read real parameters
(schema, substring, nested predicates for ext, ...) without fragile
string parsing of the `reprAux` output.
-/

/-- Serialize a `JsonSchema` to `Lean.Json`. -/
partial def JsonSchema.toJson : JsonSchema → Lean.Json
  | .jString => Lean.Json.mkObj [("type", Lean.Json.str "jString")]
  | .jNum    => Lean.Json.mkObj [("type", Lean.Json.str "jNum")]
  | .jBool   => Lean.Json.mkObj [("type", Lean.Json.str "jBool")]
  | .jNull   => Lean.Json.mkObj [("type", Lean.Json.str "jNull")]
  | .jAny    => Lean.Json.mkObj [("type", Lean.Json.str "jAny")]
  | .jArray elem =>
      Lean.Json.mkObj [
        ("type",  Lean.Json.str "jArray"),
        ("items", JsonSchema.toJson elem)
      ]
  | .jObject fields =>
      let fieldJsons : List Lean.Json := fields.map (fun (k, s) =>
        Lean.Json.mkObj [
          ("key",    Lean.Json.str k),
          ("schema", JsonSchema.toJson s)
        ])
      Lean.Json.mkObj [
        ("type",   Lean.Json.str "jObject"),
        ("fields", Lean.Json.arr fieldJsons.toArray)
      ]

/-- Serialize a `JsonFieldType` to `Lean.Json` (encoded as a plain string tag). -/
def JsonFieldType.toJson : JsonFieldType → Lean.Json
  | .jString => Lean.Json.str "jString"
  | .jNum    => Lean.Json.str "jNum"
  | .jBool   => Lean.Json.str "jBool"
  | .jArray  => Lean.Json.str "jArray"
  | .jObject => Lean.Json.str "jObject"
  | .jAny    => Lean.Json.str "jAny"

/-- Serialize a `JsonFieldSpec` to `Lean.Json`. -/
def JsonFieldSpec.toJson (f : JsonFieldSpec) : Lean.Json :=
  Lean.Json.mkObj [
    ("key",  Lean.Json.str f.key),
    ("type", JsonFieldType.toJson f.type)
  ]

/- Mutually recursive JSON serialization for `PredicateType`, `ArgValue`, `PredicateKey`. -/
mutual
  partial def PredicateType.toJson : PredicateType → Lean.Json
    | .nameExists       => Lean.Json.mkObj [("kind", Lean.Json.str "nameExists")]
    | .isNonEmptyString => Lean.Json.mkObj [("kind", Lean.Json.str "isNonEmptyString")]
    | .isNonEmptyList   => Lean.Json.mkObj [("kind", Lean.Json.str "isNonEmptyList")]
    | .isValidURL       => Lean.Json.mkObj [("kind", Lean.Json.str "isValidURL")]
    | .isValidFilePath  => Lean.Json.mkObj [("kind", Lean.Json.str "isValidFilePath")]
    | .isValidPath      => Lean.Json.mkObj [("kind", Lean.Json.str "isValidPath")]
    | .isValidBibtex    => Lean.Json.mkObj [("kind", Lean.Json.str "isValidBibtex")]
    | .isValidLatex     => Lean.Json.mkObj [("kind", Lean.Json.str "isValidLatex")]
    | .isValidJson      => Lean.Json.mkObj [("kind", Lean.Json.str "isValidJson")]
    | .isValidList      => Lean.Json.mkObj [("kind", Lean.Json.str "isValidList")]
    | .toolExists       => Lean.Json.mkObj [("kind", Lean.Json.str "toolExists")]
    | .moduleExists     => Lean.Json.mkObj [("kind", Lean.Json.str "moduleExists")]
    | .isInt            => Lean.Json.mkObj [("kind", Lean.Json.str "isInt")]
    | .fileExistsAtPath => Lean.Json.mkObj [("kind", Lean.Json.str "fileExistsAtPath")]
    | .taskCompleted    => Lean.Json.mkObj [("kind", Lean.Json.str "taskCompleted")]
    | .matchesJsonSchema s =>
        Lean.Json.mkObj [
          ("kind",   Lean.Json.str "matchesJsonSchema"),
          ("schema", JsonSchema.toJson s)
        ]
    | .isJsonWithFields fs =>
        Lean.Json.mkObj [
          ("kind",   Lean.Json.str "isJsonWithFields"),
          ("fields", Lean.Json.arr (fs.map JsonFieldSpec.toJson).toArray)
        ]
    | .containsSubstring s =>
        Lean.Json.mkObj [
          ("kind",      Lean.Json.str "containsSubstring"),
          ("substring", Lean.Json.str s)
        ]
    | .custom n =>
        Lean.Json.mkObj [
          ("kind", Lean.Json.str "custom"),
          ("name", Lean.Json.str n)
        ]
    | .ext k =>
        Lean.Json.mkObj [
          ("kind", Lean.Json.str "ext"),
          ("key",  PredicateKey.toJson k)
        ]
    | .predicateAnd p₁ p₂ =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "predicateAnd"),
          ("left",  PredicateType.toJson p₁),
          ("right", PredicateType.toJson p₂)
        ]
    | .predicateOr p₁ p₂ =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "predicateOr"),
          ("left",  PredicateType.toJson p₁),
          ("right", PredicateType.toJson p₂)
        ]

  partial def ArgValue.toJson : ArgValue → Lean.Json
    | .argStr s =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argStr"),
          ("value", Lean.Json.str s)
        ]
    | .argInt i =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argInt"),
          ("value", Lean.Json.num ⟨i, 0⟩)
        ]
    | .argJsonSchema s =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argJsonSchema"),
          ("value", JsonSchema.toJson s)
        ]
    | .argJsonSchemas ss =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argJsonSchemas"),
          ("value", Lean.Json.arr (ss.map JsonSchema.toJson).toArray)
        ]
    | .argPredType p =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argPredType"),
          ("value", PredicateType.toJson p)
        ]
    | .argPredTypes ps =>
        Lean.Json.mkObj [
          ("kind",  Lean.Json.str "argPredTypes"),
          ("value", Lean.Json.arr (ps.map PredicateType.toJson).toArray)
        ]

  partial def PredicateKey.toJson : PredicateKey → Lean.Json
    | .makePredicateKey family name args =>
        Lean.Json.mkObj [
          ("family", Lean.Json.str family),
          ("name",   Lean.Json.str name),
          ("args",   Lean.Json.arr (args.map ArgValue.toJson).toArray)
        ]
end

/-- Compressed JSON string for a `PredicateType`, used as the `pred_json` argv
    when invoking an external checker in IO mode. -/
def PredicateType.toJsonStr (p : PredicateType) : String :=
  (PredicateType.toJson p).compress

/-- Compressed JSON string for a `PredicateKey`. -/
def PredicateKey.toJsonStr (k : PredicateKey) : String :=
  (PredicateKey.toJson k).compress

/-
## Section 1.2: BEq and DecidableEq for mutual types
-/

mutual
  /-- BEq helper for PredicateType -/
  def PredicateType.beqAux : PredicateType → PredicateType → Bool
    | .nameExists, .nameExists => true
    | .isNonEmptyString, .isNonEmptyString => true
    | .isNonEmptyList, .isNonEmptyList => true
    | .isValidURL, .isValidURL => true
    | .isValidFilePath, .isValidFilePath => true
    | .isValidPath, .isValidPath => true
    | .isValidBibtex, .isValidBibtex => true
    | .isValidLatex, .isValidLatex => true
    | .isValidJson, .isValidJson => true
    | .isValidList, .isValidList => true
    | .toolExists, .toolExists => true
    | .moduleExists, .moduleExists => true
    | .isInt, .isInt => true
    | .fileExistsAtPath, .fileExistsAtPath => true
    | .taskCompleted, .taskCompleted => true
    | .matchesJsonSchema s₁, .matchesJsonSchema s₂ => s₁ == s₂
    | .isJsonWithFields f₁, .isJsonWithFields f₂ => f₁ == f₂
    | .containsSubstring s₁, .containsSubstring s₂ => s₁ == s₂
    | .custom n₁, .custom n₂ => n₁ == n₂
    | .ext k₁, .ext k₂ => PredicateKey.beqAux k₁ k₂
    | .predicateAnd l₁ r₁, .predicateAnd l₂ r₂ =>
        PredicateType.beqAux l₁ l₂ && PredicateType.beqAux r₁ r₂
    | .predicateOr l₁ r₁, .predicateOr l₂ r₂ =>
        PredicateType.beqAux l₁ l₂ && PredicateType.beqAux r₁ r₂
    | _, _ => false
  termination_by structural a => a

  def PredicateType.beqListAux : List PredicateType → List PredicateType → Bool
    | [], [] => true
    | p₁ :: ps₁, p₂ :: ps₂ =>
        PredicateType.beqAux p₁ p₂ && PredicateType.beqListAux ps₁ ps₂
    | _, _ => false
  termination_by structural ps₁ => ps₁

  /-- BEq helper for ArgValue -/
  def ArgValue.beqAux : ArgValue → ArgValue → Bool
    | .argStr s₁, .argStr s₂ => s₁ == s₂
    | .argInt i₁, .argInt i₂ => i₁ == i₂
    | .argJsonSchema s₁, .argJsonSchema s₂ => s₁ == s₂
    | .argJsonSchemas ss₁, .argJsonSchemas ss₂ => ss₁ == ss₂
    | .argPredType p₁, .argPredType p₂ => PredicateType.beqAux p₁ p₂
    | .argPredTypes ps₁, .argPredTypes ps₂ => PredicateType.beqListAux ps₁ ps₂
    | _, _ => false

  /-- BEq helper for lists of ArgValue -/
  def ArgValue.beqListAux : List ArgValue → List ArgValue → Bool
    | [], [] => true
    | a₁ :: as₁, a₂ :: as₂ => ArgValue.beqAux a₁ a₂ && ArgValue.beqListAux as₁ as₂
    | _, _ => false
  termination_by structural as₁ => as₁

  /-- BEq helper for PredicateKey -/
  def PredicateKey.beqAux : PredicateKey → PredicateKey → Bool
    | .makePredicateKey f₁ n₁ a₁, .makePredicateKey f₂ n₂ a₂ =>
        f₁ == f₂ && n₁ == n₂ && ArgValue.beqListAux a₁ a₂
end

instance : BEq PredicateType where
  beq := PredicateType.beqAux

instance : BEq ArgValue where
  beq := ArgValue.beqAux

instance : BEq PredicateKey where
  beq := PredicateKey.beqAux

/-- Map PredicateType to its corresponding Prop predicate. -/
def PredicateType.toProp
  (predType : PredicateType)
  (semanticEnv : SemanticEnv)
  (varName : String) : Prop :=
  match predType with
  -- Basic predicates (from SemanticPredicates.lean)
  | .nameExists => _root_.AgenticKernel.nameExists semanticEnv varName
  | .isNonEmptyString => _root_.AgenticKernel.isNonEmptyString semanticEnv varName
  | .isNonEmptyList => _root_.AgenticKernel.isNonEmptyList semanticEnv varName
  | .isInt => _root_.AgenticKernel.isInt semanticEnv varName
  -- File/URL predicates
  | .isValidURL => _root_.AgenticKernel.isValidURL semanticEnv varName
  | .isValidFilePath => _root_.AgenticKernel.isValidFilePath semanticEnv varName
  | .isValidPath => _root_.AgenticKernel.isValidPath semanticEnv varName
  -- Format predicates
  | .isValidBibtex => _root_.AgenticKernel.isValidBibtex semanticEnv varName
  | .isValidLatex => _root_.AgenticKernel.isValidLatex semanticEnv varName
  | .isValidJson => _root_.AgenticKernel.isValidJson semanticEnv varName
  | .isValidList => _root_.AgenticKernel.isValidList semanticEnv varName
  -- Resource predicates
  | .toolExists => _root_.AgenticKernel.toolExists semanticEnv varName
  | .moduleExists => _root_.AgenticKernel.moduleExists semanticEnv varName
  -- Schema predicates
  | .matchesJsonSchema schema =>
      ∃ j, semanticEnv.get varName = some (.vJson j) ∧ JsonMatchesSchema j schema
  | .isJsonWithFields fields => _root_.AgenticKernel.isJsonWithSchema semanticEnv varName fields
  -- String content predicates (for sentinel detection)
  | .containsSubstring substring => _root_.AgenticKernel.hasSubstring semanticEnv varName substring
  -- File existence (semantic marker - represents intent to create file)
  | .fileExistsAtPath => _root_.AgenticKernel.isNonEmptyString semanticEnv varName
  -- Task completion marker (semantic intent)
  | .taskCompleted => _root_.AgenticKernel.nameExists semanticEnv varName
  -- Custom (fallback to nameExists)
  | .custom _ => _root_.AgenticKernel.nameExists semanticEnv varName
  -- ★ ext — resolved via registry at runtime; at proof time falls back to nameExists
  | .ext _ => _root_.AgenticKernel.nameExists semanticEnv varName
  -- Propositional connectives
  | .predicateAnd p₁ p₂ => p₁.toProp semanticEnv varName ∧ p₂.toProp semanticEnv varName
  | .predicateOr p₁ p₂ => p₁.toProp semanticEnv varName ∨ p₂.toProp semanticEnv varName

/-- Decidable Bool checker. Mirrors toProp, dispatching to *Bool functions. -/
def PredicateType.checkBool
    (predType : PredicateType) (env : SemanticEnv) (varName : String) : Bool :=
  match predType with
  | .nameExists => nameExistsBool env varName
  | .isNonEmptyString => isNonEmptyStringBool env varName
  | .isNonEmptyList => isNonEmptyListBool env varName
  | .isInt => isIntBool env varName
  | .isValidURL => isValidURLBool env varName
  | .isValidFilePath => isValidFilePathBool env varName
  | .isValidPath => isValidPathBool env varName
  | .isValidBibtex => isValidBibtexBool env varName
  | .isValidLatex => isValidLatexBool env varName
  | .isValidJson => isValidJsonBool env varName
  | .isValidList => isValidListBool env varName
  | .toolExists => toolExistsBool env varName
  | .moduleExists => moduleExistsBool env varName
  | .matchesJsonSchema schema => matchesJsonSchemaBool env varName schema
  | .isJsonWithFields fields => isJsonWithSchemaBool env varName fields
  | .containsSubstring sub => hasSubstringBool env varName sub
  | .fileExistsAtPath => isNonEmptyStringBool env varName
  | .taskCompleted => nameExistsBool env varName
  | .custom _ => nameExistsBool env varName
  | .ext _ => nameExistsBool env varName
  | .predicateAnd p₁ p₂ => p₁.checkBool env varName && p₂.checkBool env varName
  | .predicateOr p₁ p₂ => p₁.checkBool env varName || p₂.checkBool env varName

end AgenticKernel
