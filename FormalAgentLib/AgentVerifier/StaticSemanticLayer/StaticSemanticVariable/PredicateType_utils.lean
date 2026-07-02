import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType_DecidableEq

namespace AgenticKernel

/-
## Section 1.4: Other instances that is needed for PredicateType, ArgValue, and PredicateKey
-/

/-
### Section 1.4.1: Normalization and semantic equality for PredicateType, ArgValue, and PredicateKey
-/


mutual
  /-- Normalize a PredicateType by normalizing all embedded JsonSchemas. -/
  partial def PredicateType.normalize : PredicateType → PredicateType
    | .matchesJsonSchema s => .matchesJsonSchema s.normalize
    | .ext k => .ext k.normalize
    | .predicateAnd p₁ p₂ => .predicateAnd p₁.normalize p₂.normalize
    | .predicateOr p₁ p₂ => .predicateOr p₁.normalize p₂.normalize
    | other => other

  /-- Normalize an ArgValue by normalizing all JsonSchema and PredicateType values. -/
  partial def ArgValue.normalize : ArgValue → ArgValue
    | .argJsonSchema s => .argJsonSchema s.normalize
    | .argJsonSchemas ss => .argJsonSchemas (ss.map JsonSchema.normalize)
    | .argPredType p => .argPredType p.normalize
    | .argPredTypes ps => .argPredTypes (ps.map PredicateType.normalize)
    | other => other

  /-- Normalize a PredicateKey by normalizing all its arguments. -/
  partial def PredicateKey.normalize : PredicateKey → PredicateKey
    | .makePredicateKey f n args => .makePredicateKey f n (args.map ArgValue.normalize)
end

/-- Semantic equality for PredicateKey: compares normalized versions. Use this when you need order-independent JsonSchema comparison. Regular == uses structural equality (order-sensitive). -/
def PredicateKey.semanticBEq (k₁ k₂ : PredicateKey) : Bool :=
  k₁.normalize.beqAux k₂.normalize

/-- Semantic equality for PredicateType: compares normalized versions. -/
def PredicateType.semanticBEq (p₁ p₂ : PredicateType) : Bool :=
  p₁.normalize.beqAux p₂.normalize

/-
### Section 1.4.2: PredicateKey constructions
Convenience functions for creating PredicateKeys. All constructors normalize JsonSchema values automatically.
-/

/-- Create a key with no arguments. -/
def PredicateKey.simple (family : String) (name : String) : PredicateKey :=
  .makePredicateKey family name []

/-- Create a key with a single JsonSchema argument (NORMALIZED). -/
def PredicateKey.withSchema (family : String) (name : String) (schema : JsonSchema)
    : PredicateKey :=
  .makePredicateKey family name [.argJsonSchema schema.normalize]

/-- Create a key with multiple JsonSchema arguments (NORMALIZED). -/
def PredicateKey.withSchemas (family : String) (name : String) (schemas : List JsonSchema)
    : PredicateKey :=
  .makePredicateKey family name [.argJsonSchemas (schemas.map JsonSchema.normalize)]

/-- Create a key with a single string argument. -/
def PredicateKey.withParam (family : String) (name : String) (param : String)
    : PredicateKey :=
  .makePredicateKey family name [.argStr param]

/-- ★ Create a key with a list of PredicateTypes (NORMALIZED, TRUE STRUCTURAL!).
    This is the key improvement: we store actual PredicateType, not a repr! -/
def PredicateKey.withPredTypes (family : String) (name : String) (preds : List PredicateType)
    : PredicateKey :=
  .makePredicateKey family name [.argPredTypes (preds.map PredicateType.normalize)]

end AgenticKernel
