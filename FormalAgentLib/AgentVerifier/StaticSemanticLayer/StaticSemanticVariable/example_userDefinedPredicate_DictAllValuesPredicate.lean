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
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.CompatibleCheck

namespace AgenticKernel

/-
# Section 6: User defined predicate example: DictAllValuesPredicate

This is the concert implementation of a user-defined predicate using the extensible predicate framework,
DictAllValuesPredicate expresses: "All values in a Dict satisfy predicate P" where P is a compound PredicateType (e.g., isValidJson ∧ matchesSchema(S)).
-/


/--
DictAllValuesPredicate checks that all values in a Json dict satisfy a given PredicateType. The `schema` field describes what each value must satisfy. The `dictVarName` field is for documentation
-/
structure DictAllValuesPredicate where
  /-- The predicates that each dict value must satisfy -/
  dictValuePredicates : List PredicateType
  /-- Optional string description -/
  dictVarName : String := ""
  deriving Repr, Inhabited, BEq, DecidableEq



namespace DictAllValuesPredicate
/-- Combine the value predicates into a single PredicateType using predicateAnd -/
def combinedValuePred
  (pred : DictAllValuesPredicate) : PredicateType :=
  match pred.dictValuePredicates with
  | [] => .nameExists
  | [p] => p
  | p :: ps => ps.foldl (fun acc q => .predicateAnd acc q) p

/-- Create the PredicateKey for this user-defined predicate. It uses withPredTypes with Predicate
★ Uses withPredTypes with PredicateType DIRECTLY for TRUE STRUCTURAL COMPARISON! No need for PredicateRepr - we store the actual PredicateType! All JsonSchema values are automatically normalized during construction, ensuring that semantically equivalent predicates (e.g., with different field orderings) produce identical keys and match correctly.-/
def toPredicateKey (pred : DictAllValuesPredicate) : PredicateKey :=
  PredicateKey.withPredTypes "user.parallel" "dictAllValues"
    pred.dictValuePredicates


/-- Prop interpretation: All values in the Dict at `varname` satifsy the combined predicate. We delegate to allDictValuesSatisfy from temp_SemanticPredicatesExtended.  -/
def toPropImplication (pred : DictAllValuesPredicate) (env : SemanticEnv) (varName : String) : Prop :=
  allDictValuesSatisfy
    (fun v => match v with
      | .vJson j => pred.combinedValuePred.toProp env varName
      | _ => False)
    env varName

/--
The list of standard predicate keys this predicate implies. It contains:
  - nameExists
  - isValidJson
  - matchesJsonSchema (.jObject [])
 -/
def impliedKeysImplication
  (_ : DictAllValuesPredicate) : List PredicateKey :=
  [StdPredicateKeys.nameExists, StdPredicateKeys.isValidJson, StdPredicateKeys.matchesJsonSchema (JsonSchema.jObject [])]


end DictAllValuesPredicate

/-- ExtendedPredicate instance for DictAllValuesPredicate. This makes DictAllValuesPredicate usable in the extensible predicate frameowrk. -/
instance : ExtendedPredicate DictAllValuesPredicate where
  toKey := DictAllValuesPredicate.toPredicateKey
  toProp := DictAllValuesPredicate.toPropImplication
  impliedKeys := DictAllValuesPredicate.impliedKeysImplication

/-- Create a DictAllValuesPredicate from a list of VariablePredicateRequirements. Useful when constructing from submodule return postconditions. -/
def makeDictValuesPred (returnPreds : List VariablePredicateRequirement) (varName : String := "")
    : DictAllValuesPredicate :=
  { dictValuePredicates := returnPreds.map (·.requiredPredicate)
    dictVarName := varName }

/-- Convert a DictAllValuesPredicate to a PredicateType.ext for use in nodes. -/
def dictAllValuesPredToExt (pred : DictAllValuesPredicate) : PredicateType :=
  .ext pred.toPredicateKey


/-- Create a VariablePredicateRequirement with a DictAllValuesPredicate. -/
def varDictAllValues (varName : String) (pred : DictAllValuesPredicate) : VariablePredicateRequirement :=
  ⟨varName, dictAllValuesPredToExt pred⟩

end AgenticKernel
