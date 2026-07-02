import Lean
import Mathlib
import AgentVerifier.StaticLayer
import AgentVerifier.StaticSemanticLayer.JsonSchema
import AgentVerifier.StaticSemanticLayer.StaticSemanticBasics
import AgentVerifier.StaticSemanticLayer.SemanticPredicates
import AgentVerifier.StaticSemanticLayer.temp_SemanticPredicatesExtended
import AgentVerifier.StaticSemanticLayer.StaticSemanticVariable.PredicateType


namespace AgenticKernel

/-
This file solves the DecidableEq properity of PredicateType, ArgValue, and PredicateKey
-/

/-
## Section 1.2: Soundness and reflexivity proofs for beqAux

Following the pattern from BaseTypes.lean, we prove:
1. beqAux_sound: beqAux a b = true → a = b
2. beqAux_refl: beqAux a a = true

These allow us to construct proper DecidableEq instances.
-/


/-
### Section 1.2.1: Reflexivity of beqAux
-/

mutual
  theorem PredicateType.beqAux_refl : ∀ (a : PredicateType), a.beqAux a = true := by
    intro a
    cases a
    case nameExists => rfl
    case isNonEmptyString => rfl
    case isNonEmptyList => rfl
    case isValidURL => rfl
    case isValidFilePath => rfl
    case isValidPath => rfl
    case isValidBibtex => rfl
    case isValidLatex => rfl
    case isValidJson => rfl
    case isValidList => rfl
    case toolExists => rfl
    case moduleExists => rfl
    case isInt => rfl
    case fileExistsAtPath => rfl
    case taskCompleted => rfl
    -- Constructors with simple data: use beq_self_eq_true
    case matchesJsonSchema s =>
      show (s == s) = true
      exact JsonSchema.beqAux_refl s
    case isJsonWithFields f =>
      show (f == f) = true
      induction f with
      | nil => rfl
      | cons x xs ih =>
        show (x == x && (xs == xs)) = true
        have h1 : (x == x) = true := JsonFieldSpec.beqAux_refl x
        rw [h1, ih]
        rfl
    case containsSubstring s =>
      show (s == s) = true
      exact beq_self_eq_true s
    case custom n =>
      show (n == n) = true
      exact beq_self_eq_true n
    -- Recursive constructors
    case ext k =>
      show PredicateKey.beqAux k k = true
      exact PredicateKey.beqAux_refl k
    case predicateAnd l r =>
      show (PredicateType.beqAux l l && PredicateType.beqAux r r) = true
      rw [PredicateType.beqAux_refl l, PredicateType.beqAux_refl r]
      rfl
    case predicateOr l r =>
      show (PredicateType.beqAux l l && PredicateType.beqAux r r) = true
      rw [PredicateType.beqAux_refl l, PredicateType.beqAux_refl r]
      rfl

  theorem PredicateType.beqListAux_refl :
    ∀ (xs : List PredicateType), PredicateType.beqListAux xs xs = true := by
    intro xs
    match xs with
    | [] => rfl
    | x::xs' =>
      show (PredicateType.beqAux x x && PredicateType.beqListAux xs' xs') = true
      rw [PredicateType.beqAux_refl x, PredicateType.beqListAux_refl xs']
      rfl


  theorem ArgValue.beqAux_refl : ∀ (a : ArgValue), a.beqAux a = true := by
    intro a
    cases a
    case argStr s =>
      show (s == s) = true
      exact beq_self_eq_true s
    case argInt i =>
      show (i == i) = true
      exact beq_self_eq_true i
    case argJsonSchema s =>
      show (s == s) = true
      exact JsonSchema.beqAux_refl s
    case argJsonSchemas ss =>
      show (ss == ss) = true
      induction ss with
      | nil => rfl
      | cons x xs ih =>
        show (x == x && (xs == xs)) = true
        have h1 : (x == x) = true := JsonSchema.beqAux_refl x
        rw [h1, ih]
        rfl
    case argPredType p =>
      show PredicateType.beqAux p p = true
      exact PredicateType.beqAux_refl p
    case argPredTypes ps =>
      show PredicateType.beqListAux ps ps = true
      exact PredicateType.beqListAux_refl ps

  theorem ArgValue.beqListAux_refl :
      ∀ (xs : List ArgValue), ArgValue.beqListAux xs xs = true := by
    intro xs
    match xs with
    | [] => rfl
    | x::xs' =>
      show (ArgValue.beqAux x x && ArgValue.beqListAux xs' xs') = true
      rw [ArgValue.beqAux_refl x, ArgValue.beqListAux_refl xs']
      rfl

  theorem PredicateKey.beqAux_refl : ∀ (a : PredicateKey), a.beqAux a = true := by
    intro a
    cases a with
    | makePredicateKey f n args =>
      unfold PredicateKey.beqAux
      simp only [beq_self_eq_true, Bool.true_and]
      exact ArgValue.beqListAux_refl args
end

/-
### Section 1.2.2: Soundness of beqAux
-/


mutual
  theorem PredicateType.beqAux_sound : ∀ (a b : PredicateType), a.beqAux b = true → a = b := by
    intro a b h
    cases a
    -- No-argument constructors: match → rfl, mismatch → Bool.noConfusion
    case nameExists => cases b <;> first | rfl | exact Bool.noConfusion h
    case isNonEmptyString => cases b <;> first | rfl | exact Bool.noConfusion h
    case isNonEmptyList => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidURL => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidFilePath => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidPath => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidBibtex => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidLatex => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidJson => cases b <;> first | rfl | exact Bool.noConfusion h
    case isValidList => cases b <;> first | rfl | exact Bool.noConfusion h
    case toolExists => cases b <;> first | rfl | exact Bool.noConfusion h
    case moduleExists => cases b <;> first | rfl | exact Bool.noConfusion h
    case isInt => cases b <;> first | rfl | exact Bool.noConfusion h
    case fileExistsAtPath => cases b <;> first | rfl | exact Bool.noConfusion h
    case taskCompleted => cases b <;> first | rfl | exact Bool.noConfusion h
    -- matchesJsonSchema: use JsonSchema.beqAux_sound
    case matchesJsonSchema s₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case matchesJsonSchema s₂ =>
        have h' : (s₁ == s₂) = true := h
        have heq := JsonSchema.beqAux_sound s₁ s₂ h'
        rw [heq]
    -- isJsonWithFields: inline list soundness via JsonFieldSpec.beqAux_sound
    case isJsonWithFields f₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case isJsonWithFields f₂ =>
        have h' : (f₁ == f₂) = true := h
        have heq : f₁ = f₂ := by
          induction f₁ generalizing f₂ with
          | nil =>
            cases f₂ with
            | nil => rfl
            | cons _ _ => exact Bool.noConfusion h'
          | cons x xs ih =>
            cases f₂ with
            | nil => exact Bool.noConfusion h'
            | cons y ys =>
              have h'' : (x == y && (xs == ys)) = true := h'
              simp only [Bool.and_eq_true] at h''
              have ⟨hx, hxs⟩ := h''
              have eqx := JsonFieldSpec.beqAux_sound x y hx
              have eqxs := ih ys hxs
              rw [eqx, eqxs]
              exact hxs
        rw [heq]
    -- containsSubstring: String has LawfulBEq
    case containsSubstring s₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case containsSubstring s₂ =>
        have h' : (s₁ == s₂) = true := h
        have heq : s₁ = s₂ := beq_iff_eq.mp h'
        rw [heq]
    -- custom: String has LawfulBEq
    case custom n₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case custom n₂ =>
        have h' : (n₁ == n₂) = true := h
        have heq : n₁ = n₂ := beq_iff_eq.mp h'
        rw [heq]
    -- ext: use PredicateKey.beqAux_sound (mutual recursion)
    case ext k₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case ext k₂ =>
        have h' : PredicateKey.beqAux k₁ k₂ = true := h
        have heq := PredicateKey.beqAux_sound k₁ k₂ h'
        rw [heq]
    -- predicateAnd: use PredicateType.beqAux_sound recursively
    case predicateAnd l₁ r₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case predicateAnd l₂ r₂ =>
        have h' : (PredicateType.beqAux l₁ l₂ && PredicateType.beqAux r₁ r₂) = true := h
        simp only [Bool.and_eq_true] at h'
        have ⟨hl, hr⟩ := h'
        have eql := PredicateType.beqAux_sound l₁ l₂ hl
        have eqr := PredicateType.beqAux_sound r₁ r₂ hr
        rw [eql, eqr]
    -- predicateOr: use PredicateType.beqAux_sound recursively
    case predicateOr l₁ r₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case predicateOr l₂ r₂ =>
        have h' : (PredicateType.beqAux l₁ l₂ && PredicateType.beqAux r₁ r₂) = true := h
        simp only [Bool.and_eq_true] at h'
        have ⟨hl, hr⟩ := h'
        have eql := PredicateType.beqAux_sound l₁ l₂ hl
        have eqr := PredicateType.beqAux_sound r₁ r₂ hr
        rw [eql, eqr]

  theorem PredicateType.beqListAux_sound :
      ∀ (xs ys : List PredicateType), PredicateType.beqListAux xs ys = true → xs = ys := by
    intro xs ys h
    match xs, ys with
    | [], [] => rfl
    | [], _::_ =>
      -- beqListAux [] (_::_) definitionally reduces to false via catch-all
      -- Use explicit type annotation (like `show` in beqAux_refl) to avoid unfold explosion
      have h' : false = true := h
      exact Bool.noConfusion h'
    | _::_, [] =>
      have h' : false = true := h
      exact Bool.noConfusion h'
    | x::xs', y::ys' =>
      -- beqListAux (x::xs') (y::ys') reduces to beqAux x y && beqListAux xs' ys'
      have h' : (PredicateType.beqAux x y && PredicateType.beqListAux xs' ys') = true := h
      simp only [Bool.and_eq_true] at h'
      have ⟨hHead, hTail⟩ := h'
      have eqHead := PredicateType.beqAux_sound x y hHead
      have eqTail := PredicateType.beqListAux_sound xs' ys' hTail
      rw [eqHead, eqTail]


  theorem ArgValue.beqAux_sound : ∀ (a b : ArgValue), a.beqAux b = true → a = b := by
    intro a b h
    cases a
    -- str: String has LawfulBEq
    case argStr s₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argStr s₂ =>
        have h' : (s₁ == s₂) = true := h
        have heq : s₁ = s₂ := beq_iff_eq.mp h'
        rw [heq]
    -- int: Int has LawfulBEq
    case argInt i₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argInt i₂ =>
        have h' : (i₁ == i₂) = true := h
        have heq : i₁ = i₂ := beq_iff_eq.mp h'
        rw [heq]
    -- schema: use JsonSchema.beqAux_sound
    case argJsonSchema s₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argJsonSchema s₂ =>
        have h' : (s₁ == s₂) = true := h
        have heq := JsonSchema.beqAux_sound s₁ s₂ h'
        rw [heq]
    -- schemas: inline list soundness via JsonSchema.beqAux_sound
    case argJsonSchemas ss₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argJsonSchemas ss₂ =>
        have h' : (ss₁ == ss₂) = true := h
        have heq : ss₁ = ss₂ := by
          induction ss₁ generalizing ss₂ with
          | nil =>
            cases ss₂ with
            | nil => rfl
            | cons _ _ => exact Bool.noConfusion h'
          | cons x xs ih =>
            cases ss₂ with
            | nil => exact Bool.noConfusion h'
            | cons y ys =>
              have h'' : (x == y && (xs == ys)) = true := h'
              simp only [Bool.and_eq_true] at h''
              have ⟨hx, hxs⟩ := h''
              have eqx := JsonSchema.beqAux_sound x y hx
              have eqxs := ih ys hxs
              rw [eqx, eqxs]
              exact hxs
        rw [heq]
    -- predType: use PredicateType.beqAux_sound (mutual recursion)
    case argPredType p₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argPredType p₂ =>
        have h' : PredicateType.beqAux p₁ p₂ = true := h
        have heq := PredicateType.beqAux_sound p₁ p₂ h'
        rw [heq]
    -- predTypeList: use PredicateType.beqListAux_sound (mutual recursion)
    case argPredTypes ps₁ =>
      cases b <;> (try exact Bool.noConfusion h)
      case argPredTypes ps₂ =>
        have h' : PredicateType.beqListAux ps₁ ps₂ = true := h
        have heq := PredicateType.beqListAux_sound ps₁ ps₂ h'
        rw [heq]

  theorem ArgValue.beqListAux_sound :
      ∀ (xs ys : List ArgValue), ArgValue.beqListAux xs ys = true → xs = ys := by
    intro xs ys h
    match xs, ys with
    | [], [] => rfl
    | [], _::_ =>
      have h' : false = true := h
      exact Bool.noConfusion h'
    | _::_, [] =>
      have h' : false = true := h
      exact Bool.noConfusion h'
    | x::xs', y::ys' =>
      have h' : (ArgValue.beqAux x y && ArgValue.beqListAux xs' ys') = true := h
      simp only [Bool.and_eq_true] at h'
      have ⟨hHead, hTail⟩ := h'
      have eqHead := ArgValue.beqAux_sound x y hHead
      have eqTail := ArgValue.beqListAux_sound xs' ys' hTail
      rw [eqHead, eqTail]

  theorem PredicateKey.beqAux_sound : ∀ (a b : PredicateKey), a.beqAux b = true → a = b := by
    intro a b h
    cases a with
    | makePredicateKey f1 n1 args1 =>
      cases b with
      | makePredicateKey f2 n2 args2 =>
        unfold PredicateKey.beqAux at h
        simp only [Bool.and_eq_true, beq_iff_eq] at h
        have ⟨⟨hf, hn⟩, hArgs⟩ := h
        have eqArgs := ArgValue.beqListAux_sound args1 args2 hArgs
        rw [hf, hn, eqArgs]
end

/-
## Section 1.3: Constructing DecidableEq instances
-/
instance : DecidableEq PredicateType := fun a b =>
  match h : a.beqAux b with
  | true  => isTrue (PredicateType.beqAux_sound a b h)
  | false => isFalse fun heq => by
      subst heq
      rw [PredicateType.beqAux_refl a] at h
      exact Bool.noConfusion h

instance : DecidableEq ArgValue := fun a b =>
  match h : a.beqAux b with
  | true  => isTrue (ArgValue.beqAux_sound a b h)
  | false => isFalse fun heq => by
      subst heq
      rw [ArgValue.beqAux_refl a] at h
      exact Bool.noConfusion h

instance : DecidableEq PredicateKey := fun a b =>
  match h : a.beqAux b with
  | true  => isTrue (PredicateKey.beqAux_sound a b h)
  | false => isFalse fun heq => by
      subst heq
      rw [PredicateKey.beqAux_refl a] at h
      exact Bool.noConfusion h

end AgenticKernel
